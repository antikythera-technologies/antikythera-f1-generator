"""Script generation service using Anthropic Claude Haiku."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic

from app.config import settings
from app.exceptions import ScriptGenerationError
from app.services.api_logger import log_api_request, log_api_response

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
    scene_type: str = "TALKING_HEAD"
    face_visible: bool = True
    voiceover_character: Optional[str] = None  # character slug for narrator when face not visible
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
- Each character has a comedic angle — EXPLOIT IT

SCENE TYPES — USE A MIX (this is critical for visual variety):
You MUST use a mix of these scene types throughout the episode. NOT just talking heads!

1. TITLE_CARD (Scene 1 always): Dramatic establishing shot of the circuit with episode title. No character face needed. Wide aerial or iconic circuit view with dramatic lighting. The dialogue is the episode tagline.

2. TALKING_HEAD: Single character speaking to camera or in interview style. Use for commentary, hot takes, reactions.

3. TWO_SHOT: Two characters in the same frame — arguing, reacting, interviewing. Great for pundit-to-pundit or pundit-interviewing-driver scenes.

4. OVER_THE_SHOULDER: Shot/reverse shot conversation. Character A speaks looking LEFT in one scene, Character B responds looking RIGHT in the next. Creates conversational flow. Use this for back-and-forth exchanges.

5. ACTION_REPLAY: On-board cockpit view, crash replay, overtake sequence, pit stop drama. NO character face needed — the car livery and helmet identify the driver (Red Bull = Verstappen, Ferrari = Leclerc, etc.). The DIALOGUE is commentary voiceover describing the action. These are the most visually exciting scenes!

6. PODIUM: Individual driver on podium holding trophy with position number visible (P1, P2, P3). Champagne spray, crowd in background. One driver per scene — don't try to show multiple faces.

7. ESTABLISHING: Wide shot of paddock, pit lane, grid walk, circuit atmosphere. Sets the scene, shows the environment. Can have crowds, team members, cars in background.

8. REACTION: Character reacting silently or with a short quip to something dramatic. Extreme close-up on facial expression. Great for comedy beats.

SCENE MIX REQUIREMENTS:
- Scene 1: ALWAYS a TITLE_CARD
- At least 3 ACTION_REPLAY scenes (racing, overtakes, incidents)
- At least 2 TWO_SHOT or OVER_THE_SHOULDER scenes (conversations)
- At least 1 ESTABLISHING scene
- At least 1 PODIUM scene (if post-race)
- The remaining scenes can be TALKING_HEAD or REACTION
- NEVER have more than 3 TALKING_HEAD scenes in a row — break them up with action or establishing shots
- NEVER use EXTREME CLOSE-UP, CLOSE-UP, or MEDIUM CLOSE-UP as the shot type — the closest allowed framing is MEDIUM SHOT. The full head, hair, and shoulders MUST be visible in every character frame. Tight crops lose hair detail and distort the caricature style.
- NEVER have two consecutive scenes with the same character at the same framing — vary the shot types

FACE VISIBILITY RULE (CRITICAL — determines how images are generated):
- Every scene MUST specify "face_visible": true or false
- true = a character's face is clearly visible in the frame. The system will use instant-character with a face reference image for identity consistency.
- false = no face visible (cars racing, helmet shots, cockpit POV, wide circuit views, crowd shots). The system will use standard LoRA image generation.

When to use face_visible: true:
  - TALKING_HEAD, TWO_SHOT, OVER_THE_SHOULDER, PODIUM, REACTION — almost always true
  - Any scene where we SEE the character's face

When to use face_visible: false:
  - ESTABLISHING — always false (wide shots, no faces)
  - TITLE_CARD — always false
  - ACTION_REPLAY showing cars/helmets/cockpit — false
  - ACTION_REPLAY showing a driver celebrating with face visible — true

VISIBLE CHARACTER vs VOICEOVER CHARACTER:
- "character" field = the person whose FACE is visible in the frame. Set to null if no face is shown.
- "voiceover_character" field = the person NARRATING over the scene (e.g., commentator providing voiceover for racing footage). Set to null if the visible character is speaking.
- Example: ACTION_REPLAY of a car chase with David Croft commentary → character: null, voiceover_character: "david_croft", face_visible: false
- Example: TALKING_HEAD of Jenson Button speaking → character: "jenson_button", voiceover_character: null, face_visible: true
- Example: TWO_SHOT of Croft and Button in studio → character: "david_croft", voiceover_character: null, face_visible: true (TWO_SHOT implies both faces visible, pick the primary one)


CHARACTER RULES:
- Use EXACTLY 3-4 characters per episode
- At least 1 must be a DRIVER or TEAM PRINCIPAL (they ARE the story)
- 1-2 pundits as hosts/anchors (they frame and react to the story)
- Each character appears in 5-8 scenes, giving them a proper arc
- Characters REACT to each other — show consequences, not just monologues
- For ACTION_REPLAY scenes, use one of the pundits as the "character" (they provide voiceover commentary)

VOICE & NATIONALITY (CRITICAL — characters must NOT all sound the same):
- Each character's dialogue MUST reflect their REAL nationality, accent, and speech patterns
- Use the speaking_style, accent_hints, catchphrases, and nationality provided in the character info below
- A French driver should sprinkle in French expressions, a Dutch driver should be blunt and direct, a Finnish driver should be dry and minimal
- British pundits should sound British, but each with their OWN distinctive voice
- The dialogue must read differently for each character — if you cover the character name, the reader should be able to GUESS who is speaking from the speech pattern alone
- Use each character's CATCHPHRASES naturally — these are their signature lines fans expect to hear

STORY STRUCTURE (26 scenes):
- Scene 1: TITLE_CARD — episode title over dramatic circuit shot
- Scenes 2-4: Cold open — hook the viewer with ACTION_REPLAY of the biggest moment + character reactions
- Scenes 5-9: Act 1 — set the stage with mix of TALKING_HEAD, TWO_SHOT, and ACTION_REPLAY
- Scenes 10-15: Act 2 — escalation with heated OVER_THE_SHOULDER exchanges and more ACTION_REPLAY
- Scenes 16-21: Comedy peak — callbacks land, visual gags, REACTION shots
- Scenes 22-25: Resolution — hot takes, predictions, character moments
- Scene 26: Outro — sign-off with show branding or "next time on..." teaser

RUNNING GAGS ARE MANDATORY:
- If running gags are provided, you MUST use at least 3 of them
- Weave them in naturally — they should feel like inside jokes the audience is in on
- Visual gags > verbal gags

ACTION_REPLAY SCENE RULES:
- CRITICAL DIRECTION RULE: All cars on track MUST be driving AWAY from camera, showing REAR wings, diffusers, exhaust pipes, and tail lights. Include "cars ALL driving away from camera showing only their REAR wings" in EVERY racing prompt. NEVER have cars facing towards camera.
- For on-board shots: describe the COCKPIT VIEW — steering wheel, halo device, visor reflection, car livery colors visible on nose/sidepods, cars ahead driving AWAY showing rear wings
- For overtake scenes: describe the specific corner, the cars involved by LIVERY COLOR (not face), the racing line, all cars pointing in the SAME direction away from camera
- For crash/incident scenes: describe the impact, debris, gravel trap, safety car
- The character field should be the COMMENTATOR who provides voiceover
- Dialogue is the commentary: "AND VERSTAPPEN GOES AROUND THE OUTSIDE!"
- These scenes do NOT need character_appearances clothing — they show CARS and HELMETS

For each scene, provide FULL cinematographic direction:

start_frame_prompt and end_frame_prompt must include:
- Scene type (from the list above)
- Shot type (WIDE SHOT, MEDIUM WIDE SHOT, MEDIUM SHOT, TWO-SHOT, OVER-THE-SHOULDER, ESTABLISHING, INSERT, COCKPIT POV) — NEVER use CLOSE-UP or tighter
- Camera angle (eye-level, low angle heroic, high angle diminishing, Dutch angle tension)
- For character scenes: position, pose, facial expression, clothing from character_appearances
- For ACTION_REPLAY: car livery, helmet design, circuit location, racing action
- Setting with SPECIFIC F1 details (name the circuit, corners, sponsors)
- Background elements: AT LEAST 3 (other people, screens, equipment, weather, crowd, cars, pit crew)
- Lighting and mood
- CRITICAL: Start and end frames must be SIMILAR ENOUGH for smooth animation interpolation

camera_direction: Professional camera movement (STATIC, DOLLY PUSH-IN, DOLLY PULL-OUT, PAN, TILT, CRANE, TRACKING, STEADICAM, HANDHELD, WHIP PAN, SLOW ZOOM)

video_prompt must include:
- Camera movement matching camera_direction
- Character motion OR racing action (for ACTION_REPLAY)
- Background motion (screens updating, people moving, sparks flying, cars passing)
- NEVER include style keywords like "ANTKF1STYLE" — the video generator does not use LoRA
- Keep it purely about motion and camera movement

CHARACTER APPEARANCE CONSISTENCY (CRITICAL):
- You MUST define a "character_appearances" object for each character
- DRIVERS: TEAM RACING SUIT — full race suit with sponsor logos, team colors, unzipped to chest with fireproof undershirt visible (post-race look)
- TEAM PRINCIPALS: team-branded smart casual (polo or button shirt)
- PUNDITS/COMMENTATORS: broadcaster's uniform (Sky Sports polo, headset, etc.)
- Be VERY SPECIFIC about colors, branding, accessories, physical features
- Every scene with a visible character MUST use their exact outfit from character_appearances
- ACTION_REPLAY scenes show cars/helmets — no character_appearances needed for those

Output EXACTLY this JSON format:
```json
{
  "title": "Episode title",
  "character_appearances": {
    "character_slug": "Detailed outfit and physical appearance for this episode.",
    "another_slug": "Their specific outfit and appearance."
  },
  "scenes": [
    {
      "scene_number": 1,
      "scene_type": "TITLE_CARD",
      "character": "narrator",
      "voiceover_character": null,
      "face_visible": false,
      "dialogue": "Episode tagline (max 15 words)",
      "audio_description": "Epic orchestral intro, engine roar building",
      "start_frame_prompt": "Full cinematographic description",
      "end_frame_prompt": "Full cinematographic description",
      "camera_direction": "Camera movement",
      "video_prompt": "Motion and animation instructions"
    }
  ],
  "gags_used": ["gag_title_1", "gag_title_2"]
}
```

FINAL RULES:
- Output valid JSON ONLY — no markdown, no commentary
- Exactly 26 scenes
- Dialogue max 15 words per scene
- character field = the person whose FACE is visible (null if no face shown)
- voiceover_character field = the person narrating when face is not shown (null if visible character is speaking)
- face_visible field MUST be true or false for every scene
- scene_type field MUST be one of: TITLE_CARD, TALKING_HEAD, TWO_SHOT, OVER_THE_SHOULDER, ACTION_REPLAY, PODIUM, ESTABLISHING, REACTION
- Scene 1 MUST be TITLE_CARD, Scene 26 MUST be an outro
- At least 3 ACTION_REPLAY scenes required
- At least 2 TWO_SHOT or OVER_THE_SHOULDER scenes required
- character_appearances MUST have an entry for EVERY character
- EVERY character scene's prompts must use their exact outfit from character_appearances
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
        teams: Optional[List[dict]] = None,
    ) -> EpisodeScript:
        """
        Generate a 26-scene script for an episode.

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
            teams=teams,
        )
        logger.debug(f"Prompt length: {len(prompt)} characters")

        log_api_request(logger, "anthropic", self.model, {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system_prompt_len": len(SCRIPT_SYSTEM_PROMPT),
            "user_prompt_len": len(prompt),
        })
        start_time = time.monotonic()

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=SCRIPT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # Extract usage
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens

            log_api_response(logger, "anthropic", self.model, "ok", {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "stop_reason": response.stop_reason,
                "content_len": len(response.content[0].text),
            }, elapsed_ms)

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
                    scene_type=s.get("scene_type", "TALKING_HEAD"),
                    face_visible=s.get("face_visible", True),
                    voiceover_character=s.get("voiceover_character"),
                    action=s.get("action"),  # backward compat
                )
                for s in script_data["scenes"]
            ]

            if len(scenes) != 24:
                logger.warning(f"Expected 26 scenes, got {len(scenes)}")

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
        teams: Optional[List[dict]] = None,
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

        # Team livery reference for prompt injection
        if teams:
            team_lines = []
            for t in teams:
                if t.get("car_description"):
                    team_lines.append(f"- {t['short_name']}: {t['car_description']}")
            if team_lines:
                team_livery_block = f"""\n
TEAM LIVERY REFERENCE (use these EXACT descriptions when showing cars on track):
{chr(10).join(team_lines)}

ACTION_REPLAY RULES:
- When describing a car on track, use the team's car_description from above VERBATIM
- When two cars are racing, describe BOTH cars with their correct liveries
- Cars MUST be driving AWAY from camera showing REAR wings and rear diffusers
- Include dynamic motion: "diving down the inside", "outbraking into Turn X",
  "slipstreaming on the main straight", "wheel-to-wheel through the corner"
- The video_prompt MUST describe motion: "car accelerating", "overtaking maneuver",
  "crossing the finish line at speed", "braking hard into the corner"

ACTION SCENE MOTION TEMPLATES (use these for video_prompt in ACTION_REPLAY scenes):
- OVERTAKE: "Car A dives down the inside of Car B into the corner, aggressive late braking, both cars wheel-to-wheel through the apex, Car A pulls ahead on exit"
- FINISH LINE: "Car crosses the finish line at speed, checkered flag waving, sparks flying from the floor, victory weaving on the straight"
- CHASE: "Two cars in close formation through high-speed corners, slipstreaming, DRS flap open on the following car, closing the gap rapidly"
- INCIDENT: "Car locks up into the corner, tire smoke billowing, gravel spray, dramatic camera angle"

DRIVER APPEARANCE RULES:
- When a driver's face is shown (TALKING_HEAD, PODIUM, TWO_SHOT), they ALWAYS wear their team race suit
- Never describe a driver in casual clothes unless explicitly at a media/press event
"""
                prompt_parts.append(team_livery_block)

        prompt_parts.append(
            "\nGenerate a 26-scene satirical commentary script with full cinematographic direction. "
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
