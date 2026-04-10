"""Script generation service using Anthropic Claude Haiku."""

import json
import logging
import re
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
    end_frame_prompt: Optional[str] = None
    camera_direction: str = ""
    video_prompt: str = ""
    scene_type: str = "TALKING_HEAD"
    face_visible: bool = True
    voiceover_character: Optional[str] = None  # character slug for narrator when face not visible
    target_duration: Optional[int] = None  # LLM-estimated duration in seconds (3-10)
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


def sanitize_scene_prompts(scene: SceneScript) -> SceneScript:
    """Sanitize LLM-generated prompts to enforce racing direction and car count rules.

    The LLM sometimes generates prompts that violate F1 visual rules (cars facing
    camera, too many cars on track). This fixes violations at source so the
    image/video pipelines receive clean, non-contradictory prompts.
    """
    import re as _re

    # Direction violations: cars must drive AWAY from camera, show REAR wings.
    # Image models interpret ANY "approaching/toward" language as cars coming
    # AT the camera, even "approaching the finish line". Must catch all variants.
    direction_patterns = [
        (r'(?i)\bapproaching\s+(?:the\s+)?camera\b', 'driving away from camera showing rear wings and rear diffusers'),
        (r'(?i)\bfacing\s+(?:the\s+)?camera\b', 'driving away from camera showing rear wings and rear diffusers'),
        (r'(?i)\btowards\s+(?:the\s+)?camera\b', 'away from camera showing rear wings'),
        (r'(?i)\bracing\s+towards\b', 'racing away from camera'),
        (r'(?i)\bdriving\s+towards\b', 'driving away from camera'),
        (r'(?i)\bcoming\s+towards\b', 'driving away from camera'),
        (r'(?i)\bhead[\s-]on\b', 'from behind showing rear wings'),
        (r'(?i)\bfacing\s+(?:the\s+)?viewer\b', 'driving away from the viewer showing rear wings'),
        (r'(?i)\bshowing\s+front\s+wing\b', 'showing rear wing and rear diffuser'),
        # Broader "approaching/toward" — image models read these as cars facing camera
        (r'(?i)\bapproaching\s+(?:the\s+)?finish\b', 'crossing the finish line driving away from camera'),
        (r'(?i)\bapproaching\s+(?:the\s+)?line\b', 'crossing the line driving away from camera'),
        (r'(?i)\baccelerating\s+toward\b', 'accelerating away from camera'),
        (r'(?i)\bracing\s+toward\b', 'racing away from camera'),
        (r'(?i)\bdriving\s+toward\b', 'driving away from camera'),
        (r'(?i)\bcar\s+approaching\b', 'car driving away from camera'),
        (r'(?i)\bcars?\s+racing\s+at\b', 'cars racing away from'),
        (r'(?i)\bfront\s+wings?\s+visible\b', 'rear wings visible'),
        (r'(?i)\bfront\s+of\s+(?:the\s+)?cars?\b', 'rear of the car'),
        # "diving/dives down the inside" / "lunging inside" — implies car approaching from front
        (r'(?i)\bdiv(?:ing|es?)\s+(?:down\s+)?(?:the\s+)?inside\s+(?:of\s+)?', 'closing the gap behind '),
        (r'(?i)\blunging\s+(?:down\s+)?(?:the\s+)?inside\b', 'pulling alongside from behind'),
        (r'(?i)\bdiv(?:ing|es?)\s+(?:down\s+)?(?:into|through)\b', 'racing through'),
    ]

    # Car count violations: max 22 cars on the F1 grid
    car_count_patterns = [
        (r'(?i)\bdozens\s+of\s+(?:F1\s+)?cars\b', 'a pack of F1 cars (max 22 on the grid)'),
        (r'(?i)\bhundreds\s+of\s+(?:F1\s+)?cars\b', 'a pack of F1 cars (max 22 on the grid)'),
        (r'(?i)\bcountless\s+(?:F1\s+)?cars\b', 'a pack of F1 cars (max 22 on the grid)'),
        (r'(?i)\bmany\s+(?:F1\s+)?cars\b', 'a pack of F1 cars (max 22 on the grid)'),
        (r'(?i)\b(?:3[0-9]|[4-9][0-9])\s+(?:F1\s+)?cars\b', '22 F1 cars'),
    ]

    # Clothing sanitization: "suit" alone could trigger business suit images
    clothing_patterns = [
        (r'(?i)\bwearing\s+a\s+suit\b', 'wearing team-coloured racing overalls'),
        (r'(?i)\bin\s+a\s+suit\b', 'in team-coloured racing overalls'),
        (r'(?i)\bbusiness\s+suit\b', 'team-coloured racing overalls'),
        (r'(?i)\bformal\s+suit\b', 'team-coloured racing overalls'),
        (r'(?i)\bdress\s+suit\b', 'team-coloured racing overalls'),
        (r'(?i)\bclosed[- ]cockpit\b', 'open-cockpit'),
        (r'(?i)\bwith\s+(?:a\s+)?roof\b', 'open-cockpit with halo device'),
        (r'(?i)\bcanopy\s+(?:over|on|covering)\b', 'halo device above'),
    ]

    # Sanitize video_prompt for escalation language (prevents screaming audio)
    vp = getattr(scene, 'video_prompt', None)
    if vp:
        scene.video_prompt = sanitize_video_prompt(vp)

    # Determine which patterns apply based on scene type.
    # Direction patterns ONLY apply to scenes that show cars on track.
    # For TALKING_HEAD, TWO_SHOT, OVER_THE_SHOULDER, REACTION:
    #   "facing the camera" means the PERSON faces the camera — correct!
    #   Replacing it with "driving away showing rear wings" is nonsensical
    #   and produces broken prompts like "Brundle driving away from camera
    #   showing rear wings and rear diffusers with characteristic smile".
    _st = getattr(scene, 'scene_type', '') or ''
    _st_upper = _st.upper().split('.')[-1] if '.' in _st else _st.upper()
    _car_scene_types = {'ACTION_REPLAY', 'ESTABLISHING', 'TITLE_CARD'}
    _is_car_scene = _st_upper in _car_scene_types

    for field_name in ('start_frame_prompt', 'end_frame_prompt', 'video_prompt'):
        value = getattr(scene, field_name, None)
        if not value:
            continue

        # Direction + car count patterns: ONLY for scenes with cars on track
        if _is_car_scene:
            for pattern, replacement in direction_patterns:
                value = _re.sub(pattern, replacement, value)
            for pattern, replacement in car_count_patterns:
                value = _re.sub(pattern, replacement, value)

        # Clothing + cockpit patterns: always apply
        for pattern, replacement in clothing_patterns:
            value = _re.sub(pattern, replacement, value)

        setattr(scene, field_name, value)

    return scene


def sanitize_prompt_text(text: str, scene_type: str = None) -> str:
    """Sanitize a raw prompt string for direction and escalation violations.

    Use this when regenerating scenes from stored prompts that may predate
    the sanitization rules. Works on plain strings unlike sanitize_scene_prompts
    which requires a SceneScript object.
    """
    import re as _re

    direction_patterns = [
        (r'(?i)\bapproaching\s+(?:the\s+)?camera\b', 'driving away from camera showing rear wings'),
        (r'(?i)\bfacing\s+(?:the\s+)?camera\b', 'driving away from camera showing rear wings'),
        (r'(?i)\btowards\s+(?:the\s+)?camera\b', 'away from camera showing rear wings'),
        (r'(?i)\bracing\s+towards\b', 'racing away from camera'),
        (r'(?i)\bdriving\s+towards\b', 'driving away from camera'),
        (r'(?i)\bcoming\s+towards\b', 'driving away from camera'),
        (r'(?i)\bhead[\s-]on\b', 'from behind showing rear wings'),
        (r'(?i)\bfacing\s+(?:the\s+)?viewer\b', 'driving away from the viewer showing rear wings'),
        (r'(?i)\bshowing\s+front\s+wing\b', 'showing rear wing and rear diffuser'),
        (r'(?i)\bapproaching\s+(?:the\s+)?finish\b', 'crossing the finish line driving away from camera'),
        (r'(?i)\bapproaching\s+(?:the\s+)?line\b', 'crossing the line driving away from camera'),
        (r'(?i)\baccelerating\s+toward\b', 'accelerating away from camera'),
        (r'(?i)\bracing\s+toward\b', 'racing away from camera'),
        (r'(?i)\bdriving\s+toward\b', 'driving away from camera'),
        (r'(?i)\bcar\s+approaching\b', 'car driving away from camera'),
        (r'(?i)\bcars?\s+racing\s+at\b', 'cars racing away from'),
        (r'(?i)\bfront\s+wings?\s+visible\b', 'rear wings visible'),
        (r'(?i)\bfront\s+of\s+(?:the\s+)?cars?\b', 'rear of the car'),
        # "diving/dives down the inside" / "lunging inside" — implies car approaching from front
        (r'(?i)\bdiv(?:ing|es?)\s+(?:down\s+)?(?:the\s+)?inside\s+(?:of\s+)?', 'closing the gap behind '),
        (r'(?i)\blunging\s+(?:down\s+)?(?:the\s+)?inside\b', 'pulling alongside from behind'),
        (r'(?i)\bdiv(?:ing|es?)\s+(?:down\s+)?(?:into|through)\b', 'racing through'),
    ]

    # Only apply direction patterns to car scenes.
    # For TALKING_HEAD, TWO_SHOT, etc., "facing the camera" is correct for people.
    _st = (scene_type or '').upper()
    _car_types = {'ACTION_REPLAY', 'ESTABLISHING', 'TITLE_CARD'}
    _is_car_scene = _st in _car_types or not scene_type  # default if no type

    if _is_car_scene:
        for pattern, replacement in direction_patterns:
            text = _re.sub(pattern, replacement, text)

    text = sanitize_video_prompt(text)
    return text


# F1 acronyms to preserve in uppercase
_F1_ACRONYMS = {
    "f1", "drs", "fia", "gp", "dnf", "dns", "dsq", "vsc", "sc", "ers",
    "kers", "mguh", "mguk", "tps", "rss", "tv", "bbc", "sky", "gpda",
}

# Proper nouns that must keep their capitalisation after lowercase conversion.
# TTS handles capitalised proper nouns fine — it's ALL-CAPS words that scream.
_F1_PROPER_NOUNS = [
    # Drivers
    "Hamilton", "Verstappen", "Leclerc", "Norris", "Sainz", "Piastri",
    "Russell", "Antonelli", "Alonso", "Stroll", "Gasly", "Ocon",
    "Tsunoda", "Lawson", "Albon", "Colapinto", "Bearman", "Hulkenberg",
    "Magnussen", "Bottas", "Zhou", "Perez", "Ricciardo", "Sargeant",
    "Doohan", "Bortoleto", "Hadjar",
    # Teams
    "Ferrari", "Mercedes", "McLaren", "Red Bull", "Aston Martin",
    "Alpine", "Williams", "Haas", "Sauber", "Kick Sauber",
    "Petronas", "Oracle", "Cognizant",
    # People
    "Toto", "Wolff", "Horner", "Binotto", "Vasseur", "Brawn",
    "Button", "Croft", "Brundle",
    # Circuits / Cities
    "Shanghai", "Silverstone", "Monza", "Monaco", "Suzuka", "Spa",
    "Jeddah", "Bahrain", "Melbourne", "Barcelona", "Budapest",
    "Zandvoort", "Singapore", "Austin", "Interlagos", "Imola",
    "Baku", "Lusail", "Las Vegas", "Miami", "Montreal", "Spielberg",
    # Brands
    "Pirelli", "Honda", "Toyota",
    # Countries
    "Italy", "China", "Japan", "Britain", "Germany", "Australia",
    "Spain", "France", "Netherlands", "Brazil", "Mexico", "Canada",
]
# Position labels: p1-p20
_POSITION_PATTERN = re.compile(r"\bp(\d{1,2})\b", re.IGNORECASE)


def sanitize_dialogue(text: str) -> str:
    """Convert dialogue to sentence case. ANY capitals make TTS scream.

    Rules:
    - Convert everything to lowercase first
    - Capitalise only the first letter of each sentence
    - Preserve F1 acronyms (F1, DRS, FIA, GP, DNF, etc.)
    - Preserve position labels (P1, P2, ... P20)
    - Collapse 3+ repeated letters (aaaargh -> aargh)
    - Reduce excessive punctuation (!!! -> !, ??? -> ?)
    - Strip standalone screaming sounds (ahhh, nooo, etc.)
    """
    if not text:
        return text

    # 1. Collapse 3+ repeated letters
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)

    # 2. Strip standalone screaming sounds (words that are just repeated vowels/consonants)
    text = re.sub(r"\b[aAeEoOuU]{3,}[hHrRgG]*\b", "", text)  # ahhh, ooooh, argh
    text = re.sub(r"\b[nN][oO]{2,}\b", "no", text)  # nooo -> no

    # 3. Reduce excessive punctuation
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\?{2,}", "?", text)
    text = re.sub(r"\.{4,}", "...", text)

    # 4. Convert to lowercase
    text = text.lower()

    # 5. Capitalise first letter of each sentence
    def cap_first(match):
        return match.group(0).upper()
    text = re.sub(r"(?:^|(?<=[.!?]\s))([a-z])", cap_first, text)
    # Ensure very first character is capitalised
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # 6. Restore F1 acronyms
    for acr in _F1_ACRONYMS:
        text = re.sub(r"\b" + acr + r"\b", acr.upper(), text, flags=re.IGNORECASE)

    # 6b. Restore proper nouns (driver names, teams, cities, etc.)
    for noun in _F1_PROPER_NOUNS:
        text = re.sub(r"\b" + re.escape(noun.lower()) + r"\b", noun, text)

    # 7. Restore position labels (p1 -> P1, p20 -> P20)
    text = _POSITION_PATTERN.sub(lambda m: f"P{m.group(1)}", text)

    # 8. Clean up whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text


# Escalation words that make video models generate screaming audio
_ESCALATION_PATTERNS = [
    (r'\bbuilding to crescendo\b', 'speaking with measured enthusiasm'),
    (r'\bincreasing intensity\b', 'steady measured delivery'),
    (r'\bwild hand gestures\b', 'subtle hand gestures'),
    (r'\bwild gestures\b', 'subtle gestures'),
    (r'\bdramatically\b', 'expressively'),
    (r'\bfrantic(ally)?\b', 'animated'),
    (r'\bexplosive\b', 'energetic'),
    (r'\bscreaming\b', 'speaking emphatically'),
    (r'\bshouting\b', 'speaking firmly'),
    (r'\byelling\b', 'speaking firmly'),
    (r'\bincreasing intensity of expression\b', 'measured expressive delivery'),
    (r'\bbuilding to\b', 'delivering with'),
    (r'\bcrescendo\b', 'emphasis'),
    (r'\bwild\b', 'animated'),
]


def sanitize_video_prompt(text: str) -> str:
    """Remove escalation language from video prompts.

    Video models generate audio from these prompts. Words like "crescendo",
    "wild", "dramatically" make the generated audio sound like screaming.
    Replace with calm professional alternatives.
    """
    if not text:
        return text
    for pattern, replacement in _ESCALATION_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


SCRIPT_SYSTEM_PROMPT = """You are the head writer and showrunner of a hilarious animated F1 satirical show — think South Park meets Drive to Survive. Your show is the funniest thing on YouTube.

COMEDY IS YOUR #1 PRIORITY. Every scene must land a joke, a visual gag, or a comedic moment. If a scene isn't funny, rewrite it until it is.

Your style:
- Sharp, witty, SAVAGE humor with deep F1 insider knowledge
- Exaggerated caricature comedy — oversized heads, dramatic expressions, physical comedy
- Real F1 events twisted into absurd satirical gold
- Running gags that build across episodes (callbacks are comedy gold)
- Pop culture references, memes, and internet F1 culture (DTS memes, r/formuladank energy)
- Each character has a comedic angle — EXPLOIT IT MERCILESSLY

SATIRICAL COMEDY RULES (THIS IS WHAT MAKES THE SHOW):
- Every character has a comedic weakness — ATTACK IT. Gentle ribbing is boring. Go for the jugular.
- Lance Stroll's billionaire daddy buying him everything. "Lawrence Stroll didn't buy Aston Martin for Lance — he bought Lance an entire F1 team as a participation trophy."
- Lewis Hamilton's bizarre fashion choices. He shows up to pressers dressed like a Met Gala reject. Reference specific outfits — the ski goggles, the kilt, the full leather Matrix look.
- Max Verstappen's sim racing addiction. He'd rather be on iRacing than talking to his team. "Max won the race and immediately asked if there was WiFi on the podium."
- Toto Wolff smashing tables and headsets. His anger management issues ARE the joke.
- Christian Horner's smugness and the tabloid drama. He's the pantomime villain.
- Fernando Alonso being ancient but refusing to retire. "Fernando has been racing since before some of these drivers were BORN. Literally."
- Guenther Steiner's profanity (even though he's no longer at Haas, reference his legacy). "Haas is so used to being foksmashed they put it on the car."
- Carlos Sainz being the eternal nearly-man, always second choice
- Lando Norris trying too hard to be the meme lord of F1
- George Russell being the Head Boy prefect of F1 — always politically correct, always diplomatic, always boring

DRIVER PERSONALITY COMEDY (make each driver DISTINCTIVE and self-absorbed):
- Lewis Hamilton: Self-absorbed fashion icon. Every comment circles back to himself or
  his legacy. "This reminds me of when I won my seventh championship..." even when
  irrelevant. References his own greatness as if stating facts. Fashion choices are so
  extreme they become the punchline.
- George Russell: Corporate Head Boy prefect. Speaks in press releases. Uses "we" when
  he means "I". His earnestness is accidentally hilarious. Would chair a meeting about
  a meeting. References data and PowerPoint presentations unironically.
- Max Verstappen: Deadpan brutal honesty. Says what everyone is thinking with zero
  diplomacy. Never uses exclamation marks. His comedy is pure understatement.
  "The car is not good" while 30 seconds behind. Treats domination as routine.
- Charles Leclerc: Dramatic Ferrari passion. Everything is either the end of the world
  or the greatest moment of his life. No middle ground. Piano-playing romantic trapped
  in a racing car. Monegasque melodrama.
- Kimi Antonelli: Gen-Z teenager energy contrasted with F1 veteran surroundings.
  Accidentally disrespectful to legends because he simply doesn't know the history.
  "Who's Schumacher?" References TikTok and gaming naturally.
- Oscar Piastri: Australian deadpan. Impossibly calm about everything. Makes Verstappen
  look emotional. "Yeah. P2. Could've been P1. Anyway."
- Fernando Alonso: Ancient warrior who refuses to accept time exists. References events
  from 2005 as if they were yesterday. "Back in my day" energy but still racing.
- Lance Stroll: Billionaire's kid who genuinely doesn't understand why people question
  his talent. Oblivious to the irony of everything.

CHARACTERS MUST TAKE JABS AT EACH OTHER:
- At least 3 scenes per episode MUST have one character insulting or mocking another
- Jabs should target REAL weaknesses (fashion, results, team drama, age, wealth)
- Brundle is the king of backhanded compliments — "That was a brave strategy"
- Verstappen says the quiet part out loud — "Your car is slow. Mine is also slow."
- Hamilton deflects criticism by referencing his own achievements
- Russell defends himself with corporate speak that makes the insult worse
- Drivers should be petty, competitive, and hilariously self-centred

JOKE DENSITY TARGET:
- MINIMUM 2 jokes per scene. One in dialogue, one in the visual/action description.
- Puns, wordplay, double entendres, callbacks, deadpan delivery, absurd escalation
- If a scene has zero laughs, it FAILS. Rewrite it.

COMEDY TECHNIQUES (use ALL of these across the episode):
1. CALLBACK JOKES: Set up something in scenes 2-5, pay it off in scenes 16-21.
   The audience feels smart for remembering.
2. RULE OF THREE: Two normal examples, third one absurd.
   "Ferrari strategy: Plan A failed, Plan B failed, Plan C was just Plan A written in Italian."
3. DEADPAN + ABSURD: State something insane as if it is perfectly normal.
   "Max won by 30 seconds. He was reportedly disappointed it was not 40."
4. DRIVER-VS-DRIVER JABS: Characters MUST insult each other TO THEIR FACE or behind
   their back. Not gentle ribbing — sharp, witty burns that hit real weak spots.
   "Lewis showed up to the paddock dressed as a lampshade. Charles said he finally
   matched his qualifying pace — decorative but dim."
5. COMMENTATOR REACTIONS: Croft losing his mind while Brundle stays deadpan is
   comedy gold. Brundle's calm "Right..." after Croft screams is a guaranteed laugh.
6. SELF-DEPRECATION: Characters accidentally roasting themselves without realizing.
   Lance Stroll: "My dad did not buy me this seat... he bought the whole team.
   The seat was free."
7. RUNNING GAG ESCALATION: Each callback should ESCALATE the gag, not just repeat it.
   If a gag started as a quip, by scene 20 it should be an absurd callback.
8. BREAKING NEWS FORMAT: Mock-serious delivery of absurd "breaking news" adds variety.
   "Breaking: FIA confirms the white line IS in fact part of the track. More at 11."
9. UNCOMFORTABLE TRUTHS: Characters saying what everyone is thinking but nobody says.
   This is where the best satire lives — saying the quiet part out loud.
10. TEAM RADIO PARODIES: Exaggerate real team radio messages to absurd levels.
    Engineer: "We are checking." Driver: "You have been checking since lap 1."
    Engineer: "We are checking the checking."

DIALOGUE TONE RULES (CRITICAL — characters must NOT all sound the same):
- Characters should NOT scream or shout constantly. Reserve CAPS and exclamation marks for genuinely dramatic moments only.
- David Croft builds to crescendos — he starts measured and EXPLODES at the key moment, not 100% volume throughout.
- Max Verstappen is deadpan. NEVER give him exclamation marks. His comedy is in understatement.
- Most characters speak conversationally. The comedy comes from WHAT they say, not volume.
- Dry, deadpan delivery is often funnier than shouting. Let the absurdity speak for itself.
- Maximum 3 scenes per episode may have exclamation-heavy dialogue. The rest MUST be conversational.

COMMENTATOR PAIRING (Sky F1 style — USE BOTH in every episode):
- David Croft is the excitable play-by-play voice — he calls the action with energy
- Martin Brundle is the dry, analytical expert — he provides calm color commentary
- USE BOTH as main characters in every episode. They are the show's anchors.
- Croft gets the high-energy ACTION_REPLAY voiceovers and big-moment calls
- Brundle gets TALKING_HEAD analysis scenes and provides dry, witty counterpoints
- Brundle's comedy style: dry British understatement, backhanded compliments,
  grid walk celebrity interruptions, "Anyway..." transitions, telling drivers
  uncomfortable truths to their face with a polite smile
- If the episode has 3+ ACTION_REPLAY scenes, at least 1 MUST use martin_brundle
  as voiceover_character — his calm, wry commentary contrasts beautifully with Croft
- Classic Brundle lines to channel: "That's a brave strategy", "He's not going to
  be happy about that", "I've seen this before and it doesn't end well"

VIDEO PROMPT TONE RULES (CRITICAL — video models generate audio from these prompts):
- video_prompt describes PHYSICAL MOTION only — camera moves, body positions, subtle gestures
- NEVER use escalation words: "crescendo", "dramatically", "wild", "intensity", "explosive", "frantic", "screaming"
- NEVER use "building to" or "increasing" — these make the video model escalate volume
- For animated commentators: "speaking with measured enthusiasm, subtle hand gestures, professional delivery"
- For excited celebrations: "smiling broadly, fist pump, controlled enthusiasm" — NOT "screaming with joy"
- The video model generates audio from these prompts. Escalation language = screaming audio. Keep it calm.
- Even David Croft should be "animated and engaged" not "building to crescendo with wild gestures"
- Check each character's humor_style from their personality data:
  "deadpan_blunt" = no exclamation marks, dry wit
  "enthusiastic_hyperbole" = some exclamations allowed, but still builds to them
  "sardonic" = eyeroll humor, backhanded compliments
  "earnest_naive" = genuine confusion that's accidentally funny
- If you cannot tell WHO is speaking from the dialogue alone (without seeing the character name), rewrite it.
- The best jokes reference REAL F1 incidents, memes, and controversies
- Don't be afraid to be mean — this is satire, not a PR press release
- Reference r/formuladank memes: "s🅱️inalla", "Bwoah", "For What?!", "Slow Button On", "El Plan", "Master Plan"
- Break the fourth wall occasionally — characters can reference being in a show
- Team radio parodies are GOLD — exaggerate real radio messages to absurd levels

F1 CAR AND DRIVER APPEARANCE RULES (CRITICAL):
- F1 cars are OPEN-COCKPIT single-seaters with NO ROOF, NO CANOPY, NO WINDSHIELD.
  The halo is a thin curved bar above the cockpit, NOT a canopy or roof.
- Maximum 22 cars on the F1 grid (11 teams, 2 cars each). NEVER describe more.
- Establishing shots with cars: show 3-5 cars maximum, not "dozens" or "hundreds".
- DRIVERS ALWAYS wear RACING OVERALLS (one-piece fireproof race suit with team colours
  and sponsor logos). NEVER a business suit, blazer, jacket, formal wear, or casual
  clothes. "Race suit" = RACING OVERALLS, not a business suit. Be explicit: write
  "team-coloured racing overalls" or "fireproof racing suit with [team] logos".
- TEAM PRINCIPALS wear team-branded polo shirts or smart casual. Never racing overalls.
- PUNDITS/COMMENTATORS wear broadcaster uniforms (Sky Sports polo, headset).

SCENE TYPES — USE A MIX (this is critical for visual variety):
You MUST use a mix of these scene types throughout the episode. NOT just talking heads!

1. TITLE_CARD (Scene 1 always): Dramatic establishing shot of the circuit with episode title. No character face needed. Wide aerial or iconic circuit view with dramatic lighting. The dialogue is the episode tagline.

2. TALKING_HEAD: Single character speaking to camera or in interview style. Use for commentary, hot takes, reactions.

3. TWO_SHOT: Two characters in the same frame — arguing, reacting, interviewing. Great for pundit-to-pundit or pundit-interviewing-driver scenes.
   CRITICAL COMPOSITION: The SPEAKING character must be DOMINANT in the foreground (larger, facing camera). The LISTENING character must be smaller in the background, slightly out of focus. NEVER have both characters at equal size side-by-side — this causes frozen animation. One character is always the focus.
   start_frame_prompt MUST describe: "[Speaker name] prominent in the foreground, [other character] visible in the background".
   video_prompt MUST describe PHYSICAL ACTIONS: "leans forward, gestures with hand, turns head" — NOT abstract moods like "mischievous energy" or "natural conversation flow".

4. OVER_THE_SHOULDER: Shot from behind one character's shoulder, showing the other character facing camera. Creates conversational flow.
   CRITICAL COMPOSITION: The foreground character's SHOULDER and BACK OF HEAD must be visible and blurred. The background character FACES the camera and is the focus. start_frame_prompt MUST describe: "Shot from behind [Character A]'s shoulder, [Character A]'s back/shoulder visible in foreground out of focus, [Character B] facing camera in the background".
   video_prompt MUST describe PHYSICAL ACTIONS: "speaks while gesturing, head tilts, eyebrow raises" — NOT abstract moods.

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


CHARACTER CAST STRUCTURE (main cast + cameos):
- 3-4 MAIN CHARACTERS: Appear in 5-8 scenes each, have full arcs
  - At least 1 commentator/pundit as host/anchor (they frame and react to the story)
  - At least 2 DRIVERS or TEAM PRINCIPALS (they ARE the story)
  - Characters REACT to each other — show consequences, not just monologues
- 2-3 CAMEO CHARACTERS: Appear in 1-2 scenes only for a quick jab, reaction, or burn
  - Perfect for: podium scenes, reaction shots, one-liner insults, team radio parodies
  - Cameos are comedy grenades — they show up, drop a bomb, and leave
  - A cameo driver roasting a main character in a REACTION scene is chef's kiss
  - Cameos still need character_appearances entries!
- Total: 6-7 characters per episode (main + cameos combined)
- For ACTION_REPLAY scenes, use one of the pundits as voiceover_character

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

SCENE DURATION TIMING:
Every scene has a target_duration (integer seconds). Match duration to content:
- Quick reaction, zinger, or beat: 3-4 seconds
- Standard dialogue (1-2 sentences): 5-6 seconds
- Complex exchange, detailed action, or multi-character scene: 7-10 seconds
- Title card: 5 seconds
- Outro: 6-8 seconds
Shorter is funnier — a 3-word punchline should NOT get 5 seconds of dead air.

POST-QUALIFYING EPISODE STRUCTURE (when episode_type is "post-qualifying"):
- Focus on qualifying drama: surprise pole positions, Q1 knockouts, red flags
- Emphasize the GAPS — who was surprisingly fast/slow and why
- Predictions for the race based on grid positions (comedic, exaggerated)
- Mock "grid penalty" drama and FIA steward decisions
- Team radio gold from qualifying: "We need to go again" "Box box box"
- The title card should reference qualifying specifically
- Main drama: who got pole, who got knocked out in Q1/Q2, any crashes
- Outro should tease the RACE (same circuit, next day) with predictions

RUNNING GAGS ARE MANDATORY:
- If running gags are provided, you MUST use at least 3 of them
- Weave them in naturally — they should feel like inside jokes the audience is in on
- Visual gags > verbal gags

ACTION_REPLAY SCENE RULES:
- ABSOLUTE DIRECTION RULE — THIS IS THE #1 RULE FOR ALL CAR SCENES:
  The camera is positioned BEHIND the cars. You are watching them drive AWAY from you.
  You can ONLY describe what you see from BEHIND: rear wings, rear diffusers, exhaust
  pipes, rear tyres, rear lights, the back of the driver's helmet.
  You CANNOT see front wings, nose cones, or the front of any car.
  EVERY start_frame_prompt for a car scene MUST include the phrase:
  "ALL cars driving away from camera showing REAR wings and rear diffusers"
  NEVER use words like "diving inside", "lunging", "approaching", "heading toward" —
  these imply the camera sees the FRONT of the car, which is WRONG.
  Instead use: "pulling alongside from behind", "closing gap to car ahead",
  "slipstreaming behind", "chasing down", "rear view of cars battling"
- F1 CARS HAVE NO ROOF: Every car description MUST include "open-cockpit" and
  "with halo device". F1 cars have NO roof, NO canopy, NO windshield. The driver's
  helmet is exposed to open air. The halo is a thin titanium bar, not a roof.
- For on-board/cockpit POV shots: describe looking FORWARD through the halo. Cars
  ahead are driving AWAY — you only see their REAR wings and rear diffusers.
- For overtake scenes: describe from BEHIND — "car pulls alongside rival, both
  driving away from camera, rear wings side by side through the corner"
- For crash/incident scenes: describe the impact, debris, gravel trap, safety car
- The character field should be the COMMENTATOR who provides voiceover
- Dialogue is the commentary: "and Verstappen goes around the outside!"
- NEVER USE ALL CAPS in dialogue — it causes TTS screaming. Use sentence case only.
- These scenes do NOT need character_appearances clothing — they show CARS and HELMETS

ESTABLISHING / TITLE_CARD SCENE RULES:
- If any cars are visible, they MUST be driving AWAY from camera (rear view only)
- Focus on ENVIRONMENT — circuit, skyline, paddock, fans, cherry blossoms, sunset
- Show at most 3-5 cars in background, NOT a full grid
- Cars are secondary to the atmosphere and setting

For each scene, provide FULL cinematographic direction:

start_frame_prompt must include:
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

video_prompt must include ALL of the following (the video model needs full context, not just motion):
- FULL scene description matching start_frame_prompt — setting, location, characters, cars, lighting, atmosphere
- Camera movement matching camera_direction
- Character motion: gestures, expressions changing, body language (for character scenes)
- Racing action: car movements, overtakes, speed, tyre smoke, sparks (for ACTION_REPLAY)
- Background motion: screens updating, people moving, flags waving, clouds drifting, crowd reacting
- NEVER include style keywords like "ANTKF1STYLE" — the video generator does not use LoRA
- The video prompt must be at LEAST as detailed as the start_frame_prompt — if the start frame describes a "black and silver Mercedes W17 with Petronas teal accents at Suzuka", the video prompt must include those same details PLUS the motion

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
  "title": "Suzuka Qualifying: The Teenager Strikes Again",
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
      "end_frame_prompt": null,
      "camera_direction": "Camera movement",
      "video_prompt": "Motion and animation instructions",
      "target_duration": 5
    }
  ],
  "gags_used": ["gag_title_1", "gag_title_2"]
}
```

FINAL RULES:
- Output valid JSON ONLY — no markdown, no commentary
- Exactly 26 scenes
- title MUST follow this format: "{Circuit/City} {Session}: {Catchy Subtitle}"
  - Examples: "Suzuka Qualifying: The Teenager Strikes Again", "Shanghai Sprint: Russell's Surprise", "Melbourne Race: When Mercedes Remembered How to Race"
  - The circuit/city name MUST appear in the title
  - The session type (Qualifying, Race, Sprint) MUST appear in the title
  - The subtitle should reference the episode's main storyline or biggest moment
- Dialogue max 15 words per scene
- target_duration: estimated seconds per scene (3-10). Short reactions/zingers: 3-4s. Standard dialogue: 5-6s. Complex exchanges or action scenes: 7-10s. Title card: 5s. Outro: 6-8s.
- character field = the person whose FACE is visible (null if no face shown)
- voiceover_character field = the person narrating when face is not shown (null if visible character is speaking)
- face_visible field MUST be true or false for every scene
- scene_type field MUST be one of: TITLE_CARD, TALKING_HEAD, TWO_SHOT, OVER_THE_SHOULDER, ACTION_REPLAY, PODIUM, ESTABLISHING, REACTION
- Scene 1 MUST be TITLE_CARD, Scene 26 MUST be an outro
- At least 3 ACTION_REPLAY scenes required
- At least 2 TWO_SHOT or OVER_THE_SHOULDER scenes required
- character_appearances MUST have an entry for EVERY character (main + cameos)
- EVERY character scene's prompts must use their exact outfit from character_appearances
- 6-7 total characters (3-4 main + 2-3 cameos). Cameos appear in only 1-2 scenes.
- martin_brundle AND david_croft must BOTH appear in every episode
- VARIETY RULE — DO NOT use the same pundit lineup every episode:
  Available pundits: david_croft, martin_brundle, jenson_button, ted_kravitz,
  karun_chandhok, natalie_pinkham, nico_rosberg, simon_lazenby, stefano_domenicali.
  Each episode MUST include at least ONE pundit who is NOT Croft or Brundle.
  Rotate through Button, Kravitz, Chandhok, Pinkham, Rosberg, Lazenby across episodes.
- TEAM PRINCIPALS ADD DRAMA — include at least 1 team principal per episode:
  Available: toto_wolff, christian_horner, fred_vasseur, andrea_stella, james_vowles,
  ayao_komatsu, oliver_oakes, graeme_lowdon, jonathan_wheatley, andy_cowell.
  Team principals are comedy gold — they react to their drivers' performances,
  blame strategy, smash tables (Toto), scheme (Horner), or deliver dry burns (Vasseur).
  Use the team principal whose team is MOST relevant to the episode's story.
- end_frame_prompt: ONLY generate for ACTION_REPLAY scenes (describes how the racing
  action ends — final car positions, aftermath). Set to null for ALL other scene types.
  Non-ACTION_REPLAY scenes do not use end frames.
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
        storylines: Optional[List[dict]] = None,
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
            teams=teams, storylines=storylines,
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

            # Build scene list — only ACTION_REPLAY gets end_frame_prompt
            scenes = []
            for s in script_data["scenes"]:
                scene_type = s.get("scene_type", "TALKING_HEAD")
                # Only ACTION_REPLAY uses FLF end frames — clear for all others
                efp = s.get("end_frame_prompt") if scene_type.upper() == "ACTION_REPLAY" else None
                scenes.append(SceneScript(
                    scene_number=s["scene_number"],
                    character=s["character"],
                    dialogue=s.get("dialogue"),
                    audio_description=s.get("audio_description"),
                    start_frame_prompt=s.get("start_frame_prompt", ""),
                    end_frame_prompt=efp or None,
                    camera_direction=s.get("camera_direction", ""),
                    video_prompt=s.get("video_prompt", ""),
                    scene_type=scene_type,
                    face_visible=s.get("face_visible", True),
                    voiceover_character=s.get("voiceover_character"),
                    action=s.get("action"),  # backward compat
                    target_duration=s.get("target_duration"),
                ))

            # Sanitize prompts to enforce direction and car count rules
            scenes = [sanitize_scene_prompts(s) for s in scenes]

            if len(scenes) != 26:
                logger.warning(f"Expected 26 scenes, got {len(scenes)}")
                if len(scenes) < 20 or len(scenes) > 30:
                    raise ScriptGenerationError(
                        f"Script has {len(scenes)} scenes (expected 26). "
                        "LLM output is too far from target."
                    )

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
        storylines: Optional[List[dict]] = None,
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

            # Rich character data for better comedy writing
            satirical_angle = p.get("satirical_angle", "")
            comedy_archetype = p.get("comedy_archetype", "")
            humor_style = p.get("humor_style", "")
            blind_spots = p.get("blind_spots", [])
            meme_status = p.get("meme_status", "")
            personality_dims = p.get("personality_dimensions", {})
            example_dialogue = p.get("example_dialogue", {})
            signature_reactions = p.get("signature_reactions", {})
            relationships = p.get("relationships_summary", {})
            storyline_hooks = p.get("storyline_hooks", [])

            line = f"- {name} ({nationality}, {team})"
            if role:
                line += f" [{role}]"
            if satirical_angle:
                line += f"\n  SATIRICAL ANGLE: {satirical_angle}"
            if comedy_archetype:
                line += f"\n  COMEDY ARCHETYPE: {comedy_archetype}"
            if core_traits:
                line += f"\n  Traits: {', '.join(core_traits[:5])}"
            if comedy_weaknesses:
                line += f"\n  Comedy weaknesses: {', '.join(comedy_weaknesses[:5])}"
            if accent_hints:
                line += f"\n  Accent/speech: {accent_hints}"
            if tone:
                line += f"\n  Tone: {tone}"
            if humor_style:
                line += f"\n  Humor style: {humor_style}"
            if catchphrases:
                line += f"\n  Catchphrases: {', '.join(repr(cp) for cp in catchphrases[:5])}"
            if personality_dims:
                dims = [f"{k}={v}" for k, v in personality_dims.items()]
                line += f"\n  Personality scores: {', '.join(dims)}"
            if blind_spots:
                line += f"\n  Blind spots: {', '.join(blind_spots[:3])}"
            if meme_status:
                line += f"\n  Fan meme culture: {meme_status[:150]}"
            if example_dialogue:
                dial_examples = []
                for situation, text in list(example_dialogue.items())[:3]:
                    dial_examples.append(f"{situation}: \"{text[:100]}\"")
                line += f"\n  EXAMPLE DIALOGUE (use as tone reference):\n    " + "\n    ".join(dial_examples)
            if signature_reactions:
                react_examples = []
                for situation, reaction in list(signature_reactions.items())[:3]:
                    react_examples.append(f"{situation}: {reaction[:100]}")
                line += f"\n  SIGNATURE REACTIONS:\n    " + "\n    ".join(react_examples)
            if relationships:
                rivals = relationships.get("rivals", [])
                friendly = relationships.get("friendly_with", [])
                if rivals:
                    line += f"\n  Rivals: {', '.join(rivals[:3])}"
                if friendly:
                    line += f"\n  Friendly with: {', '.join(friendly[:3])}"
            if physical:
                line += f"\n  Physical: {physical}"
            if storyline_hooks:
                line += f"\n  Story hooks: {'; '.join(storyline_hooks[:2])}"
            
            char_lines.append(line)
        
        character_info = "\n".join(char_lines)

        if episode_type == "pre-race":
            type_context = "Preview and predictions for the upcoming race"
        elif episode_type == "post-qualifying":
            type_context = (
                "Post-qualifying analysis: grid positions, surprise performances, "
                "Q1/Q2 knockouts, pole position drama, and race predictions"
            )
        elif episode_type == "post-sprint":
            type_context = "Post-sprint race analysis: sprint results, mini-race drama, and main race predictions"
        else:
            type_context = "Post-race analysis and commentary"

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

        # Add active storylines for narrative continuity
        if storylines:
            storyline_lines = []
            for sl in storylines:
                line = f"- {sl['title']} ({sl['type']}): {sl['description']}"
                if sl.get('comedy_notes'):
                    line += f"\n  Comedy direction: {sl['comedy_notes']}"
                if sl.get('plot_points'):
                    beats = sl['plot_points']
                    current = sl.get('current_beat', 0)
                    if current < len(beats):
                        line += f"\n  Current beat: {beats[current]}"
                    if current + 1 < len(beats):
                        line += f"\n  Next beat: {beats[current + 1]}"
                storyline_lines.append(line)
            storylines_block = (
                "\nACTIVE STORYLINES (weave these into the episode naturally — "
                "advance the plot, reference previous beats, build continuity):\n"
                + "\n".join(storyline_lines)
            )
            prompt_parts.append(storylines_block)

        # Team livery reference for prompt injection
        if teams:
            team_lines = []
            for t in teams:
                if t.get("car_description"):
                    team_lines.append(f"- {t['short_name']}: {t['car_description']}")
            # Build overalls reference for character appearance consistency
            overalls_lines = []
            for t in teams:
                if t.get("overalls_description"):
                    overalls_lines.append(f"- {t['short_name']} drivers: {t['overalls_description']}")

            if team_lines:
                team_livery_block = f"""\n
TEAM LIVERY REFERENCE (use these EXACT descriptions when showing cars on track):
{chr(10).join(team_lines)}

ACTION_REPLAY RULES:
- When describing a car on track, use the team's car_description from above VERBATIM
- When two cars are racing, describe BOTH cars with their correct liveries
- Cars MUST be driving AWAY from camera showing REAR wings and rear diffusers
- Include dynamic motion seen from BEHIND the cars: "closing the gap to the car ahead",
  "pulling alongside from behind showing both rear wings", "slipstreaming on the main straight",
  "wheel-to-wheel through the corner, both cars driving away from camera"
- The video_prompt MUST describe motion: "car accelerating", "overtaking maneuver",
  "crossing the finish line at speed", "braking hard into the corner"
- TRACK LAYOUT: The race track has tarmac in the centre with kerbs (red-white or yellow) on BOTH EDGES only.
  There is NEVER a kerb, barrier, or divider in the middle of the track. The track is one continuous surface.
  Cars race side by side on the same piece of tarmac, not in separate lanes.
- GRID SIZE: There are exactly 22 cars on the F1 grid (11 teams, 2 drivers each). Never describe more than 22 cars on track.
- CAR DESIGN: F1 cars are open-cockpit single-seaters with NO roof. The halo is a thin curved bar, NOT a canopy.
"""
                if overalls_lines:
                    team_livery_block += f"""
DRIVER OUTFIT REFERENCE (use VERBATIM in character_appearances for drivers):
{chr(10).join(overalls_lines)}
"""
                team_livery_block += """
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
            "Each scene needs start_frame_prompt, camera_direction, and video_prompt. "
            "Only ACTION_REPLAY scenes need end_frame_prompt (set null for all others). "
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
        """Format running gags into prompt context with freshness indicators."""
        lines = [
            "RUNNING GAGS — Pick 3-5 that fit the episode naturally. "
            "PRIORITIZE gags tagged [FRESH] over familiar ones. "
            "Do NOT use every gag — less is more. "
            "Find a NEW ANGLE for gags tagged [FAMILIAR] or [OVERUSED]:"
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
            freshness = gag.get("freshness", "")

            # Freshness tag
            tag = ""
            if freshness == "FRESH":
                tag = " [FRESH — never used, great opportunity!]"
            elif freshness.startswith("OVERUSED"):
                tag = f" [OVERUSED — {times_used}x, must find completely new angle or SKIP]"
            elif freshness.startswith("FAMILIAR"):
                tag = f" [FAMILIAR — {times_used}x, twist it or skip]"

            entry = f"- \"{title}\"{tag}"
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
