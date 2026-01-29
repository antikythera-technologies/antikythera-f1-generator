"""Scheduler schemas for API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.scheduler import JobStatus, JobTriggerType


class ScheduledJobBase(BaseModel):
    """Base scheduled job schema."""
    trigger_type: JobTriggerType
    scheduled_for: datetime
    description: Optional[str] = None
    scrape_context: Optional[dict[str, Any]] = None


class ScheduledJobCreate(ScheduledJobBase):
    """Schema for creating a scheduled job."""
    race_id: Optional[int] = None


class ScheduledJobUpdate(BaseModel):
    """Schema for updating a scheduled job."""
    scheduled_for: Optional[datetime] = None
    description: Optional[str] = None
    status: Optional[JobStatus] = None


class ScheduledJobResponse(ScheduledJobBase):
    """Schema for scheduled job response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    race_id: Optional[int]
    status: JobStatus
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    episode_id: Optional[int]
    error_message: Optional[str]
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime


class ScheduledJobWithRace(ScheduledJobResponse):
    """Scheduled job with race details."""
    race_name: Optional[str] = None
    race_country: Optional[str] = None
    is_sprint_weekend: Optional[bool] = None


class CalendarSyncResponse(BaseModel):
    """Response from calendar sync operation."""
    races_checked: int
    jobs_created: int
    jobs_updated: int
    off_weeks_scheduled: int


class UpcomingJobsResponse(BaseModel):
    """Response listing upcoming jobs."""
    jobs: list[ScheduledJobWithRace]
    total: int
