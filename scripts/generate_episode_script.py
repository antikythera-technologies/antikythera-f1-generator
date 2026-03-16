#!/usr/bin/env python3
"""
Generate episode script for the 2026 Australian Grand Prix.
Standalone script that calls the Anthropic API directly using the same
system prompt as the pipeline ScriptGenerator.

Usage:
    cd backend && uv run python ../scripts/generate_episode_script.py
"""

import json
import os
import sys
import time
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import anthropic

# Load .env manually
env_path = Path(__file__).parent.parent / "backend" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Import the system prompt from the actual service
from app.services.script_generator import SCRIPT_SYSTEM_PROMPT

OUTPUT_DIR = Path(__file__).parent.parent / "test-output" / "scripts"

# ── Race Context ──────────────────────────────────────────────────────

RACE_CONTEXT = """
2026 Australian Grand Prix — Albert Park, Melbourne
Round 1 of the 2026 FIA Formula One World Championship
Race Date: 8 March 2026
First race under the NEW 2026 technical regulations (active aero, powerful electric boost, overtake modes)

=== QUALIFYING ===
- George Russell took POLE POSITION for Mercedes.
- Max Verstappen CRASHED OUT in Q1 — on his very first flying lap, the rear axle locked under braking at Turn 1 (energy harvesting too aggressive, acted like a handbrake). Red flag. He walked away but needed X-rays on his hands. Starts P20.
- Kimi Antonelli qualified P2 (Mercedes 1-2 front row) despite a hefty crash in FP3.
- Oscar Piastri qualified P5.

=== PRE-RACE DRAMA ===
- Oscar Piastri CRASHED on the reconnaissance lap BEFORE the formation lap — lost control at Turn 4 exit while shifting gears. Terminal front-right damage. Did not start his HOME Grand Prix. Devastating.
- Nico Hulkenberg (Audi) also did NOT start — technical failure, wheeled off the grid.

=== RACE ===
- George Russell won from pole, leading a Mercedes 1-2 with teammate Kimi Antonelli.
- Russell and Charles Leclerc had an EPIC battle — the lead changed SEVEN TIMES in the first 10 laps. The new overtake mode (electric boost for trailing drivers within 1 second) created constant swapping. Drivers and media called it "Mario Kart" racing.
- Leclerc led until lap 26 when Ferrari made a strategic error — they didn't pit under a Virtual Safety Car while Mercedes did. Russell inherited the lead and never gave it back.
- Max Verstappen drove from P20 to P6 — a brilliant recovery drive, picking off car after car.
- 120 overtakes in the race vs only 45 at the same race in 2025 — F1 touted this as proof the new regs work, but many drivers complained the overtakes feel "artificial" and "not real racing."

=== RESULT ===
1. George Russell (Mercedes) — WINNER, his 6th career victory, first time leading the championship
2. Kimi Antonelli (Mercedes) — P2, Mercedes 1-2
3. Charles Leclerc (Ferrari) — P3, led early but lost out on strategy
4. Lewis Hamilton (Ferrari) — P4
5. Lando Norris (McLaren) — P5
6. Max Verstappen (Red Bull) — P6 from P20!
7. Oliver Bearman (Haas) — P7
8. Arvid Lindblad (Racing Bulls) — P8 (impressive debut season)

DNF/DNS: Piastri (DNS - recon lap crash), Hulkenberg (DNS - technical), Alonso (retired), Bottas (retired), Hadjar (retired)

=== FEUDS ===
- Liam Lawson vs Sergio Perez: Fighting for P16, Perez drove aggressively against Lawson. Lawson on team radio: "That guy f***ing sucks!" Reviving their 2024 Mexico feud. Lawson finished P13, Perez P16. Lawson post-race: "Two years later he's not over it. He's fighting me like it's for the world championship and we're P16."

=== KEY NARRATIVES ===
- The NEW ERA begins: 2026 regulations with active aero, electric boost, and overtake modes
- "Mario Kart" debate: Are the overtakes real or artificial?
- Mercedes dominance: Are they the new dominant force?
- Russell as championship leader for the first time — the "villain" arc begins
- Verstappen's humbling: crashed in Q1 but still drove brilliantly to P6
- Piastri's heartbreak: crashing at your home race before it even starts
- Ferrari strategy curse continues: Leclerc lost the lead due to a strategy blunder
"""

# ── Character Profiles ────────────────────────────────────────────────

CHARACTERS = [
    {
        "name": "Max Verstappen",
        "personality": (
            "The Cold Assassin. Four-time world champion who treats races like admin tasks. "
            "Emotionless winning machine bored by his own dominance. Dutch directness, matter-of-fact delivery. "
            "Catchphrases: 'Simply lovely', 'It is what it is', 'We move on'. "
            "Comedy: robotic efficiency, would rather be sim racing. Short dark hair, intense stare, sharp jawline, "
            "slight stubble. Slight slouch, dismissive hand wave. Red Bull dark blue race suit."
        ),
        "voice_description": (
            "Dutch accent with British influence. Short punchy sentences. Matter-of-fact, almost bored tone. "
            "Deadpan delivery. Uses 'simply', 'for sure', 'yeah'."
        ),
    },
    {
        "name": "George Russell",
        "personality": (
            "The Privileged Pretender / Villain. Rich boy with the best car who KNOWS he's not the best driver. "
            "Polished corporate politician, GPDA director, smug confidence that cracks under pressure. "
            "Catchphrases: 'At the end of the day', 'Going forward', 'Quite frankly'. "
            "Comedy: everything TOO perfect — hair survives helmet removal, race suit has visible ironing creases, "
            "carries a pocket mirror. Upper-class British accent, boarding school polish. "
            "Tall, slim, surgically perfect grooming, jaw designed by committee, teeth TOO white. "
            "Silver Mercedes race suit. The smile drops to dead-eyed calculation when cameras 'aren't looking'."
        ),
        "voice_description": (
            "Upper-class British, formal corporate vocabulary. Structured boardroom sentences. "
            "Smug but cracks under pressure. Uses 'look', 'the reality is', 'quite simply'."
        ),
    },
    {
        "name": "Charles Leclerc",
        "personality": (
            "The Tragic Prince. Handsome prince cursed by Ferrari strategy — every victory slips through his fingers. "
            "Passionate, emotional, charming. French-Italian accent, melodic and dramatic on radio. "
            "Catchphrases: 'No no no NO!', 'What are we doing?!', 'Come on guys!'. "
            "Comedy: increasingly dramatic reactions to Ferrari blunders, soulful intensity. "
            "Dark perfectly styled hair, model looks, intense green eyes. "
            "Elegant European posture. Red Ferrari race suit. Head in hands after errors, passionate fist pumps."
        ),
        "voice_description": (
            "French-Italian blend, melodic and dramatic. Emotional sentence structure. "
            "Passionate, frustrated with strategy. Uses 'honestly', 'I mean', 'you know'."
        ),
    },
    {
        "name": "Oscar Piastri",
        "personality": (
            "The Deadpan Assassin. Emotionally unavailable Australian prodigy who delivers devastating burns "
            "without changing expression. Driest humor in the paddock. Monotone delivery, savage content. "
            "Catchphrases: 'Yeah nah', 'I'm aware', 'Obviously', 'That's... interesting'. "
            "Comedy: never shows emotion even during crashes, poker face, minimal celebration. "
            "Dark neat hair, perpetually neutral expression, calculating eyes. "
            "Still, controlled posture. Papaya McLaren race suit."
        ),
        "voice_description": (
            "Australian, understated, bone-dry. Minimal efficient sentences. Monotone delivery. "
            "Uses 'um', 'I guess', 'sort of', 'yeah nah'."
        ),
    },
]

# ── Build Prompt ──────────────────────────────────────────────────────

def build_prompt() -> str:
    character_info = "\n".join(
        f"- {c['name']}: {c['personality']} (Voice: {c['voice_description']})"
        for c in CHARACTERS
    )

    return f"""Generate a post-race episode script.

Episode type: Post-race analysis and commentary — satirical, funny, sharp.

Available characters:
{character_info}

Race context:
{RACE_CONTEXT}

Generate a 24-scene satirical commentary script with full cinematographic direction.
Each scene needs start_frame_prompt, end_frame_prompt, camera_direction, and video_prompt.
Use the real race events as comedy fuel — exaggerate and satirize everything.

IMPORTANT IMAGE PROMPT RULES:
- Every start_frame_prompt and end_frame_prompt MUST begin with "ANTKF1STYLE satirical caricature"
- Include the shot type (WIDE, MEDIUM, CLOSE-UP, etc.)
- Describe the character's exact physical appearance, expression, clothing, and pose
- Describe the setting, background, lighting, and props in detail
- Characters have OVERSIZED HEADS with exaggerated features — always mention this
- Hyper-detailed photorealistic skin with visible pores
- Include depth of field notes (what's sharp, what's soft)

Output valid JSON only."""


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt()

    print("=" * 70)
    print("EPISODE SCRIPT GENERATION")
    print(f"Model: claude-sonnet-4-20250514")
    print(f"Max tokens: 16000")
    print(f"Temperature: 0.8")
    print(f"Prompt length: {len(prompt)} chars")
    print("=" * 70)

    start_time = time.time()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        temperature=0.8,
        system=SCRIPT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    elapsed = time.time() - start_time
    usage = response.usage

    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Input tokens: {usage.input_tokens}")
    print(f"Output tokens: {usage.output_tokens}")

    # Extract content
    content = response.content[0].text.strip()

    # Strip markdown code blocks if present
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])

    # Parse and validate
    try:
        script_data = json.loads(content)
        scene_count = len(script_data.get("scenes", []))
        print(f"Title: {script_data.get('title', 'UNTITLED')}")
        print(f"Scenes: {scene_count}")

        if scene_count != 24:
            print(f"WARNING: Expected 24 scenes, got {scene_count}")

        # Validate each scene has required fields
        for i, scene in enumerate(script_data.get("scenes", []), 1):
            missing = []
            for field in ["start_frame_prompt", "end_frame_prompt", "camera_direction", "video_prompt"]:
                if not scene.get(field):
                    missing.append(field)
            if missing:
                print(f"  Scene {i}: MISSING {', '.join(missing)}")

    except json.JSONDecodeError as e:
        print(f"WARNING: JSON parse failed: {e}")
        print("Saving raw output anyway...")
        script_data = None

    # Save
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"australian_gp_2026_{timestamp}.json"
    output_file.write_text(
        json.dumps(script_data, indent=2) if script_data else content,
        encoding="utf-8",
    )
    print(f"\nSaved: {output_file}")

    # Also save as latest
    latest_file = OUTPUT_DIR / "australian_gp_2026_latest.json"
    latest_file.write_text(
        json.dumps(script_data, indent=2) if script_data else content,
        encoding="utf-8",
    )
    print(f"Latest: {latest_file}")

    # Print first scene as preview
    if script_data and script_data.get("scenes"):
        s = script_data["scenes"][0]
        print(f"\n{'='*70}")
        print(f"PREVIEW — Scene 1:")
        print(f"  Character: {s.get('character')}")
        print(f"  Dialogue: {s.get('dialogue')}")
        print(f"  Start frame: {s.get('start_frame_prompt', '')[:120]}...")
        print(f"  Camera: {s.get('camera_direction')}")
        print(f"{'='*70}")


if __name__ == "__main__":
    main()
