"""Scene model."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SceneStatus(str, enum.Enum):
    """Scene generation status."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class Scene(Base):
    """Individual 5-second scenes with full prompt traceability."""
    
    __tablename__ = "episode_scenes"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-24

    # Character info
    character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id"))
    character_image_id: Mapped[Optional[int]] = mapped_column(ForeignKey("character_images.id"))

    # Prompts (for traceability)
    script_prompt: Mapped[Optional[str]] = mapped_column(Text)
    script_response: Mapped[Optional[str]] = mapped_column(Text)
    ovi_prompt: Mapped[Optional[str]] = mapped_column(Text)  # Legacy: single-frame prompt

    # Dual-frame prompts (LLM-generated scene descriptions)
    start_frame_prompt: Mapped[Optional[str]] = mapped_column(Text)
    end_frame_prompt: Mapped[Optional[str]] = mapped_column(Text)

    # Final enriched prompts (actually sent to ComfyUI)
    start_frame_prompt_final: Mapped[Optional[str]] = mapped_column(Text)
    end_frame_prompt_final: Mapped[Optional[str]] = mapped_column(Text)

    # Video generation prompts
    video_prompt: Mapped[Optional[str]] = mapped_column(Text)
    camera_direction: Mapped[Optional[str]] = mapped_column(Text)

    # Content
    dialogue: Mapped[Optional[str]] = mapped_column(Text)
    action_description: Mapped[Optional[str]] = mapped_column(Text)
    audio_description: Mapped[Optional[str]] = mapped_column(Text)

    # Output
    status: Mapped[SceneStatus] = mapped_column(
        Enum(SceneStatus, name="scene_status", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=SceneStatus.PENDING,
    )
    source_image_path: Mapped[Optional[str]] = mapped_column(String(500))  # Legacy: single source image
    start_frame_path: Mapped[Optional[str]] = mapped_column(String(500))
    end_frame_path: Mapped[Optional[str]] = mapped_column(String(500))
    video_clip_path: Mapped[Optional[str]] = mapped_column(String(500))
    audio_clip_path: Mapped[Optional[str]] = mapped_column(String(500))
    video_generator: Mapped[Optional[str]] = mapped_column(String(50))  # "ovi" or "ltx23"
    duration_seconds: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=5.0)
    image_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    video_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    image_backend: Mapped[Optional[str]] = mapped_column(String(50))
    scene_type: Mapped[Optional[str]] = mapped_column(String(50))  # TALKING_HEAD, ACTION_REPLAY, etc.

    # Generation metadata (for auditing)
    face_reference_url: Mapped[Optional[str]] = mapped_column(String(500))
    lora_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    instant_character_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    regeneration_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Quality validation
    validation_status: Mapped[Optional[str]] = mapped_column(String(20))  # passed, failed, skipped
    validation_issues: Mapped[Optional[str]] = mapped_column(Text)  # JSON string of issues

    # Timing
    generation_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    generation_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    generation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # Error handling
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    episode: Mapped["Episode"] = relationship("Episode", back_populates="scenes")
    character: Mapped[Optional["Character"]] = relationship("Character", back_populates="scenes")

    @property
    def character_name(self) -> str | None:
        """Character display name for API responses."""
        if self.character:
            return self.character.display_name or self.character.name
        return None
    character_image: Mapped[Optional["CharacterImage"]] = relationship("CharacterImage", back_populates="scenes")
    logs: Mapped[list["GenerationLog"]] = relationship("GenerationLog", back_populates="scene", cascade="all, delete-orphan")
    api_usage: Mapped[list["APIUsage"]] = relationship("APIUsage", back_populates="scene", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("episode_id", "scene_number", name="episode_scenes_episode_id_scene_number_key"),
    )

    def __repr__(self) -> str:
        return f"<Scene {self.scene_number} of Episode {self.episode_id}>"


# Import to avoid circular imports
from app.models.episode import Episode
from app.models.character import Character, CharacterImage
from app.models.logs import GenerationLog, APIUsage
