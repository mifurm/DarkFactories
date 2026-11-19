"""Build the 'slideshow vs film' evidence figure for the deck: the SAME shots rendered as Preview (stills + camera moves) and as Cinematic (AI video).

    python deck/make_before_after.py PREVIEW.mp4 CINEMATIC.mp4 [--out deck/assets/cinematic-before-after.png]

Both inputs are final spots of the same storyboard (download them from the app: Library → the spot's asset, or ``GET /api/library/assets/{id}/content``).
The figure is 1600×900: for shot 1 and shot 2, four frames from each render, one row per render. Needs ffmpeg + Pillow.
"""

from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
LABEL_W, HEAD_H = 176, 64
COLS = 4
TILE_W = (W - LABEL_W) // COLS
TILE_H = round(TILE_W * 9 / 16)
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
# (shot label, times in seconds): chosen inside the scenes of the Dawn Roast master (3.3 s / 4.2 s / 4.2 s), away from the dissolves
SHOTS = [("SHOT 1", (0.5, 1.3, 2.1, 2.9)), ("SHOT 2", (4.4, 5.4, 6.4, 7.2))]
INK, CREAM, AMBER, MUTED = (43, 26, 18), (246, 235, 221), (242, 160, 61), (120, 100, 88)


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def frame_at(video: Path, t: float) -> Image.Image:
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(out)).convert("RGB").resize((TILE_W, TILE_H), Image.LANCZOS)


def build(preview: Path, cinematic: Path, out: Path) -> None:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.text((24, 16), "Same storyboard, same keyframes, same edit: left to right = time", font=font(26), fill=INK)
    y = HEAD_H
    for shot, times in SHOTS:
        for name, video, colour in (("PREVIEW", preview, MUTED), ("CINEMATIC", cinematic, AMBER)):
            d.rectangle((0, y, LABEL_W - 8, y + TILE_H - 1), fill=colour)
            d.text((12, y + 14), shot, font=font(20), fill=(255, 255, 255))
            d.text((12, y + 44), name, font=font(24), fill=(255, 255, 255))
            d.text((12, y + 84), "stills +" if name == "PREVIEW" else "AI video", font=font(18), fill=(255, 255, 255))
            if name == "PREVIEW":
                d.text((12, y + 106), "camera move", font=font(18), fill=(255, 255, 255))
            for i, t in enumerate(times):
                x = LABEL_W + i * TILE_W
                img.paste(frame_at(video, t), (x, y))
                d.text((x + 8, y + TILE_H - 28), f"{t:.1f} s", font=font(18), fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
            y += TILE_H
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    print(f"wrote {out} ({img.size[0]}x{img.size[1]}, {out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("preview", type=Path)
    ap.add_argument("cinematic", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "assets" / "cinematic-before-after.png")
    a = ap.parse_args()
    build(a.preview, a.cinematic, a.out)
