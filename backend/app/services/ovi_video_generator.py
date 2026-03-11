"""Video generation service using Ovi (self-hosted Gradio on RunPod).

Style preservation is the primary challenge for image-to-video conversion.
The default I2V behaviour re-interprets the source image through the video
model's latent space, which destroys carefully crafted caricature art style.

Key parameters for style preservation:
- sample_steps: fewer steps = less deviation from source
- image_conditioning_strength: higher = more faithful to source image
- denoise_strength: lower = less re-encoding, preserves more of original
- guidance_scale: lower = less hallucination, more source fidelity
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

from gradio_client import Client, handle_file

from app.config import settings
from app.exceptions import VideoGenerationError

logger = logging.getLogger(__name__)


@dataclass
class OviVideoClip:
    """Generated video clip."""
    scene_number: int
    video_path: str
    generation_time_ms: int


@dataclass
class OviVideoPreset:
    """Preset configuration for video generation quality and style preservation."""
    sample_steps: int
    image_conditioning_strength: float
    denoise_strength: float
    guidance_scale: float


class OviVideoGenerator:
    """Service for generating video clips using Ovi with style preservation.

    The caricature preset is specifically tuned to preserve the art style
    of our Flux+LoRA+PuLID generated images during image-to-video conversion.
    """

    # Quality presets: balance between quality and style preservation
    # Lower steps + higher conditioning = better style preservation
    QUALITY_PRESETS = {
        "draft": OviVideoPreset(
            sample_steps=20,
            image_conditioning_strength=0.90,
            denoise_strength=0.40,
            guidance_scale=1.5,
        ),
        "standard": OviVideoPreset(
            sample_steps=20,
            image_conditioning_strength=0.85,
            denoise_strength=0.55,
            guidance_scale=2.0,
        ),
        "high": OviVideoPreset(
            sample_steps=30,
            image_conditioning_strength=0.80,
            denoise_strength=0.60,
            guidance_scale=2.5,
        ),
        "ultra": OviVideoPreset(
            sample_steps=40,
            image_conditioning_strength=0.75,
            denoise_strength=0.65,
            guidance_scale=3.0,
        ),
        # Optimized for our caricature art style — minimal re-interpretation
        "caricature": OviVideoPreset(
            sample_steps=20,
            image_conditioning_strength=0.92,
            denoise_strength=0.35,
            guidance_scale=1.5,
        ),
    }

    def __init__(
        self,
        quality: str = "standard",
        image_conditioning_strength: Optional[float] = None,
        denoise_strength: Optional[float] = None,
        guidance_scale: Optional[float] = None,
    ):
        """Initialize video generator.

        Args:
            quality: Preset name (draft/standard/high/ultra/caricature)
            image_conditioning_strength: Override preset value (0.0-1.0)
            denoise_strength: Override preset value (0.0-1.0)
            guidance_scale: Override preset value
        """
        self.server_url = settings.OVI_SERVER_URL
        self.timeout = settings.OVI_TIMEOUT_SECONDS

        # Load preset defaults
        preset = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])
        self.sample_steps = preset.sample_steps
        self.image_conditioning_strength = (
            image_conditioning_strength
            if image_conditioning_strength is not None
            else preset.image_conditioning_strength
        )
        self.denoise_strength = (
            denoise_strength
            if denoise_strength is not None
            else preset.denoise_strength
        )
        self.guidance_scale = (
            guidance_scale
            if guidance_scale is not None
            else preset.guidance_scale
        )

        # Allow env-level overrides from settings
        if image_conditioning_strength is None and settings.OVI_IMAGE_CONDITIONING_STRENGTH != 0.85:
            self.image_conditioning_strength = settings.OVI_IMAGE_CONDITIONING_STRENGTH
        if denoise_strength is None and settings.OVI_DENOISE_STRENGTH != 0.55:
            self.denoise_strength = settings.OVI_DENOISE_STRENGTH
        if guidance_scale is None and settings.OVI_GUIDANCE_SCALE != 2.0:
            self.guidance_scale = settings.OVI_GUIDANCE_SCALE

        self._client: Optional[Client] = None

        # Video generation defaults (configurable via settings)
        self.frame_height: int = getattr(settings, "OVI_FRAME_HEIGHT", 512)
        self.frame_width: int = getattr(settings, "OVI_FRAME_WIDTH", 992)
        self.video_seed: int = getattr(settings, "OVI_VIDEO_SEED", 100)
        self.solver_name: Literal["unipc", "euler", "dpm++"] = getattr(
            settings, "OVI_SOLVER_NAME", "unipc"
        )
        self.shift: float = getattr(settings, "OVI_SHIFT", 5.0)
        self.video_guidance_scale: float = getattr(
            settings, "OVI_VIDEO_GUIDANCE_SCALE", 4.0
        )
        self.audio_guidance_scale: float = getattr(
            settings, "OVI_AUDIO_GUIDANCE_SCALE", 3.0
        )
        self.slg_layer: float = getattr(settings, "OVI_SLG_LAYER", 11)
        self.video_negative_prompt: str = getattr(
            settings, "OVI_VIDEO_NEGATIVE_PROMPT", ""
        )
        self.audio_negative_prompt: str = getattr(
            settings, "OVI_AUDIO_NEGATIVE_PROMPT", ""
        )

    @property
    def client(self) -> Client:
        """Lazy initialization of Gradio client."""
        if self._client is None:
            logger.info(f"Connecting to Ovi server: {self.server_url}")
            self._client = Client(self.server_url)
        return self._client

    def _generate_clip_sync(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """Synchronous video generation (called from executor).

        Passes style-preservation parameters to the Ovi API.
        Falls back to full Ovi parameter set if extended params are rejected.
        """
        try:
            result = self.client.predict(
                text_prompt=prompt,
                image=handle_file(image_path),
                video_frame_height=self.frame_height,
                video_frame_width=self.frame_width,
                video_seed=self.video_seed,
                solver_name=self.solver_name,
                sample_steps=self.sample_steps,
                shift=self.shift,
                video_guidance_scale=self.video_guidance_scale,
                audio_guidance_scale=self.audio_guidance_scale,
                slg_layer=self.slg_layer,
                video_negative_prompt=self.video_negative_prompt,
                audio_negative_prompt=self.audio_negative_prompt,
                api_name="/generate_video",
            )
        except TypeError:
            logger.warning(
                "Ovi does not support full params, falling back to basic mode"
            )
            result = self.client.predict(
                text_prompt=prompt,
                sample_steps=self.sample_steps,
                image=handle_file(image_path),
                api_name="/generate_video",
            )

        if hasattr(result, "path"):
            return result.path
        if isinstance(result, dict):
            return result.get("path", result.get("video", str(result)))
        return str(result)

    async def generate_clip(
        self,
        scene_number: int,
        image_path: str,
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> OviVideoClip:
        """
        Generate a 5-second video clip from an image.

        Args:
            scene_number: Scene number (1-24)
            image_path: Local path to the source image
            action: Description of what happens in the scene
            dialogue: Speech content (optional)
            audio_description: Background audio description (optional)

        Returns:
            VideoClip with path to generated video
        """
        logger.info(
            f"Scene {scene_number}: Starting video generation "
            f"(steps={self.sample_steps}, {self.frame_width}x{self.frame_height})"
        )
        logger.debug(f"Scene {scene_number}: Image: {image_path}")

        # Build prompt with Ovi special tokens
        prompt = self._build_prompt(action, dialogue, audio_description)
        logger.debug(f"Scene {scene_number}: Prompt: {prompt}")

        start_time = time.time()

        try:
            video_path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._generate_clip_sync,
                image_path,
                prompt,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Scene {scene_number}: Generated in {elapsed_ms}ms")
            logger.debug(f"Scene {scene_number}: Output: {video_path}")

            return OviVideoClip(
                scene_number=scene_number,
                video_path=video_path,
                generation_time_ms=elapsed_ms,
            )

        except Exception as e:
            logger.error(f"Scene {scene_number}: Video generation failed - {e}")
            raise VideoGenerationError(f"Scene {scene_number}: {e}")

    def _build_prompt(
        self,
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> str:
        """
        Build Ovi prompt with special tokens and style-preservation hints.

        Ovi uses special tokens for speech and audio:
        - <S>...<E> for speech/dialogue
        - <AUDCAP>...<ENDAUDCAP> for audio description

        The prompt is prefixed with style preservation instructions to
        minimize the model's tendency to re-interpret the source art style.
        """
        parts = []

        # Style preservation prefix — tells the model to animate, not re-draw
        parts.append(
            "Subtle animated motion of the existing image. "
            "Maintain the exact art style, colors, and character appearance. "
            "Only add gentle movement: slight head turn, blinking, mouth movement for speech."
        )

        # Scene action
        parts.append(action)

        if dialogue:
            parts.append(f"<S>{dialogue}<E>")

        if audio_description:
            parts.append(f"<AUDCAP>{audio_description}<ENDAUDCAP>")

        return " ".join(parts)


# Prompt templates for common scene types
SCENE_TEMPLATES = {
    "celebration": (
        "Subtle animated celebration of the character. Maintain exact art style. "
        "{character} raises arms slightly. <S>{dialogue}<E>. "
        "<AUDCAP>Cheering crowd, triumphant music<ENDAUDCAP>"
    ),
    "frustration": (
        "Subtle animated reaction. Maintain exact art style. "
        "{character} shakes head slightly. <S>{dialogue}<E>. "
        "<AUDCAP>Sighing, subdued ambient noise<ENDAUDCAP>"
    ),
    "commentary": (
        "Subtle speaking animation. Maintain exact art style. "
        "{character} speaks to camera with gentle mouth movement. <S>{dialogue}<E>. "
        "<AUDCAP>Studio ambiance, professional voice<ENDAUDCAP>"
    ),
    "argument": (
        "Subtle animated gesturing. Maintain exact art style. "
        "{character} gestures while speaking. <S>{dialogue}<E>. "
        "<AUDCAP>Heated discussion, raised voices<ENDAUDCAP>"
    ),
    "reaction": (
        "Subtle animated reaction. Maintain exact art style. "
        "{character} reacts with surprise. <S>{dialogue}<E>. "
        "<AUDCAP>Gasp, dramatic music sting<ENDAUDCAP>"
    ),
}


def apply_template(template_name: str, character: str, dialogue: str) -> str:
    """Apply a prompt template for a scene type."""
    template = SCENE_TEMPLATES.get(template_name, SCENE_TEMPLATES["commentary"])
    return template.format(character=character, dialogue=dialogue)
