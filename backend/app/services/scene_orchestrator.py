"""Scene orchestrator — full scene lifecycle with self-correcting validation.

Processes a single scene through: image gen → validate → end frame → video gen →
validate → TTS. Retries with prompt adaptation on validation failure.

Single source of truth for the scene processing lifecycle.
Called by both video_pipeline.py (batch) and jobs.py (single scene regen).
"""

import json
import logging
import os
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logs import APIProvider
from app.models.scene import Scene, SceneStatus
from app.services.cost_tracker import log_api_cost
from app.services.fal_video_generator import FAL_FLF_CAPABLE, FalBackend
from app.services.runtime_settings import get_video_generator
from app.services.scene_image_service import generate_scene_image
from app.services.scene_validator import (
    SceneValidator,
    adapt_prompt_for_validation_failure,
)
from app.services.scene_video_service import generate_scene_video
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


@dataclass
class SceneResult:
    """Result of processing a single scene."""

    scene_number: int
    status: str  # "completed", "failed"
    image_path: str | None = None
    video_path: str | None = None
    issues: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Image validation with retry
# ---------------------------------------------------------------------------

async def _validate_and_retry_image(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    image_path: str,
    validator: SceneValidator,
    max_retries: int = 2,
    episode_character_appearances: dict | None = None,
) -> tuple[str, bool]:
    """Validate a scene image, retrying with prompt adaptation on failure.

    Returns: (image_local_path, passed_validation)
    """
    log = logging.getLogger(f"scene_orch.ep{episode_id}.s{scene.scene_number:02d}")

    from app.models.character import Character
    from app.models.team import Team

    # Load face reference for comparison
    ref_path = None
    if scene.face_visible and scene.character_id:
        try:
            char_for_ref = await db.get(Character, scene.character_id)
            if char_for_ref:
                ref_path = await storage.download_face_reference(char_for_ref.name)
        except Exception:
            pass

    # Load team context for validation
    team_context = None
    if scene.character_id:
        char = await db.get(Character, scene.character_id)
        if char and getattr(char, 'team_id', None):
            team_obj = await db.get(Team, char.team_id)
            if team_obj:
                team_context = {
                    "team_name": team_obj.name,
                    "car_description": team_obj.car_description,
                    "primary_colour": team_obj.primary_colour,
                    "secondary_colour": team_obj.secondary_colour,
                }

    current_image = image_path

    for attempt in range(1 + max_retries):
        result = await validator.validate_image(
            current_image,
            scene.scene_number,
            scene_type=scene.scene_type,
            face_visible=bool(scene.face_visible),
            reference_image_path=ref_path,
            prompt_text=scene.start_frame_prompt,
            team_context=team_context,
        )

        # Log validation cost
        await log_api_cost(
            db, episode_id=episode_id, scene_id=scene.id,
            provider=APIProvider.ANTHROPIC,
            endpoint="claude-vision/image-validation",
            cost_usd=0.003,
        )

        if result.passed:
            scene.validation_status = "passed"
            scene.validation_issues = None
            await db.flush()
            log.info(f"Image validation PASSED (attempt {attempt + 1})")
            return current_image, True

        issues = ", ".join(result.issues)
        scene.validation_status = "failed"
        scene.validation_issues = json.dumps(result.issues)
        await db.flush()
        log.warning(f"Image validation FAILED (attempt {attempt + 1}): {issues}")

        if attempt < max_retries:
            adapted = adapt_prompt_for_validation_failure(scene, result)
            if adapted:
                scene.start_frame_path = None
                await db.flush()
                await db.commit()

                try:
                    new_image = await generate_scene_image(
                        db, scene, episode_id, race_id, storage,
                        frame_type="start",
                        episode_character_appearances=episode_character_appearances,
                    )
                    await db.flush()
                    current_image = new_image
                    log.info(f"Retry image generated (attempt {attempt + 2})")
                except Exception as e:
                    log.error(f"Retry image gen failed: {e}")
                    break
            else:
                log.info("No prompt adaptation possible, proceeding")
                break
        else:
            # Max retries reached — check for critical failures
            critical_fails = [
                c for c in result.checks
                if not c.passed and c.name in (
                    "car_count", "direction", "clothing", "anatomy"
                )
            ]
            if critical_fails:
                fail_names = [c.name for c in critical_fails]
                scene.validation_status = "failed_critical"
                scene.last_error = f"Critical image validation failures: {fail_names}"
                await db.flush()
                log.error(f"CRITICAL image failures {fail_names} — BLOCKING video gen")
                return current_image, False
            else:
                scene.validation_status = "failed_minor"
                await db.flush()
                log.warning("Minor image issues only, proceeding with current image")

    return current_image, True  # Proceed with what we have


# ---------------------------------------------------------------------------
# End frame generation with validation
# ---------------------------------------------------------------------------

async def _generate_end_frame(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    start_image_path: str,
    validator: SceneValidator,
    scene_index: int,
    total_scenes: int,
    max_retries: int = 2,
    episode_character_appearances: dict | None = None,
) -> str | None:
    """Generate end frame for FLF if applicable.

    Returns: local path to end frame image, or None if not applicable/failed.
    """
    log = logging.getLogger(f"scene_orch.ep{episode_id}.s{scene.scene_number:02d}")

    backend = get_video_generator()
    try:
        backend_enum = FalBackend(backend)
    except ValueError:
        return None

    if backend_enum not in FAL_FLF_CAPABLE:
        return None

    # Lazy import to avoid circular: orchestrator → pipeline.__init__ → video_pipeline → orchestrator
    from app.pipeline.flf_router import should_generate_end_frame

    if not should_generate_end_frame(
        scene_type=scene.scene_type,
        scene_index=scene_index,
        total_scenes=total_scenes,
        backend_supports_flf=True,
    ):
        return None

    if not scene.end_frame_prompt:
        log.debug("No end_frame_prompt — skipping FLF")
        return None

    if scene.end_frame_path:
        log.info("Already has end frame — reusing")
        local_path = f"/tmp/f1-images/ep{episode_id}_s{scene.scene_number:02d}_end_resume.png"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        bucket, obj = scene.end_frame_path.split("/", 1)
        await storage.download_file(bucket, obj, local_path)
        return local_path


    for attempt in range(1 + max_retries):
        try:
            end_image = await generate_scene_image(
                db, scene, episode_id, race_id, storage,
                frame_type="end",
                episode_character_appearances=episode_character_appearances,
            )
        except Exception as e:
            log.warning(f"End frame gen failed: {e}")
            return None

        # Quality validation
        try:
            ef_result = await validator.validate_image(
                image_path=end_image,
                scene_number=scene.scene_number,
                scene_type=scene.scene_type,
                face_visible=scene.face_visible,
                prompt_text=scene.end_frame_prompt,
            )

            has_critical = any(
                not c.passed and c.name in (
                    "direction", "physical_accuracy", "car_count",
                    "clothing", "anatomy"
                )
                for c in ef_result.checks
            )
            if has_critical and attempt < max_retries:
                log.warning(f"End frame failed critical validation (attempt {attempt + 1})")
                adapt_prompt_for_validation_failure(scene, ef_result, frame_type="end")
                continue
            elif has_critical:
                log.warning("End frame failed critical validation after retries — skipping FLF")
                scene.end_frame_path = None
                return None
        except Exception as e:
            log.warning(f"End frame validation error: {e}")

        # Compatibility check vs start frame
        try:
            compatible = await validator.check_flf_frame_compatibility(
                start_image_path, end_image, scene.scene_number
            )
            if not compatible and attempt < max_retries:
                log.warning(f"End frame incompatible with start (attempt {attempt + 1})")
                scene.end_frame_prompt = _adapt_end_frame_for_consistency(
                    scene.start_frame_prompt, scene.end_frame_prompt
                )
                continue
            elif not compatible:
                log.warning("End frame still incompatible — skipping FLF")
                scene.end_frame_path = None
                return None
        except Exception as e:
            log.warning(f"FLF compatibility check failed: {e}")

        log.info("End frame validated and ready")
        return end_image

    return None


def _adapt_end_frame_for_consistency(start_prompt: str, end_prompt: str) -> str:
    """Adapt end frame prompt to be visually consistent with start frame."""
    if not start_prompt or not end_prompt:
        return end_prompt or ""

    # Extract key elements from start prompt and reinforce in end prompt
    consistency_note = (
        " CRITICAL: This end frame must be visually consistent with the start frame. "
        "Same character, same outfit, same setting, same camera angle. "
        "Only the described action change should differ."
    )
    return end_prompt + consistency_note


# ---------------------------------------------------------------------------
# Video validation with retry
# ---------------------------------------------------------------------------

async def _validate_and_retry_video(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    image_path: str,
    validator: SceneValidator,
    max_retries: int = 1,
) -> bool:
    """Validate video clip, retrying on failure.

    Returns: True if video is acceptable, False if failed.
    """
    log = logging.getLogger(f"scene_orch.ep{episode_id}.s{scene.scene_number:02d}")

    for attempt in range(1 + max_retries):
        if not scene.video_clip_path:
            return False

        # Download video for validation
        local_video = f"/tmp/f1-validate/ep{episode_id}_s{scene.scene_number:02d}.mp4"
        os.makedirs(os.path.dirname(local_video), exist_ok=True)
        bucket, obj = scene.video_clip_path.split("/", 1)
        await storage.download_file(bucket, obj, local_video)

        # Quick motion check (free, no API cost)
        has_motion = await validator.check_video_motion(local_video)
        if not has_motion:
            log.warning("Video appears STATIC/FROZEN")
            if attempt < max_retries:
                scene.video_clip_path = None
                scene.status = SceneStatus.GENERATING
                scene.video_prompt = (scene.video_prompt or "") + (
                    " CRITICAL: The subject must have visible continuous motion "
                    "throughout the entire clip. No static or frozen frames."
                )
                await db.flush()
                await db.commit()

                try:
                    await generate_scene_video(
                        db, scene, episode_id, race_id, storage,
                        image_path=image_path,
                    )
                    scene.status = SceneStatus.COMPLETED
                    await db.flush()
                    log.info("Video retry complete (motion fix)")
                except Exception as e:
                    log.error(f"Video retry failed: {e}")
                    scene.status = SceneStatus.COMPLETED  # Keep old
                    return True
                continue
            return True  # Accept what we have

        # Full Claude Vision validation
        vid_result = await validator.validate_scene(scene)

        await log_api_cost(
            db, episode_id=episode_id, scene_id=scene.id,
            provider=APIProvider.ANTHROPIC,
            endpoint="claude-vision/video-validation",
            cost_usd=0.015,
        )

        if vid_result.passed:
            scene.validation_status = "passed"
            scene.validation_issues = None
            log.info("Video validation PASSED")
            await db.flush()
            return True

        issues = ", ".join(vid_result.issues)
        scene.validation_status = "failed"
        scene.validation_issues = json.dumps(vid_result.issues)
        log.warning(f"Video validation FAILED: {issues}")

        if attempt < max_retries:
            adapted = adapt_prompt_for_validation_failure(scene, vid_result)
            if adapted:
                # Full retry: new image + new video
                scene.start_frame_path = None
                scene.video_clip_path = None
                scene.status = SceneStatus.GENERATING
                await db.flush()
                await db.commit()

                try:
                    new_image = await generate_scene_image(
                        db, scene, episode_id, race_id, storage, frame_type="start",
                    )
                    await db.flush()

                    await generate_scene_video(
                        db, scene, episode_id, race_id, storage,
                        image_path=new_image,
                    )
                    scene.status = SceneStatus.COMPLETED
                    await db.flush()
                    log.info("Full retry (image + video) complete")
                except Exception as e:
                    log.error(f"Full retry failed: {e}")
                    scene.status = SceneStatus.COMPLETED
                    return True
            else:
                break
        else:
            log.warning("Max video retries reached, accepting with issues")

    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Audio validation
# ---------------------------------------------------------------------------

async def _validate_audio(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    storage: StorageService,
    validator: SceneValidator,
) -> None:
    """Validate audio track on video clip (non-blocking)."""
    log = logging.getLogger(f"scene_orch.ep{episode_id}.s{scene.scene_number:02d}")

    if not scene.video_clip_path:
        return

    try:
        local_video = f"/tmp/f1-audio-val/ep{episode_id}_s{scene.scene_number:02d}.mp4"
        os.makedirs(os.path.dirname(local_video), exist_ok=True)
        bucket, obj = scene.video_clip_path.split("/", 1)
        await storage.download_file(bucket, obj, local_video)
        has_dialogue = bool(scene.dialogue and scene.dialogue.strip())
        audio_result = await validator.validate_audio(
            local_video,
            has_dialogue=has_dialogue,
            audio_description=scene.audio_description,
        )
        if not audio_result.passed:
            log.warning(f"Audio validation FAILED: {audio_result.issues}")
            # Flag for review but don't fail the scene
            existing = scene.validation_issues
            if isinstance(existing, str):
                try:
                    existing = json.loads(existing)
                except (json.JSONDecodeError, TypeError):
                    existing = {}
            if not isinstance(existing, dict):
                existing = {}
            existing["audio"] = audio_result.issues
            scene.validation_issues = json.dumps(existing) if isinstance(existing, dict) else existing
            await db.flush()
        else:
            log.info("Audio validation PASSED")
    except Exception as e:
        log.warning(f"Audio validation error: {e}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_scene(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    scene_index: int = 0,
    total_scenes: int = 26,
    max_image_retries: int = 2,
    max_video_retries: int = 1,
    episode_character_appearances: dict | None = None,
    skip_if_completed: bool = True,
) -> SceneResult:
    """Process a single scene through the full generation lifecycle.

    1. Generate start frame image (fal.ai, routes by face_visible)
    2. Validate image (critical checks block, minor checks warn)
    3. Generate end frame if FLF-capable + eligible scene type
    4. Validate end frame + compatibility check
    5. Generate video clip (fal.ai, configured backend)
    6. Validate video (motion check + Claude Vision)
    7. Validate audio (non-blocking)

    Self-correcting: retries with prompt adaptation on validation failure.

    Args:
        db: Active database session.
        scene: Scene to process.
        episode_id: Episode ID.
        race_id: Race ID.
        storage: StorageService for MinIO.
        scene_index: Zero-based scene position (for FLF eligibility).
        total_scenes: Total scenes in episode.
        max_image_retries: Max image validation retries.
        max_video_retries: Max video validation retries.
        episode_character_appearances: Appearance dict for clothing consistency.
        skip_if_completed: Skip scenes already completed with video.

    Returns:
        SceneResult with status, paths, and any issues.
    """
    scene_num = scene.scene_number
    log = logging.getLogger(f"scene_orch.ep{episode_id}.s{scene_num:02d}")

    # Skip completed scenes
    if skip_if_completed and scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
        log.info("Already complete — skipping")
        return SceneResult(scene_number=scene_num, status="completed")

    result = SceneResult(scene_number=scene_num, status="completed")

    try:
        from datetime import datetime
        scene.status = SceneStatus.GENERATING
        scene.generation_started_at = datetime.utcnow()
        await db.flush()

        # Single validator instance for all validation phases (avoids recreating Anthropic client)
        validator = SceneValidator()

        # --- Phase 1: Generate start frame ---
        image_path = None
        if scene.start_frame_path:
            log.info("Start frame already exists — reusing")
            image_path = f"/tmp/f1-images/ep{episode_id}_s{scene_num:02d}_resume.png"
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            bucket, obj = scene.start_frame_path.split("/", 1)
            await storage.download_file(bucket, obj, image_path)
        else:
            log.info("Generating start frame")
            image_path = await generate_scene_image(
                db, scene, episode_id, race_id, storage,
                frame_type="start",
                episode_character_appearances=episode_character_appearances,
            )
            await db.flush()

        result.image_path = image_path

        # --- Phase 2: Validate image ---
        image_path, image_ok = await _validate_and_retry_image(
            db, scene, episode_id, race_id, storage, image_path,
            validator=validator,
            max_retries=max_image_retries,
            episode_character_appearances=episode_character_appearances,
        )

        if not image_ok:
            scene.status = SceneStatus.FAILED
            await db.flush()
            result.status = "failed"
            result.error = scene.last_error or "Critical image validation failure"
            return result

        # --- Phase 3: Generate end frame (if applicable) ---
        await _generate_end_frame(
            db, scene, episode_id, race_id, storage, image_path,
            validator=validator,
            scene_index=scene_index,
            total_scenes=total_scenes,
            max_retries=max_image_retries,
            episode_character_appearances=episode_character_appearances,
        )
        await db.flush()

        # --- Phase 4: Generate video ---
        log.info("Generating video clip")
        video_local = await generate_scene_video(
            db, scene, episode_id, race_id, storage,
            image_path=image_path,
        )
        scene.status = SceneStatus.COMPLETED
        await db.flush()
        result.video_path = video_local

        # --- Phase 5: Validate video ---
        await _validate_and_retry_video(
            db, scene, episode_id, race_id, storage,
            image_path=image_path,
            validator=validator,
            max_retries=max_video_retries,
        )

        # --- Phase 6: Validate audio (non-blocking) ---
        backend = get_video_generator()
        try:
            backend_enum = FalBackend(backend)
            from app.services.fal_video_generator import FAL_AUDIO_BACKENDS
            if backend_enum in FAL_AUDIO_BACKENDS:
                await _validate_audio(db, scene, episode_id, storage, validator)
        except ValueError:
            pass

        await db.commit()
        log.info("Scene processing complete")
        return result

    except Exception as e:
        log.error(f"Scene processing failed: {e}")
        scene.status = SceneStatus.FAILED
        scene.last_error = str(e)
        scene.retry_count = (scene.retry_count or 0) + 1
        await db.flush()
        result.status = "failed"
        result.error = str(e)
        return result
