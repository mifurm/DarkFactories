"""Procedural image-to-video animator: the offline stand-in for the generative model.

It turns the opening frame into a REAL moving clip (not a still with a zoom): a seeded camera path (push-in / pull-back, drift, <= 2 degrees of
sway), a low-frequency displacement shimmer that makes surfaces breathe, soft steam particles rising through the frame and a light sweep.
Deterministic for the same image + seed. Pillow does the per-frame work (a coarse mesh warp, alpha composites at reduced resolution), numpy only
builds the small per-frame parameter grids, ffmpeg encodes H.264 — about a second for a 93-frame 1024x576 clip.
"""

from __future__ import annotations

import hashlib
import io
import math
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from ..video import media

CELL = 32  # mesh cell size (px): the warp is piecewise-bilinear between these vertices
BASE_SCALE = 1.2  # the working image is 20 % larger than the frame so the camera can push / drift without showing edges
SHIMMER_RATE = 1.3  # speed of the travelling waves (with their amplitude: the part of the motion no camera move explains, see quality.py)
WARM = (255, 222, 170)
STEAM = (248, 240, 230)

ProgressFn = Callable[[float], None]


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _mesh_grid(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    xs = np.unique(np.round(np.linspace(0, width, max(2, math.ceil(width / CELL) + 1))).astype(int))
    ys = np.unique(np.round(np.linspace(0, height, max(2, math.ceil(height / CELL) + 1))).astype(int))
    return xs, ys


def animate(image: bytes, width: int, height: int, num_frames: int, fps: int, seed: int, progress: ProgressFn | None = None) -> bytes:
    """H.264 MP4 (yuv420p, no audio, ``fps``) of ``num_frames`` frames, ``width`` x ``height``, animated from ``image``."""
    digest = int(hashlib.sha256(image).hexdigest()[:8], 16)
    rng = np.random.default_rng((int(seed) * 1_000_003 + digest) % (2**63))
    src = Image.open(io.BytesIO(image)).convert("RGB")
    base_w, base_h = round(width * BASE_SCALE), round(height * BASE_SCALE)
    base = ImageOps.fit(src, (base_w, base_h), Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    # ---- seeded camera, shimmer, steam and light parameters (the camera looks at a width x height window of the 20 % larger base image: 10 % margin on every side)
    push = rng.random() < 0.7
    z0, z1 = (1.0, rng.uniform(1.07, 1.12)) if push else (rng.uniform(1.09, 1.12), 1.02)
    drift = np.array([rng.uniform(-1, 1), rng.uniform(-0.6, 0.6)]) * np.array([0.028 * width, 0.02 * height])
    rot_amp = math.radians(rng.uniform(0.5, 1.7)) * rng.choice([-1, 1])
    rot_phase = rng.uniform(0, math.tau)
    tall = min(1.0, max(0.0, height / width - 1.0))  # a tall frame crops the keyframe to a narrow, less textured strip, where the same breathing scores lower: give it a little more
    shimmer_px = rng.uniform(3.8, 5.6) * math.sqrt(width * height) / 768 * (1.0 + 0.45 * tall)  # the "breathing" is what a camera move cannot explain: it has to be clearly more than the measurement's noise floor (quality.py); relative to the frame area, like the analysis size
    lam = rng.uniform(0.35, 0.7, size=2) * np.array([width, height])  # shorter waves than the frame: a long wave is mostly an affine trend, which the measurement takes for camera motion
    sh_phase = rng.uniform(0, math.tau, size=4)
    sh_speed = rng.uniform(1.0, 1.8, size=2)

    n_steam = int(rng.integers(7, 11))
    steam = [
        {
            "x": rng.uniform(0.22, 0.78) * width, "y": rng.uniform(0.62, 0.92) * height, "rise": rng.uniform(0.28, 0.5) * height, "sway": rng.uniform(0.01, 0.035) * width,
            "phase": rng.uniform(0, math.tau), "r": rng.uniform(0.035, 0.075) * width, "alpha": rng.uniform(0.09, 0.17), "delay": rng.uniform(0.0, 0.45),
        }
        for _ in range(n_steam)
    ]
    sweep_angle = math.radians(rng.uniform(25, 55)) * rng.choice([-1, 1])
    sweep_gain = rng.uniform(0.11, 0.17)
    sweep_sigma = rng.uniform(0.16, 0.26)

    # light-sweep coordinate field at 1/8 resolution (a smooth band: cheap to evaluate, upscaled bilinearly)
    lw, lh = max(8, width // 8), max(8, height // 8)
    gy, gx = np.mgrid[0:lh, 0:lw].astype(np.float32)
    proj = ((gx / lw - 0.5) * math.cos(sweep_angle) * (width / height) + (gy / lh - 0.5) * math.sin(sweep_angle)) / (width / height)
    sw, sh = max(8, width // 4), max(8, height // 4)
    xs, ys = _mesh_grid(width, height)
    gxv, gyv = np.meshgrid(xs.astype(np.float64), ys.astype(np.float64))
    uu, vv = gxv - width / 2, gyv - height / 2
    xl, yl = xs.tolist(), ys.tolist()
    warm_img = Image.new("RGB", (width, height), WARM)
    steam_img = Image.new("RGB", (width, height), STEAM)
    black_img = Image.new("RGB", (width, height), (0, 0, 0))

    out_dir = tempfile.mkdtemp(prefix="stubclip-")
    out_path = Path(out_dir) / "clip.mp4"
    cmd = [
        media.FFMPEG, "-y", "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", "-an", str(out_path),
    ]  # fmt: skip
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        assert proc.stdin is not None
        for f in range(num_frames):
            t = f / max(1, num_frames - 1)
            e = _ease(t)
            z = z0 + (z1 - z0) * e
            theta = rot_amp * math.sin(math.tau * 0.5 * t + rot_phase) * (0.35 + 0.65 * math.sin(math.pi * t))
            c, s = math.cos(theta), math.sin(theta)
            cx = base_w / 2 + drift[0] * (e - 0.5)
            cy = base_h / 2 + drift[1] * (e - 0.5)
            # displacement shimmer: two slow travelling waves per axis
            tt = f / fps * SHIMMER_RATE
            ox = shimmer_px * (np.sin(math.tau * (gyv / lam[1] + sh_speed[0] * tt * 0.35) + sh_phase[0]) + 0.6 * np.sin(math.tau * (gxv / lam[0] - 0.7 * sh_speed[1] * tt * 0.3) + sh_phase[1]))
            oy = shimmer_px * (np.cos(math.tau * (gxv / lam[0] + sh_speed[1] * tt * 0.33) + sh_phase[2]) + 0.6 * np.cos(math.tau * (gyv / lam[1] - 0.6 * sh_speed[0] * tt * 0.3) + sh_phase[3]))
            sx = cx + (uu * c - vv * s) / z + ox
            sy = cy + (uu * s + vv * c) / z + oy
            px_, py_ = sx.tolist(), sy.tolist()
            mesh = [
                ((xl[i], yl[j], xl[i + 1], yl[j + 1]), (px_[j][i], py_[j][i], px_[j + 1][i], py_[j + 1][i], px_[j + 1][i + 1], py_[j + 1][i + 1], px_[j][i + 1], py_[j][i + 1]))
                for j in range(len(yl) - 1)
                for i in range(len(xl) - 1)
            ]
            frame = base.transform((width, height), Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)

            # soft steam rising through the frame (alpha drawn at 1/4 resolution, blurred, upscaled)
            alpha = Image.new("L", (sw, sh), 0)
            d = ImageDraw.Draw(alpha)
            for p in steam:
                life = (t * 1.25 - p["delay"]) / 0.8
                if not 0.0 < life < 1.0:
                    continue
                px = p["x"] + p["sway"] * math.sin(p["phase"] + life * 4.0)
                py = p["y"] - p["rise"] * life
                r = p["r"] * (0.8 + 0.9 * life)
                a = p["alpha"] * math.sin(math.pi * life) ** 1.3
                q = 0.25
                d.ellipse((px * q - r * q * 0.7, py * q - r * q * 1.1, px * q + r * q * 0.7, py * q + r * q * 1.1), fill=int(255 * a))
            alpha = alpha.filter(ImageFilter.GaussianBlur(radius=max(2, sw // 64))).resize((width, height), Image.Resampling.BILINEAR)
            frame = Image.composite(steam_img, frame, alpha)

            # a soft diagonal light sweep that crosses the frame once
            band = np.exp(-(((proj - (-0.75 + 1.5 * _ease(t))) / sweep_sigma) ** 2)) * sweep_gain
            light = Image.fromarray((band * 255).astype(np.uint8), "L").resize((width, height), Image.Resampling.BILINEAR)
            frame = ImageChops.screen(frame, Image.composite(warm_img, black_img, light))

            proc.stdin.write(frame.tobytes())
            if progress and f % 12 == 0:
                progress(f / num_frames)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        if proc.wait(timeout=120) != 0:
            raise media.MediaError(f"stub animator encode failed: {err[-300:]}")
        return out_path.read_bytes()
    finally:
        if proc.poll() is None:
            proc.kill()
        out_path.unlink(missing_ok=True)
        Path(out_dir).rmdir()
