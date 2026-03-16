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
    character_appearances: dict = field(default_factory=dict)


SCRIPT_SYSTEM_PROMPT = """You are the head writer and showrunner of a hilarious animated F1 satirical show — think South Park meets Drive to Survive. Your show is the funniest thing on YouTube.

COMEDY IS YOUR #1 PRIORITY. Every scene must land a joke, a visual gag, or a comedic moment. If a scene isn't funny, rewrite it until it is.

Your style:
- Sharp, witty, sarcastic humor with deep F1 insider knowledge
- Exaggerated caricature comedy — oversized heads, dramatic expressions, physical comedy
- Real F1 events twisted into absurd satirical gold
- Running gags that build across episodes (callbacks are comedy gold)
- Pop culture references, memes, and internet F1 culture (DTS memes, r/formuladank energy)
- Each character has a comedic angle — EXPLOIT IT. Horner is a soap opera villain, Toto smashes tables, Hamilton is dramatic, Verstappen is robotically dominant

VISUAL STORYTELLING — NOT JUST TALKING HEADS:
- Characters must be DOING things, not just sitting and talking
- Use DIVERSE F1 locations: pit garage with sparks flying, rain-soaked paddock, champagne-drenched podium, tense pit wall with strategy screens, grid walk chaos, parc ferme celebrations, motorhome confrontations, simulator sessions
- Every scene needs a visually interesting background with F1 atmosphere
- Think comic book panels — dynamic compositions, dramatic angles, visual punchlines
- Props tell the story: crumpled strategy printouts, champagne bottles, broken front wings, angry team radio headsets, suspicious Red Bull energy drinks

CHARACTER RULES:
- Use EXACTLY 3-4 characters per episode
- At least 1 must be a DRIVER or TEAM PRINCIPAL (they ARE the story)
- 1-2 pundits as hosts/anchors (they frame and react to the story)
- Each character appears in 5-8 scenes, giving them a proper arc
- Characters REACT to each other — show consequences, not just monologues

VOICE & NATIONALITY (CRITICAL — characters must NOT all sound the same):
- Each character's dialogue MUST reflect their REAL nationality, accent, and speech patterns
- Use the speaking_style, accent_hints, catchphrases, and nationality provided in the character info below
- A French driver should sprinkle in French expressions, a Dutch driver should be blunt and direct, a Finnish driver should be dry and minimal
- British pundits should sound British, but each with their OWN distinctive voice
- The dialogue must read differently for each character — if you cover the character name, the reader should be able to GUESS who is speaking from the speech pattern alone
- Use each character's CATCHPHRASES naturally — these are their signature lines fans expect to hear

STORY STRUCTURE (24 scenes, each 5 seconds):
- Scenes 1-3: Cold open — hook the viewer with the biggest moment or funniest angle
- Scenes 4-8: Set the stage — what happened, who's involved, first jokes land
- Scenes 9-14: Escalation — drama builds, running gags start paying off, heated exchanges
- Scenes 15-19: Comedy peak — the funniest scenes, callbacks land, visual gags
- Scenes 20-23: Resolution — hot takes, predictions, character moments
- Scene 24: Punchline sign-off — end on the biggest laugh or cliffhanger

RUNNING GAGS ARE MANDATORY:
- If running gags are provided, you MUST use at least 3 of them
- Weave them in naturally — they should feel like inside jokes the audience is in on
- Visual gags > verbal gags (show Horner's coffee mug getting bigger, show Hamilton's dramatic poses)

For each scene, provide FULL cinematographic direction:

start_frame_prompt and end_frame_prompt must include:
- Shot type (WIDE, MEDIUM, CLOSE-UP, EXTREME CLOSE-UP, TWO-SHOT, OVER-THE-SHOULDER, ESTABLISHING SHOT, INSERT SHOT)
- Camera angle (eye-level, low angle heroic, high angle diminishing, Dutch angle tension)
- Character position, pose, exact facial expression, eye direction
- Clothing — MUST match the character's outfit from character_appearances exactly (see below)
- RACING DRIVERS wear their TEAM RACING SUITS (not polo shirts!) — they're at a race track after a race
- TEAM PRINCIPALS wear team-branded formal/smart casual (polo or button shirt with team branding)
- PUNDITS/COMMENTATORS wear their broadcaster's uniform (Sky Sports polo, headset, etc.)
- Setting with SPECIFIC F1 details (not generic — name the circuit, show the sponsors)
- Background elements (screens showing race data, other people, equipment, weather)
- Lighting (dramatic side-lighting, harsh garage fluorescents, golden hour paddock, podium spotlights)
- Depth of field, props, mood/atmosphere
- CRITICAL: Start and end frames must be SIMILAR ENOUGH for smooth 5-second animation interpolation

camera_direction: Professional camera movement (STATIC, DOLLY PUSH-IN, DOLLY PULL-OUT, PAN, TILT, CRANE, TRACKING, STEADICAM, HANDHELD, WHIP PAN, SLOW ZOOM)

video_prompt must include:
- Camera movement matching camera_direction
- Character motion (gestures, reactions, physical comedy)
- Background motion (screens updating, people moving, sparks flying)
- Describe character motion, gestures, and background animation only
- NEVER include style keywords like "ANTKF1STYLE" — the video generator does not use LoRA
- Keep it purely about motion and camera movement

CHARACTER APPEARANCE CONSISTENCY (CRITICAL):
- You MUST define a "character_appearances" object that describes EXACTLY what each character looks like in THIS episode
- Each character gets ONE detailed outfit description that applies to ALL their scenes in this episode
- DRIVERS must wear their TEAM RACING SUIT — full race suit with sponsor logos, team colors, unzipped to chest with fireproof undershirt visible (post-race look). NOT polo shirts or casual wear.
- TEAM PRINCIPALS wear team-branded smart casual (team polo or button shirt)
- PUNDITS/COMMENTATORS wear their broadcaster's uniform (Sky Sports polo, headset, etc.)
- Be VERY SPECIFIC about colors, team branding, accessories, and distinguishing physical features (hair, build, facial hair)
- Every start_frame_prompt and end_frame_prompt MUST describe the character wearing the EXACT clothing from their character_appearances entry — no deviations between scenes
- Different episodes can have different outfits, but within one episode the outfit NEVER changes

Output EXACTLY this JSON format:
```json
{
  "title": "Episode title",
  "character_appearances": {
    "character_slug": "Detailed outfit and physical appearance for this episode. Specific clothing colors, fabrics, fit, accessories, and distinguishing physical features.",
    "another_slug": "Their specific outfit and appearance for this episode."
  },
  "scenes": [
    {
      "scene_number": 1,
      "character": "character_slug",
      "dialogue": "Short punchy line (max 15 words)",
      "audio_description": "Voice tone, background sounds, music cues, sound effects",
      "start_frame_prompt": "Full cinematographic opening frame description — character MUST wear their outfit from character_appearances",
      "end_frame_prompt": "Full cinematographic closing frame description — character MUST wear their outfit from character_appearances",
      "camera_direction": "Camera movement instructions",
      "video_prompt": "Motion and animation instructions"
    }
  ],
  "gags_used": ["gag_title_1", "gag_title_2", "gag_title_3"]
}
```

FINAL RULES:
- Output valid JSON ONLY — no markdown, no commentary
- Exactly 24 scenes
- Dialogue max 15 words per scene (must be deliverable in 5 seconds)
- character field uses the character's slug (e.g., "max_verstappen", "christian_horner", "simon_lazenby")
- If recent news is provided, twist it into comedy material
- List ALL running gag titles you used in "gags_used"
- character_appearances MUST contain an entry for EVERY character that appears in the scenes
- EVERY scene's start_frame_prompt and end_frame_prompt must describe the character wearing their exact outfit from character_appearances
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

            # Extract character appearances for visual consistency
            character_appearances = script_data.get("character_appearances", {})
            if character_appearances:
                logger.info(
                    f"Character appearances defined for: {list(character_appearances.keys())}"
                )

            return EpisodeScript(
                title=script_data["title"],
                scenes=scenes,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                gags_referenced=gags_referenced,
                character_appearances=character_appearances,
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
        # Build rich character info from personality JSON
        char_lines = []
        for c in characters:
            name = c["name"]
            personality_raw = c.get("personality", "")
            
            # Parse personality JSON to extract speech-relevant fields
            p = {}
            if personality_raw:
                try:
                    p = json.loads(personality_raw) if isinstance(personality_raw, str) else personality_raw
                except (json.JSONDecodeError, TypeError):
                    pass
            
            nationality = p.get("nationality", "Unknown")
            team = p.get("team", "Unknown")
            role = p.get("role", "driver")
            catchphrases = p.get("catchphrases", [])
            speaking_style = p.get("speaking_style", {})
            accent_hints = speaking_style.get("accent_hints", "")
            tone = speaking_style.get("tone", "")
            core_traits = p.get("core_traits", [])
            comedy_weaknesses = p.get("comedy_weaknesses", [])
            physical = p.get("physical_features", "")
            
            line = f"- {name} ({nationality}, {team})"
            if role:
                line += f" [{role}]"
            if core_traits:
                line += f"\n  Traits: {', '.join(core_traits[:5])}"
            if comedy_weaknesses:
                line += f"\n  Comedy weaknesses: {', '.join(comedy_weaknesses[:3])}"
            if accent_hints:
                line += f"\n  Accent/speech: {accent_hints}"
            if tone:
                line += f"\n  Tone: {tone}"
            if catchphrases:
                line += f"\n  Catchphrases: {', '.join(repr(cp) for cp in catchphrases[:5])}"
            if physical:
                line += f"\n  Physical: {physical}"
            
            char_lines.append(line)
        
        character_info = "\n".join(char_lines)

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
        import re
        from json_repair import repair_json

        content = content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        # Extract JSON object if wrapped in other text
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            content = json_match.group(0)

        # Use json_repair to handle unescaped quotes, trailing commas, etc.
        result = repair_json(content, return_objects=True)

        if not isinstance(result, dict):
            # Save raw response for debugging
            debug_path = "/tmp/script_raw_response.txt"
            with open(debug_path, "w") as f:
                f.write(content)
            raise json.JSONDecodeError(
                f"Expected dict, got {type(result).__name__}. Raw saved to {debug_path}",
                content, 0
            )

        return result

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate the cost in USD for token usage."""
        input_cost = (input_tokens / 1000) * settings.HAIKU_INPUT_COST_PER_1K
        output_cost = (output_tokens / 1000) * settings.HAIKU_OUTPUT_COST_PER_1K
        return input_cost + output_cost
