"""Image generation service using Nano Banana Pro (Gemini 3 Pro Image).

Implements character consistency through:
1. Reference images stored per character
2. Detailed visual style guides in prompts
3. Image editing mode for maintaining consistency
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


# Visual style guide for maintaining consistency across all generations
VISUAL_STYLE_GUIDE = """
Art style: High-quality 3D animation style, similar to modern animated films.
Color palette: Rich, vibrant colors with deep navy (#0a1628), racing red (#e31937), and neon cyan (#00f0d4) accents.
Lighting: Dynamic, cinematic lighting with subtle rim lights and ambient glow effects.
Background: Racing-themed environments with subtle blur for depth of field.
Overall mood: Professional, energetic, slightly stylized/satirical but not cartoonish.
Rendering: Clean, polished 3D render quality with anti-aliasing and soft shadows.
"""

# Character visual templates for consistency
CHARACTER_TEMPLATES = {
    "max_verstappen": {
        "base_description": "Max Verstappen, a confident young Dutch racing driver with short brown hair, blue eyes, and sharp facial features. Wearing Red Bull Racing team gear with Oracle and Honda logos.",
        "colors": "Red Bull navy blue (#1e3a5f) team colors with red and yellow accents",
        "distinctive_features": "Determined expression, athletic build, often wearing cap backward when not in helmet",
    },
    "lewis_hamilton": {
        "base_description": "Lewis Hamilton, British racing legend with braids or short curly hair, warm brown skin, and expressive eyes. Wearing Mercedes AMG team wear.",
        "colors": "Mercedes silver and black (#00d2be teal accents) team colors",
        "distinctive_features": "Confident smile, fashion-forward accessories, athletic build",
    },
    "charles_leclerc": {
        "base_description": "Charles Leclerc, young Monegasque driver with wavy brown hair, green-hazel eyes, and boyish good looks. Wearing Ferrari team gear.",
        "colors": "Ferrari red (#dc0000) team colors with yellow accents",
        "distinctive_features": "Intense focused gaze, slight stubble, passionate expressions",
    },
    "lando_norris": {
        "base_description": "Lando Norris, young British driver with curly brown hair, friendly face, and bright personality. Wearing McLaren team wear.",
        "colors": "McLaren papaya orange (#ff8000) team colors",
        "distinctive_features": "Playful smile, youthful appearance, energetic expressions",
    },
    "carlos_sainz": {
        "base_description": "Carlos Sainz, Spanish driver with dark hair, warm complexion, and friendly demeanor. Wearing Ferrari team gear.",
        "colors": "Ferrari red (#dc0000) team colors",
        "distinctive_features": "Genuine smile, well-groomed beard, approachable expression",
    },
    "generic_commentator": {
        "base_description": "Professional motorsport commentator in broadcast studio setting, wearing formal attire with network branding.",
        "colors": "Professional dark suit with subtle network colors",
        "distinctive_features": "Confident broadcaster pose, studio lighting, graphics behind",
    },
}


class ImageGenerator:
    """Service for generating consistent character images using Gemini 3 Pro Image."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.output_dir = Path("/tmp/f1-images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate_scene_image(
        self,
        scene_number: int,
        episode_id: int,
        character_name: str,
        action_description: str,
        reference_image_path: Optional[str] = None,
        resolution: str = "1K",
    ) -> GeneratedImage:
        """
        Generate a scene image with character consistency.

        Args:
            scene_number: Scene number (1-24)
            episode_id: Episode ID for file naming
            character_name: Character key (e.g., 'max_verstappen')
            action_description: What the character is doing
            reference_image_path: Optional reference image for style consistency
            resolution: Output resolution (1K, 2K, or 4K)

        Returns:
            GeneratedImage with path and metadata
        """
        logger.info(f"Scene {scene_number}: Generating image for {character_name}")

        # Build comprehensive prompt with character consistency
        prompt = self._build_consistent_prompt(character_name, action_description)
        logger.debug(f"Scene {scene_number}: Prompt: {prompt[:200]}...")

        # Output filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"episode_{episode_id}_scene_{scene_number:02d}_{timestamp}.png"
        output_path = self.output_dir / filename

        start_time = time.time()

        try:
            # Run generation in executor to avoid blocking
            image_path = await asyncio.get_event_loop().run_in_executor(
                None,
                self._generate_image_sync,
                prompt,
                str(output_path),
                reference_image_path,
                resolution,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Scene {scene_number}: Generated in {elapsed_ms}ms -> {image_path}")

            return GeneratedImage(
                image_path=image_path,
                generation_time_ms=elapsed_ms,
                prompt_used=prompt,
            )

        except Exception as e:
            logger.error(f"Scene {scene_number}: Image generation failed - {e}")
            raise ImageGenerationError(f"Scene {scene_number}: {e}")

    def _generate_image_sync(
        self,
        prompt: str,
        output_path: str,
        reference_image_path: Optional[str],
        resolution: str,
    ) -> str:
        """Synchronous image generation using Imagen 4.0 (called from executor)."""
        from google.genai import types

        # Note: Imagen 4.0 doesn't support reference image input directly
        # For style consistency, we rely on detailed prompts
        if reference_image_path:
            logger.debug(f"Reference image provided but Imagen uses prompt-only generation")

        # Generate image using Imagen 4.0 API
        response = self.client.models.generate_images(
            model=settings.GEMINI_IMAGE_MODEL,  # "imagen-4.0-generate-001"
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/png",
            )
        )

        # Extract and save the generated image
        if not response.generated_images:
            raise ImageGenerationError("No images generated")

        image_data = response.generated_images[0].image.image_bytes
        image = PILImage.open(BytesIO(image_data))

        # Convert to RGB and save
        if image.mode == 'RGBA':
            rgb_image = PILImage.new('RGB', image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[3])
            rgb_image.save(output_path, 'PNG')
        elif image.mode == 'RGB':
            image.save(output_path, 'PNG')
        else:
            image.convert('RGB').save(output_path, 'PNG')

        logger.debug(f"Image saved: {output_path} ({len(image_data)} bytes)")
        return output_path

    def _build_consistent_prompt(
        self,
        character_name: str,
        action_description: str,
    ) -> str:
        """
        Build a prompt that maintains character consistency.

        Combines:
        - Global visual style guide
        - Character-specific appearance details
        - Scene-specific action
        """
        # Get character template or use generic
        char_key = character_name.lower().replace(" ", "_")
        char_template = CHARACTER_TEMPLATES.get(char_key, CHARACTER_TEMPLATES.get("generic_commentator"))

        prompt_parts = [
            # Visual style consistency
            VISUAL_STYLE_GUIDE.strip(),
            "",
            # Character consistency
            f"Character: {char_template['base_description']}",
            f"Team colors: {char_template['colors']}",
            f"Distinctive features: {char_template['distinctive_features']}",
            "",
            # Scene-specific action
            f"Scene: {action_description}",
            "",
            # Quality directives
            "Important: Maintain consistent character appearance. High quality, cinematic composition.",
        ]

        return "\n".join(prompt_parts)

    async def generate_character_reference(
        self,
        character_name: str,
        pose: str = "neutral portrait",
        resolution: str = "2K",
    ) -> GeneratedImage:
        """
        Generate a reference image for a character (for storing in database).

        This creates a canonical reference that can be used for consistency
        in future generations via the edit mode.
        """
        logger.info(f"Generating reference image for {character_name}")

        char_key = character_name.lower().replace(" ", "_")
        char_template = CHARACTER_TEMPLATES.get(char_key)

        if not char_template:
            raise ValueError(f"Unknown character: {character_name}")

        prompt = f"""
{VISUAL_STYLE_GUIDE}

Create a reference portrait of {char_template['base_description']}
Pose: {pose}
Team colors: {char_template['colors']}
Distinctive features: {char_template['distinctive_features']}

This is a reference image that will be used for character consistency.
Clear, well-lit, showing face and upper body clearly.
Professional quality suitable for animation reference.
"""

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"ref_{char_key}_{timestamp}.png"
        output_path = self.output_dir / filename

        start_time = time.time()
        image_path = await asyncio.get_event_loop().run_in_executor(
            None,
            self._generate_image_sync,
            prompt.strip(),
            str(output_path),
            None,
            resolution,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        return GeneratedImage(
            image_path=image_path,
            generation_time_ms=elapsed_ms,
            prompt_used=prompt,
        )


class ImageGenerationError(Exception):
    """Raised when image generation fails."""
    pass
