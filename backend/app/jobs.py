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

    logger.info(
        f"Scene {scene_number}: Starting video regeneration "
        f"(backend={__import__('app.services.runtime_settings', fromlist=['get_video_generator']).get_video_generator()})"
    )

    async with async_session_maker() as db:
        # Load scene with character
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character))
            .where(Scene.episode_id == episode_id, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            raise ValueError(f"Scene {scene_number} not found for episode {episode_id}")

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

                # Build rich audio prompt with character voice description
                rich_audio = scene.audio_description
                if scene.character and scene.character.personality:
                    try:
                        import json as _json
                        _p = _json.loads(scene.character.personality) if isinstance(scene.character.personality, str) else scene.character.personality
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
                        from app.services.fal_video_generator import FalVideoGenerator as _FVG
                        rich_audio = _FVG.build_audio_prompt(scene.audio_description, _voice_desc)
                        logger.debug(f"Scene {scene_number}: Audio prompt: {rich_audio[:100]}...")
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

                # Generate video
                clip = await fal_gen.generate_clip(
                    scene_number=scene_number,
                    image_url=image_url,
                    prompt=(scene.video_prompt or scene.start_frame_prompt or "").replace("ANTKF1STYLE", "").strip(),
                    dialogue=scene.dialogue,
                    audio_description=rich_audio,
                    end_image_url=end_image_url,
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
                race_id=0,
                episode_id=episode_id,
                scene_number=scene_number,
                file_path=video_local,
            )

            generation_time_ms = int(
                (datetime.utcnow() - scene.generation_started_at).total_seconds() * 1000
            )

            scene.video_clip_path = clip_path
            scene.video_generator = backend
            scene.status = SceneStatus.COMPLETED
            scene.generation_completed_at = datetime.utcnow()
            scene.generation_time_ms = generation_time_ms
            scene.last_error = None

            # Log video generation cost
            video_cost_map = {
                "fal-ovi": 0.20, "fal-ltx": 0.30,
                "fal-kling-std": 0.42, "fal-kling-std-audio": 0.63,
                "fal-kling-pro": 0.42, "fal-kling-pro-audio": 0.84,
                "fal-kling-o1-flf": 0.56, "fal-vidu-q1-flf": 0.50, "fal-wan-flf": 0.50,
            }
            scene.video_cost_usd = Decimal(str(video_cost_map.get(backend, 0.20)))
            await _log_api_cost(
                db, episode_id, scene.id,
                provider=backend if backend.startswith("fal-") else "ovi",
                endpoint=f"fal.ai/{backend}",
                cost_usd=video_cost_map.get(backend, 0.20),
                response_time_ms=generation_time_ms,
            )

            await db.commit()
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


async def _async_scene_image(episode_id: int, scene_number: int, frame_type: str = "start") -> str:
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

        # Determine which prompt to use
        if frame_type == "end":
            frame_prompt = scene.end_frame_prompt
        else:
            frame_prompt = scene.start_frame_prompt

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

        # Detect if this is a scene that should NOT show a character face
        # (ACTION_REPLAY, ESTABLISHING, TITLE_CARD — even if a character provides voiceover)
        is_landscape_scene = not scene.character_id  # No character = always landscape
        if scene.character_id and frame_prompt:
            landscape_keywords = [
                "COCKPIT POV", "ACTION_REPLAY", "TITLE_CARD",
                "ESTABLISHING", "AERIAL", "ON-BOARD", "ONBOARD",
                "HELMET CAM", "CIRCUIT VIEW",
            ]
            if any(kw in frame_prompt.upper() for kw in landscape_keywords):
                is_landscape_scene = True
                logger.info(
                    f"Scene {scene_number}: Landscape/action scene detected — "
                    f"no face, no LoRA, clean cinematic prompt"
                )

        # Build prompt based on scene type
        if is_landscape_scene:
            # Landscape prompt WITH LoRA trigger for consistent caricature style
            full_prompt = (
                f"ANTKF1STYLE {frame_prompt} "
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
            prompt_parts = ["ANTKF1STYLE", "Full body from waist up, camera 3 meters away.", frame_prompt]
            if episode_appearance:
                prompt_parts.append(f"Character appearance for this episode: {episode_appearance}")
            elif physical:
                prompt_parts.append(f"Character physical traits: {physical}")
            prompt_parts.append(
                "Satirical caricature style with oversized head, "
                "photorealistic skin with visible pores. Dramatic lighting with deep shadows. "
                "Full head, hair, and shoulders must be visible in frame. Do not crop the top of the head. "
                "No text, no words, no letters, no logos, no watermarks on clothing or background."
            )
            full_prompt = " ".join(prompt_parts)

        storage = StorageService()

        try:
            started_at = datetime.utcnow()
            scene.status = SceneStatus.GENERATING
            scene.generation_started_at = started_at
            await db.flush()

            # Upload face reference to fal CDN — only for character scenes
            face_ref_url = None
            if scene.character and not is_landscape_scene:
                face_local = await storage.download_face_reference(scene.character.name)
                if face_local:
                    import fal_client
                    logger.info(f"[API:fal-image] Uploading face reference: {face_local}")
                    _t0_face = time.monotonic()
                    face_ref_url = fal_client.upload_file(face_local)
                    _elapsed_face = int((time.monotonic() - _t0_face) * 1000)
                    logger.info(f"[API:fal-image] Face reference uploaded in {_elapsed_face}ms: {face_ref_url[:80]}...")

            # Choose image backend
            from app.services.runtime_settings import get_image_generator
            image_backend = get_image_generator()

            # Landscape/action scenes always use flux-lora (no face reference needed)
            if is_landscape_scene:
                image_backend = "flux-lora"
                logger.info(f"Scene {scene_number}: Using flux-lora (landscape/action scene)")

            if image_backend == "instant-character" and face_ref_url:
                # --- Instant Character via fal_client.subscribe (faster than HTTP queue) ---
                import fal_client as _fal

                _ic_args = {
                        "prompt": full_prompt,
                        "image_url": face_ref_url,
                        "negative_prompt": (
                            "cropped head, cut off head, cut off hair, top of head missing, "
                            "forehead cropped, extreme close-up, tight crop, face filling frame, "
                            "zoomed in, macro, portrait crop, chin to forehead only"
                        ),
                        "image_size": {"width": 1280, "height": 720},
                        "num_inference_steps": 28,
                        "guidance_scale": 3.5,
                        "scale": 0.15,
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
                with open(tmp_path, "wb") as f:
                    f.write(_img_resp.content)

                logger.info(f"Scene {scene_number}: Image downloaded ({len(_img_resp.content) / 1024:.0f} KB)")

                # Upload to MinIO
                image_storage_path = await storage.upload_scene_image(
                    race_id=0,
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

                scene.status = SceneStatus.COMPLETED
                scene.generation_completed_at = datetime.utcnow()
                scene.generation_time_ms = generation_time_ms
                scene.image_cost_usd = Decimal("0.04")
                scene.image_backend = "instant-character"
                scene.last_error = None

                await db.commit()
                # Log image generation cost
                await _log_api_cost(
                    db, episode_id, scene.id,
                    provider="fal-image",
                    endpoint="fal-ai/instant-character",
                    cost_usd=0.04,  # instant-character pricing
                    response_time_ms=generation_time_ms,
                )

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
                race_id=0,
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

            scene.status = SceneStatus.COMPLETED
            scene.generation_completed_at = datetime.utcnow()
            scene.generation_time_ms = generation_time_ms
            scene.last_error = None
            scene.image_cost_usd = Decimal("0.035")
            scene.image_backend = "flux-lora"

            await db.commit()
            # Log image generation cost
            await _log_api_cost(
                db, episode_id, scene.id,
                provider="fal-image",
                endpoint="fal-ai/flux-lora",
                cost_usd=0.035,  # flux-lora pricing
                response_time_ms=generation_time_ms,
            )

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


async def _async_scene_all(episode_id: int, scene_number: int) -> str:
    """Async worker: generate image then video sequentially."""
    logger.info(f"Scene {scene_number}: Starting full regeneration (image + video)")

    # Step 1: Generate start frame image
    await _async_scene_image(episode_id, scene_number, frame_type="start")
    logger.info(f"Scene {scene_number}: Start image done")

    # Step 1b: Generate end frame if backend supports FLF
    from app.services.runtime_settings import get_video_generator
    from app.services.fal_video_generator import FalBackend, FAL_FLF_CAPABLE
    backend_str = get_video_generator()
    try:
        backend_enum = FalBackend(backend_str)
        if backend_enum in FAL_FLF_CAPABLE:
            # Check if scene has an end_frame_prompt via DB
            from app.database import async_session_maker
            from app.models.scene import Scene as SceneModel
            from sqlalchemy import select
            async with async_session_maker() as db:
                stmt = select(SceneModel).where(
                    SceneModel.episode_id == episode_id,
                    SceneModel.scene_number == scene_number,
                )
                result = await db.execute(stmt)
                scene = result.scalar_one_or_none()
                if scene and scene.end_frame_prompt:
                    logger.info(f"Scene {scene_number}: Generating end frame for FLF")
                    await _async_scene_image(episode_id, scene_number, frame_type="end")
                    logger.info(f"Scene {scene_number}: End frame done")
    except (ValueError, Exception) as e:
        logger.debug(f"Scene {scene_number}: FLF check skipped: {e}")

    # Step 2: Generate video from the new image(s)
    logger.info(f"Scene {scene_number}: Proceeding to video")
    result = await _async_scene_video(episode_id, scene_number)
    logger.info(f"Scene {scene_number}: Full regeneration complete")
    return result
