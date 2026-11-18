"""Image preparation (centre crop + LANCZOS) and the ffmpeg H.264 encoder."""

from __future__ import annotations

import io
import json
import shutil
import stat
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from motion_worker import imaging, video
from motion_worker.errors import BadRequest, InternalError

from .conftest import keyframe_bytes

# ------------------------------------------------------------------------------------------ imaging


def ramp(width: int, height: int) -> Image.Image:
    """R encodes the column, G the row: lets a test see exactly which region survived the crop."""
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :].repeat(height, 0)
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None].repeat(width, 1)
    return Image.fromarray(np.stack([x, y, np.full_like(x, 90)], axis=-1).astype(np.uint8))


def test_wide_source_is_cropped_left_and_right_around_the_centre():
    out = imaging.fit_image(ramp(300, 100), 160, 96)  # 5:3 target from a 3:1 source: keep 167 of 300 columns
    assert out.size == (160, 96)
    arr = np.asarray(out).astype(int)
    left_expected = 66 / 299 * 255  # box starts at x=66
    right_expected = (66 + 167 - 1) / 299 * 255
    assert abs(arr[48, 0, 0] - left_expected) < 6
    assert abs(arr[48, -1, 0] - right_expected) < 6
    assert abs(arr[0, 80, 1] - 0) < 4 and abs(arr[-1, 80, 1] - 255) < 4  # full height kept


def test_tall_source_is_cropped_top_and_bottom_around_the_centre():
    out = imaging.fit_image(ramp(100, 300), 160, 96)  # keep 60 of 300 rows, starting at row 120
    arr = np.asarray(out).astype(int)
    assert abs(arr[0, 80, 1] - 120 / 299 * 255) < 6
    assert abs(arr[-1, 80, 1] - 179 / 299 * 255) < 6
    assert abs(arr[48, 0, 0] - 0) < 4 and abs(arr[48, -1, 0] - 255) < 4  # full width kept


def test_exact_size_is_returned_pixel_identical():
    src = ramp(160, 96)
    assert np.array_equal(np.asarray(imaging.fit_image(src, 160, 96)), np.asarray(src))


def test_same_aspect_is_only_resized():
    out = imaging.fit_image(ramp(320, 192), 160, 96)
    assert out.size == (160, 96)
    arr = np.asarray(out).astype(int)
    assert arr[0, 0, 0] < 4 and arr[0, -1, 0] > 251


@pytest.mark.parametrize(("w", "h"), [(1536, 1024), (1024, 1536), (1000, 999), (97, 1500), (4000, 30)])
@pytest.mark.parametrize("target", [(1024, 576), (576, 1024), (768, 768), (640, 800)])
def test_fit_always_yields_the_exact_target_size(w, h, target):
    assert imaging.fit_image(Image.new("RGB", (w, h), (10, 20, 30)), *target).size == target


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_decode_supported_formats(fmt):
    img = imaging.decode_image(keyframe_bytes(64, 48, fmt))
    assert img.mode == "RGB"
    assert img.size == (64, 48)


def test_transparency_is_flattened_onto_white():
    rgba = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
    rgba.putpixel((0, 0), (0, 0, 255, 255))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    img = imaging.decode_image(buf.getvalue())
    assert img.getpixel((4, 4)) == (255, 255, 255)
    assert img.getpixel((0, 0)) == (0, 0, 255)

    pal = Image.new("P", (4, 4), 0)
    pal.info["transparency"] = 0
    buf = io.BytesIO()
    pal.save(buf, format="PNG", transparency=0)
    assert imaging.decode_image(buf.getvalue()).size == (4, 4)


def test_exif_orientation_is_applied():
    img = Image.new("RGB", (40, 20), (1, 2, 3))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise to display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    assert imaging.decode_image(buf.getvalue()).size == (20, 40)


def test_bad_images_are_bad_requests(monkeypatch):
    with pytest.raises(BadRequest, match="empty"):
        imaging.decode_image(b"")
    with pytest.raises(BadRequest, match="decoded"):
        imaging.decode_image(b"definitely not an image")
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, format="GIF")
    with pytest.raises(BadRequest, match="unsupported"):
        imaging.decode_image(gif.getvalue())
    monkeypatch.setattr(imaging, "MAX_IMAGE_BYTES", 100)
    with pytest.raises(BadRequest, match="too large"):
        imaging.decode_image(keyframe_bytes())
    monkeypatch.setattr(imaging, "MAX_IMAGE_BYTES", 10**8)
    monkeypatch.setattr(imaging, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(BadRequest, match="pixels"):
        imaging.decode_image(keyframe_bytes())
    truncated = keyframe_bytes()[:200]
    monkeypatch.setattr(imaging, "MAX_IMAGE_PIXELS", 10**8)
    with pytest.raises(BadRequest):
        imaging.decode_image(truncated)


# ------------------------------------------------------------------------------------------ video


def ffprobe_stream(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if exe is None:
        pytest.skip("ffprobe not available")
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["streams"][0]


def decode_frames(path: Path, width: int, height: int) -> np.ndarray:
    raw = subprocess.run(
        [video.find_ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


@pytest.mark.ffmpeg
def test_encode_produces_tagged_24fps_yuv420p_h264_with_faststart(tmp_path):
    w, h, n = 256, 128, 25
    base = np.zeros((h, w, 3), np.uint8)
    base[:, :, 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    base[:, :, 1] = 128
    data, count = video.encode_h264(
        (np.roll(base, i * 3, axis=1) for i in range(n)), width=w, height=h, fps=24, workdir=tmp_path / "enc"
    )
    assert count == n
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(data)
    stream = ffprobe_stream(clip)
    assert (stream["codec_name"], stream["pix_fmt"], stream["r_frame_rate"], stream["nb_frames"]) == (
        "h264",
        "yuv420p",
        "24/1",
        "25",
    )
    assert (stream["width"], stream["height"]) == (w, h)
    assert (stream["color_space"], stream["color_range"]) == ("bt709", "tv")
    assert stream.get("color_transfer") == "bt709" and stream.get("color_primaries") == "bt709"
    assert data.find(b"moov") < data.find(b"mdat")  # +faststart
    assert not list((tmp_path / "enc").iterdir()), "scratch files must be cleaned up"
    decoded = decode_frames(clip, w, h)
    assert decoded.shape[0] == n
    assert np.abs(decoded[0].astype(int) - base.astype(int)).mean() < 2.5  # colours survive the BT.709 round trip


@pytest.mark.ffmpeg
def test_encoder_accepts_pil_uint8_and_float_frames(tmp_path):
    w, h = 64, 64
    frames = [
        Image.new("RGB", (w, h), (200, 30, 30)),
        np.full((h, w, 3), 90, np.uint8),
        np.full((h, w, 3), 0.5, np.float32),  # diffusers output_type="np": floats in [0, 1]
        Image.new("RGBA", (w, h), (10, 200, 10, 255)),
    ]
    data, count = video.encode_h264(iter(frames), width=w, height=h, fps=24, workdir=tmp_path)
    assert count == 4
    clip = tmp_path / "c.mp4"
    clip.write_bytes(data)
    decoded = decode_frames(clip, w, h).astype(int)
    assert decoded[0, 0, 0, 0] > 150 and decoded[0, 0, 0, 1] < 80
    assert 70 < decoded[1].mean() < 110
    assert 110 < decoded[2].mean() < 145  # 0.5 -> ~128


def test_frame_conversion_rules():
    assert video.frame_to_rgb_bytes(np.full((2, 3, 3), 1.0, np.float32), 3, 2) == b"\xff" * 18
    assert video.frame_to_rgb_bytes(np.full((2, 3, 3), -4.0, np.float32), 3, 2) == b"\x00" * 18
    with pytest.raises(InternalError, match="shape"):
        video.frame_to_rgb_bytes(np.zeros((4, 4, 3), np.uint8), 3, 2)


def fake_ffmpeg(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-ffmpeg"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_ffmpeg_failures_become_internal_errors_with_the_reason(tmp_path):
    big = [np.zeros((128, 256, 3), np.uint8)] * 12  # > pipe buffer: writing hits the broken pipe
    exe = fake_ffmpeg(tmp_path, "echo 'boom: no such encoder' >&2\nexit 3")
    with pytest.raises(InternalError, match=r"exit 3.*boom"):
        video.encode_h264(iter(big), width=256, height=128, fps=24, workdir=tmp_path / "w", ffmpeg=exe)
    ok_but_no_output = fake_ffmpeg(tmp_path, "cat >/dev/null\nexit 0")
    with pytest.raises(InternalError, match="ffmpeg failed"):
        video.encode_h264(iter(big), width=256, height=128, fps=24, workdir=tmp_path / "w", ffmpeg=ok_but_no_output)
    assert not list((tmp_path / "w").iterdir())


def test_ffmpeg_timeout_kills_the_process(tmp_path):
    exe = fake_ffmpeg(tmp_path, "cat >/dev/null\nsleep 30")
    frames = [np.zeros((16, 16, 3), np.uint8)]
    with pytest.raises(InternalError, match="timed out"):
        video.encode_h264(iter(frames), width=16, height=16, fps=24, workdir=tmp_path / "w", ffmpeg=exe, timeout_s=0.3)


@pytest.mark.ffmpeg
def test_empty_input_is_an_error(tmp_path):
    with pytest.raises(InternalError):
        video.encode_h264(iter([]), width=64, height=64, fps=24, workdir=tmp_path)


def test_find_ffmpeg_resolution_order(tmp_path, monkeypatch):
    exe = fake_ffmpeg(tmp_path, "exit 0")
    assert video.find_ffmpeg(exe) == exe
    monkeypatch.setattr(video.shutil, "which", lambda name: None)
    with pytest.raises(InternalError, match="not found"):
        video.find_ffmpeg("/nope/ffmpeg")
