"""Test the full audio pipeline: TTS speech muxed onto LTX AV video.

Takes the working LTX AV video (scene_01_ltx_av_v2.mp4) and muxes
character dialogue speech onto it, replacing the ambient LTX audio.
"""

import asyncio
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# Use the LTX AV video we just generated (absolute paths)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_VIDEO = str(REPO_ROOT / "test-output/scene-videos/scene_01_ltx_av_v2.mp4")
OUTPUT_DIR = REPO_ROOT / "test-output/scene-videos"

# Scene 1 dialogue — David Croft's opening line
DIALOGUE = (
    "It's lights out and away we go! What a start from Verstappen, "
    "he's absolutely launched it off the line!"
)
CHARACTER = "david_croft"


async def main():
    # Import the services
    import sys, os
    backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
    sys.path.insert(0, os.path.abspath(backend_dir))

    from app.services.tts_generator import TTSGenerator
    from app.services.audio_mixer import AudioMixer

    log.info("=== TTS + Mux Test on LTX AV Video ===")
    log.info(f"Input: {INPUT_VIDEO}")
    log.info(f"Character: {CHARACTER}")
    log.info(f"Dialogue: {DIALOGUE[:80]}...")

    # 1. Generate TTS speech
    log.info("Generating TTS speech...")
    tts = TTSGenerator(output_dir="/tmp/f1-audio-test")
    tts_result = await tts.generate_speech(
        text=DIALOGUE,
        character_name=CHARACTER,
        scene_number=1,
        episode_id=0,
    )
    log.info(
        f"TTS done: {tts_result.duration_seconds:.2f}s, "
        f"voice={tts_result.voice_used}, "
        f"{tts_result.generation_time_ms}ms"
    )

    # 2. Mux TTS onto video (replaces LTX ambient audio)
    log.info("Muxing TTS onto video...")
    mixer = AudioMixer(output_dir="/tmp/f1-mixed-test")
    mix_result = await mixer.mux_audio_onto_video(
        video_path=INPUT_VIDEO,
        audio_path=tts_result.audio_path,
        scene_number=1,
        episode_id=0,
    )
    log.info(
        f"Mux done: tempo={mix_result.tempo_factor:.2f}x, "
        f"video={mix_result.video_duration:.2f}s, "
        f"audio={mix_result.audio_duration:.2f}s, "
        f"{mix_result.generation_time_ms}ms"
    )

    # 3. Copy to output and desktop
    output_path = OUTPUT_DIR / "scene_01_final.mp4"
    shutil.copy2(mix_result.output_path, str(output_path))
    log.info(f"Saved: {output_path}")

    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_final.mp4"
        shutil.copy2(mix_result.output_path, str(dest))
        log.info(f"Copied to desktop: {dest}")

    # 4. Probe the result
    import subprocess, json
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(output_path)],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    fmt = data["format"]
    log.info(f"Duration: {float(fmt['duration']):.2f}s")
    for s in data["streams"]:
        ct = s["codec_type"]
        if ct == "video":
            log.info(f"Video: {s['codec_name']} {s['width']}x{s['height']}")
        elif ct == "audio":
            log.info(f"Audio: {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")

    log.info("=== DONE — play scene_01_final.mp4 on your desktop ===")


if __name__ == "__main__":
    asyncio.run(main())
