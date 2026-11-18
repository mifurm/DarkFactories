"""Cinematic motion — the platform pieces around the render: the storyboard's opening frame and motion text (English + Polish, hand-edits), the job runner that has
to keep a ~25 minute render alive (heartbeat, sweeper, GPU lane, keep-alive, progress slices), the catalogs, the Guardian rules and the spot builder."""

from __future__ import annotations

import asyncio
import functools
import re
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spotlight.app_factory import create_app
from spotlight.config import Settings
from spotlight.core.jobs import JobCancelled, JobContext, JobRunner, render_job
from spotlight.core.repo import MemoryRepository
from spotlight.domain.formats import reframe
from spotlight.domain.guardian import (
    BrandRules,
    Disclosure,
    GuardianContext,
    GuardianSubject,
    TextItem,
    run_rules,
)
from spotlight.domain.spot_builder import build_master_spec, scenes_from_storyboard
from spotlight.errors import AppError
from spotlight.i18n import has, t
from spotlight.motion import plan as motion_plan
from spotlight.motion.models import (
    FALLBACK_REASONS,
    MotionBadRequest,
    MotionDisabled,
    MotionFailed,
    MotionTimeout,
    MotionTransportError,
    MotionUnavailable,
)
from spotlight.motion.prompts import build_motion_prompt, default_motion, motion_text, opening_text
from spotlight.motion.report import localize_motion, reason_text
from spotlight.seed import data
from spotlight.seed.data import DAWN_ROAST_BRIEF_PL
from spotlight.util import now_iso
from spotlight.video.spec import ClipSpec, EndCardSpec, RenderSpec, SceneSpec
from test_pipeline_api import H, build_to_script

PL = {"X-Studio-Role": "creative", "X-Studio-User": "tester", "X-UI-Lang": "pl"}
PL_LETTERS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
SEQUENCE_WORDS = re.compile(r"\b(then|after|afterwards|before|while|begins?|tightens|transitions?|cuts? to|split|diptych|panels?|collage|sequence)\b", re.I)


def polish(text: str) -> bool:
    return bool(PL_LETTERS & set(text))


# ------------------------------------------------------------------------------------------------ the storyboard: opening frame + motion text


@pytest.fixture(scope="module")
def api():
    app = create_app(Settings(spotlight_mode="offline", rate_limit_enabled=False, seed_on_start=True))
    with TestClient(app) as c:
        yield c


def storyboard_of(api: TestClient, cid: str, script_id: str, headers: dict[str, str], frames: bool = False) -> dict[str, Any]:
    assert api.post(f"/api/campaigns/{cid}/guardian/run", json={"artifact_id": script_id, "auto_revise": True}, headers=headers).json()["converged"]
    assert api.post(f"/api/campaigns/{cid}/storyboard/generate?wait=true", json={"script_id": script_id}, headers=headers).status_code == 200
    sb = api.get(f"/api/campaigns/{cid}/storyboard", headers=headers).json()["latest"]
    if frames:
        assert api.post(f"/api/campaigns/{cid}/storyboard/{sb['id']}/frames?wait=true", json={"quality": "low"}, headers=headers).status_code == 200
        sb = api.get(f"/api/campaigns/{cid}/storyboard", headers=headers).json()["latest"]
    return sb


@pytest.fixture(scope="module")
def english(api: TestClient) -> tuple[str, dict[str, Any]]:
    cid = build_to_script(api)
    script = next(s for s in api.get(f"/api/campaigns/{cid}/script").json()["scripts"] if s["duration_s"] == 15)
    return cid, storyboard_of(api, cid, script["id"], H("creative"), frames=True)


@pytest.fixture(scope="module")
def polish_campaign(api: TestClient) -> tuple[str, dict[str, Any]]:
    cid = api.post("/api/campaigns", json={"name": "Dawn Roast — ruch PL", "channels": ["youtube", "meta"]}, headers=PL).json()["id"]
    api.put(f"/api/campaigns/{cid}/brief", json={"raw_text": DAWN_ROAST_BRIEF_PL}, headers=PL)
    api.post(f"/api/campaigns/{cid}/brief/analyze", headers=PL)
    api.post(f"/api/campaigns/{cid}/brief/answers", json={"answers": {"key_message": "Wolniejszy początek dnia, zrobiony dobrze.", "cta": "Znajdź Dawn Roast na northwind.example/dawn", "duration_targets": [15]}}, headers=PL)
    assert api.post(f"/api/campaigns/{cid}/brief/finalize", headers=PL).status_code == 200
    assert api.post(f"/api/campaigns/{cid}/strategy/generate?wait=true", json={}, headers=PL).status_code == 200
    assert api.post(f"/api/campaigns/{cid}/script/generate?wait=true", json={"durations": [15]}, headers=PL).status_code == 200
    script = api.get(f"/api/campaigns/{cid}/script", headers=PL).json()["scripts"][0]
    return cid, storyboard_of(api, cid, script["id"], PL, frames=True)


def patch(api: TestClient, cid: str, sb: dict[str, Any], shot: str, headers: dict[str, str], **body: Any):
    return api.patch(f"/api/campaigns/{cid}/storyboard/{sb['id']}/shots/{shot}", json=body, headers=headers)


def test_every_english_shot_has_a_single_opening_frame_and_a_short_motion_text(english):
    _, sb = english
    assert len(sb["shots"]) == 4
    for sh in sb["shots"]:
        assert sh["opening_en"] and not SEQUENCE_WORDS.search(sh["opening_en"]) and not polish(sh["opening_en"])  # the first instant, as a still photograph
        m = sh["motion"]
        assert set(m) == {"prompt_en", "prompt", "camera"} and 20 < len(m["prompt_en"]) <= 280 and m["prompt"] == m["prompt_en"]
        assert m["camera"] and sh["movement"] in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax"}
        assert sh["opening_en"] in sh["image_prompt"] and "Depict ONE single frame" in sh["image_prompt"] and m["prompt_en"] not in sh["image_prompt"]  # the keyframe never gets the motion text
        assert "motion_stale" not in sh and sh["image_status"] == "ready"


def test_polish_shots_are_shown_in_polish_while_the_models_get_english(polish_campaign):
    _, sb = polish_campaign
    assert sb["lang"] == "pl"
    for sh in sb["shots"]:
        m = sh["motion"]
        assert polish(m["prompt"]) and m["prompt"] != m["prompt_en"] and not polish(m["prompt_en"]) and len(m["prompt"]) <= 300  # people read Polish, the video model English
        assert not polish(sh["opening_en"]) and not SEQUENCE_WORDS.search(sh["opening_en"]) and not polish(sh["image_prompt"]) and sh["opening_en"] in sh["image_prompt"]
        plan = build_motion_prompt(sh, sb.get("style_bible_en"), sh["role"], sh["movement"])
        assert not polish(plan) and m["prompt_en"].rstrip(".") in plan


def test_editing_the_motion_of_an_english_shot_changes_what_the_model_gets_and_keeps_the_keyframe(api: TestClient, english):
    cid, sb = english
    shot = sb["shots"][1]
    before = motion_plan.shot_prompt_sha(shot, sb)
    r = patch(api, cid, sb, shot["id"], H("creative"), motion="  A hand   turns the bag slowly; steam drifts left.  ")
    assert r.status_code == 200, r.text
    sh = r.json()
    assert sh["motion"]["prompt"] == sh["motion"]["prompt_en"] == "A hand turns the bag slowly; steam drifts left." and sh["motion"]["edited"] is True
    assert sh["motion_stale"] is True and sh["image_status"] == "ready" and sh["asset_id"] == shot["asset_id"]  # the clip is out of date, the approved keyframe is not
    fresh = api.get(f"/api/campaigns/{cid}/storyboard").json()["latest"]
    assert motion_plan.shot_prompt_sha(next(x for x in fresh["shots"] if x["id"] == shot["id"]), fresh) != before
    assert "A hand turns the bag slowly; steam drifts left." in build_motion_prompt(sh, fresh.get("style_bible_en"), sh["role"], sh["movement"])
    assert patch(api, cid, sb, shot["id"], H("creative"), motion="x" * 301).status_code == 422
    assert patch(api, cid, sb, shot["id"], H("legal"), motion="no").status_code == 403


def test_a_new_camera_move_is_part_of_the_prompt_and_marks_the_clip_outdated(api: TestClient, english):
    cid, sb = english
    shot = sb["shots"][2]
    r = patch(api, cid, sb, shot["id"], H("creative"), movement="pan_left")
    assert r.status_code == 200 and r.json()["motion"]["camera"] == "gentle truck left" and r.json()["motion_stale"] is True and r.json()["image_status"] == "ready"
    assert "Camera: gentle truck left." in build_motion_prompt(r.json(), None, r.json()["role"], "pan_left")


def test_editing_the_description_redraws_the_keyframe_from_the_new_opening_frame(api: TestClient, english):
    cid, sb = english
    shot = sb["shots"][0]
    text = "A steaming cup on a windowsill at dawn, amber light."
    r = patch(api, cid, sb, shot["id"], H("creative"), description=text)
    sh = r.json()
    assert r.status_code == 200 and sh["opening_en"] == text and sh["description"] == text and "description_en" not in sh
    assert sh["image_status"] == "stale" and text in sh["image_prompt"] and "opening_edited_lang" not in sh  # the keyframe has to be drawn again; the clip will follow the new keyframe


def test_a_polish_hand_edit_changes_the_text_shown_but_not_the_english_prompt_of_the_video_model(api: TestClient, polish_campaign):
    cid, sb = polish_campaign
    shot = sb["shots"][1]
    before = motion_plan.shot_prompt_sha(shot, sb)
    r = patch(api, cid, sb, shot["id"], PL, motion="Dłoń powoli obraca torbę, a para unosi się w lewo.")
    assert r.status_code == 200, r.text
    sh = r.json()
    assert sh["motion"]["prompt"] == "Dłoń powoli obraca torbę, a para unosi się w lewo." and sh["motion"]["edited"] is True
    assert sh["motion"]["prompt_en"] == shot["motion"]["prompt_en"]  # the last machine-generated English prompt stays
    assert not sh.get("motion_stale") and sh["image_status"] == "ready"  # nothing the model reads changed: the clip is still valid
    fresh = api.get(f"/api/campaigns/{cid}/storyboard", headers=PL).json()["latest"]
    assert motion_plan.shot_prompt_sha(next(x for x in fresh["shots"] if x["id"] == shot["id"]), fresh) == before
    assert not polish(build_motion_prompt(sh, fresh.get("style_bible_en"), sh["role"], sh["movement"]))


def test_a_polish_description_edit_reaches_the_image_model_but_never_the_english_video_prompt(api: TestClient, polish_campaign):
    cid, sb = polish_campaign
    shot = sb["shots"][0]
    text = "Parująca filiżanka na parapecie o świcie, bursztynowe światło."
    r = patch(api, cid, sb, shot["id"], PL, description=text)
    sh = r.json()
    assert r.status_code == 200 and sh["description"] == text and sh["opening_en"] == text and sh["opening_edited_lang"] == "pl"
    assert text in sh["image_prompt"] and sh["image_status"] == "stale"
    fresh = api.get(f"/api/campaigns/{cid}/storyboard", headers=PL).json()["latest"]
    prompt = build_motion_prompt(sh, fresh.get("style_bible_en"), sh["role"], sh["movement"])
    assert not polish(prompt) and text not in prompt and opening_text(sh) == ""


def test_the_motion_prompt_of_a_shot_without_motion_text_is_a_role_default_and_never_the_unedited_display_text():
    legacy = {"id": "s1", "role": "hook", "description": "Pre-dawn kitchen.", "movement": "zoom_in"}  # a storyboard written before motion existed
    plan = build_motion_prompt(legacy, None, "hook", "zoom_in")
    assert default_motion("hook").capitalize() in plan and "Camera: slow push-in." in plan and "Pre-dawn kitchen." in plan and len(plan) <= 900
    assert motion_text({"motion": {"prompt": "Polski tekst", "edited": True}}, "hook") == default_motion("hook")  # a hand-edit in another language is for people only
    assert motion_text({"motion": {"prompt": "Plain English text"}}) == "Plain English text"  # an unedited display text is still the best we have
    assert motion_text({"motion": {"prompt_en": "English wins", "prompt": "Polski"}}) == "English wins"
    assert build_motion_prompt({"role": "proof"}, None, None, None).endswith("no text overlays.")


def test_a_long_prompt_sheds_its_optional_context_before_it_loses_the_motion():
    shot = {"role": "hook", "opening_en": "O" * 400, "framing_en": "F" * 300, "motion": {"prompt_en": "M" * 280}}
    plan = build_motion_prompt(shot, {"lighting": "L" * 300}, "hook", "zoom_out")
    assert len(plan) <= 900 and "M" * 280 in plan and "Camera: slow pull-back." in plan and "L" * 300 not in plan


# ------------------------------------------------------------------------------------------------ the job runner under a 25 minute render


class SpyRepo(MemoryRepository):
    """Records every write of a job and lets a test wait for a condition on those writes (instead of sleeping and hoping)."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self._waiters: list[tuple[Any, asyncio.Event]] = []

    async def upsert(self, container: str, doc: dict[str, Any]) -> Any:
        out = await super().upsert(container, doc)
        if container == "jobs":
            self.writes.append((doc["id"], dict(doc)))
            for condition, event in self._waiters:
                if not event.is_set() and condition():
                    event.set()
        return out

    async def until(self, condition: Any, within: float = 30.0) -> None:
        """Returns once ``condition()`` holds after a write (immediately when it already does); ``within`` only bounds a failure."""
        if condition():
            return
        event = asyncio.Event()
        self._waiters.append((condition, event))
        await asyncio.wait_for(event.wait(), within)


def runner(repo: Any = None, **kw: Any) -> JobRunner:
    return JobRunner(repo or MemoryRepository(), instance_id=kw.pop("instance_id", "replica-a"), **kw)


async def test_a_running_job_writes_a_heartbeat_so_other_replicas_know_it_is_alive():
    repo = SpyRepo()
    jobs = runner(repo, heartbeat_s=0.01)
    release = asyncio.Event()

    async def long(job: JobContext) -> dict[str, Any]:
        await release.wait()
        return {"ok": True}

    j = await jobs.submit("test.long", long, title="long")
    await repo.until(lambda: sum(1 for jid, d in repo.writes if jid == j["id"] and d.get("heartbeat_at")) >= 3)  # three heartbeats arrive while the job is still running
    assert (await jobs.get(j["id"]))["status"] == "running"
    release.set()
    assert (await jobs.wait(j["id"], 30))["status"] == "succeeded"
    assert jobs._alive({"heartbeat_at": now_iso()}) and not jobs._alive({"heartbeat_at": "2020-01-01T00:00:00+00:00"})
    await jobs.shutdown()


async def test_a_replica_that_starts_up_fails_only_the_jobs_nobody_is_working_on_anymore():
    repo = MemoryRepository()
    old = "2020-01-01T00:00:00+00:00"
    base = {"pk": "global", "kind": "spot.render", "title": "x", "progress": 0.4, "steps": []}
    await repo.upsert("jobs", {**base, "id": "job_live", "status": "running", "owner": "replica-b", "heartbeat_at": now_iso()})
    await repo.upsert("jobs", {**base, "id": "job_dead", "status": "running", "owner": "replica-c", "heartbeat_at": old, "created_at": old})
    await repo.upsert("jobs", {**base, "id": "job_queued_dead", "status": "queued", "owner": "replica-c", "heartbeat_at": old, "created_at": old})
    await repo.upsert("jobs", {**base, "id": "job_mine_before_restart", "status": "running", "owner": "replica-a", "heartbeat_at": now_iso()})
    jobs = runner(repo)
    assert await jobs.reconcile_startup() == 3
    status = {d["id"]: d["status"] for d in await repo.query("jobs")}
    assert status == {"job_live": "running", "job_dead": "failed", "job_queued_dead": "failed", "job_mine_before_restart": "failed"}
    dead = await repo.get("jobs", "job_dead")
    assert dead["error"] == "interrupted by restart/scale-in" and dead["message_key"] == "job.state.interrupted" and dead["finished_at"]
    assert await jobs.reconcile_startup() == 0  # nothing left to do
    await jobs.shutdown()


async def test_the_sweeper_fails_the_jobs_of_a_replica_that_disappeared_and_stops_with_the_runner():
    repo = SpyRepo()
    await repo.upsert("jobs", {"id": "job_gone", "pk": "global", "kind": "spot.render", "title": "x", "status": "running", "owner": "replica-z", "heartbeat_at": "2020-01-01T00:00:00+00:00", "progress": 0.2, "steps": []})
    jobs = runner(repo)
    jobs.start_sweeper(interval_s=0.01)
    first = jobs._sweeper
    jobs.start_sweeper(interval_s=0.01)
    assert jobs._sweeper is first  # one sweeper per runner
    await repo.until(lambda: any(jid == "job_gone" and d["status"] == "failed" for jid, d in repo.writes))  # its last heartbeat is years old: the sweeper fails it
    assert (await repo.get("jobs", "job_gone"))["status"] == "failed"
    await jobs.shutdown()
    assert first is not None and first.cancelled()  # (a live job is spared: see the reconcile test, the sweeper runs the very same check)


async def test_a_gpu_job_waits_in_its_own_lane_and_does_not_take_a_general_slot():
    jobs = runner(max_concurrent=1)
    gate_general, gate_gpu = asyncio.Event(), asyncio.Event()
    started = {name: asyncio.Event() for name in ("general", "gpu1", "gpu2", "general2")}

    def job(name: str, gate: asyncio.Event):
        async def fn(ctx: JobContext) -> dict[str, Any]:
            started[name].set()
            await gate.wait()
            return {}

        return fn

    general = await jobs.submit("g", job("general", gate_general), title="general")
    gpu1 = await jobs.submit("m1", job("gpu1", gate_gpu), title="gpu 1", lane="motion")
    gpu2 = await jobs.submit("m2", job("gpu2", gate_gpu), title="gpu 2", lane="motion")
    other = await jobs.submit("g2", job("general2", gate_general), title="general 2")
    await asyncio.wait_for(asyncio.gather(started["general"].wait(), started["gpu1"].wait()), 30)  # the GPU render runs next to a busy general slot...
    for waiting in (gpu2, other):  # ...while the second GPU render waits for the GPU and the second general job for its slot (both holders are blocked: they cannot have started)
        assert (await jobs.get(waiting["id"]))["status"] == "queued"
    assert not started["gpu2"].is_set() and not started["general2"].is_set()
    assert gpu1.get("lane") == "motion" and "lane" not in general
    gate_gpu.set()
    gate_general.set()
    for j in (general, gpu1, gpu2, other):
        assert (await jobs.wait(j["id"], 30))["status"] == "succeeded"
    assert all(e.is_set() for e in started.values())
    await jobs.shutdown()


async def test_a_quiet_job_keeps_its_progress_stream_alive_with_pings():
    jobs = runner()
    release = asyncio.Event()

    async def quiet(job: JobContext) -> dict[str, Any]:
        await job.progress(0.1, "waking the GPU")
        await release.wait()
        return {}

    j = await jobs.submit("quiet", quiet, title="quiet")
    events: list[str] = []
    async for ev in jobs.stream(j["id"], poll=0.01, keepalive_s=0.05):
        events.append(ev["event"])
        if events.count("ping") == 3:
            release.set()
    assert events[0] == "progress" and events.count("ping") >= 3 and events[-1] == "done"
    assert "ping" not in events[:1]
    await jobs.shutdown()


async def test_a_caller_that_stops_waiting_does_not_stop_the_job():
    jobs = runner()
    release = asyncio.Event()

    async def slow(job: JobContext) -> dict[str, Any]:
        await release.wait()
        return {"done": True}

    j = await jobs.submit("slow", slow, title="slow")
    with pytest.raises(TimeoutError):
        await jobs.wait(j["id"], 0.05)
    assert (await jobs.get(j["id"]))["status"] == "running"  # wait=true gives up after 178 s; the render goes on
    release.set()
    done = await jobs.wait(j["id"], 30)
    assert done["status"] == "succeeded" and done["result"] == {"done": True}
    await jobs.shutdown()


async def test_a_nested_render_reports_its_progress_inside_its_slice_of_the_job():
    jobs = runner()
    seen: list[tuple[float, str | None]] = []

    async def parent(job: JobContext) -> dict[str, Any]:
        await job.progress(0.1, "start")
        part = job.slice(0.2, 0.6)
        await part.progress(0.0, key="job.msg.motion.estimate", params={"shots": 3, "cached": 0, "cost": 0.2})
        seen.append((job.doc["progress"], job.doc.get("message_key")))
        await part.progress(0.5, key="job.msg.motion.shot", params={"n": 1, "total": 2, "pct": 0.5})
        seen.append((job.doc["progress"], job.doc.get("message_key")))
        await part.progress(5.0)  # clamped: a slice never leaves its range
        seen.append((job.doc["progress"], None))
        await part.progress(None, "just a message")
        assert part.id == job.id and part.campaign_id == job.campaign_id
        return {}

    j = await jobs.submit("nested", parent, title="nested")
    assert (await jobs.wait(j["id"], 30))["status"] == "succeeded"
    assert seen == [(0.2, "job.msg.motion.estimate"), (0.4, "job.msg.motion.shot"), (0.6, None)]
    await jobs.shutdown()


async def test_cancelling_reaches_a_nested_render_too():
    jobs = runner()
    flag = asyncio.Event()

    async def parent(job: JobContext) -> dict[str, Any]:
        part = job.slice(0.0, 1.0)
        flag.set()
        while True:
            await asyncio.sleep(0.01)
            await part.progress(0.5)  # raises JobCancelled once the user cancelled

    j = await jobs.submit("cancel-me", parent, title="cancel me")
    await flag.wait()
    await jobs.cancel(j["id"])
    assert (await jobs.wait(j["id"], 30))["status"] == "cancelled"
    with pytest.raises(JobCancelled):
        raise JobCancelled()
    await jobs.shutdown()


def test_the_progress_stream_sends_sse_comments_so_a_quiet_gpu_wait_is_not_cut_by_a_proxy(api: TestClient, monkeypatch: pytest.MonkeyPatch):
    jobs = api.app.state.services.jobs
    gate = threading.Event()

    async def quiet(job: JobContext) -> dict[str, Any]:
        await job.progress(0.1, key="job.msg.motion.warming", params={"s": 3})
        await asyncio.to_thread(gate.wait, 30)  # nothing to report while the GPU starts; the bound only limits a failure
        return {"ok": True}

    job = api.portal.call(functools.partial(jobs.submit, "test.quiet", quiet, title="quiet", lane="motion"))
    real = type(jobs).stream

    async def counting(self: JobRunner, job_id: str, **_: Any):
        pings = 0
        async for ev in real(self, job_id, poll=0.01, keepalive_s=0.05):
            yield ev
            if ev["event"] == "ping":
                pings += 1
                if pings == 3:
                    gate.set()  # three keep-alives went out: only now may the quiet job finish

    monkeypatch.setattr(type(jobs), "stream", counting)
    try:
        body = api.get(f"/api/stream/jobs/{job['id']}", headers={"X-UI-Lang": "pl"}).text
    finally:
        gate.set()
    assert body.count(": keep-alive\n\n") == 3 and body.index("event: progress") < body.index(": keep-alive") < body.index("event: done")
    assert "Rozgrzewanie procesu roboczego GPU" in body  # the message of the wake-up is shown in the viewer's language while the GPU starts


def test_a_finished_render_lists_its_fallback_shots_in_words_in_the_viewers_language():
    stored = {"id": "job_1", "status": "succeeded", "title": "Render", "result": {"quality": "cinematic", "motion": {"shots_total": 2, "shots_generated": 1, "shots_cached": 0, "shots_fallback": [{"shot_id": "s2", "reason": "oom", "detail": "CUDA out of memory"}]}}}
    en, pl = render_job(stored, "en"), render_job(stored, "pl")
    assert en["result"]["motion"]["shots_fallback"][0]["reason_text"] == "the GPU ran out of memory"
    assert pl["result"]["motion"]["shots_fallback"][0] == {"shot_id": "s2", "reason": "oom", "detail": "CUDA out of memory", "reason_text": "zabrakło pamięci GPU"}
    assert "reason_text" not in stored["result"]["motion"]["shots_fallback"][0]  # what is stored keeps the language-neutral code only
    plain = {"id": "job_2", "status": "succeeded", "title": "T", "result": {"x": 1}}
    assert render_job(plain, "pl")["result"] == {"x": 1} and render_job({**plain, "result": None}, "en")["result"] is None  # other jobs are untouched


# ------------------------------------------------------------------------------------------------ catalogs


def test_every_fallback_reason_and_every_motion_message_exists_in_english_and_polish_and_renders_cleanly():
    assert set(FALLBACK_REASONS) == {"oom", "timeout", "safety", "budget", "worker_unavailable", "bad_request", "internal", "disabled"}
    for reason in FALLBACK_REASONS:
        en, pl = reason_text(reason, "en"), reason_text(reason, "pl")
        assert en and pl and en != pl and "{" not in en + pl and "motion.reason" not in en + pl
    assert reason_text("something-new", "en") == reason_text("internal", "en") and reason_text(None, "pl") == reason_text("internal", "pl")  # an unknown code never shows a raw key
    params = {"shots": 3, "cached": 1, "cost": 0.2345, "s": 42, "n": 2, "total": 3, "pct": 0.5, "aspect": "16:9"}
    for key in ("job.title.render.cinematic", "job.msg.motion.estimate", "job.msg.motion.warming", "job.msg.motion.shot", "job.msg.motion.cached", "job.msg.motion.fallback", "label.call.motion", "audit.spot.motion_generated"):
        en, pl = t(key, "en", **params), t(key, "pl", **params)
        assert en != pl and not re.search(r"[{}]", en + pl), key
    assert "$0.23" in t("job.msg.motion.estimate", "en", **params) and "50" in t("job.msg.motion.shot", "pl", **params)
    for key in ("finding.disclosure.generative_video", "finding.disclosure.generative_video.sug", "finding.disclosure.video_model_missing", "finding.disclosure.video_model_missing.sug", "prov.sum.motion", "prov.sum.motion.stub", "motion.estimate.unavailable", "motion.estimate.daily", "motion.estimate.campaign"):
        assert has(key, "en") and has(key, "pl"), key


@pytest.mark.parametrize(
    "error",
    [
        MotionTimeout("The GPU motion worker did not finish within 1500 s", params={"seconds": 1500}),
        MotionFailed("The motion model failed: out of memory", worker_code="oom", params={"detail": "out of memory"}),
        MotionTransportError("The motion queue is not reachable: no route", params={"detail": "no route"}),
        MotionBadRequest("The motion request is invalid: bad size", params={"detail": "bad size"}),
        MotionUnavailable("Cinematic motion is not available in this deployment.", hint="Use the Preview quality, or ask an Admin to enable the GPU motion worker (MOTION_MODE)."),
        MotionDisabled("Cinematic motion is not available in this deployment.", hint="Use the Preview quality, or ask an Admin to enable the GPU motion worker (MOTION_MODE)."),
    ],
)
def test_motion_errors_are_told_in_polish_without_placeholders(error: AppError):
    en, en_hint = error.localized("en")
    pl, pl_hint = error.localized("pl")
    assert pl != en and not re.search(r"[{}]", pl + (pl_hint or ""))
    assert polish(pl + (pl_hint or "")) or "GPU" in pl  # real Polish, not the English text under another locale
    assert en == error.message and (not error.hint or en_hint == error.hint)


def test_the_report_helper_leaves_a_report_without_fallbacks_exactly_as_it_is():
    clean = {"shots_total": 2, "shots_generated": 2, "shots_fallback": []}
    assert localize_motion(clean, "pl") is clean and localize_motion(None) is None


# ------------------------------------------------------------------------------------------------ Guardian: the rules about generative video


@pytest.fixture
def ctx() -> GuardianContext:
    v = data.KIT["voice"]
    return GuardianContext(brand=BrandRules(palette=[p["hex"] for p in data.PALETTE], forbidden_words=v["forbidden_words"], replacements=v["replacements"], max_exclamations=1), claims=[], rights=[], today="2026-11-17")


def spot_subject(**disclosure: Any) -> GuardianSubject:
    return GuardianSubject(type="spot", campaign_id="c1", markets=["US"], channels=["youtube"], has_video=True, captions_present=True, disclosure=Disclosure(ai_generated=True, **disclosure), texts=[TextItem(id="v1", kind="vo", text="Wake up slowly.")])


def test_generative_video_without_the_on_screen_label_is_blocked_everywhere_even_where_no_law_asks_for_it(ctx):
    found = {f.rule_id: f for f in run_rules(spot_subject(label_present=False, generative_video=True, video_model="wan2.2-ti2v-5b"), ctx)}
    f = found["disclosure.generative_video"]
    assert f.severity == "block" and "wan2.2-ti2v-5b" in f.message and "AI-generated" in f.message and f.fix == {"op": "set_disclosure"}
    assert "disclosure.missing_label" not in found  # US: the law would not have asked; this rule does
    assert not [x for x in run_rules(spot_subject(label_present=False, generative_video=False), ctx) if x.severity == "block"]  # stills with camera moves: as before


def test_the_label_clears_it_and_a_missing_model_name_is_only_a_warning(ctx):
    ok = run_rules(spot_subject(label_present=True, label_text="AI-generated", generative_video=True, video_model="wan2.2-ti2v-5b"), ctx)
    assert not [f for f in ok if f.rule_id.startswith("disclosure.")]
    nameless = {f.rule_id: f for f in run_rules(spot_subject(label_present=True, label_text="AI-generated", generative_video=True, video_model=None), ctx)}
    assert nameless["disclosure.video_model_missing"].severity == "warn" and "disclosure.generative_video" not in nameless


# ------------------------------------------------------------------------------------------------ the spot builder and the format factory


def minimal_inputs(markets: list[str]) -> dict[str, Any]:
    beats = [
        {"id": "b1", "role": "hook", "t_start": 0, "t_end": 3, "visual": "x", "super_text": "Wake up slowly.", "vo": "Some mornings deserve a slower start."},
        {"id": "b2", "role": "proof", "t_start": 3, "t_end": 6, "visual": "y", "vo": "Roasted in small batches."},
        {"id": "b3", "role": "brand", "t_start": 6, "t_end": 8.4, "visual": "z", "vo": "Dawn Roast."},
    ]
    shots = [{"id": f"s{i}", "beat_id": f"b{i}", "asset_id": f"ast_{i}", "movement": "zoom_in", "focal": [0.4, 0.5], "super_text": None} for i in (1, 2, 3)]
    return {
        "campaign": {"id": "c1", "markets": markets, "channels": ["youtube"]}, "script": {"title": "T", "beats": beats, "legal": [], "tagline": "Wake up slowly.", "cta": "Find Dawn Roast"}, "storyboard": {"shots": shots},
        "voice": {"lines": [{"id": "v1", "text": "Some mornings deserve a slower start.", "start": 0.3, "duration": 2.4, "beat_id": "b1"}]}, "kit": {"palette": [{"hex": h} for h in ("#2B1A12", "#F2A03D", "#F6EBDD")], "logo": {}, "name": "Northwind"}, "music": None,
    }


def test_a_cinematic_spec_always_carries_the_ai_badge_a_preview_only_where_the_market_asks_for_it():
    us = minimal_inputs(["US"])
    preview = build_master_spec(spec_id="s1", **us)
    cinematic = build_master_spec(spec_id="s2", quality="cinematic", **us)
    assert preview.quality == "preview" and preview.disclosure_badge is None  # unchanged: no law asks for a burned-in label in the US
    assert cinematic.quality == "cinematic" and cinematic.disclosure_badge == "AI-generated"
    de = build_master_spec(spec_id="s3", **minimal_inputs(["DE"]))
    assert de.disclosure_badge == "AI-generated"  # where the market asks for it, both qualities have it


def test_the_cost_estimate_can_plan_a_storyboard_whose_keyframes_are_not_drawn_yet():
    inputs = minimal_inputs(["US"])
    inputs["storyboard"]["shots"][1]["asset_id"] = None
    strict = pytest.raises(Exception, match="keyframe")
    with strict:
        scenes_from_storyboard(inputs["script"], inputs["storyboard"])
    scenes = scenes_from_storyboard(inputs["script"], inputs["storyboard"], strict=False)
    assert [s.asset_id for s in scenes] == ["ast_1", "pending-s2"] and [s.id for s in scenes] == ["sc-b1", "sc-b2"]


def test_a_reframed_version_keeps_the_recipe_but_not_the_clips_of_the_other_aspect():
    spec = RenderSpec(
        id="m", campaign_id="c1", quality="cinematic", scenes=[SceneSpec(id="sc1", shot_id="s1", asset_id="a", duration=3, clip_asset_id="ast_clip", clip=ClipSpec(fps=24, frames=97))], endcard=EndCardSpec(),
        motion=motion_plan.plan_motion(RenderSpec(id="x", scenes=[SceneSpec(id="sc1", shot_id="s1", asset_id="a", duration=3)]), None, Settings(spotlight_mode="offline"), model="m", revision="1").recipe("stub"),
    )
    vertical = reframe(spec, "9:16")
    assert vertical.quality == "cinematic" and vertical.motion == spec.motion and vertical.aspect == "9:16"
    assert vertical.scenes[0].clip_asset_id is None and vertical.scenes[0].clip is None and spec.scenes[0].clip_asset_id == "ast_clip"  # the master is untouched


# ------------------------------------------------------------------------------------------------ services


async def test_the_motion_backend_is_closed_with_the_services(settings):
    from spotlight.services import build_services

    s = await build_services(settings)
    closed: list[bool] = []

    class Backend:
        name, model, revision, license, host = "fake", "m", "1", "x", "h"

        async def close(self) -> None:
            closed.append(True)

    s.motion = Backend()
    await s.close()
    assert closed == [True]
    s2 = await build_services(settings)
    s2.motion = None  # an older wiring without a motion backend still shuts down
    await s2.close()
