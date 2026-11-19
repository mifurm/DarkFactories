"""Cinematic motion through the API (offline: the stub animator behind the real routers, job runner, compositor, Guardian, provenance and budget).

Delivery spec of a cinematic spot, the estimate / status / warm-up endpoints, the library cache, per-shot fallback, budget refusals, formats and localization."""

from __future__ import annotations

import contextlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import needs_cv2, needs_ffmpeg
from spotlight.app_factory import create_app
from spotlight.config import Settings
from spotlight.core.ai.base import SafetyResult
from spotlight.motion.client import OffMotionClient
from spotlight.motion.models import MotionFailed
from spotlight.video import media
from test_motion_orchestrator import ScriptedClient, Stubborn
from test_pipeline_api import H, build_to_script

pytestmark = needs_ffmpeg
PL = {"X-UI-Lang": "pl"}
STATUS_KEYS = {"mode", "available", "model", "license", "worker", "price_per_gpu_second", "est_cold_start_s", "max_clip_s", "revision", "host", "steps", "high", "reason"}
ESTIMATE_KEYS = {"quality", "aspect", "shots", "cached_shots", "est_gpu_seconds", "est_cost_usd", "est_wall_seconds", "cold_start_seconds", "budget"}  # spec 4.4
ESTIMATE_EXTRA = {"cold_start_cost_usd", "available", "mode", "model", "license", "max_retry_extra_usd"}


@pytest.fixture(scope="module")
def api():
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    with TestClient(app) as c:
        yield c


@contextlib.contextmanager
def motion_client(api: TestClient, client: Any):
    services = api.app.state.services
    previous, services.motion = services.motion, client
    try:
        yield client
    finally:
        services.motion = previous


def produce(api: TestClient, duration: int) -> str:
    """A campaign with everything a render needs for a spot of ``duration`` seconds: script, storyboard keyframes, voice-over."""
    cid = build_to_script(api)
    script = next(s for s in api.get(f"/api/campaigns/{cid}/script").json()["scripts"] if s["duration_s"] == duration)
    assert api.post(f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": script["id"], "auto_revise": True}, headers=H("creative")).json()["converged"]
    assert api.post(f"/api/campaigns/{cid}/storyboard/generate?wait=true", json={"script_id": script["id"]}, headers=H("creative")).status_code == 200
    sb = api.get(f"/api/campaigns/{cid}/storyboard").json()["latest"]
    assert api.post(f"/api/campaigns/{cid}/storyboard/{sb['id']}/frames?wait=true", json={"quality": "low"}, headers=H("creative")).status_code == 200
    assert api.post(f"/api/campaigns/{cid}/audio/generate?wait=true", json={"script_id": script["id"]}, headers=H("creative")).status_code == 200
    return cid


def render(api: TestClient, cid: str, headers: dict[str, str] | None = None, **body: Any):
    return api.post(f"/api/campaigns/{cid}/spot/render?wait=true", json=body, headers=headers or H("creative"))


def spots(api: TestClient, cid: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    return api.get(f"/api/campaigns/{cid}/spot", headers=headers).json()["spots"]


def clip_assets(api: TestClient, cid: str) -> list[dict[str, Any]]:
    return api.get("/api/library/assets", params={"campaign_id": cid, "tag": "motion-clip", "limit": 200}).json()["assets"]


def frame(path: Path, t: float) -> Image.Image:
    return Image.open(io.BytesIO(media.extract_frame(path, t)))


def diff_images(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute difference per pixel and channel (0..255): zero for identical pictures."""
    return float(np.abs(np.asarray(a.convert("RGB")).astype(int) - np.asarray(b.convert("RGB")).astype(int)).mean())


@pytest.fixture(scope="module")
def produced(api: TestClient) -> str:
    """The 15 s campaign: a preview master first (the baseline), then the tests render the cinematic one."""
    cid = produce(api, 15)
    r = render(api, cid)
    assert r.status_code == 200, r.text
    return cid


@pytest.fixture(scope="module")
def cinematic(api: TestClient, produced: str) -> dict[str, Any]:
    r = render(api, produced, quality="cinematic")
    assert r.status_code == 200, r.text
    return r.json()["result"]


# ------------------------------------------------------------------------------------------------ the delivered spot


def test_a_cinematic_spot_meets_the_delivery_spec_and_its_footage_really_moves(api: TestClient, produced: str, cinematic: dict[str, Any], tmp_path: Path):
    assert cinematic["quality"] == "cinematic" and abs(cinematic["duration"] - 15.0) <= 0.5 and abs(cinematic["loudness_lufs"] - (-16.0)) <= 1.5
    assert cinematic["guardian"]["verdict"] in {"pass", "warn"}
    m = cinematic["motion"]
    assert (m["mode"], m["shots_total"], m["shots_generated"], m["shots_cached"], m["shots_fallback"]) == ("stub", 3, 3, 0, [])
    spot = next(s for s in spots(api, produced) if s["id"] == cinematic["artifact_id"])
    video = tmp_path / "cinematic.mp4"
    video.write_bytes(api.get(f"/api/library/assets/{spot['assets']['video']}/content").content)
    info = media.probe(video)
    assert (info["video"]["codec"], info["video"]["width"], info["video"]["height"], info["video"]["fps"]) == ("h264", 1280, 720, 25.0) and info["audio"]["codec"] == "aac"
    assert abs(info["duration"] - 14.9) <= 0.5 and abs(media.measure_loudness(video)["integrated_lufs"] - (-16.0)) <= 1.5
    detail = api.get(f"/api/campaigns/{produced}/spot/{spot['id']}").json()
    assert detail["spec"]["disclosure_badge"]  # real generative video always carries the AI badge
    assert "-->" in api.get(f"/api/library/assets/{spot['assets']['srt']}/content").text and spot["assets"]["poster"]
    for t in (1.0, 2.5, 4.0, 5.5, 7.0, 8.5):  # inside the scenes: no frozen stretch of 0.6 s anywhere
        assert diff_images(frame(video, t), frame(video, t + 0.6)) > 2.0, t


def test_every_clip_is_a_library_asset_that_moves_and_has_the_native_size(api: TestClient, produced: str, cinematic: dict[str, Any], tmp_path: Path):
    clips = clip_assets(api, produced)
    assert len(clips) == 3 and all(c["kind"] == "video" and c["meta"]["motion_key"] and (c["meta"]["width"], c["meta"]["height"]) == (1024, 576) and c["meta"]["frames"] >= 25 for c in clips)
    for c in clips:
        path = tmp_path / f"{c['id']}.mp4"
        path.write_bytes(api.get(f"/api/library/assets/{c['id']}/content").content)
        assert diff_images(frame(path, 0.5), frame(path, 1.1)) > 3.0  # the clip itself, without overlays or dissolves


def test_the_spot_list_and_detail_say_how_it_was_made(api: TestClient, produced: str, cinematic: dict[str, Any]):
    listing = spots(api, produced)
    cin = next(s for s in listing if s["id"] == cinematic["artifact_id"])
    prev = next(s for s in listing if s["quality"] == "preview")
    assert cin["quality"] == "cinematic" and "motion" not in prev["render"]  # a preview spot is exactly what it was
    m = cin["render"]["motion"]
    assert {"mode", "model", "revision", "license", "host", "steps", "guidance", "shots_total", "shots_generated", "shots_cached", "shots_fallback", "gpu_seconds", "cost_usd", "cold_start_s", "shots"} <= set(m)
    assert [s["status"] for s in m["shots"]] == ["generated"] * 3 and all(s["seed"] and s["prompt_sha256"] and s["asset_id"] for s in m["shots"])
    detail = api.get(f"/api/campaigns/{produced}/spot/{cin['id']}").json()
    assert detail["quality"] == "cinematic" and detail["spec"]["quality"] == "cinematic" and len(detail["spec"]["motion"]["shots"]) == 3
    assert all(sc["clip_asset_id"] and sc["clip"]["frames"] >= 25 for sc in detail["spec"]["scenes"])
    assert detail["cost_usd"] < m["cost_usd"]  # the spot's own cost is the compositor's; the GPU time is reported under render.motion
    assert api.get(f"/api/campaigns/{produced}/spot/{prev['id']}").json()["quality"] == "preview"


@needs_cv2
def test_every_shot_says_how_much_it_moves_and_the_library_clips_remember_it(api: TestClient, produced: str, cinematic: dict[str, Any]):
    assert (cinematic["motion"]["shots_low_motion"], cinematic["motion"]["retries"]) == (0, 0)  # the job result carries the counts too
    m = next(s for s in spots(api, produced) if s["id"] == cinematic["artifact_id"])["render"]["motion"]
    assert (m["shots_low_motion"], m["retries"]) == (0, 0)
    for s in m["shots"]:
        assert set(s["motion"]) == {"non_rigid", "total", "level", "attempts"} and s["motion"]["level"] in {"subtle", "rich"} and s["motion"]["non_rigid"] >= 0.6 and s["motion"]["attempts"] == 1
        assert s["plan_prompt_sha256"] == s["prompt_sha256"]  # nothing was added to the prompt: the first attempt was good
    assert all(c["meta"]["motion_score"]["level"] in {"subtle", "rich"} and c["meta"]["attempts"] == 1 for c in clip_assets(api, produced))


def test_a_preview_render_is_unchanged_in_shape_and_never_touches_the_motion_backend(api: TestClient, produced: str):
    with motion_client(api, ScriptedClient()) as client:
        r = render(api, produced)
        assert r.status_code == 200
        res = r.json()["result"]
        assert set(res) == {"artifact_id", "video_asset_id", "duration", "loudness_lufs", "guardian", "render_seconds"}  # no quality / motion keys on a preview
        assert client.requests == [] and client.warmups == 0
    assert "motion" not in next(s for s in spots(api, produced) if s["id"] == res["artifact_id"])["render"]


def test_gpu_time_is_metered_as_its_own_kind_and_the_price_is_part_of_the_budget_overview(api: TestClient, produced: str, cinematic: dict[str, Any]):
    usage = api.get("/api/usage", params={"campaign_id": produced}).json()
    assert usage["by_kind"]["motion"]["calls"] >= 3 and usage["by_kind"]["motion"]["cost_usd"] > 0 and usage["simulated_prices"] is True  # offline: simulated, like every other stub
    overview = api.get("/api/budget").json()
    assert overview["pricing"]["motion_per_gpu_second"] == 0.00108 and "motion" in overview["today"]["by_kind"]
    events = [e for e in api.get("/api/budget/events", params={"campaign_id": produced}).json()["events"] if e["kind"] == "motion"]
    assert len(events) >= 3 and all(e["units"]["gpu_seconds"] >= 0 and e["campaign_id"] == produced for e in events)


# ------------------------------------------------------------------------------------------------ provenance and Guardian


def test_the_manifest_names_the_model_hashes_every_clip_and_verifies(api: TestClient, produced: str, cinematic: dict[str, Any]):
    vid = cinematic["video_asset_id"]
    doc = api.get(f"/api/provenance/assets/{vid}").json()
    a = doc["manifest"]["assertions"]
    gv = a["generative_video"]
    assert (gv["model"], gv["mode"], gv["shots_total"], gv["fallback_shots"]) == ("spotlight-stub-animator", "stub", 3, []) and gv["license"].startswith("n/a")
    assert all(s["seed"] and s["prompt_sha256"] and s["clip_sha256"] and s["cached"] is False for s in gv["shots"])
    clips = {c["id"]: c for c in clip_assets(api, produced)}
    ingredients = [i for i in a["ingredients"] if i["role"] == "motion-clip"]
    assert {i["asset_id"] for i in ingredients} == set(clips) and all(i["sha256"] == clips[i["asset_id"]]["sha256"] for i in ingredients)
    assert {"role": "video", "deployment": "spotlight-stub-animator"} in a["models"] and a["ai_disclosure"]["burned_in_badge"]
    assert doc["verification"]["ok"] and api.post("/api/provenance/verify", json={"asset_id": vid, "tamper_test": True}).json()["tamper_detected"] is True
    en = json.dumps(doc["summary"])
    assert "simulated offline" in en and "3 of 3 shots" in en
    pl = json.dumps(api.get(f"/api/provenance/assets/{vid}", headers=PL).json()["summary"], ensure_ascii=False)
    assert "zasymulowany" in pl and "3 z 3" in pl


def test_the_raw_clips_are_ingredients_not_deliverables_in_coverage_and_the_campaign_pack(api: TestClient, produced: str, cinematic: dict[str, Any]):
    cov = api.get(f"/api/provenance/campaigns/{produced}").json()
    assert cov["coverage"] == 100.0 and not any("motion-" in a["name"] for a in cov["assets"])
    r = api.post(f"/api/campaigns/{produced}/export?wait=true", headers=H("creative_director"))
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(api.get(f"/api/library/assets/{r.json()['result']['asset_id']}/content").content)).namelist()
    assert any(n.startswith("videos/spot-") for n in names) and not any("motion-" in n for n in names)


def test_the_guardian_reviews_the_cinematic_spot_and_finds_the_ai_label(api: TestClient, produced: str, cinematic: dict[str, Any]):
    r = api.post(f"/api/campaigns/{produced}/guardian/run", json={"artifact_id": cinematic["artifact_id"]}, headers=H("creative"))
    assert r.status_code == 200, r.text
    report = r.json()["report"]
    rules = {f["rule_id"] for f in report["findings"]}
    assert report["verdict"] in {"pass", "warn"} and not rules & {"disclosure.generative_video", "disclosure.video_model_missing"}  # the badge is on screen and the model is named


# ------------------------------------------------------------------------------------------------ status and warm-up


def test_motion_status_tells_the_ui_what_it_needs(api: TestClient):
    st = api.get("/api/motion/status").json()
    assert set(st) == STATUS_KEYS
    assert (st["mode"], st["available"], st["model"], st["reason"]) == ("stub", True, "spotlight-stub-animator", None) and st["worker"]["state"] == "ready" and st["license"].startswith("n/a")
    assert st["price_per_gpu_second"] == 0.00108 and st["max_clip_s"] == 5.0 and st["est_cold_start_s"] == 240 and set(st["worker"]) == {"state", "age_s", "queue_depth"}
    with motion_client(api, OffMotionClient("wan2.2-ti2v-5b")):
        off = api.get("/api/motion/status").json()
        assert (off["mode"], off["available"], off["reason"], off["model"]) == ("off", False, "off", "wan2.2-ti2v-5b")
        assert api.get("/api/features").json() and any(f["id"] == "CS-25" for f in api.get("/api/features").json())


def test_warmup_wakes_a_cold_worker_once_and_accounts_for_the_cold_start(api: TestClient):
    with motion_client(api, ScriptedClient(state="cold")) as client:
        assert api.get("/api/motion/status").json()["worker"]["state"] == "cold"
        r = api.post("/api/motion/warmup", headers=H("creative"))
        assert r.status_code == 202
        body = r.json()
        assert set(body) == STATUS_KEYS | {"warmup"} and body["warmup"]["requested"] is True and body["warmup"]["est_seconds"] == 240 and body["warmup"]["est_cost_usd"] > 0
        assert body["worker"]["state"] == "warming"
        again = api.post("/api/motion/warmup", headers=H("creative")).json()
        assert again["warmup"] == {"requested": False, "est_cost_usd": 0.0, "est_seconds": 0.0} and client.warmups == 1
    wake = [e for e in api.get("/api/budget/events", params={"limit": 300}).json()["events"] if e["kind"] == "motion" and e["units"].get("warmup")]
    assert len(wake) >= 1 and wake[0]["units"]["estimated"] is True


def test_warmup_needs_the_generate_permission_and_the_budget(api: TestClient):
    with motion_client(api, ScriptedClient(state="cold")) as client:
        assert api.post("/api/motion/warmup", headers=H("legal")).status_code == 403
        guard = api.app.state.services.guard
        cap, guard.daily_cap = guard.daily_cap, 0.01
        try:
            r = api.post("/api/motion/warmup", headers=H("creative"))
        finally:
            guard.daily_cap = cap
        assert r.status_code == 402 and r.json()["error"]["code"] == "daily_budget_exceeded"
        assert client.warmups == 0 and client.state == "cold"  # refused: the GPU was not woken


# ------------------------------------------------------------------------------------------------ the estimate


def test_the_estimate_prices_a_cinematic_render_before_it_runs(api: TestClient):
    cid = produce(api, 6)
    e = api.get(f"/api/campaigns/{cid}/spot/estimate", params={"quality": "cinematic"}).json()
    assert set(e) == ESTIMATE_KEYS | ESTIMATE_EXTRA and (e["quality"], e["aspect"], e["mode"], e["available"]) == ("cinematic", "16:9", "stub", True)
    (shot,) = e["shots"]
    assert set(shot) == {"shot_id", "seconds", "frames", "cached", "est_gpu_seconds", "est_cost_usd"} and shot["cached"] is False and shot["frames"] % 4 == 1 and shot["est_gpu_seconds"] > 0
    assert e["est_gpu_seconds"] == shot["est_gpu_seconds"] and e["est_cost_usd"] == round(e["est_gpu_seconds"] * 0.00108, 5) and e["cached_shots"] == 0
    assert e["max_retry_extra_usd"] == shot["est_cost_usd"]  # the estimate is for ONE attempt; a shot that barely moves gets one more: at most this much on top
    assert e["cold_start_seconds"] == 0 and e["est_wall_seconds"] > shot["est_gpu_seconds"] and e["budget"]["allowed"] is True and e["budget"]["reason"] is None
    assert e["budget"]["daily_remaining_usd"] > 0 and e["budget"]["campaign_remaining_usd"] > 0
    vertical = api.get(f"/api/campaigns/{cid}/spot/estimate", params={"quality": "cinematic", "aspect": "9:16"}).json()
    assert vertical["aspect"] == "9:16" and vertical["shots"][0]["frames"] == shot["frames"]
    free = api.get(f"/api/campaigns/{cid}/spot/estimate", params={"quality": "preview"}).json()
    assert set(free) == set(e) and (free["shots"], free["est_cost_usd"], free["est_gpu_seconds"], free["cold_start_seconds"], free["max_retry_extra_usd"]) == ([], 0.0, 0.0, 0, 0.0)
    assert api.get(f"/api/campaigns/{cid}/spot/estimate").json()["quality"] == "cinematic"  # the default: what the button is about


def test_the_estimate_knows_what_the_library_already_has(api: TestClient, produced: str, cinematic: dict[str, Any]):
    e = api.get(f"/api/campaigns/{produced}/spot/estimate", params={"quality": "cinematic"}).json()
    assert e["cached_shots"] == 3 and all(s["cached"] and s["est_cost_usd"] == 0.0 for s in e["shots"]) and e["est_cost_usd"] == 0.0 and e["est_gpu_seconds"] == 0.0 and e["max_retry_extra_usd"] == 0.0
    assert e["est_wall_seconds"] < 60  # only the compositor pass is left
    other = api.get(f"/api/campaigns/{produced}/spot/estimate", params={"quality": "cinematic", "aspect": "1:1"}).json()
    assert other["cached_shots"] == 0 and other["est_cost_usd"] > 0  # clips are native to one aspect: another aspect starts from scratch


def test_the_estimate_total_is_the_shot_rows_plus_the_cold_start(api: TestClient, produced: str):
    kw = {"quality": "cinematic", "aspect": "1:1"}  # nothing of this aspect is in the library yet: three shots to generate
    with motion_client(api, ScriptedClient(state="cold")):
        cold = api.get(f"/api/campaigns/{produced}/spot/estimate", params=kw).json()
    rows = round(sum(s["est_cost_usd"] for s in cold["shots"]), 5)
    assert len(cold["shots"]) == 3 and cold["cold_start_cost_usd"] > 0 and cold["est_cost_usd"] == pytest.approx(rows + cold["cold_start_cost_usd"], abs=1e-9)
    assert cold["max_retry_extra_usd"] == rows  # a second attempt would not wake the worker again: the cold start is not part of it
    assert cold["est_gpu_seconds"] == pytest.approx(sum(s["est_gpu_seconds"] for s in cold["shots"]) + cold["cold_start_seconds"], abs=0.011)
    ready = api.get(f"/api/campaigns/{produced}/spot/estimate", params=kw).json()
    assert ready["cold_start_cost_usd"] == 0 and ready["cold_start_seconds"] == 0 and ready["est_cost_usd"] == pytest.approx(sum(s["est_cost_usd"] for s in ready["shots"]), abs=1e-9)
    assert all(s["est_cost_usd"] == pytest.approx(s["est_gpu_seconds"] * 0.00108, abs=1e-5) for s in ready["shots"])  # a row reads the same in both columns


def test_the_estimate_adds_the_cold_start_and_refuses_what_the_budget_does_not_allow(api: TestClient):
    cid = produce(api, 6)
    warm = api.get(f"/api/campaigns/{cid}/spot/estimate").json()
    with motion_client(api, ScriptedClient(state="cold")):
        cold = api.get(f"/api/campaigns/{cid}/spot/estimate").json()
    assert cold["cold_start_seconds"] == 240 and cold["cold_start_cost_usd"] == round(240 * 0.00108, 5) and cold["est_gpu_seconds"] == round(warm["est_gpu_seconds"] + 240, 2)
    assert cold["est_wall_seconds"] == round(warm["est_wall_seconds"] + 240, 1)
    assert api.put(f"/api/campaigns/{cid}/budget", json={"cap_usd": 0.05}, headers=H("brand_manager")).status_code == 200
    tight = api.get(f"/api/campaigns/{cid}/spot/estimate").json()
    assert tight["budget"]["allowed"] is False and "exceeds the remaining AI budget of this campaign" in tight["budget"]["reason"] and tight["est_cost_usd"] > tight["budget"]["campaign_remaining_usd"]
    pl = api.get(f"/api/campaigns/{cid}/spot/estimate", headers=PL).json()
    assert pl["budget"]["allowed"] is False and "przekracza pozostały budżet AI tej kampanii" in pl["budget"]["reason"]
    with motion_client(api, OffMotionClient("wan2.2-ti2v-5b")):
        off = api.get(f"/api/campaigns/{cid}/spot/estimate").json()
        assert off["available"] is False and off["budget"]["allowed"] is False and "not available in this deployment" in off["budget"]["reason"]
        assert "nie jest dostępny" in api.get(f"/api/campaigns/{cid}/spot/estimate", headers=PL).json()["budget"]["reason"]


def test_the_estimate_validates_its_input(api: TestClient):
    cid = produce(api, 6)
    assert api.get(f"/api/campaigns/{cid}/spot/estimate", params={"quality": "ultra"}).status_code == 422
    assert api.get(f"/api/campaigns/{cid}/spot/estimate", params={"aspect": "21:9"}).status_code == 422
    assert api.get("/api/campaigns/nope/spot/estimate").status_code == 404
    empty = api.post("/api/campaigns", json={"name": "Nothing yet", "markets": ["US"], "channels": ["meta"]}, headers=H("creative")).json()["id"]
    r = api.get(f"/api/campaigns/{empty}/spot/estimate")
    assert r.status_code == 422 and r.json()["error"]["code"] == "inputs_missing"
    assert api.get(f"/api/campaigns/{empty}/spot/estimate", params={"quality": "preview"}).status_code == 200  # nothing to price for a preview, whatever the state


# ------------------------------------------------------------------------------------------------ rendering again, and when things go wrong


def test_rendering_the_same_spot_again_is_served_from_the_library_for_free(api: TestClient, produced: str, cinematic: dict[str, Any]):
    calls = api.app.state.services.motion.calls
    spent = api.get("/api/usage", params={"campaign_id": produced}).json()["total_usd"]
    r = api.post(f"/api/campaigns/{produced}/spot/{cinematic['artifact_id']}/rerender?wait=true", headers=H("creative"))
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["quality"] == "cinematic" and (res["motion"]["shots_generated"], res["motion"]["shots_cached"], res["motion"]["gpu_seconds"], res["motion"]["cost_usd"]) == (3, 3, 0.0, 0.0)
    assert api.app.state.services.motion.calls == calls  # the animator was not asked
    new = next(s for s in spots(api, produced) if s["id"] == res["artifact_id"])
    assert new["parent_id"] == cinematic["artifact_id"] and new["quality"] == "cinematic"
    usage = api.get("/api/usage", params={"campaign_id": produced}).json()
    assert usage["total_usd"] - spent < 0.05 and usage["by_kind"]["motion"]["cached"] >= 3  # only the compositor was paid for; the clip hits are metered at $0
    assert next(c for c in api.get("/api/jobs", params={"campaign_id": produced}).json() if c["kind"] == "spot.render" and c["title"].endswith("(AI motion)"))["lane"] == "motion"


def test_without_a_motion_backend_cinematic_is_refused_up_front_in_both_languages(api: TestClient):
    cid = produce(api, 6)
    with motion_client(api, OffMotionClient("wan2.2-ti2v-5b")):
        r = render(api, cid, quality="cinematic")
        assert r.status_code == 503 and r.json()["error"]["code"] == "motion_unavailable"
        assert r.json()["error"]["message"] == "Cinematic motion is not available in this deployment." and "Preview" in r.json()["error"]["hint"]
        pl = render(api, cid, headers={**H("creative"), **PL}, quality="cinematic")
        assert pl.status_code == 503 and pl.json()["error"]["message"] == "Ruch filmowy (wideo AI) nie jest dostępny w tym wdrożeniu." and "Podgląd" in pl.json()["error"]["hint"]
        assert render(api, cid).status_code == 200  # a preview still renders
    assert render(api, cid, quality="ultra").status_code == 422


def test_when_every_shot_fails_the_spot_is_still_delivered_with_stills_and_says_so(api: TestClient, tmp_path: Path):
    cid = produce(api, 6)
    with motion_client(api, ScriptedClient({1: MotionFailed("CUDA out of memory", worker_code="oom", gpu_seconds=9.0)})):
        r = render(api, cid, quality="cinematic")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["quality"] == "cinematic" and abs(res["duration"] - 6.0) <= 0.5 and abs(res["loudness_lufs"] - (-16.0)) <= 1.5 and res["guardian"]["verdict"] in {"pass", "warn"}
    m = res["motion"]
    assert (m["shots_total"], m["shots_generated"], m["shots_cached"]) == (1, 0, 0) and [f["reason"] for f in m["shots_fallback"]] == ["oom"] and m["gpu_seconds"] == 9.0
    assert m["shots_fallback"][0]["reason_text"] == "the GPU ran out of memory"  # the job result names the reason in words too
    pl_job = api.get(f"/api/jobs/{r.json()['id']}", headers=PL).json()["result"]["motion"]["shots_fallback"][0]
    assert (pl_job["reason"], pl_job["reason_text"]) == ("oom", "zabrakło pamięci GPU")  # served in the viewer's language; the stored code stays
    spot = next(s for s in spots(api, cid) if s["quality"] == "cinematic")
    assert spot["render"]["motion"]["shots_fallback"][0]["reason_text"] == "the GPU ran out of memory"
    assert spots(api, cid, {**H("creative"), **PL})[0]["render"]["motion"]["shots_fallback"][0]["reason_text"] == "zabrakło pamięci GPU"
    detail = api.get(f"/api/campaigns/{cid}/spot/{spot['id']}", headers=PL).json()
    assert detail["render"]["motion"]["shots_fallback"][0]["reason_text"] == "zabrakło pamięci GPU" and all(sc["clip_asset_id"] is None for sc in detail["spec"]["scenes"])
    assert detail["spec"]["disclosure_badge"]  # a cinematic spot is labelled even when only stills made it into the picture
    assert not clip_assets(api, cid)
    usage = api.get("/api/budget/events", params={"campaign_id": cid}).json()["events"]
    assert [e["units"]["gpu_seconds"] for e in usage if e["kind"] == "motion"] == [9.0]  # the failed attempt still ran on the GPU: it is metered
    manifest = api.get(f"/api/provenance/assets/{res['video_asset_id']}").json()["manifest"]["assertions"]
    assert "generative_video" not in manifest and not [i for i in manifest["ingredients"] if i["role"] == "motion-clip"]  # no footage of a video model: nothing to claim
    video = tmp_path / "stills.mp4"
    video.write_bytes(api.get(f"/api/library/assets/{res['video_asset_id']}/content").content)
    assert media.probe(video)["video"]["fps"] == 25.0


def test_a_budget_refusal_spends_nothing_and_asks_the_worker_for_nothing(api: TestClient):
    cid = produce(api, 6)
    assert api.put(f"/api/campaigns/{cid}/budget", json={"cap_usd": 0.05}, headers=H("brand_manager")).status_code == 200
    with motion_client(api, ScriptedClient(state="cold")) as client:
        before = api.get("/api/usage", params={"campaign_id": cid}).json()["total_usd"]
        r = render(api, cid, quality="cinematic")
        assert r.status_code == 402 and r.json()["error"]["code"] == "campaign_budget_exceeded" and "Campaign AI cap reached" in r.json()["error"]["message"]
        assert client.requests == [] and client.warmups == 0 and client.state == "cold"  # the GPU was not even woken
    assert api.get("/api/usage", params={"campaign_id": cid}).json()["total_usd"] == before
    assert not [e for e in api.get("/api/budget/events", params={"campaign_id": cid}).json()["events"] if e["kind"] == "motion"]
    assert not clip_assets(api, cid) and not [s for s in spots(api, cid) if s["quality"] == "cinematic"]
    assert api.put(f"/api/campaigns/{cid}/budget", json={"cap_usd": 2}, headers=H("brand_manager")).status_code == 200
    assert render(api, cid, quality="cinematic").status_code == 200  # with the budget back, the same render goes through


def test_a_clip_that_content_safety_flags_never_reaches_the_spot(api: TestClient, monkeypatch: pytest.MonkeyPatch):
    cid = produce(api, 6)

    async def flagged(data: bytes) -> SafetyResult:
        return SafetyResult({"Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 6}, provider="stub")

    monkeypatch.setattr(api.app.state.services.safety, "analyze_image", flagged)
    r = render(api, cid, quality="cinematic")
    assert r.status_code == 200, r.text
    m = r.json()["result"]["motion"]
    assert m["shots_generated"] == 0 and [f["reason"] for f in m["shots_fallback"]] == ["safety"] and m["gpu_seconds"] > 0  # generated, paid for, and thrown away
    assert not clip_assets(api, cid)


def test_a_viewer_who_may_not_generate_cannot_start_a_cinematic_render(api: TestClient):
    cid = produce(api, 6)
    assert render(api, cid, headers=H("legal"), quality="cinematic").status_code == 403


@needs_cv2
def test_a_shot_that_barely_moved_is_made_again_and_the_report_provenance_and_meter_say_so(api: TestClient):
    cid = produce(api, 6)
    sb = api.get(f"/api/campaigns/{cid}/storyboard").json()["latest"]
    shot_id = sb["shots"][0]["id"]
    edit = api.patch(f"/api/campaigns/{cid}/storyboard/{sb['id']}/shots/{shot_id}", json={"motion": "A hand turns the bag slowly; steam drifts left."}, headers=H("creative"))
    assert edit.status_code == 200 and edit.json()["motion_stale"] is True  # the clip to come is the first one for this text
    with motion_client(api, Stubborn({1})) as client:  # the model returns the keyframe as a frozen clip the first time
        r = render(api, cid, quality="cinematic")
    assert r.status_code == 200, r.text
    first, second = client.requests
    assert second.seed == first.seed + 1 and second.prompt.startswith(first.prompt) and second.prompt != first.prompt
    res = r.json()["result"]
    m = res["motion"]
    assert (m["shots_total"], m["shots_generated"], m["shots_low_motion"], m["retries"], m["shots_fallback"]) == (1, 1, 0, 1, [])
    assert m["gpu_seconds"] == round(2 * client.results[0].gpu_seconds, 2)  # two generations on the GPU, both in the bill
    row = next(s for s in spots(api, cid) if s["id"] == res["artifact_id"])["render"]["motion"]["shots"][0]
    assert row["motion"]["attempts"] == 2 and row["motion"]["level"] in {"subtle", "rich"} and row["seed"] == second.seed and row["prompt_sha256"] != row["plan_prompt_sha256"]
    prov = api.get(f"/api/provenance/assets/{res['video_asset_id']}").json()
    assert [(s["attempts"], s["seed"]) for s in prov["manifest"]["assertions"]["generative_video"]["shots"]] == [(2, second.seed)] and prov["verification"]["ok"]
    events = [e for e in api.get("/api/budget/events", params={"campaign_id": cid}).json()["events"] if e["kind"] == "motion"]
    assert sorted((e["units"]["shots"], e["units"]["retry"]) for e in events) == [(0, True), (1, False)] and all(e["units"]["gpu_seconds"] > 0 for e in events)
    fresh = api.get(f"/api/campaigns/{cid}/storyboard").json()["latest"]
    assert not fresh["shots"][0].get("motion_stale")  # the clip answers the storyboard's own prompt, whatever the retry added to the one it was made with
    assert api.get(f"/api/campaigns/{cid}/spot/estimate", params={"quality": "cinematic"}).json()["cached_shots"] == 1  # and the library serves it from now on


# ------------------------------------------------------------------------------------------------ the other versions of a cinematic master


def test_formats_of_a_cinematic_master_are_cinematic_with_native_clips_per_aspect_and_cutdowns_from_the_cache(api: TestClient, produced: str, cinematic: dict[str, Any]):
    before = len(clip_assets(api, produced))
    r = api.post(f"/api/campaigns/{produced}/formats/generate?wait=true", json={"aspects": ["9:16"], "cutdowns": [6]}, headers=H("creative"))
    assert r.status_code == 200, r.text
    versions = {v["label"]: v for v in r.json()["result"]["versions"]}
    by_id = {s["id"]: s for s in spots(api, produced)}
    vertical, cut = by_id[versions["9:16"]["artifact_id"]], by_id[versions["6s cutdown"]["artifact_id"]]
    assert vertical["quality"] == "cinematic" and cut["quality"] == "cinematic"
    mv, mc = vertical["render"]["motion"], cut["render"]["motion"]
    assert (mv["shots_generated"], mv["shots_cached"], mv["shots_fallback"]) == (3, 0, []) and {(s["width"], s["height"]) for s in mv["shots"]} == {(576, 1024)}  # generated natively for 9:16
    assert mc["shots_generated"] >= 1 and mc["shots_cached"] == mc["shots_generated"] and mc["gpu_seconds"] == 0.0  # the cutdown plays the master's clips
    assert len(clip_assets(api, produced)) == before + 3 and abs(cut["duration"] - 6.0) <= 0.5
    job = next(j for j in api.get("/api/jobs", params={"campaign_id": produced}).json() if j["kind"] == "formats.generate")
    assert job["lane"] == "motion" and job["status"] == "succeeded"


def test_a_localized_version_of_a_cinematic_master_is_cinematic_and_reuses_its_clips(api: TestClient, produced: str, cinematic: dict[str, Any]):
    r = api.post(f"/api/campaigns/{produced}/localization/generate?wait=true", json={"langs": ["pl"], "render": True}, headers=H("creative"))
    assert r.status_code == 200, r.text
    loc = next(x for x in api.get(f"/api/campaigns/{produced}/localization").json()["localizations"] if x["lang"] == "pl")
    spot = next(s for s in spots(api, produced) if s["id"] == loc["spot_id"])
    assert spot["lang"] == "pl" and spot["quality"] == "cinematic"
    m = spot["render"]["motion"]
    assert (m["shots_generated"], m["shots_cached"], m["gpu_seconds"], m["cost_usd"]) == (3, 3, 0.0, 0.0)  # the picture did not change: only voice-over, captions and end card did
    job = next(j for j in api.get("/api/jobs", params={"campaign_id": produced}).json() if j["kind"] == "localization.generate")
    assert job["lane"] == "motion"


# ------------------------------------------------------------------------------------------------ a mixed spot (last: it becomes the newest master of the campaign)


def test_a_spot_with_one_failed_shot_mixes_clips_and_stills_and_the_manifest_says_which(api: TestClient, produced: str, tmp_path: Path):
    with motion_client(api, ScriptedClient({2: MotionFailed("the worker crashed")})):
        r = render(api, produced, quality="cinematic", aspect="4:5")  # a new aspect: nothing is cached, three shots are asked for
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    m = res["motion"]
    assert (m["shots_total"], m["shots_generated"], m["shots_cached"]) == (3, 2, 0) and [f["reason"] for f in m["shots_fallback"]] == ["internal"] and m["shots_generated"] + len(m["shots_fallback"]) == m["shots_total"]
    assert m["shots_fallback"][0]["reason_text"] == "the motion model reported an internal error"
    assert abs(res["duration"] - 15.0) <= 0.5 and abs(res["loudness_lufs"] - (-16.0)) <= 1.5 and res["guardian"]["verdict"] in {"pass", "warn"}
    detail = api.get(f"/api/campaigns/{produced}/spot/{res['artifact_id']}").json()
    assert [bool(sc["clip_asset_id"]) for sc in detail["spec"]["scenes"]] == [True, False, True]  # the middle scene plays its still with a camera move
    video = tmp_path / "mixed.mp4"
    video.write_bytes(api.get(f"/api/library/assets/{res['video_asset_id']}/content").content)
    info = media.probe(video)
    assert (info["video"]["width"], info["video"]["height"], info["video"]["fps"]) == (576, 720, 25.0) and abs(info["duration"] - 14.9) <= 0.5
    prov = api.get(f"/api/provenance/assets/{res['video_asset_id']}").json()
    gv = prov["manifest"]["assertions"]["generative_video"]
    assert (gv["shots_total"], len(gv["shots"]), [f["reason"] for f in gv["fallback_shots"]]) == (3, 2, ["internal"]) and prov["verification"]["ok"]
    assert "2 of 3 shots" in json.dumps(prov["summary"])
