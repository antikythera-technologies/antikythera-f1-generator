"""Regenerate episode scripts with the rich cinematographic prompt system.

This script re-runs the script generator for an existing episode,
updating all 24 scenes with new start_frame_prompt, end_frame_prompt,
camera_direction, video_prompt, and improved dialogue.

Usage:
    cd backend
    uv run python ../scripts/regenerate_episode_scripts.py
"""

import asyncio
import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import async_session_maker
from app.services.script_generator import ScriptGenerator
from app.services.personality import find_personality_file, load_personality_traits
from sqlalchemy import text


EPISODE_ID = 1

# Characters for Australian GP Episode 1
# 4 characters: drivers who defined the 2026 season opener
CHARACTERS = [
    "david_croft",       # Host/anchor — breathless enthusiasm, sets up jokes
    "max_verstappen",    # Crashed in Q1, drove from P20 to P6 — humbled but brilliant
    "george_russell",    # WINNER, new championship leader — smug villain arc begins
    "charles_leclerc",   # Led early, lost on strategy AGAIN — the Tragic Prince continues
]


async def main():
    print("=" * 60)
    print("REGENERATING EPISODE 1 SCRIPTS")
    print("=" * 60)

    script_generator = ScriptGenerator()

    async with async_session_maker() as db:
        # --- 1. Build race context ---
        r = await db.execute(text(
            "SELECT race_name, circuit_name, country, race_date FROM races WHERE id = 1"
        ))
        race = r.fetchone()
        print(f"\nRace: {race[0]} at {race[1]}, {race[2]}")

        race_context = f"""
Race: {race[0]}
Circuit: {race[1]}, {race[2]}
Date: {race[3]}
Season: 2026, Round 1 — SEASON OPENER under NEW 2026 technical regulations

CRITICAL: This is the 2026 season. Hamilton has been at Ferrari since 2025 — NOT new.
Kimi Antonelli replaced Hamilton at Mercedes for 2026. These are established facts, not news.

=== QUALIFYING ===
- George Russell took POLE POSITION for Mercedes.
- Max Verstappen CRASHED OUT in Q1 — rear axle locked under braking at Turn 1 (energy harvesting too aggressive, acted like a handbrake). Red flag. Walked away, needed hand X-rays. Starts P20.
- Kimi Antonelli qualified P2 (Mercedes 1-2 front row) despite FP3 crash.
- Oscar Piastri qualified P5.

=== PRE-RACE DRAMA ===
- Oscar Piastri CRASHED on the reconnaissance lap BEFORE the formation lap — lost control at Turn 4. Terminal damage. Did not start his HOME Grand Prix.
- Nico Hulkenberg (Audi) also DNS — technical failure.

=== RACE ===
- George Russell WON from pole, leading a Mercedes 1-2 with Kimi Antonelli P2.
- Russell vs Leclerc EPIC battle — lead changed SEVEN TIMES in first 10 laps. New overtake mode (electric boost for trailing drivers within 1s) created constant swapping. Drivers called it "Mario Kart" racing.
- Leclerc led until lap 26 — Ferrari STRATEGIC ERROR: didn't pit under VSC while Mercedes did. Russell inherited lead, never gave it back.
- Max Verstappen drove from P20 to P6 — brilliant recovery after the Q1 disaster.
- 120 overtakes vs only 45 at same race in 2025. F1 touted it as proof new regs work, but many drivers complained overtakes feel "artificial."

=== RESULT ===
1. George Russell (Mercedes) — WINNER
2. Kimi Antonelli (Mercedes) — P2
3. Charles Leclerc (Ferrari) — P3, led early but lost on strategy
4. Lewis Hamilton (Ferrari) — P4
5. Lando Norris (McLaren) — P5
6. Max Verstappen (Red Bull) — P6 from P20!

=== KEY NARRATIVES ===
- NEW ERA: 2026 regulations with active aero, electric boost, overtake modes
- "Mario Kart" debate: Are the overtakes real or artificial?
- Mercedes dominance: Are they the new force?
- Russell as championship leader — the smug villain arc begins
- Verstappen's humbling: crashed in Q1 but drove brilliantly to P6
- Ferrari strategy curse: Leclerc lost the lead AGAIN due to strategy blunder
- Piastri's heartbreak: crashing at your home race before it even starts
"""

        # --- 2. Build character info with full personalities ---
        print("\nLoading character personalities...")
        characters = []
        for char_name in CHARACTERS:
            r = await db.execute(text(
                "SELECT id, name, display_name, team, personality, voice_description "
                "FROM characters WHERE name = :name"
            ), {"name": char_name})
            row = r.fetchone()
            if not row:
                print(f"  WARNING: Character '{char_name}' not found in DB!")
                continue

            # Load personality from JSON files
            pfile = find_personality_file(char_name)
            traits = load_personality_traits(pfile) if pfile else {}

            char_info = {
                "name": row[1],
                "display_name": row[2],
                "team": row[3] or "Pundit",
                "personality": traits.get("comedy_angle", row[4] or "Entertaining personality"),
                "voice_description": traits.get("voice_description", row[5] or "Neutral voice"),
                "comedy_exaggeration": traits.get("comedy_exaggeration", ""),
                "satirical_angle": traits.get("satirical_angle", ""),
                "signature_expression": traits.get("signature_expression", ""),
            }
            characters.append(char_info)
            print(f"  {row[2]} ({row[3] or 'Pundit'}): {char_info['personality'][:60]}...")

        # --- 3. Load running gags ---
        r = await db.execute(text(
            "SELECT title, description, category FROM running_gags ORDER BY id"
        ))
        gags = r.fetchall()
        running_gags = [
            {"title": g[0], "description": g[1], "category": g[2]}
            for g in gags
        ]
        print(f"\nRunning gags: {len(running_gags)} available")
        for g in running_gags:
            print(f"  [{g['category']}] {g['title']}")

        # --- 4. Generate new script ---
        print("\n" + "=" * 60)
        print("CALLING SCRIPT GENERATOR (Anthropic Claude)...")
        print("=" * 60)

        episode_script = await script_generator.generate_script(
            race_context=race_context,
            characters=characters,
            episode_type="post-race",
            running_gags=running_gags,
        )

        print(f"\nTitle: {episode_script.title}")
        print(f"Scenes: {len(episode_script.scenes)}")
        print(f"Tokens: {episode_script.input_tokens} in / {episode_script.output_tokens} out")
        print(f"Cost: ${episode_script.cost_usd:.4f}")
        print(f"Gags used: {episode_script.gags_referenced}")

        # --- 5. Save script to test-output for review ---
        output_dir = os.path.join(
            os.path.dirname(__file__), "..", "test-output", "episode-1"
        )
        os.makedirs(output_dir, exist_ok=True)

        script_data = {
            "title": episode_script.title,
            "gags_used": episode_script.gags_referenced,
            "tokens": {
                "input": episode_script.input_tokens,
                "output": episode_script.output_tokens,
                "cost_usd": episode_script.cost_usd,
            },
            "scenes": [],
        }
        for scene in episode_script.scenes:
            script_data["scenes"].append({
                "scene_number": scene.scene_number,
                "character": scene.character,
                "dialogue": scene.dialogue,
                "audio_description": scene.audio_description,
                "start_frame_prompt": scene.start_frame_prompt,
                "end_frame_prompt": scene.end_frame_prompt,
                "camera_direction": scene.camera_direction,
                "video_prompt": scene.video_prompt,
            })

        script_path = os.path.join(output_dir, "script_v2.json")
        with open(script_path, "w") as f:
            json.dump(script_data, f, indent=2)
        print(f"\nScript saved to: {script_path}")

        # --- 6. Preview first 3 scenes ---
        print("\n" + "=" * 60)
        print("PREVIEW (first 3 scenes)")
        print("=" * 60)
        for scene in episode_script.scenes[:3]:
            print(f"\n--- Scene {scene.scene_number} ({scene.character}) ---")
            print(f"Dialogue: {scene.dialogue}")
            print(f"Start frame: {scene.start_frame_prompt[:120]}...")
            print(f"Camera: {scene.camera_direction[:80]}...")
            print(f"Audio: {scene.audio_description[:80]}...")

        # --- 7. Update database ---
        print("\n" + "=" * 60)
        print("UPDATING DATABASE...")
        print("=" * 60)

        # Map character names to IDs
        char_id_map = {}
        for char_name in CHARACTERS:
            r = await db.execute(text(
                "SELECT id FROM characters WHERE name = :name"
            ), {"name": char_name})
            row = r.fetchone()
            if row:
                char_id_map[char_name] = row[0]

        # Delete existing scenes and recreate
        await db.execute(text(
            "DELETE FROM episode_scenes WHERE episode_id = :eid"
        ), {"eid": EPISODE_ID})
        print(f"  Deleted old scenes for episode {EPISODE_ID}")

        for scene in episode_script.scenes:
            char_id = char_id_map.get(scene.character)
            if not char_id:
                print(f"  WARNING: No character_id for '{scene.character}', skipping scene {scene.scene_number}")
                continue

            await db.execute(text("""
                INSERT INTO episode_scenes (
                    episode_id, scene_number, character_id,
                    dialogue, audio_description, action_description,
                    start_frame_prompt, end_frame_prompt,
                    camera_direction, video_prompt,
                    status, duration_seconds, retry_count
                ) VALUES (
                    :eid, :sn, :cid,
                    :dialogue, :audio_desc, :action_desc,
                    :sfp, :efp,
                    :cd, :vp,
                    'pending', 5.0, 0
                )
            """), {
                "eid": EPISODE_ID,
                "sn": scene.scene_number,
                "cid": char_id,
                "dialogue": scene.dialogue,
                "audio_desc": scene.audio_description,
                "action_desc": scene.camera_direction,  # Use camera direction as action for backward compat
                "sfp": scene.start_frame_prompt,
                "efp": scene.end_frame_prompt,
                "cd": scene.camera_direction,
                "vp": scene.video_prompt,
            })

        await db.commit()
        print(f"  Inserted {len(episode_script.scenes)} new scenes")

        # Reset episode status
        await db.execute(text(
            "UPDATE episodes SET status = 'generating' WHERE id = :eid"
        ), {"eid": EPISODE_ID})
        await db.commit()
        print(f"  Episode status reset to 'generating'")

        print("\n" + "=" * 60)
        print("DONE! Review script at: test-output/episode-1/script_v2.json")
        print("Next: Generate images from start_frame_prompts")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
