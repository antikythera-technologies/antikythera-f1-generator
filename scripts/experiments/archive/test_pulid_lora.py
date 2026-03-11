#!/usr/bin/env python3
"""
Test PuLID (face identity) + LoRA (art style) on RunPod via ComfyUI API.

Workflow: Flux Dev fp8 → LoRA (ANTKF1STYLE) → PuLID (face from photo) → KSampler → image

This combines:
- ANTKF1STYLE LoRA for consistent caricature art style
- PuLID for face identity preservation from a real photo
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "tims42v3eaqrz7")
COMFYUI_URL = f"https://{RUNPOD_POD_ID}-19123.proxy.runpod.net"
OUTPUT_DIR = Path("test-output")
TRIGGER = "ANTKF1STYLE"


def build_pulid_lora_workflow(
    prompt_text: str,
    face_image: str = "george_russell.jpg",
    lora_strength: float = 1.0,
    pulid_weight: float = 0.9,
    width: int = 768,
    height: int = 1344,
    seed: int = 42,
) -> dict:
    """Build ComfyUI workflow: Flux + LoRA + PuLID."""
    return {
        # UNET Loader (Flux Dev fp8)
        "4": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        # LoRA Loader (ANTKF1STYLE)
        "10": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "antkf1style_v1.safetensors",
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
                "model": ["4", 0],
                "clip": ["11", 0],
            },
        },
        # Dual CLIP Loader
        "11": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "clip_l.safetensors",
                "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                "type": "flux",
            },
        },
        # VAE Loader
        "12": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": "ae.safetensors",
            },
        },
        # PuLID Model Loader
        "20": {
            "class_type": "PulidFluxModelLoader",
            "inputs": {
                "pulid_file": "pulid_flux_v0.9.0.safetensors",
            },
        },
        # InsightFace Loader
        "21": {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {
                "provider": "CUDA",
            },
        },
        # EVA-CLIP Loader
        "22": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        },
        # Load Face Image
        "23": {
            "class_type": "LoadImage",
            "inputs": {
                "image": face_image,
            },
        },
        # Apply PuLID (takes LoRA-modified model, returns PuLID-enhanced model)
        "25": {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "model": ["10", 0],       # LoRA-modified model
                "pulid_flux": ["20", 0],   # PuLID model
                "eva_clip": ["22", 0],     # EVA-CLIP
                "face_analysis": ["21", 0], # InsightFace
                "image": ["23", 0],        # Face photo
                "weight": pulid_weight,
                "start_at": 0.0,
                "end_at": 1.0,
            },
        },
        # CLIP Text Encode (positive)
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt_text,
                "clip": ["11", 0],
            },
        },
        # CLIP Text Encode (negative)
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "",
                "clip": ["11", 0],
            },
        },
        # Empty Latent Image
        "5": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        # KSampler (uses PuLID-enhanced model)
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["25", 0],        # PuLID-enhanced model (includes LoRA)
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        # VAE Decode
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["12", 0],
            },
        },
        # Save Image
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "pulid_lora_test",
                "images": ["8", 0],
            },
        },
    }


def queue_prompt(workflow: dict) -> str:
    """Send workflow to ComfyUI and return the prompt ID."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{COMFYUI_URL}/prompt", json=payload)

    if resp.status_code != 200:
        print(f"  ERROR: {resp.status_code}: {resp.text[:500]}")
        raise Exception(f"Failed to queue: {resp.status_code}")

    data = resp.json()
    prompt_id = data.get("prompt_id")
    print(f"  Queued: {prompt_id}")
    return prompt_id


def wait_for_completion(prompt_id: str, timeout: int = 600) -> dict:
    """Poll ComfyUI until the prompt completes."""
    start = time.time()
    while time.time() - start < timeout:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{COMFYUI_URL}/history/{prompt_id}")

        if resp.status_code == 200:
            data = resp.json()
            if prompt_id in data:
                return data[prompt_id]

        elapsed = int(time.time() - start)
        print(f"  Waiting... ({elapsed}s)", end="\r")
        time.sleep(3)

    raise Exception(f"Timeout after {timeout}s")


def download_image(prompt_id: str, output: dict, filename: str):
    """Download generated image from ComfyUI."""
    outputs = output.get("outputs", {})
    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        for img in images:
            img_filename = img["filename"]
            subfolder = img.get("subfolder", "")

            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{COMFYUI_URL}/view",
                    params={"filename": img_filename, "subfolder": subfolder, "type": "output"},
                )

            if resp.status_code == 200:
                path = OUTPUT_DIR / filename
                path.write_bytes(resp.content)
                print(f"  SAVED: {path} ({len(resp.content) / 1024:.0f} KB)")
                return

    print("  No image found in output")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("PULID + LORA TEST: Face Identity + Art Style")
    print(f"Endpoint: {COMFYUI_URL}")
    print("=" * 60)

    # Test 1: George Russell — LoRA style + PuLID face, pulid_weight=0.9
    prompt_text = (
        f"A {TRIGGER} satirical caricature portrait of a young male F1 driver, "
        f"wearing a black Mercedes-AMG Petronas F1 team suit with Petronas teal accents. "
        f"Oversized head with exaggerated facial features, "
        f"hyper-detailed photorealistic skin with visible pores, "
        f"warm burnt-orange to dark amber gradient background, "
        f"dramatic warm side lighting with deep shadows. "
        f"Head and shoulders portrait, cinematic satirical artwork."
    )

    tests = [
        ("george_pulid_w07", 0.7, 1.0, 42),
        ("george_pulid_w09", 0.9, 1.0, 42),
        ("george_pulid_w12", 1.2, 1.0, 42),
    ]

    for label, pulid_w, lora_s, seed in tests:
        print(f"\n--- {label}: PuLID weight={pulid_w}, LoRA strength={lora_s} ---")

        workflow = build_pulid_lora_workflow(
            prompt_text=prompt_text,
            face_image="george_russell.jpg",
            lora_strength=lora_s,
            pulid_weight=pulid_w,
            seed=seed,
        )
        prompt_id = queue_prompt(workflow)

        print("  Generating (first run loads all models, may take 60-120s)...")
        result = wait_for_completion(prompt_id, timeout=600)

        status = result.get("status", {}).get("status_str", "unknown")
        print(f"  Status: {status}")

        if status == "success":
            download_image(prompt_id, result, f"{label}.png")
        else:
            print(f"  FAILED: {json.dumps(result.get('status', {}), indent=2)[:500]}")
            # Check for error messages in the execution
            if "outputs" in result:
                for nid, nout in result["outputs"].items():
                    if "error" in str(nout).lower():
                        print(f"    Node {nid}: {str(nout)[:200]}")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/george_pulid_*.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
