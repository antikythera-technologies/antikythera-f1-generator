"""Image generation service using ComfyUI API on RunPod.

Implements character consistency through:
1. ANTKF1STYLE LoRA — fine-tuned Flux Dev model for our satirical caricature look
2. PuLID face conditioning — injects facial identity from a reference headshot
3. Character traits from database — physical features, comedy angle, pose, expression
4. Team-specific styling — suit colors, background gradients per F1 team
5. Prompt saving — every generated prompt is saved to DB for reproducibility

ComfyUI workflow chain:
  UNETLoader → LoraLoader → (optional) ApplyPulidFlux → KSampler → VAEDecode → SaveImage
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image as PILImage

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 2026 F1 team visual mapping
# ---------------------------------------------------------------------------
TEAM_COLORS: dict[str, dict[str, str]] = {
    "red_bull_racing": {
        "suit": "dark blue Red Bull Racing suit with Oracle and Bybit logos",
        "background": "dark navy blue to midnight blue gradient",
    },
    "racing_bulls": {
        "suit": "white Racing Bulls suit with blue and Ford accents",
        "background": "white to steel blue gradient",
    },
    "mclaren": {
        "suit": "papaya orange and black McLaren suit with OKX logos",
        "background": "papaya orange to black gradient",
    },
    "ferrari": {
        "suit": "red Ferrari suit with white accents and HP logos",
        "background": "deep red to dark crimson gradient",
    },
    "mercedes": {
        "suit": "black Mercedes-AMG Petronas suit with Petronas teal accents",
        "background": "dark teal to black gradient",
    },
    "aston_martin": {
        "suit": "British racing green Aston Martin suit",
        "background": "dark British racing green gradient",
    },
    "williams": {
        "suit": "blue Williams Racing suit with Barclays lighter blue accents",
        "background": "dark blue to navy gradient",
    },
    "haas": {
        "suit": "black and white TGR Haas suit with Toyota red accents",
        "background": "black to dark grey gradient with red accent",
    },
    "alpine": {
        "suit": "blue Alpine suit with BWT pink accents",
        "background": "dark blue to pink gradient",
    },
    "audi": {
        "suit": "silver and black Audi suit with red accents",
        "background": "silver to black gradient",
    },
    "cadillac": {
        "suit": "white and black Cadillac suit with chrome details",
        "background": "black to dark grey gradient with chrome highlights",
    },
}

# Fallback for pundits / characters without a team
PUNDIT_STYLE = {
    "suit": "smart dark suit with Sky Sports / F1 branding",
    "background": "warm burnt-orange to dark amber gradient",
}


@dataclass
class GeneratedImage:
    """Result of image generation."""

    image_path: str
    generation_time_ms: int
    prompt_used: str


class ImageGenerationError(Exception):
    """Raised when image generation fails."""

    pass


# ---------------------------------------------------------------------------
# ComfyUI workflow builders
# ---------------------------------------------------------------------------

def _build_workflow(
    prompt_text: str,
    negative_prompt: str = "",
    face_image: str | None = None,
    width: int = 768,
    height: int = 1344,
    steps: int = 20,
    cfg: float = 1.0,
    seed: int | None = None,
    lora_strength: float | None = None,
    pulid_weight: float | None = None,
) -> dict[str, Any]:
    """Build a ComfyUI API workflow dict.

    Matches the proven workflow from ``scripts/generate_all_characters.py``.
    When *face_image* is provided the full LoRA + PuLID chain is used.
    When it is ``None`` the PuLID / InsightFace / EvaClip / LoadImage nodes
    are omitted and the LoRA output connects directly to the KSampler.
    """
    lora_str = lora_strength if lora_strength is not None else settings.COMFYUI_LORA_STRENGTH
    pulid_w = pulid_weight if pulid_weight is not None else settings.COMFYUI_PULID_WEIGHT

    if seed is None:
        import random
        seed = random.randint(0, 2**32 - 1)

    workflow: dict[str, Any] = {}

    # --- 1  UNET loader (Flux Dev fp8) ---
    workflow["1"] = {
        "class_type": "UNETLoader",
        "inputs": {
            "unet_name": "flux1-dev-fp8.safetensors",
            "weight_dtype": "fp8_e4m3fn",
        },
    }

    # --- 5  Dual CLIP loader (clip_l + t5xxl) ---
    workflow["5"] = {
        "class_type": "DualCLIPLoader",
        "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
            "type": "flux",
        },
    }

    # --- 2  LoRA loader ---
    workflow["2"] = {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["1", 0],
            "clip": ["5", 0],
            "lora_name": "antkf1style_v1.safetensors",
            "strength_model": lora_str,
            "strength_clip": lora_str,
        },
    }

    # --- 6  CLIP Text Encode (positive prompt) ---
    # Uses DualCLIPLoader output directly (not LoRA-modified clip)
    workflow["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": prompt_text,
            "clip": ["5", 0],
        },
    }

    # --- 7  CLIP Text Encode (negative prompt / conditioning) ---
    workflow["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": negative_prompt,
            "clip": ["5", 0],
        },
    }

    # --- 8  Empty SD3 latent image (required for Flux) ---
    workflow["8"] = {
        "class_type": "EmptySD3LatentImage",
        "inputs": {
            "width": width,
            "height": height,
            "batch_size": 1,
        },
    }

    # --- 9  VAE loader ---
    workflow["9"] = {
        "class_type": "VAELoader",
        "inputs": {
            "vae_name": "ae.safetensors",
        },
    }

    # Determine model input to KSampler — either PuLID output or LoRA output
    if face_image:
        # --- 10  PuLID model loader ---
        workflow["10"] = {
            "class_type": "PulidFluxModelLoader",
            "inputs": {
                "pulid_file": "pulid_flux_v0.9.0.safetensors",
            },
        }

        # --- 11  InsightFace loader (provides face_analysis) ---
        workflow["11"] = {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {
                "provider": "CUDA",
            },
        }

        # --- 12  EvaClip loader (provides eva_clip) ---
        workflow["12"] = {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        }

        # --- 13  Load face reference image ---
        workflow["13"] = {
            "class_type": "LoadImage",
            "inputs": {
                "image": face_image,
            },
        }

        # --- 14  Apply PuLID ---
        workflow["14"] = {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "model": ["2", 0],         # model from LoRA loader
                "pulid_flux": ["10", 0],    # PuLID model
                "eva_clip": ["12", 0],      # EvaClip loader
                "face_analysis": ["11", 0], # InsightFace loader
                "image": ["13", 0],         # loaded face image
                "weight": pulid_w,
                "start_at": 0.0,
                "end_at": 1.0,
            },
        }

        model_source = ["14", 0]  # PuLID output
    else:
        model_source = ["2", 0]  # LoRA output (no PuLID)

    # --- 20  KSampler ---
    workflow["20"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_source,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["8", 0],
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
        },
    }

    # --- 21  VAE Decode ---
    workflow["21"] = {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["20", 0],
            "vae": ["9", 0],
        },
    }

    # --- 22  Save Image ---
    workflow["22"] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": ["21", 0],
            "filename_prefix": "antkf1",
        },
    }

    return workflow


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class ImageGenerator:
    """Service for generating consistent character images via ComfyUI on RunPod."""

    # Polling parameters for ComfyUI prompt execution
    POLL_INTERVAL_S = 2.0
    POLL_TIMEOUT_S = 300.0

    def __init__(self):
        self.comfyui_url = settings.COMFYUI_URL.rstrip("/")
        self.output_dir = Path("/tmp/f1-images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._http_client: httpx.AsyncClient | None = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def build_character_prompt(
        self,
        character_name: str,
        display_name: str,
        role: str | None = None,
        team: str | None = None,
        nationality: str | None = None,
        physical_features: str | None = None,
        comedy_angle: str | None = None,
        signature_expression: str | None = None,
        signature_pose: str | None = None,
        props: str | None = None,
        background_type: str | None = None,
        background_detail: str | None = None,
        clothing_description: str | None = None,
        action_description: str | None = None,
    ) -> str:
        """Build a complete generation prompt from character traits.

        Combines the ANTKF1STYLE trigger word with character-specific traits
        loaded from the database. The resulting prompt is deterministic
        and reproducible.
        """
        # Resolve team-specific visuals
        team_slug = (team or "").lower().replace(" ", "_")
        team_style = TEAM_COLORS.get(team_slug, PUNDIT_STYLE)

        # Identity line
        nat_str = f"{nationality} " if nationality else ""
        role_str = role or "personality"
        parts = [
            f"ANTKF1STYLE satirical caricature portrait of a {nat_str}{role_str}"
            f" resembling F1's {display_name}."
        ]

        # Physical description
        if physical_features:
            parts.append(physical_features)

        # Expression
        if signature_expression:
            parts.append(signature_expression)
        elif comedy_angle:
            parts.append(comedy_angle)

        # Scene action (for episode scenes, overrides static pose)
        if action_description:
            parts.append(action_description)
        elif signature_pose:
            parts.append(signature_pose)

        # Clothing — prefer explicit description, fall back to team suit
        if clothing_description:
            parts.append(f"Wearing {clothing_description}.")
        else:
            parts.append(f"Wearing {team_style['suit']}.")

        # Background
        if background_detail:
            parts.append(f"{background_detail} background.")
        else:
            parts.append(f"{team_style['background']} background.")

        # Core style instructions
        parts.append(
            "Oversized head, exaggerated facial features, photorealistic skin with visible pores and wrinkles. "
            "One eye wider than the other, asymmetric expression. "
            "Head and shoulders portrait crop only. "
            "Dramatic warm side lighting with deep shadows."
        )

        return " ".join(parts)

    # ------------------------------------------------------------------
    # ComfyUI API interaction
    # ------------------------------------------------------------------

    async def upload_face_to_comfyui(self, local_path: str, filename: str) -> str:
        """Upload a face reference image to ComfyUI's input directory.

        Uses the ``POST /upload/image`` endpoint.  Returns the filename
        as stored by ComfyUI (used in the ``LoadImage`` node).
        """
        url = f"{self.comfyui_url}/upload/image"

        with open(local_path, "rb") as f:
            files = {"image": (filename, f, "image/jpeg")}
            data = {"overwrite": "true"}
            response = await self.http_client.post(url, files=files, data=data)

        if response.status_code != 200:
            raise ImageGenerationError(
                f"ComfyUI /upload/image returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        result = response.json()
        stored_name = result.get("name", filename)
        logger.info(f"Uploaded face reference to ComfyUI: {stored_name}")
        return stored_name

    async def ensure_face_reference(self, character_name: str) -> str | None:
        """Ensure a character's face reference is available in ComfyUI.

        1. Checks if it already exists in ComfyUI's input dir.
        2. If not, downloads from MinIO and uploads to ComfyUI.

        Returns the filename in ComfyUI, or None if no face reference exists.
        """
        from app.services.storage import StorageService

        # Check if already in ComfyUI
        for ext in ("jpg", "jpeg", "png", "webp"):
            filename = f"{character_name}.{ext}"
            try:
                resp = await self.http_client.get(
                    f"{self.comfyui_url}/view",
                    params={"filename": filename, "type": "input"},
                )
                if resp.status_code == 200:
                    logger.debug(f"Face reference already in ComfyUI: {filename}")
                    return filename
            except Exception:
                continue

        # Not in ComfyUI — try downloading from MinIO
        storage = StorageService()
        local_path = await storage.download_face_reference(character_name)
        if not local_path:
            return None

        # Upload to ComfyUI
        filename = Path(local_path).name
        return await self.upload_face_to_comfyui(local_path, filename)

    async def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        """POST workflow to ComfyUI /prompt and return the prompt_id."""
        url = f"{self.comfyui_url}/prompt"
        payload = {"prompt": workflow}

        response = await self.http_client.post(url, json=payload)

        if response.status_code != 200:
            detail = response.text[:500]
            raise ImageGenerationError(
                f"ComfyUI /prompt returned HTTP {response.status_code}: {detail}"
            )

        data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ImageGenerationError(
                f"ComfyUI /prompt response missing prompt_id: {data}"
            )

        return prompt_id

    async def _poll_for_completion(self, prompt_id: str) -> dict[str, Any]:
        """Poll GET /history/{prompt_id} until the job finishes or times out."""
        url = f"{self.comfyui_url}/history/{prompt_id}"
        deadline = time.time() + self.POLL_TIMEOUT_S

        while time.time() < deadline:
            response = await self.http_client.get(url)
            if response.status_code != 200:
                logger.warning(
                    f"ComfyUI /history returned {response.status_code}, retrying..."
                )
                await asyncio.sleep(self.POLL_INTERVAL_S)
                continue

            data = response.json()
            if prompt_id in data:
                history = data[prompt_id]
                # Check for execution error
                status_info = history.get("status", {})
                if status_info.get("status_str") == "error":
                    messages = status_info.get("messages", [])
                    raise ImageGenerationError(
                        f"ComfyUI execution error: {messages}"
                    )
                outputs = history.get("outputs")
                if outputs:
                    return outputs

            await asyncio.sleep(self.POLL_INTERVAL_S)

        raise ImageGenerationError(
            f"ComfyUI prompt {prompt_id} timed out after {self.POLL_TIMEOUT_S}s"
        )

    async def _download_image(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """Download a generated image from ComfyUI via GET /view."""
        url = f"{self.comfyui_url}/view"
        params = {
            "filename": filename,
            "type": image_type,
        }
        if subfolder:
            params["subfolder"] = subfolder

        response = await self.http_client.get(url, params=params)
        if response.status_code != 200:
            raise ImageGenerationError(
                f"ComfyUI /view returned HTTP {response.status_code} for {filename}"
            )

        return response.content

    async def _generate_via_comfyui(
        self,
        prompt_text: str,
        face_image: str | None = None,
        width: int = 768,
        height: int = 1344,
        seed: int | None = None,
    ) -> bytes:
        """Build workflow, queue it, poll for completion, download the result.

        Args:
            prompt_text: The positive text prompt.
            face_image: Filename of a face reference in ComfyUI's input dir.
                        If None, PuLID nodes are skipped (LoRA-only workflow).
            width: Output image width.
            height: Output image height.
            seed: Optional fixed seed for reproducibility.

        Returns:
            Raw PNG image bytes.
        """
        workflow = _build_workflow(
            prompt_text=prompt_text,
            face_image=face_image,
            width=width,
            height=height,
            seed=seed,
        )

        prompt_id = await self._queue_prompt(workflow)
        logger.info(f"ComfyUI prompt queued: {prompt_id}")

        outputs = await self._poll_for_completion(prompt_id)

        # Find the SaveImage node output (node "22")
        save_node = outputs.get("22")
        if not save_node:
            # Fall back to first node that has images
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    save_node = node_output
                    break

        if not save_node or "images" not in save_node:
            raise ImageGenerationError(
                f"ComfyUI output has no images. Output keys: {list(outputs.keys())}"
            )

        image_info = save_node["images"][0]
        image_bytes = await self._download_image(
            filename=image_info["filename"],
            subfolder=image_info.get("subfolder", ""),
            image_type=image_info.get("type", "output"),
        )

        return image_bytes

    # ------------------------------------------------------------------
    # Public generation methods
    # ------------------------------------------------------------------

    async def generate_character_image(
        self,
        character_name: str,
        prompt: str,
        style_reference_paths: list[str] | None = None,
        output_filename: str | None = None,
        face_image: str | None = None,
    ) -> GeneratedImage:
        """Generate a character image using ComfyUI (Flux + LoRA + PuLID).

        Args:
            character_name: Character key for file naming.
            prompt: Full assembled prompt (from build_character_prompt).
            style_reference_paths: Accepted for API compatibility; not used
                by ComfyUI workflow (style comes from LoRA).
            output_filename: Optional custom filename for the output.
            face_image: Filename of face reference in ComfyUI's input dir.
                        When provided, PuLID is used for facial identity.
                        When None, LoRA-only workflow is used.

        Returns:
            GeneratedImage with path and metadata.
        """
        logger.info(f"Generating caricature for {character_name} via ComfyUI")

        if style_reference_paths:
            logger.info(
                f"Note: {len(style_reference_paths)} style reference paths provided "
                f"but ComfyUI workflow uses LoRA for style; paths ignored"
            )

        # Build output path
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if output_filename:
            filename = output_filename
        else:
            char_key = character_name.lower().replace(" ", "_")
            filename = f"caricature_{char_key}_{timestamp}.png"
        output_path = self.output_dir / filename

        start_time = time.time()

        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                image_bytes = await self._generate_via_comfyui(
                    prompt_text=prompt,
                    face_image=face_image,
                )

                # Save the image, converting to RGB PNG
                image = PILImage.open(BytesIO(image_bytes))
                if image.mode == "RGBA":
                    rgb_image = PILImage.new("RGB", image.size, (255, 255, 255))
                    rgb_image.paste(image, mask=image.split()[3])
                    rgb_image.save(str(output_path), "PNG")
                elif image.mode == "RGB":
                    image.save(str(output_path), "PNG")
                else:
                    image.convert("RGB").save(str(output_path), "PNG")

                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    f"Generated {character_name} in {elapsed_ms}ms -> {output_path} "
                    f"({len(image_bytes)} bytes, face={'yes' if face_image else 'no'})"
                )

                return GeneratedImage(
                    image_path=str(output_path),
                    generation_time_ms=elapsed_ms,
                    prompt_used=prompt,
                )

            except ImageGenerationError as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} for {character_name} "
                        f"failed ({e}), retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} for {character_name} "
                        f"failed ({type(e).__name__}: {e}), retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                break

        logger.error(f"Image generation failed for {character_name}: {last_error}")
        raise ImageGenerationError(f"Failed to generate {character_name}: {last_error}")

    async def generate_scene_image(
        self,
        scene_number: int,
        episode_id: int,
        character_name: str,
        action_description: str,
        reference_image_path: Optional[str] = None,
        style_reference_paths: list[str] | None = None,
        character_traits: dict | None = None,
        resolution: str = "1K",
        face_image: str | None = None,
    ) -> GeneratedImage:
        """Generate a scene image with character consistency.

        This is the scene-level generation used during the episode pipeline.
        It combines character traits from DB with the action description.

        Args:
            scene_number: Scene number (1-24).
            episode_id: Episode ID for file naming.
            character_name: Character key.
            action_description: What the character is doing in this scene.
            reference_image_path: Accepted for API compatibility (not used).
            style_reference_paths: Accepted for API compatibility (not used).
            character_traits: Dict of character trait fields from DB.
            resolution: Output resolution (accepted for compatibility).
            face_image: Filename of face reference in ComfyUI's input dir.

        Returns:
            GeneratedImage with path and metadata.
        """
        logger.info(f"Scene {scene_number}: Generating image for {character_name}")

        # Build prompt from character traits if available
        traits = character_traits or {}
        prompt = self.build_character_prompt(
            character_name=character_name,
            display_name=traits.get("display_name", character_name),
            role=traits.get("role"),
            team=traits.get("team"),
            nationality=traits.get("nationality"),
            physical_features=traits.get("physical_features"),
            comedy_angle=traits.get("comedy_angle"),
            signature_expression=traits.get("signature_expression"),
            signature_pose=None,  # Scene has its own action
            props=traits.get("props"),
            background_type=traits.get("background_type"),
            background_detail=traits.get("background_detail"),
            clothing_description=traits.get("clothing_description"),
            action_description=action_description,
        )

        logger.debug(f"Scene {scene_number}: Prompt: {prompt[:200]}...")

        # Output filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"episode_{episode_id}_scene_{scene_number:02d}_{timestamp}.png"

        return await self.generate_character_image(
            character_name=character_name,
            prompt=prompt,
            style_reference_paths=style_reference_paths,
            output_filename=filename,
            face_image=face_image,
        )

    async def generate_character_reference(
        self,
        character_name: str,
        character_traits: dict | None = None,
        style_reference_paths: list[str] | None = None,
        resolution: str = "2K",
        face_image: str | None = None,
    ) -> GeneratedImage:
        """Generate a canonical reference image for a character.

        Uses the full character traits from DB to create the definitive
        caricature of this character. The prompt is saved to the
        character's caricature_prompt field for reproducibility.

        Args:
            character_name: Character key.
            character_traits: Dict of character trait fields.
            style_reference_paths: Accepted for API compatibility (not used).
            resolution: Accepted for compatibility.
            face_image: Filename of face reference in ComfyUI's input dir.

        Returns:
            GeneratedImage with path and metadata.
        """
        logger.info(f"Generating reference caricature for {character_name}")

        traits = character_traits or {}
        prompt = self.build_character_prompt(
            character_name=character_name,
            display_name=traits.get("display_name", character_name),
            role=traits.get("role"),
            team=traits.get("team"),
            nationality=traits.get("nationality"),
            physical_features=traits.get("physical_features"),
            comedy_angle=traits.get("comedy_angle"),
            signature_expression=traits.get("signature_expression"),
            signature_pose=traits.get("signature_pose"),
            props=traits.get("props"),
            background_type=traits.get("background_type"),
            background_detail=traits.get("background_detail"),
            clothing_description=traits.get("clothing_description"),
        )

        return await self.generate_character_image(
            character_name=character_name,
            prompt=prompt,
            style_reference_paths=style_reference_paths,
            face_image=face_image,
        )
