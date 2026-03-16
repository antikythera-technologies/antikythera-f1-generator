"""Test LTX lip-sync v3: Fix audio-video sync with pre-pad alignment.

Problem: LTX audio VAE encoding introduces a timing offset, so mouth
movements don't align with the original TTS speech when muxed back.

Fix:
1. Pre-pad TTS audio with silence INSIDE the ComfyUI workflow
   (EmptyAudio + AudioConcat) so LTX sees aligned audio
2. Pre-pad the original TTS by the same amount when muxing
3. Use simple ffmpeg mux (no tempo/resample processing)
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

# Pre-pad silence before speech audio (seconds).
# Compensates for LTX audio VAE encoding latency.
AUDIO_PRE_PAD = 0.3
# Post-pad ensures audio fills the full video duration
AUDIO_POST_PAD = 0.5


def build_lipsync_workflow(image_filename, audio_filename, frame_count):
    """Build lip-sync workflow with pre/post-pad audio alignment."""
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
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltx-2-19b-dev-fp8.safetensors"}},
        "2": {"class_type": "LTXAVTextEncoderLoader", "inputs": {"text_encoder": "gemma_3_12B_it_fp8_scaled.safetensors", "ckpt_name": "ltx-2-19b-dev-fp8.safetensors", "device": "default"}},
        "3": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": "LTX2_audio_vae_bf16.safetensors"}},

        # === Text Conditioning ===
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": video_prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": neg_prompt, "clip": ["2", 0]}},

        # === Image → Video Latent ===
        "6": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
        "7": {"class_type": "LTXVPreprocess", "inputs": {"image": ["6", 0], "img_compression": 18}},
        "8": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": WIDTH, "height": HEIGHT, "length": frame_count, "batch_size": 1}},
        "9": {"class_type": "LTXVConditioning", "inputs": {"positive": ["4", 0], "negative": ["5", 0], "frame_rate": float(FPS)}},
        "10": {"class_type": "LTXVCropGuides", "inputs": {"positive": ["9", 0], "negative": ["9", 1], "latent": ["8", 0]}},
        "11": {"class_type": "LTXVImgToVideoConditionOnly", "inputs": {"vae": ["1", 2], "image": ["7", 0], "latent": ["10", 2], "strength": 0.7}},

        # === Audio with Pre-Pad + Post-Pad Alignment ===
        # 12: Load TTS speech
        "12": {"class_type": "LoadAudio", "inputs": {"audio": audio_filename}},
        # 13: Pre-pad silence (compensates for audio VAE timing offset)
        "13": {
            "class_type": "EmptyAudio",
            "inputs": {"duration": AUDIO_PRE_PAD, "sample_rate": 44100, "channels": 2},
        },
        # 14: Post-pad silence (ensures audio fills video duration)
        "14": {
            "class_type": "EmptyAudio",
            "inputs": {"duration": AUDIO_POST_PAD, "sample_rate": 44100, "channels": 2},
        },
        # 15: Prepend silence before speech
        "15": {
            "class_type": "AudioConcat",
            "inputs": {"audio1": ["13", 0], "audio2": ["12", 0], "direction": "after"},
        },
        # 16: Append silence after speech
        "16": {
            "class_type": "AudioConcat",
            "inputs": {"audio1": ["15", 0], "audio2": ["14", 0], "direction": "after"},
        },
        # 17: Encode padded speech into audio latent
        "17": {
            "class_type": "LTXVAudioVAEEncode",
            "inputs": {"audio": ["16", 0], "audio_vae": ["3", 0]},
        },

        # === Combine + Sample ===
        "18": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["11", 0], "audio_latent": ["17", 0]}},
        "19": {"class_type": "GuiderParameters", "inputs": {"modality": "VIDEO", "cfg": 3.0, "stg": 1.0, "perturb_attn": True, "rescale": 0.7, "modality_scale": 1.0, "skip_step": 0, "cross_attn": True}},
        "20": {"class_type": "GuiderParameters", "inputs": {"modality": "AUDIO", "cfg": 7.0, "stg": 1.0, "perturb_attn": True, "rescale": 0.7, "modality_scale": 1.0, "skip_step": 0, "cross_attn": True, "parameters": ["19", 0]}},
        "21": {"class_type": "MultimodalGuider", "inputs": {"model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1], "parameters": ["20", 0], "skip_blocks": ""}},
        "22": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}},
        "23": {"class_type": "LTXVScheduler", "inputs": {"steps": STEPS, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1, "latent": ["18", 0]}},
        "24": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "25": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["22", 0], "guider": ["21", 0], "sampler": ["24", 0], "sigmas": ["23", 0], "latent_image": ["18", 0]}},

        # === Decode & Output ===
        "26": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["25", 1]}},
        "27": {"class_type": "VAEDecode", "inputs": {"samples": ["26", 0], "vae": ["1", 2]}},
        "28": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["26", 1], "audio_vae": ["3", 0]}},
        "29": {"class_type": "CreateVideo", "inputs": {"images": ["27", 0], "audio": ["28", 0], "fps": float(FPS)}},
        "30": {"class_type": "SaveVideo", "inputs": {"video": ["29", 0], "filename_prefix": "ltx2_lipsync_v3", "format": "mp4", "codec": "h264"}},
    }


async def generate_tts():
    """Generate TTS speech."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.services.tts_generator import TTSGenerator

    tts = TTSGenerator(output_dir="/tmp/f1-lipsync-v3")
    result = await tts.generate_speech(
        text=DIALOGUE, character_name=CHARACTER, scene_number=1, episode_id=0,
    )
    log.info(f"TTS: {result.duration_seconds:.2f}s, voice={result.voice_used}")
    return result.audio_path, result.duration_seconds


async def mux_clean(ltx_video_path: str, tts_audio_path: str, output_path: str, pre_pad: float):
    """Simple mux: strip LTX audio, add pre-padded TTS speech.

    Uses -itsoffset to delay the TTS audio by pre_pad seconds,
    matching the pre-pad used in the ComfyUI workflow.
    No tempo changes, no resampling — just stream replacement.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", ltx_video_path,                      # Input 0: LTX video (lip-synced)
        "-itsoffset", str(pre_pad),                 # Delay audio by pre_pad
        "-i", tts_audio_path,                       # Input 1: Original TTS speech
        "-map", "0:v",                              # Take video from LTX
        "-map", "1:a",                              # Take audio from TTS
        "-c:v", "copy",                             # No video re-encode
        "-c:a", "aac",                              # Encode audio as AAC
        "-b:a", "192k",
        "-ac", "2",                                 # Stereo
        "-ar", "44100",
        "-shortest",                                # Match shortest stream
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()[-300:]}")
    log.info(f"Muxed with {pre_pad}s audio offset")


async def main():
    log.info("=== LTX Lip-Sync v3: Pre-Pad Aligned ===")
    log.info(f"Pre-pad: {AUDIO_PRE_PAD}s, Post-pad: {AUDIO_POST_PAD}s")

    # Step 1: Generate TTS
    log.info("Step 1: Generating TTS speech...")
    tts_audio_path, audio_duration = await generate_tts()

    # Calculate frames: audio + pre-pad + post-pad, rounded to 8n+1
    total_audio = audio_duration + AUDIO_PRE_PAD + AUDIO_POST_PAD
    raw_frames = int(total_audio * FPS) + 1
    frame_count = ((raw_frames - 1 + 7) // 8) * 8 + 1
    frame_count = max(frame_count, 121)
    video_duration = (frame_count - 1) / FPS
    log.info(f"Audio: {audio_duration:.2f}s + pad → {total_audio:.2f}s → {frame_count} frames ({video_duration:.2f}s)")

    # Step 2: Upload image + audio
    log.info("Step 2: Uploading to ComfyUI...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(IMAGE_PATH, "rb") as f:
            resp = await client.post(f"{COMFYUI_URL}/upload/image", files={"image": (IMAGE_PATH.name, f, "image/png")}, data={"overwrite": "true"})
        image_filename = resp.json()["name"]

        with open(tts_audio_path, "rb") as f:
            resp = await client.post(f"{COMFYUI_URL}/upload/image", files={"image": (Path(tts_audio_path).name, f, "audio/mpeg")}, data={"overwrite": "true"})
        audio_filename = resp.json()["name"]
    log.info(f"Image: {image_filename}, Audio: {audio_filename}")

    # Step 3: Queue workflow
    log.info("Step 3: Queuing lip-sync workflow with pre-pad...")
    workflow = build_lipsync_workflow(image_filename, audio_filename, frame_count)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow, "client_id": str(uuid.uuid4())})
        if resp.status_code != 200:
            log.error(f"Queue failed: {resp.status_code}")
            try:
                for nid, nerr in resp.json().get("node_errors", {}).items():
                    for e in nerr.get("errors", []):
                        log.error(f"  Node {nid}: {e.get('message')} - {e.get('details')}")
            except Exception:
                log.error(resp.text[:500])
            return
        prompt_id = resp.json()["prompt_id"]
    log.info(f"Prompt ID: {prompt_id}")

    # Step 4: Wait
    log.info("Step 4: Waiting for generation...")
    start = time.time()
    while (time.time() - start) < 900:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        if resp.status_code == 200 and prompt_id in resp.json():
            result = resp.json()[prompt_id]
            status = result.get("status", {}).get("status_str", "unknown")
            if status == "success":
                log.info(f"LTX done in {time.time() - start:.1f}s")
                break
            elif status == "error":
                for mt, md in result.get("status", {}).get("messages", []):
                    if "error" in str(mt).lower():
                        log.error(f"Node {md.get('node_id')}: {md.get('exception_message', '')[:300]}")
                return
        elapsed = int(time.time() - start)
        if elapsed % 60 == 0 and elapsed > 0:
            log.info(f"  Generating... ({elapsed}s)")
        await asyncio.sleep(5)
    else:
        log.error("Timeout")
        return

    # Step 5: Download LTX video
    log.info("Step 5: Downloading LTX video...")
    outputs = result.get("outputs", {})
    ltx_path = str(OUTPUT_DIR / "scene_01_lipsync_v3_raw.mp4")

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
                    Path(ltx_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(ltx_path).write_bytes(resp.content)
                    log.info(f"LTX video: {len(resp.content) / 1024:.0f} KB")
                    break
            else:
                continue
            break
        else:
            continue
        break

    # Step 6: Mux original TTS with pre-pad offset
    log.info("Step 6: Muxing original TTS speech with sync offset...")
    final_path = str(OUTPUT_DIR / "scene_01_lipsync_v3_final.mp4")
    await mux_clean(ltx_path, tts_audio_path, final_path, AUDIO_PRE_PAD)

    # Step 7: Verify
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

    # Step 8: Desktop
    desktop = Path("/mnt/c/Users/WianK/Desktop")
    if desktop.exists():
        dest = desktop / "scene_01_lipsync_v3.mp4"
        shutil.copy2(final_path, str(dest))
        log.info(f"Desktop: {dest}")

    log.info("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
