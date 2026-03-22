"""Episode API endpoints."""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import StreamingResponse

from app.database import get_db
from app.models.episode import Episode, EpisodeStatus, EpisodeType
from app.models.race import Race
from app.models.scene import Scene
from app.jobs import enqueue_pipeline, get_job_status
from app.schemas.episode import (
    EpisodeDetailResponse,
    EpisodeResponse,
    GenerateEpisodeRequest,
    GenerateEpisodeResponse,
    RetryRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=GenerateEpisodeResponse)
async def generate_episode(
    request: GenerateEpisodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger episode generation via the persistent RQ queue."""
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

    # Enqueue onto the persistent RQ queue (survives API restarts)
    rq_job_id = enqueue_pipeline(episode.id)

    logger.info(f"Episode {episode.id} enqueued as RQ job {rq_job_id}")

    return GenerateEpisodeResponse(
        episode_id=episode.id,
        status=EpisodeStatus.GENERATING,
        estimated_completion_minutes=45,
    )


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
            scene_count=ep.scene_count,
            final_video_path=ep.final_video_path,
            duration_seconds=ep.duration_seconds,
            ovi_calls=ep.ovi_calls,
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
        .options(
            selectinload(Episode.race),
            selectinload(Episode.scenes).selectinload(Scene.character),
        )
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

    # Enqueue retry onto persistent RQ queue
    rq_job_id = enqueue_pipeline(episode.id)

    return {"status": "retry_started", "episode_id": episode_id, "rq_job_id": rq_job_id}


@router.post("/{episode_id}/stitch")
async def stitch_episode(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Stitch all scene clips into a final episode video."""
    from app.jobs import enqueue_stitch
    from app.models.scene import SceneStatus as SS

    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Check scenes exist
    stmt = select(Scene).where(
        Scene.episode_id == episode_id,
        Scene.status == SS.COMPLETED,
    )
    result = await db.execute(stmt)
    completed = result.scalars().all()

    if not completed:
        raise HTTPException(status_code=400, detail="No completed scenes to stitch")

    logger.info(f"Stitch request for episode {episode_id} ({len(completed)} completed scenes)")

    rq_job_id = enqueue_stitch(episode_id)
    return {"status": "stitch_started", "episode_id": episode_id, "rq_job_id": rq_job_id}


@router.post("/{episode_id}/upload-youtube")
async def upload_youtube(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Upload stitched video to YouTube."""
    from app.jobs import enqueue_youtube_upload

    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    if not episode.final_video_path:
        raise HTTPException(status_code=400, detail="No final video to upload. Stitch first.")

    logger.info(f"YouTube upload request for episode {episode_id}")

    rq_job_id = enqueue_youtube_upload(episode_id)
    return {"status": "upload_started", "episode_id": episode_id, "rq_job_id": rq_job_id}


@router.post("/{episode_id}/validate")
async def validate_episode(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Run quality validation on all completed scenes."""
    from app.jobs import enqueue_validate
    from app.models.scene import SceneStatus as SS

    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Check scenes exist
    stmt = select(Scene).where(
        Scene.episode_id == episode_id,
        Scene.status == SS.COMPLETED,
    )
    result = await db.execute(stmt)
    completed = result.scalars().all()

    if not completed:
        raise HTTPException(status_code=400, detail="No completed scenes to validate")

    logger.info(f"Validate request for episode {episode_id} ({len(completed)} scenes)")

    rq_job_id = enqueue_validate(episode_id)
    return {"status": "validation_started", "episode_id": episode_id, "rq_job_id": rq_job_id}


# ---------------------------------------------------------------------------
# SSE progress streaming
# ---------------------------------------------------------------------------

async def _progress_stream(job_id: str) -> AsyncGenerator[str, None]:
    """Async generator that polls an RQ job and yields SSE events."""
    max_iterations = 450  # 15 min timeout at 2s intervals

    for _ in range(max_iterations):
        status_data = get_job_status(job_id)

        if status_data is None:
            event = {
                "step": "error",
                "message": "Job not found",
                "progress": 0,
                "total": 0,
                "status": "failed",
            }
            yield f"data: {json.dumps(event)}\n\n"
            return

        meta = status_data.get("meta") or {}
        job_status = status_data["status"]

        event = {
            "step": meta.get("step", ""),
            "message": meta.get("message", ""),
            "progress": meta.get("progress", 0),
            "total": meta.get("total", 0),
            "status": job_status,
        }

        if job_status == "finished":
            event["step"] = "complete"
            event["message"] = str(status_data.get("result", ""))
            yield f"data: {json.dumps(event)}\n\n"
            return

        if job_status == "failed":
            event["step"] = "error"
            event["message"] = str(status_data.get("error", "Unknown error"))
            yield f"data: {json.dumps(event)}\n\n"
            return

        if job_status == "stopped":
            event["step"] = "stopped"
            event["message"] = "Job was stopped"
            yield f"data: {json.dumps(event)}\n\n"
            return

        yield f"data: {json.dumps(event)}\n\n"
        await asyncio.sleep(2)

    # Timeout reached
    event = {
        "step": "error",
        "message": "Progress stream timed out after 5 minutes",
        "progress": 0,
        "total": 0,
        "status": "timeout",
    }
    yield f"data: {json.dumps(event)}\n\n"


@router.get("/{episode_id}/progress/{job_id}")
async def stream_job_progress(episode_id: int, job_id: str):
    """Stream real-time progress events for a background job via SSE."""
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _progress_stream(job_id),
        media_type="text/event-stream",
        headers=headers,
    )
