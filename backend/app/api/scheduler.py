"""Scheduler API endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ScheduledJob, JobStatus
from app.services import SchedulerService
from app.schemas.scheduler import (
    ScheduledJobCreate,
    ScheduledJobResponse,
    ScheduledJobWithRace,
    ScheduledJobUpdate,
    CalendarSyncResponse,
    UpcomingJobsResponse,
)

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


@router.post("/sync", response_model=CalendarSyncResponse)
async def sync_calendar(
    season: int = Query(default=None, description="Season year (defaults to current)"),
    session: AsyncSession = Depends(get_db),
):
    """
    Sync F1 calendar and create/update scheduled jobs.
    
    Scans the races table and creates appropriate jobs for:
    - Post-FP2 videos (Friday)
    - Post-Sprint videos (Saturday, sprint weekends only)
    - Post-Race videos (Sunday)
    - Weekly recap videos (off-weeks)
    """
    service = SchedulerService(session)
    result = await service.sync_calendar(season)
    return result


@router.get("/jobs", response_model=List[ScheduledJobResponse])
async def list_jobs(
    status: Optional[JobStatus] = Query(default=None),
    limit: int = Query(default=50, le=100),
    session: AsyncSession = Depends(get_db),
):
    """List scheduled jobs with optional status filter."""
    from sqlalchemy import select, desc
    
    query = select(ScheduledJob)
    if status:
        query = query.where(ScheduledJob.status == status)
    query = query.order_by(desc(ScheduledJob.scheduled_for)).limit(limit)
    
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/jobs/upcoming", response_model=UpcomingJobsResponse)
async def get_upcoming_jobs(
    days: int = Query(default=7, le=30),
    session: AsyncSession = Depends(get_db),
):
    """Get jobs scheduled for the next N days."""
    service = SchedulerService(session)
    jobs = await service.get_upcoming_jobs(days)
    
    # Enrich with race data
    enriched = []
    for job in jobs:
        job_dict = ScheduledJobWithRace.model_validate(job)
        if job.race:
            job_dict.race_name = job.race.race_name
            job_dict.race_country = job.race.country
            job_dict.is_sprint_weekend = job.race.is_sprint_weekend
        enriched.append(job_dict)
    
    return UpcomingJobsResponse(jobs=enriched, total=len(enriched))


@router.get("/jobs/pending", response_model=List[ScheduledJobResponse])
async def get_pending_jobs(
    limit: int = Query(default=10, le=50),
    session: AsyncSession = Depends(get_db),
):
    """Get jobs that are ready to run (scheduled time has passed)."""
    service = SchedulerService(session)
    jobs = await service.get_pending_jobs(limit)
    return jobs


@router.get("/jobs/{job_id}", response_model=ScheduledJobWithRace)
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Get a specific scheduled job."""
    from sqlalchemy import select
    
    result = await session.execute(
        select(ScheduledJob).where(ScheduledJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    response = ScheduledJobWithRace.model_validate(job)
    if job.race:
        response.race_name = job.race.race_name
        response.race_country = job.race.country
        response.is_sprint_weekend = job.race.is_sprint_weekend
    
    return response


@router.post("/jobs", response_model=ScheduledJobResponse)
async def create_job(
    job_data: ScheduledJobCreate,
    session: AsyncSession = Depends(get_db),
):
    """Manually create a scheduled job."""
    job = ScheduledJob(**job_data.model_dump())
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.patch("/jobs/{job_id}", response_model=ScheduledJobResponse)
async def update_job(
    job_id: int,
    job_update: ScheduledJobUpdate,
    session: AsyncSession = Depends(get_db),
):
    """Update a scheduled job."""
    from sqlalchemy import select
    
    result = await session.execute(
        select(ScheduledJob).where(ScheduledJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    update_data = job_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(job, key, value)
    
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=ScheduledJobResponse)
async def cancel_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Cancel a scheduled job."""
    service = SchedulerService(session)
    success = await service.cancel_job(job_id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Job cannot be cancelled (already running or completed)"
        )
    
    # Return updated job
    from sqlalchemy import select
    result = await session.execute(
        select(ScheduledJob).where(ScheduledJob.id == job_id)
    )
    return result.scalar_one()


@router.post("/jobs/{job_id}/run")
async def trigger_job(
    job_id: int,
    session: AsyncSession = Depends(get_db),
):
    """
    Manually trigger a scheduled job to run now.
    
    This bypasses the scheduled time and immediately starts
    the video generation pipeline.
    """
    from sqlalchemy import select
    
    result = await session.execute(
        select(ScheduledJob).where(ScheduledJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in [JobStatus.SCHEDULED, JobStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail=f"Job cannot be triggered (status: {job.status.value})"
        )
    
    service = SchedulerService(session)
    await service.mark_job_running(job)
    
    # TODO: Actually trigger the pipeline here
    # For now, just return that it's been marked as running
    
    return {
        "status": "triggered",
        "job_id": job_id,
        "message": "Job marked as running. Pipeline will process it."
    }
