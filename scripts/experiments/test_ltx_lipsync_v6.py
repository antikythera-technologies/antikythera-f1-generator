"""Test LTX 2.3 lip-sync v6: Official workflow from ComfyUI-LTXVideo examples.

v5 FAILURE ROOT CAUSE: Used LTX 2.0 workflow nodes with LTX 2.3 checkpoint.
Result was a static image + audio (no video animation).

v6 uses the OFFICIAL LTX 2.3 workflow from:
  ComfyUI-LTXVideo/example_workflows/2.3/LTX-2.3_T2V_I2V_Single_Stage_Distilled_Full.json

Key differences from v5:
  1. SamplerCustomAdvanced + MultimodalGuider  (not KSampler)
  2. EmptyLTXVLatentVideo + LTXVImgToVideoConditionOnly  (not LTXVImgToVideo)
  3. CLIPTextEncode → LTXVConditioning (adds frame_rate)  (not direct to sampler)
  4. LTXVPreprocess for image preprocessing  (not raw LoadImage)
  5. VAEDecodeTiled  (not VAEDecode)
  6. GuiderParameters chain: AUDIO(cfg=7) → VIDEO(cfg=3) → MultimodalGuider

LTX 2.3 generates speech from text prompt natively:
  Include dialogue in quotes: 'he says "Hello world"'
  The model generates video + audio with lip-synced speech in one pass.
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

# Dialogue — included directly in the text prompt for native speech generation
DIALOGUE = (
    "It's lights out and away we go! What a start from Verstappen, "
    "he's absolutely launched it off the line!"
)

# Video settings (from official workflow)
WIDTH = 768
HEIGHT = 512
FRAME_COUNT = 121  # 5s at 24fps (must be 8n+1)
FPS = 24.0
SEED = 42

# Sampler settings (from official workflow "full" path)
STEPS = 15
MAX_SHIFT = 2.05
BASE_SHIFT = 0.95

# Guider parameters (from official workflow)
VIDEO_CFG = 3.0
VIDEO_STG = 1.0
VIDEO_RESCALE = 0.9
AUDIO_CFG = 7.0
AUDIO_STG = 1.0
AUDIO_RESCALE = 0.7

# Image conditioning
IMG_STRENGTH = 0.7    # From official workflow (was 0.95 in v5)
IMG_COMPRESSION = 18  # LTXVPreprocess compression level


def build_workflow(image_filename: str) -> dict:
    """Build LTX 2.3 AV workflow matching the official example.

    Node flow:
      LoadImage → LTXVPreprocess → LTXVImgToVideoConditionOnly
      CheckpointLoader → LTXAVTextEncoderLoader → CLIPTextEncode(+/-)
        → LTXVConditioning (adds frame_rate)
      EmptyLTXVLatentVideo + LTXVEmptyLatentAudio → LTXVConcatAVLatent
      GuiderParams(AUDIO) → GuiderParams(VIDEO) → MultimodalGuider
      RandomNoise + LTXVScheduler + KSamplerSelect → SamplerCustomAdvanced
      → LTXVSeparateAVLatent → VAEDecodeTiled + LTXVAudioVAEDecode
      → CreateVideo → SaveVideo
    """
    # Speech prompt: dialogue in quotes for native lip sync
    pos_prompt = (
        f'The character is a male sports commentator speaking directly to camera. '
        f'He says "{DIALOGUE}" '
        f'Natural lip movements perfectly synchronized with speech, '
        f'expressive facial animation, subtle head movement, enthusiastic delivery. '
        f'Maintain the caricature art style, colors, and character proportions. '
        f'Professional broadcast studio setting, front-facing portrait.'
    )
    neg_prompt = (
        "blurry, distorted, deformed, ugly, low quality, "
        "photorealistic, style change, morphing, static mouth, "
        "frozen face, no mouth movement, closed mouth, "
        "silent, no speech, mute"
    )

    return {
        # === Model Loading ===
        # 1: LTX 2.3 checkpoint → MODEL, CLIP(null), VAE
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        },
        # 2: Text encoder (Gemma 3 12B) → CLIP
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors",
                "device": "default",
            },
        },

        # === Text Conditioning ===
        # 3: Positive prompt (with dialogue for speech generation)
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": pos_prompt, "clip": ["2", 0]},
        },
        # 4: Negative prompt
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": neg_prompt, "clip": ["2", 0]},
        },
        # 5: LTXVConditioning — wraps conditioning with frame_rate
        #    (THIS WAS MISSING IN v5 — critical for LTX 2.3)
        "5": {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "frame_rate": FPS,
            },
        },

        # === Image Loading & Preprocessing ===
        # 6: Load source image
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        # 7: LTXVPreprocess — compression for image conditioning
        #    (THIS WAS MISSING IN v5)
        "7": {
            "class_type": "LTXVPreprocess",
            "inputs": {
                "image": ["6", 0],
                "img_compression": IMG_COMPRESSION,
            },
        },

        # === Latent Setup ===
        # 8: Empty video latent
        "8": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {
                "width": WIDTH,
                "height": HEIGHT,
                "length": FRAME_COUNT,
                "batch_size": 1,
            },
        },
        # 9: Image-to-video conditioning (applies start frame to latent)
        #    Uses LTXVImgToVideoConditionOnly (NOT LTXVImgToVideo from v5)
        "9": {
            "class_type": "LTXVImgToVideoConditionOnly",
            "inputs": {
                "vae": ["1", 2],
                "image": ["7", 0],     # preprocessed image
                "latent": ["8", 0],    # empty video latent
                "strength": IMG_STRENGTH,
            },
        },

        # === Audio Latent ===
        # 10: Audio VAE loader
        "10": {
            "class_type": "LTXVAudioVAELoader",
            "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"},
        },
        # 11: Empty audio latent (LTX 2.3 generates speech from text prompt)
        "11": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {
                "frames_number": FRAME_COUNT,
                "frame_rate": int(FPS),
                "batch_size": 1,
                "audio_vae": ["10", 0],
            },
        },

        # === Combine AV Latents ===
        # 12: Concatenate video + audio latents
        "12": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["9", 0],    # I2V conditioned video latent
                "audio_latent": ["11", 0],   # empty audio latent
            },
        },

        # === Guider Setup (MultimodalGuider with separate audio/video CFG) ===
        # 13: Audio guider parameters
        "13": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "AUDIO",
                "cfg": AUDIO_CFG,
                "stg": AUDIO_STG,
                "perturb_attn": True,
                "rescale": AUDIO_RESCALE,
                "modality_scale": 3.0,
                "skip_step": 0,
                "cross_attn": True,
            },
        },
        # 14: Video guider parameters (chained after audio)
        "14": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "VIDEO",
                "cfg": VIDEO_CFG,
                "stg": VIDEO_STG,
                "perturb_attn": True,
                "rescale": VIDEO_RESCALE,
                "modality_scale": 3.0,
                "skip_step": 0,
                "cross_attn": True,
                "parameters": ["13", 0],  # chain after audio params
            },
        },
        # 15: MultimodalGuider
        "15": {
            "class_type": "MultimodalGuider",
            "inputs": {
                "model": ["1", 0],
                "positive": ["5", 0],    # from LTXVConditioning
                "negative": ["5", 1],    # from LTXVConditioning
                "parameters": ["14", 0],  # chained guider params
                "skip_blocks": "",
            },
        },

        # === Sampling ===
        # 16: Random noise
        "16": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": SEED},
        },
        # 17: LTX scheduler
        "17": {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": STEPS,
                "max_shift": MAX_SHIFT,
                "base_shift": BASE_SHIFT,
                "stretch": True,
                "terminal": 0.1,
                "latent": ["12", 0],  # combined AV latent
            },
        },
        # 18: Sampler selection (euler — substitute for ClownSampler_Beta)
        "18": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        # 19: SamplerCustomAdvanced (NOT KSampler — critical fix from v5)
        "19": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["16", 0],
                "guider": ["15", 0],     # MultimodalGuider
                "sampler": ["18", 0],    # KSamplerSelect
                "sigmas": ["17", 0],     # LTXVScheduler
                "latent_image": ["12", 0],  # combined AV latent
            },
        },

        # === Decode & Output ===
        # 20: Separate AV latents
        "20": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["19", 0]},  # output from sampler
        },
        # 21: Decode video (tiled — critical fix from v5)
        "21": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["20", 0],  # video latent
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 512,
                "temporal_overlap": 64,
            },
        },
        # 22: Decode audio
        "22": {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {
                "samples": ["20", 1],  # audio latent
                "audio_vae": ["10", 0],
            },
        },
        # 23: Create video (combine frames + audio)
        "23": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["21", 0],
                "audio": ["22", 0],
                "fps": FPS,
            },
        },
        # 24: Save video
        "24": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["23", 0],
                "filename_prefix": "ltx23_lipsync_v6",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def main():
    log.info("=== LTX 2.3 Lip-Sync v6: Official Workflow ===")
    log.info(f"Checkpoint: ltx-2.3-22b-dev-fp8.safetensors (22B)")
    log.info(f"Key fixes: LTXVConditioning, LTXVPreprocess, MultimodalGuider,")
    log.info(f"  SamplerCustomAdvanced, VAEDecodeTiled, LTXVImgToVideoConditionOnly")
    log.info(f"Dialogue: {DIALOGUE[:60]}...")

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

    log.info("Queuing LTX 2.3 official AV workflow...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=payload)
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code}")
            try:
                err = resp.json()
                # Show validation errors
                for nid, nerr in err.get("node_errors", {}).items():
                    for e in nerr.get("errors", []):
                        log.error(f"  Node {nid}: {e.get('message')} - {e.get('details')}")
                # Show general error
                if "error" in err:
                    log.error(f"  Error: {err['error'].get('message', '')[:300]}")
            except Exception:
                log.error(resp.text[:500])
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # 4. Poll for completion
    log.info("Waiting for generation (~3 min for AV)...")
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
                            tb = msg_data.get("traceback", [])
                            if tb:
                                for line in tb[-5:]:
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
    output_path = OUTPUT_DIR / "scene_01_lipsync_v6.mp4"
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
                async with httpx.AsyncClient(timeout=120.0) as client:
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
                    size_mb = len(resp.content) / (1024 * 1024)
                    log.info(f"Saved: {output_path} ({size_mb:.1f} MB)")
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
        size_mb = int(data.get("format", {}).get("size", 0)) / (1024 * 1024)
        log.info(f"Duration: {dur:.2f}s, Size: {size_mb:.1f} MB")
        for s in data.get("streams", []):
            codec_type = s.get("codec_type", "?")
            codec_name = s.get("codec_name", "?")
            if codec_type == "video":
                w, h = s.get("width", "?"), s.get("height", "?")
                br = int(s.get("bit_rate", 0)) / 1000
                log.info(f"  Video: {codec_name} {w}x{h} @ {br:.0f} kbps")
            elif codec_type == "audio":
                sr = s.get("sample_rate", "?")
                ch = s.get("channels", "?")
                log.info(f"  Audio: {codec_name} {sr}Hz {ch}ch")

    # 7. Copy to desktop for playback
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync_v6.mp4"
        shutil.copy2(str(output_path), str(dest))
        log.info(f"Copied to desktop: {dest}")

    log.info("=== DONE ===")
    log.info("")
    log.info("v6 uses the OFFICIAL LTX 2.3 workflow with:")
    log.info("  - LTXVConditioning (frame_rate aware conditioning)")
    log.info("  - LTXVPreprocess (image compression for better I2V)")
    log.info("  - MultimodalGuider + GuiderParameters (audio/video CFG)")
    log.info("  - SamplerCustomAdvanced (not KSampler)")
    log.info("  - VAEDecodeTiled (memory efficient)")
    log.info("  - Dialogue in text prompt for native speech + lip sync")


if __name__ == "__main__":
    asyncio.run(main())
