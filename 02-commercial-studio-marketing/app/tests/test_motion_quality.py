"""Cinematic motion — the motion quality gate: does a generated clip really MOVE, or is it a still with a camera move?

The measure (optical flow between frames 10 apart, minus the best global affine fit of that flow — see ``motion/quality.py``) is calibrated here on textured synthetic scenes:
a camera move on a still scores far below ``LOW`` however large the flow, motion no camera move can explain scores far above the stub's bar, a frozen clip is the floor.
Offline; what needs OpenCV or ffmpeg is skipped without them."""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import needs_cv2, needs_ffmpeg
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.motion import animator
from spotlight.motion.quality import (
    LOW,
    RICH,
    UNKNOWN,
    MotionQuality,
    analysis_size,
    ken_burns_control,
    level_for,
    measure_motion,
    score_frames,
)
from spotlight.video import media

W, H = 256, 144  # the analysis size of a 16:9 clip: the synthetic scenes are made at it


# ------------------------------------------------------------------------------------------------ synthetic scenes and clips


def textured(seed: int = 1, w: int = W, h: int = H) -> np.ndarray:
    """A photo-like still: noise at five scales. Optical flow needs texture to lock on to (the smooth stub keyframes are too flat to calibrate on)."""
    import cv2

    rng = np.random.default_rng(seed)
    img = np.zeros((h, w), np.float32)
    for sigma, gain in ((0.8, 0.5), (1.6, 1.0), (3.2, 1.6), (6.4, 2.4), (12.0, 3.0)):
        layer = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), sigma)
        img += gain * layer / max(float(layer.std()), 1e-6)
    img -= img.min()
    return (img * (255.0 / img.max())).astype(np.uint8)


def frozen(still: np.ndarray, n: int = 49) -> np.ndarray:
    return np.repeat(still[None], n, axis=0)


def camera_move(source: np.ndarray, n: int = 49, zoom: float = 1.13, roll_deg: float = 0.0) -> np.ndarray:
    """A push-in (and roll) over a still, or over frames that already move: what a Ken-Burns render does, with the compositor's ease."""
    import cv2

    frames = frozen(source, n) if source.ndim == 2 else source
    h, w = frames.shape[1:]
    out = np.empty_like(frames)
    for k in range(len(frames)):
        p = k / (len(frames) - 1)
        e = p * p * (3 - 2 * p)
        m = cv2.getRotationMatrix2D((w / 2, h / 2), roll_deg * e, 1.0 + (zoom - 1.0) * e)
        out[k] = cv2.warpAffine(frames[k], m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


def waves(still: np.ndarray, n: int = 49, amp: float = 1.2, lam: float = 70.0) -> np.ndarray:
    """Motion no camera move produces: travelling waves displace the picture (water, cloth, steam)."""
    import cv2

    h, w = still.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    out = np.empty((n, h, w), np.uint8)
    for k in range(n):
        t = k / 24.0 * 0.5 * 2 * np.pi
        out[k] = cv2.remap(still, xs + amp * np.sin(2 * np.pi * ys / lam + t), ys + amp * np.cos(2 * np.pi * xs / lam + t * 1.3), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


def subject_crossing(still: np.ndarray, n: int = 49) -> np.ndarray:
    """A subject (a textured disc whose own texture slides) crosses a static scene while the camera does not move."""
    h, w = still.shape
    other = textured(99, w, h)
    ys, xs = np.mgrid[0:h, 0:w]
    out = np.empty((n, h, w), np.uint8)
    for k in range(n):
        inside = ((xs - (60 + 1.5 * k)) ** 2 + (ys - (70 + 14 * np.sin(k / 9))) ** 2) < 34**2
        out[k] = np.where(inside, np.roll(other, int(round(0.7 * k)), axis=1), still)
    return out


def encode(frames: np.ndarray, fps: int = 24) -> bytes:
    """Gray frames ``(n, h, w)`` as an H.264 MP4: what the decoder sees of a model's clip, compression noise included."""
    n, h, w = frames.shape
    with tempfile.TemporaryDirectory() as td:  # conftest keeps the system temp dir inside the project
        out = Path(td) / "clip.mp4"
        media.run([media.FFMPEG, "-y", "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(out)], input_bytes=frames.tobytes())
        return out.read_bytes()


def still_clip(image: bytes, width: int, height: int, frames: int, fps: int = 24) -> bytes:
    """A clip that does not move at all (the picture, repeated): what an image-to-video model sometimes returns when it ignores the prompt."""
    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "frame.png", Path(td) / "still.mp4"
        Image.open(io.BytesIO(image)).convert("RGB").save(src)
        media.run([media.FFMPEG, "-y", "-v", "error", "-nostats", "-loop", "1", "-framerate", str(fps), "-i", str(src), "-frames:v", str(frames), "-vf", f"scale={width}:{height}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)])
        return out.read_bytes()


def keyframe(seed: int = 3, size: tuple[int, int] = (960, 640)) -> bytes:
    buf = io.BytesIO()
    render_stub_scene("dawn", size, None, seed).save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ levels, sizes, the stored score


@pytest.mark.parametrize(("non_rigid", "level"), [(0.0, "low"), (0.319, "low"), (LOW, "subtle"), (0.42, "subtle"), (0.999, "subtle"), (RICH, "rich"), (4.9, "rich")])
def test_the_levels_follow_the_calibrated_thresholds(non_rigid: float, level: str):
    assert level_for(non_rigid) == level and (LOW, RICH) == (0.32, 1.0)


@pytest.mark.parametrize(("w", "h", "expected"), [(1024, 576, (256, 144)), (1280, 720, (256, 144)), (576, 1024, (144, 256)), (768, 768, (192, 192))])
def test_the_analysis_size_keeps_the_calibrated_pixel_area_for_every_aspect(w: int, h: int, expected: tuple[int, int]):
    assert analysis_size(w, h) == expected
    aw, ah = analysis_size(640, 800)  # 4:5: no calibration size of its own, so the same area and the same shape, with even sides
    assert aw % 2 == 0 and ah % 2 == 0 and abs(aw * ah / (W * H) - 1) < 0.03 and abs(aw / ah - 0.8) < 0.02


def test_a_score_survives_the_asset_meta_and_anything_else_is_not_a_score():
    q = MotionQuality(1.234, 2.5, "rich", 97)
    assert MotionQuality.from_dict(q.to_dict()) == q and set(q.to_dict()) == {"non_rigid", "total", "level", "frames"}
    assert MotionQuality.from_dict(UNKNOWN.to_dict()) == UNKNOWN
    assert MotionQuality.from_dict({"level": "low", "non_rigid": "x", "total": None}) == MotionQuality(None, None, "low", 0)
    assert [MotionQuality.from_dict(x) for x in (None, "rich", 3, {}, {"level": "excellent"})] == [None] * 5


def test_without_opencv_every_clip_is_unknown_and_nothing_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "cv2", None)  # `import cv2` raises ImportError
    assert measure_motion(b"anything") == UNKNOWN and ken_burns_control(b"anything") == UNKNOWN
    assert score_frames(np.zeros((12, 16, 16), np.uint8)) == UNKNOWN
    assert UNKNOWN.level == "unknown" and UNKNOWN.non_rigid is None and UNKNOWN.total is None


# ------------------------------------------------------------------------------------------------ the metric


@needs_cv2
@pytest.mark.parametrize(("zoom", "roll"), [(1.13, 0.0), (1.2, 0.0), (1.04, 1.0)])
@pytest.mark.parametrize("seed", [1, 2])
def test_a_camera_move_on_a_still_is_not_motion_however_large_the_flow(seed: int, zoom: float, roll: float):
    q = score_frames(camera_move(textured(seed), zoom=zoom, roll_deg=roll))
    assert q.level == "low" and q.non_rigid is not None and q.non_rigid < LOW  # the Ken-Burns control of the calibration: 0.10-0.31
    assert q.total is not None and q.total > 0.5 and q.total > 3 * q.non_rigid  # a frame-difference check passes this: every pixel changes, none of it is the subject
    assert q.frames == 49


@needs_cv2
@pytest.mark.parametrize("make", [waves, subject_crossing, lambda s: camera_move(waves(s))], ids=["waves", "subject-crossing", "waves-under-a-camera-move"])
@pytest.mark.parametrize("seed", [1, 2])
def test_motion_that_no_camera_move_explains_scores_far_above_the_bar(seed: int, make):
    q = score_frames(make(textured(seed)))
    assert q.non_rigid is not None and q.non_rigid >= 0.6 and q.level in {"subtle", "rich"}


@needs_cv2
def test_a_short_clip_is_measured_with_what_it_has_and_a_frozen_clip_is_the_floor():
    still = textured(1)
    q = score_frames(waves(still, n=25))
    assert q.non_rigid is not None and q.non_rigid >= 0.6 and q.frames == 25  # the shortest clip the worker makes
    short = score_frames(waves(still, n=4))
    assert short.level != "unknown" and short.frames == 4  # fewer frames than the pair gap: the pairs shrink, the gate still answers
    floor = score_frames(frozen(still))
    assert floor.level == "low" and floor.non_rigid is not None and floor.non_rigid < 0.01 and floor.total is not None and floor.total < 0.01
    assert score_frames(frozen(still, 1)) == UNKNOWN  # one picture has no motion to measure (and nothing to judge)


# ------------------------------------------------------------------------------------------------ from an MP4


@needs_cv2
@needs_ffmpeg
def test_an_mp4_is_decoded_to_the_analysis_size_and_judged_like_the_raw_frames(tmp_path: Path):
    still = textured(1, 512, 288)  # twice the analysis size: ffmpeg scales it down by area
    kb, moving, standing = encode(camera_move(still)), encode(waves(still, amp=2.4, lam=140.0)), encode(frozen(still))
    low = measure_motion(kb, str(tmp_path))
    assert low.level == "low" and low.non_rigid is not None and low.non_rigid < LOW and low.frames == 49 and low.total is not None and low.total > 3 * low.non_rigid
    rich = measure_motion(moving, str(tmp_path))
    assert rich.non_rigid is not None and rich.non_rigid >= 0.6 and rich.level in {"subtle", "rich"}
    assert measure_motion(standing, str(tmp_path)).level == "low"
    assert not list(tmp_path.iterdir())  # the scratch files of the measurement are gone


@needs_cv2
@needs_ffmpeg
def test_a_clip_that_cannot_be_read_is_unknown_never_an_error(tmp_path: Path):
    assert measure_motion(b"this is not a video", str(tmp_path)) == UNKNOWN and measure_motion(b"", str(tmp_path)) == UNKNOWN
    assert ken_burns_control(b"this is not a video", str(tmp_path)) == UNKNOWN
    assert not list(tmp_path.iterdir())


@needs_cv2
@needs_ffmpeg
@pytest.mark.parametrize(("w", "h", "n"), [(512, 288, 49), (288, 512, 49), (384, 384, 33), (256, 144, 25)], ids=["16:9", "9:16", "1:1", "shortest"])
def test_the_offline_animator_clears_the_gate_at_every_aspect_so_offline_renders_never_retry(w: int, h: int, n: int, tmp_path: Path):
    for seed in (7919, 15838):
        q = measure_motion(animator.animate(keyframe(seed % 5 + 1), w, h, n, 24, seed), str(tmp_path))
        assert q.non_rigid is not None and q.non_rigid >= 0.6 and q.level in {"subtle", "rich"} and q.frames == n, (w, h, n, seed, q)


@needs_cv2
@needs_ffmpeg
def test_the_ken_burns_control_scores_the_clips_first_frame_as_a_still_and_the_clip_beats_it(tmp_path: Path):
    clip = encode(waves(textured(1, 512, 288), amp=2.4, lam=140.0))  # (twice the analysis size: the waves are as large as in the 256x144 scenes after ffmpeg's scaling)
    real, control = measure_motion(clip, str(tmp_path)), ken_burns_control(clip, str(tmp_path))
    assert control.frames == real.frames == 49 and control.non_rigid is not None and real.non_rigid is not None and control.total is not None
    assert control.level == "low" and control.non_rigid < LOW and real.non_rigid >= 0.6  # the slideshow the clip is compared with: it zooms (large total flow) and does not move
    assert control.total > 0.5 and control.total > 3 * control.non_rigid
    assert measure_motion(still_clip(keyframe(), 512, 288, 49), str(tmp_path)).level == "low"
