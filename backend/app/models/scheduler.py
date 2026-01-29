"""Scheduler models for job tracking."""

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    """Scheduled job status."""
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobTriggerType(str, enum.Enum):
    """What triggers this job."""
    POST_FP2 = "post-fp2"
    POST_SPRINT = "post-sprint"
    POST_RACE = "post-race"
    WEEKLY_RECAP = "weekly-recap"
    MANUAL = "manual"


class ScheduledJob(Base):
    """Scheduled video generation jobs with trigger timing."""
    
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[Optional[int]] = mapped_column(ForeignKey("races.id"))
    
    # Job configuration
    trigger_type: Mapped[JobTriggerType] = mapped_column(Enum(JobTriggerType), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    # Execution tracking
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.SCHEDULED)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Result tracking
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    
    # Metadata
    scrape_context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    race: Mapped[Optional["Race"]] = relationship("Race", backref="scheduled_jobs")
    episode: Mapped[Optional["Episode"]] = relationship("Episode", backref="scheduled_job")

    def __repr__(self) -> str:
        return f"<ScheduledJob {self.id}: {self.trigger_type.value} @ {self.scheduled_for}>"


# Import to avoid circular imports
from app.models.race import Race
from app.models.episode import Episode
