"""Test LTX Audio-Visual workflow: single start frame + native audio generation.

Fix: denoise=1.0 (was 0.30) — the audio latent starts empty and needs full
denoising. LTXVImgToVideo conditioning handles image guidance independently.
"""

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
IMAGE_PATH = "test-output/scene-images/scene_01_start.png"
OUTPUT_DIR = Path("test-output/scene-videos")

# Video settings
WIDTH = 768
HEIGHT = 512
FRAME_COUNT = 121  # ~5s at 24fps (must be 8n+1)
FPS = 24.0
SEED = 42
STEPS = 25
CFG = 4.0
DENOISE = 1.0  # CRITICAL: must be 1.0 for AV latent (audio starts empty)
IMG_STRENGTH = 0.95

# Audio prompt — describe the sounds that should accompany the scene
AUDIO_PROMPT = (
    "Formula 1 race ambiance, crowd cheering, engines revving in the distance, "
    "excited murmur of spectators, broadcast-style atmosphere"
)


def build_av_workflow(image_filename: str) -> dict:
    """Build LTX Audio-Visual workflow with native audio generation."""
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
        # 3: Positive text conditioning (video prompt)
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
            "inputs": {
                "ckpt_name": "LTX2_audio_vae_bf16.safetensors",
            },
        },
        # 8: Create empty audio latent (will be denoised by KSampler)
        "8": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {
                "frames_number": FRAME_COUNT,
                "frame_rate": int(FPS),
                "batch_size": 1,
                "audio_vae": ["7", 0],
            },
        },
        # 9: Concatenate video + audio latents for joint denoising
        "9": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["6", 2],   # latent from LTXVImgToVideo
                "audio_latent": ["8", 0],
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
            "inputs": {
                "av_latent": ["10", 0],
            },
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
                "fps": FPS,
            },
        },
        # 15: Save video
        "15": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": "ltx2_av_scene1",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def main():
    log.info("=== LTX Audio-Visual Scene 1 Test ===")
    log.info(f"Parameters: denoise={DENOISE}, cfg={CFG}, steps={STEPS}, img_strength={IMG_STRENGTH}")

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
    workflow = build_av_workflow(uploaded_name)
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    log.info("Queuing AV workflow...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=payload)
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code} {resp.text[:500]}")
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # 4. Poll for completion
    log.info("Waiting for generation (AV takes longer than video-only)...")
    start = time.time()
    timeout = 900  # 15 min for AV generation

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
                            log.error(f"Error in node {msg_data.get('node_id')}/{msg_data.get('node_type')}:")
                            log.error(f"  {msg_data.get('exception_message', 'unknown')[:500]}")
                    return

        elapsed = int(time.time() - start)
        if elapsed % 30 == 0 and elapsed > 0:
            log.info(f"  Still generating... ({elapsed}s)")
        await asyncio.sleep(5)
    else:
        log.error(f"Timeout after {timeout}s")
        return

    # 5. Download video
    outputs = result.get("outputs", {})
    downloaded = False
    output_path = OUTPUT_DIR / "scene_01_ltx_av_v2.mp4"

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
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(output_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if stdout:
        streams = json.loads(stdout.decode())
        for s in streams.get("streams", []):
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
        import shutil
        dest = desktop / "scene_01_ltx_av_v2.mp4"
        shutil.copy2(str(output_path), str(dest))
        log.info(f"Copied to desktop: {dest}")

    log.info("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
