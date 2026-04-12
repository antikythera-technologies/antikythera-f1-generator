"""Shared scene image generation service.

Single source of truth for generating scene images via fal.ai.
Routes by face_visible: flux-lora for action/landscape, instant-character for faces.
Called by both video_pipeline.py and jobs.py — never duplicate this logic.
"""

import asyncio
import functools
import io
import logging
import os
import re
import tempfile
from datetime import datetime
from decimal import Decimal

import httpx
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.character import Character, CharacterImage
from app.models.logs import APIProvider
from app.models.scene import Scene
from app.models.team import Team
from app.services.cost_tracker import log_api_cost
from app.services.image_utils import portrait_to_landscape
from app.services.personality import load_personality_traits_from_db
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

# LoRA weights URL — shared across all image generation
LORA_URL = (
    "https://v3b.fal.media/files/b/0a918355/"
    "tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors"
)

# Timeouts
FAL_IMAGE_TIMEOUT = 300  # 5 minutes max for image generation


# ---------------------------------------------------------------------------
# Character context loading
# ---------------------------------------------------------------------------

async def load_character_for_image(
    db: AsyncSession,
    scene: Scene,
    storage: StorageService,
    episode_character_appearances: dict | None = None,
) -> tuple[Character | None, dict, str | None]:
    """Load character, traits, and face reference for image generation.

    Args:
        db: Active database session.
        scene: Scene to load character for.
        storage: Storage service for downloading face references.
        episode_character_appearances: Optional dict of {char_name: appearance_desc}
            for clothing consistency across an episode.

    Returns:
        (character_obj, character_traits_dict, face_ref_local_path)
    """
    if not scene.character_id:
        return None, {}, None

    character = await db.get(Character, scene.character_id)
    if not character:
        return None, {}, None

    # Load personality traits
    traits: dict = {}
    if character.personality:
        try:
            traits = load_personality_traits_from_db(character.personality)
        except Exception as e:
            logger.warning(f"Could not parse personality for {character.name}: {e}")
            traits = {"display_name": character.display_name, "team": character.team}
    else:
        traits = {"display_name": character.display_name, "team": character.team}

    # Inject episode-level appearance for clothing consistency
    if episode_character_appearances:
        appearance = episode_character_appearances.get(character.name)
        if appearance:
            traits["episode_appearance"] = appearance

    # Download face reference (caricature first, then real photo)
    face_ref = None
    if getattr(scene, "face_visible", True) and scene.character_id:
        face_ref = await storage.download_face_reference(character.name)

    return character, traits, face_ref


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_flux_lora_prompt(frame_prompt: str, scene_type: str | None) -> tuple[str, str]:
    """Build prompt for flux-lora backend (action/landscape scenes).

    CRITICAL: flux-lora only processes ~60-80 words (CLIP tokenizer).
    Scene description MUST come first. Direction as concise suffix.
    Total prompt MUST be under 75 words or the model ignores the rest.
    """
    # Strip conflicting front-view language from LLM prompt
    prompt = re.sub(r'(?i)diving\s+down\s+inside\s+of', 'overtaking', frame_prompt)
    prompt = re.sub(r'(?i)wheel[- ]to[- ]wheel\s+from\s+(?:the\s+)?front', 'wheel-to-wheel from behind', prompt)
    prompt = re.sub(r'(?i)nose\s+to\s+tail', 'rear view of cars in close formation', prompt)
    prompt = re.sub(r'(?i)looking\s+FORWARD\s+through', 'view through', prompt)

    # Strip duplicate ANTKF1STYLE if LLM already included it
    clean_prompt = re.sub(r'(?i)^ANTKF1STYLE\s*', '', prompt).strip()

    # Concise direction suffix based on scene type
    _st = (scene_type or '').upper()
    pov_keywords = ["cockpit pov", "onboard", "on-board", "helmet cam", "driver pov"]
    is_pov = any(kw in (frame_prompt or "").lower() for kw in pov_keywords)

    if _st in ('ESTABLISHING', 'TITLE_CARD'):
        direction_suffix = "Wide environmental shot, 3-5 cars in background driving away showing rear wings."
    elif is_pov:
        direction_suffix = "Driver POV through halo, chasing cars ahead showing only rear wings and diffusers."
    elif any(kw in (frame_prompt or "").lower() for kw in ["car", "cars", "race", "racing", "overtake", "track", "circuit"]):
        direction_suffix = "Camera behind the cars, every car shows rear wing, open-cockpit F1 cars with halo."
    else:
        direction_suffix = ""

    full_prompt = f"ANTKF1STYLE {clean_prompt}. {direction_suffix} Satirical caricature style, dramatic lighting.".strip()

    word_count = len(full_prompt.split())
    if word_count > 75:
        logger.warning(
            f"Image prompt is {word_count} words (max ~75 for flux-lora). "
            "Model may ignore tail end."
        )

    return full_prompt, direction_suffix


def build_character_prompt(
    frame_prompt: str,
    character: Character,
    traits: dict,
    db_overalls: str | None = None,
    episode_appearance: str | None = None,
) -> str:
    """Build prompt for character face scenes (flux-lora fallback or instant-character).

    Handles framing rules, clothing by character type, and trait injection.
    """
    # Rewrite close-ups to medium shots for proper framing
    prompt = re.sub(r'(?i)\bMEDIUM\s+CLOSE[- ]?UP\b', 'MEDIUM SHOT', frame_prompt)
    prompt = re.sub(r'(?i)\bEXTREME\s+CLOSE[- ]?UP\b', 'MEDIUM SHOT', prompt)
    prompt = re.sub(r'(?i)\bCLOSE[- ]?UP\b', 'MEDIUM SHOT', prompt)

    parts = [
        "WIDE MEDIUM SHOT showing full character from knees up, "
        "camera 5 meters away, plenty of headroom above the head.",
        prompt,
    ]

    # Team overalls from DB are ground truth — always prefer over LLM appearance
    appearance = db_overalls or episode_appearance or traits.get("physical_features", "")
    if appearance:
        parts.append(f"Character appearance for this episode: {appearance}")

    # Clothing instruction by character type
    char_type_id = getattr(character, 'character_type_id', 1)
    if char_type_id == 3:
        clothing_rule = (
            "The character is a TV BROADCASTER/COMMENTATOR. "
            "They MUST wear a POLO SHIRT with broadcaster branding (e.g. Sky Sports navy blue polo). "
            "They should have a headset with microphone around their neck or on their head. "
            "NOT a racing suit, NOT overalls. Commentators wear professional broadcast attire. "
        )
    elif char_type_id == 2:
        clothing_rule = (
            "The character is a TEAM PRINCIPAL/BOSS. "
            "They MUST wear a TEAM POLO SHIRT or team jacket with team colours and sponsor logos. "
            "NOT a racing suit, NOT formal business wear. Team bosses wear branded team gear. "
        )
    else:
        clothing_rule = (
            "The character MUST wear RACING OVERALLS (fireproof race suit with team colours and sponsor logos). "
            "NOT a business suit, blazer, or formal wear. Racing overalls zip up the front and have sponsor patches. "
        )

    parts.append(
        "Satirical caricature style with oversized head, "
        "photorealistic skin with visible pores. Dramatic lighting with deep shadows. "
        "CRITICAL FRAMING: The character must be shown from the knees or waist up. "
        "Full head, all hair, and both shoulders MUST be visible with clear space above the head. "
        "NEVER crop the top of the head. Camera is far back, NOT close to the face. "
        "Any vehicles visible MUST be Formula 1 open-cockpit cars (NO ROOF) in the character team livery. No road cars. "
        "Maximum 22 F1 cars visible in any scene. "
        + clothing_rule
        + "No text, no words, no letters, no logos, no watermarks on clothing or background."
    )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# fal.ai API callers
# ---------------------------------------------------------------------------

async def _call_instant_character(prompt: str, face_ref_url: str) -> tuple[bytes, float]:
    """Call fal.ai instant-character API.

    Returns: (image_bytes, cost_usd)
    """
    import fal_client

    ic_args = {
        "prompt": prompt,
        "image_url": face_ref_url,
        "negative_prompt": (
            "cropped head, cut off head, cut off hair, top of head missing, "
            "forehead cropped, extreme close-up, tight crop, face filling frame, "
            "zoomed in, macro, portrait crop, chin to forehead only, "
            "shoulder-up only, passport photo, mugshot, headshot, face only"
        ),
        "image_size": {"width": 720, "height": 1280},
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "scale": 0.8,
        "output_format": "png",
        "loras": [{"path": LORA_URL, "scale": 1.0, "trigger_word": "ANTKF1STYLE"}],
    }

    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                functools.partial(
                    fal_client.subscribe,
                    "fal-ai/instant-character",
                    arguments=ic_args,
                    with_logs=True,
                ),
            ),
            timeout=FAL_IMAGE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"fal.ai instant-character timed out after {FAL_IMAGE_TIMEOUT}s"
        )

    images = result.get("images", [])
    if not images:
        raise RuntimeError("fal.ai instant-character returned no images")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(images[0]["url"])
        resp.raise_for_status()

    return resp.content, 0.04


async def _call_flux_lora(
    prompt: str,
    fal_key: str,
    negative_prompt: str | None = None,
) -> tuple[bytes, float]:
    """Call fal.ai flux-lora API via queue polling.

    Returns: (image_bytes, cost_usd)
    """
    endpoint = "fal-ai/flux-lora"

    payload = {
        "prompt": prompt,
        "image_size": {"width": 1280, "height": 720},
        "num_images": 1,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "loras": [{"path": LORA_URL, "scale": 1.0}],
        "output_format": "png",
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    async with httpx.AsyncClient(timeout=300) as client:
        # Submit to queue
        submit_resp = await client.post(
            f"https://queue.fal.run/{endpoint}",
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            json=payload,
        )
        submit_resp.raise_for_status()
        submit_data = submit_resp.json()
        request_id = submit_data.get("request_id")
        status_url = submit_data.get(
            "status_url",
            f"https://queue.fal.run/{endpoint}/requests/{request_id}/status",
        )
        response_url = submit_data.get(
            "response_url",
            f"https://queue.fal.run/{endpoint}/requests/{request_id}",
        )

        # Poll for completion (max 5 minutes)
        for i in range(60):
            await asyncio.sleep(5)
            status_resp = await client.get(
                status_url, headers={"Authorization": f"Key {fal_key}"}
            )
            status_data = status_resp.json()
            gen_status = status_data.get("status", "")

            if gen_status == "COMPLETED":
                break
            elif gen_status in ("FAILED", "CANCELLED"):
                error_msg = status_data.get("error", "fal.ai generation failed")
                raise RuntimeError(f"fal.ai image: {error_msg}")

            if (i + 1) % 6 == 0:
                logger.info(f"Waiting for fal.ai flux-lora... {(i + 1) * 5}s")
        else:
            raise RuntimeError("fal.ai image generation timed out after 5 minutes")

        # Get result
        result_resp = await client.get(
            response_url, headers={"Authorization": f"Key {fal_key}"}
        )
        result_resp.raise_for_status()
        result_data = result_resp.json()

        images = result_data.get("images", [])
        if not images:
            raise RuntimeError("fal.ai returned no images")

        img_resp = await client.get(images[0]["url"])
        img_resp.raise_for_status()

    return img_resp.content, 0.035


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_scene_image(
    db: AsyncSession,
    scene: Scene,
    episode_id: int,
    race_id: int,
    storage: StorageService,
    frame_type: str = "start",
    episode_character_appearances: dict | None = None,
) -> str:
    """Generate a scene image via fal.ai with smart backend routing.

    Routes based on scene properties:
    - face_visible=False → flux-lora (LoRA style, no face reference)
    - face_visible=True + face ref available → instant-character (face + LoRA)
    - face_visible=True + no face ref → flux-lora fallback (LoRA + detailed prompt)

    Args:
        db: Active database session (caller manages commit).
        scene: Scene to generate image for.
        episode_id: Episode ID for storage paths.
        race_id: Race ID for storage paths.
        storage: StorageService for MinIO uploads.
        frame_type: "start" or "end".
        episode_character_appearances: Optional appearance dict for clothing consistency.

    Returns:
        Local file path of the generated image.
    """
    fal_key = settings.FAL_KEY
    if not fal_key:
        raise RuntimeError("FAL_KEY not configured")

    scene_num = scene.scene_number
    log = logging.getLogger(f"scene_image.ep{episode_id}.s{scene_num:02d}")

    # --- Load character context ---
    character, traits, face_ref_local = await load_character_for_image(
        db, scene, storage, episode_character_appearances
    )

    character_name = character.name if character else "generic_commentator"

    # Determine which prompt to use
    if frame_type == "end":
        frame_prompt = scene.end_frame_prompt or scene.action_description or "Character speaking to camera"
    else:
        frame_prompt = scene.start_frame_prompt or scene.action_description or "Character speaking to camera"

    # --- Determine image backend ---
    use_face_reference = getattr(scene, "face_visible", True) and scene.character_id is not None

    face_ref_url = None
    if character and use_face_reference and face_ref_local:
        import fal_client
        log.info(f"Uploading face reference for {character_name}")
        face_ref_url = await asyncio.get_event_loop().run_in_executor(
            None, fal_client.upload_file, face_ref_local
        )
        scene.face_reference_url = face_ref_url

        # Link to CharacterImage record
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

    # Select backend
    if not use_face_reference:
        image_backend = "flux-lora"
        log.info(f"Using flux-lora (face_visible={getattr(scene, 'face_visible', True)}, scene_type={scene.scene_type})")
    elif face_ref_url:
        image_backend = "instant-character"
        log.info(f"Using instant-character (face ref available for {character_name})")
    else:
        image_backend = "flux-lora"
        log.info(f"Using flux-lora fallback (no face ref for {character_name})")

    # --- Build prompt ---
    if image_backend == "flux-lora" and not use_face_reference:
        full_prompt, direction_suffix = build_flux_lora_prompt(frame_prompt, scene.scene_type)
    else:
        # Load team overalls from DB (ground truth for clothing)
        db_overalls = None
        if character and hasattr(character, 'team_id') and character.team_id:
            team_obj = await db.get(Team, character.team_id)
            if team_obj and team_obj.overalls_description:
                db_overalls = team_obj.overalls_description

        episode_appearance = traits.get("episode_appearance")
        full_prompt = build_character_prompt(
            frame_prompt, character, traits,
            db_overalls=db_overalls,
            episode_appearance=episode_appearance,
        )
        direction_suffix = ""  # Not used for character prompts

    # --- Generate image ---
    start_time = datetime.utcnow()

    if image_backend == "instant-character" and face_ref_url:
        log.info("Submitting to fal-ai/instant-character")
        image_bytes, cost = await _call_instant_character(full_prompt, face_ref_url)
        endpoint_name = "fal-ai/instant-character"

        # Save and convert portrait → landscape
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"f1_scene_{episode_id}_{scene_num:02d}_{frame_type}.png",
        )
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        img_full = PILImage.open(io.BytesIO(image_bytes))
        img_landscape = portrait_to_landscape(img_full)
        img_landscape.save(tmp_path, "PNG")

        scene.image_backend = "instant-character"
        scene.instant_character_used = True
        scene.lora_used = True

    else:
        endpoint_name = "fal-ai/flux-lora"
        log.info(f"Submitting to {endpoint_name}")

        # Build negative prompt for car scenes to reinforce direction
        neg_prompt = (
            "car facing camera, front wing visible, nose cone visible, "
            "head-on view, cars driving toward camera, front view of car, "
            "closed cockpit, roof, canopy, windshield, enclosed cabin, "
            "Le Mans car, GT car, road car, covered wheels"
        ) if direction_suffix else None

        image_bytes, cost = await _call_flux_lora(full_prompt, fal_key, neg_prompt)

        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"f1_scene_{episode_id}_{scene_num:02d}_{frame_type}.png",
        )
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)

        scene.image_backend = "flux-lora"
        scene.lora_used = True

    generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

    # --- Upload to MinIO ---
    image_storage_path = await storage.upload_scene_image(
        race_id=race_id,
        episode_id=episode_id,
        scene_number=scene_num,
        file_path=tmp_path,
        suffix=frame_type,
    )

    # --- Update scene record ---
    if frame_type == "end":
        scene.end_frame_path = image_storage_path
    else:
        scene.source_image_path = image_storage_path
        scene.start_frame_path = image_storage_path

    scene.image_cost_usd = (scene.image_cost_usd or Decimal(0)) + Decimal(str(cost))

    # --- Log cost ---
    await log_api_cost(
        db,
        episode_id=episode_id,
        scene_id=scene.id,
        provider=APIProvider.FAL_IMAGE,
        endpoint=endpoint_name,
        cost_usd=cost,
        response_time_ms=generation_time_ms,
    )

    log.info(
        f"Image generated in {generation_time_ms}ms "
        f"({image_backend}, ${cost:.3f})"
    )

    return tmp_path
