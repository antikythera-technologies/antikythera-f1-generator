"""Race schemas."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RaceBase(BaseModel):
    """Base race schema."""
    season: int
    round_number: int
    race_name: str
    circuit_name: Optional[str] = None
    country: Optional[str] = None
    race_date: date


class RaceCreate(RaceBase):
    """Schema for creating a race."""
    fp1_datetime: Optional[datetime] = None
    fp2_datetime: Optional[datetime] = None
    fp3_datetime: Optional[datetime] = None
    qualifying_datetime: Optional[datetime] = None
    race_datetime: Optional[datetime] = None
    # Sprint weekend fields
    is_sprint_weekend: bool = False
    sprint_qualifying_datetime: Optional[datetime] = None
    sprint_race_datetime: Optional[datetime] = None


class RaceResponse(RaceBase):
    """Schema for race response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    fp1_datetime: Optional[datetime]
    fp2_datetime: Optional[datetime]
    fp3_datetime: Optional[datetime]
    qualifying_datetime: Optional[datetime]
    race_datetime: Optional[datetime]
    # Sprint weekend fields
    is_sprint_weekend: bool
    sprint_qualifying_datetime: Optional[datetime]
    sprint_race_datetime: Optional[datetime]
    created_at: datetime
