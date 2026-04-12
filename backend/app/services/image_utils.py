"""Image utility functions for the F1 video pipeline."""

import logging

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

TARGET_W = 1280
TARGET_H = 720


def portrait_to_landscape(img: Image.Image) -> Image.Image:
    """Convert a portrait instant-character image (720x1280) to landscape (1280x720).

    Uses blur-pad (letterbox): the portrait is resized to fit the target height,
    centered horizontally on a 1280x720 canvas, and the side margins are filled
    with a heavily blurred+stretched version of the source image.  This preserves
    the full character (head, suit, hands) while producing a broadcast-style
    composition with the subject centred and contextual background on the sides.

    Args:
        img: PIL Image, expected 720x1280 from instant-character (portrait).

    Returns:
        PIL Image at 1280x720 (landscape).
    """
    if img.width == TARGET_W and img.height == TARGET_H:
        return img

    # Step 1: Fit source to target height, preserving aspect ratio
    fit_scale = TARGET_H / img.height
    fit_w = int(img.width * fit_scale)
    fit_h = TARGET_H
    fitted = img.resize((fit_w, fit_h), Image.LANCZOS)

    # Step 2: Build blurred background from a stretched version of the source
    bg = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))

    # Step 3: Paste fitted image centred on the blurred background
    pad_x = (TARGET_W - fit_w) // 2
    bg.paste(fitted, (pad_x, 0))

    logger.info(
        f"Portrait to landscape: {img.width}x{img.height} -> {TARGET_W}x{TARGET_H} "
        f"(fitted={fit_w}x{fit_h}, pad_x={pad_x})"
    )
    return bg
