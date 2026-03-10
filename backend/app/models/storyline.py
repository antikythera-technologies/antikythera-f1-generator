"""Storyline models for managing narrative arcs across episodes."""

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StorylineType(str, enum.Enum):
    """Types of storylines."""
    RIVALRY = "rivalry"
    CHARACTER_ARC = "character_arc"
    RUNNING_JOKE = "running_joke"
    SEASON_PLOT = "season_plot"
    EVENT_REACTION = "event_reaction"


class StorylineStatus(str, enum.Enum):
    """Status of a storyline."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# Many-to-many association table: storylines <-> characters
storyline_characters = Table(
    "storyline_characters",
    Base.metadata,
    Column("storyline_id", Integer, ForeignKey("storylines.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)


class Storyline(Base):
    """Narrative arcs that span multiple episodes."""

    __tablename__ = "storylines"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Basic info
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    storyline_type: Mapped[StorylineType] = mapped_column(
        Enum(
            StorylineType,
            name="storyline_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=StorylineType.RIVALRY,
    )
    status: Mapped[StorylineStatus] = mapped_column(
        Enum(
            StorylineStatus,
            name="storyline_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=StorylineStatus.ACTIVE,
    )

    # Priority (higher = more likely to appear in episodes)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # Time-bound arcs
    start_race_id: Mapped[Optional[int]] = mapped_column(ForeignKey("races.id"))
    end_race_id: Mapped[Optional[int]] = mapped_column(ForeignKey("races.id"))

    # Plot structure
    plot_points: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)
    current_beat: Mapped[int] = mapped_column(Integer, default=0)

    # Comedy direction
    comedy_notes: Mapped[Optional[str]] = mapped_column(Text)

    # Tags for filtering
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))

    # Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    characters: Mapped[List["Character"]] = relationship(
        "Character",
        secondary=storyline_characters,
        backref="storylines",
    )
    start_race: Mapped[Optional["Race"]] = relationship(
        "Race", foreign_keys=[start_race_id]
    )
    end_race: Mapped[Optional["Race"]] = relationship(
        "Race", foreign_keys=[end_race_id]
    )
    episode_links: Mapped[List["StorylineEpisode"]] = relationship(
        "StorylineEpisode",
        back_populates="storyline",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Storyline {self.id}: {self.title}>"


class StorylineEpisode(Base):
    """Junction table linking storylines to episodes they appeared in."""

    __tablename__ = "storyline_episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    storyline_id: Mapped[int] = mapped_column(
        ForeignKey("storylines.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )

    # Which plot beat was used in this episode
    beat_used: Mapped[Optional[int]] = mapped_column(Integer)

    # Which scenes featured this storyline (list of scene numbers)
    scene_numbers: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer))

    # Notes on how the storyline was used
    usage_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    storyline: Mapped["Storyline"] = relationship(
        "Storyline", back_populates="episode_links"
    )
    episode: Mapped["Episode"] = relationship("Episode", backref="storyline_links")

    def __repr__(self) -> str:
        return f"<StorylineEpisode storyline={self.storyline_id} ep={self.episode_id}>"


# Avoid circular imports
from app.models.character import Character
from app.models.episode import Episode
from app.models.race import Race
