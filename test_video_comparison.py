#!/usr/bin/env python3
"""
A/B comparison test for image-to-video conversion.

Tests both Ovi and LTX-2 with multiple parameter combinations to find the
best settings for preserving caricature art style during I2V conversion.

The key insight: standard I2V re-interprets the source image through the
video model's latent space, destroying our carefully crafted art style.
The solution is to constrain the model with:
- Low denoise strength (don't re-encode the image too much)
- High image conditioning (anchor to the source image)
- Style-preserving prompts (animate, don't redraw)
- Fewer steps (less deviation from source)

Usage:
    # Test with default image
    python test_video_comparison.py

    # Test with specific image
    python test_video_comparison.py --image test-output/test_verstappen_scene.png

    # Test only Ovi
    python test_video_comparison.py --engine ovi

    # Test only LTX-2
    python test_video_comparison.py --engine ltx2

    # Test specific parameter sweep
    python test_video_comparison.py --engine ltx2 --sweep denoise
"""

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import httpx

# ============================================================================
# Configuration
# ============================================================================

RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "tims42v3eaqrz7")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "19123"))
COMFYUI_URL = f"https://{RUNPOD_POD_ID}-{COMFYUI_PORT}.proxy.runpod.net"

OVI_SPACE = os.environ.get("OVI_SPACE", "alexnasa/Ovi-ZEROGPU")
HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

DEFAULT_IMAGE = "test-output/test_verstappen_scene.png"
OUTPUT_DIR = Path("test-output/comparison")

# Style-preserving prompt — tells the model to animate, not redraw
STYLE_PROMPT = (
    "Subtle animated motion of the existing image. "
    "Maintain the exact art style, colors, and character appearance. "
    "Only add gentle movement: slight head turn, blinking, mouth movement. "
    "The character speaks with subtle lip movement."
)

# Standard prompt for comparison (what was used before — causes style destruction)
STANDARD_PROMPT = (
    "A caricature character speaks to camera. "
    "Head and shoulders, dramatic lighting."
)


@dataclass
class TestConfig:
    """Configuration for a single test run."""
    name: str
    engine: str  # "ovi" or "ltx2"
    denoise_strength: float
    conditioning_scale: float
    guidance_scale: float
    steps: int
    prompt_style: str = "preserve"  # "preserve" or "standard"
    seed: int = 42


@dataclass
class TestResult:
    """Result of a single test run."""
    config: TestConfig
    video_path: Optional[str]
    generation_time_s: float
    success: bool
    error: Optional[str] = None


# ============================================================================
# Test Parameter Sweeps
# ============================================================================

def get_ovi_tests() -> list[TestConfig]:
    """Parameter sweep for Ovi video generation."""
    tests = []

    # Denoise sweep (most impactful parameter for style preservation)
    for denoise in [0.25, 0.35, 0.45, 0.55, 0.70]:
        tests.append(TestConfig(
            name=f"ovi_denoise_{int(denoise*100):02d}",
            engine="ovi",
            denoise_strength=denoise,
            conditioning_scale=0.90,
            guidance_scale=1.5,
            steps=15,
        ))

    # Conditioning scale sweep
    for cond in [0.70, 0.80, 0.90, 0.95]:
        tests.append(TestConfig(
            name=f"ovi_cond_{int(cond*100):02d}",
            engine="ovi",
            denoise_strength=0.35,
            conditioning_scale=cond,
            guidance_scale=1.5,
            steps=15,
        ))

    # Steps sweep
    for steps in [8, 12, 15, 20, 30]:
        tests.append(TestConfig(
            name=f"ovi_steps_{steps:02d}",
            engine="ovi",
            denoise_strength=0.35,
            conditioning_scale=0.90,
            guidance_scale=1.5,
            steps=steps,
        ))

    # Prompt comparison: style-preserving vs standard
    tests.append(TestConfig(
        name="ovi_prompt_standard",
        engine="ovi",
        denoise_strength=0.35,
        conditioning_scale=0.90,
        guidance_scale=1.5,
        steps=15,
        prompt_style="standard",
    ))

    return tests


def get_ltx2_tests() -> list[TestConfig]:
    """Parameter sweep for LTX-2 video generation."""
    tests = []

    # Denoise sweep
    for denoise in [0.20, 0.30, 0.40, 0.50, 0.60]:
        tests.append(TestConfig(
            name=f"ltx2_denoise_{int(denoise*100):02d}",
            engine="ltx2",
            denoise_strength=denoise,
            conditioning_scale=0.90,
            guidance_scale=3.0,
            steps=20,
        ))

    # Conditioning scale sweep
    for cond in [0.70, 0.80, 0.90, 0.95, 1.00]:
        tests.append(TestConfig(
            name=f"ltx2_cond_{int(cond*100):02d}",
            engine="ltx2",
            denoise_strength=0.35,
            conditioning_scale=cond,
            guidance_scale=3.0,
            steps=20,
        ))

    # Guidance scale sweep
    for guidance in [1.5, 2.0, 3.0, 4.0, 5.0]:
        tests.append(TestConfig(
            name=f"ltx2_guidance_{int(guidance*10):02d}",
            engine="ltx2",
            denoise_strength=0.35,
            conditioning_scale=0.90,
            guidance_scale=guidance,
            steps=20,
        ))

    # Steps sweep
    for steps in [10, 15, 20, 25, 30]:
        tests.append(TestConfig(
            name=f"ltx2_steps_{steps:02d}",
            engine="ltx2",
            denoise_strength=0.35,
            conditioning_scale=0.90,
            guidance_scale=3.0,
            steps=steps,
        ))

    # Prompt comparison
    tests.append(TestConfig(
        name="ltx2_prompt_standard",
        engine="ltx2",
        denoise_strength=0.35,
        conditioning_scale=0.90,
        guidance_scale=3.0,
        steps=20,
        prompt_style="standard",
    ))

    return tests


def get_sweep_tests(engine: str, sweep: str) -> list[TestConfig]:
    """Get tests for a specific parameter sweep only."""
    if engine == "ovi":
        all_tests = get_ovi_tests()
    elif engine == "ltx2":
        all_tests = get_ltx2_tests()
    else:
        all_tests = get_ovi_tests() + get_ltx2_tests()

    if sweep:
        return [t for t in all_tests if sweep in t.name]
    return all_tests


# ============================================================================
# Ovi Generation
# ============================================================================

def generate_ovi(image_path: str, config: TestConfig) -> str:
    """Generate video using Ovi (Gradio)."""
    from gradio_client import Client, handle_file

    prompt = STYLE_PROMPT if config.prompt_style == "preserve" else STANDARD_PROMPT

    client = Client(OVI_SPACE, token=HF_TOKEN if HF_TOKEN else None)

    try:
        # Try with extended parameters
        result = client.predict(
            text_prompt=prompt,
            sample_steps=config.steps,
            image=handle_file(image_path),
            image_conditioning_strength=config.conditioning_scale,
            denoise_strength=config.denoise_strength,
            guidance_scale=config.guidance_scale,
            api_name="/generate_scene",
        )
    except TypeError:
        # Fallback: basic params only
        print(f"    [WARN] Ovi space does not support extended params, using basic mode")
        result = client.predict(
            text_prompt=prompt,
            sample_steps=config.steps,
            image=handle_file(image_path),
            api_name="/generate_scene",
        )

    if isinstance(result, dict):
        return result.get("video", str(result))
    return str(result)


# ============================================================================
# LTX-2 Generation (via ComfyUI)
# ============================================================================

def upload_image_to_comfyui(image_path: str) -> str:
    """Upload image to ComfyUI input directory."""
    filename = Path(image_path).name

    with httpx.Client(timeout=30.0) as client:
        with open(image_path, "rb") as f:
            files = {"image": (filename, f, "image/png")}
            data = {"overwrite": "true"}
            resp = client.post(f"{COMFYUI_URL}/upload/image", files=files, data=data)

    if resp.status_code != 200:
        raise Exception(f"Upload failed: {resp.status_code} {resp.text[:200]}")

    result = resp.json()
    return result.get("name", filename)


def build_ltx2_workflow(
    image_filename: str,
    prompt: str,
    config: TestConfig,
) -> dict:
    """Build ComfyUI workflow for LTX-2 image-to-video."""
    seed = config.seed if config.seed >= 0 else int(time.time()) % (2**32)

    return {
        # Load LTX-2 model
        "1": {
            "class_type": "LTXVLoader",
            "inputs": {
                "model_name": "ltxv-2b-0.9.6-distilled-fp8.safetensors",
                "dtype": "fp8_e4m3fn",
            },
        },
        # Text encode with Gemma 3
        "2": {
            "class_type": "LTXVTextEncode",
            "inputs": {
                "positive_prompt": prompt,
                "negative_prompt": (
                    "blurry, distorted, deformed, ugly, low quality, "
                    "photorealistic, different art style, style change, "
                    "morphing, melting face, horror, grotesque"
                ),
                "model": ["1", 0],
            },
        },
        # Load source image
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": image_filename},
        },
        # Resize to video dimensions
        "4": {
            "class_type": "ImageResize+",
            "inputs": {
                "image": ["3", 0],
                "width": 768,
                "height": 512,
                "interpolation": "lanczos",
                "method": "fill / crop",
                "condition": "always",
                "multiple_of": 32,
            },
        },
        # Image conditioning
        "5": {
            "class_type": "LTXVImageEncode",
            "inputs": {
                "image": ["4", 0],
                "model": ["1", 0],
                "image_conditioning_scale": config.conditioning_scale,
            },
        },
        # Set up conditioning
        "6": {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["2", 0],
                "negative": ["2", 1],
                "latent": ["5", 0],
                "frame_count": 121,
                "width": 768,
                "height": 512,
            },
        },
        # Sample
        "7": {
            "class_type": "LTXVSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],
                "negative": ["6", 1],
                "latent": ["6", 2],
                "seed": seed,
                "steps": config.steps,
                "cfg": config.guidance_scale,
                "denoise": config.denoise_strength,
                "scheduler": "normal",
            },
        },
        # Decode
        "8": {
            "class_type": "LTXVDecode",
            "inputs": {
                "model": ["1", 0],
                "samples": ["7", 0],
            },
        },
        # Save video
        "9": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["8", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": f"comparison_{config.name}",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def queue_comfyui_prompt(workflow: dict) -> str:
    """Send workflow to ComfyUI."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{COMFYUI_URL}/prompt", json=payload)

    if resp.status_code != 200:
        raise Exception(f"Queue failed: {resp.status_code}: {resp.text[:300]}")

    return resp.json().get("prompt_id")


def wait_for_comfyui(prompt_id: str, timeout: int = 600) -> dict:
    """Wait for ComfyUI prompt to complete."""
    start = time.time()
    while time.time() - start < timeout:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{COMFYUI_URL}/history/{prompt_id}")

        if resp.status_code == 200:
            data = resp.json()
            if prompt_id in data:
                result = data[prompt_id]
                status = result.get("status", {}).get("status_str", "unknown")
                if status == "success":
                    return result
                elif status == "error":
                    raise Exception(f"ComfyUI error: {str(result.get('status', {}))[:300]}")

        elapsed = int(time.time() - start)
        print(f"    Waiting... ({elapsed}s)", end="\r", flush=True)
        time.sleep(3)

    raise Exception(f"Timeout after {timeout}s")


def download_comfyui_video(result: dict, output_path: str) -> str:
    """Download video from ComfyUI output."""
    outputs = result.get("outputs", {})
    for node_id, node_output in outputs.items():
        for key in ("gifs", "videos"):
            items = node_output.get(key, [])
            for vid in items:
                filename = vid["filename"]
                subfolder = vid.get("subfolder", "")
                vid_type = vid.get("type", "output")

                with httpx.Client(timeout=60.0) as client:
                    resp = client.get(
                        f"{COMFYUI_URL}/view",
                        params={"filename": filename, "subfolder": subfolder, "type": vid_type},
                    )

                if resp.status_code == 200:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(resp.content)
                    return output_path

    raise Exception("No video found in ComfyUI output")


def generate_ltx2(image_path: str, config: TestConfig) -> str:
    """Generate video using LTX-2 via ComfyUI."""
    # Upload source image
    image_filename = upload_image_to_comfyui(image_path)

    prompt = STYLE_PROMPT if config.prompt_style == "preserve" else STANDARD_PROMPT

    # Add LTX-2 specific style instructions
    ltx2_prompt = (
        f"Animate this stylized caricature illustration with subtle, gentle motion. "
        f"Maintain the EXACT art style, colors, lighting, and character proportions. "
        f"Do NOT change the art style or make it more realistic. "
        f"{prompt}"
    )

    workflow = build_ltx2_workflow(image_filename, ltx2_prompt, config)
    prompt_id = queue_comfyui_prompt(workflow)

    result = wait_for_comfyui(prompt_id, timeout=600)

    output_path = str(OUTPUT_DIR / f"{config.name}.mp4")
    return download_comfyui_video(result, output_path)


# ============================================================================
# Main Runner
# ============================================================================

def run_test(image_path: str, config: TestConfig) -> TestResult:
    """Run a single comparison test."""
    print(f"\n--- {config.name} ---")
    print(f"    Engine: {config.engine}")
    print(f"    Denoise: {config.denoise_strength:.2f}")
    print(f"    Conditioning: {config.conditioning_scale:.2f}")
    print(f"    Guidance: {config.guidance_scale:.1f}")
    print(f"    Steps: {config.steps}")
    print(f"    Prompt: {config.prompt_style}")

    start = time.time()

    try:
        if config.engine == "ovi":
            video_path = generate_ovi(image_path, config)
        elif config.engine == "ltx2":
            video_path = generate_ltx2(image_path, config)
        else:
            raise ValueError(f"Unknown engine: {config.engine}")

        elapsed = time.time() - start

        # Copy video to output directory with descriptive name
        final_path = str(OUTPUT_DIR / f"{config.name}.mp4")
        if video_path != final_path:
            import shutil
            Path(final_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(video_path, final_path)

        size_kb = Path(final_path).stat().st_size / 1024
        print(f"    SUCCESS: {final_path} ({size_kb:.0f} KB, {elapsed:.1f}s)")

        return TestResult(
            config=config,
            video_path=final_path,
            generation_time_s=elapsed,
            success=True,
        )

    except Exception as e:
        elapsed = time.time() - start
        print(f"    FAILED: {e}")

        return TestResult(
            config=config,
            video_path=None,
            generation_time_s=elapsed,
            success=False,
            error=str(e),
        )


def main():
    parser = argparse.ArgumentParser(
        description="A/B comparison test for I2V style preservation"
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="Source caricature image path",
    )
    parser.add_argument(
        "--engine",
        choices=["ovi", "ltx2", "both"],
        default="both",
        help="Which engine(s) to test",
    )
    parser.add_argument(
        "--sweep",
        choices=["denoise", "cond", "guidance", "steps", "prompt", ""],
        default="",
        help="Run only a specific parameter sweep",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a quick test with just the recommended presets",
    )

    args = parser.parse_args()

    # Validate image exists
    image_path = args.image
    if not Path(image_path).exists():
        print(f"ERROR: Image not found: {image_path}")
        print("Run the image generation test first to create a source image.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("VIDEO COMPARISON TEST: Ovi vs LTX-2 Style Preservation")
    print("=" * 70)
    print(f"  Source image: {image_path}")
    print(f"  Output dir:   {OUTPUT_DIR}")
    print(f"  Engine:       {args.engine}")
    if args.engine in ("ltx2", "both"):
        print(f"  ComfyUI URL:  {COMFYUI_URL}")
    print()

    # Build test list
    if args.quick:
        # Quick mode: just the recommended "caricature" preset for each engine
        tests = []
        if args.engine in ("ovi", "both"):
            tests.append(TestConfig(
                name="ovi_caricature",
                engine="ovi",
                denoise_strength=0.35,
                conditioning_scale=0.92,
                guidance_scale=1.5,
                steps=15,
            ))
        if args.engine in ("ltx2", "both"):
            tests.append(TestConfig(
                name="ltx2_caricature",
                engine="ltx2",
                denoise_strength=0.30,
                conditioning_scale=0.95,
                guidance_scale=2.0,
                steps=18,
            ))
    else:
        tests = get_sweep_tests(args.engine, args.sweep)

    print(f"Running {len(tests)} tests...\n")

    # Run tests
    results = []
    for i, config in enumerate(tests):
        print(f"[{i+1}/{len(tests)}]", end="")
        result = run_test(image_path, config)
        results.append(result)

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\nSuccessful: {len(successful)}/{len(results)}")
    if failed:
        print(f"Failed: {len(failed)}")
        for r in failed:
            print(f"  - {r.config.name}: {r.error}")

    if successful:
        print(f"\nGenerated videos:")
        for r in sorted(successful, key=lambda x: x.generation_time_s):
            size = Path(r.video_path).stat().st_size / 1024 if r.video_path else 0
            print(
                f"  {r.config.name:30s}  "
                f"denoise={r.config.denoise_strength:.2f}  "
                f"cond={r.config.conditioning_scale:.2f}  "
                f"guide={r.config.guidance_scale:.1f}  "
                f"steps={r.config.steps:2d}  "
                f"{r.generation_time_s:6.1f}s  "
                f"{size:7.0f}KB"
            )

    # Save results as JSON for later analysis
    results_path = OUTPUT_DIR / "comparison_results.json"
    results_data = []
    for r in results:
        entry = {
            "name": r.config.name,
            "engine": r.config.engine,
            "denoise_strength": r.config.denoise_strength,
            "conditioning_scale": r.config.conditioning_scale,
            "guidance_scale": r.config.guidance_scale,
            "steps": r.config.steps,
            "prompt_style": r.config.prompt_style,
            "video_path": r.video_path,
            "generation_time_s": round(r.generation_time_s, 1),
            "success": r.success,
            "error": r.error,
        }
        results_data.append(entry)

    results_path.write_text(json.dumps(results_data, indent=2))
    print(f"\nResults saved to: {results_path}")

    print("\n" + "=" * 70)
    print("Review the videos in test-output/comparison/ to find the best settings.")
    print("Look for: style preservation, smooth motion, no distortion.")
    print("=" * 70)


if __name__ == "__main__":
    main()
