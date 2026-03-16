"""Test LTX 2.3 lip-sync v7: Fixes from v6 + agent research.

v6 produced video but static (no animation). Fixes:
  1. skip_blocks="28" in MultimodalGuider (was "" - critical STG param for 2.3)
  2. Audio VAE from main checkpoint (official workflow does this)
  3. Steps=25 (was 15 - more steps for dev model without distilled LoRA)
  4. bypass=false explicit on LTXVImgToVideoConditionOnly
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

WIDTH = 768
HEIGHT = 512
FRAME_COUNT = 121
FPS = 24.0
SEED = 42
STEPS = 25   # More steps for dev model (no distilled LoRA)


def build_workflow(image_filename: str) -> dict:
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
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        },
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors",
                "device": "default",
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": pos_prompt, "clip": ["2", 0]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": neg_prompt, "clip": ["2", 0]},
        },
        # LTXVConditioning — wraps with frame_rate
        "5": {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["3", 0],
                "negative": ["4", 0],
                "frame_rate": FPS,
            },
        },
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        "7": {
            "class_type": "LTXVPreprocess",
            "inputs": {"image": ["6", 0], "img_compression": 18},
        },
        "8": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {
                "width": WIDTH,
                "height": HEIGHT,
                "length": FRAME_COUNT,
                "batch_size": 1,
            },
        },
        "9": {
            "class_type": "LTXVImgToVideoConditionOnly",
            "inputs": {
                "vae": ["1", 2],
                "image": ["7", 0],
                "latent": ["8", 0],
                "strength": 0.7,
                "bypass": False,  # explicit: DO apply I2V conditioning
            },
        },
        # FIX: Load audio VAE from main checkpoint (official 2.3 approach)
        "10": {
            "class_type": "LTXVAudioVAELoader",
            "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        },
        "11": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {
                "frames_number": FRAME_COUNT,
                "frame_rate": int(FPS),
                "batch_size": 1,
                "audio_vae": ["10", 0],
            },
        },
        "12": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["9", 0],
                "audio_latent": ["11", 0],
            },
        },
        # GuiderParameters: AUDIO first, then VIDEO chained
        "13": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "AUDIO",
                "cfg": 7.0,
                "stg": 1.0,
                "perturb_attn": True,
                "rescale": 0.7,
                "modality_scale": 3.0,
                "skip_step": 0,
                "cross_attn": True,
            },
        },
        "14": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "VIDEO",
                "cfg": 3.0,
                "stg": 1.0,
                "perturb_attn": True,
                "rescale": 0.9,
                "modality_scale": 3.0,
                "skip_step": 0,
                "cross_attn": True,
                "parameters": ["13", 0],
            },
        },
        # FIX: skip_blocks="28" (was "" in v6 — critical STG for LTX 2.3)
        "15": {
            "class_type": "MultimodalGuider",
            "inputs": {
                "model": ["1", 0],
                "positive": ["5", 0],
                "negative": ["5", 1],
                "parameters": ["14", 0],
                "skip_blocks": "28",
            },
        },
        "16": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": SEED},
        },
        "17": {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": STEPS,
                "max_shift": 2.05,
                "base_shift": 0.95,
                "stretch": True,
                "terminal": 0.1,
                "latent": ["12", 0],
            },
        },
        "18": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "19": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["16", 0],
                "guider": ["15", 0],
                "sampler": ["18", 0],
                "sigmas": ["17", 0],
                "latent_image": ["12", 0],
            },
        },
        "20": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["19", 0]},
        },
        "21": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["20", 0],
                "vae": ["1", 2],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 512,
                "temporal_overlap": 64,
            },
        },
        "22": {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {
                "samples": ["20", 1],
                "audio_vae": ["10", 0],
            },
        },
        "23": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["21", 0],
                "audio": ["22", 0],
                "fps": FPS,
            },
        },
        "24": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["23", 0],
                "filename_prefix": "ltx23_lipsync_v7",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def main():
    log.info("=== LTX 2.3 Lip-Sync v7 ===")
    log.info("Fixes: skip_blocks=28, audio VAE from checkpoint, steps=25")

    # Check ComfyUI
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{COMFYUI_URL}/system_stats")
        if resp.status_code != 200:
            log.error(f"ComfyUI not responding: {resp.status_code}")
            return
    log.info("ComfyUI alive.")

    # Upload image
    image_path = IMAGE_PATH
    if not image_path.exists():
        log.error(f"Image not found: {IMAGE_PATH}")
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(image_path, "rb") as f:
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={"image": (image_path.name, f, "image/png")},
                data={"overwrite": "true"},
            )
        uploaded_name = resp.json()["name"]
    log.info(f"Uploaded: {uploaded_name}")

    # Queue
    workflow = build_workflow(uploaded_name)
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
                if "error" in err:
                    log.error(f"  {err['error'].get('message', '')[:300]}")
            except Exception:
                log.error(resp.text[:500])
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt: {prompt_id}")

    # Wait
    log.info("Generating (~4-5 min with 25 steps)...")
    start = time.time()
    timeout = 900

    while (time.time() - start) < timeout:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        if resp.status_code == 200 and prompt_id in resp.json():
            result = resp.json()[prompt_id]
            status = result.get("status", {}).get("status_str", "unknown")
            if status == "success":
                log.info(f"Done in {time.time() - start:.0f}s")
                break
            elif status == "error":
                for mt, md in result.get("status", {}).get("messages", []):
                    if "error" in str(mt).lower():
                        log.error(f"Node {md.get('node_id')}/{md.get('node_type')}: {md.get('exception_message', '')[:400]}")
                        for line in md.get("traceback", [])[-3:]:
                            log.error(f"  {line.strip()}")
                return
        elapsed = int(time.time() - start)
        if elapsed % 30 == 0 and elapsed > 0:
            log.info(f"  {elapsed}s...")
        await asyncio.sleep(5)
    else:
        log.error("Timeout")
        return

    # Download
    outputs = result.get("outputs", {})
    output_path = OUTPUT_DIR / "scene_01_lipsync_v7.mp4"
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
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.get(
                        f"{COMFYUI_URL}/view",
                        params={"filename": fn, "subfolder": vid.get("subfolder", ""), "type": vid.get("type", "output")},
                    )
                if resp.status_code == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(resp.content)
                    log.info(f"Saved: {output_path} ({len(resp.content)/1024/1024:.1f} MB)")
                    downloaded = True
                    break
            if downloaded:
                break
        if downloaded:
            break

    if not downloaded:
        log.error("No video in output!")
        return

    # Probe
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(output_path)],
        capture_output=True, text=True,
    )
    if proc.stdout:
        data = json.loads(proc.stdout)
        dur = float(data.get("format", {}).get("duration", 0))
        size = int(data.get("format", {}).get("size", 0)) / 1024 / 1024
        log.info(f"Duration: {dur:.2f}s, Size: {size:.1f} MB")
        for s in data.get("streams", []):
            ct = s.get("codec_type", "?")
            if ct == "video":
                log.info(f"  Video: {s['codec_name']} {s['width']}x{s['height']} @ {int(s.get('bit_rate',0))/1000:.0f}kbps")
            elif ct == "audio":
                log.info(f"  Audio: {s['codec_name']} {s['sample_rate']}Hz {s['channels']}ch")

    # Desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync_v7.mp4"
        shutil.copy2(str(output_path), str(dest))
        log.info(f"Desktop: {dest}")

    log.info("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
