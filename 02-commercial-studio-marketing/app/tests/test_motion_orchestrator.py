"""Cinematic motion — orchestration of the motion phase of a render: library cache, budget, per-shot fallback, content safety and metering.

Offline: the stub animator behind scripted failures, no video compositing (the API tests cover the whole render)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from conftest import needs_ffmpeg
from spotlight.core.ai import pricing
from spotlight.core.ai.base import reset_ctx, set_ctx
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.core.jobs import JobCancelled
from spotlight.core.studio import Studio
from spotlight.errors import AppError, BudgetExceeded
from spotlight.i18n import has
from spotlight.motion import wire
from spotlight.motion.client import OffMotionClient
from spotlight.motion.models import (
    FALLBACK_REASONS,
    MotionBadRequest,
    MotionDisabled,
    MotionFailed,
    MotionRequest,
    MotionResult,
    MotionTimeout,
    MotionTransportError,
    MotionUnavailable,
    WorkerStatus,
)
from spotlight.motion.orchestrator import (
    FLAG_FROM,
    find_cached,
    generate_clips,
    license_of,
    motion_status,
    request_warmup,
)
from spotlight.motion.stub_client import StubMotionClient
from spotlight.video.spec import RenderSpec, SceneSpec

pytestmark = needs_ffmpeg
CID = "camp-orch"
ROLES = ["hook", "proof", "payoff", "proof"]


def jpeg(seed: int) -> bytes:
    buf = io.BytesIO()
    render_stub_scene("dawn", (768, 512), None, seed).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def make_spec(n: int = 2, aspect: str = "16:9", per: float = 1.0) -> tuple[RenderSpec, dict[str, bytes]]:
    scenes = [SceneSpec(id=f"sc-b{i}", shot_id=f"shot_{i}", asset_id=f"ast_k{i}", duration=per, motion="zoom_in", focal=(0.5, 0.55), role=ROLES[i % 4]) for i in range(n)]
    return RenderSpec(id="spec_o", campaign_id=CID, aspect=aspect, scenes=scenes, quality="cinematic"), {f"ast_k{i}": jpeg(i + 1) for i in range(n)}  # type: ignore[arg-type]


class ScriptedClient(StubMotionClient):
    """The offline animator behind scripted trouble: ``script[n]`` is raised by the n-th generate() call (1-based)."""

    def __init__(self, script: dict[int, BaseException] | None = None, state: str = "ready") -> None:
        super().__init__()
        self.script = script or {}
        self.state = state
        self.requests: list[MotionRequest] = []
        self.warmups = 0

    async def status(self) -> WorkerStatus:
        return WorkerStatus(state=self.state)

    async def warmup(self) -> WorkerStatus:
        self.warmups += 1
        requested = self.state == "cold"
        self.state = "warming" if requested else self.state
        return WorkerStatus(state=self.state, requested=requested)

    async def generate(self, req: MotionRequest, on_progress: Any = None, timeout_s: float = 1500.0) -> MotionResult:
        self.requests.append(req)
        if (err := self.script.get(len(self.requests))) is not None:
            raise err
        return await super().generate(req, on_progress, timeout_s)


class Recorder:
    """A job that records what the render reports (the real JobContext only needs progress())."""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.events: list[tuple[float, str, dict[str, Any]]] = []
        self.cancel_after = cancel_after

    async def progress(self, pct: float | None = None, message: str | None = None, step: str | None = None, *, key: str | None = None, params: dict[str, Any] | None = None, force: bool = False) -> None:
        if self.cancel_after is not None and len(self.events) >= self.cancel_after:
            raise JobCancelled()
        self.events.append((pct or 0.0, key or "", params or {}))


@pytest.fixture
async def world(services):
    services.motion = ScriptedClient()
    token = set_ctx(campaign_id=CID, feature="CS-08")  # the HTTP layer does this for every request
    yield services
    reset_ctx(token)


async def run(s: Any, spec: RenderSpec, images: dict[str, bytes], **kw: Any):
    return await generate_clips(s, Studio(s), {"id": CID}, spec, storyboard=None, images=images, **kw)


async def motion_events(s: Any) -> list[dict[str, Any]]:
    return [e for e in await s.meter.events() if e["kind"] == "motion"]


# ------------------------------------------------------------------------------------------------ the happy path and the cache


async def test_every_scene_gets_a_clip_that_is_framed_stored_metered_and_reported(world):
    s = world
    spec, images = make_spec(2)
    out = await run(s, spec, images)
    assert [o.status for o in out.shots] == ["generated", "generated"] and all(o.clip[4:8] == b"ftyp" for o in out.shots)
    for req, sp in zip(s.motion.requests, out.plan.shots, strict=True):
        assert (req.width, req.height, req.num_frames, req.seed) == (1024, 576, sp.frames, sp.seed) and req.prompt == sp.prompt
        assert req.job_id == wire.compute_job_id(req.model, req.revision, req.prompt, req.negative_prompt, req.width, req.height, req.num_frames, req.fps, req.steps, req.guidance_scale, req.seed, req.image_sha256)
    from PIL import Image

    assert Image.open(io.BytesIO(s.motion.requests[0].image)).size == (1024, 576)  # framed to the clip's size here, not by the worker
    rep = out.report()
    assert (rep["shots_total"], rep["shots_generated"], rep["shots_cached"], rep["shots_fallback"]) == (2, 2, 0, [])
    assert rep["gpu_seconds"] > 0 and rep["cost_usd"] == round(pricing.motion_cost(rep["gpu_seconds"], s.settings.motion_price_per_gpu_second), 6)
    assert rep["mode"] == "stub" and rep["model"] == "spotlight-stub-animator" and rep["license"].startswith("n/a")
    assert all(x["status"] == "generated" and x["asset_id"] and x["safety_max"] == 0 for x in rep["shots"])
    events = await motion_events(s)
    assert len(events) == 2 and all(e["units"]["gpu_seconds"] > 0 and not e["cached"] and e["campaign_id"] == CID for e in events)
    assets = await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID)
    assert len(assets) == 2 and all("motion-clip" in a["tags"] and a["meta"]["motion_key"] and a["meta"]["seed"] and a["meta"]["frames"] for a in assets)
    out.apply(spec)
    assert all(sc.clip_asset_id and sc.clip and sc.clip.frames == sp.frames for sc, sp in zip(spec.scenes, out.plan.shots, strict=True))
    assert spec.quality == "cinematic" and spec.motion and [x.seed for x in spec.motion.shots] == [sp.seed for sp in out.plan.shots]


async def test_a_second_run_is_served_from_the_library_for_free(world):
    s = world
    spec, images = make_spec(2)
    first = await run(s, spec, images)
    n_requests, spent = len(s.motion.requests), (await s.meter.summary())["total_usd"]
    again = await run(s, spec, images)
    assert [o.status for o in again.shots] == ["cached", "cached"] and len(s.motion.requests) == n_requests  # the worker was not asked
    assert [o.clip for o in again.shots] == [o.clip for o in first.shots]
    rep = again.report()
    assert (rep["shots_generated"], rep["shots_cached"], rep["gpu_seconds"], rep["cost_usd"]) == (2, 2, 0.0, 0.0)  # cached shots still carry AI motion
    assert (await s.meter.summary())["total_usd"] == spent
    hits = [e for e in await motion_events(s) if e["cached"]]
    assert len(hits) == 2 and all(e["cost_usd"] == 0.0 for e in hits)


async def test_the_cache_follows_the_keyframe_and_the_prompt_not_the_clip_length(world):
    s = world
    spec, images = make_spec(1)
    await run(s, spec, images)
    changed = {"ast_k0": jpeg(99)}  # another keyframe: the old clip does not apply
    assert (await run(s, spec, changed)).shots[0].status == "generated"
    longer = spec.model_copy(deep=True)
    longer.scenes[0].duration = 2.4  # a longer scene needs a longer clip than the cached one
    assert (await run(s, longer, images)).shots[0].status == "generated"
    shorter = spec.model_copy(deep=True)
    shorter.scenes[0].duration = 0.6  # a shorter scene is satisfied by the longer clip that is already there
    assert (await run(s, shorter, images)).shots[0].status == "cached"


async def test_find_cached_picks_the_shortest_clip_that_is_long_enough(world):
    s = world
    st = Studio(s)
    spec, images = make_spec(1)
    plan_shot = (await run(s, spec, images)).plan.shots[0]
    for frames in (plan_shot.frames + 16, plan_shot.frames + 8, plan_shot.frames - 4):  # one too short, two longer than needed
        await st.put_asset(campaign_id=CID, name=f"c{frames}.mp4", data=b"x", mime="video/mp4", kind="video", meta={"motion_key": plan_shot.cache_key, "frames": frames}, index=False)
    hit = await find_cached(st, CID, plan_shot)
    assert hit is not None and hit["meta"]["frames"] == plan_shot.frames  # the one the render stored: exactly long enough
    assert await find_cached(st, "another-campaign", plan_shot) is None


async def test_a_cached_clip_whose_file_is_gone_is_generated_again(world, monkeypatch):
    s = world
    spec, images = make_spec(1)
    await run(s, spec, images)
    st_cls = Studio

    async def gone(self: Studio, asset: dict[str, Any]) -> bytes:
        raise FileNotFoundError(asset["id"])

    monkeypatch.setattr(st_cls, "asset_bytes", gone)
    out = await run(s, spec, images)
    assert [o.status for o in out.shots] == ["generated"] and len(s.motion.requests) == 2


async def test_a_clip_the_worker_had_already_made_costs_no_gpu_time(world):
    s = world

    class AlreadyThere(ScriptedClient):
        async def generate(self, req: MotionRequest, on_progress: Any = None, timeout_s: float = 1500.0) -> MotionResult:
            res = await super().generate(req, on_progress, timeout_s)
            res.cached, res.gpu_seconds = True, 55.0  # the worker answers from its own result store; the recorded 55 s were spent by an earlier job
            return res

    s.motion = AlreadyThere()
    spec, images = make_spec(1)
    out = await run(s, spec, images)
    rep = out.report()
    assert out.shots[0].transport_cached and rep["gpu_seconds"] == 0.0 and rep["cost_usd"] == 0.0 and rep["shots_generated"] == 1
    (event,) = await motion_events(s)
    assert event["cached"] and event["cost_usd"] == 0.0 and event["units"]["gpu_seconds"] == 0.0


# ------------------------------------------------------------------------------------------------ shots that fail


async def test_a_failed_shot_falls_back_to_the_still_while_the_others_still_play(world):
    s = world
    s.motion.script = {2: MotionFailed("CUDA out of memory", worker_code="oom", gpu_seconds=12.0)}
    spec, images = make_spec(3)
    out = await run(s, spec, images)
    assert [o.status for o in out.shots] == ["generated", "fallback", "generated"]
    rep = out.report()
    assert (rep["shots_total"], rep["shots_generated"], len(rep["shots_fallback"])) == (3, 2, 1)
    assert rep["shots_fallback"] == [{"shot_id": "shot_1", "reason": "oom", "detail": "CUDA out of memory"}]
    failed = [e for e in await motion_events(s) if e["units"].get("failed")]
    assert len(failed) == 1 and failed[0]["units"]["gpu_seconds"] == 12.0 and failed[0]["cost_usd"] == round(pricing.motion_cost(12.0, s.settings.motion_price_per_gpu_second), 6)  # the failed attempt still ran on the GPU
    assert rep["gpu_seconds"] == round(sum(o.gpu_seconds for o in out.shots), 2) and rep["gpu_seconds"] > 12.0
    out.apply(spec)
    assert [bool(sc.clip_asset_id) for sc in spec.scenes] == [True, False, True] and spec.motion and len(spec.motion.shots) == 3
    assert set(out.clips) == {"sc-b0", "sc-b2"}  # the compositor plays the still for the shot that fell back


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (MotionTimeout("took too long"), "timeout"),
        (MotionUnavailable("worker unreachable"), "worker_unavailable"),
        (MotionTransportError("queue unreachable"), "worker_unavailable"),
        (MotionDisabled("switched off"), "disabled"),
        (MotionBadRequest("bad request"), "bad_request"),
        (MotionFailed("internal error"), "internal"),
        (MotionFailed("out of memory", worker_code="oom"), "oom"),
        (MotionFailed("worker timed out", worker_code="timeout"), "timeout"),
        (MotionFailed("worker refused", worker_code="bad_request"), "bad_request"),
        (AppError("something else", code="x"), "internal"),
        (RuntimeError("boom"), "internal"),
    ],
)
async def test_every_kind_of_failure_becomes_a_stable_fallback_reason(world, error, reason):
    s = world
    s.motion.script = {1: error}
    spec, images = make_spec(1)
    out = await run(s, spec, images)
    assert out.shots[0].status == "fallback" and out.shots[0].reason == reason and not out.clips
    assert reason in FALLBACK_REASONS and has(f"motion.reason.{reason}", "en") and has(f"motion.reason.{reason}", "pl")


async def test_when_every_shot_fails_the_render_still_has_a_report_and_no_clips(world):
    s = world
    s.motion.script = {1: MotionFailed("nope"), 2: MotionFailed("nope")}
    spec, images = make_spec(2)
    out = await run(s, spec, images)
    rep = out.report()
    assert (rep["shots_generated"], rep["shots_cached"], len(rep["shots_fallback"]), rep["shots_total"]) == (0, 0, 2, 2)
    assert out.clips == {} and rep["gpu_seconds"] == 0.0
    out.apply(spec)
    assert spec.quality == "cinematic" and all(sc.clip_asset_id is None and sc.clip is None for sc in spec.scenes)  # still cinematic by request; the stills play


async def test_two_unreachable_shots_in_a_row_stop_the_asking_but_a_success_resets_the_count(world):
    s = world
    s.motion.script = {1: MotionTimeout("t"), 2: MotionTimeout("t")}
    spec, images = make_spec(4)
    out = await run(s, spec, images)
    assert [o.status for o in out.shots] == ["fallback"] * 4 and len(s.motion.requests) == 2  # the circuit breaker spared the worker the rest
    assert [o.reason for o in out.shots] == ["timeout"] * 4 and "skipped" in out.shots[3].detail
    s.motion = ScriptedClient({1: MotionTimeout("t"), 3: MotionTimeout("t")})  # one success in between: no breaker
    out = await run(s, *make_spec(4, per=0.9))
    assert [o.status for o in out.shots] == ["fallback", "generated", "fallback", "generated"] and len(s.motion.requests) == 4


async def test_a_render_that_used_up_its_motion_time_budget_falls_back_without_calling_the_worker(world, monkeypatch):
    s = world
    monkeypatch.setattr(s.settings, "motion_timeout_s", 2)
    spec, images = make_spec(2)
    out = await run(s, spec, images)
    assert [o.reason for o in out.shots] == ["timeout", "timeout"] and s.motion.requests == []


async def test_a_clip_that_is_not_a_video_is_never_used(world):
    s = world

    class Garbage(ScriptedClient):
        async def generate(self, req: MotionRequest, on_progress: Any = None, timeout_s: float = 1500.0) -> MotionResult:
            res = await super().generate(req, on_progress, timeout_s)
            res.clip = b"definitely not an mp4"
            return res

    s.motion = Garbage()
    out = await run(s, *make_spec(1))
    assert out.shots[0].status == "fallback" and out.shots[0].reason == "internal" and out.shots[0].detail == "the generated clip could not be read as a video" and out.report()["gpu_seconds"] > 0  # the GPU time was spent and is accounted for
    assert await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID) == []


async def test_a_clip_that_content_safety_flags_falls_back_and_is_not_kept(world, monkeypatch):
    s = world

    async def flagged(data: bytes) -> Any:
        from spotlight.core.ai.base import SafetyResult

        return SafetyResult({"Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 6}, provider="stub")

    monkeypatch.setattr(s.safety, "analyze_image", flagged)
    out = await run(s, *make_spec(1))
    shot = out.shots[0]
    assert shot.status == "fallback" and shot.reason == "safety" and (shot.safety_max or 0) >= FLAG_FROM and shot.gpu_seconds > 0
    assert await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID) == [] and out.report()["shots"][0]["safety_max"] >= FLAG_FROM


# ------------------------------------------------------------------------------------------------ budget


async def test_a_budget_refusal_before_the_first_shot_spends_nothing_and_never_calls_the_worker(world):
    s = world
    await s.repo.upsert("campaigns", {"id": CID, "pk": CID, "budget_cap_usd": 0.02})
    before = await s.meter.summary()
    with pytest.raises(BudgetExceeded) as exc:
        await run(s, *make_spec(2))
    assert exc.value.code == "campaign_budget_exceeded"
    assert s.motion.requests == [] and s.motion.warmups == 0
    after = await s.meter.summary()
    assert after["total_usd"] == before["total_usd"] and "motion" not in after["by_kind"]
    assert await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID) == []


async def test_the_daily_cap_refuses_too_and_a_fully_cached_render_needs_no_budget_at_all(world):
    s = world
    spec, images = make_spec(1)
    await run(s, spec, images)
    s.guard.daily_cap = 0.0001  # the day's money is gone
    assert (await run(s, spec, images)).shots[0].status == "cached"  # nothing to authorise
    with pytest.raises(BudgetExceeded) as exc:
        await run(s, *make_spec(2, per=1.4))
    assert exc.value.code == "daily_budget_exceeded"


async def test_a_refusal_in_the_middle_of_a_render_falls_back_for_the_rest(world, monkeypatch):
    s = world
    real, asked = s.guard.authorize, []

    async def authorize(est: float, **kw: Any) -> None:
        if kw.get("kind") == "motion":
            asked.append(est)
            if len(asked) >= 3:  # the up-front check and the first shot pass; the second shot is refused (other jobs spent the money meanwhile)
                raise BudgetExceeded("Daily AI budget reached", code="daily_budget_exceeded")
        await real(est, **kw)

    monkeypatch.setattr(s.guard, "authorize", authorize)
    out = await run(s, *make_spec(3))
    assert [o.status for o in out.shots] == ["generated", "fallback", "fallback"] and [o.reason for o in out.shots[1:]] == ["budget", "budget"]
    assert len(s.motion.requests) == 1


# ------------------------------------------------------------------------------------------------ the cold start and the worker's state


async def test_a_cold_worker_is_woken_once_and_the_estimated_cold_start_is_part_of_the_cost(world):
    s = world
    s.motion.state = "cold"
    out = await run(s, *make_spec(2))
    cold_usd = pricing.motion_cost(s.settings.motion_cold_start_s, s.settings.motion_price_per_gpu_second)
    rep = out.report()
    assert s.motion.warmups == 1 and rep["cold_start_s"] == s.settings.motion_cold_start_s and rep["cold_start_usd"] == round(cold_usd, 6)
    assert rep["cost_usd"] == round(sum(o.cost_usd for o in out.shots) + cold_usd, 6)
    (warm,) = [e for e in await motion_events(s) if e["units"].get("warmup")]
    assert warm["units"]["estimated"] is True and warm["cost_usd"] == round(cold_usd, 6)


async def test_a_ready_worker_costs_no_cold_start_and_an_unreadable_status_does_not_stop_a_render(world):
    s = world
    out = await run(s, *make_spec(1))
    assert out.report()["cold_start_s"] == 0 and s.motion.warmups <= 1 and not [e for e in await motion_events(s) if e["units"].get("warmup")]
    s.motion = ScriptedClient(state="cold")

    async def broken() -> WorkerStatus:
        return WorkerStatus(state="cold", error="storage unreachable")

    s.motion.status = broken  # type: ignore[method-assign]
    out = await run(s, *make_spec(1, per=1.6))  # longer than the clip cached above: generated now
    assert out.shots[0].status == "generated" and out.report()["cold_start_s"] == 0  # no cold start is assumed (or billed) when the state is unknown


async def test_request_warmup_is_authorised_metered_once_and_does_nothing_for_an_awake_worker(world):
    s = world
    s.motion.state = "cold"
    first = await request_warmup(s)
    cold_usd = pricing.motion_cost(s.settings.motion_cold_start_s, s.settings.motion_price_per_gpu_second)
    assert first["requested"] and first["seconds"] == s.settings.motion_cold_start_s and first["cost_usd"] == cold_usd and first["status"].state == "warming"
    second = await request_warmup(s)  # now warming: nothing more to pay
    assert not second["requested"] and second["cost_usd"] == 0.0 and s.motion.warmups == 1
    assert len([e for e in await motion_events(s) if e["units"].get("warmup")]) == 1
    s.motion = ScriptedClient(state="ready")
    assert not (await request_warmup(s))["requested"] and s.motion.warmups == 0
    s.motion = OffMotionClient()
    assert not (await request_warmup(s))["requested"]


async def test_a_warmup_the_budget_does_not_allow_wakes_nothing(world):
    s = world
    s.motion.state = "cold"
    s.guard.daily_cap = 0.01  # a 240 s cold start (~$0.26) does not fit
    with pytest.raises(BudgetExceeded):
        await request_warmup(s)
    assert s.motion.warmups == 0 and s.motion.state == "cold" and await motion_events(s) == []


async def test_status_reports_what_the_ui_needs_and_never_raises(world):
    s = world
    st = await motion_status(s)
    assert (st["mode"], st["available"], st["model"], st["worker"]["state"], st["reason"]) == ("stub", True, "spotlight-stub-animator", "ready", None)
    assert st["price_per_gpu_second"] == s.settings.motion_price_per_gpu_second and st["max_clip_s"] == 5.0 and st["est_cold_start_s"] == s.settings.motion_cold_start_s
    s.motion = OffMotionClient("wan2.2-ti2v-5b")
    off = await motion_status(s)
    assert (off["mode"], off["available"], off["reason"], off["model"]) == ("off", False, "off", "wan2.2-ti2v-5b") and off["license"] == "Apache-2.0"

    async def unreachable() -> WorkerStatus:
        return WorkerStatus(state="cold", error="queue unreachable")

    s.motion = ScriptedClient()
    s.motion.status = unreachable  # type: ignore[method-assign]
    bad = await motion_status(s)
    assert bad["available"] is False and bad["reason"] == "unreachable"


# ------------------------------------------------------------------------------------------------ progress and cancelling


async def test_progress_is_reported_in_catalog_keys_and_only_moves_forward(world):
    s = world
    s.motion.state = "cold"
    job = Recorder()
    await run(s, *make_spec(2), job=job)
    keys = {k for _, k, _ in job.events}
    assert {"job.msg.motion.estimate", "job.msg.motion.warming", "job.msg.motion.shot"} <= keys
    assert all(has(k, "en") and has(k, "pl") for k in keys)
    fractions = [p for p, _, _ in job.events]
    assert fractions == sorted(fractions) and 0.06 <= fractions[0] and fractions[-1] <= 0.55
    est = next(p for _, k, p in job.events if k == "job.msg.motion.estimate")
    assert est["shots"] == 2 and est["cached"] == 0 and est["cost"] > 0
    job2 = Recorder()
    await run(s, *make_spec(2), job=job2)  # the same shots again: every message says "cached"
    assert {"job.msg.motion.cached"} <= {k for _, k, _ in job2.events}


async def test_cancelling_the_job_stops_the_render_instead_of_falling_back(world):
    s = world
    with pytest.raises(JobCancelled):
        await run(s, *make_spec(3), job=Recorder(cancel_after=4))
    assert len(s.motion.requests) < 3  # the cancel arrived while the second clip was being made: the third was never ordered
    s.motion = ScriptedClient({1: JobCancelled()})
    with pytest.raises(JobCancelled):
        await run(s, *make_spec(2, per=0.8))


# ------------------------------------------------------------------------------------------------ honesty about what made the clip


def test_a_fake_pipeline_never_claims_the_licence_of_the_real_model():
    assert license_of(wire.MODEL_ID, wire.MODEL_REVISION) == "Apache-2.0"
    assert license_of(wire.MODEL_ID, "fake").startswith("n/a") and "fake" in license_of(wire.MODEL_ID, "fake")
    assert license_of("some-other-model", "r1", "custom") == "custom" and license_of("", "") == ""


async def test_the_report_names_the_model_that_really_made_the_clips(world):
    s = world

    class FakeWorker(ScriptedClient):
        async def generate(self, req: MotionRequest, on_progress: Any = None, timeout_s: float = 1500.0) -> MotionResult:
            res = await super().generate(req, on_progress, timeout_s)
            res.model, res.revision = wire.MODEL_ID, "fake"  # the worker's test pipeline answered, not Wan
            return res

    s.motion = FakeWorker()
    rep = (await run(s, *make_spec(1))).report()
    assert (rep["model"], rep["revision"]) == (wire.MODEL_ID, "fake") and rep["license"].startswith("n/a")
    assert (await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID))[0]["meta"]["revision"] == "fake"
