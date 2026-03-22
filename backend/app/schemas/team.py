"""Team schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TeamBase(BaseModel):
    """Base team schema."""

    name: str
    short_name: str
    season: int = 2026
    livery_description: Optional[str] = None
    car_description: Optional[str] = None
    overalls_description: Optional[str] = None
    primary_colour: Optional[str] = None
    secondary_colour: Optional[str] = None
    accent_colour: Optional[str] = None
    principal_name: Optional[str] = None
    engine_supplier: Optional[str] = None
    constructor_name: Optional[str] = None
    headquarters: Optional[str] = None


class TeamCreate(TeamBase):
    """Schema for creating a team."""

    pass


class TeamUpdate(BaseModel):
    """Schema for updating a team."""

    name: Optional[str] = None
    short_name: Optional[str] = None
    season: Optional[int] = None
    livery_description: Optional[str] = None
    car_description: Optional[str] = None
    overalls_description: Optional[str] = None
    primary_colour: Optional[str] = None
    secondary_colour: Optional[str] = None
    accent_colour: Optional[str] = None
    principal_name: Optional[str] = None
    engine_supplier: Optional[str] = None
    constructor_name: Optional[str] = None
    headquarters: Optional[str] = None
    is_active: Optional[bool] = None


class TeamResponse(TeamBase):
    """Schema for team response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
