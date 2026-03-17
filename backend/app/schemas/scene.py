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
    character_name: Optional[str] = None
    status: SceneStatus
    dialogue: Optional[str]
    action_description: Optional[str]
    audio_description: Optional[str] = None
    source_image_path: Optional[str] = None
    start_frame_path: Optional[str] = None
    video_clip_path: Optional[str]
    video_generator: Optional[str] = None
    video_prompt: Optional[str] = None
    start_frame_prompt: Optional[str] = None
    camera_direction: Optional[str] = None
    duration_seconds: Decimal
    image_cost_usd: Optional[Decimal] = None
    video_cost_usd: Optional[Decimal] = None
    image_backend: Optional[str] = None
    scene_type: Optional[str] = None
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

    # Dual-frame prompts
    start_frame_prompt: Optional[str] = None
    end_frame_prompt: Optional[str] = None
    start_frame_prompt_final: Optional[str] = None
    end_frame_prompt_final: Optional[str] = None

    # Dual-frame outputs
    start_frame_path: Optional[str] = None
    end_frame_path: Optional[str] = None

    # Video generation
    video_prompt: Optional[str] = None
    video_generator: Optional[str] = None
    camera_direction: Optional[str] = None

    # Audio
    audio_clip_path: Optional[str] = None


class ScenePromptUpdate(BaseModel):
    """Schema for updating scene prompts."""
    start_frame_prompt: Optional[str] = None
    end_frame_prompt: Optional[str] = None
    camera_direction: Optional[str] = None
    video_prompt: Optional[str] = None
