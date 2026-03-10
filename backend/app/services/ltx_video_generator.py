"""LTX-2 video generation service via ComfyUI API on RunPod.

LTX-2 is a 19B parameter video generation model that supports image-to-video
with synchronized audio generation. It runs on our RunPod pod via ComfyUI.

Style preservation strategy:
- Low denoise_strength (0.3-0.5) to avoid re-interpreting the source image
- High conditioning_scale (0.8-0.95) to anchor the video to the source
- Moderate guidance_scale (2.0-4.0) for prompt-following without hallucination
- Fewer steps (15-25) to reduce drift from source
- The prompt explicitly instructs "animate, don't redraw"
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.exceptions import VideoGenerationError

logger = logging.getLogger(__name__)


@dataclass
class LTX2VideoClip:
    """Generated LTX-2 video clip."""
    scene_number: int
    video_path: str
    generation_time_ms: int


class LTX2VideoGenerator:
    """Generate video clips from images using LTX-2 via ComfyUI API.

    The ComfyUI workflow:
    1. Load source image
    2. Encode with LTX-2 VAE (image)
    3. Text encode with Gemma 3 12B
    4. LTX-2 sampler with image conditioning
    5. Decode and save video

    Style preservation is controlled by denoise_strength and conditioning_scale.
    Lower denoise = less re-interpretation. Higher conditioning = more source fidelity.
    """

    # Style-preservation presets
    PRESETS = {
        "draft": {
            "denoise_strength": 0.50,
            "conditioning_scale": 0.85,
            "guidance_scale": 3.0,
            "steps": 15,
        },
        "standard": {
            "denoise_strength": 0.45,
            "conditioning_scale": 0.90,
            "guidance_scale": 3.0,
            "steps": 20,
        },
        "high": {
            "denoise_strength": 0.40,
            "conditioning_scale": 0.92,
            "guidance_scale": 2.5,
            "steps": 25,
        },
        # Maximum style preservation — minimal motion, maximum fidelity
        "caricature": {
            "denoise_strength": 0.30,
            "conditioning_scale": 0.95,
            "guidance_scale": 2.0,
            "steps": 18,
        },
    }

    def __init__(
        self,
        quality: str = "standard",
        denoise_strength: Optional[float] = None,
        conditioning_scale: Optional[float] = None,
        guidance_scale: Optional[float] = None,
        steps: Optional[int] = None,
    ):
        """Initialize LTX-2 video generator.

        Args:
            quality: Preset name (draft/standard/high/caricature)
            denoise_strength: Override preset (0.0-1.0, lower = preserve more)
            conditioning_scale: Override preset (0.0-1.0, higher = more faithful)
            guidance_scale: Override preset
            steps: Override preset
        """
        self.comfyui_url = settings.comfyui_url
        self.timeout = settings.COMFYUI_TIMEOUT_SECONDS
        self.output_dir = Path("/tmp/ltx2-videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load preset
        preset = self.PRESETS.get(quality, self.PRESETS["standard"])

        self.denoise_strength = denoise_strength or settings.LTX2_DENOISE_STRENGTH
        self.conditioning_scale = conditioning_scale or settings.LTX2_CONDITIONING_SCALE
        self.guidance_scale = guidance_scale or settings.LTX2_GUIDANCE_SCALE
        self.steps = steps or settings.LTX2_STEPS
        self.frame_count = settings.LTX2_FRAME_COUNT
        self.width = settings.LTX2_WIDTH
        self.height = settings.LTX2_HEIGHT
        self.fps = settings.LTX2_FPS
        self.seed = settings.LTX2_SEED

        # If no explicit overrides were given, use preset values
        if denoise_strength is None and quality in self.PRESETS:
            self.denoise_strength = preset["denoise_strength"]
        if conditioning_scale is None and quality in self.PRESETS:
            self.conditioning_scale = preset["conditioning_scale"]
        if guidance_scale is None and quality in self.PRESETS:
            self.guidance_scale = preset["guidance_scale"]
        if steps is None and quality in self.PRESETS:
            self.steps = preset["steps"]

        logger.info(
            f"LTX2VideoGenerator initialized: quality={quality}, "
            f"denoise={self.denoise_strength:.2f}, "
            f"conditioning={self.conditioning_scale:.2f}, "
            f"guidance={self.guidance_scale:.1f}, "
            f"steps={self.steps}"
        )

    def _build_workflow(
        self,
        image_filename: str,
        prompt: str,
        seed: Optional[int] = None,
    ) -> dict:
        """Build ComfyUI workflow for LTX-2 image-to-video.

        The workflow uses image conditioning to anchor the video generation
        to the source caricature image. Key nodes:

        - LTXVLoader: Loads the LTX-2 19B model
        - LTXVTextEncode: Encodes text with Gemma 3 12B
        - LTXVImageEncode: Encodes the source image for conditioning
        - LTXVConditioning: Combines text + image conditioning
        - LTXVSampler: Generates video frames with controlled denoise
        - LTXVDecode: Decodes latents to video frames
        - VHS_VideoCombine: Saves as MP4

        Args:
            image_filename: Filename of the source image (already uploaded to ComfyUI)
            prompt: Text description of desired motion
            seed: Random seed (-1 for random)
        """
        effective_seed = seed if seed is not None else self.seed
        if effective_seed == -1:
            import random
            effective_seed = random.randint(0, 2**32 - 1)

        return {
            # Load LTX-2 model (19B FP8)
            "1": {
                "class_type": "LTXVLoader",
                "inputs": {
                    "model_name": "ltxv-2b-0.9.6-distilled-fp8.safetensors",
                    "dtype": "fp8_e4m3fn",
                },
            },
            # Load text encoder (Gemma 3 12B FP8)
            "2": {
                "class_type": "LTXVTextEncode",
                "inputs": {
                    "positive_prompt": prompt,
                    "negative_prompt": (
                        "blurry, distorted, deformed, ugly, low quality, "
                        "photorealistic, different art style, style change, "
                        "morphing, melting face, horror, grotesque"
                    ),
                    "model": ["1", 0],
                },
            },
            # Load source image
            "3": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": image_filename,
                },
            },
            # Resize image to video dimensions
            "4": {
                "class_type": "ImageResize+",
                "inputs": {
                    "image": ["3", 0],
                    "width": self.width,
                    "height": self.height,
                    "interpolation": "lanczos",
                    "method": "fill / crop",
                    "condition": "always",
                    "multiple_of": 32,
                },
            },
            # Encode source image for conditioning
            "5": {
                "class_type": "LTXVImageEncode",
                "inputs": {
                    "image": ["4", 0],
                    "model": ["1", 0],
                    "image_conditioning_scale": self.conditioning_scale,
                },
            },
            # Set up conditioning (text + image)
            "6": {
                "class_type": "LTXVConditioning",
                "inputs": {
                    "positive": ["2", 0],
                    "negative": ["2", 1],
                    "latent": ["5", 0],
                    "frame_count": self.frame_count,
                    "width": self.width,
                    "height": self.height,
                },
            },
            # Sample video frames
            "7": {
                "class_type": "LTXVSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["6", 0],
                    "negative": ["6", 1],
                    "latent": ["6", 2],
                    "seed": effective_seed,
                    "steps": self.steps,
                    "cfg": self.guidance_scale,
                    "denoise": self.denoise_strength,
                    "scheduler": "normal",
                },
            },
            # Decode latents to video
            "8": {
                "class_type": "LTXVDecode",
                "inputs": {
                    "model": ["1", 0],
                    "samples": ["7", 0],
                },
            },
            # Save as video file
            "9": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["8", 0],
                    "frame_rate": self.fps,
                    "loop_count": 0,
                    "filename_prefix": "ltx2_video",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True,
                },
            },
        }

    async def upload_image(self, image_path: str) -> str:
        """Upload source image to ComfyUI input directory.

        Args:
            image_path: Local path to the image file

        Returns:
            Filename as it appears in ComfyUI's input directory
        """
        filename = Path(image_path).name

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(image_path, "rb") as f:
                files = {"image": (filename, f, "image/png")}
                data = {"overwrite": "true"}
                resp = await client.post(
                    f"{self.comfyui_url}/upload/image",
                    files=files,
                    data=data,
                )

            if resp.status_code != 200:
                raise VideoGenerationError(
                    f"Failed to upload image to ComfyUI: {resp.status_code} {resp.text[:200]}"
                )

            result = resp.json()
            uploaded_name = result.get("name", filename)
            logger.info(f"Uploaded image to ComfyUI: {uploaded_name}")
            return uploaded_name

    async def _queue_prompt(self, workflow: dict) -> str:
        """Send workflow to ComfyUI and return prompt ID."""
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.comfyui_url}/prompt",
                json=payload,
            )

        if resp.status_code != 200:
            raise VideoGenerationError(
                f"Failed to queue ComfyUI prompt: {resp.status_code} {resp.text[:300]}"
            )

        data = resp.json()
        prompt_id = data.get("prompt_id")
        logger.info(f"Queued ComfyUI prompt: {prompt_id}")
        return prompt_id

    async def _wait_for_completion(self, prompt_id: str) -> dict:
        """Poll ComfyUI until the prompt completes."""
        start = time.time()

        while (time.time() - start) < self.timeout:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.comfyui_url}/history/{prompt_id}")

            if resp.status_code == 200:
                data = resp.json()
                if prompt_id in data:
                    result = data[prompt_id]
                    status = result.get("status", {}).get("status_str", "unknown")
                    if status == "success":
                        return result
                    elif status == "error":
                        error_msg = str(result.get("status", {}))[:500]
                        raise VideoGenerationError(
                            f"ComfyUI workflow failed: {error_msg}"
                        )

            elapsed = int(time.time() - start)
            if elapsed % 10 == 0:
                logger.debug(f"Waiting for ComfyUI... ({elapsed}s)")

            await asyncio.sleep(2)

        raise VideoGenerationError(
            f"ComfyUI timeout after {self.timeout}s for prompt {prompt_id}"
        )

    async def _download_video(self, result: dict, output_path: str) -> str:
        """Download generated video from ComfyUI output."""
        outputs = result.get("outputs", {})

        for node_id, node_output in outputs.items():
            # VHS_VideoCombine outputs gifs/videos
            gifs = node_output.get("gifs", [])
            for vid in gifs:
                vid_filename = vid["filename"]
                subfolder = vid.get("subfolder", "")
                vid_type = vid.get("type", "output")

                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{self.comfyui_url}/view",
                        params={
                            "filename": vid_filename,
                            "subfolder": subfolder,
                            "type": vid_type,
                        },
                    )

                if resp.status_code == 200:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(resp.content)
                    size_kb = len(resp.content) / 1024
                    logger.info(f"Downloaded video: {output_path} ({size_kb:.0f} KB)")
                    return output_path

            # Also check for video key (some nodes use this)
            videos = node_output.get("videos", [])
            for vid in videos:
                vid_filename = vid["filename"]
                subfolder = vid.get("subfolder", "")

                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{self.comfyui_url}/view",
                        params={
                            "filename": vid_filename,
                            "subfolder": subfolder,
                            "type": "output",
                        },
                    )

                if resp.status_code == 200:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(resp.content)
                    size_kb = len(resp.content) / 1024
                    logger.info(f"Downloaded video: {output_path} ({size_kb:.0f} KB)")
                    return output_path

        raise VideoGenerationError("No video found in ComfyUI output")

    async def generate_clip(
        self,
        scene_number: int,
        image_path: str,
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> LTX2VideoClip:
        """Generate a video clip from a caricature image using LTX-2.

        Args:
            scene_number: Scene number (1-24)
            image_path: Local path to the source caricature image
            action: Description of what happens in the scene
            dialogue: Speech content (optional, used in prompt)
            audio_description: Background audio description (optional)

        Returns:
            LTX2VideoClip with path to generated video
        """
        logger.info(
            f"Scene {scene_number}: Starting LTX-2 video generation "
            f"(denoise={self.denoise_strength:.2f}, "
            f"conditioning={self.conditioning_scale:.2f}, "
            f"steps={self.steps})"
        )

        start_time = time.time()

        try:
            # Upload source image to ComfyUI
            image_filename = await self.upload_image(image_path)

            # Build style-preserving prompt
            prompt = self._build_prompt(action, dialogue, audio_description)
            logger.debug(f"Scene {scene_number}: Prompt: {prompt}")

            # Build and queue workflow
            workflow = self._build_workflow(image_filename, prompt)
            prompt_id = await self._queue_prompt(workflow)

            # Wait for completion
            result = await self._wait_for_completion(prompt_id)

            # Download video
            output_path = str(
                self.output_dir / f"scene_{scene_number:02d}_{int(time.time())}.mp4"
            )
            video_path = await self._download_video(result, output_path)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Scene {scene_number}: LTX-2 generated in {elapsed_ms}ms")

            return LTX2VideoClip(
                scene_number=scene_number,
                video_path=video_path,
                generation_time_ms=elapsed_ms,
            )

        except Exception as e:
            logger.error(f"Scene {scene_number}: LTX-2 video generation failed - {e}")
            raise VideoGenerationError(f"Scene {scene_number} (LTX-2): {e}")

    def _build_prompt(
        self,
        action: str,
        dialogue: Optional[str] = None,
        audio_description: Optional[str] = None,
    ) -> str:
        """Build a style-preserving prompt for LTX-2.

        Unlike Ovi, LTX-2 doesn't use special tokens for speech/audio.
        Instead, we describe the desired subtle animation while explicitly
        instructing the model to preserve the source art style.
        """
        parts = [
            "Animate this stylized caricature illustration with subtle, gentle motion.",
            "Maintain the EXACT art style, colors, lighting, and character proportions.",
            "Do NOT change the art style or make it more realistic.",
            "Add only subtle movement:",
        ]

        # Describe the motion
        parts.append(action)

        if dialogue:
            parts.append(f"The character speaks: \"{dialogue}\"")
            parts.append("Show subtle mouth movement for speech.")

        if audio_description:
            parts.append(f"Background atmosphere: {audio_description}")

        parts.append(
            "Keep all motion minimal and subtle. "
            "The character should look like a gently animated illustration, "
            "not a re-drawn or reinterpreted image."
        )

        return " ".join(parts)

    async def check_health(self) -> bool:
        """Check if ComfyUI is reachable and responsive."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.comfyui_url}/system_stats")
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"ComfyUI health check failed: {e}")
            return False
