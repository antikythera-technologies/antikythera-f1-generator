#!/usr/bin/env python3
"""
Batch character caricature generator for the F1 satirical video system.

Generates ANTKF1STYLE caricatures for all characters using ComfyUI
(Flux Dev fp8 + LoRA + PuLID) on RunPod, then uploads to MinIO.

Usage:
    python scripts/generate_all_characters.py --phase faces
    python scripts/generate_all_characters.py --phase generate
    python scripts/generate_all_characters.py --phase upload
    python scripts/generate_all_characters.py --phase clean
    python scripts/generate_all_characters.py --phase all
    python scripts/generate_all_characters.py --phase generate --character max_verstappen
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERSONALITIES_DIR = PROJECT_ROOT / "character-system" / "personalities"
FACE_REF_DIR = PROJECT_ROOT / "face-references"
OUTPUT_DIR = PROJECT_ROOT / "generated-characters"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# ComfyUI
# ---------------------------------------------------------------------------
COMFYUI_BASE = "https://tims42v3eaqrz7-19123.proxy.runpod.net"
COMFYUI_UPLOAD = f"{COMFYUI_BASE}/upload/image"
COMFYUI_PROMPT = f"{COMFYUI_BASE}/prompt"
COMFYUI_HISTORY = f"{COMFYUI_BASE}/history"
COMFYUI_VIEW = f"{COMFYUI_BASE}/view"

# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------
MC_ALIAS = "antikythera"
MINIO_BUCKET = "f1-characters"

# ---------------------------------------------------------------------------
# Team visual config (2026 season)
# ---------------------------------------------------------------------------
TEAM_COLORS: dict[str, dict[str, str]] = {
    "red_bull_racing": {
        "suit": "dark blue Red Bull Racing suit with Oracle and Bybit logos",
        "background": "dark navy blue to midnight blue gradient",
    },
    "racing_bulls": {
        "suit": "white Racing Bulls suit with blue and Ford accents",
        "background": "white to steel blue gradient",
    },
    "mclaren": {
        "suit": "papaya orange and black McLaren suit with OKX logos",
        "background": "papaya orange to black gradient",
    },
    "ferrari": {
        "suit": "red Ferrari suit with white accents and HP logos",
        "background": "deep red to dark crimson gradient",
    },
    "mercedes": {
        "suit": "black Mercedes-AMG Petronas suit with Petronas teal accents",
        "background": "dark teal to black gradient",
    },
    "aston_martin": {
        "suit": "British racing green Aston Martin suit",
        "background": "dark British racing green gradient",
    },
    "williams": {
        "suit": "blue Williams Racing suit with Barclays lighter blue accents",
        "background": "dark blue to navy gradient",
    },
    "haas": {
        "suit": "black and white TGR Haas suit with Toyota red accents",
        "background": "black to dark grey gradient with red accent",
    },
    "alpine": {
        "suit": "blue Alpine suit with BWT pink accents",
        "background": "dark blue to pink gradient",
    },
    "audi": {
        "suit": "silver and black Audi suit with red accents",
        "background": "silver to black gradient",
    },
    "cadillac": {
        "suit": "white and black Cadillac suit with chrome details",
        "background": "black to dark grey gradient with chrome highlights",
    },
}

PUNDIT_VISUAL = {
    "suit": "smart dark blazer with Sky Sports microphone",
    "background": "warm burnt-orange to dark amber gradient",
}

# For Stefano Domenicali (F1 CEO) — no team, not a pundit
CEO_VISUAL = {
    "suit": "impeccable dark Italian suit with F1 logo pin",
    "background": "warm burnt-orange to dark amber gradient",
}


# ===================================================================
# Character discovery
# ===================================================================

def discover_characters() -> list[dict]:
    """Scan personality JSONs and return a sorted list of character dicts."""
    characters: list[dict] = []
    for category in ("drivers", "principals", "pundits"):
        cat_dir = PERSONALITIES_DIR / category
        if not cat_dir.is_dir():
            continue
        for fp in sorted(cat_dir.glob("*.json")):
            with open(fp) as f:
                data = json.load(f)
            data["_category"] = category
            data["_json_path"] = str(fp)
            characters.append(data)
    characters.sort(key=lambda c: c["id"])
    return characters


# ===================================================================
# Prompt builder
# ===================================================================

def build_prompt(char: dict) -> str:
    """Build the ANTKF1STYLE prompt from personality data."""
    category = char["_category"]
    team = char.get("team")

    # --- Determine suit and background ---
    if category == "pundits":
        visual = PUNDIT_VISUAL
        # Stefano Domenicali is the F1 CEO, not a Sky Sports pundit
        if char["id"] == "stefano_domenicali":
            visual = CEO_VISUAL
    elif category == "principals":
        team_data = TEAM_COLORS.get(team, {})
        bg = team_data.get("background", "dark gradient")
        # Principals wear polo shirts, not race suits
        team_label = team.replace("_", " ").title() if team else "team"
        suit = f"{team_label} team polo shirt"
        visual = {"suit": suit, "background": bg}
    else:
        # Drivers
        visual = TEAM_COLORS.get(team, {"suit": "racing suit", "background": "dark gradient"})

    # --- Physical description from visual_profile ---
    vp = char.get("visual_profile", {})
    physical = vp.get("physical", {})
    hair_raw = physical.get("hair", "")
    features = physical.get("distinguishing_features", [])

    # Strip overly long prose from hair descriptions — keep just the visual part
    # e.g. "bald, gleaming — the aerodynamic dome..." -> "bald, gleaming"
    hair = hair_raw.split("—")[0].split(" - ")[0].strip().rstrip(",")
    # Further trim if still too wordy (>50 chars)
    if len(hair) > 50:
        parts = [p.strip() for p in hair.split(",")[:2]]
        hair = ", ".join(parts).rstrip(",")

    # Build concise description string
    nationality = char.get("nationality", "")
    if category == "drivers":
        role_label = "Formula 1 driver"
    elif category == "principals":
        role_label = "Formula 1 team principal"
    else:
        role = char.get("role", "pundit").replace("_", " ")
        role_label = f"Formula 1 {role}"

    # Clean up features: take up to 2, strip prose
    clean_features = []
    for feat in features[:2]:
        # Trim long descriptive features to the core visual cue
        short = feat.split("—")[0].split(" - ")[0].strip().rstrip(",")
        if len(short) <= 60:
            clean_features.append(short)

    desc = f"{nationality} {role_label}" if nationality else role_label
    if hair:
        desc += f", {hair}"
    if clean_features:
        desc += f", {', '.join(clean_features)}"

    description = desc

    # --- Expression from personality ---
    anim = vp.get("animation_notes", {})
    expression = anim.get("expression_default", "")
    if not expression:
        # Fallback: derive from comedy_archetype or satirical_angle
        expression = char.get("satirical_angle", "expressive face")
    # Strip prose after dashes and trim to keep it concise for the prompt
    expression = expression.split("—")[0].split(" - ")[0].strip().rstrip(",")
    if len(expression) > 80:
        expression = expression[:80].rsplit(" ", 1)[0]

    prompt = (
        f"A ANTKF1STYLE satirical caricature portrait of a {description}, "
        f"wearing {visual['suit']}. "
        f"{expression}. "
        f"Oversized head with exaggerated facial features, "
        f"hyper-detailed photorealistic skin with visible pores and texture, "
        f"{visual['background']} background, "
        f"dramatic warm side lighting with deep shadows. "
        f"Head and shoulders portrait, cinematic satirical artwork."
    )
    return prompt


def character_seed(name: str) -> int:
    """Deterministic seed from character name."""
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % (2**32)


# ===================================================================
# ComfyUI workflow builder
# ===================================================================

def build_workflow(char: dict, face_filename: str) -> dict:
    """Build the ComfyUI API workflow JSON for one character."""
    prompt_text = build_prompt(char)
    seed = character_seed(char["id"])

    workflow = {
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
                "strength_model": 1.4,
                "strength_clip": 1.4,
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
        "20": {
            "class_type": "PulidFluxModelLoader",
            "inputs": {
                "pulid_file": "pulid_flux_v0.9.0.safetensors",
            },
        },
        "21": {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {
                "provider": "CUDA",
            },
        },
        "22": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        },
        "23": {
            "class_type": "LoadImage",
            "inputs": {
                "image": face_filename,
            },
        },
        "25": {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "weight": 0.7,
                "start_at": 0.0,
                "end_at": 1.0,
                "model": ["10", 0],
                "pulid_flux": ["20", 0],
                "eva_clip": ["22", 0],
                "face_analysis": ["21", 0],
                "image": ["23", 0],
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
                "width": 768,
                "height": 1344,
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
                "filename_prefix": char["id"],
                "images": ["8", 0],
            },
        },
    }
    return workflow


# ===================================================================
# Phase 1: Face reference audit
# ===================================================================

FACE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def find_face_photo(char_id: str) -> Path | None:
    """Return path to face reference photo if it exists."""
    for ext in FACE_EXTENSIONS:
        candidate = FACE_REF_DIR / f"{char_id}{ext}"
        if candidate.is_file():
            return candidate
    return None


def phase_faces(characters: list[dict], *, report_only: bool = False) -> dict[str, Path]:
    """Check for face references. Return dict of char_id -> face_path."""
    FACE_REF_DIR.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    missing: list[str] = []

    for char in characters:
        cid = char["id"]
        face = find_face_photo(cid)
        if face:
            found[cid] = face
        else:
            missing.append(cid)

    # Report
    print(f"\n{'=' * 60}")
    print(f"FACE REFERENCE AUDIT — {len(found)} found, {len(missing)} missing")
    print(f"{'=' * 60}")

    if found:
        print(f"\nFOUND ({len(found)}):")
        for cid, path in sorted(found.items()):
            print(f"  OK   {cid} -> {path.name}")

    if missing:
        print(f"\nMISSING ({len(missing)}):")
        for cid in sorted(missing):
            name = next((c["name"] for c in characters if c["id"] == cid), cid)
            print(f"  MISSING: {name} — please add face photo to face-references/{cid}.jpg")

    if not missing:
        print("\nAll face references present.")

    print()
    return found


# ===================================================================
# Phase 2: Generate caricatures via ComfyUI
# ===================================================================

def upload_face_to_comfyui(client: httpx.Client, face_path: Path) -> str:
    """Upload a face photo to ComfyUI's input directory. Returns the filename."""
    filename = face_path.name
    with open(face_path, "rb") as f:
        files = {"image": (filename, f, "image/png")}
        data = {"overwrite": "true"}
        resp = client.post(COMFYUI_UPLOAD, files=files, data=data, timeout=60)
        resp.raise_for_status()
    result = resp.json()
    # ComfyUI returns {"name": "filename.jpg", "subfolder": "", "type": "input"}
    return result.get("name", filename)


def queue_prompt(client: httpx.Client, workflow: dict) -> str:
    """Queue a ComfyUI prompt and return the prompt_id."""
    payload = {"prompt": workflow}
    resp = client.post(COMFYUI_PROMPT, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"No prompt_id in response: {data}")
    return prompt_id


def wait_for_completion(
    client: httpx.Client, prompt_id: str, *, timeout: int = 300, poll: float = 3.0
) -> dict:
    """Poll ComfyUI history until the prompt completes. Returns the output dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"{COMFYUI_HISTORY}/{prompt_id}", timeout=30)
        resp.raise_for_status()
        history = resp.json()
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("completed", False) or status.get("status_str") == "success":
                return entry
            # Check for errors
            if status.get("status_str") == "error":
                msgs = entry.get("status", {}).get("messages", [])
                raise RuntimeError(f"ComfyUI generation failed: {msgs}")
        time.sleep(poll)
    raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")


def download_result(client: httpx.Client, history_entry: dict, char_id: str) -> Path:
    """Download the generated image from ComfyUI and save locally."""
    outputs = history_entry.get("outputs", {})
    # Node 9 is SaveImage
    node_output = outputs.get("9", {})
    images = node_output.get("images", [])
    if not images:
        raise RuntimeError(f"No output images found for {char_id}: {outputs}")

    img_info = images[0]
    filename = img_info["filename"]
    subfolder = img_info.get("subfolder", "")
    img_type = img_info.get("type", "output")

    params = {"filename": filename, "subfolder": subfolder, "type": img_type}
    resp = client.get(COMFYUI_VIEW, params=params, timeout=120)
    resp.raise_for_status()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{char_id}.png"
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path


def phase_generate(
    characters: list[dict], faces: dict[str, Path], *, single: str | None = None
) -> dict[str, str]:
    """Generate caricatures for all characters with face photos."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    to_process = [c for c in characters if c["id"] in faces]
    if single:
        to_process = [c for c in to_process if c["id"] == single]
        if not to_process:
            if single not in faces:
                print(f"ERROR: No face reference for '{single}'. Add it to face-references/")
            else:
                print(f"ERROR: Character '{single}' not found in personality JSONs.")
            return {}

    total = len(to_process)
    results: dict[str, str] = {}
    errors: list[str] = []

    print(f"\n{'=' * 60}")
    print(f"GENERATING {total} CARICATURES via ComfyUI")
    print(f"{'=' * 60}\n")

    with httpx.Client(timeout=30) as client:
        # Quick connectivity check
        try:
            resp = client.get(f"{COMFYUI_BASE}/system_stats", timeout=10)
            resp.raise_for_status()
            print(f"ComfyUI connected: {COMFYUI_BASE}\n")
        except Exception as e:
            print(f"ERROR: Cannot reach ComfyUI at {COMFYUI_BASE}: {e}")
            print("Is the RunPod pod running? Check https://www.runpod.io/console/pods")
            return {}

        for idx, char in enumerate(to_process, 1):
            cid = char["id"]
            name = char.get("name", cid)
            face_path = faces[cid]
            t0 = time.time()

            print(f"[{idx}/{total}] Generating {cid}...", end=" ", flush=True)

            try:
                # 1. Upload face photo
                face_filename = upload_face_to_comfyui(client, face_path)

                # 2. Build workflow
                workflow = build_workflow(char, face_filename)

                # 3. Log prompt for debugging
                prompt_text = build_prompt(char)
                print(f"\n         Prompt: {prompt_text[:100]}...")

                # 4. Queue
                prompt_id = queue_prompt(client, workflow)
                print(f"         Queued: {prompt_id}")

                # 5. Wait
                history_entry = wait_for_completion(client, prompt_id, timeout=300)

                # 6. Download
                out_path = download_result(client, history_entry, cid)
                elapsed = time.time() - t0
                print(f"         done ({elapsed:.0f}s) -> {out_path.name}")

                results[cid] = str(out_path)

            except Exception as e:
                elapsed = time.time() - t0
                print(f"FAILED ({elapsed:.0f}s): {e}")
                errors.append(f"{cid}: {e}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"GENERATION COMPLETE: {len(results)}/{total} succeeded, {len(errors)} failed")
    if errors:
        print("\nFailed:")
        for err in errors:
            print(f"  {err}")
    print()

    # Save manifest
    _save_manifest(characters, faces, results)

    return results


# ===================================================================
# Phase 3: Upload to MinIO
# ===================================================================

def mc_run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run an mc CLI command."""
    cmd = ["mc"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        raise RuntimeError(f"mc command failed: {' '.join(cmd)}\n{result.stderr}")
    return result


def phase_upload(characters: list[dict], faces: dict[str, Path]) -> None:
    """Upload generated caricatures and face references to MinIO."""
    print(f"\n{'=' * 60}")
    print("UPLOADING TO MINIO")
    print(f"{'=' * 60}\n")

    uploaded = 0
    errors: list[str] = []

    for char in characters:
        cid = char["id"]

        # Upload caricature if it exists
        caricature_path = OUTPUT_DIR / f"{cid}.png"
        if caricature_path.is_file():
            dest = f"{MC_ALIAS}/{MINIO_BUCKET}/{cid}/caricature.png"
            try:
                mc_run(["cp", str(caricature_path), dest])
                print(f"  Uploaded caricature: {cid}/caricature.png")
                uploaded += 1
            except Exception as e:
                errors.append(f"caricature {cid}: {e}")
                print(f"  FAILED caricature {cid}: {e}")

        # Upload face reference if it exists
        if cid in faces:
            face_path = faces[cid]
            dest = f"{MC_ALIAS}/{MINIO_BUCKET}/face-references/{cid}{face_path.suffix}"
            try:
                mc_run(["cp", str(face_path), dest])
                print(f"  Uploaded face ref:   face-references/{cid}{face_path.suffix}")
                uploaded += 1
            except Exception as e:
                errors.append(f"face-ref {cid}: {e}")
                print(f"  FAILED face ref {cid}: {e}")

    print(f"\nUploaded {uploaded} files, {len(errors)} errors.")
    if errors:
        for err in errors:
            print(f"  {err}")
    print()


# ===================================================================
# Phase 4: Clean old MinIO objects
# ===================================================================

def phase_clean(characters: list[dict]) -> None:
    """Remove old objects from f1-characters bucket, keeping LoRA and new files."""
    print(f"\n{'=' * 60}")
    print("CLEANING MINIO BUCKET")
    print(f"{'=' * 60}\n")

    # Build set of paths we want to keep
    keep_prefixes = {"lora/"}
    keep_paths: set[str] = set()

    for char in characters:
        cid = char["id"]
        # Caricature
        keep_paths.add(f"{cid}/caricature.png")
        # Face references (any extension)
        for ext in FACE_EXTENSIONS:
            keep_paths.add(f"face-references/{cid}{ext}")

    # List all objects in the bucket
    result = mc_run(["ls", "--recursive", f"{MC_ALIAS}/{MINIO_BUCKET}/"], check=False)
    if result.returncode != 0:
        print(f"Could not list bucket: {result.stderr}")
        return

    lines = result.stdout.strip().split("\n")
    to_delete: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # mc ls output: "[2024-01-01 12:00:00 UTC]  1234B STANDARD path/to/file"
        # The path is the last space-delimited token
        parts = line.split()
        if len(parts) < 5:
            continue
        obj_path = parts[-1]

        # Keep lora/ prefix
        if any(obj_path.startswith(p) for p in keep_prefixes):
            continue
        # Keep known good paths
        if obj_path in keep_paths:
            continue
        to_delete.append(obj_path)

    if not to_delete:
        print("Nothing to clean — all objects are current.")
        return

    print(f"Found {len(to_delete)} objects to delete:\n")
    for obj in to_delete:
        print(f"  DELETE: {obj}")

    print()
    confirm = input("Proceed with deletion? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    deleted = 0
    for obj in to_delete:
        full_path = f"{MC_ALIAS}/{MINIO_BUCKET}/{obj}"
        try:
            mc_run(["rm", full_path])
            deleted += 1
        except Exception as e:
            print(f"  Failed to delete {obj}: {e}")

    print(f"\nDeleted {deleted}/{len(to_delete)} objects.")


# ===================================================================
# Manifest
# ===================================================================

def _save_manifest(
    characters: list[dict], faces: dict[str, Path], results: dict[str, str]
) -> None:
    """Save a manifest JSON with generation results."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for char in characters:
        cid = char["id"]
        entry = {
            "id": cid,
            "name": char.get("name", cid),
            "category": char["_category"],
            "team": char.get("team"),
            "face_reference": str(faces[cid]) if cid in faces else None,
            "generated": cid in results,
            "output_path": results.get(cid),
            "minio_caricature": f"{MINIO_BUCKET}/{cid}/caricature.png" if cid in results else None,
            "minio_face_ref": (
                f"{MINIO_BUCKET}/face-references/{cid}{faces[cid].suffix}"
                if cid in faces
                else None
            ),
            "prompt": build_prompt(char) if cid in faces else None,
            "seed": character_seed(cid),
        }
        entries.append(entry)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_characters": len(characters),
        "total_generated": len(results),
        "total_faces": len(faces),
        "characters": entries,
    }

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest saved: {MANIFEST_PATH}")


# ===================================================================
# CLI
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch generate F1 character caricatures via ComfyUI + LoRA + PuLID"
    )
    parser.add_argument(
        "--phase",
        choices=["faces", "generate", "upload", "clean", "all"],
        required=True,
        help="Which phase to run",
    )
    parser.add_argument(
        "--character",
        type=str,
        default=None,
        help="Process a single character by ID (e.g. max_verstappen)",
    )
    parser.add_argument(
        "--faces-only",
        action="store_true",
        help="Alias for --phase faces (just report missing face photos)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompts (for clean phase)",
    )

    args = parser.parse_args()

    # --faces-only overrides --phase
    if args.faces_only:
        args.phase = "faces"

    # Discover all characters
    characters = discover_characters()
    if args.character:
        matching = [c for c in characters if c["id"] == args.character]
        if not matching:
            valid = [c["id"] for c in characters]
            print(f"ERROR: Character '{args.character}' not found.")
            print(f"Valid IDs: {', '.join(sorted(valid))}")
            sys.exit(1)

    total_chars = len(characters)
    drivers = sum(1 for c in characters if c["_category"] == "drivers")
    principals = sum(1 for c in characters if c["_category"] == "principals")
    pundits = sum(1 for c in characters if c["_category"] == "pundits")
    print(f"Discovered {total_chars} characters: {drivers} drivers, {principals} principals, {pundits} pundits")

    # Always run face audit first
    faces = phase_faces(characters, report_only=(args.phase == "faces"))

    if args.phase == "faces":
        return

    if args.phase in ("generate", "all"):
        phase_generate(characters, faces, single=args.character)

    if args.phase in ("upload", "all"):
        phase_upload(characters, faces)

    if args.phase in ("clean", "all"):
        # Monkey-patch input for --yes
        if args.yes:
            import builtins
            _original_input = builtins.input
            builtins.input = lambda _: "y"
            try:
                phase_clean(characters)
            finally:
                builtins.input = _original_input
        else:
            phase_clean(characters)


if __name__ == "__main__":
    main()
