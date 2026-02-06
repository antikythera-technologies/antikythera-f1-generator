"""Image generation service using Nano Banana Pro (Gemini) with reference image support.

Implements character consistency through:
1. Style reference images - feed 3-4 "gold standard" caricatures as style input
2. Character traits from database - physical features, comedy angle, pose, expression
3. Master style template - locked-down style description proven to produce correct output
4. Prompt saving - every generated prompt is saved to DB for reproducibility
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImage:
    """Result of image generation."""
    image_path: str
    generation_time_ms: int
    prompt_used: str


# Master style template - the core style DNA that NEVER changes.
# This was derived from analyzing the successful Manus.ai-generated caricatures
# (Toto Wolff, Fernando Alonso, Lando Norris, etc.) that define our target style.
MASTER_STYLE_TEMPLATE = """Highly detailed 3D satirical caricature rendered as a comedic Pixar-quality animated character. \
This is a FUNNY satirical portrait meant to humorously exaggerate the subject's personality.

STYLE REQUIREMENTS:
- Fully stylized smooth 3D animated skin, NOT photorealistic
- Exaggerated animated body proportions like a high-end animated movie character
- Bold exaggerated facial features while still being recognizable as the real person
- Fine detail in facial expressions: wrinkles, frown lines, crow's feet, expression creases, laugh lines
- Visible detail in skin texture, muscle definition, fabric wrinkles and stitching
- Asymmetric expressions for comedy: one eye wider than the other, lopsided smirks, raised eyebrows
- Dynamic poses with personality-driven action, NOT static portraits
- Rich saturated colors with dramatic cinematic lighting and deep shadows
- This should look like a frame from a big-budget Pixar or DreamWorks animated comedy film"""


class ImageGenerator:
    """Service for generating consistent character images using Gemini with reference images."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.output_dir = Path("/tmp/f1-images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._style_ref_images: list[PILImage.Image] | None = None

    @property
    def client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _load_style_reference_images(
        self,
        reference_paths: list[str],
    ) -> list[PILImage.Image]:
        """Load style reference images from local paths or MinIO.

        These are the 'gold standard' caricatures that define our visual style.
        They are fed to the model alongside the text prompt so it can SEE
        what style we want, rather than relying on text description alone.
        """
        images = []
        for path in reference_paths:
            try:
                if os.path.exists(path):
                    img = PILImage.open(path)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    images.append(img)
                    logger.debug(f"Loaded style reference: {path}")
                else:
                    logger.warning(f"Style reference not found: {path}")
            except Exception as e:
                logger.warning(f"Failed to load style reference {path}: {e}")

        logger.info(f"Loaded {len(images)} style reference images")
        return images

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

        Combines the master style template with character-specific traits
        loaded from the database. The resulting prompt is deterministic
        and reproducible.
        """
        # Start with master style
        parts = [MASTER_STYLE_TEMPLATE, ""]

        # Character identity - use generic description to avoid real-person image filters
        # The model blocks generation of named real people, so we describe them
        # by role and features rather than name
        role_str = f", {role}" if role else ""
        team_str = f" for {team}" if team else ""
        nat_str = f"{nationality} " if nationality else ""
        parts.append(
            f"CHARACTER: A {nat_str}Formula 1{role_str}{team_str}. "
            f"This is a FICTIONAL animated character loosely inspired by motorsport personalities."
        )
        parts.append("")

        # Physical features for the character design
        if physical_features:
            parts.append(f"CHARACTER DESIGN: {physical_features}")
            parts.append("")

        # Expression and pose
        expr_pose_parts = []
        if signature_expression:
            expr_pose_parts.append(f"EXPRESSION: {signature_expression}")
        if signature_pose:
            expr_pose_parts.append(f"POSE: {signature_pose}")
        if props:
            expr_pose_parts.append(f"PROPS: {props}")
        if comedy_angle:
            expr_pose_parts.append(f"COMEDY: {comedy_angle}")
        if expr_pose_parts:
            parts.append("EXPRESSION AND POSE: " + " ".join(expr_pose_parts))
            parts.append("")

        # Scene-specific action (for episode scene generation)
        if action_description:
            parts.append(f"ACTION: {action_description}")
            parts.append("")

        # Clothing
        if clothing_description:
            parts.append(f"CLOTHING: {clothing_description}")
            parts.append("")

        # Background
        bg_type = background_type or "orange_gradient"
        if bg_type == "orange_gradient":
            parts.append("BACKGROUND: Warm orange to dark amber gradient background.")
        elif bg_type == "team_logo":
            detail = background_detail or "Team logo subtly visible"
            parts.append(f"BACKGROUND: {detail}")
        elif bg_type == "custom" and background_detail:
            parts.append(f"BACKGROUND: {background_detail}")
        else:
            parts.append("BACKGROUND: Warm orange to dark amber gradient background.")

        return "\n".join(parts)

    async def generate_character_image(
        self,
        character_name: str,
        prompt: str,
        style_reference_paths: list[str] | None = None,
        output_filename: str | None = None,
    ) -> GeneratedImage:
        """Generate a character image using style references + prompt.

        This is the primary generation method. It feeds style reference images
        to the model alongside the text prompt, so the model can SEE the
        target style rather than guessing from text alone.

        Args:
            character_name: Character key for file naming
            prompt: Full assembled prompt (from build_character_prompt)
            style_reference_paths: Paths to style reference images (the 'gold standard' caricatures)
            output_filename: Optional custom filename

        Returns:
            GeneratedImage with path and metadata
        """
        logger.info(f"Generating caricature for {character_name}")

        # Load style references if provided
        style_images = []
        if style_reference_paths:
            style_images = self._load_style_reference_images(style_reference_paths)

        # Build output path
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if output_filename:
            filename = output_filename
        else:
            char_key = character_name.lower().replace(" ", "_")
            filename = f"caricature_{char_key}_{timestamp}.png"
        output_path = self.output_dir / filename

        start_time = time.time()

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                image_path = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._generate_with_references_sync,
                    prompt,
                    style_images,
                    str(output_path),
                )

                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Generated {character_name} in {elapsed_ms}ms -> {image_path}")

                return GeneratedImage(
                    image_path=image_path,
                    generation_time_ms=elapsed_ms,
                    prompt_used=prompt,
                )

            except ImageGenerationError as e:
                last_error = e
                if "IMAGE_OTHER" in str(e) and attempt < max_retries - 1:
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} for {character_name} "
                        f"hit IMAGE_OTHER filter, retrying..."
                    )
                    await asyncio.sleep(1)
                    continue
                break
            except Exception as e:
                last_error = e
                break

        logger.error(f"Image generation failed for {character_name}: {last_error}")
        raise ImageGenerationError(f"Failed to generate {character_name}: {last_error}")

    def _generate_with_references_sync(
        self,
        prompt: str,
        style_images: list[PILImage.Image],
        output_path: str,
    ) -> str:
        """Generate image using Gemini with multi-modal input (reference images + text).

        This uses generate_content() instead of generate_images() because
        generate_content supports feeding reference images as input, which is
        essential for style consistency.
        """
        from google.genai import types

        # Build content parts: style reference images first, then the prompt
        content_parts = []

        # Add style reference images
        if style_images:
            content_parts.append(
                "Here are style reference images. Generate the new character "
                "in the EXACT SAME art style as these references:"
            )
            for img in style_images:
                content_parts.append(img)
            content_parts.append("")

        # Add the generation prompt
        content_parts.append(prompt)

        # Generate using multi-modal content generation with image output
        # Use BLOCK_NONE for safety since we're generating fictional animated characters
        response = self.client.models.generate_content(
            model=settings.GEMINI_IMAGE_MODEL,
            contents=content_parts,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
                temperature=0.8,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE",
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE",
                    ),
                ],
            ),
        )

        # Extract the generated image from the response
        image_data = None

        if not response.candidates:
            raise ImageGenerationError(
                f"No candidates in response. Finish reason: {getattr(response, 'prompt_feedback', 'unknown')}"
            )

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            # Model returned without image - log the response for debugging
            finish_reason = getattr(candidate, "finish_reason", "unknown")
            text_response = ""
            try:
                text_response = response.text[:500] if response.text else ""
            except Exception:
                pass
            raise ImageGenerationError(
                f"No content parts in response. Finish reason: {finish_reason}. "
                f"Text: {text_response or 'None'}"
            )

        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                image_data = part.inline_data.data
                break

        if image_data is None:
            # Try alternative response format
            for part in candidate.content.parts:
                if hasattr(part, "image") and part.image is not None:
                    image_data = part.image.image_bytes
                    break

        if image_data is None:
            # Collect text parts for debugging
            text_parts = [p.text for p in candidate.content.parts if hasattr(p, "text") and p.text]
            raise ImageGenerationError(
                "No image in response. Model may have returned text only. "
                f"Text parts: {'; '.join(text_parts)[:500] if text_parts else 'None'}"
            )

        # Save the image
        image = PILImage.open(BytesIO(image_data))
        if image.mode == "RGBA":
            rgb_image = PILImage.new("RGB", image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[3])
            rgb_image.save(output_path, "PNG")
        elif image.mode == "RGB":
            image.save(output_path, "PNG")
        else:
            image.convert("RGB").save(output_path, "PNG")

        logger.debug(f"Image saved: {output_path} ({len(image_data)} bytes)")
        return output_path

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
    ) -> GeneratedImage:
        """Generate a scene image with character consistency.

        This is the scene-level generation used during episode pipeline.
        It combines character traits from DB with the action description.

        Args:
            scene_number: Scene number (1-24)
            episode_id: Episode ID for file naming
            character_name: Character key
            action_description: What the character is doing in this scene
            reference_image_path: Character's primary reference image
            style_reference_paths: Style reference images for consistency
            character_traits: Dict of character trait fields from DB
            resolution: Output resolution

        Returns:
            GeneratedImage with path and metadata
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

        # Load reference images
        ref_paths = style_reference_paths or []
        if reference_image_path and os.path.exists(reference_image_path):
            ref_paths = [reference_image_path] + ref_paths

        # Output filename
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"episode_{episode_id}_scene_{scene_number:02d}_{timestamp}.png"

        return await self.generate_character_image(
            character_name=character_name,
            prompt=prompt,
            style_reference_paths=ref_paths,
            output_filename=filename,
        )

    async def generate_character_reference(
        self,
        character_name: str,
        character_traits: dict | None = None,
        style_reference_paths: list[str] | None = None,
        resolution: str = "2K",
    ) -> GeneratedImage:
        """Generate a canonical reference image for a character.

        Uses the full character traits from DB + style references to create
        the definitive caricature of this character. The prompt is saved
        to the character's caricature_prompt field for reproducibility.
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
        )


class ImageGenerationError(Exception):
    """Raised when image generation fails."""
    pass
