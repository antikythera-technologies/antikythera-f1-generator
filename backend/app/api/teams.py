"""Team API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.team import Team
from app.schemas.team import TeamCreate, TeamResponse, TeamUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[TeamResponse])
async def list_teams(
    season: Optional[int] = None,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List all teams, optionally filtered by season."""
    stmt = select(Team)

    if season:
        stmt = stmt.where(Team.season == season)
    if active_only:
        stmt = stmt.where(Team.is_active == True)

    stmt = stmt.order_by(Team.name)

    result = await db.execute(stmt)
    teams = result.scalars().all()

    return teams


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get team by ID."""
    team = await db.get(Team, team_id)

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    return team


@router.post("", response_model=TeamResponse, status_code=201)
async def create_team(
    team: TeamCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new team."""
    # Check for duplicate
    stmt = select(Team).where(
        Team.short_name == team.short_name, Team.season == team.season
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Team '{team.short_name}' already exists for season {team.season}",
        )

    db_team = Team(**team.model_dump())
    db.add(db_team)
    await db.flush()

    logger.info(f"Created team: {db_team.name} ({db_team.season})")

    return db_team


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: int,
    team: TeamUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a team."""
    db_team = await db.get(Team, team_id)

    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")

    update_data = team.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_team, key, value)

    logger.info(f"Updated team: {db_team.name}")

    return db_team


@router.delete("/{team_id}")
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a team (soft delete — sets is_active=False)."""
    db_team = await db.get(Team, team_id)

    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")

    db_team.is_active = False
    logger.info(f"Deactivated team: {db_team.name}")

    return {"status": "deleted", "team_id": team_id}
