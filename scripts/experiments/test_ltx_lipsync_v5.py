"""Test LTX 2.3 lip-sync v5: Text-prompt dialogue (no audio conditioning).

LTX 2.3 (22B) generates speech + lip-synced video from TEXT PROMPT directly.
Include dialogue in the prompt and it produces both audio and matching mouth
movements in a single pass. No separate TTS → encode → mux pipeline needed.

This is a fundamentally different approach from v1-v4 which used:
  TTS → audio encode → LTXVAudioVAEEncode → MultimodalGuider → mux

v5 approach:
  Include dialogue text in prompt → LTX 2.3 generates video + audio natively
  Uses the same basic AV workflow as test_ltx_av_scene1.py but with:
    - LTX 2.3 checkpoint (ltx-2.3-22b-dev-fp8.safetensors)
    - Dialogue embedded in the positive prompt
    - Empty audio latent (LTX 2.3 generates speech from text)
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

# The dialogue the character should speak
DIALOGUE = (
    "It's lights out and away we go! What a start from Verstappen, "
    "he's absolutely launched it off the line!"
)
CHARACTER_DESCRIPTION = "a male sports commentator with an enthusiastic British accent"

# Video settings
WIDTH = 768
HEIGHT = 512
FRAME_COUNT = 121  # ~5s at 24fps (must be 8n+1)
FPS = 24
SEED = 42
STEPS = 25
CFG = 4.0
DENOISE = 1.0  # CRITICAL: must be 1.0 for AV latent (audio starts empty)
IMG_STRENGTH = 0.95


def build_workflow(image_filename: str) -> dict:
    """Build LTX 2.3 AV workflow with dialogue in text prompt.

    Key difference from v4: No audio conditioning (LTXVAudioVAEEncode).
    Instead, dialogue is embedded in the text prompt and LTX 2.3
    generates speech + lip-synced video natively from empty audio latent.
    """
    # Include dialogue directly in the prompt for LTX 2.3 speech generation
    pos_prompt = (
        f"The character speaks directly to camera and says: \"{DIALOGUE}\" "
        f"The speaker is {CHARACTER_DESCRIPTION}. "
        "Natural lip movements perfectly synchronized with speech, "
        "expressive facial animation, subtle head movement. "
        "Maintain the caricature art style, colors, and character proportions. "
        "Professional broadcast studio setting, front-facing portrait."
    )
    neg_prompt = (
        "blurry, distorted, deformed, ugly, low quality, "
        "photorealistic, style change, morphing, static mouth, "
        "frozen face, no mouth movement, closed mouth, "
        "silent, no speech, mute"
    )

    return {
        # 1: Load LTX 2.3 checkpoint → MODEL, CLIP(null), VAE
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        },
        # 2: Load text encoder (Gemma 3 12B) → CLIP
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors",
                "device": "default",
            },
        },
        # 3: Positive text conditioning (includes dialogue)
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": pos_prompt, "clip": ["2", 0]},
        },
        # 4: Negative text conditioning
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": neg_prompt, "clip": ["2", 0]},
        },
        # 5: Load source image
        "5": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        # 6: Image-to-video conditioning (single start frame)
        "6": {
            "class_type": "LTXVImgToVideo",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "vae": ["1", 2],
                "image": ["5", 0],
                "width": WIDTH,
                "height": HEIGHT,
                "length": FRAME_COUNT,
                "batch_size": 1,
                "strength": IMG_STRENGTH,
            },
        },
        # 7: Load audio VAE
        "7": {
            "class_type": "LTXVAudioVAELoader",
            "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"},
        },
        # 8: Create EMPTY audio latent (LTX 2.3 generates speech from text prompt)
        "8": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {
                "frames_number": FRAME_COUNT,
                "frame_rate": FPS,
                "batch_size": 1,
                "audio_vae": ["7", 0],
            },
        },
        # 9: Concatenate video + audio latents for joint denoising
        "9": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["6", 2],   # latent from LTXVImgToVideo
                "audio_latent": ["8", 0],   # EMPTY audio latent
            },
        },
        # 10: KSampler — joint audio+video denoising
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],     # conditioning from LTXVImgToVideo
                "negative": ["6", 1],
                "latent_image": ["9", 0],  # combined AV latent
                "seed": SEED,
                "steps": STEPS,
                "cfg": CFG,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": DENOISE,
            },
        },
        # 11: Separate audio and video latents after denoising
        "11": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["10", 0]},
        },
        # 12: Decode video latent → image frames
        "12": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["11", 0],  # video latent
                "vae": ["1", 2],
            },
        },
        # 13: Decode audio latent → audio waveform
        "13": {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {
                "samples": ["11", 1],  # audio latent
                "audio_vae": ["7", 0],
            },
        },
        # 14: Create video from frames + audio
        "14": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["12", 0],
                "audio": ["13", 0],
                "fps": float(FPS),
            },
        },
        # 15: Save video
        "15": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": "ltx23_lipsync_v5",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def main():
    log.info("=== LTX 2.3 Lip-Sync v5: Text-Prompt Dialogue ===")
    log.info("Approach: Dialogue in text prompt, LTX 2.3 generates speech natively")
    log.info(f"Checkpoint: ltx-2.3-22b-dev-fp8.safetensors (22B params)")
    log.info(f"Dialogue: {DIALOGUE[:80]}...")

    # 1. Check ComfyUI
    log.info(f"Checking ComfyUI at {COMFYUI_URL}...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{COMFYUI_URL}/system_stats")
        if resp.status_code != 200:
            log.error(f"ComfyUI not responding: {resp.status_code}")
            return
    log.info("ComfyUI is alive.")

    # 2. Upload image
    image_path = IMAGE_PATH
    if not image_path.exists():
        log.error(f"Image not found: {IMAGE_PATH}")
        return

    log.info(f"Uploading {image_path.name}...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files=files,
                data={"overwrite": "true"},
            )
        if resp.status_code != 200:
            log.error(f"Upload failed: {resp.status_code} {resp.text[:200]}")
            return
        uploaded_name = resp.json().get("name", image_path.name)
    log.info(f"Uploaded as: {uploaded_name}")

    # 3. Queue workflow
    workflow = build_workflow(uploaded_name)
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    log.info("Queuing LTX 2.3 AV workflow with dialogue prompt...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=payload)
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

    # 4. Poll for completion
    log.info("Waiting for generation (AV takes ~2-3 min)...")
    start = time.time()
    timeout = 900  # 15 min

    while (time.time() - start) < timeout:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")

        if resp.status_code == 200:
            data = resp.json()
            if prompt_id in data:
                result = data[prompt_id]
                status = result.get("status", {}).get("status_str", "unknown")
                if status == "success":
                    elapsed = time.time() - start
                    log.info(f"Generation complete in {elapsed:.1f}s")
                    break
                elif status == "error":
                    msgs = result.get("status", {}).get("messages", [])
                    for msg_type, msg_data in msgs:
                        if "error" in str(msg_type).lower():
                            log.error(
                                f"Error in node {msg_data.get('node_id')}/{msg_data.get('node_type')}:"
                            )
                            log.error(f"  {msg_data.get('exception_message', 'unknown')[:500]}")
                            traceback_lines = msg_data.get("traceback", [])
                            if traceback_lines:
                                log.error(f"  Traceback (last 3):")
                                for line in traceback_lines[-3:]:
                                    log.error(f"    {line.strip()}")
                    return

        elapsed = int(time.time() - start)
        if elapsed % 30 == 0 and elapsed > 0:
            log.info(f"  Still generating... ({elapsed}s)")
        await asyncio.sleep(5)
    else:
        log.error(f"Timeout after {timeout}s")
        return

    # 5. Download video
    log.info("Downloading output video...")
    outputs = result.get("outputs", {})
    output_path = OUTPUT_DIR / "scene_01_lipsync_v5.mp4"
    downloaded = False

    for node_id, node_output in outputs.items():
        for key in ("videos", "gifs", "video", "images"):
            items = node_output.get(key, [])
            if isinstance(items, dict):
                items = [items]
            for vid in items:
                if isinstance(vid, str):
                    vid = {"filename": vid}
                vid_filename = vid.get("filename", "")
                if not vid_filename:
                    continue
                subfolder = vid.get("subfolder", "")
                vid_type = vid.get("type", "output")

                log.info(f"Downloading {vid_filename}...")
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{COMFYUI_URL}/view",
                        params={
                            "filename": vid_filename,
                            "subfolder": subfolder,
                            "type": vid_type,
                        },
                    )

                if resp.status_code == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(resp.content)
                    size_kb = len(resp.content) / 1024
                    log.info(f"Saved: {output_path} ({size_kb:.0f} KB)")
                    downloaded = True
                    break
            if downloaded:
                break
        if downloaded:
            break

    if not downloaded:
        log.error("No video found in output!")
        log.error(f"Raw outputs: {json.dumps({k: list(v.keys()) for k, v in outputs.items()}, indent=2)}")
        return

    # 6. Probe the result
    log.info("Probing output...")
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(output_path)],
        capture_output=True, text=True,
    )
    if proc.stdout:
        data = json.loads(proc.stdout)
        dur = float(data.get("format", {}).get("duration", 0))
        log.info(f"Duration: {dur:.2f}s")
        for s in data.get("streams", []):
            codec_type = s.get("codec_type", "?")
            codec_name = s.get("codec_name", "?")
            if codec_type == "video":
                w, h = s.get("width", "?"), s.get("height", "?")
                log.info(f"  Video: {codec_name} {w}x{h}")
            elif codec_type == "audio":
                sr = s.get("sample_rate", "?")
                ch = s.get("channels", "?")
                log.info(f"  Audio: {codec_name} {sr}Hz {ch}ch")

    # 7. Copy to desktop for playback
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync_v5.mp4"
        shutil.copy2(str(output_path), str(dest))
        log.info(f"Copied to desktop: {dest}")

    log.info("=== DONE ===")
    log.info("")
    log.info("Expected result with LTX 2.3:")
    log.info("  - Character should SPEAK the dialogue with lip sync")
    log.info("  - Audio should be intelligible English speech")
    log.info("  - No muxing needed — this is native AV generation")
    log.info("")
    log.info("If audio is still garbled/non-English, try:")
    log.info("  1. Increase FRAME_COUNT for longer speech")
    log.info("  2. Simplify dialogue (shorter sentences)")
    log.info("  3. Try different SEED values")


if __name__ == "__main__":
    asyncio.run(main())
