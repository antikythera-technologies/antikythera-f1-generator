"""
F1 Video Scheduler Service

Determines what content to generate based on:
- F1 calendar (race weekends, sprint weekends)
- Off-weeks (weekly recap content)
- Manual triggers

Content Schedule:
- Standard Race Weekend: 2 videos (post-FP2 Friday, post-Race Sunday)
- Sprint Race Weekend: 3 videos (post-FP2 Friday, post-Sprint Saturday, post-Race Sunday)
- Off-Week: 1 video (weekly recap on Friday 07:00 SAST)
"""

import logging
from datetime import datetime, timedelta, time
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Race, ScheduledJob, JobStatus, JobTriggerType, EpisodeType

logger = logging.getLogger(__name__)

# Timezone for scheduling
SAST = ZoneInfo("Africa/Johannesburg")

# Default trigger delays after session end
TRIGGER_DELAYS = {
    JobTriggerType.POST_FP2: timedelta(hours=1),      # 1 hour after FP2
    JobTriggerType.POST_SPRINT: timedelta(hours=1),   # 1 hour after sprint
    JobTriggerType.POST_RACE: timedelta(hours=2),     # 2 hours after race
    JobTriggerType.WEEKLY_RECAP: timedelta(hours=0),  # Fixed time (07:00 Friday)
}

# Off-week video release time
OFF_WEEK_RELEASE_TIME = time(7, 0, 0)  # 07:00 SAST


class SchedulerService:
    """Manages video generation scheduling based on F1 calendar."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def sync_calendar(self, season: int = None) -> dict:
        """
        Sync F1 calendar and create/update scheduled jobs.
        
        Returns summary of actions taken.
        """
        if season is None:
            season = datetime.now().year

        # Get all races for the season
        result = await self.session.execute(
            select(Race)
            .where(Race.season == season)
            .order_by(Race.round_number)
        )
        races = result.scalars().all()

        stats = {
            "races_checked": len(races),
            "jobs_created": 0,
            "jobs_updated": 0,
            "off_weeks_scheduled": 0,
        }

        for race in races:
            # Schedule race weekend jobs
            jobs_created = await self._schedule_race_jobs(race)
            stats["jobs_created"] += jobs_created

        # Schedule off-week jobs
        off_week_jobs = await self._schedule_off_week_jobs(races)
        stats["off_weeks_scheduled"] = off_week_jobs

        await self.session.commit()
        
        logger.info(f"Calendar sync complete: {stats}")
        return stats

    async def _schedule_race_jobs(self, race: Race) -> int:
        """Schedule video generation jobs for a race weekend."""
        jobs_created = 0

        # Always schedule post-FP2 if FP2 time is set
        if race.fp2_datetime:
            trigger_time = race.fp2_datetime + TRIGGER_DELAYS[JobTriggerType.POST_FP2]
            if await self._create_job_if_not_exists(
                race_id=race.id,
                trigger_type=JobTriggerType.POST_FP2,
                scheduled_for=trigger_time,
                description=f"Post-FP2 recap for {race.race_name}"
            ):
                jobs_created += 1

        # Schedule post-sprint if it's a sprint weekend
        if race.is_sprint_weekend and race.sprint_race_datetime:
            trigger_time = race.sprint_race_datetime + TRIGGER_DELAYS[JobTriggerType.POST_SPRINT]
            if await self._create_job_if_not_exists(
                race_id=race.id,
                trigger_type=JobTriggerType.POST_SPRINT,
                scheduled_for=trigger_time,
                description=f"Post-Sprint recap for {race.race_name}"
            ):
                jobs_created += 1

        # Always schedule post-race if race time is set
        if race.race_datetime:
            trigger_time = race.race_datetime + TRIGGER_DELAYS[JobTriggerType.POST_RACE]
            if await self._create_job_if_not_exists(
                race_id=race.id,
                trigger_type=JobTriggerType.POST_RACE,
                scheduled_for=trigger_time,
                description=f"Post-Race recap for {race.race_name}"
            ):
                jobs_created += 1

        return jobs_created

    async def _schedule_off_week_jobs(self, races: List[Race]) -> int:
        """Schedule weekly recap jobs for off-weeks (no race)."""
        jobs_created = 0
        
        # Find off-weeks by looking for gaps > 7 days between races
        for i, race in enumerate(races):
            if i == 0:
                continue
                
            prev_race = races[i - 1]
            gap_days = (race.race_date - prev_race.race_date).days
            
            # If gap is more than 8 days, there's an off-week
            if gap_days > 8:
                # Schedule for Friday(s) in the gap
                current_friday = self._next_friday(prev_race.race_date + timedelta(days=1))
                
                while current_friday < race.race_date - timedelta(days=3):
                    # Create off-week job for this Friday
                    scheduled_time = datetime.combine(
                        current_friday, 
                        OFF_WEEK_RELEASE_TIME,
                        tzinfo=SAST
                    )
                    
                    if await self._create_job_if_not_exists(
                        race_id=None,  # No race associated
                        trigger_type=JobTriggerType.WEEKLY_RECAP,
                        scheduled_for=scheduled_time,
                        description=f"Weekly F1 recap for {current_friday.strftime('%Y-%m-%d')}",
                        scrape_context={
                            "type": "off-week",
                            "focus": ["paddock_news", "transfers", "technical", "gossip"],
                            "date_range_days": 7,
                        }
                    ):
                        jobs_created += 1
                    
                    current_friday += timedelta(days=7)

        return jobs_created

    def _next_friday(self, from_date) -> datetime:
        """Get the next Friday from a given date."""
        days_ahead = 4 - from_date.weekday()  # Friday is weekday 4
        if days_ahead <= 0:
            days_ahead += 7
        return from_date + timedelta(days=days_ahead)

    async def _create_job_if_not_exists(
        self,
        race_id: Optional[int],
        trigger_type: JobTriggerType,
        scheduled_for: datetime,
        description: str,
        scrape_context: dict = None
    ) -> bool:
        """Create a scheduled job if one doesn't already exist."""
        
        # Check for existing job
        query = select(ScheduledJob).where(
            and_(
                ScheduledJob.race_id == race_id if race_id else ScheduledJob.race_id.is_(None),
                ScheduledJob.trigger_type == trigger_type,
                ScheduledJob.scheduled_for == scheduled_for,
            )
        )
        result = await self.session.execute(query)
        existing = result.scalar_one_or_none()
        
        if existing:
            return False
        
        # Set default scrape context based on trigger type
        if scrape_context is None:
            scrape_context = self._default_scrape_context(trigger_type)
        
        job = ScheduledJob(
            race_id=race_id,
            trigger_type=trigger_type,
            scheduled_for=scheduled_for,
            description=description,
            scrape_context=scrape_context,
        )
        self.session.add(job)
        
        logger.info(f"Created scheduled job: {trigger_type.value} @ {scheduled_for}")
        return True

    def _default_scrape_context(self, trigger_type: JobTriggerType) -> dict:
        """Get default scraping context for a trigger type."""
        contexts = {
            JobTriggerType.POST_FP2: {
                "type": "race-weekend",
                "focus": ["fp1_results", "fp2_results", "driver_quotes", "track_conditions"],
                "date_range_hours": 24,
            },
            JobTriggerType.POST_SPRINT: {
                "type": "race-weekend",
                "focus": ["sprint_results", "driver_battles", "team_drama", "championship_implications"],
                "date_range_hours": 12,
            },
            JobTriggerType.POST_RACE: {
                "type": "race-weekend",
                "focus": ["race_results", "key_moments", "penalties", "post_race_interviews", "championship_standings"],
                "date_range_hours": 6,
            },
            JobTriggerType.WEEKLY_RECAP: {
                "type": "off-week",
                "focus": ["paddock_news", "transfers", "technical_developments", "paddock_gossip"],
                "date_range_days": 7,
            },
        }
        return contexts.get(trigger_type, {})

    async def get_pending_jobs(self, limit: int = 10) -> List[ScheduledJob]:
        """Get jobs that are ready to run."""
        now = datetime.now(SAST)
        
        result = await self.session.execute(
            select(ScheduledJob)
            .where(
                and_(
                    ScheduledJob.status == JobStatus.SCHEDULED,
                    ScheduledJob.scheduled_for <= now,
                )
            )
            .order_by(ScheduledJob.scheduled_for)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_upcoming_jobs(self, days: int = 7) -> List[ScheduledJob]:
        """Get jobs scheduled for the next N days."""
        now = datetime.now(SAST)
        future = now + timedelta(days=days)
        
        result = await self.session.execute(
            select(ScheduledJob)
            .where(
                and_(
                    ScheduledJob.scheduled_for >= now,
                    ScheduledJob.scheduled_for <= future,
                )
            )
            .order_by(ScheduledJob.scheduled_for)
        )
        return result.scalars().all()

    async def mark_job_running(self, job: ScheduledJob) -> None:
        """Mark a job as running."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(SAST)
        await self.session.commit()

    async def mark_job_completed(self, job: ScheduledJob, episode_id: int) -> None:
        """Mark a job as completed."""
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(SAST)
        job.episode_id = episode_id
        await self.session.commit()

    async def mark_job_failed(self, job: ScheduledJob, error: str) -> None:
        """Mark a job as failed."""
        job.retry_count += 1
        job.error_message = error
        
        if job.retry_count >= job.max_retries:
            job.status = JobStatus.FAILED
        else:
            job.status = JobStatus.SCHEDULED  # Will retry
            # Reschedule for 30 minutes later
            job.scheduled_for = datetime.now(SAST) + timedelta(minutes=30)
        
        await self.session.commit()

    async def cancel_job(self, job_id: int) -> bool:
        """Cancel a scheduled job."""
        result = await self.session.execute(
            select(ScheduledJob).where(ScheduledJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if job and job.status == JobStatus.SCHEDULED:
            job.status = JobStatus.CANCELLED
            await self.session.commit()
            return True
        return False

    def map_trigger_to_episode_type(self, trigger_type: JobTriggerType) -> EpisodeType:
        """Map a job trigger type to an episode type."""
        mapping = {
            JobTriggerType.POST_FP2: EpisodeType.POST_FP2,
            JobTriggerType.POST_SPRINT: EpisodeType.POST_SPRINT,
            JobTriggerType.POST_RACE: EpisodeType.POST_RACE,
            JobTriggerType.WEEKLY_RECAP: EpisodeType.WEEKLY_RECAP,
            JobTriggerType.MANUAL: EpisodeType.POST_RACE,  # Default for manual
        }
        return mapping.get(trigger_type, EpisodeType.POST_RACE)
