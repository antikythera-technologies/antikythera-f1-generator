"""Personality file loading utilities.

Shared by the character API and the video pipeline to resolve
personality JSON files and extract image-generation traits.
"""

import json
from pathlib import Path

# Root of the character-system personality files.
# In Docker: mounted at /character-system/personalities/
# In dev: relative to repo root at <repo>/character-system/personalities/
PERSONALITY_DIR_DOCKER = Path("/character-system/personalities")
PERSONALITY_DIR_DEV = Path(__file__).resolve().parents[3] / "character-system" / "personalities"
PERSONALITY_DIR = PERSONALITY_DIR_DOCKER if PERSONALITY_DIR_DOCKER.is_dir() else PERSONALITY_DIR_DEV


def find_personality_file(character_name: str) -> Path | None:
    """Locate the personality JSON file for a character by name.

    Searches drivers/ and principals/ subdirectories using the
    character's DB ``name`` field (e.g. ``george_russell``).

    Returns the Path if found, otherwise None.
    """
    slug = character_name.lower().replace(" ", "_")
    for subdir in ("drivers", "principals", "pundits"):
        candidate = PERSONALITY_DIR / subdir / f"{slug}.json"
        if candidate.exists():
            return candidate
    return None


def load_personality_traits_from_db(personality_json: str, role_hint: str | None = None) -> dict:
    """Load personality traits from a DB JSON string.

    Same extraction logic as load_personality_traits but reads from
    the database personality column instead of a file on disk.

    Args:
        personality_json: JSON string from characters.personality column.
        role_hint: Optional role hint (e.g., "driver", "team principal").
    """
    data = json.loads(personality_json)
    return _extract_traits(data, role_hint)


def load_personality_traits(personality_path: Path) -> dict:
    """Load a personality JSON file and extract image-generation traits.

    DEPRECATED: Use load_personality_traits_from_db() for new code.
    Kept for backward compatibility with scripts that reference files.

    Maps the rich personality JSON structure to the flat dict expected by
    ``ImageGenerator.build_character_prompt()``.

    Returns a dict with keys matching the prompt builder parameters.
    If any field is missing from the JSON, it is simply omitted.
    """
    with open(personality_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    parent_dir = personality_path.parent.name
    role_map = {
        "drivers": "driver",
        "principals": "team principal",
    }
    return _extract_traits(data, role_map.get(parent_dir))


def _extract_traits(data: dict, role_hint: str | None = None) -> dict:
    """Shared trait extraction logic used by both file and DB loaders."""
    traits: dict = {}

    # --- identity ---
    traits["display_name"] = data.get("name", "")
    traits["team"] = data.get("team")
    traits["nationality"] = data.get("nationality")
    traits["role"] = role_hint

    # --- visual profile ---
    visual = data.get("visual_profile", {})
    physical = visual.get("physical", {})

    # Build a descriptive physical_features string from the sub-fields
    phys_parts = []
    if physical.get("height"):
        phys_parts.append(physical["height"])
    if physical.get("build"):
        phys_parts.append(f"{physical['build']} build")
    if physical.get("hair"):
        phys_parts.append(f"hair: {physical['hair']}")
    for feat in physical.get("distinguishing_features", []):
        phys_parts.append(feat)
    if phys_parts:
        traits["physical_features"] = ", ".join(phys_parts)

    # --- comedy / satirical ---
    comedy_parts = []
    if data.get("comedy_archetype"):
        comedy_parts.append(data["comedy_archetype"].replace("_", " "))
    if data.get("satirical_angle"):
        comedy_parts.append(data["satirical_angle"])
    anim = visual.get("animation_notes", {})
    if anim.get("comedy_exaggeration"):
        comedy_parts.append(anim["comedy_exaggeration"])
    if comedy_parts:
        traits["comedy_angle"] = ". ".join(comedy_parts)

    # --- expression ---
    if anim.get("expression_default"):
        traits["signature_expression"] = anim["expression_default"]

    # --- pose (from signature_gestures) ---
    gestures = visual.get("signature_gestures", [])
    if gestures:
        traits["signature_pose"] = ", ".join(gestures)

    # --- clothing (from physical or animation notes) ---
    clothing_parts = []
    # Some profiles mention clothing in distinguishing features
    for feat in physical.get("distinguishing_features", []):
        if any(kw in feat.lower() for kw in ("suit", "polo", "outfit", "wear", "dress", "uniform", "couture")):
            clothing_parts.append(feat)
    if anim.get("posture"):
        # Posture informs how clothing sits
        clothing_parts.append(f"posture: {anim['posture']}")
    if clothing_parts:
        traits["clothing_description"] = "; ".join(clothing_parts)

    return traits
