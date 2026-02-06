"""Running gag schemas."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GagBase(BaseModel):
    """Base gag schema."""
    title: str
    description: str
    category: str = "running_joke"
    primary_character_id: Optional[int] = None
    secondary_character_id: Optional[int] = None
    setup: Optional[str] = None
    punchline: Optional[str] = None
    variations: Optional[str] = None
    context_needed: Optional[str] = None
    origin_race: Optional[str] = None
    origin_date: Optional[date] = None
    origin_description: Optional[str] = None
    humor_rating: int = 5
    cooldown_races: int = 2
    max_uses: Optional[int] = None
    tags: Optional[list[str]] = None


class GagCreate(GagBase):
    """Schema for creating a gag."""
    pass


class GagUpdate(BaseModel):
    """Schema for updating a gag."""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    primary_character_id: Optional[int] = None
    secondary_character_id: Optional[int] = None
    setup: Optional[str] = None
    punchline: Optional[str] = None
    variations: Optional[str] = None
    context_needed: Optional[str] = None
    origin_race: Optional[str] = None
    origin_date: Optional[date] = None
    origin_description: Optional[str] = None
    status: Optional[str] = None
    humor_rating: Optional[int] = None
    cooldown_races: Optional[int] = None
    max_uses: Optional[int] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None


class GagUsageCreate(BaseModel):
    """Schema for recording gag usage."""
    gag_id: int
    episode_id: int
    scene_id: Optional[int] = None
    usage_context: Optional[str] = None
    dialogue_excerpt: Optional[str] = None
    effectiveness_rating: Optional[int] = None


class GagUsageResponse(BaseModel):
    """Schema for gag usage response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    gag_id: int
    episode_id: int
    scene_id: Optional[int]
    usage_context: Optional[str]
    dialogue_excerpt: Optional[str]
    effectiveness_rating: Optional[int]
    created_at: datetime


class GagResponse(GagBase):
    """Schema for gag response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    times_used: int
    audience_familiarity: int
    last_used_at: Optional[datetime]
    last_used_in_race: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    usages: list[GagUsageResponse] = []
