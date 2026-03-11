#!/usr/bin/env python3
"""
Proof-of-concept: Two-reference-image generation with Nano Banana Pro.

Test hypothesis: Can we pass a real photo (identity) + an existing caricature (style)
to produce a NEW caricature that has the real person's likeness in the caricature art style?

Input 1 (identity): George Russell real photo
Input 2 (style):    Fernando Alonso original Manus.ai caricature
Expected output:    George Russell's face rendered in the Manus.ai caricature style

Usage:
    source .env
    python test_two_ref_nanobana.py
"""

import base64
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

import httpx

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Models to test (in order of preference)
MODELS = [
    "nano-banana-pro-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
    "gemini-2.5-flash-image",
]

# Paths
IDENTITY_IMAGE = "/mnt/c/Users/WianK/Desktop/George-russel.jpg"
STYLE_IMAGE = "test-output/style_ref_fernando.jpg"
OUTPUT_DIR = Path("test-output")


def load_image_b64(path: str) -> tuple[str, str]:
    """Load image file and return (base64_string, mime_type)."""
    path = str(path)
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return base64.b64encode(data).decode(), mime


def build_prompt(version: str = "v1") -> str:
    """Build the generation prompt.

    The prompt explicitly tells the model which image is identity vs style.
    """
    prompts = {
        # v1: Explicit two-image routing instructions
        "v1": (
            "I am providing two reference images.\n\n"
            "IMAGE 1 is the IDENTITY reference — use this person's exact face, facial structure, "
            "hair style, eye color, and all identity features.\n\n"
            "IMAGE 2 is the ART STYLE reference — copy this exact artistic style: "
            "hyper-detailed photorealistic skin with visible pores and wrinkles, "
            "slightly oversized caricature head proportions, exaggerated facial features, "
            "dramatic warm side lighting, warm burnt-orange to dark amber gradient background.\n\n"
            "Generate a new portrait of the person from IMAGE 1 rendered in the exact art style of IMAGE 2.\n\n"
            "The subject must wear a black Mercedes-AMG Petronas F1 team suit with silver Mercedes star logo "
            "and Petronas teal accents.\n\n"
            "Head and shoulders portrait crop. Portrait orientation (9:16 aspect ratio).\n\n"
            "CRITICAL: The face must be recognizably the person from IMAGE 1. "
            "The art style must match IMAGE 2 exactly. Do NOT make a photorealistic portrait. "
            "Do NOT make cartoon/googly eyes. The eyes must be realistic and detailed."
        ),

        # v2: Simpler, more direct
        "v2": (
            "Create a satirical caricature portrait of the person in the first image, "
            "using the exact same artistic style as the second image.\n\n"
            "Keep the person's face, hair, and features identical to the first image. "
            "Apply the caricature style from the second image: oversized head, "
            "hyper-detailed skin, warm amber background, dramatic lighting.\n\n"
            "Dress them in a black Mercedes F1 team suit with Petronas teal accents.\n\n"
            "Portrait crop, head and shoulders only. No helmet. Realistic eyes, not cartoon."
        ),

        # v3: Minimal — let the model figure it out
        "v3": (
            "Generate a satirical caricature portrait of the person in image 1, "
            "in the exact artistic style of image 2. "
            "Black Mercedes F1 suit. Warm amber background. "
            "Oversized head, photorealistic skin detail. No helmet. Realistic eyes."
        ),
    }
    return prompts.get(version, prompts["v1"])


def call_gemini_image_gen(
    api_key: str,
    model: str,
    identity_b64: str,
    identity_mime: str,
    style_b64: str,
    style_mime: str,
    prompt: str,
) -> bytes | None:
    """Call Gemini generateContent with two images + text, requesting image output."""

    url = f"{GEMINI_BASE_URL}/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": identity_mime,
                            "data": identity_b64,
                        }
                    },
                    {
                        "inlineData": {
                            "mimeType": style_mime,
                            "data": style_b64,
                        }
                    },
                    {
                        "text": prompt,
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    print(f"  Calling {model}...")
    start = time.time()

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    elapsed = time.time() - start
    print(f"  Response: HTTP {response.status_code} in {elapsed:.1f}s")

    if response.status_code != 200:
        print(f"  ERROR: {response.text[:500]}")
        return None

    data = response.json()

    # Check for safety blocks
    if data.get("promptFeedback", {}).get("blockReason"):
        print(f"  BLOCKED: {data['promptFeedback']['blockReason']}")
        return None

    candidates = data.get("candidates", [])
    if not candidates:
        print(f"  No candidates returned. Response keys: {list(data.keys())}")
        if "promptFeedback" in data:
            print(f"  promptFeedback: {json.dumps(data['promptFeedback'], indent=2)}")
        return None

    # Check finish reason
    finish_reason = candidates[0].get("finishReason", "unknown")
    if finish_reason not in ("STOP", "MAX_TOKENS"):
        print(f"  finishReason: {finish_reason}")
        if finish_reason == "SAFETY":
            safety = candidates[0].get("safetyRatings", [])
            for s in safety:
                if s.get("probability", "NEGLIGIBLE") != "NEGLIGIBLE":
                    print(f"    {s['category']}: {s['probability']}")
            return None

    # Extract image from response parts
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = []
    image_data = None

    for part in parts:
        if "inlineData" in part:
            image_data = base64.b64decode(part["inlineData"]["data"])
            mime = part["inlineData"].get("mimeType", "image/png")
            print(f"  Got image: {len(image_data):,} bytes ({mime})")
        elif "text" in part:
            text_parts.append(part["text"])

    if text_parts:
        print(f"  Model text: {' '.join(text_parts)[:200]}")

    if not image_data:
        print(f"  No image in response. Parts: {[list(p.keys()) for p in parts]}")
        return None

    return image_data


def main():
    # Get API key
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set. Run: source .env")
        sys.exit(1)

    print("=" * 60)
    print("TWO-REFERENCE IMAGE TEST: Identity + Style")
    print("=" * 60)

    # Verify input files
    if not Path(IDENTITY_IMAGE).exists():
        print(f"ERROR: Identity image not found: {IDENTITY_IMAGE}")
        sys.exit(1)
    if not Path(STYLE_IMAGE).exists():
        print(f"ERROR: Style image not found: {STYLE_IMAGE}")
        sys.exit(1)

    print(f"Identity (face):  {IDENTITY_IMAGE}")
    print(f"Style (art):      {STYLE_IMAGE}")
    print()

    # Load images
    print("Loading images...")
    identity_b64, identity_mime = load_image_b64(IDENTITY_IMAGE)
    style_b64, style_mime = load_image_b64(STYLE_IMAGE)
    print(f"  Identity: {len(identity_b64) * 3 // 4 // 1024}KB ({identity_mime})")
    print(f"  Style:    {len(style_b64) * 3 // 4 // 1024}KB ({style_mime})")
    print()

    # Model to use (first arg or default)
    model = sys.argv[1] if len(sys.argv) > 1 else MODELS[0]
    print(f"Model: {model}")
    print()

    # Test all prompt versions
    for version in ["v1", "v2", "v3"]:
        prompt = build_prompt(version)
        print(f"--- Prompt {version} ({len(prompt)} chars) ---")
        print(f"  {prompt[:100]}...")
        print()

        image_data = call_gemini_image_gen(
            api_key=api_key,
            model=model,
            identity_b64=identity_b64,
            identity_mime=identity_mime,
            style_b64=style_b64,
            style_mime=style_mime,
            prompt=prompt,
        )

        if image_data:
            output_path = OUTPUT_DIR / f"george_nanobana_{version}.png"
            with open(output_path, "wb") as f:
                f.write(image_data)
            print(f"  SAVED: {output_path}")
        else:
            print(f"  FAILED: No image generated for {version}")

        print()

    print("=" * 60)
    print("DONE — Check test-output/george_nanobana_v*.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
