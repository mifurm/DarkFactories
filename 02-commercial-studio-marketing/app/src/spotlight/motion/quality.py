"""Motion quality gate: does a generated clip really MOVE, or is it a still with a camera move?

Image-to-video models sometimes return a near-static clip (a "calm" prompt, a hard-to-animate frame). A still with a Ken-Burns zoom is as good as that for
the viewer — and for any check based on pixel differences between frames, because a camera move changes every pixel. So the measure is the optical flow
(Farneback, dense) between frames 10 apart, MINUS the best global affine fit of that flow field: what a camera move on a flat picture (zoom, pan, roll) can
explain is removed, what remains is genuine subject motion — the "non-rigid" flow, in pixels at the analysis size (256x144 for 16:9; the same area for other aspects).

Calibration (raw clips, 8 frame pairs per clip): a still with a slow 1.0 -> 1.13 zoom scores 0.10-0.31; clips of the open model score 0.42-4.9 (the lowest one came from a
"static camera, very calm" prompt, action prompts give 0.9-4.9). So ``level``: ``low`` < 0.32 <= ``subtle`` < 1.0 <= ``rich``. OpenCV is imported lazily: without it every
level is ``unknown`` (and nothing is retried or reported as a problem) — measuring never raises.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..video import media

log = logging.getLogger("spotlight.motion")

LOW = 0.32  # below this a shot is no better than a still with a camera move
RICH = 1.0  # from this up the subject clearly moves
WIDTH, HEIGHT = 256, 144  # analysis size of a 16:9 clip (the calibration size); other aspects get the same area
FPS = 24
GAP = 10  # frames between the two pictures of a pair (0.42 s)
PAIRS = 8
LEVELS = ("low", "subtle", "rich", "unknown")


@dataclass(frozen=True)
class MotionQuality:
    non_rigid: float | None  # mean magnitude (px at the analysis size) of the flow that no global affine move explains
    total: float | None  # mean magnitude of the whole flow (camera included)
    level: str  # low | subtle | rich | unknown
    frames: int = 0  # frames of the clip that were analysed

    def to_dict(self) -> dict[str, Any]:
        return {"non_rigid": self.non_rigid, "total": self.total, "level": self.level, "frames": self.frames}

    @classmethod
    def from_dict(cls, doc: Any) -> MotionQuality | None:
        """The score stored on a clip asset (``meta.motion_score``); anything that is not one is None."""
        if not isinstance(doc, dict) or doc.get("level") not in LEVELS:
            return None
        nr, tot = doc.get("non_rigid"), doc.get("total")
        return cls(float(nr) if isinstance(nr, (int, float)) else None, float(tot) if isinstance(tot, (int, float)) else None, str(doc["level"]), int(doc.get("frames") or 0))


UNKNOWN = MotionQuality(None, None, "unknown", 0)


def level_for(non_rigid: float) -> str:
    return "low" if non_rigid < LOW else "subtle" if non_rigid < RICH else "rich"


def analysis_size(width: int, height: int) -> tuple[int, int]:
    """The 256x144 calibration size for 16:9; the same pixel area (so flow magnitudes stay comparable) for any other aspect, even sides."""
    ratio = max(width, 1) / max(height, 1)
    w = max(64, round((WIDTH * HEIGHT * ratio) ** 0.5 / 2) * 2)
    h = max(64, round(w / ratio / 2) * 2)
    return w, h


def _opencv() -> Any | None:
    try:
        import cv2
    except ImportError:
        return None
    return cv2


def score_frames(frames: np.ndarray) -> MotionQuality:
    """The score of decoded gray frames ``(n, h, w)`` uint8 (``unknown`` without OpenCV or with fewer than two frames)."""
    cv2 = _opencv()
    n = int(frames.shape[0]) if frames.ndim == 3 else 0
    if cv2 is None or n < 2:
        return UNKNOWN
    gap = min(GAP, n - 1)
    height, width = frames.shape[1:]
    ys, xs = np.mgrid[0:height, 0:width]
    design = np.stack([xs.ravel() / width, ys.ravel() / height, np.ones(height * width)], axis=1)  # [x/W, y/H, 1]: an affine field in each component
    non_rigid: list[float] = []
    total: list[float] = []
    for i in np.linspace(0, n - gap - 1, PAIRS).astype(int):
        flow = cv2.calcOpticalFlowFarneback(frames[i], frames[i + gap], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        fx, fy = flow[..., 0].ravel().astype(np.float64), flow[..., 1].ravel().astype(np.float64)
        rx = fx - design @ np.linalg.lstsq(design, fx, rcond=None)[0]
        ry = fy - design @ np.linalg.lstsq(design, fy, rcond=None)[0]
        non_rigid.append(float(np.mean(np.sqrt(rx * rx + ry * ry))))
        total.append(float(np.mean(np.sqrt(fx * fx + fy * fy))))
    nr = float(np.mean(non_rigid))
    return MotionQuality(round(nr, 3), round(float(np.mean(total)), 3), level_for(nr), n)


def decode_gray(path: Path, width: int, height: int) -> np.ndarray:
    """The clip as ``(n, height, width)`` uint8 gray frames at 24 fps (ffmpeg does the scaling: a 4.5 MB array for the longest clip)."""
    res = media.run([media.FFMPEG, "-v", "error", "-nostats", "-i", str(path), "-an", "-vf", f"fps={FPS},scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], timeout=120)
    n = len(res.stdout) // (width * height)
    return np.frombuffer(res.stdout, dtype=np.uint8, count=n * width * height).reshape(n, height, width)


def measure_motion(clip: bytes, work_dir: str | None = None) -> MotionQuality:
    """How much a generated MP4 moves (see the module docstring). Blocking (ffmpeg + OpenCV): call it with ``asyncio.to_thread``. Never raises."""
    if _opencv() is None:
        return UNKNOWN
    try:
        with tempfile.TemporaryDirectory(prefix="motion-", dir=work_dir or None) as td:
            path = Path(td) / "clip.mp4"
            path.write_bytes(clip)
            info = media.probe(path)["video"] or {}
            width, height = analysis_size(int(info.get("width") or WIDTH), int(info.get("height") or HEIGHT))
            return score_frames(decode_gray(path, width, height))
    except Exception as exc:  # a clip that cannot be measured is "unknown", never a failed render
        log.warning("motion quality could not be measured: %s", str(exc)[:200])
        return UNKNOWN


def ken_burns_control(clip: bytes, work_dir: str | None = None, zoom: float = 1.13) -> MotionQuality:
    """Calibration aid: the score of a STILL made from the clip's first frame with a slow 1.0 -> ``zoom`` push-in over as many frames as the clip has — what a preview
    render of that keyframe would look like. A clip that scores no better than this is a slideshow."""
    cv2 = _opencv()
    if cv2 is None:
        return UNKNOWN
    try:
        with tempfile.TemporaryDirectory(prefix="motion-", dir=work_dir or None) as td:
            path = Path(td) / "clip.mp4"
            path.write_bytes(clip)
            info = media.probe(path)["video"] or {}
            native_w, native_h = int(info["width"]), int(info["height"])
            width, height = analysis_size(native_w, native_h)
            first = np.frombuffer(media.run([media.FFMPEG, "-v", "error", "-nostats", "-i", str(path), "-an", "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]).stdout, dtype=np.uint8).reshape(native_h, native_w)
            n = len(decode_gray(path, width, height))
        frames = np.empty((n, height, width), dtype=np.uint8)
        for k in range(n):
            p = k / max(1, n - 1)
            z = 1.0 + (zoom - 1.0) * p * p * (3 - 2 * p)  # the compositor's ease
            cw, ch = native_w / z, native_h / z
            x0, y0 = (native_w - cw) / 2, (native_h - ch) / 2
            m = np.array([[native_w / cw, 0, -x0 * native_w / cw], [0, native_h / ch, -y0 * native_h / ch]], dtype=np.float64)
            warped = cv2.warpAffine(first, m, (native_w, native_h), flags=cv2.INTER_LINEAR)
            frames[k] = cv2.resize(warped, (width, height), interpolation=cv2.INTER_AREA)
        return score_frames(frames)
    except Exception as exc:
        log.warning("ken-burns control could not be measured: %s", str(exc)[:200])
        return UNKNOWN
