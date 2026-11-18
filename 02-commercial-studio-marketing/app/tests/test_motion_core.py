"""Cinematic motion — the pure core: plan maths, prompts, the wire contract (job-id golden vectors), pricing, settings and the procedural stub animator."""

from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import needs_ffmpeg
from spotlight.config import Settings
from spotlight.core.ai import pricing
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.motion import animator, plan, prompts, wire
from spotlight.motion.models import NEGATIVE_PROMPT, MotionBadRequest, MotionRequest
from spotlight.motion.orchestrator import crop_keyframe
from spotlight.motion.stub_client import StubMotionClient
from spotlight.video import media
from spotlight.video.renderer import cover_box
from spotlight.video.spec import RenderSpec, SceneSpec

ROOT = Path(__file__).resolve().parents[2]


def keyframe(seed: int = 3, size: tuple[int, int] = (960, 640)) -> bytes:
    buf = io.BytesIO()
    render_stub_scene("dawn", size, None, seed).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def decode_frames(clip: bytes, tmp_path: Path, w: int, h: int) -> np.ndarray:
    path = tmp_path / "c.mp4"
    path.write_bytes(clip)
    raw = subprocess.run([media.FFMPEG, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


# ------------------------------------------------------------------------------------------------ plan maths


@pytest.mark.parametrize(("needed", "frames"), [(0.5, 25), (3.87, 93), (4.77, 117), (5.0, 121), (9.0, 121), (1.04, 25), (1.05, 29)])
def test_frames_are_4n_plus_1_rounded_up_and_clamped_to_25_121(needed, frames):
    got = plan.frames_for(needed)
    assert got == frames and got % 4 == 1 and 25 <= got <= 121 and got / 24 >= min(needed, 121 / 24) - 1e-9


def test_a_scene_needs_its_duration_plus_a_dissolve_and_a_margin_and_long_scenes_are_slowed_then_held():
    short = plan.timing_for(3.3)
    assert short.needed_s == pytest.approx(3.87) and short.frames == 93 and short.speed == 1.0 and not short.hold_tail
    edge = plan.timing_for(4.4)  # needs 4.97 s: still fits in the longest clip
    assert edge.frames == 121 and edge.speed == 1.0 and not edge.hold_tail
    slow = plan.timing_for(5.5)  # needs 6.07 s > 5.04 s: slow motion, no hold
    assert slow.frames == 121 and 1 / 1.35 <= slow.speed < 1.0 and not slow.hold_tail
    assert 121 / 24 / slow.speed == pytest.approx(slow.needed_s, abs=0.05)
    long = plan.timing_for(9.0)  # beyond 6.8 s even the slowest slow motion runs out: hold the last frame and keep pushing
    assert long.speed == pytest.approx(1 / 1.35, abs=1e-3) and long.hold_tail


def test_native_size_per_aspect_and_the_high_setting():
    assert [plan.resolution_for(a) for a in ("16:9", "9:16", "1:1", "4:5")] == [(1024, 576), (576, 1024), (768, 768), (640, 800)]
    assert plan.resolution_for("16:9", high=True) == (1280, 704) and plan.resolution_for("9:16", high=True) == (576, 1024)
    for w, h in [*plan.RESOLUTIONS.values(), *plan.HIGH_RESOLUTIONS.values()]:
        assert w % 32 == 0 and h % 32 == 0 and w * h <= 1280 * 704  # what the worker accepts


def test_seed_is_deterministic_per_campaign_shot_and_prompt_and_fits_24_bits():
    a = plan.shot_seed("c1", "s1", "a hand lifts the mug")
    assert a == plan.shot_seed("c1", "s1", "a hand lifts the mug") and 0 <= a < 2**24
    assert len({a, plan.shot_seed("c2", "s1", "a hand lifts the mug"), plan.shot_seed("c1", "s2", "a hand lifts the mug"), plan.shot_seed("c1", "s1", "another prompt")}) == 4


def test_cache_key_ignores_the_length_but_not_what_makes_the_pixels():
    base = {"model": "m", "revision": "r", "prompt": "p", "negative": "n", "keyframe_sha": "k", "width": 1024, "height": 576, "focal": (0.5, 0.5), "seed": 7, "steps": 20, "guidance": 4.0}
    key = plan.cache_key(**base)
    assert key == plan.cache_key(**base) and len(key) == 32
    for field, value in {"prompt": "q", "keyframe_sha": "z", "width": 1280, "focal": (0.4, 0.5), "seed": 8, "steps": 12, "guidance": 5.0, "revision": "r2", "model": "m2"}.items():
        assert plan.cache_key(**{**base, field: value}) != key, field


def test_gpu_estimate_reproduces_the_calibration_on_the_real_a100():
    assert pricing.motion_estimate(73, 1024, 576, 20) == pytest.approx(58.4, abs=0.1)  # measured 55 s
    assert pricing.motion_estimate(109, 1024, 576, 20) == pytest.approx(87.2, abs=0.1)  # measured 88 s
    assert pricing.motion_estimate(73, 1024, 576, 12) == pytest.approx(37.96, abs=0.1)  # measured 38 s
    assert pricing.motion_estimate(73, 1280, 704, 20) == pytest.approx(89.2, abs=2.0)  # measured 92 s
    assert pricing.motion_estimate(73, 576, 1024, 20) == pytest.approx(pricing.motion_estimate(73, 1024, 576, 20))  # the same number of pixels
    assert pricing.MOTION_USD_PER_GPU_SECOND == 0.00108 and pricing.motion_cost(100) == pytest.approx(0.108) and pricing.motion_cost(-5) == 0.0
    assert pricing.motion_cost(10, 0.002) == pytest.approx(0.02)


def spec_with(scenes: list[tuple[str, float]], aspect: str = "16:9") -> RenderSpec:
    return RenderSpec(id="sp", campaign_id="camp", aspect=aspect, scenes=[SceneSpec(id=f"sc-{n}", shot_id=n, asset_id=f"a-{n}", duration=d, role="hook", motion="zoom_in", focal=(0.5, 0.55)) for n, d in scenes])  # type: ignore[arg-type]


def test_plan_motion_gives_every_scene_a_clip_size_frames_seed_key_and_estimate():
    storyboard = {"shots": [{"id": "s1", "role": "hook", "opening_en": "A kitchen at dawn.", "motion": {"prompt_en": "A hand lifts the mug.", "camera": "slow push-in"}, "movement": "zoom_in"}], "style_bible_en": {"lighting": "Warm."}}
    settings = Settings(spotlight_mode="offline")
    p = plan.plan_motion(spec_with([("s1", 3.3), ("s2", 4.2)]), storyboard, settings, model="wan2.2-ti2v-5b", revision="rev", license_name="Apache-2.0", keyframe_sha={"a-s1": "11", "a-s2": "22"}, campaign_id="camp")
    assert [s.shot_id for s in p.shots] == ["s1", "s2"] and [s.frames for s in p.shots] == [93, 117]
    s1 = p.shots[0]
    assert (s1.width, s1.height) == (1024, 576) and s1.steps == 20 and s1.guidance == 4.0 and "A hand lifts the mug." in s1.prompt and s1.negative == NEGATIVE_PROMPT
    assert s1.seed == plan.shot_seed("camp", "s1", s1.prompt) and len(s1.cache_key) == 32 and s1.cache_key != p.shots[1].cache_key
    assert s1.est_gpu_seconds == pytest.approx(pricing.motion_estimate(93, 1024, 576, 20), abs=0.01) and s1.est_cost_usd == pytest.approx(s1.est_gpu_seconds * 0.00108, abs=1e-4)
    assert p.est_gpu_seconds == pytest.approx(sum(s.est_gpu_seconds for s in p.shots)) and p.seed_base == plan.seed_base("camp")
    nine = plan.plan_motion(spec_with([("s1", 3.3)], "9:16"), storyboard, settings, model="m", revision="r")
    assert (nine.shots[0].width, nine.shots[0].height) == (576, 1024)
    assert plan.plan_motion(spec_with([("s1", 3.3)]), storyboard, Settings(spotlight_mode="offline", motion_high=True, motion_steps=12), model="m", revision="r").shots[0].width == 1280


def test_a_recipe_stored_on_the_spec_wins_over_the_storyboard_so_a_re_render_asks_for_the_same_clips():
    settings = Settings(spotlight_mode="offline")
    first = plan.plan_motion(spec_with([("s1", 3.3)]), None, settings, model="m", revision="r", keyframe_sha={"a-s1": "k"}, campaign_id="camp")
    spec = spec_with([("s1", 3.3)])
    spec.motion = first.recipe("stub")
    edited = {"shots": [{"id": "s1", "role": "hook", "motion": {"prompt_en": "Something completely different."}}]}
    again = plan.plan_motion(spec, edited, Settings(spotlight_mode="offline", motion_steps=30), model="m", revision="r", keyframe_sha={"a-s1": "k"}, campaign_id="camp")
    assert again.shots[0].prompt == first.shots[0].prompt and again.shots[0].seed == first.shots[0].seed and again.shots[0].cache_key == first.shots[0].cache_key and again.steps == 20


def test_wall_time_adds_the_cold_start_generation_overhead_and_the_composite():
    p = plan.plan_motion(spec_with([("s1", 3.3), ("s2", 3.3)]), None, Settings(spotlight_mode="offline"), model="m", revision="r")
    warm = plan.wall_seconds(p.shots)
    assert warm == pytest.approx(sum(s.est_gpu_seconds + plan.GENERATE_OVERHEAD_S for s in p.shots) + plan.COMPOSITE_S, abs=0.2)
    assert plan.wall_seconds(p.shots, 240) == pytest.approx(warm + 240, abs=0.2) and plan.wall_seconds([]) == plan.COMPOSITE_S


# ------------------------------------------------------------------------------------------------ prompts


def test_motion_prompt_says_what_moves_adds_the_camera_the_style_and_the_product_safety_suffix():
    shot = {"opening_en": "Pre-dawn kitchen.", "framing_en": "wide shot", "motion": {"prompt_en": "A hand lifts the mug."}, "role": "hook", "movement": "zoom_in"}
    text = prompts.build_motion_prompt(shot, {"lighting": "Low warm light."}, "hook", "zoom_in")
    assert "A hand lifts the mug." in text and "Camera: slow push-in." in text and "Lighting: Low warm light." in text and "Pre-dawn kitchen." in text and "Framing: wide shot." in text
    assert text.endswith("Style: realistic cinematic commercial footage, natural motion, shallow depth of field. Constraints: the product packaging stays unchanged and legible, no text overlays.")
    assert prompts.STYLE_SUFFIX in text and prompts.PRODUCT_SAFETY in text
    assert [prompts.camera_phrase(m) for m in ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax")] == [
        "slow push-in", "slow pull-back", "gentle truck left", "gentle truck right", "slow tilt up", "slow tilt down", "subtle parallax drift"]
    assert "text" in NEGATIVE_PROMPT and "watermark" in NEGATIVE_PROMPT and "collage" in NEGATIVE_PROMPT


def test_legacy_storyboards_without_motion_fields_still_get_a_sensible_prompt_from_description_framing_and_movement():
    shot = {"description": "Slow pour into a ceramic cup; golden light crosses the counter.", "framing": "macro close-up", "role": "proof", "movement": "parallax"}
    text = prompts.build_motion_prompt(shot, None, "proof", "parallax")
    dm = prompts.default_motion("proof")
    assert "Slow pour into a ceramic cup" in text and "Framing: macro close-up." in text and "Camera: subtle parallax drift." in text and dm[0].upper() + dm[1:] in text
    assert prompts.build_motion_prompt({}, None, None, None).startswith(prompts.GENERIC_MOTION[0].upper() + prompts.GENERIC_MOTION[1:])


def test_a_hand_edited_or_overlong_motion_prompt_never_blows_the_length_budget_and_the_motion_survives():
    shot = {"opening_en": "x" * 800, "framing_en": "y" * 200, "motion": {"prompt_en": "A hand lifts the mug. " * 40}}
    text = prompts.build_motion_prompt(shot, {"lighting": "z" * 400}, "hook", "zoom_in")
    assert len(text) <= prompts.MAX_PROMPT_CHARS and "A hand lifts the mug." in text and "Camera: slow push-in." in text and text.endswith("no text overlays.")


# ------------------------------------------------------------------------------------------------ wire contract


VECTORS = [  # contracts/job-id-vectors.json (Agent W): every implementation must reproduce these
    ({"model": "wan2.2-ti2v-5b", "revision": "b8fff7315c768468a5333511427288870b2e9635", "prompt": "A hand gently lifts the speckled ceramic mug; steam rises; slow cinematic push-in.", "negative": "blurry, distorted, text, watermark",
      "width": 1024, "height": 576, "num_frames": 93, "fps": 24, "steps": 20, "guidance": 4.0, "seed": 123456, "image_sha256": "830e4d0a125dc83c76a53baf8f2c6c1408e90145151e3b1636f73116c44545aa"},
     "mj_380b932f37f39c944afce70d"),
    ({"model": "wan2.2-ti2v-5b", "revision": "b8fff7315c768468a5333511427288870b2e9635", "prompt": "Dłoń unosi kubek | para wznosi się\\ powoli — zbliżenie 🎬", "negative": "",
      "width": 768, "height": 768, "num_frames": 25, "fps": 24, "steps": 12, "guidance": 3.5, "seed": 4294967295, "image_sha256": "e946bc689b60488d3709a245c74edbe947b738631710723062041beb8e401ec8"},
     "mj_7312d03e1865eeb0c0d6cfc6"),
    ({"model": "wan2.2-ti2v-5b", "revision": "b8fff7315c768468a5333511427288870b2e9635", "prompt": "Slow truck left across the counter.", "negative": "a|b",
      "width": 576, "height": 1024, "num_frames": 121, "fps": 24, "steps": 40, "guidance": 7.123456789, "seed": 0, "image_sha256": "3501e4bdb6ff91eb3777744c93a2b68ce91ad0f3431fafbfa4aa624afcf1d409"},
     "mj_04cc9e66b42e6b872d7ceb09"),
]


@pytest.mark.parametrize(("inputs", "job_id"), VECTORS)
def test_job_id_reproduces_the_golden_vectors_of_the_worker_contract(inputs, job_id):
    assert wire.compute_job_id(**inputs) == job_id


def _vector_args(v: dict) -> dict:
    i = v["inputs"]
    return {"model": i["model"], "revision": i["revision"], "prompt": i["prompt"], "negative": i["negative_prompt"], "width": i["width"], "height": i["height"], "num_frames": i["num_frames"], "fps": i["fps"], "steps": i["steps"], "guidance": i["guidance_scale"], "seed": i["seed"], "image_sha256": i["image_sha256"]}


def test_job_id_matches_the_contract_file_when_the_repo_checkout_has_it():
    path = ROOT / "contracts" / "job-id-vectors.json"
    if not path.is_file():
        pytest.skip("contracts/ is not part of this checkout (the golden vectors above are the copy that always runs)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    embedded = {job_id: inputs for inputs, job_id in VECTORS}
    for v in doc["vectors"]:
        args = _vector_args(v)
        assert wire.canonical_job_string(**args) == v["canonical"], v["name"]
        assert wire.compute_job_id(**args) == v["job_id"], v["name"]
        assert embedded.get(v["job_id"]) == args, f"{v['name']}: the vector copy in this test file is out of date"


def test_job_id_changes_with_every_input_and_is_stable_otherwise():
    base = VECTORS[0][0]
    ids = {wire.compute_job_id(**{**base, k: v}) for k, v in {"prompt": "x", "width": 1280, "seed": 1, "steps": 21, "guidance": 4.5, "image_sha256": "0" * 64, "revision": "r", "num_frames": 97}.items()}
    assert len(ids) == 8 and wire.compute_job_id(**base) not in ids and re.fullmatch(r"mj_[0-9a-f]{24}", next(iter(ids)))


def make_request(**kw) -> MotionRequest:
    return MotionRequest(**{"prompt": "A hand lifts the mug.", "image": keyframe(), "width": 1024, "height": 576, "num_frames": 93, "seed": 5, **kw})


def test_request_document_follows_the_schema_and_carries_the_job_id_revision_and_image_hash():
    req = make_request(campaign_id="camp", shot_id="s1")
    doc = req.to_wire("2026-11-18T18:00:00Z")
    assert req.job_id == doc["job_id"] and re.fullmatch(r"mj_[0-9a-f]{24}", doc["job_id"])
    assert doc["v"] == 1 and doc["model"] == "wan2.2-ti2v-5b" and doc["model_revision"] == wire.MODEL_REVISION and doc["image"] == "image.jpg" and doc["image_sha256"] == req.image_sha256
    assert {"prompt", "negative_prompt", "width", "height", "num_frames", "fps", "steps", "guidance_scale", "seed", "campaign_id", "shot_id", "created_at"} <= set(doc) and doc["fps"] == 24 and doc["guidance_scale"] == 4.0
    assert "campaign_id" not in make_request().to_wire() and make_request(image_mime="image/png").to_wire()["image"] == "image.png"


@pytest.mark.parametrize(
    "bad",
    [{"width": 1000}, {"num_frames": 92}, {"num_frames": 123}, {"fps": 25}, {"steps": 7}, {"guidance_scale": 9.0}, {"seed": -1}, {"seed": 2**32}, {"prompt": "  "}, {"width": 1536, "height": 1024}, {"image": b""}],
)
def test_requests_that_the_worker_would_reject_are_refused_before_anything_is_queued(bad):
    with pytest.raises(MotionBadRequest):
        make_request(**bad).validate()
    make_request().validate()
    make_request(width=1280, height=704).validate()


def test_worker_readiness_is_read_from_the_heartbeat():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 11, 18, 18, 0, tzinfo=UTC)
    fresh = {"state": "ready", "updated_at": wire.utc_iso(now - timedelta(seconds=40)), "model": "m", "model_revision": "r", "replica": "x"}
    assert wire.WorkerReady.from_doc(fresh, now).state == "ready" and wire.WorkerReady.from_doc(fresh, now).age_s == 40
    assert wire.WorkerReady.from_doc({**fresh, "updated_at": wire.utc_iso(now - timedelta(seconds=151))}, now).state == "cold"  # stale heartbeat: the worker is gone
    assert wire.WorkerReady.from_doc({**fresh, "state": "loading"}, now).state == "loading"
    assert wire.WorkerReady.from_doc(None).state == "cold" and wire.WorkerReady.from_doc({"state": "ready"}).state == "cold"
    assert wire.queue_message("generate", "mj_" + "0" * 24) == {"v": 1, "type": "generate", "job_id": "mj_" + "0" * 24}
    with pytest.raises(ValueError):
        wire.decode("[1]")


# ------------------------------------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    ("kw", "mode"),
    [
        ({}, "stub"),  # offline default
        ({"motion_mode": "off"}, "off"),
        ({"motion_mode": "stub"}, "stub"),
        ({"motion_mode": "local"}, "off"),  # local needs a directory
        ({"motion_mode": "local", "motion_local_dir": "x"}, "local"),
        ({"motion_mode": "azure"}, "off"),  # azure needs the queue
        ({"motion_mode": "azure", "motion_queue_url": "https://q", "motion_blob_account_url": "https://b"}, "azure"),
        ({"spotlight_mode": "azure"}, "off"),  # azure deployment without the GPU worker configured: cinematic is not offered (never the offline simulator)
        ({"spotlight_mode": "azure", "motion_queue_url": "https://q", "blob_account_url": "https://b"}, "azure"),
    ],
)
def test_motion_mode_resolution(kw, mode):
    assert Settings(**{"spotlight_mode": "offline", **kw}).motion_effective_mode == mode


# ------------------------------------------------------------------------------------------------ the keyframe crop


def test_crop_keyframe_frames_the_clip_around_the_focal_point_not_blindly_on_the_centre():
    # a 3:2 keyframe whose subject (a bright stripe) sits on the left: a blind centre-crop to 9:16 would cut it out, the focal point keeps it in view
    img = Image.new("RGB", (1536, 1024), (30, 30, 30))
    img.paste((250, 250, 250), (200, 0, 300, 1024))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    png = buf.getvalue()
    on_subject = np.asarray(Image.open(io.BytesIO(crop_keyframe(png, 576, 1024, (0.16, 0.5)))))
    centred = np.asarray(Image.open(io.BytesIO(crop_keyframe(png, 576, 1024, (0.5, 0.5)))))
    assert on_subject.shape == centred.shape == (1024, 576, 3) and on_subject.max() > 200 and centred.max() < 80
    # the window is exactly the compositor's own crop for the still path (cover_box at zoom 1.0), Lanczos-resized to the clip size
    for focal in ((0.0, 0.5), (0.16, 0.5), (0.5, 0.5), (0.9, 0.3), (1.0, 1.0)):
        for w, h in ((576, 1024), (1024, 576), (768, 768), (640, 800)):
            got = np.asarray(Image.open(io.BytesIO(crop_keyframe(png, w, h, focal)))).astype(int)
            want = np.asarray(img.resize((w, h), Image.Resampling.LANCZOS, box=cover_box(1536, 1024, w, h, 1.0, *focal))).astype(int)
            assert got.shape == (h, w, 3) and np.abs(got - want).mean() < 2.0, (focal, w, h)
    jpg = crop_keyframe(png, 1024, 576, (0.5, 0.5))
    assert jpg[:2] == b"\xff\xd8" and Image.open(io.BytesIO(jpg)).size == (1024, 576) and jpg == crop_keyframe(png, 1024, 576, (0.5, 0.5))  # JPEG, exact size, deterministic bytes (the job id hashes them)


# ------------------------------------------------------------------------------------------------ the procedural animator (offline stand-in for the model)


@needs_ffmpeg
def test_the_stub_animator_makes_a_real_moving_clip_with_the_requested_size_frames_and_fps(tmp_path: Path):
    clip = animator.animate(keyframe(), 512, 288, 49, 24, seed=11)
    info = media.probe(_write(tmp_path / "a.mp4", clip))
    assert info["video"]["codec"] == "h264" and (info["video"]["width"], info["video"]["height"]) == (512, 288) and info["video"]["fps"] == 24.0 and info["audio"] is None
    frames = decode_frames(clip, tmp_path, 512, 288)
    assert len(frames) == 49
    steps = [float(np.abs(frames[i + 1].astype(int) - frames[i].astype(int)).mean()) for i in range(len(frames) - 1)]
    assert 0.05 < min(steps) and max(steps) < 6.0 and np.mean(steps) > 0.3  # every frame changes, none of them jumps
    assert float(np.abs(frames[0].astype(int) - frames[-1].astype(int)).mean()) > 4.0  # the shot has travelled: first is not last
    assert float(np.abs(frames[20].astype(int) - frames[22].astype(int)).mean()) > 0.3
    assert frames[:, :6, :6].min() > 5  # the camera never leaves the picture: no black wedges at the corners


@needs_ffmpeg
def test_the_stub_animator_is_deterministic_per_seed_and_image_and_different_across_seeds(tmp_path: Path):
    a = decode_frames(animator.animate(keyframe(), 256, 144, 25, 24, seed=1), tmp_path, 256, 144)
    b = decode_frames(animator.animate(keyframe(), 256, 144, 25, 24, seed=1), tmp_path, 256, 144)
    c = decode_frames(animator.animate(keyframe(), 256, 144, 25, 24, seed=2), tmp_path, 256, 144)
    assert np.array_equal(a[12], b[12]) and not np.array_equal(a[12], c[12])
    assert not np.array_equal(a[12], decode_frames(animator.animate(keyframe(7), 256, 144, 25, 24, seed=1), tmp_path, 256, 144)[12])


async def test_stub_client_honours_the_request_reports_simulated_gpu_seconds_and_progress():
    client = StubMotionClient()
    seen = []

    async def on_progress(p):
        seen.append((p.state, p.progress))

    req = make_request(width=320, height=256, num_frames=29)
    res = await client.generate(req, on_progress)
    assert (res.width, res.height, res.num_frames, res.fps, res.seed) == (320, 256, 29, 24, 5) and res.clip[4:8] == b"ftyp" and not res.cached and res.provider == "stub"
    assert res.gpu_seconds == pytest.approx(pricing.motion_estimate(29, 320, 256, 20), abs=0.01) and res.job_id == req.job_id
    assert seen[0][0] == "running" and seen[-1][1] == 1.0 and client.calls == 1
    st = await client.status()
    assert (st.state, st.queue_depth) == ("ready", 0) and (await client.warmup()).state == "ready"
    assert client.model == "spotlight-stub-animator" and "no generative model" in client.license  # honest: the offline simulator never claims to be Wan
    with pytest.raises(MotionBadRequest):
        await client.generate(make_request(num_frames=30))


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path
