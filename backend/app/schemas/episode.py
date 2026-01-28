"""Episode schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.episode import EpisodeStatus, EpisodeType
from app.schemas.race import RaceResponse
from app.schemas.scene import SceneResponse


class EpisodeBase(BaseModel):
    """Base episode schema."""
    episode_type: EpisodeType
    title: str
    description: Optional[str] = None


class EpisodeCreate(EpisodeBase):
    """Schema for creating an episode."""
    race_id: Optional[int] = None


class GenerateEpisodeRequest(BaseModel):
    """Schema for episode generation request."""
    race_id: int
    episode_type: EpisodeType
    force: bool = False


class GenerateEpisodeResponse(BaseModel):
    """Schema for episode generation response."""
    episode_id: int
    status: EpisodeStatus
    estimated_completion_minutes: int


class RetryRequest(BaseModel):
    """Schema for retry request."""
    scene_ids: list[int] = []


class EpisodeResponse(BaseModel):
    """Schema for episode list response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    race_id: Optional[int]
    race_name: Optional[str] = None
    episode_type: EpisodeType
    title: str
    status: EpisodeStatus
    youtube_url: Optional[str]
    total_cost_usd: Decimal
    created_at: datetime
    published_at: Optional[datetime]


class EpisodeDetailResponse(BaseModel):
    """Schema for episode detail response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    race: Optional[RaceResponse]
    episode_type: EpisodeType
    title: str
    description: Optional[str]
    status: EpisodeStatus

    # Timing
    triggered_at: datetime
    generation_started_at: Optional[datetime]
    generation_completed_at: Optional[datetime]
    published_at: Optional[datetime]

    # Output
    final_video_path: Optional[str]
    youtube_video_id: Optional[str]
    youtube_url: Optional[str]

    # Metrics
    duration_seconds: Optional[int]
    scene_count: int
    generation_time_seconds: Optional[int]

    # Costs
    anthropic_tokens_used: int
    anthropic_cost_usd: Decimal
    ovi_calls: int
    total_cost_usd: Decimal

    # Scenes
    scenes: list[SceneResponse] = []
