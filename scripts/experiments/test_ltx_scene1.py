"""Generate ONE LTX-2 video from scene 1 image for A/B comparison with OVI."""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

COMFYUI_URL = "https://tims42v3eaqrz7-19123.proxy.runpod.net"
IMAGE_PATH = "test-output/scene-images/test_verstappen_scene.png"
OUTPUT_PATH = "test-output/ltx2/scene1_comparison.mp4"

# Settings
WIDTH = 768
HEIGHT = 1344
FRAME_COUNT = 121  # ~5s at 24fps (must be 8n+1)
FPS = 24.0
SEED = 42
STEPS = 18
CFG = 2.0
DENOISE = 0.30
IMG_STRENGTH = 0.95  # LTXVImgToVideo conditioning strength


def build_workflow(image_filename: str) -> dict:
    pos_prompt = (
        "Animate this stylized caricature illustration with subtle, gentle motion. "
        "Maintain the EXACT art style, colors, lighting, and character proportions. "
        "Do NOT change the art style or make it more realistic. "
        "Add only subtle movement: slight head turn, gentle blinking, subtle breathing motion. "
        "The character looks directly at camera with a confident expression. "
        "Keep all motion minimal and subtle. "
        "The character should look like a gently animated illustration, "
        "not a re-drawn or reinterpreted image."
    )
    neg_prompt = (
        "blurry, distorted, deformed, ugly, low quality, "
        "photorealistic, different art style, style change, "
        "morphing, melting face, horror, grotesque"
    )

    return {
        # 1: Load LTX-2 checkpoint → MODEL, CLIP(null), VAE
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "ltx-2-19b-dev-fp8.safetensors",
            },
        },
        # 2: Load text encoder (Gemma 3 12B) → CLIP
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2-19b-dev-fp8.safetensors",
                "device": "default",
            },
        },
        # 3: Positive text conditioning
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": pos_prompt,
                "clip": ["2", 0],
            },
        },
        # 4: Negative text conditioning
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": neg_prompt,
                "clip": ["2", 0],
            },
        },
        # 5: Load source image
        "5": {
            "class_type": "LoadImage",
            "inputs": {
                "image": image_filename,
            },
        },
        # 6: Image-to-video conditioning (encodes image + creates latent)
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
        # 7: Sample video frames
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],
                "negative": ["6", 1],
                "latent_image": ["6", 2],
                "seed": SEED,
                "steps": STEPS,
                "cfg": CFG,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": DENOISE,
            },
        },
        # 8: Decode latent → image frames
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["7", 0],
                "vae": ["1", 2],
            },
        },
        # 9: Create video from frames
        "9": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["8", 0],
                "fps": FPS,
            },
        },
        # 10: Save video
        "10": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["9", 0],
                "filename_prefix": "ltx2_scene1",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def main():
    log.info("=== LTX-2 Scene 1 Generation (for OVI comparison) ===")

    # 1. Check ComfyUI
    log.info(f"Checking ComfyUI at {COMFYUI_URL}...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{COMFYUI_URL}/system_stats")
        if resp.status_code != 200:
            log.error(f"ComfyUI not responding: {resp.status_code}")
            return
    log.info("ComfyUI is alive.")

    # 2. Upload image
    image_path = Path(IMAGE_PATH)
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

    log.info(f"Queuing workflow (denoise={DENOISE}, strength={IMG_STRENGTH}, steps={STEPS}, cfg={CFG})...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=payload)
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code} {resp.text[:500]}")
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # 4. Poll for completion
    log.info("Waiting for generation...")
    start = time.time()
    timeout = 600

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
                    # Get detailed error
                    msgs = result.get("status", {}).get("messages", [])
                    for msg_type, msg_data in msgs:
                        if "error" in msg_type:
                            log.error(f"Error in node {msg_data.get('node_id')}/{msg_data.get('node_type')}:")
                            log.error(f"  {msg_data.get('exception_message', 'unknown')[:300]}")
                    return

        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            log.info(f"  Still generating... ({elapsed}s)")
        await asyncio.sleep(3)
    else:
        log.error(f"Timeout after {timeout}s")
        return

    # 5. Download video
    outputs = result.get("outputs", {})
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
                    out = Path(OUTPUT_PATH)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(resp.content)
                    size_kb = len(resp.content) / 1024
                    log.info(f"Saved: {OUTPUT_PATH} ({size_kb:.0f} KB)")
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

    log.info("=== DONE ===")
    log.info(f"LTX-2:  {OUTPUT_PATH}")
    log.info(f"OVI:    test-output/ovi/test_verstappen.mp4")


if __name__ == "__main__":
    asyncio.run(main())
