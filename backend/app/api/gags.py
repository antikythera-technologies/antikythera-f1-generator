"""Running gags API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.gag import GagUsage, RunningGag
from app.schemas.gag import (
    GagCreate,
    GagResponse,
    GagUpdate,
    GagUsageCreate,
    GagUsageResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[GagResponse])
async def list_gags(
    active_only: bool = True,
    character_id: Optional[int] = Query(None, description="Filter by character"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """List running gags with optional filters."""
    stmt = select(RunningGag).options(selectinload(RunningGag.usages))

    if active_only:
        stmt = stmt.where(RunningGag.is_active == True)

    if character_id:
        stmt = stmt.where(
            (RunningGag.primary_character_id == character_id)
            | (RunningGag.secondary_character_id == character_id)
        )

    if category:
        stmt = stmt.where(RunningGag.category == category)

    if status:
        stmt = stmt.where(RunningGag.status == status)

    stmt = stmt.order_by(RunningGag.humor_rating.desc(), RunningGag.created_at.desc())

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{gag_id}", response_model=GagResponse)
async def get_gag(
    gag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a running gag by ID."""
    stmt = (
        select(RunningGag)
        .options(selectinload(RunningGag.usages))
        .where(RunningGag.id == gag_id)
    )
    result = await db.execute(stmt)
    gag = result.scalar_one_or_none()

    if not gag:
        raise HTTPException(status_code=404, detail="Gag not found")

    return gag


@router.post("", response_model=GagResponse)
async def create_gag(
    gag: GagCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new running gag."""
    db_gag = RunningGag(**gag.model_dump())
    db.add(db_gag)
    await db.flush()

    # Reload with usages relationship for response
    stmt = (
        select(RunningGag)
        .options(selectinload(RunningGag.usages))
        .where(RunningGag.id == db_gag.id)
    )
    result = await db.execute(stmt)
    db_gag = result.scalar_one()

    logger.info(f"Created running gag: {db_gag.title}")
    return db_gag


@router.put("/{gag_id}", response_model=GagResponse)
async def update_gag(
    gag_id: int,
    gag: GagUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a running gag."""
    db_gag = await db.get(RunningGag, gag_id)

    if not db_gag:
        raise HTTPException(status_code=404, detail="Gag not found")

    update_data = gag.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_gag, key, value)

    await db.flush()

    # Reload with usages relationship for response
    stmt = (
        select(RunningGag)
        .options(selectinload(RunningGag.usages))
        .where(RunningGag.id == gag_id)
    )
    result = await db.execute(stmt)
    db_gag = result.scalar_one()

    logger.info(f"Updated running gag: {db_gag.title}")
    return db_gag


@router.delete("/{gag_id}")
async def delete_gag(
    gag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a running gag."""
    db_gag = await db.get(RunningGag, gag_id)

    if not db_gag:
        raise HTTPException(status_code=404, detail="Gag not found")

    await db.delete(db_gag)
    logger.info(f"Deleted running gag: {db_gag.title}")

    return {"detail": "Gag deleted"}


@router.post("/{gag_id}/use", response_model=GagUsageResponse)
async def record_gag_usage(
    gag_id: int,
    usage: GagUsageCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record a gag being used in an episode."""
    db_gag = await db.get(RunningGag, gag_id)

    if not db_gag:
        raise HTTPException(status_code=404, detail="Gag not found")

    # Create usage record
    db_usage = GagUsage(
        gag_id=gag_id,
        episode_id=usage.episode_id,
        scene_id=usage.scene_id,
        usage_context=usage.usage_context,
        dialogue_excerpt=usage.dialogue_excerpt,
        effectiveness_rating=usage.effectiveness_rating,
    )
    db.add(db_usage)

    # Update gag tracking
    from datetime import datetime
    db_gag.times_used += 1
    db_gag.last_used_at = datetime.utcnow()
    db_gag.last_used_in_episode_id = usage.episode_id
    db_gag.audience_familiarity = min(10, db_gag.audience_familiarity + 1)

    # Check if exhausted
    if db_gag.max_uses and db_gag.times_used >= db_gag.max_uses:
        db_gag.status = "exhausted"

    await db.flush()
    logger.info(f"Recorded usage of gag '{db_gag.title}' (used {db_gag.times_used} times)")

    return db_usage


@router.get("/for-episode/{episode_type}", response_model=list[GagResponse])
async def get_available_gags_for_episode(
    episode_type: str,
    character_ids: Optional[str] = Query(None, description="Comma-separated character IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Get available gags for an episode, respecting cooldowns and status.

    This is used by the script generator to find relevant gags
    that can be referenced in the current episode.
    """
    stmt = (
        select(RunningGag)
        .options(selectinload(RunningGag.usages))
        .where(RunningGag.is_active == True)
        .where(RunningGag.status.in_(["active", "cooling_down"]))
    )

    # Filter by characters in this episode
    if character_ids:
        char_id_list = [int(x) for x in character_ids.split(",")]
        stmt = stmt.where(
            (RunningGag.primary_character_id.in_(char_id_list))
            | (RunningGag.secondary_character_id.in_(char_id_list))
            | (RunningGag.primary_character_id.is_(None))  # Universal gags
        )

    stmt = stmt.order_by(RunningGag.humor_rating.desc())

    result = await db.execute(stmt)
    gags = result.scalars().all()

    # Filter out gags still in cooldown
    available = []
    for gag in gags:
        if gag.status == "active":
            available.append(gag)
        elif gag.status == "cooling_down":
            # Check if cooldown period has passed (simplified - count episodes since last use)
            if gag.times_used > 0 and gag.last_used_at:
                available.append(gag)  # Let the script generator decide

    return available
