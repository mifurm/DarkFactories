"""Graphics for the compositor: fonts, logo, captions, supers, end card, badges (Pillow; no ffmpeg text filters needed)."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .spec import SAFE_AREAS, RenderSpec

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    v = hex_color.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont:
    name = ("DejaVuSerif" if serif else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(str(FONT_DIR / name), max(8, int(size)))


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def spaced_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fnt: ImageFont.FreeTypeFont, fill: Any, spacing: float) -> float:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += fnt.getlength(ch) + spacing
    return x - xy[0]


def spaced_width(text: str, fnt: ImageFont.FreeTypeFont, spacing: float) -> float:
    return sum(fnt.getlength(c) + spacing for c in text) - spacing


def to_np(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.uint8)


# ----------------------------------------------------------------------------------------------- logo


def draw_logo(width: int, wordmark: str = "NORTHWIND", sub: str = "COFFEE ROASTERS", mark: str = "#F2A03D", ink: str = "#F6EBDD") -> Image.Image:
    """Amber sun mark above a letter-spaced wordmark. Returns RGBA image of size (width, round(width*0.62))."""
    s = 3
    w, h = width * s, int(width * 0.62) * s
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy, r = w / 2, h * 0.27, w * 0.115
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*_rgb(mark), 255))
    for k in range(9):
        a = math.pi + k * math.pi / 8
        x0, y0 = cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35
        x1, y1 = cx + math.cos(a) * r * 1.85, cy + math.sin(a) * r * 1.85
        d.line([(x0, y0), (x1, y1)], fill=(*_rgb(mark), 255), width=max(2, int(w * 0.009)))
    d.rectangle([cx - r * 2.0, cy, cx + r * 2.0, cy + r * 0.12], fill=(0, 0, 0, 0))
    wf = font(int(w * 0.105), bold=True)
    sp = w * 0.016
    ww = spaced_width(wordmark, wf, sp)
    spaced_text(d, ((w - ww) / 2, h * 0.52), wordmark, wf, (*_rgb(ink), 255), sp)
    sf = font(int(w * 0.042))
    sp2 = w * 0.012
    sw = spaced_width(sub, sf, sp2)
    spaced_text(d, ((w - sw) / 2, h * 0.76), sub, sf, (*_rgb(mark), 255), sp2)
    return img.resize((width, int(width * 0.62)), Image.LANCZOS)


# ----------------------------------------------------------------------------------------------- captions & supers


def render_caption(text: str, w: int, h: int, aspect: str) -> tuple[np.ndarray, int, int]:
    safe = SAFE_AREAS[aspect]
    size = int(min(w, h) * (0.058 if aspect in ("9:16", "4:5") else 0.05))
    f = font(size, bold=True)
    max_w = w * (1 - safe["left"] - safe["right"]) * 0.92
    lines = wrap(text, f, max_w - size)
    lh = int(size * 1.28)
    pad = int(size * 0.42)
    bw = int(max(f.getlength(ln) for ln in lines) + pad * 2)
    bh = lh * len(lines) + pad * 2 - int(size * 0.2)
    s = 2
    img = Image.new("RGBA", (bw * s, bh * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bw * s - 1, bh * s - 1], radius=int(size * 0.35) * s, fill=(21, 13, 9, 208))
    big = font(size * s, bold=True)
    for i, ln in enumerate(lines):
        lw = big.getlength(ln)
        d.text(((bw * s - lw) / 2, (pad + i * lh) * s - int(size * 0.05) * s), ln, font=big, fill=(247, 240, 230, 255))
    img = img.resize((bw, bh), Image.LANCZOS)
    x = int((w - bw) / 2)
    y = int(h * (1 - safe["bottom"]) - bh - h * 0.012)
    return to_np(img), x, y


def render_super(text: str, w: int, h: int, aspect: str, accent: str = "#F2A03D", fg: str = "#F6EBDD") -> tuple[np.ndarray, int, int]:
    """Large editorial headline over the picture (serif, soft shadow); anchored left inside the safe area."""
    safe = SAFE_AREAS[aspect]
    size = int(min(w, h) * (0.092 if aspect in ("9:16", "4:5") else 0.082))
    max_w = w * (1 - safe["left"] - safe["right"]) * 0.86
    while True:
        f = font(size, bold=True, serif=True)
        lines = wrap(text, f, max_w)
        if len(lines) <= 3 or size <= 18:
            break
        size = int(size * 0.92)
    lines = lines[:4]
    lh = int(size * 1.18)
    bw = int(max(f.getlength(ln) for ln in lines)) + 30
    bh = lh * len(lines) + 24
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    sd, d = ImageDraw.Draw(shadow), ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        sd.text((16, 10 + i * lh + 4), ln, font=f, fill=(15, 8, 5, 235))
        d.text((12, 8 + i * lh), ln, font=f, fill=(*_rgb(fg), 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    out = Image.alpha_composite(shadow, img)
    # amber underline accent
    od = ImageDraw.Draw(out)
    od.rectangle([14, bh - 8, 14 + int(bw * 0.16), bh - 4], fill=(*_rgb(accent), 255))
    x = int(w * safe["left"])
    y = int(h * 0.56 - bh / 2)
    if aspect in ("9:16", "4:5"):
        y = int(h * 0.50 - bh / 2)
    return to_np(out), x, y


def render_label(text: str, w: int, h: int, aspect: str, corner: str = "tl", small: bool = True) -> tuple[np.ndarray, int, int]:
    safe = SAFE_AREAS[aspect]
    size = int(min(w, h) * 0.030)
    f = font(size, bold=True)
    pad = int(size * 0.5)
    bw, bh = int(f.getlength(text) + pad * 2), int(size * 1.5 + pad * 0.6)
    s = 2
    img = Image.new("RGBA", (bw * s, bh * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bw * s - 1, bh * s - 1], radius=bh * s // 2, fill=(21, 13, 9, 190), outline=(244, 169, 73, 255), width=2)
    d.text((pad * s, int(size * 0.28) * s), text, font=font(size * s, bold=True), fill=(247, 240, 230, 255))
    img = img.resize((bw, bh), Image.LANCZOS)
    x = int(w * safe["left"]) if corner[1] == "l" else int(w * (1 - safe["right"]) - bw)
    y = int(h * safe["top"]) if corner[0] == "t" else int(h * (1 - safe["bottom"]) - bh)
    return to_np(img), x, y


def render_legal(lines: list[str], w: int, h: int, aspect: str) -> tuple[np.ndarray, int, int]:
    safe = SAFE_AREAS[aspect]
    size = int(min(w, h) * 0.026)
    f = font(size)
    max_w = w * (1 - safe["left"] - safe["right"]) * 0.9
    wrapped: list[str] = []
    for ln in lines:
        wrapped += wrap(ln, f, max_w)
    lh = int(size * 1.3)
    bw = int(max(f.getlength(x) for x in wrapped) + size)
    bh = lh * len(wrapped) + int(size * 0.7)
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=6, fill=(21, 13, 9, 170))
    for i, ln in enumerate(wrapped):
        d.text((int(size * 0.5), int(size * 0.3) + i * lh), ln, font=f, fill=(246, 235, 221, 255))
    x = int((w - bw) / 2)
    y = int(h * (1 - safe["bottom"]) - bh - h * 0.17)
    return to_np(img), x, y


# ----------------------------------------------------------------------------------------------- end card


def endcard_layout(spec: RenderSpec, w: int, h: int) -> dict[str, Any]:
    """Geometry of the end card — shared by the renderer and the Brand Guardian (logo size / clear-space checks)."""
    ec = spec.endcard
    safe = SAFE_AREAS[spec.aspect]
    vertical = h > w
    logo_w = w * (0.50 if vertical else 0.24)
    logo_h = logo_w * 0.62
    logo_y = h * (0.12 if vertical else 0.08)
    logo_x = (w - logo_w) / 2
    gap = spec.brand.logo_clear_space_ratio * logo_h + h * 0.012
    y = logo_y + logo_h + gap
    elements: list[dict[str, Any]] = []
    hl_size = int(min(w, h) * (0.078 if vertical else 0.068))
    hf = font(hl_size, bold=True, serif=True)
    hl_lines = wrap((ec.headline if ec else ""), hf, w * 0.84)[:2]
    hl_h = int(hl_size * 1.2) * max(1, len(hl_lines))
    if ec and ec.headline:
        elements.append({"name": "headline", "x": (w - max(hf.getlength(x) for x in hl_lines)) / 2, "y": y, "w": max(hf.getlength(x) for x in hl_lines), "h": hl_h})
        y += hl_h + h * 0.035
    cta_box = None
    if ec and ec.cta:
        cs = int(min(w, h) * 0.04)
        cf = font(cs, bold=True)
        bw, bh = cf.getlength(ec.cta) + cs * 2.2, cs * 2.3
        cta_box = {"name": "cta", "x": (w - bw) / 2, "y": y, "w": bw, "h": bh, "size": cs}
        elements.append(cta_box)
        y += bh + h * 0.025
    if ec and ec.url:
        us = int(min(w, h) * 0.03)
        uf = font(us)
        elements.append({"name": "url", "x": (w - uf.getlength(ec.url)) / 2, "y": y, "w": uf.getlength(ec.url), "h": us * 1.3, "size": us})
    legal_lines: list[str] = []
    if ec and ec.legal:
        ls = int(min(w, h) * 0.024)
        lf = font(ls)
        for ln in ec.legal:
            legal_lines += wrap(ln, lf, w * (1 - safe["left"] - safe["right"]) * 0.92)
        lh = int(ls * 1.35)
        ly = h * (1 - safe["bottom"]) - lh * len(legal_lines) + h * 0.03
        elements.append({"name": "legal", "x": w * safe["left"], "y": ly, "w": w * (1 - safe["left"] - safe["right"]), "h": lh * len(legal_lines), "size": ls, "lines": legal_lines, "lh": lh})
    return {
        "logo": {"x": logo_x, "y": logo_y, "w": logo_w, "h": logo_h, "frame_w": float(w), "frame_h": float(h)},
        "elements": elements,
        "headline_lines": hl_lines,
        "headline_size": hl_size,
        "colors": {"bg": ec.bg if ec else "#2B1A12", "fg": ec.fg if ec else "#F6EBDD", "accent": ec.accent if ec else "#F2A03D"},
    }


def render_endcard(spec: RenderSpec, w: int, h: int) -> Image.Image:
    ec = spec.endcard
    assert ec is not None
    lay = endcard_layout(spec, w, h)
    img = Image.new("RGB", (w, h), _rgb(ec.bg))
    # subtle warm glow behind the logo
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    lg = lay["logo"]
    gd.ellipse([lg["x"] - lg["w"] * 0.4, lg["y"] - lg["h"] * 0.3, lg["x"] + lg["w"] * 1.4, lg["y"] + lg["h"] * 1.3], fill=(*_rgb(ec.accent), 42))
    glow = glow.filter(ImageFilter.GaussianBlur(max(w, h) * 0.06))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    logo = draw_logo(int(lg["w"]), spec.brand.wordmark, spec.brand.sub, mark=ec.accent, ink=ec.fg)
    img.alpha_composite(logo, (int(lg["x"]), int(lg["y"])))
    d = ImageDraw.Draw(img)
    for el in lay["elements"]:
        if el["name"] == "headline":
            hf = font(lay["headline_size"], bold=True, serif=True)
            yy = el["y"]
            for ln in lay["headline_lines"]:
                d.text(((w - hf.getlength(ln)) / 2, yy), ln, font=hf, fill=_rgb(ec.fg))
                yy += int(lay["headline_size"] * 1.2)
        elif el["name"] == "cta":
            cf = font(el["size"], bold=True)
            d.rounded_rectangle([el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"]], radius=int(el["h"] / 2), fill=_rgb(ec.accent))
            d.text((el["x"] + (el["w"] - cf.getlength(ec.cta or "")) / 2, el["y"] + el["h"] * 0.5 - el["size"] * 0.62), ec.cta or "", font=cf, fill=_rgb(ec.bg))
        elif el["name"] == "url":
            d.text((el["x"], el["y"]), ec.url or "", font=font(el["size"]), fill=_rgb(ec.fg))
        elif el["name"] == "legal":
            lf = font(el["size"])
            for i, ln in enumerate(el["lines"]):
                d.text((w * 0.5 - lf.getlength(ln) / 2, el["y"] + i * el["lh"]), ln, font=lf, fill=(*_rgb(ec.fg), 200))
    return img.convert("RGB")


@lru_cache(maxsize=8)
def vignette(w: int, h: int, strength: float = 0.28) -> Image.Image:
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xs - w / 2) / (w / 2)) ** 2 + ((ys - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
    m = 1.0 - strength * np.clip(d, 0, 1) ** 2.2
    return Image.fromarray((np.stack([m, m, m], -1) * 255).astype(np.uint8), "RGB")
