"""fal.ai video generation service.

Supports multiple video models via fal.ai's hosted API:
- Ovi (image-to-video with native audio + lip sync)
- LTX 2.3 (image-to-video with native audio)
- Kling 3.0 Standard (with or without audio)
- Kling 3.0 Pro (with or without audio)

All backends share the same interface: image + prompt → video clip.
Authentication: set FAL_KEY environment variable.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from app.services.api_logger import log_api_request, log_api_response

logger = logging.getLogger(__name__)


class FalBackend(str, Enum):
    """Available fal.ai video generation backends."""

    OVI = "fal-ovi"
    LTX = "fal-ltx"
    KLING_STD = "fal-kling-std"
    KLING_STD_AUDIO = "fal-kling-std-audio"
    KLING_PRO = "fal-kling-pro"
    KLING_PRO_AUDIO = "fal-kling-pro-audio"
    KLING_O1_FLF = "fal-kling-o1-flf"
    VIDU_Q1_FLF = "fal-vidu-q1-flf"
    WAN_FLF = "fal-wan-flf"


# Map backend enum to fal.ai model endpoint
FAL_MODEL_MAP: dict[FalBackend, str] = {
    FalBackend.OVI: "fal-ai/ovi/image-to-video",
    FalBackend.LTX: "fal-ai/ltx-2.3/image-to-video",
    FalBackend.KLING_STD: "fal-ai/kling-video/v3/standard/image-to-video",
    FalBackend.KLING_STD_AUDIO: "fal-ai/kling-video/v3/standard/image-to-video",
    FalBackend.KLING_PRO: "fal-ai/kling-video/v3/pro/image-to-video",
    FalBackend.KLING_PRO_AUDIO: "fal-ai/kling-video/v3/pro/image-to-video",
    FalBackend.KLING_O1_FLF: "fal-ai/kling-video/o1/image-to-video",
    FalBackend.VIDU_Q1_FLF: "fal-ai/vidu/q1/start-end-to-video",
    FalBackend.WAN_FLF: "fal-ai/wan-flf2v",
}

# Backends that produce native audio (no TTS mux needed)
FAL_AUDIO_BACKENDS: set[FalBackend] = {
    FalBackend.OVI,
    FalBackend.LTX,
    FalBackend.KLING_STD_AUDIO,
    FalBackend.KLING_PRO_AUDIO,
}

# FLF (First-Last Frame) capability sets
# FLF re-enabled for LTX — but only ACTION_REPLAY scenes pass the FLF router.
# Character scenes are excluded (start/end frame characters look too different).
# Direction validation checks both frames before video generation.
FAL_FLF_CAPABLE: set[FalBackend] = {
    FalBackend.LTX,
}
FAL_FLF_REQUIRED: set[FalBackend] = {
    FalBackend.KLING_O1_FLF,
    FalBackend.VIDU_Q1_FLF,
    FalBackend.WAN_FLF,
}

# Human-readable names for logging
FAL_DISPLAY_NAMES: dict[FalBackend, str] = {
    FalBackend.OVI: "Ovi (fal.ai)",
    FalBackend.LTX: "LTX 2.3 (fal.ai)",
    FalBackend.KLING_STD: "Kling 3.0 Standard",
    FalBackend.KLING_STD_AUDIO: "Kling 3.0 Standard + Audio",
    FalBackend.KLING_PRO: "Kling 3.0 Pro",
    FalBackend.KLING_PRO_AUDIO: "Kling 3.0 Pro + Audio",
    FalBackend.KLING_O1_FLF: "Kling O1 FLF",
    FalBackend.VIDU_Q1_FLF: "Vidu Q1 FLF",
    FalBackend.WAN_FLF: "Wan FLF",
}


def estimate_speech_duration(dialogue: str | None, words_per_second: float = 2.0) -> float:
    """Estimate how many seconds a dialogue line takes to speak.
    
    Animated character speech with emotion/accents is slower than normal.
    ~120 wpm = 2.0 words/sec is realistic for dramatic delivery.
    We add 1.0s buffer for natural pauses and audio fade.
    """
    if not dialogue:
        return 0.0
    word_count = len(dialogue.split())
    return (word_count / words_per_second) + 2.0  # 2s buffer for pauses + audio fade


def calculate_scene_duration(
    dialogue: str | None,
    base_duration: int = 5,
    backend: str = "fal-ltx",
) -> int:
    """Calculate optimal scene duration based on dialogue length.
    
    Returns an even integer duration (LTX requires even values: 6, 8, 10, etc).
    Caps at the backend's maximum.
    """
    max_durations = {
        "fal-ovi": 10,
        "fal-ltx": 20,
        "fal-kling-std": 15,
        "fal-kling-std-audio": 15,
        "fal-kling-pro": 15,
        "fal-kling-pro-audio": 15,
        "fal-kling-o1-flf": 10,
        "fal-vidu-q1-flf": 10,
        "fal-wan-flf": 10,
    }
    max_dur = max_durations.get(backend, 10)
    
    speech_seconds = estimate_speech_duration(dialogue)
    needed = max(base_duration, int(speech_seconds) + 1)
    
    # LTX requires even durations; round up
    if "ltx" in backend and needed % 2 != 0:
        needed += 1
    
    # Ovi only supports 5 or 10
    if "ovi" in backend:
        needed = 5 if needed <= 5 else 10
    
    return min(needed, max_dur)


class FalVideoError(Exception):
    """Error during fal.ai video generation."""


@dataclass
class FalVideoClip:
    """Result of fal.ai video generation."""

    scene_number: int
    video_path: str  # Local path to downloaded video
    has_native_audio: bool
    generation_time_ms: int
    backend: str
    seed: Optional[int] = None



# ---------------------------------------------------------------------------
# LTX 2.3 image-to-video prompt builder
# ---------------------------------------------------------------------------
# Key principles (from official LTX 2.3 prompting guide):
# 1. Do NOT redescribe static elements visible in the source image
# 2. Focus on TEMPORAL EVOLUTION — what changes, moves, or happens
# 3. Use explicit camera verbs with measurements (dolly, pan, tilt, crane)
# 4. One clean camera move per scene — don't combine multiple fast moves
# 5. 4-8 flowing sentences in present tense, ~80 words total
# 6. Negative guidance ("no face warping, no flickering") reduces artifacts
# ---------------------------------------------------------------------------

SCENE_TYPE_CAMERA_DEFAULTS: dict[str, str] = {
    "TALKING_HEAD": (
        "Static lock-off shot, 50mm lens, shallow depth of field."
    ),
    "TWO_SHOT": (
        "Gentle pan right 0.5 meters over 6 seconds, 35mm lens."
    ),
    "OVER_THE_SHOULDER": (
        "Slow dolly-in 0.3 meters over 6 seconds, 85mm lens, shallow depth of field."
    ),
    "REACTION": (
        "Hold static 2 seconds then slow dolly-in 0.5 meters over 4 seconds on the expression."
    ),
    "PODIUM": (
        "Slow crane up 1 meter over 6 seconds, 35mm wide lens."
    ),
    "ACTION_REPLAY": (
        "Tracking shot following car movement at speed, 200mm telephoto lens, motion blur on background."
    ),
    "ESTABLISHING": (
        "Slow pan right 2 meters over 8 seconds, 24mm wide lens, deep depth of field."
    ),
    "TITLE_CARD": (
        "Slow dolly-out 1 meter over 6 seconds, 35mm lens."
    ),
}

# Maps LLM-generated camera_direction keywords to LTX-optimized language.
# The LLM generates directions like "DOLLY PUSH-IN", "PAN LEFT", "TRACKING", etc.
_CAMERA_DIRECTION_MAP: dict[str, str] = {
    "STATIC": "Static lock-off shot, {lens} lens.",
    "DOLLY PUSH-IN": "Dolly-in {dist} over {dur} seconds, {lens} lens, shallow depth of field.",
    "DOLLY PULL-OUT": "Dolly-out {dist} over {dur} seconds, {lens} lens.",
    "DOLLY IN": "Dolly-in {dist} over {dur} seconds, {lens} lens, shallow depth of field.",
    "DOLLY OUT": "Dolly-out {dist} over {dur} seconds, {lens} lens.",
    "PAN LEFT": "Pan left {dist} over {dur} seconds, {lens} lens.",
    "PAN RIGHT": "Pan right {dist} over {dur} seconds, {lens} lens.",
    "PAN": "Pan right {dist} over {dur} seconds, {lens} lens.",
    "TILT UP": "Tilt up 0.5 meters over {dur} seconds, {lens} lens.",
    "TILT DOWN": "Tilt down 0.5 meters over {dur} seconds, {lens} lens.",
    "TILT": "Tilt up 0.5 meters over {dur} seconds, {lens} lens.",
    "CRANE": "Crane up 1.5 meters over {dur} seconds, {lens} wide lens.",
    "CRANE UP": "Crane up 1.5 meters over {dur} seconds, {lens} wide lens.",
    "CRANE DOWN": "Crane down 1 meter over {dur} seconds, {lens} lens.",
    "TRACKING": "Tracking shot following subject movement, {lens} lens, motion blur on background.",
    "STEADICAM": "Steadicam follow with gentle floating movement, {lens} lens.",
    "HANDHELD": "Subtle handheld movement with natural micro-shake, {lens} lens.",
    "WHIP PAN": "Quick whip pan over 1 second then settle to static, {lens} lens.",
    "SLOW ZOOM": "Gradual zoom-in from 35mm to 50mm over {dur} seconds.",
    "ORBIT": "Slow clockwise orbit around subject over {dur} seconds, {lens} lens.",
    "360": "Slow 360-degree clockwise orbit over {dur} seconds, {lens} lens.",
}

# Motion intensity defaults per scene type
_SCENE_MOTION_PARAMS: dict[str, dict] = {
    # Restrained
    "TALKING_HEAD": {"dist": "0.3 meters", "dur": "6", "lens": "50mm"},
    "REACTION": {"dist": "0.5 meters", "dur": "6", "lens": "50mm"},
    # Moderate
    "TWO_SHOT": {"dist": "0.5 meters", "dur": "6", "lens": "35mm"},
    "OVER_THE_SHOULDER": {"dist": "0.3 meters", "dur": "6", "lens": "85mm"},
    "ESTABLISHING": {"dist": "2 meters", "dur": "8", "lens": "24mm"},
    "TITLE_CARD": {"dist": "1 meter", "dur": "6", "lens": "35mm"},
    "PODIUM": {"dist": "1 meter", "dur": "6", "lens": "35mm"},
    # Dynamic
    "ACTION_REPLAY": {"dist": "3 meters", "dur": "6", "lens": "200mm"},
}

# One background ambient motion element per scene type
_SCENE_AMBIENT_MOTION: dict[str, str] = {
    "TALKING_HEAD": "LED screens cycle telemetry data in the background.",
    "TWO_SHOT": "Crew members shift positions in the soft-focus background.",
    "OVER_THE_SHOULDER": "Monitor screens flicker with live timing data behind the speakers.",
    "REACTION": "Team personnel react in the blurred background.",
    "PODIUM": "Confetti drifts down and champagne spray catches the light.",
    "ACTION_REPLAY": "Trackside barriers and sponsor boards streak past with speed.",
    "ESTABLISHING": "Flags flutter in the breeze above the grandstands.",
    "TITLE_CARD": "Heat haze rises from the track surface in the distance.",
}


_SCENE_CHOREOGRAPHY: dict[str, str] = {
    "TALKING_HEAD": (
        "0-2s: character settles into position, slight head tilt, eyes engage camera. "
        "2-4s: gestures with one hand to emphasize point, weight shifts forward. "
        "4-6s: leans back slightly, expression changes, nods."
    ),
    "TWO_SHOT": (
        "0-2s: speaking character leans forward with hand gesture, listening character watches. "
        "2-4s: listener reacts with head turn and eyebrow raise, speaker continues. "
        "4-6s: both characters shift — speaker settles, listener nods in response."
    ),
    "OVER_THE_SHOULDER": (
        "0-2s: background character begins speaking, foreground shoulder visible and steady. "
        "2-4s: speaking character gestures, foreground character shifts weight slightly. "
        "4-6s: speaker pauses with expression change, foreground reacts with subtle tilt."
    ),
    "REACTION": (
        "0-1.5s: eyes widen slowly as realization dawns. "
        "1.5-3s: head tilts, mouth opens slightly in disbelief. "
        "3-5s: full expression lands — head shake or slow nod, eyebrows set."
    ),
    "PODIUM": (
        "0-2s: trophy raised higher, grin broadens. "
        "2-4s: champagne spray arc, head tilts back laughing. "
        "4-6s: waves to crowd with free hand, confetti drifts past."
    ),
    "ACTION_REPLAY": (
        "0-2s: cars accelerate, rear tyres spinning, exhaust heat visible. "
        "2-4s: lead car pulls ahead, sparks fly from floor on straight. "
        "4-6s: trailing car closes gap, both cars visible driving away."
    ),
    "ESTABLISHING": (
        "0-2s: flags flutter, crowd begins to shift in seats. "
        "2-4s: distant car passes in background with faint engine sound. "
        "4-6s: light shifts as clouds pass, atmosphere builds."
    ),
    "TITLE_CARD": (
        "0-2s: atmospheric haze drifts across circuit. "
        "2-4s: distant heat shimmer from track surface. "
        "4-6s: subtle light flare as sun catches circuit features."
    ),
}


def _resolve_camera_movement(camera_direction: str | None, scene_type: str) -> str:
    """Convert LLM camera_direction into LTX-optimized camera language.

    Falls back to SCENE_TYPE_CAMERA_DEFAULTS if no direction or no match.
    STATIC is overridden to subtle dolly for face-visible scene types
    because LTX produces frozen characters with zero camera movement.
    """
    params = _SCENE_MOTION_PARAMS.get(scene_type, {"dist": "0.5 meters", "dur": "6", "lens": "35mm"})

    # Override STATIC for talking/character scenes — LTX needs camera
    # movement to drive character animation. A locked-off camera produces
    # frozen characters even when dialogue is present.
    _TALKING_TYPES = {"TALKING_HEAD", "TWO_SHOT", "OVER_THE_SHOULDER", "REACTION"}
    if camera_direction and camera_direction.strip().upper() == "STATIC" and scene_type in _TALKING_TYPES:
        return SCENE_TYPE_CAMERA_DEFAULTS.get(scene_type, f"Slow dolly-in {params['dist']} over {params['dur']} seconds, {params['lens']} lens.")

    if camera_direction:
        # Normalise: uppercase, strip whitespace
        cd = camera_direction.strip().upper()
        # Try exact match first, then prefix match
        template = _CAMERA_DIRECTION_MAP.get(cd)
        if not template:
            # Try matching the first keyword (e.g. "DOLLY PUSH-IN with slow reveal" -> "DOLLY PUSH-IN")
            for key in sorted(_CAMERA_DIRECTION_MAP.keys(), key=len, reverse=True):
                if cd.startswith(key):
                    template = _CAMERA_DIRECTION_MAP[key]
                    break
        if template:
            return template.format(**params)

    # Fall back to scene-type default
    return SCENE_TYPE_CAMERA_DEFAULTS.get(scene_type, "Steady camera with subtle movement, 35mm lens.")


import re as re  # needed by _sanitize_voice_description


def _sanitize_voice_description(voice_desc: str | None) -> str | None:
    """Strip screaming/escalation language from voice descriptions.

    LTX generates audio from prompt text. Personality traits like
    "throat-shredding SCREAMING" or "perpetual crescendo" cause
    literal screaming in generated audio. Only keep accent/nationality.
    """
    if not voice_desc:
        return None
    # Strip everything after common escalation markers
    for marker in [
        "starts measured", "rapidly escalates", "escalates to",
        "perpetual crescendo", "peaks at", "no access to",
        "whispers are louder", "throat-shredding", "full throat",
    ]:
        idx = voice_desc.lower().find(marker)
        if idx > 0:
            voice_desc = voice_desc[:idx].rstrip(", ")
    # Remove individual screaming words
    screaming_words = [
        r"\bscreaming\b", r"\bSCREAMING\b", r"\bcrescendo\b",
        r"\bvolcanic\b", r"\bexplosive\b", r"\bthroat-shredding\b",
        r"\bshredding\b", r"\bwild\b", r"\bfrantic\b",
        r"\bhysterical\b", r"\bmanic\b", r"\bshouts?\b",
        r"\byelling\b", r"\bellowing\b", r"\broaring\b",
    ]
    for pattern in screaming_words:
        voice_desc = re.sub(pattern, "", voice_desc, flags=re.IGNORECASE)
    # Clean up whitespace and trailing punctuation
    voice_desc = re.sub(r"\s{2,}", " ", voice_desc).strip().rstrip(",. —-")
    return voice_desc if voice_desc else None


def build_f1_video_prompt(
    video_prompt: str,
    scene_type: str | None = None,
    face_visible: bool = False,
    dialogue: str | None = None,
    team_name: str | None = None,
    car_description: str | None = None,
    overalls_description: str | None = None,
    camera_direction: str | None = None,
    character_animation: dict | None = None,
    livery_description: str | None = None,
) -> str:
    """Build an LTX 2.3-optimized image-to-video prompt.

    Follows official LTX prompting guidelines:
    - Do NOT redescribe the static image (LTX sees it)
    - Focus on temporal evolution (motion, action, changes)
    - Explicit camera verbs with measurements
    - 4-8 sentences, ~80 words, present tense
    """
    st = (scene_type or "").upper()
    if "." in st:
        st = st.split(".")[-1]

    sentences = []

    # --- Sentence 1: Camera movement (strongest LTX signal) ---
    sentences.append(_resolve_camera_movement(camera_direction, st))

    # --- Sentences 2-3: Temporal evolution / action ---
    # The base video_prompt from the LLM describes what happens in the scene.
    # For image-to-video, this should describe CHANGES, not static elements.
    action = video_prompt.strip()

    # Weave in character acting guidance from personality data
    if character_animation and face_visible:
        expr = character_animation.get("signature_expression")
        pose = character_animation.get("signature_pose")
        if expr and pose:
            action += f" Character performs with {expr}, {pose}."
        elif expr:
            action += f" Character's expression shows {expr}."
        elif pose:
            action += f" Character gestures with {pose}."

    sentences.append(action)

    # --- Sentence 4: One ambient background motion element ---
    ambient = _SCENE_AMBIENT_MOTION.get(st)
    if ambient:
        sentences.append(ambient)

    # --- Time-phased choreography for scene type ---
    choreo = _SCENE_CHOREOGRAPHY.get(st)
    if choreo:
        sentences.append(choreo)

    # --- Sentence 5 (conditional): Lip sync and character animation ---
    if dialogue and face_visible:
        if st in ("TWO_SHOT", "OVER_THE_SHOULDER"):
            sentences.append(
                "Both characters are animated and alive throughout. "
                "The speaking character's mouth opens and closes with each word, "
                "jaw moving naturally, head nodding. The listening character reacts "
                "with head turns, eyebrow raises, and subtle expression changes. "
                "Neither character is frozen or static at any point."
            )
        else:
            sentences.append(
                "Character's mouth opens and closes with each word, "
                "jaw moving naturally, head tilting between phrases, "
                "hands gesturing expressively. Never frozen or static."
            )

    # --- Sentence 6 (conditional): F1 car safety for racing scenes ---
    if st == "ACTION_REPLAY":
        car_note = ""
        if car_description:
            car_note = f"Lead car matches {car_description}. "
        sentences.append(
            f"{car_note}All cars are open-cockpit F1 single-seaters, "
            "all driving in the same direction away from camera."
        )
    elif st in ("ESTABLISHING", "TITLE_CARD"):
        sentences.append(
            "No close-up faces. All people are distant background figures only."
        )

    # --- Sentence 7 (conditional): Motion directives for non-dialogue scenes ---
    # Without this, action replays and reaction shots end up static
    if not (dialogue and face_visible):
        if st == "ACTION_REPLAY":
            sentences.append(
                "Cars accelerate and move continuously throughout the clip. "
                "Wheels spinning, sparks flying, visible speed and motion from frame 1. "
                "Never static or frozen."
            )
        elif st == "REACTION":
            sentences.append(
                "Character reacts with visible facial movement — eyebrow raise, "
                "head turn, expression change. Never frozen or static."
            )
        elif st not in ("ESTABLISHING", "TITLE_CARD"):
            sentences.append(
                "Subject must have visible, continuous motion throughout. "
                "No frozen or static frames at any point."
            )

    # --- Final sentence: Negative guidance (reduces artifacts ~50%) ---
    neg_parts = ["No face warping, no object duplication, no flickering, no morphing of clothing or setting."]
    if face_visible:
        neg_parts.append("Maintain consistent facial features throughout.")
    if st == "ACTION_REPLAY":
        neg_parts.append("No cars facing toward camera.")
    sentences.append(" ".join(neg_parts))

    return " ".join(sentences)


class FalVideoGenerator:
    """Generate video clips via fal.ai hosted API.

    Usage:
        gen = FalVideoGenerator(backend="fal-ovi")
        image_url = await gen.upload_image("/tmp/scene_01.png")
        clip = await gen.generate_clip(
            scene_number=1,
            image_url=image_url,
            prompt="Character speaks to camera",
            dialogue="Hello world",
        )
    """

    def __init__(self, backend: str = "fal-ovi"):
        """Initialize with the selected backend.

        Args:
            backend: One of: fal-ovi, fal-ltx, fal-kling-std,
                     fal-kling-std-audio, fal-kling-pro, fal-kling-pro-audio
        """
        try:
            self.backend = FalBackend(backend)
        except ValueError:
            raise ValueError(
                f"Unknown fal.ai backend: {backend}. "
                f"Valid options: {[b.value for b in FalBackend]}"
            )

        self.model_id = FAL_MODEL_MAP[self.backend]
        self.has_audio = self.backend in FAL_AUDIO_BACKENDS
        self.display_name = FAL_DISPLAY_NAMES[self.backend]

        # Ensure FAL_KEY is in environment for fal_client SDK
        from app.config import settings as _settings
        if not _settings.FAL_KEY:
            raise FalVideoError(
                "FAL_KEY not configured in settings. "
                "Get your key at https://fal.ai/dashboard/keys"
            )
        # FAL_KEY is set in os.environ by config.py at startup

    async def generate_clip(
        self,
        scene_number: int,
        image_url: str,
        prompt: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
        seed: Optional[int] = None,
        duration: Optional[int] = None,
        end_image_url: Optional[str] = None,
        face_visible: bool = True,
        voice_description: Optional[str] = None,
    ) -> FalVideoClip:
        """Generate a video clip from image + prompt via fal.ai.

        Args:
            scene_number: Scene number (1-24)
            image_url: Public URL of the source image (fal CDN or any HTTPS URL)
            prompt: Scene action/description
            dialogue: Character speech (used with Ovi's <S>/<E> tokens)
            audio_description: Background audio description
            seed: Random seed for reproducibility

        Returns:
            FalVideoClip with local path to downloaded video
        """
        import fal_client

        # Auto-calculate duration from dialogue length if not explicitly set
        if duration is None:
            duration = calculate_scene_duration(
                dialogue, base_duration=5, backend=self.backend.value
            )
        if duration > 5:
            _dlg_preview = (dialogue or "")[:50]
            logger.info(
                f"Scene {scene_number}: Extended duration to {duration}s "
                f"for dialogue: {_dlg_preview}..."
            )

        arguments = self._build_arguments(
            image_url=image_url,
            prompt=prompt,
            dialogue=dialogue,
            audio_description=audio_description,
            seed=seed,
            duration=duration,
            end_image_url=end_image_url,
            face_visible=face_visible,
            voice_description=voice_description,
        )

        logger.info(
            f"Scene {scene_number}: Generating via {self.display_name} "
            f"({self.model_id})"
        )
        logger.debug(f"Scene {scene_number}: Args: {arguments}")

        log_api_request(logger, "fal-video", self.model_id, arguments)
        start_time = time.monotonic()

        # Retry up to 3 times — fal CDN can return transient 503s
        # CRITICAL: 10-minute timeout per attempt — scheduler must not hang forever
        FAL_VIDEO_TIMEOUT = 600  # 10 minutes max per video generation attempt
        last_error = None
        for attempt in range(3):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        fal_client.subscribe,
                        self.model_id,
                        arguments=arguments,
                        with_logs=True,
                    ),
                    timeout=FAL_VIDEO_TIMEOUT,
                )
                break  # Success
            except Exception as e:
                last_error = e
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                log_api_response(logger, "fal-video", self.model_id, f"ERROR (attempt {attempt+1}/3): {type(e).__name__}: {e}", elapsed_ms=elapsed_ms)
                if attempt < 2:
                    logger.info(f"Scene {scene_number}: Retrying in 5s (CDN may recover)...")
                    await asyncio.sleep(5)
                else:
                    raise FalVideoError(
                        f"Scene {scene_number}: fal.ai {self.display_name} failed after 3 attempts: {last_error}"
                    )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        log_api_response(logger, "fal-video", self.model_id, "ok", result, elapsed_ms)

        # Extract video URL from result
        video_data = result.get("video")
        if not video_data or not video_data.get("url"):
            raise FalVideoError(
                f"Scene {scene_number}: fal.ai returned no video URL: {result}"
            )

        video_url = video_data["url"]
        result_seed = result.get("seed")

        logger.info(
            f"Scene {scene_number}: Generated in {elapsed_ms}ms "
            f"(seed={result_seed}): {video_url}"
        )

        # Download to local file
        local_path = (
            f"/tmp/f1-fal/scene_{scene_number:02d}_{self.backend.value}.mp4"
        )
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(resp.content)

        file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
        logger.info(
            f"Scene {scene_number}: Downloaded {file_size_mb:.1f}MB → {local_path}"
        )

        return FalVideoClip(
            scene_number=scene_number,
            video_path=local_path,
            has_native_audio=self.has_audio,
            generation_time_ms=elapsed_ms,
            backend=self.backend.value,
            seed=result_seed,
        )

    async def upload_image(self, local_path: str) -> str:
        """Upload a local image to fal.ai CDN and return the URL.

        Args:
            local_path: Path to local image file

        Returns:
            fal.ai CDN URL for the uploaded image
        """
        import fal_client

        if not os.path.exists(local_path):
            raise FalVideoError(f"Image not found: {local_path}")

        file_size_kb = os.path.getsize(local_path) / 1024
        log_api_request(logger, "fal-cdn", "upload_file", {
            "path": local_path,
            "size_kb": round(file_size_kb, 1),
        })
        start_time = time.monotonic()

        url = await asyncio.get_event_loop().run_in_executor(
            None, fal_client.upload_file, local_path
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        log_api_response(logger, "fal-cdn", "upload_file", "ok", {"url": url}, elapsed_ms)
        return url

    # ------------------------------------------------------------------
    # Backend-specific argument builders
    # ------------------------------------------------------------------

    def _build_arguments(
        self,
        image_url: str,
        prompt: str,
        dialogue: Optional[str],
        audio_description: Optional[str],
        seed: Optional[int],
        duration: int = 5,
        end_image_url: Optional[str] = None,
        face_visible: bool = True,
        voice_description: Optional[str] = None,
    ) -> dict:
        """Build fal.ai API arguments for the selected backend."""
        if self.backend == FalBackend.OVI:
            return self._args_ovi(
                image_url, prompt, dialogue, audio_description, seed, duration
            )
        elif self.backend == FalBackend.LTX:
            return self._args_ltx(
                image_url, prompt, dialogue, audio_description, seed, duration,
                end_image_url=end_image_url, face_visible=face_visible,
                voice_description=voice_description,
            )
        elif self.backend == FalBackend.KLING_O1_FLF:
            return self._args_kling_o1_flf(
                image_url, prompt, dialogue, audio_description, seed, duration,
                end_image_url=end_image_url,
            )
        elif self.backend in (FalBackend.VIDU_Q1_FLF, FalBackend.WAN_FLF):
            return self._args_flf_generic(
                image_url, prompt, dialogue, audio_description, seed, duration,
                end_image_url=end_image_url,
            )
        else:
            return self._args_kling(
                image_url, prompt, dialogue, audio_description, seed, duration
            )

    def _args_ovi(self, image_url, prompt, dialogue, audio_description, seed, duration=5):
        """Build Ovi arguments with <S>/<E> speech tokens."""
        full_prompt = self._build_ovi_prompt(prompt, dialogue, audio_description)
        args = {
            "prompt": full_prompt,
            "image_url": image_url,
            "num_inference_steps": 30,
            "duration": duration,  # Ovi accepts 5 or 10
        }
        if seed is not None:
            args["seed"] = seed
        return args

    def _args_ltx(self, image_url, prompt, dialogue, audio_description, seed, duration=6, end_image_url=None, face_visible=True, voice_description=None):
        """Build LTX 2.3 arguments with native audio generation."""
        # Sanitize voice — strip screaming/escalation, keep only accent
        safe_voice = _sanitize_voice_description(voice_description)

        if dialogue and face_visible:
            # Character scene: dialogue + camera + action + lip sync.
            # Keep the action text (choreography, ambient, character animation)
            # but prefix with "Visually:" so LTX treats it as visual direction,
            # not speech narration.
            if safe_voice:
                voice_clause = f' with a clear {safe_voice} accent'
            else:
                voice_clause = ''
            # Parse build_f1_video_prompt output into structural parts
            sentences = [s.strip() for s in prompt.split('. ') if s.strip()]
            camera_line = sentences[0] + '.' if sentences else ''
            # Negative guidance (always last sentences)
            neg_keywords = ('No face warping', 'Maintain consistent', 'No cars facing')
            neg_lines = [s for s in sentences if any(s.startswith(kw) for kw in neg_keywords)]
            neg_text = '. '.join(neg_lines) + '.' if neg_lines else ''
            # Action/animation = everything EXCEPT camera (first) and negative (last)
            action_lines = [
                s for s in sentences[1:]
                if not any(s.startswith(kw) for kw in neg_keywords)
            ]
            action_text = '. '.join(action_lines) + '.' if action_lines else ''
            full_prompt = (
                f'Character speaks calmly and clearly{voice_clause}: '
                f'"{dialogue}" '
                f'{camera_line} '
                f'Visually: {action_text} '
                f'{neg_text}'
            )
        elif dialogue and not face_visible:
            # Action/landscape scene — voiceover. Keep the visual action text.
            if safe_voice:
                voice_clause = f' in a clear {safe_voice} accent'
            else:
                voice_clause = ''
            sentences = [s.strip() for s in prompt.split('. ') if s.strip()]
            camera_line = sentences[0] + '.' if sentences else ''
            neg_keywords = ('No face warping', 'Maintain consistent', 'No cars facing')
            action_lines = [
                s for s in sentences[1:]
                if not any(s.startswith(kw) for kw in neg_keywords)
            ]
            neg_lines = [s for s in sentences if any(s.startswith(kw) for kw in neg_keywords)]
            action_text = '. '.join(action_lines) + '.' if action_lines else ''
            neg_text = '. '.join(neg_lines) + '.' if neg_lines else ''
            full_prompt = (
                f'Calm professional voiceover narration{voice_clause}: '
                f'"{dialogue}" '
                f'{camera_line} '
                f'Visually: {action_text} '
                f'The voice is off-screen narration only. No person speaking on screen. '
                f'{neg_text}'
            )
        else:
            full_prompt = prompt

        args = {
            "prompt": full_prompt,
            "image_url": image_url,
            "num_inference_steps": 30,
            "generate_audio": True,
            "duration": min(10, max(6, duration if duration % 2 == 0 else duration + 1)),  # LTX: 6, 8, or 10 only
        }
        if end_image_url is not None:
            args["end_image_url"] = end_image_url
        if audio_description:
            args["audio_prompt"] = audio_description
        if seed is not None:
            args["seed"] = seed
        return args

    @staticmethod
    def build_audio_prompt(
        audio_description: str | None,
        voice_description: str | None = None,
    ) -> str | None:
        """Build a rich audio prompt combining voice characteristics + scene audio.

        Prepends the character's voice/accent description so the audio model
        generates consistent voices across scenes.
        """
        parts = []
        if voice_description:
            parts.append(f"Voice: {voice_description}")
        if audio_description:
            parts.append(audio_description)
        return ". ".join(parts) if parts else None

    def _args_kling(self, image_url, prompt, dialogue, audio_description, seed, duration=5):
        """Build Kling 3.0 arguments."""
        enable_audio = self.backend in FAL_AUDIO_BACKENDS

        full_prompt = prompt
        if dialogue:
            full_prompt += f" The character says: \"{dialogue}\""

        args = {
            "prompt": full_prompt,
            "image_url": image_url,
            "duration": str(duration),  # Kling accepts string: "3" to "15"
            "aspect_ratio": "16:9",
        }
        if enable_audio:
            args["enable_audio"] = True
        if seed is not None:
            args["seed"] = seed
        return args

    def _args_kling_o1_flf(self, image_url, prompt, dialogue, audio_description, seed, duration=5, end_image_url=None):
        """Build Kling O1 FLF arguments. Requires end_image_url."""
        if end_image_url is None:
            raise FalVideoError("Kling O1 FLF requires end_image_url")

        full_prompt = prompt
        if dialogue:
            full_prompt += f' The character says: "{dialogue}"'

        # Kling O1 uses @Image1/@Image2 syntax in prompt for FLFV
        full_prompt = f"@Image1 {full_prompt} @Image2"

        args = {
            "prompt": full_prompt,
            "start_image_url": image_url,
            "end_image_url": end_image_url,
            "duration": str(duration),
            "aspect_ratio": "16:9",
        }
        if seed is not None:
            args["seed"] = seed
        return args

    def _args_flf_generic(self, image_url, prompt, dialogue, audio_description, seed, duration=5, end_image_url=None):
        """Build FLF arguments for Vidu Q1 and Wan backends. Requires end_image_url."""
        if end_image_url is None:
            raise FalVideoError(f"{self.display_name} requires end_image_url")

        full_prompt = prompt
        if dialogue:
            full_prompt += f' The character says: "{dialogue}"'

        args = {
            "prompt": full_prompt,
            "image_url": image_url,
            "end_image_url": end_image_url,
            "duration": duration,
        }
        if seed is not None:
            args["seed"] = seed
        return args

    @staticmethod
    def _build_ovi_prompt(
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> str:
        """Build Ovi prompt with <S>/<E> speech and <AUDCAP> audio tokens.

        Ovi uses special tokens:
        - <S>spoken words<E> for speech/dialogue with lip sync
        - <AUDCAP>audio description<ENDAUDCAP> for background sounds
        """
        parts = [
            "Subtle animated motion of the existing image. "
            "Maintain the exact art style, colors, and character appearance. "
            "Only add gentle movement: slight head turn, blinking, "
            "mouth movement for speech.",
            action,
        ]
        if dialogue:
            parts.append(f"<S>{dialogue}<E>")
        if audio_description:
            parts.append(f"<AUDCAP>{audio_description}<ENDAUDCAP>")
        return " ".join(parts)

    @staticmethod
    def _log_progress(scene_number: int, update) -> None:
        """Log fal.ai queue progress updates."""
        status = getattr(update, "status", None)
        if status:
            logger.info(f"Scene {scene_number}: fal.ai → {status}")
        logs = getattr(update, "logs", None)
        if logs:
            for log_entry in logs:
                msg = getattr(log_entry, "message", str(log_entry))
                logger.debug(f"Scene {scene_number}: {msg}")


# ------------------------------------------------------------------
# Convenience: list all available backends
# ------------------------------------------------------------------

# Per-backend cost rates ($/second of video)
FAL_COST_PER_SECOND: dict[FalBackend, float] = {
    FalBackend.OVI: 0.04,
    FalBackend.LTX: 0.06,
    FalBackend.KLING_STD: 0.084,
    FalBackend.KLING_STD_AUDIO: 0.126,
    FalBackend.KLING_PRO: 0.112,
    FalBackend.KLING_PRO_AUDIO: 0.168,
    FalBackend.KLING_O1_FLF: 0.112,
    FalBackend.VIDU_Q1_FLF: 0.10,
    FalBackend.WAN_FLF: 0.10,
}

ALL_FAL_BACKENDS: list[dict] = [
    {
        "value": b.value,
        "name": FAL_DISPLAY_NAMES[b],
        "model": FAL_MODEL_MAP[b],
        "has_audio": b in FAL_AUDIO_BACKENDS,
        "supports_flf": b in FAL_FLF_CAPABLE,
        "requires_flf": b in FAL_FLF_REQUIRED,
        "cost_per_second": FAL_COST_PER_SECOND.get(b, 0.10),
    }
    for b in FalBackend
]
