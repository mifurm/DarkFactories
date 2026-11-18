"""Colour science for brand-palette checks: sRGB <-> CIELAB, delta-E (CIE76 + CIE94), dominant colours."""

from __future__ import annotations

import io
import math
from typing import Any, cast

import numpy as np
from PIL import Image

Lab = tuple[float, float, float]
NEUTRALS = ["#000000", "#FFFFFF", "#808080", "#F5F5F5", "#222222"]


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int] | np.ndarray) -> str:
    r, g, b = (round(float(x)) for x in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb: tuple[int, int, int] | np.ndarray) -> Lab:
    r, g, b = (_lin(float(x)) for x in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(a: Lab, b: Lab) -> float:
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b, strict=True)))


def delta_e94(a: Lab, b: Lab) -> float:
    """CIE94 (graphic arts) — less over-sensitive to chroma than CIE76; used for the palette distance."""
    l1, a1, b1 = a
    l2, a2, b2 = b
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    dl, dc = l1 - l2, c1 - c2
    da, db = a1 - a2, b1 - b2
    dh2 = max(0.0, da * da + db * db - dc * dc)
    sc, sh = 1 + 0.045 * c1, 1 + 0.015 * c1
    return math.sqrt(dl**2 + (dc / sc) ** 2 + dh2 / (sh**2))


def nearest_palette(hex_color: str, palette: list[str], allow_neutrals: bool = True) -> tuple[str, float]:
    lab = rgb_to_lab(hex_to_rgb(hex_color))
    best, best_d = palette[0], 1e9
    for p in palette + (NEUTRALS if allow_neutrals else []):
        d = delta_e94(lab, rgb_to_lab(hex_to_rgb(p)))
        if d < best_d:
            best, best_d = p, d
    return best, round(best_d, 2)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_lin(float(x)) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = relative_luminance(hex_to_rgb(fg)), relative_luminance(hex_to_rgb(bg))
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def dominant_colors(image_bytes: bytes, k: int = 6) -> list[dict[str, Any]]:
    """Median-cut quantisation of a downscaled copy -> [{hex, share}] sorted by coverage."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((160, 160))
    q = img.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(cast(list[tuple[int, int]], q.getcolors() or []), reverse=True)
    total = sum(c for c, _ in counts) or 1
    return [{"hex": rgb_to_hex((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2])), "share": round(c / total, 4)} for c, i in counts]


def tonal_anchors(palette: list[str]) -> list[Lab]:
    """Brand colours plus their tints/shades (lightness steps, softer chroma) and neutral greys: what a real photo in
    the brand's colour world looks like (browns, tans, creams, deep shadows, muted greens...)."""
    anchors: list[Lab] = []
    for hx in palette:
        _l0, a0, b0 = rgb_to_lab(hex_to_rgb(hx))
        for lightness in (12, 24, 38, 52, 66, 80, 92):
            for ch in (0.35, 0.7, 1.0):
                anchors.append((float(lightness), a0 * ch, b0 * ch))
    for lightness in range(6, 100, 12):
        anchors.append((float(lightness), 0.0, 0.0))
    return anchors


def palette_distance(colors: list[dict[str, Any]], palette: list[str]) -> float:
    """Coverage-weighted mean CIE76 distance from each dominant colour to the brand's tonal range (0 = squarely on-brand)."""
    if not colors:
        return 0.0
    anchors = np.array(tonal_anchors(palette), dtype=np.float64)
    total = sum(c["share"] for c in colors) or 1.0
    acc = 0.0
    for c in colors:
        lab = np.array(rgb_to_lab(hex_to_rgb(c["hex"])))
        acc += c["share"] * float(np.min(np.linalg.norm(anchors - lab, axis=1)))
    return round(acc / total, 2)
