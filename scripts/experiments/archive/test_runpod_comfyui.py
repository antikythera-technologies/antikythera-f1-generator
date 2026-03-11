#!/usr/bin/env python3
"""
Test Flux + LoRA on RunPod via ComfyUI API.

Sends a workflow that generates a caricature using the trained ANTKF1STYLE LoRA.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

# ComfyUI endpoint on RunPod
RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "tims42v3eaqrz7")
COMFYUI_URL = f"https://{RUNPOD_POD_ID}-19123.proxy.runpod.net"
OUTPUT_DIR = Path("test-output")

TRIGGER = "ANTKF1STYLE"


def build_workflow(prompt_text: str, width: int = 768, height: int = 1344, seed: int = 42) -> dict:
    """Build a ComfyUI workflow for Flux Dev + LoRA generation."""
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["10", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        "5": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt_text,
                "clip": ["11", 0],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "",
                "clip": ["11", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["12", 0],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "lora_test",
                "images": ["8", 0],
            },
        },
        "10": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "antkf1style_v1.safetensors",
                "strength_model": 1.0,
                "strength_clip": 1.0,
                "model": ["4", 0],
                "clip": ["11", 0],
            },
        },
        "11": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "clip_l.safetensors",
                "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                "type": "flux",
            },
        },
        "12": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": "ae.safetensors",
            },
        },
    }


def queue_prompt(workflow: dict) -> str:
    """Send workflow to ComfyUI and return the prompt ID."""
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": workflow,
        "client_id": client_id,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{COMFYUI_URL}/prompt", json=payload)

    if resp.status_code != 200:
        raise Exception(f"Failed to queue: {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    prompt_id = data.get("prompt_id")
    print(f"  Queued: {prompt_id}")
    return prompt_id


def wait_for_completion(prompt_id: str, timeout: int = 300) -> dict:
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
        time.sleep(2)

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
    print("=" * 60)
    print("RUNPOD COMFYUI TEST: Flux Dev fp8 + ANTKF1STYLE LoRA")
    print(f"Endpoint: {COMFYUI_URL}")
    print("=" * 60)

    # Test 1: Same prompt that produced the great t2i result on fal.ai
    prompt_text = (
        f"A {TRIGGER} satirical caricature portrait of a young male F1 driver, "
        f"wearing a dark blue Red Bull Racing suit with Oracle and Bybit logos. "
        f"Oversized head with exaggerated facial features, "
        f"hyper-detailed photorealistic skin with visible pores, "
        f"warm burnt-orange to dark amber gradient background, "
        f"dramatic warm side lighting with deep shadows. "
        f"Head and shoulders portrait, cinematic satirical artwork."
    )

    print(f"\n--- Test: Generic F1 driver caricature ---")
    print(f"  Prompt: {prompt_text[:80]}...")

    workflow = build_workflow(prompt_text, seed=42)
    prompt_id = queue_prompt(workflow)

    print("  Generating (first run loads models, may take 30-60s)...")
    result = wait_for_completion(prompt_id, timeout=300)

    status = result.get("status", {}).get("status_str", "unknown")
    print(f"  Status: {status}")

    if status == "success":
        download_image(prompt_id, result, "runpod_lora_test1.png")
    else:
        print(f"  FAILED: {json.dumps(result.get('status', {}), indent=2)[:300]}")

    # Test 2: Different character to verify consistency
    prompt_text2 = (
        f"A {TRIGGER} satirical caricature portrait of a middle-aged male F1 team principal, "
        f"wearing a red Ferrari team polo shirt. Intense passionate expression. "
        f"Oversized head with exaggerated facial features, "
        f"hyper-detailed photorealistic skin with visible pores and wrinkles, "
        f"warm burnt-orange to dark amber gradient background, "
        f"dramatic warm side lighting with deep shadows. "
        f"Head and shoulders portrait, cinematic satirical artwork."
    )

    print(f"\n--- Test 2: Team principal caricature ---")
    workflow2 = build_workflow(prompt_text2, seed=123)
    prompt_id2 = queue_prompt(workflow2)

    print("  Generating (models cached, should be faster)...")
    result2 = wait_for_completion(prompt_id2, timeout=300)

    status2 = result2.get("status", {}).get("status_str", "unknown")
    print(f"  Status: {status2}")

    if status2 == "success":
        download_image(prompt_id2, result2, "runpod_lora_test2.png")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/runpod_lora_test*.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
