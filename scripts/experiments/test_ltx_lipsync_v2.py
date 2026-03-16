"""Test LTX lip-sync v2: Use LTX for video+lipsync, then mux original TTS audio back.

LTX generates lip-synced video when fed speech audio, but its audio decoder
produces garbled/non-English output. Solution: keep the LTX video (with
mouth movements), discard its audio, and mux the original TTS speech back on.

Pipeline:
1. Generate TTS speech (Edge TTS — clean English)
2. Upload speech to ComfyUI → LTX generates lip-synced video
3. Discard LTX audio, mux original TTS audio onto LTX video
"""

import asyncio
import json
import logging
import shutil
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


def build_lipsync_workflow(image_filename, audio_filename, frame_count):
    """Build lip-sync workflow (same as v1 — video has mouth movements)."""
    video_prompt = (
        "The character speaks directly to camera with expressive mouth movements "
        "and natural facial expressions. Lips move clearly in sync with speech. "
        "Maintain the caricature art style, colors, and character proportions. "
        "Subtle head movement and natural gestures while speaking. "
        "Professional broadcast studio setting."
    )
    neg_prompt = (
        "blurry, distorted, deformed, ugly, low quality, "
        "photorealistic, style change, morphing, static mouth, "
        "frozen face, no mouth movement"
    )

    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltx-2-19b-dev-fp8.safetensors"}},
        "2": {"class_type": "LTXAVTextEncoderLoader", "inputs": {"text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors", "ckpt_name": "ltx-2-19b-dev-fp8.safetensors", "device": "default"}},
        "3": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": video_prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": neg_prompt, "clip": ["2", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
        "7": {"class_type": "LTXVPreprocess", "inputs": {"image": ["6", 0], "img_compression": 18}},
        "8": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": WIDTH, "height": HEIGHT, "length": frame_count, "batch_size": 1}},
        "9": {"class_type": "LTXVConditioning", "inputs": {"positive": ["4", 0], "negative": ["5", 0], "frame_rate": float(FPS)}},
        "10": {"class_type": "LTXVCropGuides", "inputs": {"positive": ["9", 0], "negative": ["9", 1], "latent": ["8", 0]}},
        "11": {"class_type": "LTXVImgToVideoConditionOnly", "inputs": {"vae": ["1", 2], "image": ["7", 0], "latent": ["10", 2], "strength": 0.7}},
        "12": {"class_type": "LoadAudio", "inputs": {"audio": audio_filename}},
        "13": {"class_type": "LTXVAudioVAEEncode", "inputs": {"audio": ["12", 0], "audio_vae": ["3", 0]}},
        "14": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["11", 0], "audio_latent": ["13", 0]}},
        "15": {"class_type": "GuiderParameters", "inputs": {"modality": "VIDEO", "cfg": 3.0, "stg": 1.0, "perturb_attn": True, "rescale": 0.7, "modality_scale": 1.0, "skip_step": 0, "cross_attn": True}},
        "16": {"class_type": "GuiderParameters", "inputs": {"modality": "AUDIO", "cfg": 7.0, "stg": 1.0, "perturb_attn": True, "rescale": 0.7, "modality_scale": 1.0, "skip_step": 0, "cross_attn": True, "parameters": ["15", 0]}},
        "17": {"class_type": "MultimodalGuider", "inputs": {"model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1], "parameters": ["16", 0], "skip_blocks": ""}},
        "18": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "19": {"class_type": "LTXVScheduler", "inputs": {"steps": STEPS, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1, "latent": ["14", 0]}},
        "20": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "21": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["18", 0], "guider": ["17", 0], "sampler": ["20", 0], "sigmas": ["19", 0], "latent_image": ["14", 0]}},
        "22": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["21", 1]}},
        # Only decode VIDEO — we discard LTX audio and use original TTS
        "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["1", 2]}},
        # Still decode audio for CreateVideo (required input), but we'll replace it
        "24": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["22", 1], "audio_vae": ["3", 0]}},
        "25": {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "audio": ["24", 0], "fps": float(FPS)}},
        "26": {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": "ltx2_lipsync_v2", "format": "mp4", "codec": "h264"}},
    }


async def generate_tts():
    """Generate TTS speech."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.services.tts_generator import TTSGenerator

    tts = TTSGenerator(output_dir="/tmp/f1-lipsync-v2")
    result = await tts.generate_speech(
        text=DIALOGUE, character_name=CHARACTER, scene_number=1, episode_id=0,
    )
    log.info(f"TTS: {result.duration_seconds:.2f}s, voice={result.voice_used}")
    return result.audio_path, result.duration_seconds


async def mux_original_tts(ltx_video_path: str, tts_audio_path: str, output_path: str):
    """Replace LTX garbled audio with original clean TTS speech.

    Uses ffmpeg to:
    1. Take video stream from LTX output (has lip-synced mouth movements)
    2. Take audio stream from original TTS file (clean English speech)
    3. Speed up/pad TTS audio to match video duration
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.services.audio_mixer import AudioMixer

    mixer = AudioMixer(output_dir="/tmp/f1-lipsync-v2-mixed")
    result = await mixer.mux_audio_onto_video(
        video_path=ltx_video_path,
        audio_path=tts_audio_path,
        scene_number=1,
        episode_id=0,
    )
    shutil.copy2(result.output_path, output_path)
    log.info(f"Muxed: tempo={result.tempo_factor:.2f}x, {result.generation_time_ms}ms")
    return result


async def main():
    log.info("=== LTX Lip-Sync v2: Video from LTX + Audio from TTS ===")

    # Step 1: Generate TTS
    log.info("Step 1: Generating TTS speech...")
    tts_audio_path, audio_duration = await generate_tts()

    # Calculate frames to match audio
    raw_frames = int(audio_duration * FPS) + 1
    frame_count = ((raw_frames - 1 + 7) // 8) * 8 + 1
    frame_count = max(frame_count, 121)
    log.info(f"Audio: {audio_duration:.2f}s → {frame_count} frames")

    # Step 2: Upload image + audio to ComfyUI
    log.info("Step 2: Uploading to ComfyUI...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(IMAGE_PATH, "rb") as f:
            resp = await client.post(f"{COMFYUI_URL}/upload/image", files={"image": (IMAGE_PATH.name, f, "image/png")}, data={"overwrite": "true"})
        image_filename = resp.json()["name"]

        with open(tts_audio_path, "rb") as f:
            resp = await client.post(f"{COMFYUI_URL}/upload/image", files={"image": (Path(tts_audio_path).name, f, "audio/mpeg")}, data={"overwrite": "true"})
        audio_filename = resp.json()["name"]

    log.info(f"Image: {image_filename}, Audio: {audio_filename}")

    # Step 3: Queue lip-sync workflow
    log.info("Step 3: Queuing lip-sync workflow...")
    workflow = build_lipsync_workflow(image_filename, audio_filename, frame_count)
    client_id = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow, "client_id": client_id})
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

    # Step 4: Wait for generation
    log.info("Step 4: Waiting for LTX generation...")
    start = time.time()
    timeout = 900

    while (time.time() - start) < timeout:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        if resp.status_code == 200:
            data = resp.json()
            if prompt_id in data:
                result = data[prompt_id]
                status = result.get("status", {}).get("status_str", "unknown")
                if status == "success":
                    log.info(f"LTX done in {time.time() - start:.1f}s")
                    break
                elif status == "error":
                    msgs = result.get("status", {}).get("messages", [])
                    for mt, md in msgs:
                        if "error" in str(mt).lower():
                            log.error(f"Node {md.get('node_id')}: {md.get('exception_message', '')[:300]}")
                    return
        elapsed = int(time.time() - start)
        if elapsed % 60 == 0 and elapsed > 0:
            log.info(f"  Still generating... ({elapsed}s)")
        await asyncio.sleep(5)
    else:
        log.error(f"Timeout after {timeout}s")
        return

    # Step 5: Download LTX video (has lip sync but garbled audio)
    log.info("Step 5: Downloading LTX video...")
    outputs = result.get("outputs", {})
    ltx_video_path = str(OUTPUT_DIR / "scene_01_lipsync_raw.mp4")

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
                    resp = await client.get(f"{COMFYUI_URL}/view", params={"filename": fn, "subfolder": vid.get("subfolder", ""), "type": vid.get("type", "output")})
                if resp.status_code == 200:
                    Path(ltx_video_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(ltx_video_path).write_bytes(resp.content)
                    log.info(f"LTX video saved: {len(resp.content) / 1024:.0f} KB")
                    break
            else:
                continue
            break
        else:
            continue
        break

    # Step 6: Replace LTX audio with original TTS speech
    log.info("Step 6: Replacing audio with original TTS speech...")
    final_path = str(OUTPUT_DIR / "scene_01_lipsync_final.mp4")
    await mux_original_tts(ltx_video_path, tts_audio_path, final_path)

    # Step 7: Verify
    import subprocess
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", final_path],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    log.info(f"Duration: {float(data['format']['duration']):.2f}s")
    for s in data["streams"]:
        ct = s["codec_type"]
        if ct == "video":
            log.info(f"Video: {s['codec_name']} {s['width']}x{s['height']}")
        elif ct == "audio":
            log.info(f"Audio: {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")

    # Step 8: Copy to desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync_final.mp4"
        shutil.copy2(final_path, str(dest))
        log.info(f"Desktop: {dest}")

    log.info("=== DONE ===")
    log.info("Video: LTX lip-synced mouth movements")
    log.info("Audio: Original TTS English speech (David Croft)")


if __name__ == "__main__":
    asyncio.run(main())
