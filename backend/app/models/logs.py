"""Logging and tracking models."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LogLevel(str, enum.Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class LogComponent(str, enum.Enum):
    """Pipeline components for logging."""
    TRIGGER = "trigger"
    SCRIPT = "script"
    IMAGE = "image"
    VIDEO = "video"
    STITCH = "stitch"
    UPLOAD = "upload"
    CLEANUP = "cleanup"


class APIProvider(str, enum.Enum):
    """External API providers."""
    ANTHROPIC = "anthropic"
    OVI = "ovi"
    YOUTUBE = "youtube"
    MINIO = "minio"


class GenerationLog(Base):
    """Comprehensive logging for debugging and observability."""
    
    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))

    level: Mapped[LogLevel] = mapped_column(Enum(LogLevel), nullable=False)
    component: Mapped[LogComponent] = mapped_column(Enum(LogComponent), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    episode: Mapped[Optional["Episode"]] = relationship("Episode", back_populates="logs")
    scene: Mapped[Optional["Scene"]] = relationship("Scene", back_populates="logs")

    def __repr__(self) -> str:
        return f"<GenerationLog {self.level.value}: {self.message[:50]}>"


class APIUsage(Base):
    """External API call tracking for cost analysis."""
    
    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))

    provider: Mapped[APIProvider] = mapped_column(Enum(APIProvider), nullable=False)
    endpoint: Mapped[Optional[str]] = mapped_column(String(255))

    # Request details
    request_payload_size: Mapped[Optional[int]] = mapped_column(Integer)

    # Response details
    response_status: Mapped[Optional[int]] = mapped_column(Integer)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # Cost tracking (Anthropic specific)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    episode: Mapped[Optional["Episode"]] = relationship("Episode", back_populates="api_usage")
    scene: Mapped[Optional["Scene"]] = relationship("Scene", back_populates="api_usage")

    def __repr__(self) -> str:
        return f"<APIUsage {self.provider.value} - {self.endpoint}>"


class CleanupLog(Base):
    """Storage cleanup audit trail."""
    
    __tablename__ = "cleanup_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[Optional[int]] = mapped_column(ForeignKey("races.id"))
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id"))

    files_deleted: Mapped[Optional[int]] = mapped_column(Integer)
    bytes_freed: Mapped[Optional[int]] = mapped_column(BigInteger)
    cleanup_type: Mapped[Optional[str]] = mapped_column(String(50))  # scene_images, video_clips, both

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<CleanupLog {self.id}: {self.files_deleted} files>"


# Import to avoid circular imports
from app.models.episode import Episode
from app.models.scene import Scene
