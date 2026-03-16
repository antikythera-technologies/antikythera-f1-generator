"""Test Ovi scene 1 generation — end-to-end pipeline validation.

Downloads existing scene 1 image from MinIO, generates video with Ovi,
generates TTS audio, muxes audio onto video. Validates the full Ovi
pipeline path before running all 24 scenes.

IMPORTANT: This script properly manages GPU sharing between ComfyUI and Ovi.
ComfyUI and Ovi CANNOT run simultaneously on the same A6000 48GB GPU.
Since we already have the image from MinIO, we STOP ComfyUI and only
run Ovi for video generation.

Usage:
    cd backend && .venv/bin/python ../scripts/experiments/test_ovi_scene1.py
"""

import asyncio
import logging
import os
import sys
import time

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("test_ovi_scene1")

# Scene 1 data (from DB)
SCENE_1 = {
    "scene_number": 1,
    "character_name": "simon_lazenby",
    "dialogue": (
        "Welcome to our post-race analysis of the 2026 Australian Grand Prix!"
    ),
    "action_description": "Sitting at the broadcast desk, looking serious",
    "audio_description": "Dramatic music, crisp British accent",
    "source_image_path": "f1-scene-images/race_001/episode_1/scene_01.png",
}

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "test-output", "ovi-scene1"
)


async def step_1_download_image() -> str:
    """Download scene 1 image from MinIO."""
    from app.services.storage import StorageService

    local_path = os.path.join(OUTPUT_DIR, "scene_01_source.png")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Skip download if already exists
    if os.path.exists(local_path) and os.path.getsize(local_path) > 10000:
        size_kb = os.path.getsize(local_path) / 1024
        logger.info(f"Image already downloaded: {local_path} ({size_kb:.0f} KB)")
        return local_path

    storage = StorageService()
    bucket, obj = SCENE_1["source_image_path"].split("/", 1)
    logger.info(f"Downloading image from MinIO: {bucket}/{obj}")
    await storage.download_file(bucket, obj, local_path)

    size_kb = os.path.getsize(local_path) / 1024
    logger.info(f"Image downloaded: {local_path} ({size_kb:.0f} KB)")
    return local_path


async def step_2_stop_comfyui():
    """Stop ComfyUI to free ALL GPU memory for Ovi.

    ComfyUI and Ovi share one A6000 48GB. They CANNOT run simultaneously.
    Since we already have the scene image, ComfyUI is not needed.
    """
    import httpx
    from app.config import settings

    logger.info("Stopping ComfyUI to free GPU for Ovi...")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First try to unload models
            try:
                resp = await client.post(
                    f"{settings.COMFYUI_URL}/free",
                    json={"unload_models": True, "free_memory": True},
                )
                logger.info(f"ComfyUI free response: {resp.status_code}")
            except Exception:
                logger.info("ComfyUI /free not responding (may already be stopped)")

            # Check GPU memory
            try:
                resp = await client.get(f"{settings.COMFYUI_URL}/gpu/memory")
                mem = resp.json()
                logger.info(
                    f"GPU memory: {mem.get('free_mib', '?')} MiB free "
                    f"/ {mem.get('total_mib', '?')} MiB total"
                )
            except Exception:
                logger.info("GPU memory endpoint not responding")

    except Exception as e:
        logger.info(f"ComfyUI not reachable (may already be stopped): {e}")


async def step_3_ensure_ovi_ready() -> bool:
    """Ensure Ovi is running and responsive.

    Uses the OviSpaceManager to check pod status and wait for Gradio.
    """
    import httpx
    from app.config import settings

    logger.info("Checking Ovi readiness...")

    # Check via GPU manager first
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{settings.COMFYUI_URL}/ovi/status")
            status = resp.json()
            logger.info(f"Ovi GPU manager: {status}")

            if not status.get("running"):
                logger.info("Starting Ovi via GPU manager...")
                await client.post(f"{settings.COMFYUI_URL}/ovi/start")
                logger.info("Waiting for Ovi model load (~4-5 min with cpu_offload)...")

                # Poll until Ovi Gradio is responsive
                for attempt in range(30):  # 30 x 15s = 7.5 min timeout
                    await asyncio.sleep(15)
                    try:
                        resp = await client.get(
                            f"{settings.OVI_SERVER_URL}/",
                            timeout=10.0,
                        )
                        if resp.status_code == 200:
                            logger.info(
                                f"Ovi Gradio responsive after {(attempt + 1) * 15}s"
                            )
                            return True
                    except Exception:
                        logger.info(
                            f"  Waiting... ({(attempt + 1) * 15}s elapsed)"
                        )

                logger.error("Ovi did not become responsive in time")
                return False
    except Exception as e:
        logger.warning(f"GPU manager not reachable: {e}")

    # Direct check on Ovi Gradio
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{settings.OVI_SERVER_URL}/")
            if resp.status_code == 200:
                logger.info("Ovi Gradio is responsive!")
                return True
            else:
                logger.error(f"Ovi returned HTTP {resp.status_code}")
                return False
    except Exception as e:
        logger.error(f"Ovi not responsive: {e}")
        return False


async def step_4_generate_video(image_path: str) -> str:
    """Generate video with Ovi from scene 1 image."""
    from app.services.ovi_video_generator import OviVideoGenerator

    generator = OviVideoGenerator(quality="standard")

    logger.info("Generating video with Ovi...")
    logger.info(f"  Steps: {generator.sample_steps}")
    logger.info(f"  Conditioning: {generator.image_conditioning_strength}")
    logger.info(f"  Denoise: {generator.denoise_strength}")
    logger.info(f"  Guidance: {generator.guidance_scale}")
    logger.info(f"  Resolution: {generator.frame_width}x{generator.frame_height}")

    clip = await generator.generate_clip(
        scene_number=SCENE_1["scene_number"],
        image_path=image_path,
        action=SCENE_1["action_description"],
        dialogue=SCENE_1["dialogue"],
        audio_description=SCENE_1["audio_description"],
    )

    if clip.video_path is None or clip.video_path == "None":
        raise RuntimeError(
            "Ovi returned None for video path. "
            "Likely GPU OOM — check that ComfyUI is not consuming VRAM."
        )

    # Copy the video to our output directory
    import shutil

    output_path = os.path.join(OUTPUT_DIR, "scene_01_ovi_raw.mp4")
    shutil.copy2(clip.video_path, output_path)

    logger.info(
        f"Video generated in {clip.generation_time_ms}ms: {output_path}"
    )
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Video size: {size_mb:.1f} MB")
    return output_path


async def step_5_generate_tts(video_path: str) -> str:
    """Generate TTS audio and mux onto video."""
    from app.services.tts_generator import TTSGenerator
    from app.services.audio_mixer import AudioMixer
    from app.config import settings

    tts = TTSGenerator(default_voice=settings.TTS_DEFAULT_VOICE)
    mixer = AudioMixer()

    # Generate TTS speech
    logger.info("Generating TTS audio...")
    tts_result = await tts.generate_speech(
        text=SCENE_1["dialogue"],
        character_name=SCENE_1["character_name"],
        scene_number=SCENE_1["scene_number"],
        episode_id=999,  # Test episode
    )
    logger.info(
        f"TTS: {tts_result.duration_seconds:.2f}s, voice={tts_result.voice_used}"
    )

    # Mux audio onto video
    logger.info("Muxing TTS audio onto video...")
    mix_result = await mixer.mux_audio_onto_video(
        video_path=video_path,
        audio_path=tts_result.audio_path,
        scene_number=SCENE_1["scene_number"],
        episode_id=999,
    )

    # Copy final to output
    import shutil

    final_path = os.path.join(OUTPUT_DIR, "scene_01_ovi_final.mp4")
    shutil.copy2(mix_result.output_path, final_path)

    logger.info(
        f"Final video with audio: {final_path} "
        f"(tempo={mix_result.tempo_factor:.2f}x, {mix_result.generation_time_ms}ms)"
    )
    return final_path


async def main():
    start = time.time()
    logger.info("=" * 60)
    logger.info("OVI SCENE 1 TEST — Full Pipeline Validation")
    logger.info("=" * 60)

    # Step 1: Download image (uses MinIO, no GPU needed)
    logger.info("\n--- STEP 1: Download scene image from MinIO ---")
    image_path = await step_1_download_image()

    # Step 2: Stop ComfyUI (free GPU for Ovi)
    logger.info("\n--- STEP 2: Stop ComfyUI (free GPU) ---")
    await step_2_stop_comfyui()

    # Step 3: Ensure Ovi is ready
    logger.info("\n--- STEP 3: Ensure Ovi is ready ---")
    ovi_ready = await step_3_ensure_ovi_ready()
    if not ovi_ready:
        logger.error(
            "Ovi is not ready. Start it manually via RunPod web terminal:\n"
            "  bash /workspace/start-ovi.sh\n"
            "Then re-run this script."
        )
        return

    # Step 4: Generate video (~16 min with cpu_offload)
    logger.info("\n--- STEP 4: Generate video with Ovi ---")
    video_path = await step_4_generate_video(image_path)

    # Step 5: TTS + audio mux (runs locally, no GPU)
    logger.info("\n--- STEP 5: Generate TTS + mux audio ---")
    final_path = await step_5_generate_tts(video_path)

    elapsed = time.time() - start
    logger.info("\n" + "=" * 60)
    logger.info(f"TEST COMPLETE in {elapsed:.1f}s")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"  Source image:    scene_01_source.png")
    logger.info(f"  Raw video:       scene_01_ovi_raw.mp4")
    logger.info(f"  Final (w/audio): scene_01_ovi_final.mp4")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
