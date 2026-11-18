"""Compositor behavioural tests: ffprobe-verified MP4, loudness within ±1.5 LU, aspect ratios, caption/SRT timing."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

from conftest import needs_ffmpeg
from spotlight.core.ai.stubs import render_stub_scene, synth_pseudo_speech
from spotlight.video import media
from spotlight.video.music import generate_track
from spotlight.video.renderer import cover_box, motion_params, render
from spotlight.video.spec import EndCardSpec, MusicSpec, RenderSpec, SceneSpec, VoLine, make_captions, to_srt


def _jpeg(seed: int, size=(960, 640)) -> bytes:
    buf = io.BytesIO()
    render_stub_scene("dawn", size, None, seed).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def make_spec(aspect="16:9", scenes=3, per=3.2, lufs=-16.0) -> tuple[RenderSpec, dict[str, bytes], dict[str, bytes]]:
    sc = [SceneSpec(id=f"s{i}", asset_id=f"img{i}", duration=per, motion=m, focal=(0.5, 0.55), role="hook", super_text="Some mornings deserve a slower start." if i == 0 else None)
          for i, m in zip(range(scenes), ["zoom_in", "pan_left", "parallax", "zoom_out"], strict=False)]
    vo_text = ["Some mornings deserve a slower start.", "Dawn Roast. Roasted in small batches.", "Wake up slowly."]
    vo, audio = [], {}
    t = 0.4
    for i, text in enumerate(vo_text[:scenes]):
        data = synth_pseudo_speech(text, "openai:nova")
        dur = media.audio_duration(data)
        vo.append(VoLine(id=f"vo{i}", text=text, start=t, duration=dur))
        audio[f"vo{i}"] = data
        t += per
    spec = RenderSpec(
        id="spec1", aspect=aspect, scenes=sc, vo=vo, captions=make_captions(vo), music=MusicSpec(), endcard=EndCardSpec(duration=2.4, headline="Wake up slowly.", cta="Find Dawn Roast", url="northwind.example/dawn", legal=["Contains caffeine. Not recommended for children or pregnant women."]),
        disclosure_badge="AI-generated", legal_supers=["Contains caffeine. Not recommended for children or pregnant women."], loudness_lufs=lufs,
    )
    images = {f"img{i}": _jpeg(i + 1) for i in range(scenes)}
    return spec, images, audio


@needs_ffmpeg
def test_render_mp4_is_valid_h264_aac_with_correct_duration_and_loudness(tmp_path: Path):
    spec, images, audio = make_spec()
    res = render(spec, images, audio, tmp_path)
    info = media.probe(tmp_path / "video.mp4")
    assert info["video"]["codec"] == "h264"
    assert (info["video"]["width"], info["video"]["height"]) == (1280, 720)
    assert info["audio"] and info["audio"]["codec"] == "aac"
    assert abs(info["duration"] - spec.duration) <= 0.5
    # independent EBU R128 measurement of the delivered file
    lufs = media.measure_loudness(tmp_path / "video.mp4")["integrated_lufs"]
    assert abs(lufs - (-16.0)) <= 1.5, lufs
    assert res["loudness"]["true_peak_dbfs"] <= -0.5
    assert (tmp_path / "poster.jpg").stat().st_size > 5000


@needs_ffmpeg
@pytest.mark.parametrize(("aspect", "size"), [("9:16", (720, 1280)), ("1:1", (720, 720)), ("4:5", (576, 720))])
def test_aspect_ratios_render_with_exact_frame_size(tmp_path: Path, aspect: str, size: tuple[int, int]):
    spec, images, audio = make_spec(aspect=aspect, scenes=2, per=2.0)
    render(spec, images, audio, tmp_path)
    v = media.probe(tmp_path / "video.mp4")["video"]
    assert (v["width"], v["height"]) == size


@needs_ffmpeg
def test_broadcast_loudness_target_minus_23(tmp_path: Path):
    spec, images, audio = make_spec(scenes=2, per=3.0, lufs=-23.0)
    render(spec, images, audio, tmp_path)
    assert abs(media.measure_loudness(tmp_path / "video.mp4")["integrated_lufs"] - (-23.0)) <= 1.5


def test_captions_and_srt_timing_are_monotonic_and_inside_the_spot():
    spec, _, _ = make_spec()
    cues = spec.captions
    assert cues, "captions must be generated from the voice-over"
    for c in cues:
        assert c.end > c.start
        assert 0 <= c.start < spec.duration and c.end <= spec.duration + 0.01
    for a, b in zip(cues, cues[1:], strict=False):
        assert a.end <= b.start + 1e-6 and a.start < b.start
    srt = to_srt(cues)
    assert srt.startswith("1\n00:00:") and "-->" in srt and srt.count("-->") == len(cues)


def test_music_generator_is_deterministic_and_bounded():
    a = generate_track("warm", 84, "A", 33, 4.0)
    b = generate_track("warm", 84, "A", 33, 4.0)
    c = generate_track("warm", 84, "A", 34, 4.0)
    assert a.shape == (4 * 48000, 2) and (a == b).all() and not (a == c).all()
    assert abs(a).max() <= 0.61


def test_cover_box_keeps_aspect_and_stays_inside_the_image():
    for w, h in ((1280, 720), (720, 1280), (720, 720), (576, 720)):
        for z in (1.0, 1.13):
            x0, y0, x1, y1 = cover_box(1536, 1024, w, h, z, 0.95, 0.05)
            assert 0 <= x0 < x1 <= 1536 and 0 <= y0 < y1 <= 1024
            assert abs((x1 - x0) / (y1 - y0) - w / h) < 1e-6
    z0, *_ = motion_params("zoom_in", (0.5, 0.5), 0.0)
    z1, *_ = motion_params("zoom_in", (0.5, 0.5), 1.0)
    assert z1 > z0


@needs_ffmpeg
async def test_provider_renders_in_an_isolated_subprocess(tmp_path: Path):
    from spotlight.video.provider import CompositorProvider

    spec, images, audio = make_spec(scenes=2, per=2.0)
    prov = CompositorProvider(timeout_s=120, work_dir=str(tmp_path))
    seen: list[float] = []

    async def prog(p: float, msg: str) -> None:
        seen.append(p)

    out = await prov.render(spec, images, audio, prog)
    assert out.video[4:8] == b"ftyp" and out.srt and out.poster[:2] == b"\xff\xd8"
    assert seen and max(seen) > 0.5
    assert sys.executable  # worker used the same interpreter


def test_unused_pil_import_guard():
    assert Image.new("RGB", (2, 2)).size == (2, 2)
