"""Test LTX lip-sync v4: Corrected workflow fixing 4 identified bugs.

Fixes from v1-v3:
  Bug 1: Audio MUST be >= video duration or conditioning fails entirely.
         → Pad audio AFTER calculating frame count to guarantee this.
  Bug 2: Wrong I2V node (LTXVImgToVideoConditionOnly + EmptyLatent + CropGuides).
         → Use unified LTXVImgToVideo (matches working AV test).
  Bug 3: FP8 model has known lip sync issues (ComfyUI #12161).
         → Flag for bf16 fallback if results still poor.
  Bug 4: Edge TTS outputs MP3 24kHz mono; LTX wants WAV 48kHz mono.
         → Convert TTS to WAV 48kHz mono before upload.

Pipeline:
  1. Generate TTS speech (Edge TTS → MP3)
  2. Convert MP3 → WAV 48kHz mono
  3. Calculate frame count (8n+1), then pad WAV to >= video duration
  4. Upload image + padded WAV to ComfyUI
  5. LTX generates lip-synced video (LTXVImgToVideo + LTXVAudioVAEEncode)
  6. Download LTX video (mouth movements synced to audio latent)
  7. Simple mux: strip LTX audio, replace with original TTS (stream copy, no tempo)
"""

import asyncio
import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

COMFYUI_URL = "https://tims42v3eaqrz7-19123.proxy.runpod.net"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE_PATH = REPO_ROOT / "test-output/scene-images/scene_01_start.png"
OUTPUT_DIR = REPO_ROOT / "test-output/scene-videos"

DIALOGUE = (
    "It's lights out and away we go! What a start from Verstappen, "
    "he's absolutely launched it off the line!"
)
CHARACTER = "david_croft"

WIDTH = 768
HEIGHT = 512
FPS = 24
SEED = 42
STEPS = 25
IMG_STRENGTH = 0.95  # High — preserve the caricature style


def calc_frame_count(audio_duration: float, fps: int) -> int:
    """Calculate frame count (8n+1) that fits within the audio duration.

    CRITICAL: Video duration must be <= audio duration, otherwise
    LTX audio conditioning fails entirely. We round DOWN to the
    nearest 8n+1 that fits, rather than rounding up.
    """
    max_frames = int(audio_duration * fps)  # Don't add +1 — stay under
    # Round DOWN to 8n+1: find largest (8n+1) <= max_frames
    n = (max_frames - 1) // 8
    frame_count = n * 8 + 1
    # Minimum viable clip: 3 seconds
    frame_count = max(frame_count, 73)  # 73 = 9*8+1 = 3.0s at 24fps
    return frame_count


def build_lipsync_workflow(
    image_filename: str,
    audio_filename: str,
    frame_count: int,
) -> dict:
    """Build corrected lip-sync workflow.

    Key differences from v1-v3:
      - Uses LTXVImgToVideo (unified node) instead of
        EmptyLTXVLatentVideo + LTXVCropGuides + LTXVImgToVideoConditionOnly
      - Audio encoded via LTXVAudioVAEEncode (speech conditioning)
      - MultimodalGuider for separate audio/video CFG control
      - Prompt explicitly describes character speaking the attached audio
    """
    video_prompt = (
        "The character speaks directly to camera, lips perfectly in sync "
        "with the provided audio. Natural mouth movements matching speech "
        "patterns, expressive facial expressions, subtle head movement. "
        "Maintain the caricature art style, colors, and character proportions. "
        "Professional broadcast studio setting, front-facing portrait."
    )
    neg_prompt = (
        "blurry, distorted, deformed, ugly, low quality, "
        "photorealistic, style change, morphing, static mouth, "
        "frozen face, no mouth movement, closed mouth"
    )

    return {
        # === Model Loading ===
        # 1: LTX checkpoint → MODEL, CLIP(null), VAE
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-2-19b-dev-fp8.safetensors"},
        },
        # 2: Text encoder (Gemma 3 12B) → CLIP
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2-19b-dev-fp8.safetensors",
                "device": "default",
            },
        },
        # 3: Audio VAE
        "3": {
            "class_type": "LTXVAudioVAELoader",
            "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"},
        },

        # === Text Conditioning ===
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": video_prompt, "clip": ["2", 0]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": neg_prompt, "clip": ["2", 0]},
        },

        # === Image → Video (unified node — FIX for Bug 2) ===
        # LTXVImgToVideo outputs: [0]=positive, [1]=negative, [2]=video_latent
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "7": {
            "class_type": "LTXVImgToVideo",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["1", 2],
                "image": ["6", 0],
                "width": WIDTH,
                "height": HEIGHT,
                "length": frame_count,
                "batch_size": 1,
                "strength": IMG_STRENGTH,
            },
        },

        # === Audio Latent (from TTS speech — FIX for Bug 1) ===
        # Audio has been pre-padded to >= video duration before upload.
        "8": {
            "class_type": "LoadAudio",
            "inputs": {"audio": audio_filename},
        },
        "9": {
            "class_type": "LTXVAudioVAEEncode",
            "inputs": {
                "audio": ["8", 0],
                "audio_vae": ["3", 0],
            },
        },

        # === Combine Audio + Video Latents ===
        "10": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["7", 2],   # from LTXVImgToVideo
                "audio_latent": ["9", 0],   # from LTXVAudioVAEEncode
            },
        },

        # === Sampling (MultimodalGuider for separate audio/video control) ===
        "11": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "VIDEO",
                "cfg": 3.0,
                "stg": 1.0,
                "perturb_attn": True,
                "rescale": 0.7,
                "modality_scale": 1.0,
                "skip_step": 0,
                "cross_attn": True,
            },
        },
        "12": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "AUDIO",
                "cfg": 7.0,         # High audio CFG for tight lip sync
                "stg": 1.0,
                "perturb_attn": True,
                "rescale": 0.7,
                "modality_scale": 1.0,
                "skip_step": 0,
                "cross_attn": True,
                "parameters": ["11", 0],  # Chain after video params
            },
        },
        "13": {
            "class_type": "MultimodalGuider",
            "inputs": {
                "model": ["1", 0],
                "positive": ["7", 0],   # conditioning from LTXVImgToVideo
                "negative": ["7", 1],   # conditioning from LTXVImgToVideo
                "parameters": ["12", 0],
                "skip_blocks": "",
            },
        },
        "14": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": SEED},
        },
        "15": {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": STEPS,
                "max_shift": 2.05,
                "base_shift": 0.95,
                "stretch": True,
                "terminal": 0.1,
                "latent": ["10", 0],  # combined AV latent
            },
        },
        "16": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "17": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["14", 0],
                "guider": ["13", 0],
                "sampler": ["16", 0],
                "sigmas": ["15", 0],
                "latent_image": ["10", 0],  # combined AV latent
            },
        },

        # === Decode & Output ===
        "18": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["17", 1]},  # denoised output
        },
        "19": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["18", 0],  # video latent
                "vae": ["1", 2],
            },
        },
        "20": {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {
                "samples": ["18", 1],  # audio latent
                "audio_vae": ["3", 0],
            },
        },
        "21": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["19", 0],
                "audio": ["20", 0],
                "fps": float(FPS),
            },
        },
        "22": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["21", 0],
                "filename_prefix": "ltx2_lipsync_v4",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def generate_tts() -> tuple[str, float]:
    """Generate TTS speech and return (mp3_path, duration)."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.services.tts_generator import TTSGenerator

    tts = TTSGenerator(output_dir="/tmp/f1-lipsync-v4")
    result = await tts.generate_speech(
        text=DIALOGUE, character_name=CHARACTER, scene_number=1, episode_id=0,
    )
    log.info(f"TTS: {result.duration_seconds:.2f}s, voice={result.voice_used}")
    return result.audio_path, result.duration_seconds


def convert_to_wav(mp3_path: str) -> str:
    """Convert MP3 to WAV 48kHz mono (FIX for Bug 4).

    LTX audio conditioning works best with WAV 48kHz mono.
    Edge TTS outputs MP3 24kHz mono — the low sample rate and
    lossy compression can degrade audio latent encoding.
    """
    wav_path = mp3_path.replace(".mp3", ".wav")
    cmd = [
        "ffmpeg", "-y",
        "-i", mp3_path,
        "-ar", "48000",     # 48kHz sample rate
        "-ac", "1",         # Mono
        "-c:a", "pcm_s16le",  # 16-bit PCM WAV
        wav_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"WAV conversion failed: {proc.stderr[-300:]}")
    log.info(f"Converted to WAV 48kHz mono: {Path(wav_path).name}")
    return wav_path


def get_duration(path: str) -> float:
    """Get media duration in seconds."""
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def pad_audio_to_duration(wav_path: str, target_seconds: float) -> str:
    """Pad WAV with silence to reach target duration (FIX for Bug 1).

    Audio MUST be >= video duration or LTX audio conditioning
    fails entirely. We add a small buffer (0.5s) beyond the video
    duration to be safe.
    """
    current = get_duration(wav_path)
    if current >= target_seconds:
        log.info(f"Audio {current:.2f}s already >= target {target_seconds:.2f}s")
        return wav_path

    pad_seconds = target_seconds - current
    padded_path = wav_path.replace(".wav", "_padded.wav")

    # Use ffmpeg to append silence
    cmd = [
        "ffmpeg", "-y",
        "-i", wav_path,
        "-af", f"apad=pad_dur={pad_seconds}",
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        padded_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Audio padding failed: {proc.stderr[-300:]}")

    new_dur = get_duration(padded_path)
    log.info(f"Padded audio: {current:.2f}s → {new_dur:.2f}s (target was {target_seconds:.2f}s)")
    return padded_path


async def main():
    log.info("=== LTX Lip-Sync v4: All Bugs Fixed ===")
    log.info("Fixes: audio>=video, LTXVImgToVideo, WAV 48kHz, explicit prompt")

    # Step 1: Generate TTS speech
    log.info("Step 1: Generating TTS speech...")
    mp3_path, tts_duration = await generate_tts()

    # Step 2: Convert MP3 → WAV 48kHz mono (Bug 4 fix)
    log.info("Step 2: Converting to WAV 48kHz mono...")
    wav_path = convert_to_wav(mp3_path)
    wav_duration = get_duration(wav_path)
    log.info(f"WAV duration: {wav_duration:.2f}s")

    # Step 3: Calculate frame count, then pad audio to match
    # Add 1.0s buffer to speech duration for post-speech silence in video
    padded_target = wav_duration + 1.0
    raw_frames = int(padded_target * FPS)
    # Round to nearest 8n+1 (round DOWN to stay within audio)
    frame_count = calc_frame_count(padded_target, FPS)
    video_duration = (frame_count - 1) / FPS

    # Now pad the audio to be >= video duration + safety margin
    audio_target = video_duration + 0.5  # 0.5s safety buffer
    padded_wav_path = pad_audio_to_duration(wav_path, audio_target)

    log.info(
        f"Timing: TTS={wav_duration:.2f}s → padded={get_duration(padded_wav_path):.2f}s, "
        f"video={video_duration:.2f}s ({frame_count} frames)"
    )

    # Verify: audio >= video (critical check)
    final_audio_dur = get_duration(padded_wav_path)
    assert final_audio_dur >= video_duration, (
        f"FATAL: audio {final_audio_dur:.2f}s < video {video_duration:.2f}s"
    )
    log.info(f"✓ Audio ({final_audio_dur:.2f}s) >= Video ({video_duration:.2f}s)")

    # Step 4: Upload image + audio to ComfyUI
    log.info("Step 4: Uploading to ComfyUI...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Upload image
        with open(IMAGE_PATH, "rb") as f:
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={"image": (IMAGE_PATH.name, f, "image/png")},
                data={"overwrite": "true"},
            )
        if resp.status_code != 200:
            log.error(f"Image upload failed: {resp.status_code} {resp.text[:200]}")
            return
        image_filename = resp.json()["name"]

        # Upload WAV audio (not MP3!)
        wav_name = Path(padded_wav_path).name
        with open(padded_wav_path, "rb") as f:
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={"image": (wav_name, f, "audio/wav")},
                data={"overwrite": "true"},
            )
        if resp.status_code != 200:
            log.error(f"Audio upload failed: {resp.status_code} {resp.text[:200]}")
            return
        audio_filename = resp.json()["name"]

    log.info(f"Uploaded — image: {image_filename}, audio: {audio_filename}")

    # Step 5: Build and queue workflow
    log.info("Step 5: Queuing lip-sync workflow...")
    workflow = build_lipsync_workflow(image_filename, audio_filename, frame_count)

    client_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code}")
            try:
                err = resp.json()
                for nid, nerr in err.get("node_errors", {}).items():
                    for e in nerr.get("errors", []):
                        log.error(f"  Node {nid}: {e.get('message')} - {e.get('details')}")
            except Exception:
                log.error(resp.text[:500])
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # Step 6: Wait for generation
    log.info("Step 6: Waiting for generation (AV lip-sync, expect ~2-3 min)...")
    start = time.time()
    timeout = 900

    while (time.time() - start) < timeout:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")

        if resp.status_code == 200 and prompt_id in resp.json():
            result = resp.json()[prompt_id]
            status = result.get("status", {}).get("status_str", "unknown")
            if status == "success":
                log.info(f"Generation complete in {time.time() - start:.1f}s")
                break
            elif status == "error":
                for mt, md in result.get("status", {}).get("messages", []):
                    if "error" in str(mt).lower():
                        log.error(
                            f"Node {md.get('node_id')}/{md.get('node_type')}: "
                            f"{md.get('exception_message', '')[:400]}"
                        )
                return

        elapsed = int(time.time() - start)
        if elapsed % 30 == 0 and elapsed > 0:
            log.info(f"  Still generating... ({elapsed}s)")
        await asyncio.sleep(5)
    else:
        log.error(f"Timeout after {timeout}s")
        return

    # Step 7: Download LTX video
    log.info("Step 7: Downloading LTX video...")
    outputs = result.get("outputs", {})
    ltx_path = str(OUTPUT_DIR / "scene_01_lipsync_v4_raw.mp4")
    downloaded = False

    for nid, nout in outputs.items():
        for key in ("videos", "gifs", "video", "images"):
            items = nout.get(key, [])
            if isinstance(items, dict):
                items = [items]
            for vid in items:
                if isinstance(vid, str):
                    vid = {"filename": vid}
                fn = vid.get("filename", "")
                if not fn:
                    continue
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{COMFYUI_URL}/view",
                        params={
                            "filename": fn,
                            "subfolder": vid.get("subfolder", ""),
                            "type": vid.get("type", "output"),
                        },
                    )
                if resp.status_code == 200:
                    Path(ltx_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(ltx_path).write_bytes(resp.content)
                    log.info(f"LTX video saved: {len(resp.content) / 1024:.0f} KB")
                    downloaded = True
                    break
            if downloaded:
                break
        if downloaded:
            break

    if not downloaded:
        log.error("No video found in output!")
        log.error(f"Outputs: {json.dumps({k: list(v.keys()) for k, v in outputs.items()}, indent=2)}")
        return

    # Step 8: Mux original TTS speech onto LTX video (simple stream replacement)
    # The LTX video has lip-synced mouth movements; the LTX audio is garbled.
    # Replace with original clean TTS audio — no tempo change, no offset.
    log.info("Step 8: Muxing original TTS speech...")
    final_path = str(OUTPUT_DIR / "scene_01_lipsync_v4_final.mp4")

    mux_cmd = [
        "ffmpeg", "-y",
        "-i", ltx_path,         # Input 0: LTX video (lip-synced)
        "-i", mp3_path,         # Input 1: Original TTS speech (clean)
        "-map", "0:v",          # Video from LTX
        "-map", "1:a",          # Audio from original TTS
        "-c:v", "copy",         # No video re-encode
        "-c:a", "aac",          # Encode audio as AAC
        "-b:a", "192k",
        "-ac", "2",
        "-ar", "44100",
        "-shortest",            # Cut at shortest stream
        final_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *mux_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error(f"Mux failed: {stderr.decode()[-300:]}")
        # Still have the raw LTX video with its own audio
        log.info(f"Raw LTX video (with LTX audio) at: {ltx_path}")
    else:
        log.info("Muxed successfully (LTX video + TTS audio)")

    # Step 9: Verify both outputs
    for label, path in [("Raw LTX", ltx_path), ("Final (TTS muxed)", final_path)]:
        if not Path(path).exists():
            continue
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True,
        )
        data = json.loads(proc.stdout)
        dur = float(data["format"]["duration"])
        log.info(f"{label}: {dur:.2f}s")
        for s in data["streams"]:
            ct = s["codec_type"]
            if ct == "video":
                log.info(f"  Video: {s['codec_name']} {s['width']}x{s['height']}")
            elif ct == "audio":
                log.info(f"  Audio: {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")

    # Step 10: Copy to desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        # Copy both raw and final for comparison
        for src, name in [
            (ltx_path, "scene_01_lipsync_v4_raw.mp4"),
            (final_path, "scene_01_lipsync_v4_final.mp4"),
        ]:
            if Path(src).exists():
                dest = desktop / name
                shutil.copy2(src, str(dest))
                log.info(f"Desktop: {dest}")

    log.info("=== DONE ===")
    log.info("Compare:")
    log.info("  _raw.mp4  = LTX video + LTX audio (lip sync should match LTX audio)")
    log.info("  _final.mp4 = LTX video + TTS audio (lip sync should match TTS speech)")
    log.info("")
    log.info("If _raw has good lip sync but _final doesn't, the mux timing is off.")
    log.info("If _raw has NO lip sync, the generation itself failed (try bf16 model).")


if __name__ == "__main__":
    asyncio.run(main())
