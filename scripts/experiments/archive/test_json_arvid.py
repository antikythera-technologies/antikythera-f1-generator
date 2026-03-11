#!/usr/bin/env python3
"""
Round 4b: Arvid Lindblad test — same v12 approach (4 style refs + identity).

Style refs: Fernando Alonso, Toto Wolff, Fred Vasseur, Charles Leclerc
Identity: Arvid Lindblad real photo

Usage:
    source .env
    python test_json_arvid.py
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

IDENTITY_IMAGE = "/mnt/c/Users/WianK/Desktop/arthur-lindblad.jpeg"
STYLE_IMAGES = [
    "test-output/style_ref_fernando.jpg",
    "test-output/style_ref_toto.jpg",
    "test-output/style_ref_fred.jpg",
    "test-output/style_ref_leclerc.jpg",
]
OUTPUT_DIR = Path("test-output")


def load_image_b64(path: str) -> tuple[str, str]:
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return base64.b64encode(data).decode(), mime


def make_image_part(path: str) -> dict:
    b64, mime = load_image_b64(path)
    return {"inlineData": {"mimeType": mime, "data": b64}}


def call_gemini(api_key: str, parts: list, label: str) -> bytes | None:
    url = f"{GEMINI_BASE_URL}/models/{MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    print(f"  Calling {MODEL} for {label}...")
    start = time.time()

    with httpx.Client(timeout=180.0) as client:
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
        print(f"  No candidates.")
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
            print(f"  Text: {part['text'][:200]}")

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
    print("ROUND 4b: Arvid Lindblad — 4 Style Refs + Identity")
    print("=" * 60)

    style_parts = []
    for path in STYLE_IMAGES:
        print(f"  Loading style ref: {Path(path).name}")
        style_parts.append(make_image_part(path))

    print(f"  Loading identity:  Arvid Lindblad")
    id_part = make_image_part(IDENTITY_IMAGE)

    schema = {
        "image_sources": {
            "IMAGE_1": {"role": "art_style", "character": "Fernando Alonso caricature"},
            "IMAGE_2": {"role": "art_style", "character": "Toto Wolff caricature"},
            "IMAGE_3": {"role": "art_style", "character": "Fred Vasseur caricature"},
            "IMAGE_4": {"role": "art_style", "character": "Charles Leclerc caricature"},
            "IMAGE_5": {"role": "identity", "character": "Arvid Lindblad real photo"}
        },
        "style_lock": {
            "source": "IMAGE_1 through IMAGE_4",
            "priority": "HIGH",
            "copy": ["oversized head proportions", "exaggerated facial features",
                     "hyper-detailed skin texture", "warm amber background",
                     "dramatic warm side lighting", "caricature artwork render style"]
        },
        "identity_lock": {
            "source": "IMAGE_5",
            "copy": ["face", "hair", "eyes", "bone structure"]
        },
        "text_override": {
            "clothing": "dark blue Red Bull Racing F1 team suit with Oracle and Bybit sponsor logos"
        },
        "output_must_not": ["look like a real photograph", "have normal head proportions",
                            "have cartoon eyes", "include a helmet"]
    }

    prompt = (
        f"```json\n{json.dumps(schema, indent=2)}\n```\n\n"
        "Using the routing above: The first FOUR images are all examples from the same "
        "caricature art series — study their shared art style carefully. "
        "The FIFTH image is the real person whose face and identity to use.\n\n"
        "Generate a NEW caricature of the person from IMAGE_5, rendered in the EXACT "
        "same art style as IMAGE_1 through IMAGE_4. The result must look like it belongs "
        "in the same caricature series as all four style reference images.\n\n"
        "The caricature must have a massively oversized head, exaggerated facial features, "
        "hyper-detailed skin with visible pores and texture, warm amber background, "
        "and dramatic warm side lighting.\n\n"
        "Dress the subject in a dark blue Red Bull Racing F1 team suit with Oracle and Bybit logos.\n"
        "Head and shoulders crop. Portrait orientation.\n\n"
        "The result must be a CARICATURE ARTWORK, not a photograph."
    )

    print(f"\n  Prompt: {len(prompt)} chars")
    print()

    all_parts = style_parts + [id_part, {"text": prompt}]

    result = call_gemini(api_key, all_parts, "arvid_v12")
    if result:
        save(result, "arvid_nanobana_v12.png")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/arvid_nanobana_v12.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
