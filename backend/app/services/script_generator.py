"""Script generation service using Anthropic Claude Haiku."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import anthropic

from app.config import settings
from app.exceptions import ScriptGenerationError

logger = logging.getLogger(__name__)


@dataclass
class SceneScript:
    """Generated script for a single scene."""
    scene_number: int
    character: str
    action: str
    dialogue: Optional[str]
    audio_description: Optional[str]


@dataclass
class EpisodeScript:
    """Generated script for an entire episode."""
    title: str
    scenes: list[SceneScript]
    input_tokens: int
    output_tokens: int
    cost_usd: float


SCRIPT_SYSTEM_PROMPT = """You are a satirical F1 commentator creating scripts for animated videos.

Your style:
- Witty, sarcastic humor
- Deep F1 knowledge
- Character-driven comedy
- Pop culture references when appropriate

You will create scripts with exactly 24 scenes, each 5 seconds long.
Each scene features one character speaking or reacting.

Output format (JSON):
```json
{
  "title": "Episode title",
  "scenes": [
    {
      "scene_number": 1,
      "character": "character_name",
      "action": "What the character is physically doing",
      "dialogue": "What they say (keep under 15 words)",
      "audio_description": "Background sounds, voice tone"
    }
  ]
}
```

Rules:
- Each scene MUST be completable in 5 seconds
- Dialogue must be SHORT and punchy
- Actions must be simple and animatable
- Audio descriptions help set the mood
- Create a coherent narrative across all 24 scenes
"""


class ScriptGenerator:
    """Service for generating episode scripts using Anthropic Claude."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL
        self.max_tokens = settings.ANTHROPIC_MAX_TOKENS
        self.temperature = settings.ANTHROPIC_TEMPERATURE

    async def generate_script(
        self,
        race_context: str,
        characters: list[dict],
        episode_type: str = "post-race",
    ) -> EpisodeScript:
        """
        Generate a 24-scene script for an episode.

        Args:
            race_context: Description of the race/event to comment on
            characters: List of available characters with their personalities
            episode_type: 'pre-race' or 'post-race'

        Returns:
            EpisodeScript with generated content and usage metrics
        """
        logger.info(f"Starting script generation for {episode_type} episode")
        logger.debug(f"Race context: {race_context[:200]}...")

        prompt = self._build_prompt(race_context, characters, episode_type)
        logger.debug(f"Prompt length: {len(prompt)} characters")

        start_time = time.time()

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=SCRIPT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Anthropic response received in {elapsed_ms}ms")

            # Extract usage
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens

            logger.info(f"Token usage - Input: {input_tokens}, Output: {output_tokens}")

            # Calculate cost
            cost_usd = self._calculate_cost(input_tokens, output_tokens)
            logger.info(f"Estimated cost: ${cost_usd:.6f}")

            # Parse response
            content = response.content[0].text
            script_data = self._parse_response(content)

            # Build scene list
            scenes = [
                SceneScript(
                    scene_number=s["scene_number"],
                    character=s["character"],
                    action=s["action"],
                    dialogue=s.get("dialogue"),
                    audio_description=s.get("audio_description"),
                )
                for s in script_data["scenes"]
            ]

            if len(scenes) != 24:
                logger.warning(f"Expected 24 scenes, got {len(scenes)}")

            return EpisodeScript(
                title=script_data["title"],
                scenes=scenes,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            raise ScriptGenerationError(f"Anthropic API error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse script response: {e}")
            raise ScriptGenerationError(f"Failed to parse script response: {e}")

    def _build_prompt(
        self,
        race_context: str,
        characters: list[dict],
        episode_type: str,
    ) -> str:
        """Build the prompt for script generation."""
        character_info = "\n".join(
            f"- {c['name']}: {c.get('personality', 'No personality defined')} "
            f"(Voice: {c.get('voice_description', 'neutral')})"
            for c in characters
        )

        type_context = (
            "Preview and predictions for the upcoming race"
            if episode_type == "pre-race"
            else "Post-race analysis and commentary"
        )

        return f"""Generate a {episode_type} episode script.

Episode type: {type_context}

Available characters:
{character_info}

Race context:
{race_context}

Generate a 24-scene satirical commentary script. Output valid JSON only."""

    def _parse_response(self, content: str) -> dict:
        """Parse the LLM response into structured data."""
        # Try to extract JSON from response
        content = content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        return json.loads(content)

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate the cost in USD for token usage."""
        input_cost = (input_tokens / 1000) * settings.HAIKU_INPUT_COST_PER_1K
        output_cost = (output_tokens / 1000) * settings.HAIKU_OUTPUT_COST_PER_1K
        return input_cost + output_cost
