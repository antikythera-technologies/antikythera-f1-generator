"""FLF (First-Last Frame) routing decisions.

Pure function that decides which scenes should have end frames generated
for first-last-frame video generation. Zero external dependencies.
"""

# Scene types eligible for FLF (character-focused, benefit from smooth transitions)
FLF_ELIGIBLE = {
    "REACTION",
    "ACTION_REPLAY",
}

# Scene types that should NEVER get FLF (non-character, establishing shots)
FLF_INELIGIBLE = {
    "TITLE_CARD",
    "ESTABLISHING",
}


def should_generate_end_frame(
    scene_type: str | None,
    scene_index: int,
    total_scenes: int,
    backend_supports_flf: bool,
) -> bool:
    """Decide if a scene should have an end frame generated.

    Args:
        scene_type: LLM-generated scene type (TALKING_HEAD, ACTION_REPLAY, etc.)
        scene_index: Zero-based index of the scene in the episode
        total_scenes: Total number of scenes in the episode
        backend_supports_flf: Whether the video backend supports FLF

    Returns:
        True if an end frame should be generated for this scene
    """
    if not backend_supports_flf:
        return False

    if not scene_type:
        return False

    scene_type_upper = scene_type.upper().strip()

    if scene_type_upper in FLF_INELIGIBLE:
        return False

    if scene_type_upper not in FLF_ELIGIBLE:
        return False

    # Last scene never needs FLF — no next scene to transition to
    if scene_index >= total_scenes - 1:
        return False

    return True
