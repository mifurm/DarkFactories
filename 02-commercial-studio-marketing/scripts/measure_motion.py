#!/usr/bin/env python
"""Measure how much a generated clip really MOVES (the motion quality gate of the cinematic path), and what a Ken-Burns still of its first frame scores for comparison.

    app/.venv/bin/python scripts/measure_motion.py clip.mp4 [more.mp4 ...]

Per clip it prints ``non_rigid`` (mean optical-flow magnitude, in pixels at the 256x144 analysis size, left over after the best global affine fit — what a camera move on a
still cannot explain), ``total`` (the whole flow, camera included) and ``level`` (``low`` < 0.32 <= ``subtle`` < 1.0 <= ``rich``), and the same for a slow 1.0 -> 1.13 push-in
over the clip's own first frame (the "control": what the preview render of that keyframe looks like). A clip that scores no better than its control is a slideshow.
Calibration: control 0.10-0.31, clips of the open model 0.42-4.9. Needs OpenCV (``opencv-python-headless``, a runtime dependency of the app: use the app venv) and ffmpeg.
Exit code: 0 all measured, 1 a file could not be measured, 2 OpenCV or ffmpeg is missing.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "src"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Motion quality of generated clips: non-rigid optical flow versus a Ken-Burns control of the first frame.")
    ap.add_argument("clips", nargs="+", type=Path, help="MP4 clip(s) to measure")
    args = ap.parse_args(argv)
    if importlib.util.find_spec("cv2") is None:
        print("error: OpenCV is not installed (pip install opencv-python-headless): it is a runtime dependency of the app, so run this with the app venv: app/.venv/bin/python scripts/measure_motion.py", file=sys.stderr)
        return 2
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("error: ffmpeg / ffprobe not found on PATH", file=sys.stderr)
        return 2
    from spotlight.motion.quality import ken_burns_control, measure_motion

    failed = 0
    scores: list[float] = []
    with tempfile.TemporaryDirectory(dir=str(ROOT / "app")) as work:  # scratch files stay inside the project
        for path in args.clips:
            try:
                data = path.read_bytes()
            except OSError as exc:
                print(f"{path}: cannot read ({exc.strerror or exc})", file=sys.stderr)
                failed += 1
                continue
            clip, control = measure_motion(data, work), ken_burns_control(data, work)
            if clip.level == "unknown":
                print(f"{path}: could not be measured (not a readable video?)", file=sys.stderr)
                failed += 1
                continue
            scores.append(clip.non_rigid or 0.0)
            ctl = f"non_rigid {control.non_rigid:.2f}  total {control.total:.2f}  {control.level}" if control.non_rigid is not None and control.total is not None else "n/a"
            print(f"{path.name}: non_rigid {clip.non_rigid:.2f}  total {clip.total:.2f}  level {clip.level}  ({clip.frames} frames)   |   Ken-Burns control of its first frame: {ctl}")
    if len(scores) > 1:
        ordered = sorted(scores)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        print(f"{len(scores)} clips: non_rigid min {ordered[0]:.2f}  median {median:.2f}  max {ordered[-1]:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
