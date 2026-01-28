"""Scene schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.scene import SceneStatus


class SceneBase(BaseModel):
    """Base scene schema."""
    scene_number: int
    dialogue: Optional[str] = None
    action_description: Optional[str] = None
    audio_description: Optional[str] = None


class SceneResponse(BaseModel):
    """Schema for scene response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    scene_number: int
    character_id: Optional[int]
    status: SceneStatus
    dialogue: Optional[str]
    action_description: Optional[str]
    video_clip_path: Optional[str]
    duration_seconds: Decimal
    generation_time_ms: Optional[int]
    retry_count: int
    last_error: Optional[str]
    created_at: datetime


class SceneDetailResponse(SceneResponse):
    """Schema for scene detail response with prompts."""
    script_prompt: Optional[str]
    script_response: Optional[str]
    ovi_prompt: Optional[str]
    audio_description: Optional[str]
    source_image_path: Optional[str]
    character_image_id: Optional[int]
    generation_started_at: Optional[datetime]
    generation_completed_at: Optional[datetime]
