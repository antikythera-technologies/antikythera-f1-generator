"""Race API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.race import Race
from app.schemas.race import RaceCreate, RaceResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[RaceResponse])
async def list_races(
    season: Optional[int] = None,
    upcoming_only: bool = False,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List races with optional filtering."""
    from datetime import date

    stmt = select(Race)

    if season:
        stmt = stmt.where(Race.season == season)

    if upcoming_only:
        stmt = stmt.where(Race.race_date >= date.today())

    stmt = stmt.order_by(Race.race_date).limit(limit)

    result = await db.execute(stmt)
    races = result.scalars().all()

    return races


@router.get("/{race_id}", response_model=RaceResponse)
async def get_race(
    race_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get race by ID."""
    race = await db.get(Race, race_id)

    if not race:
        raise HTTPException(status_code=404, detail="Race not found")

    return race


@router.post("", response_model=RaceResponse)
async def create_race(
    race: RaceCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new race."""
    # Check for duplicate
    stmt = select(Race).where(
        Race.season == race.season,
        Race.round_number == race.round_number,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Race already exists for season {race.season} round {race.round_number}",
        )

    db_race = Race(**race.model_dump())
    db.add(db_race)
    await db.flush()

    logger.info(f"Created race: {db_race.race_name}")

    return db_race


@router.post("/sync")
async def sync_races(
    season: int = Query(default=2025),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync race calendar from external source.
    
    TODO: Implement Ergast API or similar integration.
    """
    logger.info(f"Syncing races for season {season}")

    # Placeholder for external API integration
    return {
        "status": "not_implemented",
        "message": "Race calendar sync not yet implemented. Add races manually or integrate with F1 calendar API.",
    }
