"""Generate a single scene: video (Ovi) + TTS audio + mux.

Usage:
    cd backend
    PYTHONUNBUFFERED=1 uv run python ../scripts/generate_scene_video.py --scene 1
    PYTHONUNBUFFERED=1 uv run python ../scripts/generate_scene_video.py --scene 1 --audio-only
"""

import argparse
import asyncio
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text

from app.config import settings
from app.database import async_session_maker
from app.services.ovi_video_generator import OviVideoGenerator
from app.services.tts_generator import TTSGenerator
from app.services.audio_mixer import AudioMixer
from app.services.storage import StorageService


EPISODE_ID = 1
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test-output", "episode-1", "ovi")
DESKTOP_DIR = "/mnt/c/Users/WianK/Desktop/F1-Episode-1/ovi"


async def main(scene_number: int, audio_only: bool = False):
    print("=" * 70)
    print(f"SCENE GENERATION — Episode {EPISODE_ID}, Scene {scene_number}")
    print(f"Mode: {'audio-only (skip video gen)' if audio_only else 'full (video + audio)'}")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    storage = StorageService()
    tts = TTSGenerator()
    mixer = AudioMixer()

    async with async_session_maker() as db:
        # Get scene data
        r = await db.execute(text("""
            SELECT es.scene_number, es.dialogue, es.audio_description,
                   es.video_prompt, es.start_frame_path, es.camera_direction,
                   es.action_description, c.name as character_name,
                   e.race_id, es.video_clip_path
            FROM episode_scenes es
            JOIN characters c ON c.id = es.character_id
            JOIN episodes e ON e.id = es.episode_id
            WHERE es.episode_id = :eid AND es.scene_number = :sn
        """), {"eid": EPISODE_ID, "sn": scene_number})
        scene = r.fetchone()

        if not scene:
            print(f"ERROR: Scene {scene_number} not found!")
            return

        character = scene[7]
        dialogue = scene[1]
        audio_desc = scene[2]
        video_prompt = scene[3]
        image_minio_path = scene[4]
        camera_dir = scene[5]
        action_desc = scene[6]
        race_id = scene[8]
        existing_clip_path = scene[9]

        print(f"\nCharacter: {character}")
        print(f"Dialogue: {dialogue}")
        print(f"Audio desc: {audio_desc}")
        print(f"Video prompt: {(video_prompt or '')[:120]}...")
        print(f"Camera: {camera_dir}")
        print(f"Image: {image_minio_path}")
        print(f"Existing clip: {existing_clip_path}")

        # ---- STEP 1: Video Generation (Ovi) ----

        video_file = os.path.join(OUTPUT_DIR, f"scene_{scene_number:02d}_silent.mp4")

        if audio_only and existing_clip_path:
            print(f"\n--- SKIPPING VIDEO GEN (audio-only mode) ---")
            print(f"Downloading existing clip from MinIO...")
            bucket = existing_clip_path.split("/")[0]
            obj = existing_clip_path.replace(f"{bucket}/", "", 1)
            await storage.download_file(bucket, obj, video_file)
            print(f"  Downloaded: {video_file}")
        else:
            if not image_minio_path:
                print("ERROR: No start frame image! Generate images first.")
                return

            # Check Ovi is reachable
            print(f"\nOvi server: {settings.OVI_SERVER_URL}")
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(f"{settings.OVI_SERVER_URL}/gradio_api/info")
                    if resp.status_code == 200:
                        print("  Ovi Gradio API: OK")
                    else:
                        print(f"  ERROR: Ovi returned {resp.status_code}")
                        return
                except Exception as e:
                    print(f"  ERROR: Cannot reach Ovi: {e}")
                    return

            # Download start frame
            print("\nDownloading start frame from MinIO...")
            local_image = f"/tmp/f1-scene{scene_number}-start.png"
            await storage.download_file(
                bucket=settings.MINIO_BUCKET_SCENE_IMAGES,
                object_name=image_minio_path.replace("f1-scene-images/", ""),
                file_path=local_image,
            )
            print(f"  Downloaded: {local_image}")

            action = video_prompt or action_desc or "Character speaking to camera"
            print(f"\nAction prompt: {action[:120]}...")

            ovi = OviVideoGenerator()

            print(f"\n{'=' * 70}")
            print("STEP 1: GENERATING VIDEO WITH OVI (~16 min with cpu_offload)")
            print(f"{'=' * 70}")

            start_time = time.time()
            try:
                clip = await ovi.generate_clip(
                    scene_number=scene_number,
                    image_path=local_image,
                    action=action,
                    dialogue=dialogue,
                    audio_description=audio_desc,
                )
                elapsed = time.time() - start_time
                print(f"\n  Video generated in {elapsed:.0f}s ({elapsed/60:.1f} min)")
                print(f"  Video: {clip.video_path}")

                # Copy silent video to output
                shutil.copy2(clip.video_path, video_file)
                print(f"  Silent video saved: {video_file}")

            except Exception as e:
                elapsed = time.time() - start_time
                print(f"\n  VIDEO GENERATION FAILED after {elapsed:.0f}s: {e}")
                import traceback
                traceback.print_exc()
                return

        # ---- STEP 2: TTS Audio Generation ----

        print(f"\n{'=' * 70}")
        print("STEP 2: GENERATING TTS AUDIO")
        print(f"{'=' * 70}")

        audio_path = None
        if dialogue and dialogue.strip():
            try:
                tts_result = await tts.generate_speech(
                    text=dialogue,
                    character_name=character,
                    scene_number=scene_number,
                    episode_id=EPISODE_ID,
                )
                audio_path = tts_result.audio_path
                print(f"  TTS generated: {audio_path}")
                print(f"  Duration: {tts_result.duration_seconds:.2f}s")
                print(f"  Voice: {tts_result.voice_used}")
                print(f"  Time: {tts_result.generation_time_ms}ms")
            except Exception as e:
                print(f"  TTS FAILED: {e}")
                import traceback
                traceback.print_exc()
                return
        else:
            print("  No dialogue — will add silent audio track")

        # ---- STEP 3: Mux Audio onto Video ----

        print(f"\n{'=' * 70}")
        print("STEP 3: MUXING AUDIO ONTO VIDEO")
        print(f"{'=' * 70}")

        try:
            mix_result = await mixer.mux_audio_onto_video(
                video_path=video_file,
                audio_path=audio_path,
                scene_number=scene_number,
                episode_id=EPISODE_ID,
            )
            print(f"  Muxed: {mix_result.output_path}")
            print(f"  Video duration: {mix_result.video_duration:.2f}s")
            print(f"  Audio duration: {mix_result.audio_duration:.2f}s")
            print(f"  Tempo factor: {mix_result.tempo_factor:.2f}x")
            print(f"  Time: {mix_result.generation_time_ms}ms")
        except Exception as e:
            print(f"  AUDIO MUX FAILED: {e}")
            import traceback
            traceback.print_exc()
            return

        # ---- STEP 4: Validate Audio Track ----

        print(f"\n{'=' * 70}")
        print("STEP 4: VALIDATING OUTPUT")
        print(f"{'=' * 70}")

        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "stream=codec_type,codec_name,duration",
            "-of", "csv=p=0",
            mix_result.output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        streams = stdout.decode().strip()
        print(f"  Streams: {streams}")

        if "audio" not in streams:
            print("  VALIDATION FAILED: No audio track in output!")
            return

        print("  VALIDATION PASSED: Video has audio track")

        # ---- STEP 5: Save & Upload ----

        print(f"\n{'=' * 70}")
        print("STEP 5: SAVING & UPLOADING")
        print(f"{'=' * 70}")

        # Copy final to output dir
        final_file = os.path.join(OUTPUT_DIR, f"scene_{scene_number:02d}.mp4")
        shutil.copy2(mix_result.output_path, final_file)
        print(f"  Local: {final_file}")

        # Upload to MinIO
        minio_path = await storage.upload_video_clip(
            race_id=race_id,
            episode_id=EPISODE_ID,
            scene_number=scene_number,
            file_path=mix_result.output_path,
        )
        print(f"  MinIO: {minio_path}")

        # Update DB
        await db.execute(text("""
            UPDATE episode_scenes
            SET video_clip_path = :path, video_generator = 'ovi',
                audio_clip_path = :path, status = 'completed'
            WHERE episode_id = :eid AND scene_number = :sn
        """), {"path": minio_path, "eid": EPISODE_ID, "sn": scene_number})
        await db.commit()
        print("  DB updated (video_clip_path + audio_clip_path)")

        # Copy to desktop
        try:
            os.makedirs(DESKTOP_DIR, exist_ok=True)
            desktop_file = os.path.join(DESKTOP_DIR, f"scene_{scene_number:02d}.mp4")
            shutil.copy2(mix_result.output_path, desktop_file)
            print(f"  Desktop: {desktop_file}")
        except Exception as e:
            print(f"  Could not copy to desktop: {e}")

        print(f"\n{'=' * 70}")
        print(f"DONE! Scene {scene_number} complete with audio.")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=int, default=1, help="Scene number")
    parser.add_argument("--audio-only", action="store_true",
                        help="Skip video gen, just do TTS + mux on existing clip")
    args = parser.parse_args()
    asyncio.run(main(args.scene, audio_only=args.audio_only))
