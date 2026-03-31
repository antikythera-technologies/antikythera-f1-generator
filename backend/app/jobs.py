"""Job enqueue utilities for the RQ task queue.

Provides a simple interface to enqueue pipeline jobs onto the Redis-backed
RQ queue. The actual work is executed by the worker process defined in
``app.worker``.
"""

from decimal import Decimal
import logging
from typing import Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from app.config import settings

import time
from app.services.api_logger import log_api_request, log_api_response

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
    """Log an API usage record for cost tracking."""
    from app.models.logs import APIUsage, APIProvider
    try:
        usage = APIUsage(
            episode_id=episode_id,
            scene_id=scene_id,
            provider=APIProvider(provider),
            endpoint=endpoint,
            cost_usd=cost_usd,
            response_time_ms=response_time_ms,
        )
        db.add(usage)
        await db.flush()
        logger.debug(f"Logged API cost: {provider} ${cost_usd:.4f} ({endpoint})")
    except Exception as e:
        logger.warning(f"Failed to log API cost: {e}")

# Queue name used across the project


async def _update_episode_costs(db, episode_id: int) -> None:
    """Sum all scene costs and update Episode.total_cost_usd."""
    from sqlalchemy import func, select
    from app.models.scene import Scene
    from app.models.episode import Episode

    result = await db.execute(
        select(
            func.coalesce(func.sum(Scene.image_cost_usd), 0),
            func.coalesce(func.sum(Scene.video_cost_usd), 0),
        ).where(Scene.episode_id == episode_id)
    )
    img_total, vid_total = result.one()
    episode = await db.get(Episode, episode_id)
    if episode:
        episode.total_cost_usd = img_total + vid_total
        await db.flush()
        logger.debug(f"Episode {episode_id}: Updated total cost to ${float(img_total + vid_total):.4f}")

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
    """Async worker: regenerate video for a single scene using configured backend."""
    import os
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.config import settings
    from app.database import async_session_maker
    from app.models.scene import Scene, SceneStatus
    from app.services.storage import StorageService
    from app.services.fal_video_generator import build_f1_video_prompt as _build_f1_prompt

    logger.info(
        f"Scene {scene_number}: Starting video regeneration "
        f"(backend={__import__('app.services.runtime_settings', fromlist=['get_video_generator']).get_video_generator()})"
    )

    async with async_session_maker() as db:
        # Load scene with character
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character), selectinload(Scene.voiceover_character))
            .where(Scene.episode_id == episode_id, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            raise ValueError(f"Scene {scene_number} not found for episode {episode_id}")

        # Load episode race_id for correct storage path
        from app.models.episode import Episode as _EpModelV
        _ep_v = await db.get(_EpModelV, episode_id)
        _race_id = _ep_v.race_id if _ep_v else 0

        # Get the source image path
        image_path = scene.start_frame_path or scene.source_image_path
        if not image_path:
            scene.status = SceneStatus.FAILED
            scene.last_error = "No start frame image — generate image first"
            await db.commit()
            raise ValueError("No start frame image available")

        from app.services.runtime_settings import get_video_generator
        backend = get_video_generator()
        storage = StorageService()

        try:
            scene.status = SceneStatus.GENERATING
            scene.generation_started_at = datetime.utcnow()
            # Reset costs for this regeneration — old costs are sunk
            scene.video_cost_usd = Decimal(0)
            await db.flush()

            if backend.startswith("fal-"):
                # --- fal.ai backend ---
                from app.services.fal_video_generator import FalVideoGenerator

                fal_gen = FalVideoGenerator(backend=backend)

                # Download image from MinIO to local
                local_image = f"/tmp/f1-regen/ep{episode_id}_scene{scene_number:02d}.png"
                os.makedirs(os.path.dirname(local_image), exist_ok=True)
                bucket, obj = image_path.split("/", 1)
                await storage.download_file(bucket, obj, local_image)

                # Upload to fal CDN
                image_url = await fal_gen.upload_image(local_image)

                # Extract voice/accent for speech synthesis (goes into video prompt)
                # Audio prompt is ambient sounds only
                rich_audio = scene.audio_description
                _voice_desc = None
                _voice_char = scene.character or getattr(scene, 'voiceover_character', None)
                if _voice_char and _voice_char.personality:
                    try:
                        import json as _json
                        _p = _json.loads(_voice_char.personality) if isinstance(_voice_char.personality, str) else _voice_char.personality
                        _ss = _p.get("speaking_style", {})
                        _nationality = _p.get("nationality", "")
                        _accent = _ss.get("accent_hints", "") if isinstance(_ss, dict) else ""
                        _tone = _ss.get("tone", "") if isinstance(_ss, dict) else ""
                        _voice_parts = [p for p in [
                            f"{_nationality} accent" if _nationality else "",
                            _accent,
                            _tone,
                        ] if p]
                        _voice_desc = ", ".join(_voice_parts) if _voice_parts else None
                        logger.debug(f"Scene {scene_number}: Voice desc: {_voice_desc}")
                    except Exception as e:
                        logger.warning(f"Scene {scene_number}: Could not build voice prompt: {e}")

                # Upload end frame for FLF if available
                end_image_url = None
                if scene.end_frame_path:
                    from app.services.fal_video_generator import FAL_FLF_CAPABLE
                    if fal_gen.backend in FAL_FLF_CAPABLE:
                        end_local = f"/tmp/f1-regen/ep{episode_id}_scene{scene_number:02d}_end.png"
                        try:
                            end_bucket, end_obj = scene.end_frame_path.split("/", 1)
                            await storage.download_file(end_bucket, end_obj, end_local)
                            end_image_url = await fal_gen.upload_image(end_local)
                            logger.info(f"Scene {scene_number}: End frame uploaded for FLF")
                        except Exception as e:
                            logger.warning(f"Scene {scene_number}: Could not load end frame for FLF: {e}")

                # Load team data for F1 colour context in video prompt
                _scene_team = None
                if scene.character and hasattr(scene.character, 'team_id') and scene.character.team_id:
                    from app.models.team import Team as _TeamModel
                    _scene_team = await db.get(_TeamModel, scene.character.team_id)

                # Extract character animation from personality for video prompt
                _char_anim = None
                _voice_char = scene.character or getattr(scene, 'voiceover_character', None)
                if _voice_char and _voice_char.personality:
                    try:
                        import json as _pjson
                        _p = _pjson.loads(_voice_char.personality) if isinstance(_voice_char.personality, str) else _voice_char.personality
                        from app.services.personality import load_personality_traits_from_db
                        _anim_traits = load_personality_traits_from_db(_p)
                        _char_anim = {
                            "signature_expression": _anim_traits.get("signature_expression"),
                            "signature_pose": _anim_traits.get("signature_pose"),
                            "comedy_angle": _anim_traits.get("comedy_angle"),
                        }
                    except Exception:
                        pass

                # Generate video
                # Sanitize stored video prompt for direction/escalation
                from app.services.script_generator import sanitize_prompt_text as _sanitize_vp
                _raw_vp = (scene.video_prompt or scene.start_frame_prompt or "").replace("ANTKF1STYLE", "").strip()
                _clean_vp = _sanitize_vp(_raw_vp)
                clip = await fal_gen.generate_clip(
                    scene_number=scene_number,
                    image_url=image_url,
                    prompt=_build_f1_prompt(
                        _clean_vp,
                        scene_type=str(scene.scene_type) if scene.scene_type else None,
                        face_visible=bool(scene.face_visible),
                        dialogue=scene.dialogue,
                        team_name=_scene_team.name if _scene_team else None,
                        car_description=_scene_team.car_description if _scene_team else None,
                        overalls_description=_scene_team.overalls_description if _scene_team else None,
                        camera_direction=scene.camera_direction,
                        character_animation=_char_anim,
                        livery_description=_scene_team.livery_description if _scene_team else None,
                    ),
                    dialogue=scene.dialogue,
                    audio_description=rich_audio,
                    face_visible=bool(scene.face_visible),
                    end_image_url=end_image_url,
                    voice_description=_voice_desc,
                )
                video_local = clip.video_path

            elif backend in ("ovi", "runpod-ovi"):
                # --- RunPod Ovi backend ---
                from app.services.ovi_space_manager import RunPodManager as OviSpaceManager

                local_image = f"/tmp/f1-regen/ep{episode_id}_scene{scene_number:02d}.png"
                os.makedirs(os.path.dirname(local_image), exist_ok=True)
                bucket, obj = image_path.split("/", 1)
                await storage.download_file(bucket, obj, local_image)

                async with OviSpaceManager(quality=settings.OVI_QUALITY) as ovi:
                    # Build Ovi prompt
                    parts = [scene.video_prompt or scene.start_frame_prompt or "Character speaking"]
                    if scene.dialogue:
                        parts.append(f"<S>{scene.dialogue}<E>")
                    if scene.audio_description:
                        parts.append(f"<AUDCAP>{scene.audio_description}<ENDAUDCAP>")
                    prompt = " ".join(parts)

                    video_local = await ovi.generate_video(
                        image_path=local_image,
                        prompt=prompt,
                    )
            else:
                raise ValueError(f"Unsupported backend for single-scene regen: {backend}")

            # Upload video to MinIO
            clip_path = await storage.upload_video_clip(
                race_id=_race_id,
                episode_id=episode_id,
                scene_number=scene_number,
                file_path=video_local,
            )

            generation_time_ms = int(
                (datetime.utcnow() - scene.generation_started_at).total_seconds() * 1000
            )

            scene.video_clip_path = clip_path
            scene.video_generator = backend
            scene.audio_clip_path = None  # Clear — new video has different audio
            scene.status = SceneStatus.COMPLETED
            scene.generation_completed_at = datetime.utcnow()
            scene.generation_time_ms = generation_time_ms
            scene.last_error = None

            # Duration-based video cost (accumulates on regeneration)
            from app.services.fal_video_generator import FAL_COST_PER_SECOND, FalBackend
            cost_per_sec = FAL_COST_PER_SECOND.get(
                FalBackend(backend) if backend.startswith("fal-") else None,
                0.04,  # fallback
            )
            duration = float(scene.duration_seconds or 5)
            video_cost = Decimal(str(round(duration * cost_per_sec, 6)))
            scene.video_cost_usd = (scene.video_cost_usd or Decimal(0)) + video_cost
            scene.regeneration_count = (scene.regeneration_count or 0) + 1
            await _log_api_cost(
                db, episode_id, scene.id,
                provider=backend if backend.startswith("fal-") else "ovi",
                endpoint=f"fal.ai/{backend}",
                cost_usd=float(video_cost),
                response_time_ms=generation_time_ms,
            )

            await db.commit()
            await _update_episode_costs(db, episode_id)
            logger.info(f"Scene {scene_number}: Video regenerated in {generation_time_ms}ms")
            return f"Scene {scene_number} video regenerated ({backend})"

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
    import json
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
    """Async worker: generate a scene image via fal.ai flux-lora."""
    import os
    import tempfile
    from datetime import datetime

    import httpx
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.config import settings
    from app.database import async_session_maker
    from app.models.scene import Scene, SceneStatus
    from app.services.personality import load_personality_traits_from_db
    from app.services.storage import StorageService

    FAL_KEY = os.environ.get("FAL_KEY", "")
    LORA_URL = "https://v3b.fal.media/files/b/0a918355/tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors"

    if not FAL_KEY:
        raise RuntimeError("FAL_KEY environment variable not set")

    logger.info(f"Scene {scene_number}: Starting {frame_type} frame image generation via fal.ai")

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

        # Load episode race_id for correct storage path
        from app.models.episode import Episode as _EpModelI
        _ep_i = await db.get(_EpModelI, episode_id)
        _race_id = _ep_i.race_id if _ep_i else 0

        # Determine which prompt to use
        if frame_type == "end":
            frame_prompt = scene.end_frame_prompt
        else:
            frame_prompt = scene.start_frame_prompt


        # Sanitize stored prompts — they may predate direction/escalation fixes
        from app.services.script_generator import sanitize_prompt_text
        frame_prompt = sanitize_prompt_text(frame_prompt)
        if not frame_prompt:
            scene.status = SceneStatus.FAILED
            scene.last_error = f"No {frame_type}_frame_prompt set"
            await db.commit()
            raise ValueError(f"No {frame_type}_frame_prompt for scene {scene_number}")

        # Load character traits for prompt enrichment
        character_traits: dict = {}
        if scene.character:
            character = scene.character
            if character.personality:
                try:
                    character_traits = load_personality_traits_from_db(character.personality)
                except Exception as e:
                    logger.warning(f"Could not parse personality for {character.name}: {e}")
                    character_traits = {
                        "display_name": character.display_name,
                        "team": character.team,
                    }
            else:
                character_traits = {
                    "display_name": character.display_name,
                    "team": character.team,
                }

        # Load episode-level character appearance for clothing consistency
        episode_appearance = ""
        if scene.character:
            from app.models.episode import Episode
            ep_stmt = select(Episode).where(Episode.id == episode_id)
            ep_result = await db.execute(ep_stmt)
            episode = ep_result.scalar_one_or_none()
            if episode and episode.character_appearances:
                episode_appearance = episode.character_appearances.get(
                    scene.character.name, ""
                )
                if episode_appearance:
                    logger.info(
                        f"Scene {scene_number}: Using episode appearance for {scene.character.name}"
                    )

        # Determine if face reference is needed for this scene
        use_face_reference = getattr(scene, 'face_visible', True) and scene.character_id is not None

        # Build prompt based on scene type
        if not use_face_reference:
            # Landscape prompt WITH LoRA trigger for consistent caricature style
            racing_direction_rule = ""
            racing_keywords = ["car", "cars", "race", "racing", "overtake", "track", "circuit",
                               "straight", "corner", "grid", "cockpit", "onboard", "on-board"]
            if any(kw in (frame_prompt or "").lower() for kw in racing_keywords):
                # Detect POV/cockpit shots vs external shots
                pov_keywords = ["cockpit pov", "onboard", "on-board", "helmet cam", "driver pov"]
                is_pov = any(kw in (frame_prompt or "").lower() for kw in pov_keywords)
                if is_pov:
                    racing_direction_rule = (
                        "CRITICAL: This is a cockpit/driver POV shot looking forward through the halo. "
                        "Any cars visible AHEAD must be driving AWAY from the camera — "
                        "show their REAR wings, rear diffusers, and exhaust. "
                        "The viewer sees the BACK of the cars in front, NOT their front. "
                        "No car should face towards the camera. "
                        "TRACK LAYOUT: Tarmac surface in the centre, kerbs (red-white or yellow) on BOTH EDGES of the track only. "
                        "There is NO kerb, barrier, or divider in the middle of the track. The track is one continuous surface. "
                        "GRID SIZE: Maximum 22 cars on track (11 teams x 2 drivers). Never show more than 22 cars. "
                    )
                else:
                    racing_direction_rule = (
                        "ALL cars MUST face the SAME direction, driving AWAY from the camera. "
                        "Show only the REAR of every car — rear wings, rear diffusers, exhaust, rear tyres. "
                        "NO car faces towards the camera. NO car faces the opposite direction. "
                        "TRACK LAYOUT: Tarmac surface in the centre, kerbs (red-white or yellow) on BOTH EDGES only. "
                        "NO kerb, barrier, or divider in the middle of the track. One continuous racing surface. "
                        "Maximum 22 cars on track (11 teams x 2 drivers). "
                        "F1 cars are open-cockpit single-seaters with NO roof. The halo is a thin curved bar above the driver, NOT a canopy or roof. "
                    )
            # For ALL non-face scenes: enforce F1 car count
            # ESTABLISHING shots: focus on environment, minimal cars
            scene_type_upper = (getattr(scene, 'scene_type', '') or '').upper()
            if scene_type_upper in ('ESTABLISHING', 'TITLE_CARD'):
                racing_direction_rule += (
                    "IMPORTANT: This is an atmospheric/establishing shot. "
                    "Focus on the ENVIRONMENT — circuit, skyline, sunset, paddock. "
                    "Show at most 3-5 cars in the background, NOT a full grid. "
                    "Cars are secondary to the setting. "
                    "F1 has only 22 cars total (11 teams x 2). NEVER show more than 22 cars. "
                )
            elif not racing_direction_rule:
                # Non-racing, non-establishing: still cap car count
                racing_direction_rule = (
                    "F1 has exactly 22 cars (11 teams x 2 drivers). "
                    "NEVER show more than 22 cars in any scene. "
                )

            # Enrich with team livery for racing scenes
            team_livery_text = ""
            if scene.character_id and scene.character:
                team_obj = None
                if hasattr(scene.character, 'team_id') and scene.character.team_id:
                    from app.models.team import Team
                    team_obj = await db.get(Team, scene.character.team_id)
                if team_obj and team_obj.car_description:
                    team_livery_text = f"The car is a {team_obj.car_description}. "

            full_prompt = (
                f"ANTKF1STYLE {team_livery_text}{frame_prompt} "
                f"{racing_direction_rule}"
                "Satirical caricature art style, dramatic lighting, vibrant colors. "
                "No text, no words, no letters, no watermarks."
            )
        else:
            # Character scene: LoRA trigger + caricature style + character traits

            # Safety net: rewrite tight framing keywords to prevent head/hair cropping
            import re as _re
            frame_prompt = _re.sub(r'(?i)MEDIUM\s+CLOSE[- ]?UP', 'MEDIUM SHOT', frame_prompt)
            frame_prompt = _re.sub(r'(?i)EXTREME\s+CLOSE[- ]?UP', 'MEDIUM SHOT', frame_prompt)
            frame_prompt = _re.sub(r'(?i)CLOSE[- ]?UP', 'MEDIUM SHOT', frame_prompt)

            physical = character_traits.get("physical_features", "")
            prompt_parts = ["WIDE MEDIUM SHOT showing full character from knees up, camera 5 meters away, plenty of headroom above the head.", frame_prompt]
            # Team overalls from DB are ground truth — always prefer over LLM-generated appearance
            if scene.character and hasattr(scene.character, 'team_id') and scene.character.team_id:
                from app.models.team import Team
                team_obj = await db.get(Team, scene.character.team_id)
                if team_obj and team_obj.overalls_description:
                    episode_appearance = team_obj.overalls_description

            if episode_appearance:
                prompt_parts.append(
                    f"MANDATORY CLOTHING: The character MUST wear {episode_appearance}. "
                    f"This is a Formula 1 driver — they ALWAYS wear their team race suit, "
                    f"NEVER a business suit, casual clothes, or any other outfit."
                )
            elif physical:
                prompt_parts.append(f"Character physical traits: {physical}")
            prompt_parts.append(
                "Satirical caricature style with oversized head, "
                "photorealistic skin with visible pores. Dramatic lighting with deep shadows. "
                "CRITICAL FRAMING: The character must be shown from the knees or waist up. "
                "Full head, all hair, and both shoulders MUST be visible with clear space above the head. "
                "NEVER crop the top of the head. Camera is far back, NOT close to the face. "
                "No text, no words, no letters, no logos, no watermarks on clothing or background."
            )
            full_prompt = " ".join(prompt_parts)

        storage = StorageService()

        try:
            started_at = datetime.utcnow()
            scene.status = SceneStatus.GENERATING
            scene.generation_started_at = started_at
            # Reset costs for this regeneration — old costs are sunk
            scene.image_cost_usd = Decimal(0)
            await db.flush()

            # Upload face reference to fal CDN — only for character scenes
            face_ref_url = None
            if scene.character and use_face_reference:
                face_local = await storage.download_face_reference(scene.character.name)
                if face_local:
                    import fal_client
                    logger.info(f"[API:fal-image] Uploading face reference: {face_local}")
                    _t0_face = time.monotonic()
                    face_ref_url = fal_client.upload_file(face_local)
                    _elapsed_face = int((time.monotonic() - _t0_face) * 1000)
                    logger.info(f"[API:fal-image] Face reference uploaded in {_elapsed_face}ms: {face_ref_url[:80]}...")

                    # Track which face reference was used
                    scene.face_reference_url = face_ref_url

                    # Link to the CharacterImage record (primary image for this character)
                    from app.models.character import CharacterImage
                    ci_stmt = (
                        select(CharacterImage)
                        .where(CharacterImage.character_id == scene.character_id)
                        .order_by(CharacterImage.is_primary.desc(), CharacterImage.id)
                        .limit(1)
                    )
                    ci_result = await db.execute(ci_stmt)
                    ci = ci_result.scalar_one_or_none()
                    if ci:
                        scene.character_image_id = ci.id
                        logger.debug(f"Scene {scene_number}: Linked to CharacterImage {ci.id}")

            # Choose image backend
            from app.services.runtime_settings import get_image_generator
            image_backend = get_image_generator()

            if not use_face_reference:
                # No face visible — flux-lora (LoRA style only, no face reference)
                image_backend = "flux-lora"
                logger.info(f"Scene {scene_number}: Using flux-lora (face_visible={getattr(scene, 'face_visible', True)}, no character face)")
            elif face_ref_url:
                # Face visible + character assigned + face ref available — instant-character
                image_backend = "instant-character"
                logger.info(f"Scene {scene_number}: Using instant-character (face_visible=True, face ref available)")
            else:
                # Face visible but no face ref file — fall back to flux-lora
                image_backend = "flux-lora"
                logger.info(f"Scene {scene_number}: Using flux-lora (face_visible=True but no face ref file)")

            if image_backend == "instant-character" and face_ref_url:
                # --- Instant Character via fal_client.subscribe (faster than HTTP queue) ---
                import fal_client as _fal

                # Generate taller (4:3) to give headroom, then crop to 16:9.
                # Instant-character inherently zooms into the face reference,
                # so we give it extra vertical space and crop the excess.
                _ic_args = {
                        "prompt": full_prompt,
                        "image_url": face_ref_url,
                        "negative_prompt": (
                            "cropped head, cut off head, cut off hair, top of head missing, "
                            "forehead cropped, extreme close-up, tight crop, face filling frame, "
                            "zoomed in, macro, portrait crop, chin to forehead only, "
                            "shoulder-up only, passport photo, mugshot, headshot, face only"
                        ),
                        "image_size": {"width": 1280, "height": 1280},
                        "num_inference_steps": 28,
                        "guidance_scale": 3.5,
                        "scale": 0.3,
                        "output_format": "png",
                        "loras": [{"path": LORA_URL, "scale": 1.0, "trigger_word": "ANTKF1STYLE"}],
                    }
                _t0_ic = time.monotonic()
                log_api_request(logger, "fal-image", "fal-ai/instant-character", _ic_args)
                logger.info(f"[API:fal-image] PROMPT: {full_prompt}")

                _ic_result = _fal.subscribe(
                    "fal-ai/instant-character",
                    arguments=_ic_args,
                    with_logs=True,
                )
                _elapsed_ic = int((time.monotonic() - _t0_ic) * 1000)
                log_api_response(logger, "fal-image", "fal-ai/instant-character", "ok", _ic_result, _elapsed_ic)

                _ic_images = _ic_result.get("images", [])
                if not _ic_images:
                    raise RuntimeError("fal.ai instant-character returned no images")

                _ic_url = _ic_images[0]["url"]
                logger.info(f"Scene {scene_number}: instant-character done, downloading...")

                async with httpx.AsyncClient(timeout=120) as _dl:
                    _img_resp = await _dl.get(_ic_url)
                    _img_resp.raise_for_status()

                tmp_path = os.path.join(tempfile.gettempdir(), f"f1_scene_{episode_id}_{scene_number:02d}_{frame_type}.png")

                # Crop from 1280x960 (4:3) to 1280x720 (16:9)
                # Take the top 720px to preserve head/hair, trim excess below waist
                from PIL import Image as _PILImage
                import io as _io
                _img_full = _PILImage.open(_io.BytesIO(_img_resp.content))
                if _img_full.height > 720:
                    _img_cropped = _img_full.crop((0, 0, _img_full.width, 720))
                    _img_cropped.save(tmp_path, "PNG")
                    logger.info(f"Scene {scene_number}: Cropped {_img_full.width}x{_img_full.height} -> {_img_cropped.width}x{_img_cropped.height}")
                else:
                    with open(tmp_path, "wb") as f:
                        f.write(_img_resp.content)

                logger.info(f"Scene {scene_number}: Image downloaded ({len(_img_resp.content) / 1024:.0f} KB)")

                # Upload to MinIO
                image_storage_path = await storage.upload_scene_image(
                    race_id=_race_id,
                    episode_id=episode_id,
                    scene_number=scene_number,
                    file_path=tmp_path,
                    suffix=frame_type,
                )

                generation_time_ms = int(
                    (datetime.utcnow() - started_at).total_seconds() * 1000
                )

                if frame_type == "start":
                    scene.start_frame_path = image_storage_path
                    scene.source_image_path = image_storage_path
                else:
                    scene.end_frame_path = image_storage_path

                scene.status = SceneStatus.COMPLETED if set_completed else SceneStatus.GENERATING
                scene.generation_completed_at = datetime.utcnow()
                scene.generation_time_ms = generation_time_ms
                scene.image_cost_usd = (scene.image_cost_usd or Decimal(0)) + Decimal("0.04")
                scene.image_backend = "instant-character"
                scene.instant_character_used = True
                scene.lora_used = True
                scene.regeneration_count = (scene.regeneration_count or 0) + 1
                scene.last_error = None

                await db.commit()
                # Verify the path was persisted
                await db.refresh(scene)
                if frame_type == "start" and not scene.start_frame_path:
                    raise RuntimeError(
                        f"Scene {scene_number}: start_frame_path NULL after commit — storage may have failed"
                    )
                # Log image generation cost
                await _log_api_cost(
                    db, episode_id, scene.id,
                    provider="fal-image",
                    endpoint="fal-ai/instant-character",
                    cost_usd=0.04,
                    response_time_ms=generation_time_ms,
                )
                await _update_episode_costs(db, episode_id)

                logger.info(f"Scene {scene_number}: {frame_type} frame generated in {generation_time_ms}ms via instant-character")
                return f"Scene {scene_number} {frame_type} frame generated (instant-character)"

            if not (image_backend == "instant-character" and face_ref_url):
                # --- Flux LoRA: style-only, no face reference (default) ---
                endpoint = "fal-ai/flux-lora"
                logger.info(f"Scene {scene_number}: Submitting to {endpoint}...")

                fal_payload = {
                    "prompt": full_prompt,
                    "image_size": {"width": 1280, "height": 720},
                    "num_images": 1,
                    "num_inference_steps": 28,
                    "guidance_scale": 3.5,
                    "loras": [{"path": LORA_URL, "scale": 1.0}],
                    "output_format": "png",
                }

            # Submit to fal.ai
            _t0_flux = time.monotonic()
            log_api_request(logger, "fal-image", "fal-ai/flux-lora", fal_payload)
            logger.info(f"[API:fal-image] PROMPT: {full_prompt}")
            async with httpx.AsyncClient(timeout=300) as client:
                # Submit request
                submit_resp = await client.post(
                    f"https://queue.fal.run/{endpoint}",
                    headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
                    json=fal_payload,
                )
                submit_resp.raise_for_status()
                submit_data = submit_resp.json()
                request_id = submit_data.get("request_id")
                status_url = submit_data.get("status_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}/status")
                response_url = submit_data.get("response_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}")

                logger.info(f"Scene {scene_number}: fal.ai request {request_id} submitted")

                # Poll for completion (max 5 minutes)
                import asyncio
                for i in range(60):
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        status_url,
                        headers={"Authorization": f"Key {FAL_KEY}"},
                    )
                    status_data = status_resp.json()
                    status = status_data.get("status", "")

                    if status == "COMPLETED":
                        break
                    elif status in ("FAILED", "CANCELLED"):
                        error_msg = status_data.get("error", "fal.ai generation failed")
                        raise RuntimeError(f"fal.ai: {error_msg}")

                    if (i + 1) % 6 == 0:
                        logger.info(f"Scene {scene_number}: Waiting for fal.ai... {(i+1)*5}s")
                else:
                    raise RuntimeError("fal.ai generation timed out after 5 minutes")

                # Get result
                result_resp = await client.get(
                    response_url,
                    headers={"Authorization": f"Key {FAL_KEY}"},
                )
                result_resp.raise_for_status()
                result_data = result_resp.json()
                _elapsed_flux = int((time.monotonic() - _t0_flux) * 1000)
                log_api_response(logger, "fal-image", "fal-ai/flux-lora", "ok", result_data, _elapsed_flux)

                images = result_data.get("images", [])
                if not images:
                    raise RuntimeError("fal.ai returned no images")

                image_url = images[0]["url"]

                # Download the generated image
                img_resp = await client.get(image_url)
                img_resp.raise_for_status()

                tmp_path = os.path.join(tempfile.gettempdir(), f"f1_scene_{episode_id}_{scene_number:02d}_{frame_type}.png")
                with open(tmp_path, "wb") as f:
                    f.write(img_resp.content)

                logger.info(f"Scene {scene_number}: Image downloaded ({len(img_resp.content) / 1024:.0f} KB)")

            # Upload to MinIO
            image_storage_path = await storage.upload_scene_image(
                race_id=_race_id,
                episode_id=episode_id,
                scene_number=scene_number,
                file_path=tmp_path,
                suffix=frame_type,
            )

            generation_time_ms = int(
                (datetime.utcnow() - started_at).total_seconds() * 1000
            )

            # Update scene record
            if frame_type == "start":
                scene.start_frame_path = image_storage_path
                scene.source_image_path = image_storage_path
            else:
                scene.end_frame_path = image_storage_path

            scene.status = SceneStatus.COMPLETED if set_completed else SceneStatus.GENERATING
            scene.generation_completed_at = datetime.utcnow()
            scene.generation_time_ms = generation_time_ms
            scene.last_error = None
            scene.image_cost_usd = (scene.image_cost_usd or Decimal(0)) + Decimal("0.035")
            scene.image_backend = "flux-lora"
            scene.lora_used = True
            scene.regeneration_count = (scene.regeneration_count or 0) + 1

            await db.commit()
            # Verify the path was persisted
            await db.refresh(scene)
            if frame_type == "start" and not scene.start_frame_path:
                raise RuntimeError(
                    f"Scene {scene_number}: start_frame_path NULL after commit — storage may have failed"
                )
            # Log image generation cost
            await _log_api_cost(
                db, episode_id, scene.id,
                provider="fal-image",
                endpoint="fal-ai/flux-lora",
                cost_usd=0.035,
                response_time_ms=generation_time_ms,
            )
            await _update_episode_costs(db, episode_id)

            logger.info(f"Scene {scene_number}: {frame_type} frame generated in {generation_time_ms}ms via fal.ai")
            return f"Scene {scene_number} {frame_type} frame generated"

        except Exception as e:
            logger.error(f"Scene {scene_number}: Image generation failed: {e}")
            scene.status = SceneStatus.FAILED
            scene.last_error = str(e)[:500]
            scene.retry_count += 1
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
from app.services.scene_validator import adapt_prompt_for_validation_failure as _adapt_prompt_for_failure

async def _async_scene_all(episode_id: int, scene_number: int) -> str:
    """Async worker: generate image then video with inline validation.

    Validation loop:
      1. Generate start frame image
      2. Validate image (direction, composition, text, style, character)
      3. If fail -> adapt prompt, regenerate (up to MAX_IMAGE_RETRIES)
      4. Generate video
      5. Check motion (free, no API cost)
      6. Validate video via Claude Vision (5-frame check)
      7. If fail -> adapt prompt, regenerate image + video (up to MAX_VIDEO_RETRIES)
    """
    from app.database import async_session_maker
    from app.models.scene import Scene as SceneModel
    from app.services.scene_validator import SceneValidator
    from app.services.storage import StorageService
    from sqlalchemy import select

    logger.info(f"Scene {scene_number}: Starting full regeneration (image + video + validation)")

    # --- Step 1: Generate and validate start frame ---
    for image_attempt in range(MAX_IMAGE_RETRIES + 1):
        await _async_scene_image(episode_id, scene_number, frame_type="start", set_completed=False)
        logger.info(f"Scene {scene_number}: Start image done (attempt {image_attempt + 1})")

        # Validate the image
        try:
            validator = SceneValidator()
            storage = StorageService()
            async with async_session_maker() as db:
                scene = (await db.execute(
                    select(SceneModel).where(
                        SceneModel.episode_id == episode_id,
                        SceneModel.scene_number == scene_number,
                    )
                )).scalar_one_or_none()

                if scene and scene.start_frame_path:
                    # Download image for validation
                    bucket, obj = scene.start_frame_path.split("/", 1)
                    local_img = f"/tmp/val_{episode_id}_{scene_number}_start.png"
                    await storage.download_file(bucket, obj, local_img)

                    # Download face reference if character scene
                    ref_path = None
                    if scene.character_id and scene.face_visible:
                        from app.models import Character
                        char = await db.get(Character, scene.character_id)
                        if char:
                            ref_path = await storage.download_face_reference(char.name)

                    # Build team context for validation
                    team_context = None
                    if scene.character_id:
                        from app.models.team import Team
                        from sqlalchemy.orm import selectinload
                        char_with_team = await db.get(Character, scene.character_id)
                        if char_with_team and hasattr(char_with_team, 'team_id') and char_with_team.team_id:
                            team_obj = await db.get(Team, char_with_team.team_id)
                            if team_obj:
                                team_context = {
                                    "team_name": team_obj.name,
                                    "car_description": team_obj.car_description,
                                    "primary_colour": team_obj.primary_colour,
                                    "secondary_colour": team_obj.secondary_colour,
                                }

                    img_val = await validator.validate_image(
                        image_path=local_img,
                        scene_number=scene_number,
                        scene_type=scene.scene_type,
                        face_visible=scene.face_visible,
                        reference_image_path=ref_path,
                        prompt_text=scene.start_frame_prompt,
                        team_context=team_context,
                    )

                    if img_val.passed:
                        logger.info(f"Scene {scene_number}: Image validation PASSED")
                        break
                    else:
                        failed_checks = [c.name for c in img_val.checks if not c.passed]
                        logger.warning(f"Scene {scene_number}: Image validation FAILED: {failed_checks}")
                        if image_attempt < MAX_IMAGE_RETRIES:
                            adapted = _adapt_prompt_for_failure(scene, img_val)
                            if adapted:
                                await db.commit()
                                logger.info(f"Scene {scene_number}: Retrying image with adapted prompt")
                                continue
                        failed_names = [c.name for c in img_val.checks if not c.passed]
                        # Only BLOCK video gen for critical failures
                        CRITICAL_CHECKS = {"car_count", "direction", "clothing", "anatomy"}
                        critical_fails = [n for n in failed_names if n in CRITICAL_CHECKS]

                        if critical_fails:
                            logger.error(
                                f"Scene {scene_number}: CRITICAL image validation failures "
                                f"{critical_fails} — BLOCKING video generation"
                            )
                            async with async_session_maker() as db_fail:
                                s_fail = (await db_fail.execute(
                                    select(SceneModel).where(
                                        SceneModel.episode_id == episode_id,
                                        SceneModel.scene_number == scene_number,
                                    )
                                )).scalar_one_or_none()
                                if s_fail:
                                    s_fail.status = "failed"
                                    s_fail.validation_status = "failed_critical"
                                    import json as _json
                                    s_fail.validation_issues = _json.dumps(failed_names)
                                    await db_fail.commit()
                            return f"Scene {scene_number}: Critical validation failures {critical_fails}"
                        else:
                            logger.warning(
                                f"Scene {scene_number}: Minor image issues {failed_names} "
                                "after max retries — proceeding to video generation"
                            )
                            # Record the minor issues but continue
                            scene.validation_status = "failed_minor"
                            import json as _json_minor
                            scene.validation_issues = _json_minor.dumps(failed_names)
                            await db.commit()
                else:
                    break  # No image to validate
        except Exception as ve:
            logger.warning(f"Scene {scene_number}: Image validation error: {ve}")
            break

    # --- Step 1b: Generate and validate end frame for ACTION_REPLAY (FLF) ---
    try:
        from app.services.runtime_settings import get_video_generator
        from app.services.fal_video_generator import FalBackend, FAL_FLF_CAPABLE
        from app.pipeline.flf_router import should_generate_end_frame

        backend_str = get_video_generator()
        backend_enum = FalBackend(backend_str)
        if backend_enum in FAL_FLF_CAPABLE:
            async with async_session_maker() as db:
                scene = (await db.execute(
                    select(SceneModel).where(
                        SceneModel.episode_id == episode_id,
                        SceneModel.scene_number == scene_number,
                    )
                )).scalar_one_or_none()
                from sqlalchemy import func
                total = (await db.execute(
                    select(func.count()).select_from(SceneModel).where(SceneModel.episode_id == episode_id)
                )).scalar() or 0

                if scene and scene.end_frame_prompt and should_generate_end_frame(
                    scene_type=scene.scene_type,
                    scene_index=scene_number - 1,
                    total_scenes=total,
                    backend_supports_flf=True,
                ):
                    logger.info(f"Scene {scene_number}: Generating end frame for FLF (type={scene.scene_type})")
                    await _async_scene_image(episode_id, scene_number, frame_type="end", set_completed=False)

                    # Validate end frame direction (critical for racing scenes)
                    if scene.end_frame_path:
                        try:
                            bucket, obj = scene.end_frame_path.split("/", 1)
                            local_end = f"/tmp/val_{episode_id}_{scene_number}_end.png"
                            await storage.download_file(bucket, obj, local_end)
                            end_val = await validator.validate_image(
                                image_path=local_end,
                                scene_number=scene_number,
                                scene_type=scene.scene_type,
                                face_visible=False,
                                prompt_text=scene.end_frame_prompt,
                                team_context=team_context if 'team_context' in dir() else None,
                            )
                            if end_val.passed:
                                logger.info(f"Scene {scene_number}: End frame validation PASSED")
                            else:
                                failed = [c.name for c in end_val.checks if not c.passed]
                                logger.warning(f"Scene {scene_number}: End frame validation FAILED: {failed}")
                                # Adapt and retry end frame
                                if _adapt_prompt_for_failure(scene, end_val):
                                    scene.end_frame_path = None
                                    await db.commit()
                                    await _async_scene_image(episode_id, scene_number, frame_type="end", set_completed=False)
                                    logger.info(f"Scene {scene_number}: End frame regenerated with adapted prompt")
                        except Exception as efv:
                            logger.warning(f"Scene {scene_number}: End frame validation error: {efv}")
                else:
                    logger.debug(f"Scene {scene_number}: FLF not applicable")
    except Exception as flf_err:
        logger.debug(f"Scene {scene_number}: FLF check skipped: {flf_err}")

        # --- Step 2: Generate and validate video ---
    for video_attempt in range(MAX_VIDEO_RETRIES + 1):
        logger.info(f"Scene {scene_number}: Generating video (attempt {video_attempt + 1})")
        result = await _async_scene_video(episode_id, scene_number)

        # Validate the video
        try:
            validator = SceneValidator()
            async with async_session_maker() as db:
                scene = (await db.execute(
                    select(SceneModel).where(
                        SceneModel.episode_id == episode_id,
                        SceneModel.scene_number == scene_number,
                    )
                )).scalar_one_or_none()

                if scene and scene.video_clip_path:
                    # Motion check (free, no API cost)
                    bucket, obj = scene.video_clip_path.split("/", 1)
                    local_vid = f"/tmp/val_{episode_id}_{scene_number}_video.mp4"
                    await storage.download_file(bucket, obj, local_vid)

                    has_motion = await validator.check_video_motion(local_vid)
                    if not has_motion:
                        logger.warning(f"Scene {scene_number}: Video FROZEN/STATIC")
                        if video_attempt < MAX_VIDEO_RETRIES:
                            async with async_session_maker() as db2:
                                s = (await db2.execute(
                                    select(SceneModel).where(
                                        SceneModel.episode_id == episode_id,
                                        SceneModel.scene_number == scene_number,
                                    )
                                )).scalar_one_or_none()
                                if s:
                                    s.video_prompt = (s.video_prompt or "") + " Strong dynamic motion throughout."
                                    await db2.commit()
                            continue

                    # Audio validation (free, ffmpeg-based)
                    has_dialogue = bool(scene.dialogue and scene.dialogue.strip())
                    audio_val = await validator.validate_audio(
                        local_vid,
                        has_dialogue=has_dialogue,
                        audio_description=scene.audio_description,
                    )
                    if not audio_val.passed:
                        logger.warning(
                            f"Scene {scene_number}: Audio validation FAILED: "
                            f"{audio_val.issues}"
                        )
                        # Log but don't block — audio issues flagged for review
                        scene.validation_issues = scene.validation_issues or {}
                        if isinstance(scene.validation_issues, str):
                            import json as _json2
                            try:
                                scene.validation_issues = _json2.loads(scene.validation_issues)
                            except Exception:
                                scene.validation_issues = {}
                        scene.validation_issues["audio"] = audio_val.issues

                    # Full Claude Vision validation
                    vid_val = await validator.validate_scene(scene)
                    if vid_val.passed:
                        logger.info(f"Scene {scene_number}: Video validation PASSED")
                        scene.validation_status = "passed"
                    else:
                        failed = [c.name for c in vid_val.checks if not c.passed]
                        logger.warning(f"Scene {scene_number}: Video validation FAILED: {failed}")
                        scene.validation_status = "failed"
                        import json as _json
                        scene.validation_issues = _json.dumps(failed)
                        if video_attempt < MAX_VIDEO_RETRIES:
                            adapted = _adapt_prompt_for_failure(scene, vid_val)
                            if adapted:
                                scene.start_frame_path = None
                                scene.video_clip_path = None
                                await db.commit()
                                # Regenerate image first, then video
                                await _async_scene_image(episode_id, scene_number, frame_type="start", set_completed=False)
                                continue
                    await db.commit()
                    break
                else:
                    break
        except Exception as ve:
            logger.warning(f"Scene {scene_number}: Video validation error: {ve}")
            break

    logger.info(f"Scene {scene_number}: Full regeneration complete (with validation)")
    return result


# ──────────────────────────────────────────────────────────────────
# Stitch / Upload / Validate jobs
# ──────────────────────────────────────────────────────────────────

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
