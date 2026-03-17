#!/usr/bin/env python3
"""Test LTX 2.3 First-Last-Frame (FLF) video generation via fal.ai.

Generates a START frame and END frame using fal-ai/flux-lora with the
ANTKF1STYLE LoRA, then feeds both into fal-ai/ltx-2.3/image-to-video
to produce a smooth interpolation video.

Tests both standard and fast endpoints for comparison.

Usage:
    python scripts/experiments/test_ltx_flf.py
    python scripts/experiments/test_ltx_flf.py --skip-images          # reuse cached frames
    python scripts/experiments/test_ltx_flf.py --standard-only
    python scripts/experiments/test_ltx_flf.py --fast-only
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LORA_URL = (
    "https://v3b.fal.media/files/b/0a918355/"
    "tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors"
)

OUTPUT_DIR = Path("/tmp/f1-flf-test")

IMAGE_ENDPOINT = "fal-ai/flux-lora"

VIDEO_ENDPOINT_STANDARD = "fal-ai/ltx-2.3/image-to-video"
VIDEO_ENDPOINT_FAST = "fal-ai/ltx-2.3/image-to-video/fast"

# Frame prompts — logically connected, same character + setting, different pose
START_FRAME_PROMPT = (
    "ANTKF1STYLE MEDIUM SHOT of Max Verstappen at a press conference podium, "
    "looking slightly to the left, confident expression, microphone visible. "
    "Satirical caricature style with oversized head, photorealistic skin with "
    "visible pores. Dramatic lighting with deep shadows. "
    "No text, no words, no letters."
)

END_FRAME_PROMPT = (
    "ANTKF1STYLE MEDIUM SHOT of Max Verstappen at a press conference podium, "
    "looking slightly to the right with a subtle smirk, hand gesturing. "
    "Satirical caricature style with oversized head, photorealistic skin with "
    "visible pores. Dramatic lighting with deep shadows. "
    "No text, no words, no letters."
)

VIDEO_PROMPT = (
    "A racing driver speaks at a press conference, slight head movement "
    "and hand gesture, cinematic lighting"
)

# Paths for cached images (used with --skip-images)
CACHED_START_FRAME = OUTPUT_DIR / "start_frame.png"
CACHED_END_FRAME = OUTPUT_DIR / "end_frame.png"
CACHED_URLS_FILE = OUTPUT_DIR / "frame_urls.json"


# ---------------------------------------------------------------------------
# Image generation via fal.ai queue API
# ---------------------------------------------------------------------------

async def generate_image(prompt: str, name: str, fal_key: str) -> str:
    """Generate an image via fal-ai/flux-lora and return the CDN URL.

    Uses the HTTP queue API: POST to submit, poll status, GET result.
    Also saves the image locally for inspection.

    Args:
        prompt: The image generation prompt (should include ANTKF1STYLE trigger).
        name: Friendly name for logging/filenames (e.g. "start_frame").
        fal_key: fal.ai API key.

    Returns:
        Public CDN URL of the generated image.
    """
    print(f"\n{'='*60}")
    print(f"Generating image: {name}")
    print(f"{'='*60}")
    print(f"Prompt: {prompt[:80]}...")

    fal_payload = {
        "prompt": prompt,
        "image_size": {"width": 1280, "height": 720},
        "num_images": 1,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "loras": [{"path": LORA_URL, "scale": 1.0}],
        "output_format": "png",
    }

    headers = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json",
    }

    start_time = time.monotonic()

    async with httpx.AsyncClient(timeout=300) as client:
        # Submit to queue
        submit_resp = await client.post(
            f"https://queue.fal.run/{IMAGE_ENDPOINT}",
            headers=headers,
            json=fal_payload,
        )
        submit_resp.raise_for_status()
        submit_data = submit_resp.json()

        request_id = submit_data.get("request_id")
        status_url = submit_data.get(
            "status_url",
            f"https://queue.fal.run/{IMAGE_ENDPOINT}/requests/{request_id}/status",
        )
        response_url = submit_data.get(
            "response_url",
            f"https://queue.fal.run/{IMAGE_ENDPOINT}/requests/{request_id}",
        )

        print(f"  Submitted: request_id={request_id}")

        # Poll for completion (max 5 minutes)
        for i in range(60):
            await asyncio.sleep(5)
            status_resp = await client.get(status_url, headers=headers)
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "COMPLETED":
                break
            elif status in ("FAILED", "CANCELLED"):
                error_msg = status_data.get("error", "fal.ai generation failed")
                raise RuntimeError(f"Image generation failed for {name}: {error_msg}")

            if (i + 1) % 6 == 0:
                print(f"  Waiting... {(i + 1) * 5}s (status: {status})")
        else:
            raise RuntimeError(f"Image generation timed out for {name} after 5 minutes")

        # Get result
        result_resp = await client.get(response_url, headers=headers)
        result_resp.raise_for_status()
        result_data = result_resp.json()

        images = result_data.get("images", [])
        if not images:
            raise RuntimeError(f"fal.ai returned no images for {name}")

        image_url = images[0]["url"]

        # Download locally for inspection
        img_resp = await client.get(image_url)
        img_resp.raise_for_status()

    elapsed = time.monotonic() - start_time
    local_path = OUTPUT_DIR / f"{name}.png"
    local_path.write_bytes(img_resp.content)
    file_size_kb = local_path.stat().st_size / 1024

    print(f"  Done in {elapsed:.1f}s")
    print(f"  CDN URL: {image_url}")
    print(f"  Local: {local_path} ({file_size_kb:.0f} KB)")

    return image_url


# ---------------------------------------------------------------------------
# Video generation via fal_client.subscribe
# ---------------------------------------------------------------------------

async def generate_flf_video(
    start_url: str,
    end_url: str,
    prompt: str,
    endpoint: str,
    name: str,
) -> dict:
    """Generate a first-last-frame video via LTX 2.3 on fal.ai.

    Uses fal_client.subscribe (same pattern as FalVideoGenerator.generate_clip).

    Args:
        start_url: CDN URL of the start frame image.
        end_url: CDN URL of the end frame image.
        prompt: Video action prompt.
        endpoint: fal.ai model endpoint (standard or fast).
        name: Friendly name for logging/filenames.

    Returns:
        Dict with video_url, local_path, elapsed_s, file_size_mb, seed.
    """
    import fal_client

    print(f"\n{'='*60}")
    print(f"Generating FLF video: {name}")
    print(f"Endpoint: {endpoint}")
    print(f"{'='*60}")

    arguments = {
        "image_url": start_url,
        "end_image_url": end_url,
        "prompt": prompt,
        "duration": 6,
        "num_inference_steps": 30,
        "generate_audio": False,
    }

    print(f"  Start frame: {start_url[:60]}...")
    print(f"  End frame:   {end_url[:60]}...")
    print(f"  Duration: {arguments['duration']}s, Steps: {arguments['num_inference_steps']}")

    def on_queue_update(update):
        status = getattr(update, "status", None)
        if status:
            print(f"  Queue: {status}")
        logs = getattr(update, "logs", None)
        if logs:
            for log_entry in logs:
                msg = getattr(log_entry, "message", str(log_entry))
                print(f"  Log: {msg}")

    start_time = time.monotonic()

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: fal_client.subscribe(
                endpoint,
                arguments=arguments,
                with_logs=True,
                on_queue_update=on_queue_update,
            ),
        )
    except Exception as e:
        elapsed = time.monotonic() - start_time
        print(f"  FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")
        return {
            "name": name,
            "endpoint": endpoint,
            "status": "failed",
            "error": str(e),
            "elapsed_s": elapsed,
        }

    elapsed = time.monotonic() - start_time

    # Extract video URL
    video_data = result.get("video")
    if not video_data or not video_data.get("url"):
        print(f"  ERROR: No video URL in result: {result}")
        return {
            "name": name,
            "endpoint": endpoint,
            "status": "failed",
            "error": "No video URL returned",
            "elapsed_s": elapsed,
        }

    video_url = video_data["url"]
    result_seed = result.get("seed")

    print(f"  Video URL: {video_url}")
    print(f"  Seed: {result_seed}")

    # Download video
    local_path = OUTPUT_DIR / f"{name}.mp4"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)

    file_size_mb = local_path.stat().st_size / (1024 * 1024)

    print(f"  Done in {elapsed:.1f}s")
    print(f"  Local: {local_path} ({file_size_mb:.1f} MB)")

    return {
        "name": name,
        "endpoint": endpoint,
        "status": "success",
        "video_url": video_url,
        "local_path": str(local_path),
        "elapsed_s": elapsed,
        "file_size_mb": file_size_mb,
        "seed": result_seed,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        description="Test LTX 2.3 First-Last-Frame video generation via fal.ai"
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Reuse previously generated frame images (from frame_urls.json)",
    )
    parser.add_argument(
        "--standard-only",
        action="store_true",
        help="Only test the standard endpoint (skip fast)",
    )
    parser.add_argument(
        "--fast-only",
        action="store_true",
        help="Only test the fast endpoint (skip standard)",
    )
    args = parser.parse_args()

    # Validate FAL_KEY
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        print("ERROR: FAL_KEY environment variable is not set.")
        print("Export it before running: export FAL_KEY='your-key-here'")
        sys.exit(1)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LTX 2.3 First-Last-Frame (FLF) Video Test")
    print("=" * 60)
    print(f"Output directory: {OUTPUT_DIR}")

    # -----------------------------------------------------------------------
    # Step 1: Generate (or reuse) start + end frames
    # -----------------------------------------------------------------------
    if args.skip_images:
        if not CACHED_URLS_FILE.exists():
            print(f"\nERROR: --skip-images requires {CACHED_URLS_FILE} to exist.")
            print("Run without --skip-images first to generate frames.")
            sys.exit(1)

        urls = json.loads(CACHED_URLS_FILE.read_text())
        start_url = urls["start_frame_url"]
        end_url = urls["end_frame_url"]
        print(f"\nReusing cached frame URLs from {CACHED_URLS_FILE}")
        print(f"  Start: {start_url[:60]}...")
        print(f"  End:   {end_url[:60]}...")
    else:
        print("\n--- Step 1: Generating start + end frames via flux-lora ---")
        start_url = await generate_image(START_FRAME_PROMPT, "start_frame", fal_key)
        end_url = await generate_image(END_FRAME_PROMPT, "end_frame", fal_key)

        # Cache URLs for --skip-images reruns
        CACHED_URLS_FILE.write_text(json.dumps({
            "start_frame_url": start_url,
            "end_frame_url": end_url,
        }, indent=2))
        print(f"\nFrame URLs cached to {CACHED_URLS_FILE}")

    # -----------------------------------------------------------------------
    # Step 2: Generate FLF videos
    # -----------------------------------------------------------------------
    print("\n--- Step 2: Generating FLF videos via LTX 2.3 ---")

    results = []

    if not args.fast_only:
        result_standard = await generate_flf_video(
            start_url=start_url,
            end_url=end_url,
            prompt=VIDEO_PROMPT,
            endpoint=VIDEO_ENDPOINT_STANDARD,
            name="flf_standard",
        )
        results.append(result_standard)

    if not args.standard_only:
        result_fast = await generate_flf_video(
            start_url=start_url,
            end_url=end_url,
            prompt=VIDEO_PROMPT,
            endpoint=VIDEO_ENDPOINT_FAST,
            name="flf_fast",
        )
        results.append(result_fast)

    # -----------------------------------------------------------------------
    # Step 3: Summary
    # -----------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    print(f"\nOutput directory: {OUTPUT_DIR}")
    print(f"Start frame: {OUTPUT_DIR / 'start_frame.png'}")
    print(f"End frame:   {OUTPUT_DIR / 'end_frame.png'}")

    for r in results:
        print(f"\n--- {r['name']} ({r['endpoint']}) ---")
        print(f"  Status:    {r['status']}")
        print(f"  Time:      {r['elapsed_s']:.1f}s")
        if r["status"] == "success":
            print(f"  File size: {r['file_size_mb']:.1f} MB")
            print(f"  Seed:      {r.get('seed')}")
            print(f"  File:      {r['local_path']}")
        else:
            print(f"  Error:     {r.get('error', 'unknown')}")

    # Comparison table if both ran
    if len(results) == 2 and all(r["status"] == "success" for r in results):
        print(f"\n--- Comparison ---")
        print(f"  {'Metric':<15} {'Standard':>12} {'Fast':>12} {'Diff':>12}")
        print(f"  {'-'*15} {'-'*12} {'-'*12} {'-'*12}")

        t_std = results[0]["elapsed_s"]
        t_fast = results[1]["elapsed_s"]
        print(f"  {'Time (s)':<15} {t_std:>12.1f} {t_fast:>12.1f} {t_fast - t_std:>+12.1f}")

        s_std = results[0]["file_size_mb"]
        s_fast = results[1]["file_size_mb"]
        print(f"  {'Size (MB)':<15} {s_std:>12.1f} {s_fast:>12.1f} {s_fast - s_std:>+12.1f}")

        speedup = t_std / t_fast if t_fast > 0 else 0
        print(f"\n  Fast endpoint is {speedup:.1f}x {'faster' if speedup > 1 else 'slower'} than standard")

    print(f"\nDone. Check {OUTPUT_DIR} for output files.")


if __name__ == "__main__":
    asyncio.run(main())
