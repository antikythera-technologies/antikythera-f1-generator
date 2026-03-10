"""Storyline API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.character import Character
from app.models.storyline import Storyline, StorylineEpisode, storyline_characters
from app.schemas.storyline import (
    StorylineCreate,
    StorylineEpisodeCreate,
    StorylineEpisodeResponse,
    StorylineListResponse,
    StorylineResponse,
    StorylineUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/active", response_model=list[StorylineListResponse])
async def get_active_storylines(
    db: AsyncSession = Depends(get_db),
):
    """Get active storylines for script generation.

    Returns storylines ordered by priority (highest first).
    Used by the script generator to incorporate ongoing narratives.
    """
    stmt = (
        select(Storyline)
        .options(selectinload(Storyline.characters))
        .where(Storyline.is_active == True)
        .where(Storyline.status == "active")
        .order_by(Storyline.priority.desc(), Storyline.updated_at.desc())
    )

    result = await db.execute(stmt)
    storylines = result.scalars().all()

    # Add episode counts
    responses = []
    for s in storylines:
        count_stmt = (
            select(func.count())
            .select_from(StorylineEpisode)
            .where(StorylineEpisode.storyline_id == s.id)
        )
        count_result = await db.execute(count_stmt)
        ep_count = count_result.scalar() or 0

        response = StorylineListResponse.model_validate(s)
        response.episode_count = ep_count
        responses.append(response)

    return responses


@router.get("", response_model=list[StorylineListResponse])
async def list_storylines(
    status: Optional[str] = Query(None, description="Filter by status"),
    storyline_type: Optional[str] = Query(None, description="Filter by type"),
    character_id: Optional[int] = Query(None, description="Filter by character"),
    active_only: bool = Query(True, description="Only show active storylines"),
    db: AsyncSession = Depends(get_db),
):
    """List storylines with optional filters."""
    stmt = (
        select(Storyline)
        .options(selectinload(Storyline.characters))
    )

    if active_only:
        stmt = stmt.where(Storyline.is_active == True)

    if status:
        stmt = stmt.where(Storyline.status == status)

    if storyline_type:
        stmt = stmt.where(Storyline.storyline_type == storyline_type)

    if character_id:
        stmt = stmt.join(storyline_characters).where(
            storyline_characters.c.character_id == character_id
        )

    stmt = stmt.order_by(Storyline.priority.desc(), Storyline.created_at.desc())

    result = await db.execute(stmt)
    storylines = result.scalars().unique().all()

    # Add episode counts
    responses = []
    for s in storylines:
        count_stmt = (
            select(func.count())
            .select_from(StorylineEpisode)
            .where(StorylineEpisode.storyline_id == s.id)
        )
        count_result = await db.execute(count_stmt)
        ep_count = count_result.scalar() or 0

        response = StorylineListResponse.model_validate(s)
        response.episode_count = ep_count
        responses.append(response)

    return responses


@router.get("/{storyline_id}", response_model=StorylineResponse)
async def get_storyline(
    storyline_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a storyline by ID with full details."""
    stmt = (
        select(Storyline)
        .options(
            selectinload(Storyline.characters),
            selectinload(Storyline.episode_links),
        )
        .where(Storyline.id == storyline_id)
    )
    result = await db.execute(stmt)
    storyline = result.scalar_one_or_none()

    if not storyline:
        raise HTTPException(status_code=404, detail="Storyline not found")

    # Add episode count
    response = StorylineResponse.model_validate(storyline)
    response.episode_count = len(storyline.episode_links)

    return response


@router.post("", response_model=StorylineResponse)
async def create_storyline(
    data: StorylineCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new storyline."""
    # Extract character_ids before creating the model
    character_ids = data.character_ids
    storyline_data = data.model_dump(exclude={"character_ids"})

    db_storyline = Storyline(**storyline_data)

    # Load characters if IDs provided
    if character_ids:
        for char_id in character_ids:
            character = await db.get(Character, char_id)
            if character:
                db_storyline.characters.append(character)
            else:
                logger.warning(f"Character {char_id} not found, skipping")

    db.add(db_storyline)
    await db.flush()

    # Reload with relationships
    stmt = (
        select(Storyline)
        .options(
            selectinload(Storyline.characters),
            selectinload(Storyline.episode_links),
        )
        .where(Storyline.id == db_storyline.id)
    )
    result = await db.execute(stmt)
    db_storyline = result.scalar_one()

    logger.info(f"Created storyline: {db_storyline.title}")

    response = StorylineResponse.model_validate(db_storyline)
    response.episode_count = 0
    return response


@router.put("/{storyline_id}", response_model=StorylineResponse)
async def update_storyline(
    storyline_id: int,
    data: StorylineUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a storyline."""
    stmt = (
        select(Storyline)
        .options(
            selectinload(Storyline.characters),
            selectinload(Storyline.episode_links),
        )
        .where(Storyline.id == storyline_id)
    )
    result = await db.execute(stmt)
    db_storyline = result.scalar_one_or_none()

    if not db_storyline:
        raise HTTPException(status_code=404, detail="Storyline not found")

    update_data = data.model_dump(exclude_unset=True, exclude={"character_ids"})
    for key, value in update_data.items():
        setattr(db_storyline, key, value)

    # Update characters if provided
    if data.character_ids is not None:
        db_storyline.characters.clear()
        for char_id in data.character_ids:
            character = await db.get(Character, char_id)
            if character:
                db_storyline.characters.append(character)

    await db.flush()

    # Reload
    stmt = (
        select(Storyline)
        .options(
            selectinload(Storyline.characters),
            selectinload(Storyline.episode_links),
        )
        .where(Storyline.id == storyline_id)
    )
    result = await db.execute(stmt)
    db_storyline = result.scalar_one()

    logger.info(f"Updated storyline: {db_storyline.title}")

    response = StorylineResponse.model_validate(db_storyline)
    response.episode_count = len(db_storyline.episode_links)
    return response


@router.delete("/{storyline_id}")
async def delete_storyline(
    storyline_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Soft delete (archive) a storyline."""
    db_storyline = await db.get(Storyline, storyline_id)

    if not db_storyline:
        raise HTTPException(status_code=404, detail="Storyline not found")

    db_storyline.status = "archived"
    db_storyline.is_active = False
    await db.flush()

    logger.info(f"Archived storyline: {db_storyline.title}")
    return {"detail": "Storyline archived"}


@router.post("/{storyline_id}/advance", response_model=StorylineResponse)
async def advance_storyline(
    storyline_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Advance the storyline to the next plot beat."""
    stmt = (
        select(Storyline)
        .options(
            selectinload(Storyline.characters),
            selectinload(Storyline.episode_links),
        )
        .where(Storyline.id == storyline_id)
    )
    result = await db.execute(stmt)
    db_storyline = result.scalar_one_or_none()

    if not db_storyline:
        raise HTTPException(status_code=404, detail="Storyline not found")

    if db_storyline.status != "active":
        raise HTTPException(
            status_code=400, detail=f"Cannot advance storyline with status '{db_storyline.status}'"
        )

    # Advance the beat counter
    plot_points = db_storyline.plot_points or []
    total_beats = len(plot_points)

    if total_beats == 0:
        raise HTTPException(status_code=400, detail="Storyline has no plot points to advance")

    if db_storyline.current_beat >= total_beats - 1:
        # Mark as completed when we've gone through all beats
        db_storyline.current_beat = total_beats - 1
        db_storyline.status = "completed"
        logger.info(f"Storyline '{db_storyline.title}' completed (all beats used)")
    else:
        db_storyline.current_beat += 1
        logger.info(
            f"Advanced storyline '{db_storyline.title}' to beat {db_storyline.current_beat}"
        )

    # Mark current beat as completed in plot_points
    if isinstance(plot_points, list) and db_storyline.current_beat < len(plot_points):
        current = plot_points[db_storyline.current_beat]
        if isinstance(current, dict):
            current["completed"] = True
            # Force JSONB update by reassigning
            db_storyline.plot_points = list(plot_points)

    await db.flush()

    response = StorylineResponse.model_validate(db_storyline)
    response.episode_count = len(db_storyline.episode_links)
    return response


@router.post("/{storyline_id}/episodes", response_model=StorylineEpisodeResponse)
async def link_episode(
    storyline_id: int,
    data: StorylineEpisodeCreate,
    db: AsyncSession = Depends(get_db),
):
    """Link a storyline to an episode (record that it appeared)."""
    db_storyline = await db.get(Storyline, storyline_id)
    if not db_storyline:
        raise HTTPException(status_code=404, detail="Storyline not found")

    link = StorylineEpisode(
        storyline_id=storyline_id,
        episode_id=data.episode_id,
        beat_used=data.beat_used,
        scene_numbers=data.scene_numbers,
        usage_notes=data.usage_notes,
    )
    db.add(link)
    await db.flush()

    logger.info(f"Linked storyline '{db_storyline.title}' to episode {data.episode_id}")
    return link
