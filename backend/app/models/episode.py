"""Episode model."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EpisodeType(str, enum.Enum):
    """Type of episode relative to race weekend session."""
    PRE_RACE = "pre-race"      # Legacy: kept for backwards compatibility
    POST_RACE = "post-race"    # Main race recap (Sunday)
    POST_FP2 = "post-fp2"      # Friday practice recap
    POST_SPRINT = "post-sprint"  # Sprint race recap (Saturday)
    WEEKLY_RECAP = "weekly-recap"  # Off-week news compilation


class EpisodeStatus(str, enum.Enum):
    """Episode generation status."""
    PENDING = "pending"
    GENERATING = "generating"
    STITCHING = "stitching"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"


class Episode(Base):
    """Generated video episodes with full lifecycle tracking."""
    
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[Optional[int]] = mapped_column(ForeignKey("races.id"))
    episode_type: Mapped[EpisodeType] = mapped_column(
        Enum(EpisodeType, name="episode_type", create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus, name="episode_status", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=EpisodeStatus.PENDING,
    )

    # Timing
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    generation_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    generation_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    upload_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Output
    final_video_path: Mapped[Optional[str]] = mapped_column(String(500))
    youtube_video_id: Mapped[Optional[str]] = mapped_column(String(50))
    youtube_url: Mapped[Optional[str]] = mapped_column(String(255))

    # Metrics
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    scene_count: Mapped[int] = mapped_column(Integer, default=24)
    generation_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    # Cost tracking
    anthropic_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    anthropic_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    ovi_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)

    # Error handling
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    race: Mapped[Optional["Race"]] = relationship("Race", back_populates="episodes")
    scenes: Mapped[List["Scene"]] = relationship("Scene", back_populates="episode", cascade="all, delete-orphan")
    logs: Mapped[List["GenerationLog"]] = relationship("GenerationLog", back_populates="episode", cascade="all, delete-orphan")
    api_usage: Mapped[List["APIUsage"]] = relationship("APIUsage", back_populates="episode", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Episode {self.id}: {self.title}>"


# Import to avoid circular imports
from app.models.race import Race
from app.models.scene import Scene
from app.models.logs import GenerationLog, APIUsage
