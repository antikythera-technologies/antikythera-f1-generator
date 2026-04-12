"""Shared scene video generation service.

Single source of truth for generating scene video clips via fal.ai.
Handles prompt building, FLF end frames, backend selection, cost tracking.
Called by both video_pipeline.py and jobs.py — never duplicate this logic.
"""

import logging
import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.logs import APIProvider
from app.models.scene import Scene
from app.models.team import Team
from app.services.cost_tracker import log_api_cost
from app.services.fal_video_generator import (
    FAL_COST_PER_SECOND,
    FAL_FLF_CAPABLE,
    FalBackend,
    FalVideoGenerator,
    build_f1_video_prompt,
)
from app.services.personality import load_personality_traits_from_db
from app.services.runtime_settings import get_video_generator
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Character context helpers
# ---------------------------------------------------------------------------

def _load_voice_description(character: Character | None) -> str | None:
    """Extract voice/accent description from character personality.

    Uses load_personality_traits_from_db (single source of truth for personality parsing).
    """
    if not character or not character.personality:
        return None

    try:
        traits = load_personality_traits_from_db(character.personality)
        ss = traits.get("speaking_style", {})
        parts = [p for p in [
            f"{traits.get('nationality', '')} accent" if traits.get('nationality') else "",
            ss.get("accent_hints", "") if isinstance(ss, dict) else "",
            ss.get("tone", "") if isinstance(ss, dict) else "",
        ] if p]
        return ", ".join(parts) if parts else None
    except Exception as e:
        logger.warning(f"Could not build voice description: {e}")
        return None


def _load_character_animation(character: Character | None) -> dict | None:
    """Extract animation traits from character personality for video prompt."""
    if not character or not character.personality:
        return None

    try:
        traits = load_personality_traits_from_db(character.personality)
        return {
            "signature_expression": traits.get("signature_expression"),
            "signature_pose": traits.get("signature_pose"),
            "comedy_angle": traits.get("comedy_angle"),
        }
    except Exception:
        return None


async def _load_team_context(db: AsyncSession, character: Character | None) -> Team | None:
    """Load team data for video prompt colour context."""
    if not character or not getattr(character, 'team_id', None):
        return None
    return await db.get(Team, character.team_id)


# ---------------------------------------------------------------------------
# FLF end frame handling
# ---------------------------------------------------------------------------

async def _prepare_end_frame(
    scene: Scene,
    storage: StorageService,
    fal_gen: FalVideoGenerator,
    start_image_local: str,
) -> str | None:
    """Upload end frame for FLF if available and compatible.

    Returns fal.ai CDN URL of end frame, or None if FLF not applicable.
    """
    if not scene.end_frame_path:
        return None

    if fal_gen.backend not in FAL_FLF_CAPABLE:
        return None

    end_local = f"/tmp/f1-video/ep{scene.episode_id}_s{scene.scene_number:02d}_end.png"
    os.makedirs(os.path.dirname(end_local), exist_ok=True)

    try:
        end_bucket, end_obj = scene.end_frame_path.split("/", 1)
        await storage.download_file(end_bucket, end_obj, end_local)

        # Validate start/end frame compatibility
        from app.services.scene_validator import SceneValidator
        validator = SceneValidator()
        compatible = await validator.check_flf_frame_compatibility(
            start_image_local, end_local, scene.scene_number
        )

        if compatible:
            end_url = await fal_gen.upload_image(end_local)
            logger.info(f"Scene {scene.scene_number}: End frame uploaded for FLF (frames compatible)")
            return end_url
        else:
            logger.warning(
                f"Scene {scene.scene_number}: FLF DISABLED — start/end frames too different"
            )
            return None
    except Exception as e:
        logger.warning(f"Scene {scene.scene_number}: Could not prepare end frame for FLF: {e}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_scene_video(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    image_path: str | None = None,
) -> str:
    """Generate a video clip for a scene using the configured fal.ai backend.

    Handles: downloading start frame, uploading to fal CDN, building F1 video
    prompt with team context and character animation, FLF end frames, calling
    fal.ai API, uploading result to MinIO, and tracking costs.

    Args:
        db: Active database session (caller manages commit).
        scene: Scene to generate video for. Must have start_frame_path.
        episode_id: Episode ID for storage paths.
        race_id: Race ID for storage paths.
        storage: StorageService for MinIO operations.
        image_path: Optional local path to start frame. If None, downloads from MinIO.

    Returns:
        Local file path of the generated video clip.
    """
    scene_num = scene.scene_number
    log = logging.getLogger(f"scene_video.ep{episode_id}.s{scene_num:02d}")

    # Get start frame
    start_frame_ref = scene.start_frame_path or scene.source_image_path
    if not start_frame_ref and not image_path:
        raise ValueError(f"Scene {scene_num}: No start frame image available")

    # Download start frame if not provided locally
    if not image_path:
        image_path = f"/tmp/f1-video/ep{episode_id}_s{scene_num:02d}_start.png"
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        bucket, obj = start_frame_ref.split("/", 1)
        await storage.download_file(bucket, obj, image_path)

    # Initialize fal.ai generator
    backend = get_video_generator()
    if not backend.startswith("fal-"):
        raise ValueError(f"Unsupported video backend: {backend}")

    fal_gen = FalVideoGenerator(backend=backend)

    # Upload image to fal.ai CDN
    image_url = await fal_gen.upload_image(image_path)

    # Load character context for video prompt
    voice_char = scene.character or getattr(scene, 'voiceover_character', None)
    team = await _load_team_context(db, voice_char if voice_char else scene.character)
    voice_desc = _load_voice_description(voice_char)
    char_anim = _load_character_animation(voice_char)

    # Prepare FLF end frame
    end_image_url = await _prepare_end_frame(scene, storage, fal_gen, image_path)

    # Build F1 video prompt
    from app.services.script_generator import sanitize_prompt_text
    raw_vp = (scene.video_prompt or scene.start_frame_prompt or "").replace("ANTKF1STYLE", "").strip()
    clean_vp = sanitize_prompt_text(raw_vp, scene_type=scene.scene_type)

    video_prompt = build_f1_video_prompt(
        clean_vp,
        scene_type=str(scene.scene_type) if scene.scene_type else None,
        face_visible=bool(scene.face_visible),
        dialogue=scene.dialogue,
        team_name=team.name if team else None,
        car_description=team.car_description if team else None,
        overalls_description=team.overalls_description if team else None,
        camera_direction=scene.camera_direction,
        character_animation=char_anim,
        livery_description=team.livery_description if team else None,
    )

    # Generate video
    start_time = datetime.utcnow()

    clip = await fal_gen.generate_clip(
        scene_number=scene_num,
        image_url=image_url,
        prompt=video_prompt,
        dialogue=scene.dialogue,
        audio_description=scene.audio_description,
        face_visible=bool(scene.face_visible),
        end_image_url=end_image_url,
        voice_description=voice_desc,
        duration=int(scene.duration_seconds) if scene.duration_seconds else None,
    )

    generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

    # Upload video to MinIO
    clip_path = await storage.upload_video_clip(
        race_id=race_id,
        episode_id=episode_id,
        scene_number=scene_num,
        file_path=clip.video_path,
    )

    # Update scene record
    scene.video_clip_path = clip_path
    scene.video_generator = backend
    scene.audio_clip_path = None  # Clear — new video has different audio
    scene.generation_completed_at = datetime.utcnow()
    scene.generation_time_ms = generation_time_ms

    # Track cost (per-second pricing × duration)
    try:
        backend_enum = FalBackend(backend)
        cost_per_sec = FAL_COST_PER_SECOND.get(backend_enum, 0.04)
    except ValueError:
        cost_per_sec = 0.04

    duration = float(scene.duration_seconds or 5)
    video_cost = Decimal(str(round(duration * cost_per_sec, 6)))
    scene.video_cost_usd = (scene.video_cost_usd or Decimal(0)) + video_cost

    try:
        api_provider = APIProvider(backend)
    except ValueError:
        api_provider = APIProvider.FAL_OVI
    await log_api_cost(
        db,
        episode_id=episode_id,
        scene_id=scene.id,
        provider=api_provider,
        endpoint=f"fal.ai/{fal_gen.model_id}",
        cost_usd=float(video_cost),
        response_time_ms=generation_time_ms,
    )

    log.info(
        f"Video generated in {generation_time_ms}ms, "
        f"${float(video_cost):.3f} ({fal_gen.display_name})"
    )

    return clip.video_path
