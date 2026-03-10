"""Storyline schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlotPoint(BaseModel):
    """A single plot beat in a storyline."""
    title: str
    description: str
    completed: bool = False


class StorylineBase(BaseModel):
    """Base storyline schema."""
    title: str
    description: str
    storyline_type: str = "rivalry"
    priority: int = Field(default=5, ge=1, le=10)
    start_race_id: Optional[int] = None
    end_race_id: Optional[int] = None
    plot_points: Optional[list[dict[str, Any]]] = None
    comedy_notes: Optional[str] = None
    tags: Optional[list[str]] = None


class StorylineCreate(StorylineBase):
    """Schema for creating a storyline."""
    character_ids: list[int] = []


class StorylineUpdate(BaseModel):
    """Schema for updating a storyline."""
    title: Optional[str] = None
    description: Optional[str] = None
    storyline_type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=10)
    start_race_id: Optional[int] = None
    end_race_id: Optional[int] = None
    plot_points: Optional[list[dict[str, Any]]] = None
    current_beat: Optional[int] = None
    comedy_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    character_ids: Optional[list[int]] = None
    is_active: Optional[bool] = None


class StorylineEpisodeCreate(BaseModel):
    """Schema for linking a storyline to an episode."""
    episode_id: int
    beat_used: Optional[int] = None
    scene_numbers: Optional[list[int]] = None
    usage_notes: Optional[str] = None


class StorylineEpisodeResponse(BaseModel):
    """Schema for storyline-episode link response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    storyline_id: int
    episode_id: int
    beat_used: Optional[int]
    scene_numbers: Optional[list[int]]
    usage_notes: Optional[str]
    created_at: datetime


class CharacterBrief(BaseModel):
    """Minimal character info for storyline responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    team: Optional[str] = None


class StorylineResponse(StorylineBase):
    """Schema for storyline response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    current_beat: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    characters: list[CharacterBrief] = []
    episode_links: list[StorylineEpisodeResponse] = []
    episode_count: Optional[int] = None


class StorylineListResponse(BaseModel):
    """Schema for storyline list item (lighter than full response)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    storyline_type: str
    status: str
    priority: int
    current_beat: int
    plot_points: Optional[list[dict[str, Any]]] = None
    comedy_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    characters: list[CharacterBrief] = []
    episode_count: Optional[int] = None
