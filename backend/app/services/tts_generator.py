"""Text-to-Speech generator using Edge TTS for character dialogue.

Maps F1 character nationalities and voice descriptions to Microsoft
Edge TTS neural voices for distinct, recognizable character voices.
"""

import asyncio
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import edge_tts

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Result of TTS generation."""

    audio_path: str
    duration_seconds: float
    generation_time_ms: int
    voice_used: str
    text: str


# Voice mapping by nationality → Edge TTS voice name.
# Each character gets a distinct voice for recognizability.
# All voices speak English; nationality determines accent flavor.
VOICE_MAP: dict[str, str] = {
    # British male voices (commentators, principals)
    "british_male_1": "en-GB-RyanNeural",       # Deep, authoritative (Crofty, Brundle)
    "british_male_2": "en-GB-ThomasNeural",      # Lighter, analytical (Ted, Karun)
    "british_female_1": "en-GB-SoniaNeural",     # Professional (Natalie)
    "british_female_2": "en-GB-LibbyNeural",     # Younger
    # European accented English
    "dutch_male": "en-GB-RyanNeural",            # Dutch characters in English
    "german_male": "de-AT-JonasNeural",          # Austrian/German accent
    "french_male": "fr-FR-HenriNeural",          # French accent
    "spanish_male": "es-ES-AlvaroNeural",        # Spanish accent
    "italian_male": "it-IT-DiegoNeural",         # Italian accent (Leclerc via Monaco/French)
    "finnish_male": "fi-FI-HarriNeural",         # Finnish accent
    "australian_male": "en-AU-WilliamNeural",    # Australian accent
    "japanese_male": "en-US-GuyNeural",          # Neutral for Japanese characters
    "thai_male": "en-US-GuyNeural",              # Neutral fallback
    "brazilian_male": "pt-BR-AntonioNeural",     # Brazilian accent
    "mexican_male": "es-MX-JorgeNeural",         # Mexican accent
    # Fallbacks
    "default_male": "en-GB-RyanNeural",
    "default_female": "en-GB-SoniaNeural",
}

# Character-specific voice assignments for recognizability.
# Key = character slug (matches personality JSON id / character.name).
CHARACTER_VOICE_MAP: dict[str, str] = {
    # Pundits / Commentators
    "david_croft": "en-GB-RyanNeural",          # Loud, excitable British
    "martin_brundle": "en-GB-ThomasNeural",      # Measured, analytical British
    "ted_kravitz": "en-GB-RyanNeural",           # Enthusiastic British
    "karun_chandhok": "en-GB-ThomasNeural",      # Technical, calm
    "simon_lazenby": "en-GB-ThomasNeural",       # Anchor voice
    "natalie_pinkham": "en-GB-SoniaNeural",      # Professional female
    "jenson_button": "en-GB-RyanNeural",         # Smooth British
    "nico_rosberg": "de-AT-JonasNeural",         # German accent
    "stefano_domenicali": "it-IT-DiegoNeural",   # Italian accent
    # Drivers
    "max_verstappen": "en-GB-RyanNeural",        # Dutch but speaks English
    "lewis_hamilton": "en-GB-ThomasNeural",       # British, smooth
    "charles_leclerc": "fr-FR-HenriNeural",      # Monégasque/French accent
    "carlos_sainz": "es-ES-AlvaroNeural",        # Spanish accent
    "lando_norris": "en-GB-RyanNeural",          # British, casual
    "oscar_piastri": "en-AU-WilliamNeural",      # Australian
    "george_russell": "en-GB-ThomasNeural",      # British, polished
    "fernando_alonso": "es-ES-AlvaroNeural",     # Spanish accent
    "pierre_gasly": "fr-FR-HenriNeural",         # French accent
    "esteban_ocon": "fr-FR-HenriNeural",         # French accent
    "alex_albon": "en-GB-ThomasNeural",          # Thai-British
    "lance_stroll": "en-US-GuyNeural",           # Canadian
    "nico_hulkenberg": "de-AT-JonasNeural",      # German accent
    "valtteri_bottas": "fi-FI-HarriNeural",      # Finnish accent
    "sergio_perez": "es-MX-JorgeNeural",         # Mexican accent
    "liam_lawson": "en-AU-WilliamNeural",        # New Zealand ≈ Australian
    "franco_colapinto": "es-ES-AlvaroNeural",    # Argentine ≈ Spanish
    "oliver_bearman": "en-GB-RyanNeural",        # British
    "kimi_antonelli": "it-IT-DiegoNeural",       # Italian
    "gabriel_bortoleto": "pt-BR-AntonioNeural",  # Brazilian
    "isack_hadjar": "fr-FR-HenriNeural",         # French-Algerian
    "arvid_lindblad": "en-GB-RyanNeural",        # British
    # Team Principals
    "christian_horner": "en-GB-RyanNeural",      # British, confident
    "toto_wolff": "de-AT-JonasNeural",           # Austrian accent
    "fred_vasseur": "fr-FR-HenriNeural",         # French accent
    "andrea_stella": "it-IT-DiegoNeural",        # Italian accent
    "james_vowles": "en-GB-ThomasNeural",        # British, measured
    "ayao_komatsu": "en-GB-ThomasNeural",        # Japanese but in English
    "oliver_oakes": "en-GB-RyanNeural",          # British
    "laurent_mekies": "fr-FR-HenriNeural",       # French accent
    "andy_cowell": "en-GB-ThomasNeural",         # British, technical
    "graeme_lowdon": "en-GB-RyanNeural",         # British
    "jonathan_wheatley": "en-GB-ThomasNeural",   # British
}

# Rate adjustments per character for personality flavor.
# Edge TTS rate: "+0%" is normal, "+20%" is faster, "-10%" is slower.
CHARACTER_RATE_MAP: dict[str, str] = {
    "david_croft": "+15%",       # Fast, excitable
    "max_verstappen": "-5%",     # Measured, slightly bored
    "fernando_alonso": "-10%",   # Slow, deliberate
    "toto_wolff": "-5%",         # Measured, intense
    "valtteri_bottas": "-10%",   # Dry, slow delivery
    "kimi_antonelli": "+5%",     # Young, eager
}

DEFAULT_VOICE = "en-GB-RyanNeural"
DEFAULT_RATE = "+0%"
DEFAULT_VOLUME = "+0%"


class TTSGenerator:
    """Generate speech audio for scene dialogue using Edge TTS."""

    def __init__(
        self,
        output_dir: str = "/tmp/f1-audio",
        default_voice: str = DEFAULT_VOICE,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.default_voice = default_voice

    def _resolve_voice(self, character_name: Optional[str]) -> str:
        """Resolve character name to Edge TTS voice."""
        if not character_name:
            return self.default_voice

        # Normalize: "Max Verstappen" -> "max_verstappen"
        slug = character_name.lower().replace(" ", "_").replace("-", "_")

        if slug in CHARACTER_VOICE_MAP:
            return CHARACTER_VOICE_MAP[slug]

        return self.default_voice

    def _resolve_rate(self, character_name: Optional[str]) -> str:
        """Resolve character-specific speech rate."""
        if not character_name:
            return DEFAULT_RATE

        slug = character_name.lower().replace(" ", "_").replace("-", "_")
        return CHARACTER_RATE_MAP.get(slug, DEFAULT_RATE)

    @staticmethod
    def _normalize_for_tts(text: str) -> str:
        """Normalize dialogue text for Edge TTS.

        Edge TTS treats ALL-CAPS words (2+ letters) as acronyms and
        spells them letter-by-letter. Convert to sentence case while
        preserving real acronyms (F1, DRS, FIA, etc.).
        """

        import re as _re
        # Defense-in-depth: collapse capitals and screaming before TTS
        # ANY capitals make Edge TTS scream
        text = _re.sub(r"(.)\1{2,}", r"\1\1", text)  # collapse repeated letters
        text = _re.sub(r"!{2,}", "!", text)  # reduce punctuation
        text = _re.sub(r"\?{2,}", "?", text)
        text = text.lower()
        # Restore sentence starts
        text = _re.sub(r"(?:^|(?<=[.!?]\s))([a-z])", lambda m: m.group(0).upper(), text)
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        # Restore F1 acronyms
        for _acr in ("F1", "DRS", "FIA", "GP", "DNF", "DNS", "DSQ", "VSC", "SC", "ERS"):
            text = _re.sub(r"\b" + _acr.lower() + r"\b", _acr, text, flags=_re.IGNORECASE)

        # Known F1 acronyms that should stay uppercase
        acronyms = {
            "F1", "DRS", "FIA", "FP1", "FP2", "FP3", "Q1", "Q2", "Q3",
            "P1", "P2", "P3", "DNF", "DNS", "DSQ", "VSC", "SC", "ERS",
            "MGU", "ICE", "PU", "TV", "UK", "US", "USA", "GP", "AWS",
            "RPM", "KPH", "MPH", "OK", "ID",
        }

        def fix_word(word: str) -> str:
            # Strip punctuation to check the core word
            prefix = ""
            suffix = ""
            core = word

            # Peel leading punctuation
            while core and not core[0].isalnum():
                prefix += core[0]
                core = core[1:]
            # Peel trailing punctuation
            while core and not core[-1].isalnum():
                suffix = core[-1] + suffix
                core = core[:-1]

            if not core:
                return word

            # Preserve known acronyms
            if core.upper() in acronyms:
                return word

            # If the word is ALL CAPS and longer than 1 char, convert to
            # capitalized (first letter upper, rest lower)
            if len(core) > 1 and core.isupper():
                return prefix + core.capitalize() + suffix

            return word

        words = text.split()
        normalized = " ".join(fix_word(w) for w in words)

        # Ensure trailing punctuation to prevent last-word truncation
        stripped = normalized.rstrip()
        if not stripped.endswith((".", "!", "?", "...")):
            stripped += "."
        # Extra trailing pause for safety
        normalized = stripped + " ..."

        return normalized

    async def generate_speech(
        self,
        text: str,
        character_name: Optional[str] = None,
        scene_number: int = 0,
        episode_id: int = 0,
        voice_override: Optional[str] = None,
        rate_override: Optional[str] = None,
    ) -> TTSResult:
        """Generate speech audio from dialogue text.

        Args:
            text: Dialogue text to speak.
            character_name: Character name for voice selection.
            scene_number: Scene number for file naming.
            episode_id: Episode ID for file naming.
            voice_override: Force a specific Edge TTS voice.
            rate_override: Force a specific speech rate.

        Returns:
            TTSResult with path to generated audio file.
        """
        voice = voice_override or self._resolve_voice(character_name)
        rate = rate_override or self._resolve_rate(character_name)

        output_path = (
            self.output_dir
            / f"ep{episode_id}_scene_{scene_number:02d}_dialogue.mp3"
        )

        logger.info(
            f"Scene {scene_number}: Generating TTS "
            f"(voice={voice}, rate={rate}, chars={len(text)})"
        )

        start_time = time.time()

        # Normalize text for TTS:
        # 1. Edge TTS spells out ALL-CAPS words as acronyms ("GO" → "G-O").
        #    Convert to sentence case while preserving known acronyms.
        # 2. Add trailing punctuation to prevent last-word truncation.
        normalized = self._normalize_for_tts(text)

        communicate = edge_tts.Communicate(
            text=normalized,
            voice=voice,
            rate=rate,
            volume=DEFAULT_VOLUME,
        )

        await communicate.save(str(output_path))

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Get audio duration via ffprobe
        duration = await self._get_audio_duration(str(output_path))

        logger.info(
            f"Scene {scene_number}: TTS done in {elapsed_ms}ms "
            f"(duration={duration:.2f}s, voice={voice})"
        )

        return TTSResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            generation_time_ms=elapsed_ms,
            voice_used=voice,
            text=text,
        )

    async def generate_silence(
        self,
        duration_seconds: float,
        scene_number: int = 0,
        episode_id: int = 0,
    ) -> str:
        """Generate a silent audio file for scenes without dialogue.

        Args:
            duration_seconds: Duration in seconds.
            scene_number: Scene number for file naming.
            episode_id: Episode ID for file naming.

        Returns:
            Path to silent audio file.
        """
        output_path = (
            self.output_dir
            / f"ep{episode_id}_scene_{scene_number:02d}_silence.mp3"
        )

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(duration_seconds),
            "-c:a", "libmp3lame",
            "-q:a", "4",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to generate silence: {stderr.decode()}")

        return str(output_path)

    @staticmethod
    async def _get_audio_duration(audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        try:
            duration = float(stdout.decode().strip())
        except (ValueError, AttributeError):
            raise RuntimeError(
                f"TTS audio duration probe failed for {audio_path} — "
                f"ffprobe returned: {stdout.decode().strip()!r}"
            )

        if duration <= 0:
            raise RuntimeError(
                f"TTS audio has zero/negative duration ({duration}s): {audio_path}"
            )

        return duration
