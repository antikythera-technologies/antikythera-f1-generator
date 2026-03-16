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

logger = logging.getLogger(__name__)


class FalBackend(str, Enum):
    """Available fal.ai video generation backends."""

    OVI = "fal-ovi"
    LTX = "fal-ltx"
    KLING_STD = "fal-kling-std"
    KLING_STD_AUDIO = "fal-kling-std-audio"
    KLING_PRO = "fal-kling-pro"
    KLING_PRO_AUDIO = "fal-kling-pro-audio"


# Map backend enum to fal.ai model endpoint
FAL_MODEL_MAP: dict[FalBackend, str] = {
    FalBackend.OVI: "fal-ai/ovi/image-to-video",
    FalBackend.LTX: "fal-ai/ltx-2.3/image-to-video",
    FalBackend.KLING_STD: "fal-ai/kling-video/v3/standard/image-to-video",
    FalBackend.KLING_STD_AUDIO: "fal-ai/kling-video/v3/standard/image-to-video",
    FalBackend.KLING_PRO: "fal-ai/kling-video/v3/pro/image-to-video",
    FalBackend.KLING_PRO_AUDIO: "fal-ai/kling-video/v3/pro/image-to-video",
}

# Backends that produce native audio (no TTS mux needed)
FAL_AUDIO_BACKENDS: set[FalBackend] = {
    FalBackend.OVI,
    FalBackend.LTX,
    FalBackend.KLING_STD_AUDIO,
    FalBackend.KLING_PRO_AUDIO,
}

# Human-readable names for logging
FAL_DISPLAY_NAMES: dict[FalBackend, str] = {
    FalBackend.OVI: "Ovi (fal.ai)",
    FalBackend.LTX: "LTX 2.3 (fal.ai)",
    FalBackend.KLING_STD: "Kling 3.0 Standard",
    FalBackend.KLING_STD_AUDIO: "Kling 3.0 Standard + Audio",
    FalBackend.KLING_PRO: "Kling 3.0 Pro",
    FalBackend.KLING_PRO_AUDIO: "Kling 3.0 Pro + Audio",
}


def estimate_speech_duration(dialogue: str | None, words_per_second: float = 2.5) -> float:
    """Estimate how many seconds a dialogue line takes to speak.
    
    Average conversational speech is ~150 wpm = 2.5 words/sec.
    We add 0.5s buffer for natural pauses.
    """
    if not dialogue:
        return 0.0
    word_count = len(dialogue.split())
    return (word_count / words_per_second) + 0.5


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

        # Validate FAL_KEY is set
        if not os.environ.get("FAL_KEY"):
            raise FalVideoError(
                "FAL_KEY environment variable not set. "
                "Get your key at https://fal.ai/dashboard/keys"
            )

    async def generate_clip(
        self,
        scene_number: int,
        image_url: str,
        prompt: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
        seed: Optional[int] = None,
        duration: Optional[int] = None,
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
            logger.info(
                f"Scene {scene_number}: Extended duration to {duration}s "
                f"for dialogue: {dialogue[:50]}..."
            )

        arguments = self._build_arguments(
            image_url=image_url,
            prompt=prompt,
            dialogue=dialogue,
            audio_description=audio_description,
            seed=seed,
            duration=duration,
        )

        logger.info(
            f"Scene {scene_number}: Generating via {self.display_name} "
            f"({self.model_id})"
        )
        logger.debug(f"Scene {scene_number}: Args: {arguments}")

        start_time = time.time()

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: fal_client.subscribe(
                    self.model_id,
                    arguments=arguments,
                    with_logs=True,
                    on_queue_update=lambda u: self._log_progress(scene_number, u),
                ),
            )
        except Exception as e:
            raise FalVideoError(
                f"Scene {scene_number}: fal.ai {self.display_name} failed: {e}"
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

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

        logger.info(f"Uploading to fal CDN: {local_path}")

        url = await asyncio.get_event_loop().run_in_executor(
            None, fal_client.upload_file, local_path
        )

        logger.info(f"Uploaded: {url}")
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
    ) -> dict:
        """Build fal.ai API arguments for the selected backend."""
        if self.backend == FalBackend.OVI:
            return self._args_ovi(
                image_url, prompt, dialogue, audio_description, seed, duration
            )
        elif self.backend == FalBackend.LTX:
            return self._args_ltx(
                image_url, prompt, dialogue, audio_description, seed, duration
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

    def _args_ltx(self, image_url, prompt, dialogue, audio_description, seed, duration=6):
        """Build LTX 2.3 arguments with native audio generation."""
        full_prompt = prompt
        if dialogue:
            full_prompt += f" The character says: \"{dialogue}\""

        args = {
            "prompt": full_prompt,
            "image_url": image_url,
            "num_inference_steps": 30,
            "generate_audio": True,
            "duration": duration,  # LTX accepts even values: 6, 8, 10, ..., 20
        }
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

ALL_FAL_BACKENDS: list[dict] = [
    {
        "value": b.value,
        "name": FAL_DISPLAY_NAMES[b],
        "model": FAL_MODEL_MAP[b],
        "has_audio": b in FAL_AUDIO_BACKENDS,
    }
    for b in FalBackend
]
