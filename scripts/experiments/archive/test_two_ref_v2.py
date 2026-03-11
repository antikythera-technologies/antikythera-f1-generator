#!/usr/bin/env python3
"""
Round 2: Push harder on style transfer.

Problem from round 1: Model preserves identity perfectly but barely applies
the caricature style. Results are too photorealistic.

Fixes attempted:
- v4: Swap image order (style FIRST, identity second) — models weight first image more
- v5: Same swap + much more aggressive style language
- v6: Two style references (Fernando original + Flux Pro George) + identity photo
- v7: Style-first with explicit "do NOT make photorealistic" negative constraints

Usage:
    source .env
    python test_two_ref_v2.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "nano-banana-pro-preview"

IDENTITY_IMAGE = "/mnt/c/Users/WianK/Desktop/George-russel.jpg"
STYLE_IMAGE_FERNANDO = "test-output/style_ref_fernando.jpg"
STYLE_IMAGE_FLUX = "test-output/george_russell_flux_1.png"  # Flux Pro caricature (no likeness but perfect style)
OUTPUT_DIR = Path("test-output")


def load_image_b64(path: str) -> tuple[str, str]:
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return base64.b64encode(data).decode(), mime


def call_gemini(api_key: str, parts: list, label: str) -> bytes | None:
    """Call Gemini with arbitrary parts list."""
    url = f"{GEMINI_BASE_URL}/models/{MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    print(f"  Calling {MODEL} for {label}...")
    start = time.time()

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json=payload, headers={"Content-Type": "application/json"})

    elapsed = time.time() - start
    print(f"  HTTP {response.status_code} in {elapsed:.1f}s")

    if response.status_code != 200:
        print(f"  ERROR: {response.text[:500]}")
        return None

    data = response.json()

    if data.get("promptFeedback", {}).get("blockReason"):
        print(f"  BLOCKED: {data['promptFeedback']['blockReason']}")
        return None

    candidates = data.get("candidates", [])
    if not candidates:
        print(f"  No candidates. Keys: {list(data.keys())}")
        return None

    finish = candidates[0].get("finishReason", "unknown")
    if finish == "SAFETY":
        print(f"  SAFETY blocked")
        return None

    parts_out = candidates[0].get("content", {}).get("parts", [])
    for part in parts_out:
        if "inlineData" in part:
            img = base64.b64decode(part["inlineData"]["data"])
            print(f"  Got image: {len(img):,} bytes")
            return img
        elif "text" in part:
            print(f"  Text: {part['text'][:150]}")

    print("  No image in response")
    return None


def save(data: bytes, name: str):
    path = OUTPUT_DIR / name
    with open(path, "wb") as f:
        f.write(data)
    print(f"  SAVED: {path}")


def main():
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print("ROUND 2: Pushing Style Transfer Harder")
    print("=" * 60)

    # Load all images
    id_b64, id_mime = load_image_b64(IDENTITY_IMAGE)
    style_b64, style_mime = load_image_b64(STYLE_IMAGE_FERNANDO)
    flux_b64, flux_mime = load_image_b64(STYLE_IMAGE_FLUX)

    id_part = {"inlineData": {"mimeType": id_mime, "data": id_b64}}
    style_part = {"inlineData": {"mimeType": style_mime, "data": style_b64}}
    flux_part = {"inlineData": {"mimeType": flux_mime, "data": flux_b64}}

    # ---- v4: SWAP ORDER — style first, identity second ----
    print("\n--- v4: Style image FIRST, identity second ---")
    prompt_v4 = (
        "The FIRST image is the ART STYLE you must replicate exactly — "
        "notice the oversized head, exaggerated facial proportions, hyper-detailed skin texture, "
        "warm amber background, and dramatic side lighting. This is a caricature, NOT a photograph.\n\n"
        "The SECOND image is the person whose face and identity you must use.\n\n"
        "Generate a caricature portrait of the person from the second image "
        "rendered in the EXACT same caricature art style as the first image. "
        "The result must look like it belongs in the same series as the first image. "
        "Black Mercedes F1 team suit. Portrait orientation."
    )
    result = call_gemini(api_key, [style_part, id_part, {"text": prompt_v4}], "v4")
    if result:
        save(result, "george_nanobana_v4.png")

    # ---- v5: Swap + aggressive anti-realism language ----
    print("\n--- v5: Style-first + aggressive anti-realism ---")
    prompt_v5 = (
        "FIRST IMAGE: This is the target art style. Study it carefully — "
        "it is a CARICATURE with: massively oversized head relative to body, "
        "exaggerated facial bone structure, visible skin pores and wrinkles at extreme detail, "
        "warm burnt-orange gradient background, cinematic warm side lighting.\n\n"
        "SECOND IMAGE: This is the person whose likeness to use.\n\n"
        "Create a NEW caricature of the person in the second image, matching the first image's style EXACTLY.\n\n"
        "CRITICAL STYLE REQUIREMENTS:\n"
        "- Head must be SIGNIFICANTLY oversized compared to body (same proportions as first image)\n"
        "- Facial features must be EXAGGERATED — larger nose, more prominent chin, wider smile\n"
        "- Skin must have extreme hyper-detail: every pore, wrinkle, stubble hair visible\n"
        "- Background: warm burnt-orange to dark amber gradient ONLY\n"
        "- Lighting: dramatic warm side lighting with deep shadows on one side of face\n\n"
        "DO NOT make a photorealistic portrait. DO NOT make it look like a real photograph. "
        "It MUST look like a stylized caricature artwork, the same series as the first image.\n\n"
        "Clothing: black Mercedes-AMG Petronas F1 team suit.\n"
        "Crop: head and shoulders. No helmet. Realistic detailed eyes (not cartoon)."
    )
    result = call_gemini(api_key, [style_part, id_part, {"text": prompt_v5}], "v5")
    if result:
        save(result, "george_nanobana_v5.png")

    # ---- v6: TWO style refs (Fernando + Flux Pro) + identity ----
    print("\n--- v6: Two style references + identity ---")
    prompt_v6 = (
        "The FIRST TWO images are ART STYLE references — they show the exact caricature style I want. "
        "Study both carefully: oversized heads, exaggerated proportions, hyper-detailed skin, "
        "warm amber backgrounds, cinematic lighting. Both are from the same art series.\n\n"
        "The THIRD image is the real person whose face and identity to use.\n\n"
        "Generate a caricature of the person from the third image in the EXACT art style "
        "of the first two images. It must look like part of the same caricature series.\n\n"
        "Black Mercedes F1 suit. Warm amber background. Oversized head. "
        "NOT a photograph — a stylized caricature artwork. Realistic eyes, not cartoon."
    )
    result = call_gemini(api_key, [style_part, flux_part, id_part, {"text": prompt_v6}], "v6")
    if result:
        save(result, "george_nanobana_v6.png")

    # ---- v7: Style-first with explicit negatives ----
    print("\n--- v7: Style-first + negative constraints ---")
    prompt_v7 = (
        "STYLE REFERENCE (first image): Copy this caricature art style exactly.\n"
        "IDENTITY REFERENCE (second image): Use this person's face.\n\n"
        "Generate a caricature portrait combining the identity from the second image "
        "with the art style from the first image.\n\n"
        "The output MUST have these properties from the style reference:\n"
        "- Oversized head (at least 40% larger than realistic proportions)\n"
        "- Exaggerated jawline, nose, and forehead\n"
        "- Hyper-detailed skin rendering with visible texture\n"
        "- Warm amber/orange gradient background\n"
        "- Dramatic warm directional lighting\n"
        "- Slightly humorous, satirical tone\n\n"
        "The output must NOT:\n"
        "- Look like a real photograph\n"
        "- Have normal/realistic head-to-body proportions\n"
        "- Have flat or cool-toned lighting\n"
        "- Have any background other than warm amber gradient\n"
        "- Have cartoon or googly eyes\n\n"
        "Clothing: black Mercedes F1 team suit with Petronas teal accents.\n"
        "Portrait orientation, head and shoulders crop."
    )
    result = call_gemini(api_key, [style_part, id_part, {"text": prompt_v7}], "v7")
    if result:
        save(result, "george_nanobana_v7.png")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/george_nanobana_v4-v7.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
