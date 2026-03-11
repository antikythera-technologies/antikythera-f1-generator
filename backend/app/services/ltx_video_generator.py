"""LTX 2.3 video generation service via ComfyUI.

Generates 5-second video clips using first-frame + last-frame conditioning.
The model interpolates between start and end images based on a text prompt
describing the camera movement and character motion.

ComfyUI workflow chain (17 nodes):
  CheckpointLoaderSimple -> CLIPTextEncode(pos) + CLIPTextEncode(neg)
  -> LTXVConditioning -> EmptyLTXVLatentVideo
  -> LTXVAddGuide(start, frame_idx=0) -> LTXVAddGuide(end, frame_idx=-1)
  -> LTXVApplySTG -> STGGuiderAdvanced -> LTXVScheduler
  -> KSamplerSelect -> RandomNoise -> SamplerCustomAdvanced
  -> LTXVSpatioTemporalTiledVAEDecode -> SaveWEBM
"""

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LTXVideoClip:
    """Result of LTX 2.3 video generation."""

    scene_number: int
    video_path: str
    generation_time_ms: int
    prompt_used: str
    seed_used: int


class LTXVideoGenerationError(Exception):
    """Raised when LTX video generation fails."""

    pass


class LTXVideoGenerator:
    """Generate video clips using LTX 2.3 via ComfyUI with first/last frame support.

    Quality presets balance between motion fidelity and style preservation.
    The 'caricature' preset minimizes re-interpretation of the source art style
    by using lower STG scale values and fewer sampling steps.
    """

    PRESETS = {
        "caricature": {
            "steps": 18,
            "stg_block_indices": "14, 19",
            "sigmas": "1.0, 0.9933, 0.9850, 0.9767, 0.9008, 0.6180",
            "cfg_values": "6, 4, 4, 3, 2, 1",
            "stg_scale_values": "2, 2, 2, 1, 1, 0",
            "stg_rescale_values": "1, 1, 1, 1, 1, 1",
            "stg_layers_indices": "[29], [29], [29], [29], [29], [29]",
            "start_frame_strength": 1.0,
            "end_frame_strength": 1.0,
        },
        "standard": {
            "steps": 20,
            "stg_block_indices": "14, 19",
            "sigmas": "1.0, 0.9933, 0.9850, 0.9767, 0.9008, 0.6180",
            "cfg_values": "8, 6, 6, 4, 3, 1",
            "stg_scale_values": "4, 4, 3, 2, 1, 0",
            "stg_rescale_values": "1, 1, 1, 1, 1, 1",
            "stg_layers_indices": "[29], [29], [29], [29], [29], [29]",
            "start_frame_strength": 1.0,
            "end_frame_strength": 1.0,
        },
        "high_motion": {
            "steps": 25,
            "stg_block_indices": "14, 19",
            "sigmas": "1.0, 0.9933, 0.9850, 0.9767, 0.9008, 0.6180",
            "cfg_values": "10, 8, 8, 6, 4, 2",
            "stg_scale_values": "6, 6, 5, 4, 2, 0",
            "stg_rescale_values": "1, 1, 1, 1, 1, 1",
            "stg_layers_indices": "[29], [29], [29], [29], [29], [29]",
            "start_frame_strength": 0.9,
            "end_frame_strength": 0.9,
        },
    }

    def __init__(self, quality: str = "caricature"):
        from app.services.comfyui_client import ComfyUIClient

        self.client = ComfyUIClient(
            poll_timeout=float(settings.COMFYUI_TIMEOUT_SECONDS),
        )
        self.output_dir = Path("/tmp/f1-videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load preset
        preset = self.PRESETS.get(quality, self.PRESETS["caricature"])
        self.steps = preset["steps"]
        self.stg_block_indices = preset["stg_block_indices"]
        self.sigmas = preset["sigmas"]
        self.cfg_values = preset["cfg_values"]
        self.stg_scale_values = preset["stg_scale_values"]
        self.stg_rescale_values = preset["stg_rescale_values"]
        self.stg_layers_indices = preset["stg_layers_indices"]
        self.start_frame_strength = preset["start_frame_strength"]
        self.end_frame_strength = preset["end_frame_strength"]

        # Allow settings overrides - if a config value differs from the
        # default, it means the operator explicitly set it, so honour it.
        if settings.LTX23_STEPS != 20:
            self.steps = settings.LTX23_STEPS
        if settings.LTX23_STG_BLOCK_INDICES != "14, 19":
            self.stg_block_indices = settings.LTX23_STG_BLOCK_INDICES
        if settings.LTX23_STG_SIGMAS != "1.0, 0.9933, 0.9850, 0.9767, 0.9008, 0.6180":
            self.sigmas = settings.LTX23_STG_SIGMAS
        if settings.LTX23_STG_CFG_VALUES != "8, 6, 6, 4, 3, 1":
            self.cfg_values = settings.LTX23_STG_CFG_VALUES
        if settings.LTX23_STG_SCALE_VALUES != "4, 4, 3, 2, 1, 0":
            self.stg_scale_values = settings.LTX23_STG_SCALE_VALUES
        if settings.LTX23_STG_RESCALE_VALUES != "1, 1, 1, 1, 1, 1":
            self.stg_rescale_values = settings.LTX23_STG_RESCALE_VALUES
        if settings.LTX23_STG_LAYERS_INDICES != "[29], [29], [29], [29], [29], [29]":
            self.stg_layers_indices = settings.LTX23_STG_LAYERS_INDICES
        if settings.LTX23_START_FRAME_STRENGTH != 1.0:
            self.start_frame_strength = settings.LTX23_START_FRAME_STRENGTH
        if settings.LTX23_END_FRAME_STRENGTH != 1.0:
            self.end_frame_strength = settings.LTX23_END_FRAME_STRENGTH

    # ------------------------------------------------------------------
    # Workflow builder
    # ------------------------------------------------------------------

    def _build_workflow(
        self,
        start_frame_filename: str,
        end_frame_filename: str,
        video_prompt: str,
        seed: int,
        width: int | None = None,
        height: int | None = None,
        frame_count: int | None = None,
    ) -> dict[str, Any]:
        """Build ComfyUI workflow for LTX 2.3 image-to-video with first/last frame.

        Constructs a 17-node workflow using verified ComfyUI node class_types:
        CheckpointLoaderSimple, LoadImage, CLIPTextEncode, LTXVConditioning,
        EmptyLTXVLatentVideo, LTXVAddGuide, LTXVApplySTG, STGGuiderAdvanced,
        LTXVScheduler, KSamplerSelect, RandomNoise, SamplerCustomAdvanced,
        LTXVSpatioTemporalTiledVAEDecode, SaveWEBM.
        """
        w = width or settings.LTX23_WIDTH
        h = height or settings.LTX23_HEIGHT
        frames = frame_count or settings.LTX23_FRAME_COUNT
        fps = settings.LTX23_FPS

        workflow: dict[str, Any] = {}

        # --- Node 1: CheckpointLoaderSimple (loads MODEL, CLIP, VAE) ---
        workflow["1"] = {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": settings.LTX23_MODEL_NAME,
            },
        }

        # --- Node 2: LoadImage (start frame) ---
        workflow["2"] = {
            "class_type": "LoadImage",
            "inputs": {
                "image": start_frame_filename,
            },
        }

        # --- Node 3: LoadImage (end frame) ---
        workflow["3"] = {
            "class_type": "LoadImage",
            "inputs": {
                "image": end_frame_filename,
            },
        }

        # --- Node 4: CLIPTextEncode (positive prompt) ---
        workflow["4"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": video_prompt,
                "clip": ["1", 1],  # CLIP from CheckpointLoaderSimple
            },
        }

        # --- Node 5: CLIPTextEncode (negative prompt) ---
        workflow["5"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "blurry, distorted, low quality, static, frozen",
                "clip": ["1", 1],  # CLIP from CheckpointLoaderSimple
            },
        }

        # --- Node 6: LTXVConditioning (combine pos/neg + frame rate) ---
        workflow["6"] = {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["4", 0],  # CONDITIONING from positive CLIPTextEncode
                "negative": ["5", 0],  # CONDITIONING from negative CLIPTextEncode
                "frame_rate": float(fps),
            },
        }

        # --- Node 7: EmptyLTXVLatentVideo (initial latent) ---
        workflow["7"] = {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {
                "width": w,
                "height": h,
                "length": frames,
                "batch_size": 1,
            },
        }

        # --- Node 8: LTXVAddGuide (start frame at frame_idx=0) ---
        workflow["8"] = {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["6", 0],   # positive from LTXVConditioning
                "negative": ["6", 1],   # negative from LTXVConditioning
                "vae": ["1", 2],        # VAE from CheckpointLoaderSimple
                "latent": ["7", 0],     # LATENT from EmptyLTXVLatentVideo
                "image": ["2", 0],      # IMAGE from LoadImage (start frame)
                "frame_idx": 0,
                "strength": self.start_frame_strength,
            },
        }

        # --- Node 9: LTXVAddGuide (end frame at frame_idx=-1) ---
        workflow["9"] = {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["8", 0],   # positive from first LTXVAddGuide
                "negative": ["8", 1],   # negative from first LTXVAddGuide
                "vae": ["1", 2],        # VAE from CheckpointLoaderSimple
                "latent": ["8", 2],     # latent from first LTXVAddGuide
                "image": ["3", 0],      # IMAGE from LoadImage (end frame)
                "frame_idx": -1,
                "strength": self.end_frame_strength,
            },
        }

        # --- Node 10: LTXVApplySTG (apply STG to model) ---
        workflow["10"] = {
            "class_type": "LTXVApplySTG",
            "inputs": {
                "model": ["1", 0],  # MODEL from CheckpointLoaderSimple
                "block_indices": self.stg_block_indices,
            },
        }

        # --- Node 11: STGGuiderAdvanced (advanced guider with sigma schedule) ---
        workflow["11"] = {
            "class_type": "STGGuiderAdvanced",
            "inputs": {
                "model": ["10", 0],     # model from LTXVApplySTG
                "positive": ["9", 0],   # positive from second LTXVAddGuide
                "negative": ["9", 1],   # negative from second LTXVAddGuide
                "skip_steps_sigma_threshold": settings.LTX23_STG_SKIP_STEPS_SIGMA_THRESHOLD,
                "cfg_star_rescale": settings.LTX23_STG_CFG_STAR_RESCALE,
                "sigmas": self.sigmas,
                "cfg_values": self.cfg_values,
                "stg_scale_values": self.stg_scale_values,
                "stg_rescale_values": self.stg_rescale_values,
                "stg_layers_indices": self.stg_layers_indices,
            },
        }

        # --- Node 12: LTXVScheduler (frame-aware sigma schedule) ---
        workflow["12"] = {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": self.steps,
                "max_shift": settings.LTX23_SCHEDULER_MAX_SHIFT,
                "base_shift": settings.LTX23_SCHEDULER_BASE_SHIFT,
                "stretch": settings.LTX23_SCHEDULER_STRETCH,
                "terminal": settings.LTX23_SCHEDULER_TERMINAL,
                "latent": ["9", 2],  # latent from second LTXVAddGuide
            },
        }

        # --- Node 13: KSamplerSelect (sampler algorithm) ---
        workflow["13"] = {
            "class_type": "KSamplerSelect",
            "inputs": {
                "sampler_name": "euler",
            },
        }

        # --- Node 14: RandomNoise (noise seed) ---
        workflow["14"] = {
            "class_type": "RandomNoise",
            "inputs": {
                "noise_seed": seed,
            },
        }

        # --- Node 15: SamplerCustomAdvanced (run the sampling) ---
        workflow["15"] = {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["14", 0],         # NOISE from RandomNoise
                "guider": ["11", 0],        # GUIDER from STGGuiderAdvanced
                "sampler": ["13", 0],       # SAMPLER from KSamplerSelect
                "sigmas": ["12", 0],        # SIGMAS from LTXVScheduler
                "latent_image": ["9", 2],   # LATENT from second LTXVAddGuide
            },
        }

        # --- Node 16: LTXVSpatioTemporalTiledVAEDecode (decode latent to images) ---
        workflow["16"] = {
            "class_type": "LTXVSpatioTemporalTiledVAEDecode",
            "inputs": {
                "vae": ["1", 2],            # VAE from CheckpointLoaderSimple
                "latents": ["15", 1],       # denoised_output from SamplerCustomAdvanced
                "spatial_tiles": settings.LTX23_VAE_SPATIAL_TILES,
                "spatial_overlap": settings.LTX23_VAE_SPATIAL_OVERLAP,
                "temporal_tile_length": settings.LTX23_VAE_TEMPORAL_TILE_LENGTH,
                "temporal_overlap": settings.LTX23_VAE_TEMPORAL_OVERLAP,
                "last_frame_fix": False,
                "working_device": "auto",
                "working_dtype": "auto",
            },
        }

        # --- Node 17: SaveWEBM (output video file) ---
        workflow["17"] = {
            "class_type": "SaveWEBM",
            "inputs": {
                "images": ["16", 0],    # IMAGE from VAE decode
                "filename_prefix": "ltx23",
                "codec": settings.LTX23_OUTPUT_CODEC,
                "fps": float(fps),
                "crf": settings.LTX23_OUTPUT_CRF,
            },
        }

        return workflow

    # ------------------------------------------------------------------
    # Public generation method
    # ------------------------------------------------------------------

    async def generate_clip(
        self,
        scene_number: int,
        start_frame_path: str,
        end_frame_path: str,
        video_prompt: str,
        dialogue: str | None = None,
        audio_description: str | None = None,
        seed: int | None = None,
    ) -> LTXVideoClip:
        """Generate a 5-second video clip from start and end frame images.

        Args:
            scene_number: Scene number (1-24).
            start_frame_path: Local path to the start frame image.
            end_frame_path: Local path to the end frame image.
            video_prompt: Text prompt describing camera movement and action.
            dialogue: Optional dialogue (for future audio sync).
            audio_description: Optional audio description (for future audio).
            seed: Optional seed for reproducibility. -1 or None = random.

        Returns:
            LTXVideoClip with path to generated video and metadata.
        """
        logger.info(f"Scene {scene_number}: Starting LTX 2.3 video generation")

        # Determine seed
        if seed is None or seed == -1:
            actual_seed = random.randint(0, 2**32 - 1)
        else:
            actual_seed = seed

        # Build prompt with style preservation note
        full_prompt = (
            f"{video_prompt} "
            "Maintain caricature art style throughout, subtle animation only."
        )

        start_time = time.time()

        # Upload both frames to ComfyUI
        start_filename = f"ltx23_scene{scene_number:02d}_start.png"
        end_filename = f"ltx23_scene{scene_number:02d}_end.png"

        logger.info(f"Scene {scene_number}: Uploading start frame...")
        start_stored = await self.client.upload_image(
            start_frame_path, start_filename
        )

        logger.info(f"Scene {scene_number}: Uploading end frame...")
        end_stored = await self.client.upload_image(
            end_frame_path, end_filename
        )

        # Build and queue workflow
        workflow = self._build_workflow(
            start_frame_filename=start_stored,
            end_frame_filename=end_stored,
            video_prompt=full_prompt,
            seed=actual_seed,
        )

        prompt_id = await self.client.queue_prompt(workflow)
        logger.info(f"Scene {scene_number}: ComfyUI prompt queued: {prompt_id}")

        # Poll for completion
        outputs = await self.client.poll_for_completion(
            prompt_id,
            timeout=float(settings.COMFYUI_TIMEOUT_SECONDS),
        )

        # Find the video output
        video_bytes = await self._extract_video_output(outputs, scene_number)

        # Save to local file
        output_path = (
            self.output_dir / f"ltx23_scene_{scene_number:02d}_{actual_seed}.webm"
        )
        output_path.write_bytes(video_bytes)

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Scene {scene_number}: LTX 2.3 video generated in {elapsed_ms}ms "
            f"(seed={actual_seed}, {len(video_bytes)} bytes)"
        )

        return LTXVideoClip(
            scene_number=scene_number,
            video_path=str(output_path),
            generation_time_ms=elapsed_ms,
            prompt_used=full_prompt,
            seed_used=actual_seed,
        )

    # ------------------------------------------------------------------
    # Output extraction
    # ------------------------------------------------------------------

    async def _extract_video_output(
        self,
        outputs: dict[str, Any],
        scene_number: int,
    ) -> bytes:
        """Extract video bytes from ComfyUI workflow outputs.

        Tries node "17" (SaveWEBM) first, then falls back to searching
        all nodes for video/image output.
        """
        # Try the expected output node (SaveWEBM at node 17)
        video_node = outputs.get("17")
        if video_node:
            # SaveWEBM outputs in "videos" key
            videos = video_node.get("videos", [])
            if videos:
                info = videos[0]
                return await self.client.download_file(
                    filename=info["filename"],
                    subfolder=info.get("subfolder", ""),
                    file_type=info.get("type", "output"),
                )

            # Some output nodes use "images" key for video frames
            images = video_node.get("images", [])
            if images:
                info = images[0]
                return await self.client.download_file(
                    filename=info["filename"],
                    subfolder=info.get("subfolder", ""),
                    file_type=info.get("type", "output"),
                )

            # Also check "gifs" key (VHS compat)
            gifs = video_node.get("gifs", [])
            if gifs:
                info = gifs[0]
                return await self.client.download_file(
                    filename=info["filename"],
                    subfolder=info.get("subfolder", ""),
                    file_type=info.get("type", "output"),
                )

        # Fallback: search all output nodes for video content
        for node_id, node_output in outputs.items():
            for key in ("videos", "gifs", "images"):
                items = node_output.get(key, [])
                if items:
                    info = items[0]
                    # For images key, only accept video-like formats
                    if key == "images" and not any(
                        info.get("filename", "").endswith(ext)
                        for ext in (".webm", ".webp", ".gif", ".mp4")
                    ):
                        continue
                    return await self.client.download_file(
                        filename=info["filename"],
                        subfolder=info.get("subfolder", ""),
                        file_type=info.get("type", "output"),
                    )

        raise LTXVideoGenerationError(
            f"Scene {scene_number}: No video output found in ComfyUI response. "
            f"Output keys: {list(outputs.keys())}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the ComfyUI client."""
        await self.client.close()
