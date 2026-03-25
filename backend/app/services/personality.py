"""Personality trait extraction from database.

All personality data lives in the characters.personality column (JSONB).
No JSON files on disk — the database is the single source of truth.
"""

import json


def load_personality_traits_from_db(personality_json: str, role_hint: str | None = None) -> dict:
    """Load personality traits from the database personality column.

    Args:
        personality_json: JSON string from characters.personality column.
        role_hint: Optional role hint (e.g., "driver", "team principal").

    Returns:
        Dict with extracted traits for prompt building.
    """
    data = json.loads(personality_json) if isinstance(personality_json, str) else personality_json
    return _extract_traits(data, role_hint)


def _extract_traits(data: dict, role_hint: str | None = None) -> dict:
    """Extract prompt-relevant traits from a personality JSON blob."""
    traits: dict = {}

    # --- identity ---
    traits["display_name"] = data.get("name", "")
    traits["team"] = data.get("team")
    traits["nationality"] = data.get("nationality")
    traits["role"] = role_hint

    # --- speaking style ---
    speaking = data.get("speaking_style", {})
    if speaking:
        traits["speaking_style"] = speaking

    # --- catchphrases ---
    if data.get("catchphrases"):
        traits["catchphrases"] = data["catchphrases"]

    # --- core personality traits ---
    if data.get("core_traits"):
        traits["core_traits"] = data["core_traits"]

    # --- comedy weaknesses ---
    if data.get("comedy_weaknesses"):
        traits["comedy_weaknesses"] = data["comedy_weaknesses"]

    # --- visual profile ---
    visual = data.get("visual_profile", {})
    physical = visual.get("physical", {})

    # Build a descriptive physical_features string
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

    # --- clothing ---
    clothing_parts = []
    for feat in physical.get("distinguishing_features", []):
        if any(kw in feat.lower() for kw in ("suit", "polo", "outfit", "wear", "dress", "uniform", "couture")):
            clothing_parts.append(feat)
    if anim.get("posture"):
        clothing_parts.append(f"posture: {anim['posture']}")
    if clothing_parts:
        traits["clothing_description"] = "; ".join(clothing_parts)

    return traits
