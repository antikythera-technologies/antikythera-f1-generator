"""Race results model — stores actual session results for accurate script generation."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, Boolean, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SessionType(str, enum.Enum):
    """F1 session types."""
    FP1 = "fp1"
    FP2 = "fp2"
    FP3 = "fp3"
    QUALIFYING = "qualifying"
    SPRINT_QUALIFYING = "sprint_qualifying"
    SPRINT = "sprint"
    RACE = "race"


class RaceResult(Base):
    """Individual driver result for a session."""

    __tablename__ = "race_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, name="session_type", create_type=False,
             values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    # Driver info
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-20
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)  # "max_verstappen"
    driver_display_name: Mapped[Optional[str]] = mapped_column(String(100))  # "Max Verstappen"
    driver_number: Mapped[Optional[int]] = mapped_column(Integer)
    team: Mapped[Optional[str]] = mapped_column(String(100))  # "Red Bull Racing"

    # Timing
    time_or_gap: Mapped[Optional[str]] = mapped_column(String(50))  # "1:23.456" or "+5.123s"
    laps_completed: Mapped[Optional[int]] = mapped_column(Integer)
    grid_position: Mapped[Optional[int]] = mapped_column(Integer)  # Starting grid position
    positions_gained: Mapped[Optional[int]] = mapped_column(Integer)  # Grid vs finish

    # Status
    status: Mapped[str] = mapped_column(String(50), default="Finished")  # "Finished", "DNF", "DNS", "+1 Lap"
    is_dnf: Mapped[bool] = mapped_column(Boolean, default=False)
    dnf_reason: Mapped[Optional[str]] = mapped_column(String(200))  # "Collision", "Engine", etc.

    # Highlights
    fastest_lap: Mapped[bool] = mapped_column(Boolean, default=False)
    fastest_lap_time: Mapped[Optional[str]] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    race: Mapped["Race"] = relationship("Race", back_populates="results")


class RaceIncident(Base):
    """Key incidents during a session (safety cars, crashes, penalties)."""

    __tablename__ = "race_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, name="session_type", create_type=False,
             values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    lap: Mapped[Optional[int]] = mapped_column(Integer)
    incident_type: Mapped[str] = mapped_column(String(50))  # "safety_car", "vsc", "crash", "penalty", "overtake_record"
    description: Mapped[str] = mapped_column(Text, nullable=False)
    drivers_involved: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated driver names

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    race: Mapped["Race"] = relationship("Race")


class RaceSessionSummary(Base):
    """High-level session summary with stats."""

    __tablename__ = "race_session_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, name="session_type", create_type=False,
             values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    # Stats
    total_overtakes: Mapped[Optional[int]] = mapped_column(Integer)
    safety_car_periods: Mapped[int] = mapped_column(Integer, default=0)
    vsc_periods: Mapped[int] = mapped_column(Integer, default=0)
    red_flag_periods: Mapped[int] = mapped_column(Integer, default=0)
    total_dnfs: Mapped[int] = mapped_column(Integer, default=0)
    rain: Mapped[bool] = mapped_column(Boolean, default=False)

    # Podium (quick access)
    winner: Mapped[Optional[str]] = mapped_column(String(100))
    second: Mapped[Optional[str]] = mapped_column(String(100))
    third: Mapped[Optional[str]] = mapped_column(String(100))

    # Raw data from API (for debugging)
    raw_api_response: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    race: Mapped["Race"] = relationship("Race")
