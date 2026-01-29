"""Race model."""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Race(Base):
    """F1 race calendar - used for scheduling and content context."""
    
    __tablename__ = "races"

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    race_name: Mapped[str] = mapped_column(String(100), nullable=False)
    circuit_name: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    race_date: Mapped[date] = mapped_column(Date, nullable=False)
    fp1_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    fp2_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    fp3_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    qualifying_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    race_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Sprint weekend fields
    is_sprint_weekend: Mapped[bool] = mapped_column(Boolean, default=False)
    sprint_qualifying_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sprint_race_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    episodes: Mapped[List["Episode"]] = relationship("Episode", back_populates="race")

    __table_args__ = (
        UniqueConstraint("season", "round_number", name="uq_race_season_round"),
    )

    def __repr__(self) -> str:
        return f"<Race {self.season} R{self.round_number}: {self.race_name}>"


# Import Episode here to avoid circular imports
from app.models.episode import Episode
