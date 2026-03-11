"""Script generation service using Anthropic Claude Haiku."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic

from app.config import settings
from app.exceptions import ScriptGenerationError

logger = logging.getLogger(__name__)


@dataclass
class SceneScript:
    """Generated script for a single scene with full cinematographic direction."""
    scene_number: int
    character: str
    dialogue: Optional[str]
    audio_description: Optional[str]
    start_frame_prompt: str
    end_frame_prompt: str
    camera_direction: str
    video_prompt: str
    # Keep action for backward compatibility (derived from camera_direction)
    action: Optional[str] = None


@dataclass
class EpisodeScript:
    """Generated script for an entire episode."""
    title: str
    scenes: list[SceneScript]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    gags_referenced: List[str] = field(default_factory=list)


SCRIPT_SYSTEM_PROMPT = """You are a professional TV director and satirical comedy writer creating an animated F1 show.

Your style:
- Witty, sarcastic humor with deep F1 knowledge
- Character-driven comedy with pop culture references
- Real F1 events and drama become fuel for satirical comedy

For each scene you must provide FULL cinematographic direction as if briefing a director of photography. Every visual detail matters — shot type, camera angle, character position in frame, expression, clothing, setting, lighting, depth of field, background elements, props, and mood.

You are generating TWO key frames per scene (start and end) and the camera/motion direction for the 5-second animation between them. Think of it like creating storyboard panels with detailed director's notes.

CRITICAL RULES:
- Start and end frames for the same scene must be SIMILAR ENOUGH for smooth animation (same setting, same character, shifted pose/framing). The video generator will interpolate between them.
- Each scene MUST be completable in 5 seconds
- Dialogue must be SHORT and punchy (max 15 words)
- Use no more than 3-4 unique characters per episode, each appearing in 4-8 scenes
- The 24 scenes tell a complete story arc: intro (1-3), first act (4-8), deep dive (9-14), comedy peak (15-19), resolution (20-23), sign-off (24)

Shot type vocabulary: WIDE, MEDIUM WIDE, MEDIUM, MEDIUM CLOSE-UP, CLOSE-UP, EXTREME CLOSE-UP, TWO-SHOT, OVER-THE-SHOULDER, ESTABLISHING SHOT, INSERT SHOT

Camera movement vocabulary: STATIC, DOLLY PUSH-IN, DOLLY PULL-OUT, PAN LEFT/RIGHT, TILT UP/DOWN, CRANE UP/DOWN, TRACKING SHOT, STEADICAM, HANDHELD (subtle), WHIP PAN, SLOW ZOOM

For start_frame_prompt and end_frame_prompt, include:
- Shot type and camera position
- Character position in frame (rule of thirds), body orientation, pose, hand placement
- Exact facial expression, eye direction
- Clothing specific to the scene
- Setting/location (broadcast studio, pit wall, paddock, press conference, podium, garage, grid)
- Background details (screens, people, equipment, signage, weather)
- Lighting direction, color temperature, mood
- Depth of field (what's sharp, what's soft)
- Props (microphones, headsets, data screens, trophies)

For video_prompt, include:
- Camera movement matching camera_direction
- Character motion (gestures, head turns, expressions changing)
- Background motion (screen changes, people moving)
- Style note: "Maintain caricature art style throughout"

You will create scripts with exactly 24 scenes, each 5 seconds long.

Output format (JSON):
```json
{
  "title": "Episode title",
  "scenes": [
    {
      "scene_number": 1,
      "character": "character_name",
      "dialogue": "What they say (max 15 words)",
      "audio_description": "Voice tone, background sounds, music, effects",
      "start_frame_prompt": "Full cinematographic description of opening frame",
      "end_frame_prompt": "Full cinematographic description of closing frame",
      "camera_direction": "Professional camera movement instructions",
      "video_prompt": "Motion and animation instructions for the 5-second clip"
    }
  ],
  "gags_used": ["gag_title_1"]
}
```

Rules:
- If recent news is provided, use it as comedy material
- If running gags are provided, weave them in naturally
- List all running gag titles you referenced in "gags_used"
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
        news_context: Optional[List[dict]] = None,
        running_gags: Optional[List[dict]] = None,
    ) -> EpisodeScript:
        """
        Generate a 24-scene script for an episode.

        Args:
            race_context: Description of the race/event to comment on
            characters: List of available characters with their personalities
            episode_type: 'pre-race' or 'post-race'
            news_context: Recent F1 news articles for comedic material
            running_gags: Active running gags to weave into the script

        Returns:
            EpisodeScript with generated content and usage metrics
        """
        logger.info(f"Starting script generation for {episode_type} episode")
        logger.debug(f"Race context: {race_context[:200]}...")
        if news_context:
            logger.info(f"News context: {len(news_context)} articles provided")
        if running_gags:
            logger.info(f"Running gags: {len(running_gags)} gags provided")

        prompt = self._build_prompt(
            race_context, characters, episode_type,
            news_context=news_context, running_gags=running_gags,
        )
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
                    dialogue=s.get("dialogue"),
                    audio_description=s.get("audio_description"),
                    start_frame_prompt=s.get("start_frame_prompt", ""),
                    end_frame_prompt=s.get("end_frame_prompt", ""),
                    camera_direction=s.get("camera_direction", ""),
                    video_prompt=s.get("video_prompt", ""),
                    action=s.get("action"),  # backward compat
                )
                for s in script_data["scenes"]
            ]

            if len(scenes) != 24:
                logger.warning(f"Expected 24 scenes, got {len(scenes)}")

            # Extract gag references from response
            gags_referenced = script_data.get("gags_used", [])
            if gags_referenced:
                logger.info(f"Gags referenced in script: {gags_referenced}")

            return EpisodeScript(
                title=script_data["title"],
                scenes=scenes,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                gags_referenced=gags_referenced,
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
        news_context: Optional[List[dict]] = None,
        running_gags: Optional[List[dict]] = None,
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

        prompt_parts = [
            f"Generate a {episode_type} episode script.",
            f"\nEpisode type: {type_context}",
            f"\nAvailable characters:\n{character_info}",
            f"\nRace context:\n{race_context}",
        ]

        # Add news context if available
        if news_context:
            news_section = self._format_news_context(news_context)
            prompt_parts.append(f"\n{news_section}")

        # Add running gags if available
        if running_gags:
            gags_section = self._format_running_gags(running_gags)
            prompt_parts.append(f"\n{gags_section}")

        prompt_parts.append(
            "\nGenerate a 24-scene satirical commentary script with full cinematographic direction. "
            "Each scene needs start_frame_prompt, end_frame_prompt, camera_direction, and video_prompt. "
            "Use the real news as comedy fuel — exaggerate and satirize real events. "
            "Weave in any running gags that fit naturally. "
            "Output valid JSON only."
        )

        return "\n".join(prompt_parts)

    def _format_news_context(self, news_articles: List[dict]) -> str:
        """Format news articles into prompt context."""
        lines = ["Recent F1 News (use as satirical material — real drama becomes comedy):"]

        for i, article in enumerate(news_articles, 1):
            title = article.get("title", "Untitled")
            summary = article.get("summary", "")
            drivers = article.get("mentioned_drivers", [])
            teams = article.get("mentioned_teams", [])

            entry = f"{i}. {title}"
            if summary:
                # Truncate long summaries to save tokens
                truncated = summary[:300] + "..." if len(summary) > 300 else summary
                entry += f"\n   Summary: {truncated}"
            if drivers:
                entry += f"\n   Drivers mentioned: {', '.join(drivers)}"
            if teams:
                entry += f"\n   Teams mentioned: {', '.join(teams)}"

            lines.append(entry)

        return "\n".join(lines)

    def _format_running_gags(self, gags: List[dict]) -> str:
        """Format running gags into prompt context."""
        lines = [
            "Running Gags (weave these in naturally where they fit — "
            "don't force them all, pick the ones that work best):"
        ]

        for gag in gags:
            title = gag.get("title", "Untitled")
            description = gag.get("description", "")
            category = gag.get("category", "")
            character = gag.get("primary_character", "")
            setup = gag.get("setup", "")
            punchline = gag.get("punchline", "")
            variations = gag.get("variations", "")
            times_used = gag.get("times_used", 0)

            entry = f"- \"{title}\""
            if character:
                entry += f" (character: {character})"
            if category:
                entry += f" [{category}]"
            if description:
                entry += f"\n  Description: {description}"
            if setup:
                entry += f"\n  Setup: {setup}"
            if punchline:
                entry += f"\n  Punchline: {punchline}"
            if variations:
                entry += f"\n  Variations: {variations}"
            if times_used > 0:
                entry += f"\n  Used {times_used} times before — find a fresh angle"

            lines.append(entry)

        return "\n".join(lines)

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
