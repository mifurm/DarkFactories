"""H.264 encoding through an ffmpeg subprocess; frames are piped as raw RGB, the output is a seekable file."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from .errors import InternalError

# BT.709 matrix + limited range, explicitly converted AND tagged so players/decoders agree on the colours.
# (setparams is what reliably writes primaries/transfer into the stream; the codec flags are belt and braces.)
_COLOR_FILTER = (
    "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic,format=yuv420p,"
    "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
)
_COLOR_TAGS = ("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv")


def find_ffmpeg(explicit: str | None = None) -> str:
    """Explicit path/name, else the ffmpeg bundled with imageio-ffmpeg (has libx264), else ffmpeg on PATH."""
    candidates: list[str | None] = [explicit]
    with contextlib.suppress(Exception):  # not installed / no bundled binary: fall through to PATH
        import imageio_ffmpeg  # noqa: PLC0415 - optional dependency, resolved lazily

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    candidates.append("ffmpeg")
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise InternalError("ffmpeg not found (install imageio-ffmpeg or set MOTION_FFMPEG)")


def frame_to_rgb_bytes(frame: Any, width: int, height: int) -> bytes:
    """PIL image, uint8 array or float array in [0,1] (diffusers ``output_type="np"``) -> raw RGB bytes."""
    if hasattr(frame, "convert"):
        frame = frame.convert("RGB")
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if arr.shape != (height, width, 3):
        raise InternalError(f"frame has shape {arr.shape}, expected {(height, width, 3)}")
    return np.ascontiguousarray(arr).tobytes()


def encode_h264(
    frames: Iterable[Any],
    *,
    width: int,
    height: int,
    fps: int,
    workdir: Path,
    ffmpeg: str | None = None,
    crf: int = 17,
    preset: str = "medium",
    timeout_s: float = 300.0,
) -> tuple[bytes, int]:
    """Encode frames to H.264 yuv420p (``-crf 17 -preset medium -movflags +faststart``, silent). Returns (mp4, n)."""
    exe = find_ffmpeg(ffmpeg)
    workdir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    out_path, err_path = workdir / f"clip-{token}.mp4", workdir / f"ffmpeg-{token}.log"
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-vf", _COLOR_FILTER,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), *_COLOR_TAGS,
        "-r", str(fps), "-movflags", "+faststart", str(out_path),
    ]  # fmt: skip
    count = 0
    returncode: int | None = None
    try:
        with open(err_path, "wb") as err_file:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_file)  # noqa: S603
            try:
                assert proc.stdin is not None
                try:
                    for frame in frames:
                        proc.stdin.write(frame_to_rgb_bytes(frame, width, height))
                        count += 1
                    proc.stdin.close()
                except BrokenPipeError:
                    pass  # ffmpeg exited early; its stderr explains why (below)
                returncode = proc.wait(timeout=timeout_s)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if returncode != 0 or not out_path.exists():
            tail = err_path.read_text("utf-8", "replace")[-600:].strip()
            raise InternalError(f"ffmpeg failed (exit {returncode}): {tail}")
        if count == 0:
            raise InternalError("no frames to encode")
        return out_path.read_bytes(), count
    except subprocess.TimeoutExpired as exc:
        raise InternalError(f"ffmpeg timed out after {timeout_s:.0f}s") from exc
    finally:
        for path in (out_path, err_path):
            path.unlink(missing_ok=True)
