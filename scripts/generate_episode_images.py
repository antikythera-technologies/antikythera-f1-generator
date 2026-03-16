"""Batch generate all scene images for an episode.

Reads start_frame_prompt from DB, generates images via ComfyUI
(Flux + LoRA + PuLID), uploads to MinIO, and updates DB paths.

Strategy A: Generate ALL images first, then ALL videos.
This minimizes GPU swaps (ComfyUI stays loaded the whole time).

Usage:
    cd backend
    uv run python ../scripts/generate_episode_images.py
    uv run python ../scripts/generate_episode_images.py --episode 1 --start 5  # Resume from scene 5
    uv run python ../scripts/generate_episode_images.py --scene 1              # Single scene only
"""

import argparse
import asyncio
import os
import shutil
import sys
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text

from app.database import async_session_maker
from app.services.image_generator import ImageGenerator
from app.services.personality import find_personality_file, load_personality_traits
from app.services.storage import StorageService


EPISODE_ID = 1
RACE_ID = 1
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test-output", "episode-1", "images")
DESKTOP_DIR = "/mnt/c/Users/WianK/Desktop/F1-Episode-1/images"


async def main(episode_id: int, start_scene: int = 1, single_scene: int = 0):
    print("=" * 70)
    print(f"BATCH IMAGE GENERATION — Episode {episode_id}")
    print(f"Starting from scene {start_scene}")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    image_gen = ImageGenerator()
    storage = StorageService()

    # Check ComfyUI is reachable
    print("\nChecking ComfyUI...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{image_gen.comfyui_url}/system_stats")
            if resp.status_code != 200:
                print(f"  ERROR: ComfyUI returned {resp.status_code}. Is the RunPod pod running?")
                print(f"  URL: {image_gen.comfyui_url}")
                return
            stats = resp.json()
            gpus = stats.get("devices", [])
            for gpu in gpus:
                print(f"  GPU: {gpu.get('name', 'unknown')} — "
                      f"VRAM: {gpu.get('vram_total', 0) / 1e9:.1f}GB")
    except Exception as e:
        print(f"  ERROR: Cannot reach ComfyUI: {e}")
        print(f"  URL: {image_gen.comfyui_url}")
        print("  Start the RunPod pod and try again.")
        return

    async with async_session_maker() as db:
        # Get race_id for this episode
        r = await db.execute(text(
            "SELECT race_id FROM episodes WHERE id = :eid"
        ), {"eid": episode_id})
        row = r.fetchone()
        if not row:
            print(f"ERROR: Episode {episode_id} not found!")
            return
        race_id = row[0]

        # Load all scenes
        r = await db.execute(text("""
            SELECT es.scene_number, es.character_id, es.start_frame_prompt,
                   es.start_frame_path, c.name as character_name
            FROM episode_scenes es
            JOIN characters c ON c.id = es.character_id
            WHERE es.episode_id = :eid
            ORDER BY es.scene_number
        """), {"eid": episode_id})
        scenes = r.fetchall()
        print(f"\nLoaded {len(scenes)} scenes")

        # Pre-load character data and face references
        print("\nPreparing characters...")
        char_cache = {}  # name -> (traits, face_image)

        for scene in scenes:
            char_name = scene[4]  # character_name
            if char_name in char_cache:
                continue

            # Load personality traits
            pfile = find_personality_file(char_name)
            traits = load_personality_traits(pfile) if pfile else {}
            if not traits:
                # Fallback: get basic info from DB
                cr = await db.execute(text(
                    "SELECT display_name, team FROM characters WHERE name = :name"
                ), {"name": char_name})
                crow = cr.fetchone()
                if crow:
                    traits = {"display_name": crow[0], "team": crow[1]}

            # Ensure face reference
            face_image = await image_gen.ensure_face_reference(char_name)

            char_cache[char_name] = (traits, face_image)
            print(f"  {char_name}: traits={'yes' if traits else 'no'}, "
                  f"face={'yes' if face_image else 'NO'}")

        # Generate images
        print("\n" + "=" * 70)
        print("GENERATING SCENE IMAGES")
        print("=" * 70)

        total_time = 0
        success_count = 0
        fail_count = 0

        for scene in scenes:
            scene_num = scene[0]
            char_id = scene[1]
            start_frame_prompt = scene[2]
            existing_path = scene[3]
            char_name = scene[4]

            if single_scene and scene_num != single_scene:
                continue

            if scene_num < start_scene:
                print(f"\n--- Scene {scene_num:02d} ({char_name}) --- SKIPPED (before start)")
                continue

            if existing_path and start_scene == 1:
                print(f"\n--- Scene {scene_num:02d} ({char_name}) --- SKIPPED (already has image)")
                continue

            if not start_frame_prompt:
                print(f"\n--- Scene {scene_num:02d} ({char_name}) --- SKIPPED (no prompt)")
                fail_count += 1
                continue

            print(f"\n--- Scene {scene_num:02d} ({char_name}) ---")
            print(f"  Prompt: {start_frame_prompt[:100]}...")

            traits, face_image = char_cache.get(char_name, ({}, None))

            scene_start = time.time()
            try:
                result = await image_gen.generate_scene_image(
                    scene_number=scene_num,
                    episode_id=episode_id,
                    character_name=char_name,
                    frame_prompt=start_frame_prompt,
                    frame_type="start",
                    character_traits=traits,
                    face_image=face_image,
                )

                elapsed = time.time() - scene_start
                total_time += elapsed
                print(f"  Generated in {elapsed:.1f}s: {result.image_path}")

                # Upload to MinIO
                minio_path = await storage.upload_scene_image(
                    race_id=race_id,
                    episode_id=episode_id,
                    scene_number=scene_num,
                    file_path=result.image_path,
                    suffix="start",
                )
                print(f"  Uploaded to MinIO: {minio_path}")

                # Update DB
                await db.execute(text("""
                    UPDATE episode_scenes
                    SET start_frame_path = :path
                    WHERE episode_id = :eid AND scene_number = :sn
                """), {"path": minio_path, "eid": episode_id, "sn": scene_num})
                await db.commit()

                # Copy to local output
                local_out = os.path.join(OUTPUT_DIR, f"scene_{scene_num:02d}_start.png")
                shutil.copy2(result.image_path, local_out)
                print(f"  Saved: {local_out}")

                success_count += 1

            except Exception as e:
                elapsed = time.time() - scene_start
                total_time += elapsed
                print(f"  FAILED ({elapsed:.1f}s): {e}")
                fail_count += 1
                # Continue to next scene — don't stop on individual failures

        # Copy to Windows desktop
        print("\n" + "=" * 70)
        print("COPYING TO DESKTOP")
        print("=" * 70)
        try:
            os.makedirs(DESKTOP_DIR, exist_ok=True)
            for f in os.listdir(OUTPUT_DIR):
                if f.endswith(".png"):
                    src = os.path.join(OUTPUT_DIR, f)
                    dst = os.path.join(DESKTOP_DIR, f)
                    shutil.copy2(src, dst)
                    print(f"  {f}")
            print(f"  Copied to: {DESKTOP_DIR}")
        except Exception as e:
            print(f"  Could not copy to desktop: {e}")

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Success: {success_count}/{len(scenes)}")
        print(f"  Failed:  {fail_count}")
        print(f"  Total time: {total_time:.0f}s ({total_time/60:.1f} min)")
        if success_count > 0:
            print(f"  Avg per scene: {total_time/success_count:.1f}s")
        print(f"\n  Images: {OUTPUT_DIR}")
        print(f"  Desktop: {DESKTOP_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate scene images for an episode")
    parser.add_argument("--episode", type=int, default=EPISODE_ID, help="Episode ID")
    parser.add_argument("--start", type=int, default=1, help="Start from scene number")
    parser.add_argument("--scene", type=int, default=0, help="Generate single scene only")
    args = parser.parse_args()

    asyncio.run(main(args.episode, args.start, args.scene))
