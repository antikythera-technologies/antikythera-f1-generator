#!/usr/bin/env python3
"""
Generate a proper SCENE image (not just a portrait) for video generation testing.

Scene: Max Verstappen arriving at the Australian Grand Prix, Albert Park circuit.
This is what real episode scene images should look like — characters in environments,
doing things, not just headshots against gradients.

Uses: Flux Dev fp8 + ANTKF1STYLE LoRA + PuLID (face identity)
"""

import json
import os
import time
import uuid
from pathlib import Path

import httpx

RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "tims42v3eaqrz7")
COMFYUI_URL = f"https://{RUNPOD_POD_ID}-19123.proxy.runpod.net"
OUTPUT_DIR = Path("test-output/scene-images")
TRIGGER = "ANTKF1STYLE"


def build_scene_workflow(
    prompt_text: str,
    negative_prompt: str = "",
    face_image: str = "max_verstappen.jpg",
    lora_strength: float = 1.4,
    pulid_weight: float = 0.7,
    width: int = 1344,       # Landscape for scenes!
    height: int = 768,       # Landscape for scenes!
    steps: int = 20,
    seed: int = 42,
) -> dict:
    """Build ComfyUI workflow for a SCENE image (landscape, environmental)."""
    workflow = {}

    # UNET Loader (Flux Dev fp8)
    workflow["1"] = {
        "class_type": "UNETLoader",
        "inputs": {
            "unet_name": "flux1-dev-fp8.safetensors",
            "weight_dtype": "fp8_e4m3fn",
        },
    }

    # Dual CLIP Loader
    workflow["5"] = {
        "class_type": "DualCLIPLoader",
        "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
            "type": "flux",
        },
    }

    # LoRA Loader (ANTKF1STYLE)
    workflow["2"] = {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["1", 0],
            "clip": ["5", 0],
            "lora_name": "antkf1style_v1.safetensors",
            "strength_model": lora_strength,
            "strength_clip": lora_strength,
        },
    }

    # CLIP Text Encode (positive) — uses DualCLIP directly, NOT LoRA-modified
    workflow["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": prompt_text,
            "clip": ["5", 0],
        },
    }

    # CLIP Text Encode (negative)
    workflow["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": negative_prompt,
            "clip": ["5", 0],
        },
    }

    # Empty SD3 Latent (required for Flux)
    workflow["8"] = {
        "class_type": "EmptySD3LatentImage",
        "inputs": {
            "width": width,
            "height": height,
            "batch_size": 1,
        },
    }

    # VAE Loader
    workflow["9"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": "ae.safetensors"},
    }

    # PuLID model loader
    workflow["10"] = {
        "class_type": "PulidFluxModelLoader",
        "inputs": {"pulid_file": "pulid_flux_v0.9.0.safetensors"},
    }

    # InsightFace loader
    workflow["11"] = {
        "class_type": "PulidFluxInsightFaceLoader",
        "inputs": {"provider": "CUDA"},
    }

    # EVA-CLIP loader
    workflow["12"] = {
        "class_type": "PulidFluxEvaClipLoader",
        "inputs": {},
    }

    # Load face reference
    workflow["13"] = {
        "class_type": "LoadImage",
        "inputs": {"image": face_image},
    }

    # Apply PuLID
    workflow["14"] = {
        "class_type": "ApplyPulidFlux",
        "inputs": {
            "model": ["2", 0],
            "pulid_flux": ["10", 0],
            "eva_clip": ["12", 0],
            "face_analysis": ["11", 0],
            "image": ["13", 0],
            "weight": pulid_weight,
            "start_at": 0.0,
            "end_at": 1.0,
        },
    }

    # KSampler
    workflow["20"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["14", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["8", 0],
            "seed": seed,
            "steps": steps,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
        },
    }

    # VAE Decode
    workflow["21"] = {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["20", 0],
            "vae": ["9", 0],
        },
    }

    # Save Image
    workflow["22"] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": ["21", 0],
            "filename_prefix": "scene_test",
        },
    }

    return workflow


def queue_prompt(workflow: dict) -> str:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{COMFYUI_URL}/prompt", json=payload)
    if resp.status_code != 200:
        print(f"  ERROR: {resp.status_code}: {resp.text[:500]}")
        raise Exception(f"Queue failed: {resp.status_code}")
    prompt_id = resp.json().get("prompt_id")
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
        print(f"  Generating... ({elapsed}s)", end="\r")
        time.sleep(3)
    raise Exception(f"Timeout after {timeout}s")


def download_image(output: dict, filename: str) -> str:
    outputs = output.get("outputs", {})
    for node_output in outputs.values():
        images = node_output.get("images", [])
        for img in images:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{COMFYUI_URL}/view",
                    params={
                        "filename": img["filename"],
                        "subfolder": img.get("subfolder", ""),
                        "type": "output",
                    },
                )
            if resp.status_code == 200:
                path = OUTPUT_DIR / filename
                path.write_bytes(resp.content)
                print(f"  SAVED: {path} ({len(resp.content) / 1024:.0f} KB)")
                return str(path)
    raise Exception("No image in output")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("SCENE IMAGE GENERATION TEST")
    print(f"ComfyUI: {COMFYUI_URL}")
    print("=" * 70)

    # ==============================================================
    # Scene 1: Verstappen arriving at Albert Park paddock
    # ==============================================================
    scenes = [
        {
            "name": "verstappen_arriving_albert_park",
            "prompt": (
                f"{TRIGGER} satirical caricature scene, wide shot. "
                f"A confident Dutch F1 driver with short dark hair, intense stare, sharp jawline, slight stubble, "
                f"wearing a dark blue Red Bull Racing team polo with Oracle and Bybit logos, "
                f"walking through the Albert Park paddock in Melbourne, Australia. "
                f"Palm trees and modern paddock buildings in the background, bright Australian sunshine. "
                f"He has a bored, matter-of-fact expression, like arriving at the office for another routine day. "
                f"One hand in pocket, slightly slouched posture, radiating casual dominance. "
                f"Other team personnel and journalists visible in the background, all looking at him. "
                f"Oversized head with exaggerated features, hyper-detailed photorealistic skin. "
                f"Dramatic warm lighting, cinematic satirical artwork."
            ),
            "negative": "photograph, realistic proportions, normal head size, anime, cartoon, low quality",
            "seed": 42,
        },
        {
            "name": "verstappen_pit_garage",
            "prompt": (
                f"{TRIGGER} satirical caricature scene, medium shot. "
                f"A dominant Dutch F1 driver with short dark hair, intense stare, sharp jawline, "
                f"standing in the Red Bull Racing pit garage, arms crossed, looking at telemetry screens. "
                f"Wearing a dark blue Red Bull Racing race suit with Oracle and Bybit logos, unzipped at the top. "
                f"The RB21 car visible behind him with mechanics working on it. "
                f"Fluorescent garage lighting, tool boards and tire warmers visible. "
                f"His expression is analytical and slightly bored, like a chess grandmaster reviewing a trivial puzzle. "
                f"Oversized head with exaggerated features, hyper-detailed photorealistic skin with visible pores. "
                f"Dramatic side lighting with deep shadows, cinematic satirical artwork."
            ),
            "negative": "photograph, realistic proportions, normal head size, anime, cartoon, low quality",
            "seed": 77,
        },
        {
            "name": "verstappen_press_conference",
            "prompt": (
                f"{TRIGGER} satirical caricature scene. "
                f"A bored Dutch F1 champion with short dark hair, intense eyes, sharp jawline, slight stubble, "
                f"sitting at an FIA press conference table with microphones in front of him. "
                f"Wearing a dark blue Red Bull Racing team polo. "
                f"His expression is deadpan, slightly dismissive, chin resting on one hand. "
                f"FIA and F1 branding banners behind him, other drivers blurred in background seats. "
                f"Press conference room with harsh overhead lighting. "
                f"Oversized head with exaggerated features, one eye slightly wider than the other. "
                f"Hyper-detailed photorealistic skin, dramatic lighting, cinematic satirical artwork."
            ),
            "negative": "photograph, realistic proportions, normal head size, anime, cartoon, low quality",
            "seed": 123,
        },
    ]

    for scene in scenes:
        print(f"\n--- {scene['name']} ---")
        print(f"  Prompt: {scene['prompt'][:100]}...")

        workflow = build_scene_workflow(
            prompt_text=scene["prompt"],
            negative_prompt=scene["negative"],
            face_image="max_verstappen.jpg",
            lora_strength=1.4,
            pulid_weight=0.7,
            width=1344,     # Landscape
            height=768,
            steps=20,
            seed=scene["seed"],
        )

        prompt_id = queue_prompt(workflow)
        result = wait_for_completion(prompt_id, timeout=600)

        status = result.get("status", {}).get("status_str", "unknown")
        print(f"  Status: {status}")

        if status == "success":
            download_image(result, f"{scene['name']}.png")
        else:
            print(f"  FAILED: {json.dumps(result.get('status', {}), indent=2)[:500]}")

    print("\n" + "=" * 70)
    print(f"DONE — Check {OUTPUT_DIR}/")
    print("=" * 70)


if __name__ == "__main__":
    main()
