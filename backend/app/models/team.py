"""Team model — F1 constructor/team data with livery descriptions."""

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Team(Base):
    """F1 team with livery descriptions for prompt injection."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)

    # Livery (structured prompt snippets, ready to inject)
    livery_description: Mapped[Optional[str]] = mapped_column(Text)
    car_description: Mapped[Optional[str]] = mapped_column(Text)
    overalls_description: Mapped[Optional[str]] = mapped_column(Text)

    # Colours (for dashboard display)
    primary_colour: Mapped[Optional[str]] = mapped_column(String(7))
    secondary_colour: Mapped[Optional[str]] = mapped_column(String(7))
    accent_colour: Mapped[Optional[str]] = mapped_column(String(7))

    # Team info
    principal_name: Mapped[Optional[str]] = mapped_column(String(100))
    engine_supplier: Mapped[Optional[str]] = mapped_column(String(50))
    constructor_name: Mapped[Optional[str]] = mapped_column(String(100))
    headquarters: Mapped[Optional[str]] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    characters: Mapped[List["Character"]] = relationship(
        "Character", back_populates="team_rel"
    )

    __table_args__ = (
        UniqueConstraint("short_name", "season", name="uq_team_short_name_season"),
    )

    def __repr__(self) -> str:
        return f"<Team {self.short_name} ({self.season})>"
