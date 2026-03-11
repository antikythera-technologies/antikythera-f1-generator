#!/usr/bin/env python3
"""
Round 3: JSON prompt method for image generation.

Uses structured JSON to explicitly route which attributes come from which source.
Based on the JsonPromptMaker concept — deterministic attribute routing.

Builds on v6 (best result so far): two style refs + identity photo.

Usage:
    source .env
    python test_json_prompt.py
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
STYLE_IMAGE_FLUX = "test-output/george_russell_flux_1.png"
OUTPUT_DIR = Path("test-output")


def load_image_b64(path: str) -> tuple[str, str]:
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return base64.b64encode(data).decode(), mime


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


# ============================================================
# JSON PROMPT SCHEMAS
# ============================================================

def json_prompt_v8() -> str:
    """Full JSON schema with explicit state routing per attribute."""
    schema = {
        "task": "generate_caricature_portrait",
        "image_routing": {
            "IMAGE_1": {
                "role": "STYLE_REFERENCE",
                "description": "Caricature art style to replicate exactly"
            },
            "IMAGE_2": {
                "role": "STYLE_REFERENCE",
                "description": "Second caricature style example from the same series"
            },
            "IMAGE_3": {
                "role": "IDENTITY_REFERENCE",
                "description": "Real person whose face and identity to use"
            }
        },
        "generation_payload": {
            "subject": {
                "identity": {
                    "face": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"},
                    "facial_structure": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"},
                    "hair_style": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"},
                    "hair_color": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"},
                    "eye_color": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"},
                    "skin_tone": {"state": "IMAGE_LOCKED", "source": "IMAGE_3"}
                },
                "style_transfer": {
                    "head_proportions": {"state": "IMAGE_LOCKED", "source": "IMAGE_1", "value": "oversized head, at least 40% larger than realistic"},
                    "facial_exaggeration": {"state": "IMAGE_LOCKED", "source": "IMAGE_1", "value": "exaggerated bone structure, prominent features"},
                    "skin_rendering": {"state": "IMAGE_LOCKED", "source": "IMAGE_1", "value": "hyper-detailed with visible pores, wrinkles, stubble"},
                    "art_style": {"state": "IMAGE_LOCKED", "source": "IMAGE_1", "value": "satirical caricature artwork, NOT a photograph"},
                    "render_quality": {"state": "IMAGE_LOCKED", "source": "IMAGE_1"}
                }
            },
            "appearance": {
                "clothing": {
                    "state": "TEXT_OVERRIDE",
                    "value": "black Mercedes-AMG Petronas F1 team racing suit with silver Mercedes star logo, Petronas teal accents, sponsor logos (INEOS, UBS, TeamViewer, Crowdstrike)"
                }
            },
            "environment": {
                "background": {
                    "state": "IMAGE_LOCKED",
                    "source": "IMAGE_1",
                    "value": "warm burnt-orange to dark amber gradient"
                },
                "lighting": {
                    "state": "IMAGE_LOCKED",
                    "source": "IMAGE_1",
                    "value": "dramatic warm side lighting with deep shadows"
                }
            },
            "camera": {
                "framing": {"state": "TEXT_OVERRIDE", "value": "head and shoulders portrait crop"},
                "orientation": {"state": "TEXT_OVERRIDE", "value": "portrait 9:16"},
                "angle": {"state": "TEXT_OVERRIDE", "value": "eye-level, facing camera"}
            },
            "negative_constraints": [
                "photorealistic portrait",
                "real photograph look",
                "normal realistic head-to-body proportions",
                "cartoon eyes or googly eyes",
                "helmet",
                "cool-toned lighting",
                "flat lighting",
                "any background other than warm amber gradient"
            ]
        },
        "quality_controls": {
            "style_priority": "Style from IMAGE_1 and IMAGE_2 takes precedence over realism",
            "identity_priority": "Face identity from IMAGE_3 must be recognizable",
            "mandatory": "The output MUST look like a caricature artwork from the same series as IMAGE_1 and IMAGE_2, NOT like a real photograph"
        }
    }

    return (
        "You are an image generation engine. Follow the JSON instruction payload below EXACTLY. "
        "Three reference images are provided in the order specified by the image_routing field.\n\n"
        f"```json\n{json.dumps(schema, indent=2)}\n```"
    )


def json_prompt_v9() -> str:
    """Compact JSON — less verbose, more direct routing."""
    schema = {
        "mode": "style_transfer_with_identity",
        "images": {
            "1": "style_reference (caricature art style to copy)",
            "2": "style_reference (second example of same art series)",
            "3": "identity_reference (real person's face to use)"
        },
        "from_style_images": {
            "copy_exactly": [
                "oversized head proportions (head 40%+ larger than normal)",
                "exaggerated facial features and bone structure",
                "hyper-detailed skin texture (visible pores, wrinkles, stubble)",
                "warm burnt-orange to dark amber gradient background",
                "dramatic warm side lighting with deep shadows",
                "satirical caricature art style",
                "painted/rendered look (NOT photographic)"
            ]
        },
        "from_identity_image": {
            "copy_exactly": [
                "face shape and structure",
                "hair style and color",
                "eye color",
                "all identifying facial features"
            ]
        },
        "from_text": {
            "clothing": "black Mercedes-AMG Petronas F1 team suit, Petronas teal accents",
            "crop": "head and shoulders portrait",
            "orientation": "portrait 9:16"
        },
        "must_not": [
            "look like a real photograph",
            "have realistic head-to-body proportions",
            "have cartoon/googly eyes",
            "include a helmet"
        ],
        "critical": "Output MUST be a caricature artwork matching the style of images 1 and 2. It must NOT look photorealistic."
    }

    return (
        "Generate an image following this structured prompt specification:\n\n"
        f"```json\n{json.dumps(schema, indent=2)}\n```"
    )


def json_prompt_v10() -> str:
    """Hybrid: JSON routing header + natural language body."""
    schema = {
        "image_sources": {
            "IMAGE_1": {"role": "art_style", "lock": ["proportions", "skin_detail", "background", "lighting", "render_style"]},
            "IMAGE_2": {"role": "art_style", "lock": ["proportions", "skin_detail", "background", "lighting", "render_style"]},
            "IMAGE_3": {"role": "identity", "lock": ["face", "hair", "eyes", "bone_structure"]}
        },
        "output_style": "IMAGE_LOCKED from IMAGE_1 — satirical caricature artwork",
        "output_realism": "FORBIDDEN — must NOT look like a photograph"
    }

    return (
        f"```json\n{json.dumps(schema, indent=2)}\n```\n\n"
        "Using the routing above: Create a satirical caricature portrait of the person in IMAGE_3, "
        "rendered in the EXACT art style of IMAGE_1 and IMAGE_2.\n\n"
        "The caricature must have a massively oversized head, exaggerated facial features, "
        "hyper-detailed skin with visible pores and texture, warm amber background, "
        "and dramatic warm side lighting — exactly like the style reference images.\n\n"
        "Dress the subject in a black Mercedes F1 team suit with Petronas teal accents.\n"
        "Head and shoulders crop. Portrait orientation.\n\n"
        "The result must look like a CARICATURE ARTWORK, not a photograph. "
        "It must belong in the same art series as IMAGE_1 and IMAGE_2."
    )


def json_prompt_v11() -> str:
    """Minimal JSON — just routing + constraints, let the model do the rest."""
    schema = {
        "generate": "satirical caricature portrait",
        "style": {"source": "image_1 and image_2", "lock": True, "priority": "HIGH"},
        "identity": {"source": "image_3", "lock": True, "priority": "MEDIUM"},
        "override": {"clothing": "black Mercedes F1 suit, Petronas teal"},
        "constraints": {
            "must": ["oversized head", "exaggerated features", "caricature artwork", "amber background", "warm side lighting"],
            "must_not": ["photorealistic", "photograph", "normal proportions", "cartoon eyes", "helmet"]
        }
    }

    return (
        "Follow this image generation specification exactly:\n\n"
        f"```json\n{json.dumps(schema, indent=2)}\n```\n\n"
        "Image 1 and Image 2 are the art style. Image 3 is the person. "
        "Style priority is HIGH — the output must be a caricature, not a photo."
    )


def main():
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print("ROUND 3: JSON Prompt Method")
    print("=" * 60)

    # Load images
    id_b64, id_mime = load_image_b64(IDENTITY_IMAGE)
    style_b64, style_mime = load_image_b64(STYLE_IMAGE_FERNANDO)
    flux_b64, flux_mime = load_image_b64(STYLE_IMAGE_FLUX)

    style_part = {"inlineData": {"mimeType": style_mime, "data": style_b64}}
    flux_part = {"inlineData": {"mimeType": flux_mime, "data": flux_b64}}
    id_part = {"inlineData": {"mimeType": id_mime, "data": id_b64}}

    # All versions use: style_fernando, style_flux, identity_george (same as v6)
    tests = [
        ("v8", json_prompt_v8(), "Full JSON schema with state routing"),
        ("v9", json_prompt_v9(), "Compact JSON with copy_exactly lists"),
        ("v10", json_prompt_v10(), "Hybrid: JSON header + natural language"),
        ("v11", json_prompt_v11(), "Minimal JSON — routing + constraints only"),
    ]

    for version, prompt, desc in tests:
        print(f"\n--- {version}: {desc} ---")
        print(f"  Prompt length: {len(prompt)} chars")

        result = call_gemini(
            api_key,
            [style_part, flux_part, id_part, {"text": prompt}],
            version,
        )

        if result:
            save(result, f"george_nanobana_{version}.png")
        else:
            print(f"  FAILED")

    print("\n" + "=" * 60)
    print("DONE — Check test-output/george_nanobana_v8-v11.png")
    print("=" * 60)


if __name__ == "__main__":
    main()
