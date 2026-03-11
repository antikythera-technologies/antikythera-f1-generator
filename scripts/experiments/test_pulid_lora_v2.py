#!/usr/bin/env python3
"""
Test PuLID + LoRA v2: Tuned settings based on w07 feedback.

Changes from v1:
- LoRA strength bumped to 1.2 and 1.4 (more caricature)
- PuLID weight locked at 0.7
- Prompt: evil villain expression, Mercedes team colors background
- Correct team overalls description
"""

import json
import os
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
    pulid_weight: float = 0.7,
    width: int = 768,
    height: int = 1344,
    seed: int = 42,
) -> dict:
    """Build ComfyUI workflow: Flux + LoRA + PuLID."""
    return {
        "4": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
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
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "20": {
            "class_type": "PulidFluxModelLoader",
            "inputs": {"pulid_file": "pulid_flux_v0.9.0.safetensors"},
        },
        "21": {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {"provider": "CUDA"},
        },
        "22": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        },
        "23": {
            "class_type": "LoadImage",
            "inputs": {"image": face_image},
        },
        "25": {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "model": ["10", 0],
                "pulid_flux": ["20", 0],
                "eva_clip": ["22", 0],
                "face_analysis": ["21", 0],
                "image": ["23", 0],
                "weight": pulid_weight,
                "start_at": 0.0,
                "end_at": 1.0,
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
        "5": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["25", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
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
                "filename_prefix": "pulid_lora_v2",
                "images": ["8", 0],
            },
        },
    }


def queue_prompt(workflow: dict) -> str:
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
    print("PULID + LORA v2: Higher LoRA, Evil Villain Expression")
    print(f"Endpoint: {COMFYUI_URL}")
    print("=" * 60)

    # George Russell — Mercedes team
    # Background: Mercedes colors (dark teal/black gradient)
    # Expression: evil villain, menacing
    # Overalls: accurate Mercedes-AMG Petronas team suit

    prompt_george = (
        f"A {TRIGGER} satirical caricature portrait of a young male F1 driver, "
        f"wearing a black Mercedes-AMG Petronas F1 team race suit with Petronas teal green accents, "
        f"INEOS and Petronas sponsor logos visible on the suit. "
        f"Evil villain expression, menacing smirk, narrowed eyes, scheming look. "
        f"Oversized head with exaggerated facial features, "
        f"hyper-detailed photorealistic skin with visible pores and texture, "
        f"dark teal to black gradient background matching Mercedes team colors, "
        f"dramatic warm side lighting with deep shadows. "
        f"Head and shoulders portrait, cinematic satirical artwork."
    )

    tests = [
        # (label, lora_strength, seed)
        ("george_v2_lora12", 1.2, 42),
        ("george_v2_lora14", 1.4, 42),
        ("george_v2_lora12_s99", 1.2, 99),
    ]

    for label, lora_s, seed in tests:
        print(f"\n--- {label}: LoRA={lora_s}, PuLID=0.7, seed={seed} ---")

        workflow = build_pulid_lora_workflow(
            prompt_text=prompt_george,
            face_image="george_russell.jpg",
            lora_strength=lora_s,
            pulid_weight=0.7,
            seed=seed,
        )
        prompt_id = queue_prompt(workflow)

        print("  Generating...")
        result = wait_for_completion(prompt_id, timeout=600)

        status = result.get("status", {}).get("status_str", "unknown")
        print(f"  Status: {status}")

        if status == "success":
            download_image(prompt_id, result, f"{label}.png")
        else:
            print(f"  FAILED: {json.dumps(result.get('status', {}), indent=2)[:500]}")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/george_v2_*.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
