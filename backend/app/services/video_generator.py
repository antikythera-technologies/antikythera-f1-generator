"""Video generation service using Ovi (HuggingFace Gradio).

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
from typing import Optional

from gradio_client import Client, handle_file

from app.config import settings
from app.exceptions import VideoGenerationError

logger = logging.getLogger(__name__)


@dataclass
class VideoClip:
    """Generated video clip."""
    scene_number: int
    video_path: str
    generation_time_ms: int


@dataclass
class VideoPreset:
    """Preset configuration for video generation quality and style preservation."""
    sample_steps: int
    image_conditioning_strength: float
    denoise_strength: float
    guidance_scale: float


class VideoGenerator:
    """Service for generating video clips using Ovi with style preservation.

    The caricature preset is specifically tuned to preserve the art style
    of our Flux+LoRA+PuLID generated images during image-to-video conversion.
    """

    # Quality presets: balance between quality and style preservation
    # Lower steps + higher conditioning = better style preservation
    QUALITY_PRESETS = {
        "draft": VideoPreset(
            sample_steps=10,
            image_conditioning_strength=0.90,
            denoise_strength=0.40,
            guidance_scale=1.5,
        ),
        "standard": VideoPreset(
            sample_steps=20,
            image_conditioning_strength=0.85,
            denoise_strength=0.55,
            guidance_scale=2.0,
        ),
        "high": VideoPreset(
            sample_steps=30,
            image_conditioning_strength=0.80,
            denoise_strength=0.60,
            guidance_scale=2.5,
        ),
        "ultra": VideoPreset(
            sample_steps=40,
            image_conditioning_strength=0.75,
            denoise_strength=0.65,
            guidance_scale=3.0,
        ),
        # Optimized for our caricature art style — minimal re-interpretation
        "caricature": VideoPreset(
            sample_steps=15,
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
        self.space = settings.OVI_SPACE
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

        logger.info(
            f"VideoGenerator initialized: quality={quality}, "
            f"steps={self.sample_steps}, "
            f"conditioning={self.image_conditioning_strength:.2f}, "
            f"denoise={self.denoise_strength:.2f}, "
            f"guidance={self.guidance_scale:.1f}"
        )

    @property
    def client(self) -> Client:
        """Lazy initialization of Gradio client."""
        if self._client is None:
            logger.info(f"Connecting to Ovi space: {self.space}")
            hf_token = getattr(settings, 'HUGGINGFACE_TOKEN', None)
            if hf_token and hf_token.strip():
                logger.info("Using HuggingFace token for authenticated access")
                self._client = Client(self.space, token=hf_token)
            else:
                logger.warning("No HuggingFace token configured - using anonymous access")
                self._client = Client(self.space)
        return self._client

    def _generate_clip_sync(
        self,
        image_path: str,
        prompt: str,
    ) -> str:
        """Synchronous video generation (called from executor).

        Passes style-preservation parameters to the Ovi API.
        The API may not support all parameters depending on the space version —
        we pass them as kwargs and let the Gradio client handle it.
        """
        try:
            # Try with full parameter set (newer Ovi spaces support these)
            result = self.client.predict(
                text_prompt=prompt,
                sample_steps=self.sample_steps,
                image=handle_file(image_path),
                image_conditioning_strength=self.image_conditioning_strength,
                denoise_strength=self.denoise_strength,
                guidance_scale=self.guidance_scale,
                api_name="/generate_scene",
            )
        except TypeError:
            # Fallback: older Ovi space only accepts basic params
            logger.warning(
                "Ovi space does not support extended params, "
                "falling back to basic mode (steps only)"
            )
            result = self.client.predict(
                text_prompt=prompt,
                sample_steps=self.sample_steps,
                image=handle_file(image_path),
                api_name="/generate_scene",
            )

        if isinstance(result, dict):
            return result.get('video', result)
        return result

    async def generate_clip(
        self,
        scene_number: int,
        image_path: str,
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> VideoClip:
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
            f"(steps={self.sample_steps}, conditioning={self.image_conditioning_strength:.2f}, "
            f"denoise={self.denoise_strength:.2f})"
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

            return VideoClip(
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
