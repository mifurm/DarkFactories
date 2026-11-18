"""Input image handling: safe decode, centre-crop to the target aspect, LANCZOS resize."""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps

from .errors import BadRequest

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


def decode_image(data: bytes) -> Image.Image:
    """Decode JPEG/PNG/WEBP bytes to an RGB image (EXIF orientation applied, alpha flattened onto white)."""
    if not data:
        raise BadRequest("image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise BadRequest(f"image is too large ({len(data)} bytes > {MAX_IMAGE_BYTES})")
    try:
        img: Any = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise BadRequest(f"unsupported image format {img.format!r} (use JPEG, PNG or WEBP)")
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise BadRequest(f"image has too many pixels ({img.width}x{img.height})")
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return img.convert("RGB")
    except BadRequest:
        raise
    except Exception as exc:  # PIL raises OSError/ValueError/SyntaxError/DecompressionBombError/... on bad input
        raise BadRequest(f"image could not be decoded: {type(exc).__name__}") from exc


def fit_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Centre-crop to the width:height aspect, then resize to exactly width x height with LANCZOS."""
    src_w, src_h = img.size
    if src_w * height > src_h * width:  # source is wider than the target: trim left/right
        new_w = max(1, min(src_w, round(src_h * width / height)))
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:  # source is taller (or equal): trim top/bottom
        new_h = max(1, min(src_h, round(src_w * height / width)))
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return img.crop(box).resize((width, height), Image.Resampling.LANCZOS)
