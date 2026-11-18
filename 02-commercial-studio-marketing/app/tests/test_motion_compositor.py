"""Cinematic motion — the compositor side: how a generated clip plays inside its scene (24 -> 25 fps retiming, slow motion, holding the last frame, falling back
to the keyframe) and what a cinematic render adds (film grain) — which a preview never gets."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import needs_ffmpeg
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.motion import animator
from spotlight.video import media, renderer
from spotlight.video.renderer import GRAIN_SIGMA, TD, ClipSceneRenderer, SceneRenderer, _grain, render
from spotlight.video.spec import ClipSpec
from test_compositor import make_spec

W, H = 320, 192


def keyframe() -> Image.Image:
    return render_stub_scene("dawn", (960, 640), None, 4)


@pytest.fixture(scope="module")
def clip_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    buf = io.BytesIO()
    keyframe().save(buf, "JPEG", quality=90)
    path = tmp_path_factory.mktemp("clip") / "clip.mp4"
    path.write_bytes(animator.animate(buf.getvalue(), W, H, 49, 24, 7))  # 2.04 s at 24 fps
    return path


def player(clip_path: Path, tmp_path: Path, *, w: int = W, h: int = H, focal: tuple[float, float] = (0.5, 0.5), **clip: float | bool) -> ClipSceneRenderer:
    return ClipSceneRenderer(clip_path, ClipSpec(fps=24, frames=49, **clip), w, h, focal, tmp_path / "decoded")  # type: ignore[arg-type]


def px(frame: Image.Image) -> np.ndarray:
    return np.asarray(frame)


def diff(a: Image.Image, b: Image.Image) -> float:
    return float(np.abs(px(a).astype(int) - px(b).astype(int)).mean())


# ------------------------------------------------------------------------------------------------ playing a clip inside a scene


@needs_ffmpeg
def test_a_24_fps_clip_is_retimed_to_the_timeline_by_nearest_frame_and_is_already_moving_when_the_dissolve_starts(clip_path: Path, tmp_path: Path):
    r = player(clip_path, tmp_path)
    first = r.frame_at(-TD / 2, 2.0)  # the very start of the dissolve into the scene: clip time 0
    assert r._n == 49 and r._mm is not None
    assert np.array_equal(px(first), np.asarray(r._mm[0]))
    for t in (0.0, 0.5, 1.0, 1.6):
        idx = round((t + TD / 2) * 24)
        assert np.array_equal(px(r.frame_at(t, 2.0)), np.asarray(r._mm[idx])), t
    assert diff(r.frame_at(0.5, 2.0), r.frame_at(1.0, 2.0)) > 1.5  # the picture really moves (a still would be identical)
    assert diff(r.frame_at(0.0, 2.0), r.frame_at(0.04, 2.0)) > 0  # and moves from one 25 fps frame to the next
    r.close()


@needs_ffmpeg
def test_slow_motion_stretches_the_clip_over_more_of_the_scene(clip_path: Path, tmp_path: Path):
    slow = player(clip_path, tmp_path / "slow", speed=0.8)
    real = player(clip_path, tmp_path / "real")
    slow.frame_at(0, 2.0)
    real.frame_at(0, 2.0)
    assert slow._mm is not None and real._mm is not None
    assert np.array_equal(px(slow.frame_at(1.0, 2.0)), np.asarray(slow._mm[round((1.0 + TD / 2) * 0.8 * 24)]))
    assert diff(slow.frame_at(1.0, 2.0), real.frame_at(1.0, 2.0)) > 0  # the same moment shows an earlier part of the clip
    slow.close()
    real.close()


@needs_ffmpeg
def test_a_clip_that_ends_early_holds_its_last_frame_or_keeps_pushing_in_gently(clip_path: Path, tmp_path: Path):
    hold = player(clip_path, tmp_path / "hold")
    push = player(clip_path, tmp_path / "push", hold_tail=True)
    hold.frame_at(0, 3.0)
    push.frame_at(0, 3.0)
    assert hold._mm is not None
    last = np.asarray(hold._mm[-1])
    assert np.array_equal(px(hold.frame_at(2.9, 3.0)), last) and np.array_equal(px(hold.frame_at(3.2, 3.0)), last)  # frozen on the last frame
    near, far = push.frame_at(2.5, 3.0), push.frame_at(3.2, 3.0)
    assert 0 < diff(near, Image.fromarray(last)) < diff(far, Image.fromarray(last))  # the push keeps growing...
    assert np.array_equal(px(push.frame_at(1000, 3.0)), px(push.frame_at(2000, 3.0)))  # ...up to a cap (never a runaway zoom)
    assert far.size == (W, H)
    hold.close()
    push.close()


@needs_ffmpeg
def test_a_clip_of_another_aspect_is_cover_cropped_around_the_scene_focal_point(clip_path: Path, tmp_path: Path):
    left = player(clip_path, tmp_path / "l", w=108, h=192, focal=(0.0, 0.5))
    right = player(clip_path, tmp_path / "r", w=108, h=192, focal=(1.0, 0.5))
    a, b = left.frame_at(0.5, 2.0), right.frame_at(0.5, 2.0)
    assert a.size == b.size == (108, 192) and diff(a, b) > 3  # a 9:16 window on a 5:3 clip: which part is kept depends on the focal point
    left.close()
    right.close()


@needs_ffmpeg
def test_a_clip_that_cannot_be_decoded_plays_the_keyframe_instead_of_failing_the_render(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    still = keyframe()
    r = ClipSceneRenderer(bad, ClipSpec(fps=24, frames=49), W, H, (0.5, 0.5), tmp_path / "decoded", fallback=lambda: SceneRenderer(still, "zoom_in", (0.5, 0.5), W, H))
    frame = r.frame_at(0.5, 2.0)
    assert r.failed and frame.size == (W, H)
    assert np.array_equal(px(frame), px(SceneRenderer(still, "zoom_in", (0.5, 0.5), W, H).frame(0.25)))  # the Ken-Burns position for this moment of the scene
    assert r.frame_at(1.5, 2.0).size == (W, H)  # keeps playing the still without trying to decode again
    nothing = ClipSceneRenderer(bad, ClipSpec(fps=24, frames=49), W, H, (0.5, 0.5), tmp_path / "d2")
    with pytest.raises(media.MediaError):
        nothing.frame_at(0.0, 1.0)  # no keyframe to fall back on: a clear error


@needs_ffmpeg
def test_closing_deletes_the_decoded_frames_and_can_be_repeated(clip_path: Path, tmp_path: Path):
    r = player(clip_path, tmp_path)
    r.frame_at(0.2, 2.0)
    raw = r._raw
    assert raw is not None and raw.is_file() and raw.stat().st_size == 49 * W * H * 3
    r.close()
    assert not raw.exists() and r._mm is None
    r.close()
    assert r.frame_at(0.2, 2.0).size == (W, H)  # decoded again on demand
    r.close()


# ------------------------------------------------------------------------------------------------ film grain


def test_film_grain_is_subtle_luma_only_reproducible_and_never_frozen():
    flat = np.full((96, 160, 3), 128, np.uint8)
    g = _grain(flat, 7, 10)
    assert np.array_equal(g, _grain(flat, 7, 10))  # a re-render has the same grain
    assert not np.array_equal(g, _grain(flat, 7, 11)) and not np.array_equal(g, _grain(flat, 8, 10))  # it moves from frame to frame
    d = g.astype(float) - 128
    assert 1.0 < d.std() < 2.4 and abs(d.mean()) < 0.3
    assert np.array_equal(g[..., 0], g[..., 1]) and np.array_equal(g[..., 1], g[..., 2])  # luma grain: no colour speckle
    assert _grain(np.zeros((8, 8, 3), np.uint8), 1, 1).max() <= 8 and _grain(np.full((8, 8, 3), 255, np.uint8), 1, 1).min() >= 247  # no wrap-around at the ends
    assert np.array_equal(_grain(flat, 7, 10, 0.0), flat)  # faded out completely: untouched
    assert GRAIN_SIGMA < 2.5


# ------------------------------------------------------------------------------------------------ whole renders


@needs_ffmpeg
def test_a_cinematic_render_plays_the_clip_and_adds_grain_while_a_preview_never_does(clip_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec, images, audio = make_spec(scenes=2, per=2.0)
    calls: list[int] = []
    real = renderer._grain

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(renderer, "_grain", spy)
    render(spec, images, audio, tmp_path / "preview")
    assert calls == []  # previews are byte-for-byte what they were: no grain
    spec.quality = "cinematic"
    spec.scenes[0].clip_asset_id, spec.scenes[0].clip = "ast_clip", ClipSpec(fps=24, frames=49)
    out = render(spec, images, audio, tmp_path / "cinematic", clips={"s0": clip_path})
    assert len(calls) > 50
    v = media.probe(tmp_path / "cinematic" / "video.mp4")
    assert (v["video"]["width"], v["video"]["height"], v["video"]["codec"]) == (1280, 720, "h264") and abs(v["duration"] - spec.duration) <= 0.5
    assert abs(out["loudness"]["integrated_lufs"] - (-16.0)) <= 1.5 and (tmp_path / "cinematic" / "captions.srt").read_text()
    assert not list((tmp_path / "cinematic" / "_clips").glob("*.rgb"))  # the decoded frames are cleaned up
    t = 1.0  # the clip scene differs from the preview's Ken-Burns picture of the same moment: the clip really is on screen
    a, b = media.extract_frame(tmp_path / "preview" / "video.mp4", t), media.extract_frame(tmp_path / "cinematic" / "video.mp4", t)
    assert diff(Image.open(io.BytesIO(a)), Image.open(io.BytesIO(b))) > 2


@needs_ffmpeg
def test_a_scene_whose_clip_file_is_missing_renders_the_still_and_the_render_still_succeeds(tmp_path: Path):
    spec, images, audio = make_spec(scenes=2, per=1.5)
    spec.quality = "cinematic"
    spec.scenes[1].clip_asset_id, spec.scenes[1].clip = "ast_gone", ClipSpec(fps=24, frames=49)
    render(spec, images, audio, tmp_path / "out", clips={"s1": tmp_path / "does-not-exist.mp4"})
    assert media.probe(tmp_path / "out" / "video.mp4")["video"]["codec"] == "h264"
