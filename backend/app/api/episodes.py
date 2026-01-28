"""Episode API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.episode import Episode, EpisodeStatus, EpisodeType
from app.models.race import Race
from app.schemas.episode import (
    EpisodeDetailResponse,
    EpisodeResponse,
    GenerateEpisodeRequest,
    GenerateEpisodeResponse,
    RetryRequest,
)
from app.pipeline.video_pipeline import VideoPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=GenerateEpisodeResponse)
async def generate_episode(
    request: GenerateEpisodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger episode generation."""
    logger.info(f"Generate episode request: race_id={request.race_id}, type={request.episode_type}")

    # Check if race exists
    race = await db.get(Race, request.race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")

    # Check for existing episode
    stmt = select(Episode).where(
        Episode.race_id == request.race_id,
        Episode.episode_type == request.episode_type,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing and not request.force:
        raise HTTPException(
            status_code=409,
            detail=f"Episode already exists: {existing.id}. Use force=true to regenerate.",
        )

    # Create new episode
    title = f"{race.race_name} - {request.episode_type.value.replace('-', ' ').title()}"
    episode = Episode(
        race_id=request.race_id,
        episode_type=request.episode_type,
        title=title,
        status=EpisodeStatus.PENDING,
    )
    db.add(episode)
    await db.flush()

    logger.info(f"Created episode {episode.id}: {title}")

    # Start pipeline in background
    background_tasks.add_task(run_pipeline_background, episode.id)

    return GenerateEpisodeResponse(
        episode_id=episode.id,
        status=EpisodeStatus.GENERATING,
        estimated_completion_minutes=45,
    )


async def run_pipeline_background(episode_id: int):
    """Run video pipeline in background."""
    logger.info(f"Starting background pipeline for episode {episode_id}")
    try:
        pipeline = VideoPipeline(episode_id)
        await pipeline.run()
    except Exception as e:
        logger.error(f"Pipeline failed for episode {episode_id}: {e}")


@router.get("", response_model=list[EpisodeResponse])
async def list_episodes(
    status: Optional[EpisodeStatus] = None,
    race_id: Optional[int] = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List episodes with filtering."""
    stmt = select(Episode).options(selectinload(Episode.race))

    if status:
        stmt = stmt.where(Episode.status == status)
    if race_id:
        stmt = stmt.where(Episode.race_id == race_id)

    stmt = stmt.order_by(Episode.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    episodes = result.scalars().all()

    return [
        EpisodeResponse(
            id=ep.id,
            race_id=ep.race_id,
            race_name=ep.race.race_name if ep.race else None,
            episode_type=ep.episode_type,
            title=ep.title,
            status=ep.status,
            youtube_url=ep.youtube_url,
            total_cost_usd=ep.total_cost_usd,
            created_at=ep.created_at,
            published_at=ep.published_at,
        )
        for ep in episodes
    ]


@router.get("/{episode_id}", response_model=EpisodeDetailResponse)
async def get_episode(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get episode details."""
    stmt = (
        select(Episode)
        .options(selectinload(Episode.race), selectinload(Episode.scenes))
        .where(Episode.id == episode_id)
    )
    result = await db.execute(stmt)
    episode = result.scalar_one_or_none()

    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    return episode


@router.post("/{episode_id}/retry")
async def retry_episode(
    episode_id: int,
    request: RetryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry failed episode or specific scenes."""
    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    logger.info(f"Retry request for episode {episode_id}, scenes: {request.scene_ids or 'all failed'}")

    # Reset episode status
    episode.status = EpisodeStatus.GENERATING
    episode.retry_count += 1

    # Start retry in background
    background_tasks.add_task(run_pipeline_background, episode.id)

    return {"status": "retry_started", "episode_id": episode_id}
