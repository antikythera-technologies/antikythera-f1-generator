"""Test LTX lip-sync workflow: TTS speech drives character mouth movement.

Correct pipeline:
1. Generate TTS speech (Edge TTS)
2. Upload speech audio to ComfyUI
3. Encode speech into audio latent (LTXVAudioVAEEncode)
4. Encode start frame into video latent (LTXVImgToVideoConditionOnly)
5. Concatenate audio + video latents (LTXVConcatAVLatent)
6. Sample jointly with MultimodalGuider (audio cfg=7, video cfg=3)
7. Model generates video frames WITH lip-synced mouth movements
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

# Scene 1 dialogue
DIALOGUE = (
    "It's lights out and away we go! What a start from Verstappen, "
    "he's absolutely launched it off the line!"
)
CHARACTER = "david_croft"

# Video settings
WIDTH = 768
HEIGHT = 512
FPS = 24
SEED = 42
STEPS = 25


def build_lipsync_workflow(
    image_filename: str,
    audio_filename: str,
    frame_count: int,
) -> dict:
    """Build ComfyUI workflow with speech-driven lip sync.

    Uses LTXVAudioVAEEncode to encode real speech audio, so the
    diffusion process generates mouth movements matching the speech.
    """
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
        # === Model Loading ===
        # 1: Load LTX checkpoint → MODEL, CLIP(null), VAE
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-2-19b-dev-fp8.safetensors"},
        },
        # 2: Load text encoder → CLIP
        "2": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors",
                "ckpt_name": "ltx-2-19b-dev-fp8.safetensors",
                "device": "default",
            },
        },
        # 3: Load audio VAE
        "3": {
            "class_type": "LTXVAudioVAELoader",
            "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"},
        },

        # === Text Conditioning ===
        # 4: Positive prompt (describes speaking character)
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": video_prompt, "clip": ["2", 0]},
        },
        # 5: Negative prompt
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": neg_prompt, "clip": ["2", 0]},
        },

        # === Video Latent (from start frame image) ===
        # 6: Load start frame image
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        # 7: Preprocess image (compress slightly for video consistency)
        "7": {
            "class_type": "LTXVPreprocess",
            "inputs": {
                "image": ["6", 0],
                "img_compression": 18,  # Low compression, high quality
            },
        },
        # 8: Create empty video latent
        "8": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {
                "width": WIDTH,
                "height": HEIGHT,
                "length": frame_count,
                "batch_size": 1,
            },
        },
        # 9: Conditioning — frame rate
        "9": {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "frame_rate": float(FPS),
            },
        },
        # 10: Crop guides to match latent
        "10": {
            "class_type": "LTXVCropGuides",
            "inputs": {
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent": ["8", 0],
            },
        },
        # 11: Inject start frame as conditioning into video latent
        "11": {
            "class_type": "LTXVImgToVideoConditionOnly",
            "inputs": {
                "vae": ["1", 2],
                "image": ["7", 0],        # preprocessed image
                "latent": ["10", 2],       # cropped latent
                "strength": 0.7,           # 0.7 for I2V with audio
            },
        },

        # === Audio Latent (from TTS speech) ===
        # 12: Load TTS speech audio
        "12": {
            "class_type": "LoadAudio",
            "inputs": {"audio": audio_filename},
        },
        # 13: Encode speech audio into audio latent
        # This is the KEY node: encodes real speech so the model
        # generates lip movements matching the speech patterns.
        "13": {
            "class_type": "LTXVAudioVAEEncode",
            "inputs": {
                "audio": ["12", 0],
                "audio_vae": ["3", 0],
            },
        },

        # === Combine Audio + Video ===
        # 14: Concatenate video and audio latents
        "14": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": ["11", 0],   # image-conditioned video latent
                "audio_latent": ["13", 0],   # speech-encoded audio latent
            },
        },

        # === Sampling (MultimodalGuider for separate audio/video control) ===
        # 15: Video guidance parameters
        "15": {
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
        # 16: Audio guidance parameters (chained after video)
        "16": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "AUDIO",
                "cfg": 7.0,
                "stg": 1.0,
                "perturb_attn": True,
                "rescale": 0.7,
                "modality_scale": 1.0,
                "skip_step": 0,
                "cross_attn": True,
                "parameters": ["15", 0],  # Chain after video params
            },
        },
        # 17: MultimodalGuider (replaces simple KSampler/CFGGuider)
        "17": {
            "class_type": "MultimodalGuider",
            "inputs": {
                "model": ["1", 0],
                "positive": ["10", 0],   # cropped positive conditioning
                "negative": ["10", 1],   # cropped negative conditioning
                "parameters": ["16", 0], # chained audio+video params
                "skip_blocks": "",
            },
        },
        # 18: Noise
        "18": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": SEED},
        },
        # 19: Scheduler
        "19": {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": STEPS,
                "max_shift": 2.05,
                "base_shift": 0.95,
                "stretch": True,
                "terminal": 0.1,
                "latent": ["14", 0],  # combined AV latent
            },
        },
        # 20: Sampler select
        "20": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        # 21: Sample!
        "21": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["18", 0],
                "guider": ["17", 0],
                "sampler": ["20", 0],
                "sigmas": ["19", 0],
                "latent_image": ["14", 0],  # combined AV latent
            },
        },

        # === Decode & Output ===
        # 22: Separate audio and video latents
        "22": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["21", 1]},  # denoised output
        },
        # 23: Decode video frames
        "23": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["22", 0],  # video latent
                "vae": ["1", 2],
            },
        },
        # 24: Decode audio waveform
        "24": {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {
                "samples": ["22", 1],  # audio latent
                "audio_vae": ["3", 0],
            },
        },
        # 25: Create video from frames + audio
        "25": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["23", 0],
                "audio": ["24", 0],
                "fps": float(FPS),
            },
        },
        # 26: Save video
        "26": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["25", 0],
                "filename_prefix": "ltx2_lipsync_scene1",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


async def generate_tts() -> tuple[str, float]:
    """Generate TTS speech and return (path, duration)."""
    import sys, os
    sys.path.insert(0, str(REPO_ROOT / "backend"))

    from app.services.tts_generator import TTSGenerator

    tts = TTSGenerator(output_dir="/tmp/f1-lipsync-test")
    result = await tts.generate_speech(
        text=DIALOGUE,
        character_name=CHARACTER,
        scene_number=1,
        episode_id=0,
    )
    log.info(
        f"TTS: {result.duration_seconds:.2f}s, voice={result.voice_used}, "
        f"{result.generation_time_ms}ms"
    )
    return result.audio_path, result.duration_seconds


async def upload_audio(audio_path: str) -> str:
    """Upload audio file to ComfyUI and return the stored filename."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(audio_path, "rb") as f:
            files = {"image": (Path(audio_path).name, f, "audio/mpeg")}
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files=files,
                data={"overwrite": "true"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Audio upload failed: {resp.status_code} {resp.text[:200]}")
        name = resp.json().get("name", Path(audio_path).name)
        log.info(f"Audio uploaded as: {name}")
        return name


async def main():
    log.info("=== LTX Lip-Sync Test ===")
    log.info(f"Dialogue: {DIALOGUE[:80]}...")

    # 1. Generate TTS speech
    log.info("Step 1: Generating TTS speech...")
    audio_path, audio_duration = await generate_tts()

    # Calculate frame count from audio duration (must be 8n+1)
    raw_frames = int(audio_duration * FPS) + 1
    frame_count = ((raw_frames - 1 + 7) // 8) * 8 + 1  # Round up to 8n+1
    frame_count = max(frame_count, 121)  # Minimum 5s
    video_duration = (frame_count - 1) / FPS
    log.info(
        f"Audio: {audio_duration:.2f}s → {frame_count} frames "
        f"({video_duration:.2f}s video)"
    )

    # 2. Upload image and audio to ComfyUI
    log.info("Step 2: Uploading image and audio...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Upload image
        with open(IMAGE_PATH, "rb") as f:
            files = {"image": (IMAGE_PATH.name, f, "image/png")}
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files=files,
                data={"overwrite": "true"},
            )
        image_filename = resp.json().get("name", IMAGE_PATH.name)
        log.info(f"Image uploaded as: {image_filename}")

    audio_filename = await upload_audio(audio_path)

    # 3. Build and queue workflow
    log.info("Step 3: Building lip-sync workflow...")
    workflow = build_lipsync_workflow(
        image_filename=image_filename,
        audio_filename=audio_filename,
        frame_count=frame_count,
    )

    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    log.info(f"Queuing workflow ({frame_count} frames, {STEPS} steps)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=payload)
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code}")
            # Parse error details
            try:
                err = resp.json()
                for node_id, node_err in err.get("node_errors", {}).items():
                    for e in node_err.get("errors", []):
                        log.error(f"  Node {node_id}: {e.get('message', '')} - {e.get('details', '')}")
            except Exception:
                log.error(resp.text[:500])
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # 4. Poll for completion
    log.info("Step 4: Waiting for generation (lip-sync takes longer)...")
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
                            log.error(f"Node {msg_data.get('node_id')}/{msg_data.get('node_type')}:")
                            log.error(f"  {msg_data.get('exception_message', '')[:500]}")
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
    output_path = OUTPUT_DIR / "scene_01_lipsync.mp4"

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
                        params={"filename": vid_filename, "subfolder": subfolder, "type": vid_type},
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

    # 6. Probe result
    import subprocess
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(output_path)],
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

    # 7. Copy to desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync.mp4"
        shutil.copy2(str(output_path), str(dest))
        log.info(f"Copied to desktop: {dest}")

    log.info("=== DONE — check scene_01_lipsync.mp4 ===")


if __name__ == "__main__":
    asyncio.run(main())
