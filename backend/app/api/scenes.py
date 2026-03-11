"""Scene API endpoints for prompt editing and regeneration."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.scene import Scene, SceneStatus
from app.schemas.scene import SceneDetailResponse, ScenePromptUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{episode_id}/scenes",
    response_model=list[SceneDetailResponse],
)
async def list_scenes(
    episode_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List all scenes for an episode with full prompt details."""
    # Verify episode exists
    episode = await db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    stmt = (
        select(Scene)
        .where(Scene.episode_id == episode_id)
        .order_by(Scene.scene_number)
    )
    result = await db.execute(stmt)
    scenes = result.scalars().all()

    return scenes


@router.get(
    "/{episode_id}/scenes/{scene_number}",
    response_model=SceneDetailResponse,
)
async def get_scene(
    episode_id: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full scene detail including all prompts."""
    scene = await _get_scene(db, episode_id, scene_number)
    return scene


@router.put(
    "/{episode_id}/scenes/{scene_number}/prompts",
    response_model=SceneDetailResponse,
)
async def update_scene_prompts(
    episode_id: int,
    scene_number: int,
    update: ScenePromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update scene prompts. Any field omitted is left unchanged."""
    scene = await _get_scene(db, episode_id, scene_number)

    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No fields provided for update",
        )

    for field, value in update_data.items():
        setattr(scene, field, value)

    await db.commit()
    await db.refresh(scene)

    logger.info(
        f"Updated prompts for episode {episode_id} scene {scene_number}: "
        f"{list(update_data.keys())}"
    )

    return scene


@router.post(
    "/{episode_id}/scenes/{scene_number}/regenerate-start-frame",
)
async def regenerate_start_frame(
    episode_id: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the start frame image using stored prompts."""
    scene = await _get_scene(db, episode_id, scene_number)

    if not scene.start_frame_prompt:
        raise HTTPException(
            status_code=400,
            detail="No start_frame_prompt set for this scene",
        )

    # Reset start frame status
    scene.start_frame_path = None
    scene.start_frame_prompt_final = None
    scene.status = SceneStatus.PENDING
    await db.commit()

    # TODO: Enqueue regeneration job
    return {
        "status": "queued",
        "episode_id": episode_id,
        "scene_number": scene_number,
        "regenerating": "start_frame",
    }


@router.post(
    "/{episode_id}/scenes/{scene_number}/regenerate-end-frame",
)
async def regenerate_end_frame(
    episode_id: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the end frame image using stored prompts."""
    scene = await _get_scene(db, episode_id, scene_number)

    if not scene.end_frame_prompt:
        raise HTTPException(
            status_code=400,
            detail="No end_frame_prompt set for this scene",
        )

    scene.end_frame_path = None
    scene.end_frame_prompt_final = None
    scene.status = SceneStatus.PENDING
    await db.commit()

    return {
        "status": "queued",
        "episode_id": episode_id,
        "scene_number": scene_number,
        "regenerating": "end_frame",
    }


@router.post(
    "/{episode_id}/scenes/{scene_number}/regenerate-video",
)
async def regenerate_video(
    episode_id: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the video clip using stored frames and prompts."""
    scene = await _get_scene(db, episode_id, scene_number)

    if not scene.start_frame_path or not scene.end_frame_path:
        raise HTTPException(
            status_code=400,
            detail="Both start and end frame images must exist before regenerating video",
        )

    scene.video_clip_path = None
    scene.status = SceneStatus.PENDING
    await db.commit()

    return {
        "status": "queued",
        "episode_id": episode_id,
        "scene_number": scene_number,
        "regenerating": "video",
    }


@router.post(
    "/{episode_id}/scenes/{scene_number}/regenerate-all",
)
async def regenerate_all(
    episode_id: int,
    scene_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate start frame, end frame, and video for a scene."""
    scene = await _get_scene(db, episode_id, scene_number)

    if not scene.start_frame_prompt or not scene.end_frame_prompt:
        raise HTTPException(
            status_code=400,
            detail="Both start and end frame prompts must be set",
        )

    # Reset all generated assets
    scene.start_frame_path = None
    scene.start_frame_prompt_final = None
    scene.end_frame_path = None
    scene.end_frame_prompt_final = None
    scene.video_clip_path = None
    scene.status = SceneStatus.PENDING
    await db.commit()

    return {
        "status": "queued",
        "episode_id": episode_id,
        "scene_number": scene_number,
        "regenerating": "all",
    }


async def _get_scene(
    db: AsyncSession,
    episode_id: int,
    scene_number: int,
) -> Scene:
    """Helper to fetch a scene by episode_id and scene_number."""
    stmt = select(Scene).where(
        Scene.episode_id == episode_id,
        Scene.scene_number == scene_number,
    )
    result = await db.execute(stmt)
    scene = result.scalar_one_or_none()

    if not scene:
        raise HTTPException(
            status_code=404,
            detail=f"Scene {scene_number} not found in episode {episode_id}",
        )

    return scene
