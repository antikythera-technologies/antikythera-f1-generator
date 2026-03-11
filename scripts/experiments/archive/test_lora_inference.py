#!/usr/bin/env python3
"""
Test the trained F1 caricature style LoRA.

Two approaches:
1. flux-lora (text-to-image + LoRA) — verify the LoRA produces the right style
2. flux-kontext-lora (image + LoRA) — real photo in, caricature out

Usage:
    export FAL_KEY="your-key"
    python test_lora_inference.py
"""

import json
import os
import sys
from pathlib import Path

import fal_client

# Load training result to get LoRA URL
RESULT_PATH = "test-output/lora_training_result.json"
IDENTITY_GEORGE = "/mnt/c/Users/WianK/Desktop/George-russel.jpg"
IDENTITY_ARVID = "/mnt/c/Users/WianK/Desktop/arthur-lindblad.jpeg"
TRIGGER = "ANTKF1STYLE"
OUTPUT_DIR = Path("test-output")


def get_lora_url() -> str:
    with open(RESULT_PATH) as f:
        result = json.load(f)
    return result["diffusers_lora_file"]["url"]


def save(url_or_data, name: str):
    """Download and save image from URL."""
    import httpx
    path = OUTPUT_DIR / name

    if isinstance(url_or_data, str) and url_or_data.startswith("http"):
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url_or_data)
            path.write_bytes(resp.content)
    elif isinstance(url_or_data, bytes):
        path.write_bytes(url_or_data)

    print(f"  SAVED: {path}")


def test_text_to_image(lora_url: str):
    """Test 1: Pure text-to-image with LoRA — does the style come through?"""
    print("\n--- TEST 1: Text-to-Image + LoRA (no face reference) ---")
    print("  Testing if LoRA produces the caricature style from text alone")

    result = fal_client.subscribe(
        "fal-ai/flux-lora",
        arguments={
            "prompt": (
                f"A {TRIGGER} satirical caricature portrait of a young male F1 driver, "
                f"wearing a dark blue Red Bull Racing suit with Oracle and Bybit logos. "
                f"Oversized head with exaggerated facial features, "
                f"hyper-detailed photorealistic skin with visible pores, "
                f"warm burnt-orange to dark amber gradient background, "
                f"dramatic warm side lighting with deep shadows. "
                f"Head and shoulders portrait, cinematic satirical artwork."
            ),
            "loras": [{"path": lora_url, "scale": 1.0}],
            "image_size": {"width": 768, "height": 1344},
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
        },
    )

    img_url = result["images"][0]["url"]
    print(f"  Image URL: {img_url}")
    save(img_url, "lora_test_t2i.png")


def test_kontext_george(lora_url: str):
    """Test 2: Kontext + LoRA — real George Russell photo → caricature."""
    print("\n--- TEST 2: Kontext + LoRA — George Russell ---")

    # Upload identity photo
    print("  Uploading George Russell photo...")
    photo_url = fal_client.upload_file(IDENTITY_GEORGE)
    print(f"  Photo URL: {photo_url}")

    for scale in [0.8, 1.0, 1.2]:
        label = f"s{str(scale).replace('.', '')}"
        print(f"\n  Generating with LoRA scale={scale}...")

        result = fal_client.subscribe(
            "fal-ai/flux-kontext-lora",
            arguments={
                "image_url": photo_url,
                "prompt": (
                    f"Transform this photo into a {TRIGGER} satirical caricature portrait. "
                    f"Make the head massively oversized with exaggerated facial features. "
                    f"Hyper-detailed skin with visible pores and wrinkles. "
                    f"Keep the person's face identity and hair recognizable. "
                    f"Black Mercedes F1 team suit with Petronas teal accents. "
                    f"Warm burnt-orange to dark amber gradient background. "
                    f"Dramatic warm side lighting. Cinematic satirical artwork. "
                    f"NOT a photograph — a stylized caricature."
                ),
                "loras": [{"path": lora_url, "scale": scale}],
                "num_inference_steps": 30,
                "guidance_scale": 2.5,
            },
        )

        img_url = result["images"][0]["url"]
        save(img_url, f"lora_george_{label}.png")


def test_kontext_arvid(lora_url: str):
    """Test 3: Kontext + LoRA — Arvid Lindblad photo → caricature."""
    print("\n--- TEST 3: Kontext + LoRA — Arvid Lindblad ---")

    print("  Uploading Arvid Lindblad photo...")
    photo_url = fal_client.upload_file(IDENTITY_ARVID)
    print(f"  Photo URL: {photo_url}")

    print("  Generating with LoRA scale=1.0...")

    result = fal_client.subscribe(
        "fal-ai/flux-kontext-lora",
        arguments={
            "image_url": photo_url,
            "prompt": (
                f"Transform this photo into a {TRIGGER} satirical caricature portrait. "
                f"Make the head massively oversized with exaggerated facial features. "
                f"Hyper-detailed skin with visible pores and wrinkles. "
                f"Keep the person's face identity and hair recognizable. "
                f"Dark blue Red Bull Racing F1 team suit with Oracle and Bybit logos. "
                f"Warm burnt-orange to dark amber gradient background. "
                f"Dramatic warm side lighting. Cinematic satirical artwork. "
                f"NOT a photograph — a stylized caricature."
            ),
            "loras": [{"path": lora_url, "scale": 1.0}],
            "num_inference_steps": 30,
            "guidance_scale": 2.5,
        },
    )

    img_url = result["images"][0]["url"]
    save(img_url, "lora_arvid_s10.png")


def main():
    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        print("ERROR: FAL_KEY not set")
        sys.exit(1)

    lora_url = get_lora_url()

    print("=" * 60)
    print("LORA INFERENCE TESTS")
    print("=" * 60)
    print(f"  LoRA: {lora_url[:80]}...")
    print(f"  Trigger: {TRIGGER}")

    # Test 1: Does the LoRA style work at all?
    test_text_to_image(lora_url)

    # Test 2: George Russell — real photo → caricature (3 LoRA scales)
    test_kontext_george(lora_url)

    # Test 3: Arvid Lindblad — the one that failed with Nano Banana
    test_kontext_arvid(lora_url)

    print("\n" + "=" * 60)
    print("ALL TESTS DONE")
    print("Check test-output/lora_*.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
