"""Video generation service using Ovi (HuggingFace Gradio)."""

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


class VideoGenerator:
    """Service for generating video clips using Ovi."""

    # Quality presets (sample_steps: higher = better quality, slower)
    QUALITY_PRESETS = {
        "draft": 15,      # Fast preview
        "standard": 30,   # Good balance
        "high": 50,       # High quality
        "ultra": 75,      # Maximum quality (slow)
    }

    def __init__(self, quality: str = "standard"):
        self.space = settings.OVI_SPACE
        self.timeout = settings.OVI_TIMEOUT_SECONDS
        self.sample_steps = self.QUALITY_PRESETS.get(quality, 30)
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        """Lazy initialization of Gradio client."""
        if self._client is None:
            logger.info(f"Connecting to Ovi space: {self.space}")
            # Use HuggingFace token if available for authenticated access
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
        """Synchronous video generation (called from executor)."""
        # Ovi API expects: text_prompt, sample_steps, image (in that order)
        # IMPORTANT: Use handle_file() to properly format the image for Gradio
        result = self.client.predict(
            text_prompt=prompt,
            sample_steps=self.sample_steps,
            image=handle_file(image_path),
            api_name="/generate_scene",
        )
        # Result is a dict with 'video' key containing the path
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
        logger.info(f"Scene {scene_number}: Starting video generation (steps={self.sample_steps})")
        logger.debug(f"Scene {scene_number}: Image: {image_path}")

        # Build prompt with Ovi special tokens
        prompt = self._build_prompt(action, dialogue, audio_description)
        logger.debug(f"Scene {scene_number}: Prompt: {prompt}")

        start_time = time.time()

        try:
            # Run sync Gradio call in executor to avoid blocking
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
        Build Ovi prompt with special tokens.

        Ovi uses special tokens for speech and audio:
        - <S>...<E> for speech/dialogue
        - <AUDCAP>...<ENDAUDCAP> for audio description
        """
        parts = [action]

        if dialogue:
            parts.append(f"<S>{dialogue}<E>")

        if audio_description:
            parts.append(f"<AUDCAP>{audio_description}<ENDAUDCAP>")

        return " ".join(parts)


# Prompt templates for common scene types
SCENE_TEMPLATES = {
    "celebration": "{character} celebrates with raised arms. <S>{dialogue}<E>. <AUDCAP>Cheering crowd, triumphant music<ENDAUDCAP>",
    "frustration": "{character} shakes head in disappointment. <S>{dialogue}<E>. <AUDCAP>Sighing, subdued ambient noise<ENDAUDCAP>",
    "commentary": "{character} speaks to camera. <S>{dialogue}<E>. <AUDCAP>Studio ambiance, professional voice<ENDAUDCAP>",
    "argument": "{character} gestures emphatically while speaking. <S>{dialogue}<E>. <AUDCAP>Heated discussion, raised voices<ENDAUDCAP>",
    "reaction": "{character} reacts with surprise. <S>{dialogue}<E>. <AUDCAP>Gasp, dramatic music sting<ENDAUDCAP>",
}


def apply_template(template_name: str, character: str, dialogue: str) -> str:
    """Apply a prompt template for a scene type."""
    template = SCENE_TEMPLATES.get(template_name, SCENE_TEMPLATES["commentary"])
    return template.format(character=character, dialogue=dialogue)
