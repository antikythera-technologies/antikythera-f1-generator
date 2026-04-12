"""Job enqueue utilities for the RQ task queue.

Provides a simple interface to enqueue pipeline jobs onto the Redis-backed
RQ queue. The actual work is executed by the worker process defined in
``app.worker``.
"""

import logging
from typing import Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from app.config import settings
from app.services.api_logger import log_api_request, log_api_response
from app.services.cost_tracker import log_api_cost as _log_api_cost_shared
from app.services.cost_tracker import update_episode_costs as _update_episode_costs_shared

import time

logger = logging.getLogger(__name__)


async def _log_api_cost(
    db,
    episode_id: int,
    scene_id: int | None,
    provider: str,
    endpoint: str,
    cost_usd: float,
    response_time_ms: int = 0,
):
    """Log an API usage record. Delegates to shared cost_tracker."""
    await _log_api_cost_shared(
        db, episode_id=episode_id, scene_id=scene_id,
        provider=provider, endpoint=endpoint,
        cost_usd=cost_usd, response_time_ms=response_time_ms,
    )


async def _update_episode_costs(db, episode_id: int) -> None:
    """Sum all scene costs. Delegates to shared cost_tracker."""
    await _update_episode_costs_shared(db, episode_id)

PIPELINE_QUEUE = "f1-pipeline"

# Pipeline jobs can run for up to 2 hours (image gen + stitching is slow)
DEFAULT_JOB_TIMEOUT = 7200  # seconds


def get_redis_connection() -> Redis:
    """Get a Redis connection from settings."""
    return Redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    """Get the pipeline RQ queue."""
    return Queue(PIPELINE_QUEUE, connection=get_redis_connection())


def enqueue_pipeline(episode_id: int, job_timeout: int = DEFAULT_JOB_TIMEOUT) -> str:
    """
    Enqueue a video pipeline job for the given episode.

    Args:
        episode_id: ID of the Episode record to process.
        job_timeout: Maximum seconds the job may run (default 2 hours).

    Returns:
        The RQ job ID (a UUID string).
    """
    queue = get_queue()

    # The function path that the worker will import and call.
    # It must be a top-level function importable by the worker process.
    job: Job = queue.enqueue(
        "app.jobs._run_pipeline",
        episode_id,
        job_timeout=job_timeout,
        result_ttl=86400,       # keep result for 24 h
        failure_ttl=604800,     # keep failure info for 7 days
        meta={"episode_id": episode_id},
    )

    logger.info(
        f"Enqueued pipeline job {job.id} for episode {episode_id} "
        f"(timeout={job_timeout}s)"
    )
    return job.id


def get_job_status(job_id: str) -> Optional[dict]:
    """
    Get the status of an RQ job.

    Returns a dict with keys ``status``, ``meta``, ``result``, ``error``
    or ``None`` if the job does not exist.
    """
    try:
        job = Job.fetch(job_id, connection=get_redis_connection())
        return {
            "id": job.id,
            "status": job.get_status(),
            "meta": job.meta,
            "result": job.result,
            "error": job.exc_info if job.is_failed else None,
            "enqueued_at": str(job.enqueued_at) if job.enqueued_at else None,
            "started_at": str(job.started_at) if job.started_at else None,
            "ended_at": str(job.ended_at) if job.ended_at else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The function that the RQ worker actually executes.
# It MUST be importable as a top-level function — RQ pickles the dotted path.
# Because VideoPipeline.run() is async, we bridge with asyncio.run().
# ---------------------------------------------------------------------------

def _run_pipeline(episode_id: int) -> str:
    """
    Synchronous wrapper executed by the RQ worker.

    Bridges into the async VideoPipeline via ``asyncio.run()``.
    Creates a fresh DB engine to avoid issues with forked asyncpg
    connections from the parent process.
    """
    import asyncio
    import sys

    # Ensure child process logs go to stdout (captured by docker)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )

    logger.info(f"RQ worker starting pipeline for episode {episode_id}")

    # Replace the module-level engine with a fresh one.
    # The forked child inherits stale asyncpg connections that deadlock
    # when disposed. Creating a fresh engine is safer.
    import app.database as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.config import settings

    db_module.engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    db_module.async_session_maker = async_sessionmaker(
        db_module.engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.pipeline.video_pipeline import VideoPipeline

    pipeline = VideoPipeline(episode_id)
    result = asyncio.run(pipeline.run())

    logger.info(f"RQ worker completed pipeline for episode {episode_id}: {result}")
    return result


def enqueue_scene_video(episode_id: int, scene_number: int) -> str:
    """Enqueue a single scene video regeneration job.

    Uses the currently configured VIDEO_GENERATOR_DEFAULT backend.
    Requires at least a start frame image to exist.
    """
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_scene_video",
        episode_id,
        scene_number,
        job_timeout=600,        # 10 minutes should be enough for fal.ai
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "scene_number": scene_number, "type": "scene_video"},
    )
    logger.info(f"Enqueued scene video job {job.id} for episode {episode_id} scene {scene_number}")
    return job.id


def enqueue_scene_image(episode_id: int, scene_number: int, frame_type: str = "start") -> str:
    """Enqueue a single scene image generation job.

    Args:
        frame_type: "start" or "end" — which frame prompt to use.
    """
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_scene_image",
        episode_id,
        scene_number,
        frame_type,
        job_timeout=600,        # 10 minutes for fal.ai image gen (instant-character needs warm-up)
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "scene_number": scene_number, "type": f"scene_image_{frame_type}"},
    )
    logger.info(f"Enqueued scene image ({frame_type}) job {job.id} for episode {episode_id} scene {scene_number}")
    return job.id


def enqueue_scene_all(episode_id: int, scene_number: int) -> str:
    """Enqueue a full scene regeneration (image then video, sequential)."""
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_scene_all",
        episode_id,
        scene_number,
        job_timeout=900,        # 15 minutes for image + video
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "scene_number": scene_number, "type": "scene_all"},
    )
    logger.info(f"Enqueued scene all job {job.id} for episode {episode_id} scene {scene_number}")
    return job.id


def _run_scene_video(episode_id: int, scene_number: int) -> str:
    """Worker function: regenerate video for a single scene."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_scene_video(episode_id, scene_number))


async def _async_scene_video(episode_id: int, scene_number: int) -> str:
    """Async worker: regenerate video for a single scene. Delegates to shared service."""
    from datetime import datetime
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import async_session_maker
    from app.models.episode import Episode as _Ep
    from app.models.scene import Scene, SceneStatus
    from app.services.scene_video_service import generate_scene_video
    from app.services.storage import StorageService

    logger.info(f"Scene {scene_number}: Starting video regeneration (shared service)")

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character), selectinload(Scene.voiceover_character))
            .where(Scene.episode_id == episode_id, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            raise ValueError(f"Scene {scene_number} not found for episode {episode_id}")

        ep = await db.get(_Ep, episode_id)
        race_id = ep.race_id if ep and ep.race_id else 0
        storage = StorageService()

        try:
            scene.status = SceneStatus.GENERATING
            scene.generation_started_at = datetime.utcnow()
            from decimal import Decimal
            scene.video_cost_usd = Decimal(0)  # Reset for regen
            await db.flush()

            await generate_scene_video(
                db, scene, episode_id, race_id, storage,
            )
            scene.status = SceneStatus.COMPLETED
            scene.last_error = None
            scene.regeneration_count = (scene.regeneration_count or 0) + 1
            await _update_episode_costs(db, episode_id)
            await db.commit()

            logger.info(f"Scene {scene_number}: Video regenerated via shared service")
            return f"Scene {scene_number} video regenerated"

        except Exception as e:
            logger.error(f"Scene {scene_number}: Video regeneration failed: {e}")
            scene.status = SceneStatus.FAILED
            scene.last_error = str(e)
            scene.retry_count += 1
            await db.commit()
            raise



def _init_worker_db():
    """Initialize a fresh DB engine for the RQ worker process."""
    import app.database as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.config import settings

    db_module.engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    db_module.async_session_maker = async_sessionmaker(
        db_module.engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def _init_worker_logging():
    """Initialize logging for the RQ worker process."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )


def _run_scene_image(episode_id: int, scene_number: int, frame_type: str = "start") -> str:
    """Worker function: generate image for a single scene."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_scene_image(episode_id, scene_number, frame_type))


async def _ensure_runpod_ready(timeout: int = 300) -> None:
    """Check ComfyUI pod is running, auto-start if stopped. Waits up to timeout seconds."""
    import httpx
    from app.config import settings

    comfyui_url = settings.COMFYUI_URL
    api_key = settings.RUNPOD_API_KEY
    pod_id = settings.RUNPOD_POD_ID

    # Quick health check
    try:
        _health_url = f"{comfyui_url}/system_stats"
        logger.info(f"[API:runpod] Health check: GET {_health_url}")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_health_url)
            logger.info(f"[API:runpod] Health check response: {resp.status_code}")
            if resp.status_code == 200:
                logger.info("RunPod ComfyUI pod is ready")
                return
    except Exception as _hc_err:
        logger.info(f"[API:runpod] Health check failed: {_hc_err}")

    logger.warning("RunPod ComfyUI pod is not responding — attempting to start it")

    if not api_key:
        raise RuntimeError("RUNPOD_API_KEY not set — cannot auto-start pod")

    # Start the pod via RunPod GraphQL API
    _resume_payload = {"query": f'mutation {{ podResume(input: {{ podId: \"{pod_id}\", gpuCount: 1 }}) {{ id desiredStatus }} }}'}
    log_api_request(logger, "runpod", "graphql/podResume", _resume_payload)
    _t0_resume = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.runpod.io/graphql",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=_resume_payload,
        )
        data = resp.json()
        _elapsed_resume = int((time.monotonic() - _t0_resume) * 1000)
        if "errors" in data:
            error_msg = data["errors"][0].get("message", "Unknown RunPod error")
            log_api_response(logger, "runpod", "graphql/podResume", "error", data, _elapsed_resume)
            raise RuntimeError(f"Failed to start RunPod pod: {error_msg}")
        log_api_response(logger, "runpod", "graphql/podResume", "ok", data, _elapsed_resume)
        logger.info(f"RunPod pod resume requested: {data}")

    # Poll until ComfyUI is ready
    import asyncio
    for i in range(timeout // 5):
        await asyncio.sleep(5)
        elapsed = (i + 1) * 5
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{comfyui_url}/system_stats")
                logger.debug(f"[API:runpod] Poll health check: {resp.status_code} ({elapsed}s)")
                if resp.status_code == 200:
                    logger.info(f"RunPod ComfyUI pod ready after {elapsed}s")
                    return
        except Exception as _poll_err:
            logger.debug(f"[API:runpod] Poll health check failed: {_poll_err} ({elapsed}s)")
        if elapsed % 30 == 0:
            logger.info(f"Waiting for RunPod pod to start... {elapsed}s elapsed")

    raise RuntimeError(f"RunPod pod did not become ready within {timeout}s")


async def _async_scene_image(episode_id: int, scene_number: int, frame_type: str = "start", set_completed: bool = True) -> str:
    """Async worker: generate a scene image. Delegates to shared service."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import async_session_maker
    from app.models.episode import Episode as _Ep
    from app.models.scene import Scene, SceneStatus
    from app.services.scene_image_service import generate_scene_image
    from app.services.storage import StorageService

    logger.info(f"Scene {scene_number}: Starting {frame_type} frame image generation (shared service)")

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character))
            .where(Scene.episode_id == episode_id, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            raise ValueError(f"Scene {scene_number} not found for episode {episode_id}")

        ep = await db.get(_Ep, episode_id)
        race_id = ep.race_id if ep and ep.race_id else 0

        # Load episode-level character appearances for clothing consistency
        episode_appearances = None
        if ep and hasattr(ep, "character_appearances"):
            episode_appearances = ep.character_appearances

        storage = StorageService()

        try:
            await generate_scene_image(
                db, scene, episode_id, race_id, storage,
                frame_type=frame_type,
                episode_character_appearances=episode_appearances,
            )

            if set_completed:
                scene.status = SceneStatus.COMPLETED

            await _update_episode_costs(db, episode_id)
            await db.commit()

            logger.info(f"Scene {scene_number}: {frame_type} frame generated via shared service")
            return f"Scene {scene_number} {frame_type} frame generated"

        except Exception as e:
            logger.error(f"Scene {scene_number}: Image generation failed: {e}")
            scene.status = SceneStatus.FAILED
            scene.last_error = str(e)
            scene.retry_count = (scene.retry_count or 0) + 1
            await db.commit()
            raise



def _run_scene_all(episode_id: int, scene_number: int) -> str:
    """Worker function: regenerate image + video for a single scene (sequential)."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_scene_all(episode_id, scene_number))




MAX_IMAGE_RETRIES = 2
MAX_VIDEO_RETRIES = 1


# Use shared prompt adaptation from scene_validator

async def _async_scene_all(episode_id: int, scene_number: int) -> str:
    """Async worker: generate image + video with validation. Delegates to shared orchestrator."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import async_session_maker
    from app.models.episode import Episode as _Ep
    from app.models.scene import Scene
    from app.services.scene_orchestrator import process_scene
    from app.services.storage import StorageService

    logger.info(f"Scene {scene_number}: Starting full scene generation (shared orchestrator)")

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character), selectinload(Scene.voiceover_character))
            .where(Scene.episode_id == episode_id, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            raise ValueError(f"Scene {scene_number} not found for episode {episode_id}")

        ep = await db.get(_Ep, episode_id)
        race_id = ep.race_id if ep and ep.race_id else 0

        episode_appearances = None
        if ep and hasattr(ep, "character_appearances"):
            episode_appearances = ep.character_appearances

        # Count total scenes for FLF eligibility
        from sqlalchemy import func
        total_count = await db.scalar(
            select(func.count()).where(Scene.episode_id == episode_id)
        )

        storage = StorageService()

        scene_result = await process_scene(
            db=db,
            scene=scene,
            episode_id=episode_id,
            race_id=race_id,
            storage=storage,
            scene_index=scene.scene_number - 1,  # 0-based
            total_scenes=total_count or 26,
            episode_character_appearances=episode_appearances,
            skip_if_completed=False,
        )

        await _update_episode_costs(db, episode_id)
        await db.commit()

        if scene_result.status == "failed":
            raise RuntimeError(
                f"Scene {scene_number} failed: {scene_result.error}"
            )

        logger.info(f"Scene {scene_number}: Full generation complete via shared orchestrator")
        return f"Scene {scene_number} fully generated"


def enqueue_stitch(episode_id: int) -> str:
    """Enqueue a video stitching job for the given episode."""
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_stitch",
        episode_id,
        job_timeout=1800,       # 30 minutes (libx264 encoding is slow on VPS)
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "type": "stitch"},
    )
    logger.info(f"Enqueued stitch job {job.id} for episode {episode_id}")
    return job.id


def enqueue_youtube_upload(episode_id: int, privacy_status: str = "public") -> str:
    """Enqueue a YouTube upload job for the given episode."""
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_youtube_upload",
        episode_id,
        privacy_status,
        job_timeout=1800,       # 30 minutes (large uploads)
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "type": "youtube_upload"},
    )
    logger.info(f"Enqueued YouTube upload job {job.id} for episode {episode_id}")
    return job.id


def enqueue_validate(episode_id: int) -> str:
    """Enqueue a quality validation job for the given episode."""
    queue = get_queue()
    job: Job = queue.enqueue(
        "app.jobs._run_validate",
        episode_id,
        job_timeout=900,        # 15 minutes
        result_ttl=86400,
        failure_ttl=604800,
        meta={"episode_id": episode_id, "type": "validate"},
    )
    logger.info(f"Enqueued validation job {job.id} for episode {episode_id}")
    return job.id


def _run_stitch(episode_id: int) -> str:
    """Worker function: stitch all scene clips into final video."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_stitch(episode_id))


def _run_youtube_upload(episode_id: int, privacy_status: str = "public") -> str:
    """Worker function: upload final video to YouTube."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_youtube_upload(episode_id, privacy_status=privacy_status))


def _run_validate(episode_id: int) -> str:
    """Worker function: validate all scenes in an episode."""
    import asyncio
    _init_worker_logging()
    _init_worker_db()
    return asyncio.run(_async_validate(episode_id))


async def _async_stitch(episode_id: int) -> str:
    """Async worker: stitch all scene clips into a final episode video."""
    import os
    from datetime import datetime
    from sqlalchemy import select
    from app.database import async_session_maker
    from app.models.episode import Episode, EpisodeStatus
    from app.models.scene import Scene, SceneStatus
    from app.services.stitcher import VideoStitcher
    from app.services.storage import StorageService

    logger.info(f"Episode {episode_id}: Starting stitch job")
    storage = StorageService()
    stitcher = VideoStitcher()

    # Progress tracking via RQ job meta
    import rq
    job = rq.get_current_job()
    def _update_progress(step, message, progress=0, total=0):
        if job:
            job.meta = {"step": step, "message": message, "progress": progress, "total": total}
            job.save_meta()

    async with async_session_maker() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        # Load race for title/subtitle info
        race = None
        if episode.race_id:
            from app.models.race import Race
            race = await db.get(Race, episode.race_id)

        # Verify all scenes completed
        stmt = (
            select(Scene)
            .where(Scene.episode_id == episode_id, Scene.status == SceneStatus.COMPLETED)
            .order_by(Scene.scene_number)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        total_stmt = select(Scene).where(Scene.episode_id == episode_id)
        total_result = await db.execute(total_stmt)
        total_scenes = len(total_result.scalars().all())

        if len(scenes) == 0:
            raise ValueError(f"No completed scenes for episode {episode_id}")

        logger.info(f"Episode {episode_id}: {len(scenes)}/{total_scenes} scenes completed, starting stitch")

        # Update status
        episode.status = EpisodeStatus.STITCHING
        await db.commit()

        # Download scene clips to local temp
        _update_progress("downloading", f"Downloading {len(scenes)} clips from storage...", 0, len(scenes))
        clip_paths = []
        work_dir = f"/tmp/videos/episode_{episode_id}"
        os.makedirs(work_dir, exist_ok=True)

        for scene in scenes:
            if scene.video_clip_path:
                local_path = os.path.join(work_dir, f"clip_{scene.scene_number:02d}.mp4")
                bucket, object_name = scene.video_clip_path.split("/", 1)
                await storage.download_file(bucket, object_name, local_path)
                clip_paths.append(local_path)
                _update_progress("downloading", f"Downloaded clip {len(clip_paths)}/{len(scenes)}...", len(clip_paths), len(scenes))

        if not clip_paths:
            episode.status = EpisodeStatus.FAILED
            episode.last_error = "No video clips found to stitch"
            await db.commit()
            raise ValueError("No video clips found")

        # Build title/subtitle
        race_name = race.race_name if race else "F1 Race"
        title = episode.title or race_name
        subtitle = f"Season {race.season if race else 2026} | Episode {episode_id} | {race_name}"

        # Build outro text
        next_episode_text = ""
        if race:
            from sqlalchemy import and_
            from app.models.race import Race as RaceModel
            next_race_stmt = (
                select(RaceModel)
                .where(
                    and_(
                        RaceModel.season == race.season,
                        RaceModel.round_number > race.round_number,
                    )
                )
                .order_by(RaceModel.round_number)
                .limit(1)
            )
            next_race_result = await db.execute(next_race_stmt)
            next_race = next_race_result.scalar_one_or_none()
            if next_race:
                next_episode_text = f"Next: {next_race.race_name}"

        # Stitch (normalize + concat)
        _update_progress("stitching", f"Stitching {len(clip_paths)} clips (normalize + concat)...", 0, len(clip_paths))
        stitch_result = await stitcher.stitch(
            episode_id=episode_id,
            clip_paths=clip_paths,
            title=title,
            subtitle=subtitle,
            next_episode_text=next_episode_text,
            circuit_name=race.circuit_name if race else "",
        )

        # Upload final video to MinIO
        _update_progress("uploading", "Uploading final video to storage...", 0, 1)
        final_path = await storage.upload_final_video(
            race_id=race.id if race else 0,
            episode_id=episode_id,
            file_path=stitch_result.output_path,
        )

        # Update episode
        episode.final_video_path = final_path
        episode.duration_seconds = stitch_result.duration_seconds
        episode.generation_completed_at = datetime.utcnow()

        if episode.generation_started_at:
            gen_time = (datetime.utcnow() - episode.generation_started_at).total_seconds()
            episode.generation_time_seconds = int(gen_time)

        # Stitching complete — set to COMPLETED (ready for YouTube upload)
        episode.status = EpisodeStatus.COMPLETED
        await db.commit()

        # Cleanup temp files
        await stitcher.cleanup(episode_id)

        # Update episode costs
        await _update_episode_costs(db, episode_id)

        logger.info(f"Episode {episode_id}: Stitch complete → {final_path}")
        duration = stitch_result.duration_seconds
        size_mb = stitch_result.file_size_bytes / (1024 * 1024)
        _update_progress("complete", f"Stitch complete — {duration}s, {size_mb:.1f}MB")
        return final_path


async def _async_youtube_upload(episode_id: int, privacy_status: str = "public") -> str:
    """Async worker: upload final video to YouTube."""
    import os
    from datetime import datetime
    from app.database import async_session_maker
    from app.models.episode import Episode, EpisodeStatus
    from app.services.youtube_uploader import YouTubeUploader
    from app.services.storage import StorageService

    logger.info(f"Episode {episode_id}: Starting YouTube upload job")
    storage = StorageService()

    async with async_session_maker() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        if not episode.final_video_path:
            raise ValueError(f"Episode {episode_id} has no final video to upload")

        # Load race for metadata
        race = None
        if episode.race_id:
            from app.models.race import Race
            race = await db.get(Race, episode.race_id)

        # Update status
        episode.status = EpisodeStatus.UPLOADING
        episode.upload_started_at = datetime.utcnow()
        await db.commit()

        # Download final video from MinIO
        local_path = f"/tmp/videos/episode_{episode_id}_final.mp4"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        bucket, object_name = episode.final_video_path.split("/", 1)
        await storage.download_file(bucket, object_name, local_path)

        # Build YouTube metadata
        title = episode.title
        if race:
            title = f"{episode.title} | F1 {race.season} Round {race.round_number}"
        description = _build_youtube_description(episode, race)
        tags = [
            "F1", "Formula 1", "Formula One", "racing", "motorsport",
            "satire", "comedy", "AI generated", "caricature",
            "F1 highlights", "race recap", "F1 commentary",
            "Antikythera", "AI video", "animated F1",
        ]
        if race:
            tags.extend([
                race.race_name,
                race.circuit_name or "",
                race.country or "",
                f"{race.season} F1",
                f"F1 {race.season}",
            ])

        # Upload
        uploader = YouTubeUploader()
        try:
            result = await uploader.upload(
                video_path=local_path,
                title=title,
                description=description,
                tags=tags,
                privacy_status=privacy_status,
            )

            episode.youtube_video_id = result.video_id
            episode.youtube_url = result.youtube_url
            episode.published_at = datetime.utcnow()
            episode.status = EpisodeStatus.PUBLISHED
            await db.commit()

            logger.info(f"Episode {episode_id}: YouTube upload complete → {result.youtube_url}")
            return result.youtube_url

        except Exception as e:
            logger.error(f"Episode {episode_id}: YouTube upload failed: {e}")
            episode.status = EpisodeStatus.FAILED
            episode.last_error = f"YouTube upload failed: {str(e)}"
            await db.commit()
            raise
        finally:
            # Clean up temp file
            if os.path.exists(local_path):
                os.remove(local_path)


async def _async_validate(episode_id: int) -> str:
    """Async worker: validate all scenes in an episode using Claude Vision."""
    import json
    from sqlalchemy import select
    from app.database import async_session_maker
    from app.models.scene import Scene, SceneStatus
    from app.services.scene_validator import SceneValidator

    logger.info(f"Episode {episode_id}: Starting validation job")
    validator = SceneValidator()

    # Progress tracking via RQ job meta
    import rq as _rq
    _job = _rq.get_current_job()
    def _update_progress(step, message, progress=0, total=0):
        if _job:
            _job.meta = {"step": step, "message": message, "progress": progress, "total": total}
            _job.save_meta()

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .where(Scene.episode_id == episode_id, Scene.status == SceneStatus.COMPLETED)
            .order_by(Scene.scene_number)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        if not scenes:
            logger.warning(f"Episode {episode_id}: No completed scenes to validate")
            return "No scenes to validate"

        logger.info(f"Episode {episode_id}: Validating {len(scenes)} scenes")
        _update_progress("validating", f"Validating {len(scenes)} scenes...", 0, len(scenes))

        episode_validation = await validator.validate_episode(scenes)

        # Update each scene with validation results
        _done = 0
        for scene_result in episode_validation.scene_results:
            scene_stmt = select(Scene).where(
                Scene.episode_id == episode_id,
                Scene.scene_number == scene_result.scene_number,
            )
            scene_row = await db.execute(scene_stmt)
            scene = scene_row.scalar_one_or_none()
            if scene:
                scene.validation_status = "passed" if scene_result.passed else "failed"
                scene.validation_issues = json.dumps(scene_result.issues) if scene_result.issues else None
                _done += 1
                _update_progress("validating", f"Validated scene {_done}/{len(scenes)}...", _done, len(scenes))

        await db.commit()

        summary = (
            f"Validated {episode_validation.total_scenes} scenes: "
            f"{episode_validation.passed_scenes} passed, "
            f"{episode_validation.failed_scenes} failed"
        )
        logger.info(f"Episode {episode_id}: {summary}")
        _update_progress("complete", summary)
        return summary


def _build_youtube_description(episode, race) -> str:
    """Build YouTube video description."""
    lines = [
        episode.title,
        "",
        "Satirical AI-generated F1 commentary. Every driver, every team, "
        "every dramatic moment \u2014 reimagined in caricature.",
        "",
    ]

    if race:
        lines.extend([
            f"\U0001f3c6 {race.season} F1 Season | Round {race.round_number} \u2014 {race.race_name}",
            f"\U0001f4cd {race.circuit_name or 'Unknown'}, {race.country or ''}",
            f"\U0001f4c5 Season {race.season}",
            "",
        ])

    lines.extend([
        "\u2500" * 40,
        "",
        "\u26a0\ufe0f DISCLAIMER: This video is entirely AI-generated satire \u2014 "
        "all characters, voices, and commentary are fictional parodies "
        "created by AI. No real people were harmed in the making of this chaos.",
        "",
        "Built with \u2764\ufe0f by Antikythera Technologies",
        "\U0001f310 https://antikythera.co.za",
        "",
        "#F1 #Formula1 #Racing #Motorsport #F12026 #Satire #AIGenerated #Comedy",
    ])

    return "\n".join(lines)
