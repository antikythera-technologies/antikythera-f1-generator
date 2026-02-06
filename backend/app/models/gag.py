"""Running gags and character history models."""

import enum
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GagStatus(str, enum.Enum):
    ACTIVE = "active"
    COOLING_DOWN = "cooling_down"
    EXHAUSTED = "exhausted"
    RETIRED = "retired"


class GagCategory(str, enum.Enum):
    PERSONALITY_TRAIT = "personality_trait"
    INCIDENT = "incident"
    RIVALRY = "rivalry"
    CATCHPHRASE = "catchphrase"
    RUNNING_JOKE = "running_joke"
    RELATIONSHIP = "relationship"
    LEGACY = "legacy"


class RunningGag(Base):
    """Running jokes and character gags that carry across races."""

    __tablename__ = "running_gags"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Core definition
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[GagCategory] = mapped_column(
        Enum(GagCategory, name="gag_category", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=GagCategory.RUNNING_JOKE,
    )

    # Character associations
    primary_character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id"))
    secondary_character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id"))

    # Comedy details
    setup: Mapped[Optional[str]] = mapped_column(Text)
    punchline: Mapped[Optional[str]] = mapped_column(Text)
    variations: Mapped[Optional[str]] = mapped_column(Text)
    context_needed: Mapped[Optional[str]] = mapped_column(Text)

    # Origin
    origin_race: Mapped[Optional[str]] = mapped_column(String(100))
    origin_episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id"))
    origin_date: Mapped[Optional[date]] = mapped_column(Date)
    origin_description: Mapped[Optional[str]] = mapped_column(Text)

    # Usage tracking
    status: Mapped[GagStatus] = mapped_column(
        Enum(GagStatus, name="gag_status", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=GagStatus.ACTIVE,
    )
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer)
    cooldown_races: Mapped[int] = mapped_column(Integer, default=2)
    last_used_in_episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_used_in_race: Mapped[Optional[str]] = mapped_column(String(100))

    # Relevance
    humor_rating: Mapped[int] = mapped_column(Integer, default=5)
    audience_familiarity: Mapped[int] = mapped_column(Integer, default=1)

    # Metadata
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    primary_character: Mapped[Optional["Character"]] = relationship(
        "Character", foreign_keys=[primary_character_id], backref="primary_gags"
    )
    secondary_character: Mapped[Optional["Character"]] = relationship(
        "Character", foreign_keys=[secondary_character_id], backref="secondary_gags"
    )
    origin_episode: Mapped[Optional["Episode"]] = relationship(
        "Episode", foreign_keys=[origin_episode_id], backref="originated_gags"
    )
    last_used_episode: Mapped[Optional["Episode"]] = relationship(
        "Episode", foreign_keys=[last_used_in_episode_id]
    )
    usages: Mapped[List["GagUsage"]] = relationship("GagUsage", back_populates="gag", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<RunningGag {self.id}: {self.title}>"


class GagUsage(Base):
    """Tracks every time a gag is used in an episode."""

    __tablename__ = "gag_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    gag_id: Mapped[int] = mapped_column(ForeignKey("running_gags.id", ondelete="CASCADE"), nullable=False)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episode_scenes.id"))

    usage_context: Mapped[Optional[str]] = mapped_column(Text)
    dialogue_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    effectiveness_rating: Mapped[Optional[int]] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    gag: Mapped["RunningGag"] = relationship("RunningGag", back_populates="usages")
    episode: Mapped["Episode"] = relationship("Episode", backref="gag_usages")

    def __repr__(self) -> str:
        return f"<GagUsage gag={self.gag_id} ep={self.episode_id}>"


# Avoid circular imports
from app.models.character import Character
from app.models.episode import Episode
