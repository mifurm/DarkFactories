"""Cinematic motion — orchestration of the motion phase of a render: library cache, budget, per-shot fallback, content safety and metering.

Offline: the stub animator behind scripted failures, no video compositing (the API tests cover the whole render)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from conftest import needs_cv2, needs_ffmpeg
from spotlight.core.ai import pricing
from spotlight.core.ai.base import reset_ctx, set_ctx
from spotlight.core.ai.stubs import render_stub_scene
from spotlight.core.jobs import JobCancelled
from spotlight.core.studio import Studio
from spotlight.errors import AppError, BudgetExceeded
from spotlight.i18n import has, t
from spotlight.motion import orchestrator, wire
from spotlight.motion import plan as planner
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
    RETRY_SUFFIX,
    find_cached,
    generate_clips,
    license_of,
    motion_status,
    request_warmup,
)
from spotlight.motion.quality import UNKNOWN, MotionQuality, level_for
from spotlight.motion.stub_client import StubMotionClient
from spotlight.video.spec import RenderSpec, SceneSpec
from test_motion_quality import still_clip

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


class Stubborn(ScriptedClient):
    """A model that ignores the prompt: the calls in ``still_calls`` (1-based) return the keyframe as a clip that does not move at all, the other calls animate it."""

    def __init__(self, still_calls: set[int], script: dict[int, BaseException] | None = None) -> None:
        super().__init__(script)
        self.still_calls = still_calls
        self.results: list[MotionResult] = []

    async def generate(self, req: MotionRequest, on_progress: Any = None, timeout_s: float = 1500.0) -> MotionResult:
        res = await super().generate(req, on_progress, timeout_s)
        if len(self.requests) in self.still_calls:
            res.clip = still_clip(req.image, req.width, req.height, req.num_frames, req.fps)
        self.results.append(res)
        return res


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


# ------------------------------------------------------------------------------------------------ the motion gate: a clip that barely moves is made once more


def scripted_scores(monkeypatch: pytest.MonkeyPatch, *scores: float) -> list[bytes]:
    """The gate measures the clips with these non-rigid scores, in order, whatever the clips look like: what is tested is what the orchestrator does with a score.
    Returns the clips it was asked to measure (a measurement the script has no score for fails the test)."""
    seen: list[bytes] = []

    def measure(clip: bytes, work_dir: str | None = None) -> MotionQuality:
        seen.append(clip)
        score = scores[len(seen) - 1]
        return MotionQuality(score, round(score * 3, 3), level_for(score), 25)

    monkeypatch.setattr(orchestrator, "measure_motion", measure)
    return seen


@needs_cv2
async def test_a_clip_that_barely_moves_is_made_again_once_with_the_next_seed_and_the_moving_one_is_kept(world):
    s = world
    s.motion = Stubborn({1})  # the model ignores the prompt the first time: the clip is the keyframe, frozen
    spec, images = make_spec(1)
    out = await run(s, spec, images)
    sp = out.plan.shots[0]
    first, second = s.motion.requests
    assert (first.seed, first.prompt) == (sp.seed, sp.prompt) and second.image == first.image
    assert (second.seed, second.prompt) == ((sp.seed + 1) % 2**32, sp.prompt + RETRY_SUFFIX) and second.job_id != first.job_id
    assert second.job_id == wire.compute_job_id(second.model, second.revision, second.prompt, second.negative_prompt, second.width, second.height, second.num_frames, second.fps, second.steps, second.guidance_scale, second.seed, second.image_sha256)
    (shot,) = out.shots
    assert shot.status == "generated" and shot.attempts == 2 and shot.seed == second.seed and shot.clip == s.motion.results[1].clip  # the clip that moves is the one in the spot
    assert shot.motion is not None and shot.motion.level in {"subtle", "rich"} and (shot.motion.non_rigid or 0.0) >= 0.6
    rep = out.report()
    assert (rep["retries"], rep["shots_low_motion"], rep["shots_generated"], rep["shots_fallback"]) == (1, 0, 1, [])
    row = rep["shots"][0]
    assert row["motion"] == {"non_rigid": shot.motion.non_rigid, "total": shot.motion.total, "level": shot.motion.level, "attempts": 2}
    assert row["seed"] == second.seed and row["prompt_sha256"] == planner.prompt_sha256(second.prompt, sp.negative)  # what made the clip that is kept
    assert row["plan_prompt_sha256"] == planner.prompt_sha256(sp.prompt, sp.negative) != row["prompt_sha256"]  # what the storyboard asked for
    events = await motion_events(s)  # both attempts ran on the GPU: both are metered and both are in the bill of the shot
    assert sorted((e["units"]["shots"], e["units"]["retry"]) for e in events) == [(0, True), (1, False)] and all(e["units"]["gpu_seconds"] > 0 for e in events)
    assert rep["gpu_seconds"] == round(sum(e["units"]["gpu_seconds"] for e in events), 2) and rep["cost_usd"] == pytest.approx(sum(e["cost_usd"] for e in events), abs=1e-6)
    (asset,) = await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID)
    meta = asset["meta"]
    assert (meta["attempts"], meta["seed"], meta["motion_key"], meta["plan_prompt_sha256"]) == (2, second.seed, sp.cache_key, row["plan_prompt_sha256"])
    assert meta["motion_score"] == shot.motion.to_dict() and meta["gpu_seconds"] == rep["gpu_seconds"]  # the library remembers the score and what the clip cost
    out.apply(spec)
    assert spec.motion and spec.motion.shots[0].seed == sp.seed  # the recipe stays the plan's: that is what the library cache and a re-render are keyed on


@needs_cv2
async def test_a_clip_that_moves_is_kept_as_it_is_and_never_made_twice(world):
    s = world
    out = await run(s, *make_spec(2))
    assert len(s.motion.requests) == 2 and [o.attempts for o in out.shots] == [1, 1]
    rep = out.report()
    assert (rep["retries"], rep["shots_low_motion"]) == (0, 0)
    assert all(x["motion"]["level"] in {"subtle", "rich"} and x["motion"]["attempts"] == 1 and x["motion"]["non_rigid"] >= 0.6 for x in rep["shots"])  # the stub animator clears the gate with room to spare
    assert all(a["meta"]["motion_score"]["level"] in {"subtle", "rich"} and a["meta"]["attempts"] == 1 for a in await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID))
    assert [e["units"]["retry"] for e in await motion_events(s)] == [False, False]


@pytest.mark.parametrize(
    ("scores", "second_kept", "level"),
    [((0.10, 0.25), True, "low"), ((0.28, 0.12), False, "low"), ((0.10, 0.60), True, "subtle")],
    ids=["the-retry-moves-more", "the-first-moves-more", "the-retry-is-good"],
)
async def test_the_clip_that_moves_more_is_kept_even_when_neither_is_good(world, monkeypatch, scores, second_kept, level):
    s = world
    s.motion = Stubborn(set())
    seen = scripted_scores(monkeypatch, *scores)
    out = await run(s, *make_spec(1))
    sp, (shot,) = out.plan.shots[0], out.shots
    kept = s.motion.results[1 if second_kept else 0]
    assert seen == [r.clip for r in s.motion.results] and shot.clip == kept.clip  # both clips were measured, the better one is in the spot
    assert (shot.attempts, shot.seed) == (2, (sp.seed + 1) % 2**32 if second_kept else sp.seed) and shot.motion is not None
    assert (shot.motion.non_rigid, shot.motion.level) == (scores[1 if second_kept else 0], level)
    rep = out.report()
    assert (rep["retries"], rep["shots_low_motion"]) == (1, 1 if level == "low" else 0)
    assert (rep["shots"][0]["prompt_sha256"] == rep["shots"][0]["plan_prompt_sha256"]) is (not second_kept)  # only the retry's prompt differs from the plan's
    (asset,) = await Studio(s).repo.query("assets", {"kind": "video"}, pk=CID)
    assert asset["meta"]["seed"] == shot.seed and asset["meta"]["motion_score"]["non_rigid"] == scores[1 if second_kept else 0]


async def test_a_budget_refusal_of_the_retry_keeps_the_first_clip_and_is_no_error(world, monkeypatch):
    s = world
    scripted_scores(monkeypatch, 0.1)
    real, asked = s.guard.authorize, []

    async def authorize(est: float, **kw: Any) -> None:
        if kw.get("kind") == "motion":
            asked.append(est)
            if len(asked) == 3:  # the up-front check and the first attempt pass; the retry is refused (other jobs spent the day's money meanwhile)
                raise BudgetExceeded("Daily AI budget reached", code="daily_budget_exceeded")
        await real(est, **kw)

    monkeypatch.setattr(s.guard, "authorize", authorize)
    out = await run(s, *make_spec(1))
    (shot,) = out.shots
    assert len(asked) == 3 and len(s.motion.requests) == 1  # the refused retry never reached the worker
    assert shot.status == "generated" and shot.attempts == 1 and shot.motion is not None and shot.motion.level == "low"
    rep = out.report()
    assert (rep["retries"], rep["shots_low_motion"], rep["shots_fallback"]) == (0, 1, []) and rep["gpu_seconds"] == shot.gpu_seconds > 0
    assert len(await motion_events(s)) == 1  # nothing was spent on the refused attempt


async def test_a_retry_that_fails_keeps_the_first_clip_and_pays_for_the_gpu_time_it_wasted(world, monkeypatch):
    s = world
    s.motion = ScriptedClient({2: MotionFailed("CUDA out of memory", worker_code="oom", gpu_seconds=7.0)})
    scripted_scores(monkeypatch, 0.1)
    out = await run(s, *make_spec(1))
    (shot,) = out.shots
    assert shot.status == "generated" and shot.attempts == 2 and shot.seed == out.plan.shots[0].seed and shot.motion is not None and shot.motion.level == "low"
    rep = out.report()
    assert (rep["retries"], rep["shots_low_motion"], rep["shots_fallback"]) == (1, 1, [])  # the failed retry is no failed shot
    events = await motion_events(s)
    (failed,) = [e for e in events if e["units"].get("failed")]
    assert failed["units"]["gpu_seconds"] == 7.0 and failed["units"]["retry"] is True and failed["units"]["shots"] == 0
    assert rep["gpu_seconds"] == round(sum(e["units"]["gpu_seconds"] for e in events), 2) and rep["gpu_seconds"] > 7.0


async def test_whatever_goes_wrong_with_the_retry_cannot_cost_the_clip_already_in_hand(world, monkeypatch):
    s = world

    def measure(clip: bytes, work_dir: str | None = None) -> MotionQuality:
        if len(s.motion.requests) > 1:
            raise RuntimeError("a bug in the second measurement")  # measure_motion never raises; this is the net under it
        return MotionQuality(0.1, 0.3, "low", 25)

    monkeypatch.setattr(orchestrator, "measure_motion", measure)
    out = await run(s, *make_spec(1))
    assert len(s.motion.requests) == 2 and out.shots[0].status == "generated" and out.shots[0].attempts == 1 and out.shots[0].clip == out.clips["sc-b0"]
    s.motion = ScriptedClient({2: JobCancelled()})
    spec, _ = make_spec(1)
    with pytest.raises(JobCancelled):  # a cancelled job is not an "unexpected error": it stops the render
        await run(s, spec, {"ast_k0": jpeg(9)})  # another keyframe: nothing in the library to serve it


async def test_the_retry_can_be_switched_off_and_needs_time_left_in_the_motion_budget(world, monkeypatch):
    s = world
    scripted_scores(monkeypatch, 0.1)
    monkeypatch.setattr(s.settings, "motion_retry_low_motion", False)
    out = await run(s, *make_spec(1))
    assert len(s.motion.requests) == 1 and out.shots[0].attempts == 1 and (out.report()["shots_low_motion"], out.report()["retries"]) == (1, 0)
    monkeypatch.setattr(s.settings, "motion_retry_low_motion", True)
    monkeypatch.setattr(s.settings, "motion_timeout_s", 50)  # less than a minute left after the first clip: no time for a second one
    scripted_scores(monkeypatch, 0.1)
    out = await run(s, *make_spec(1, per=2.0))  # (a longer scene than the clip in the library: it is generated)
    assert len(s.motion.requests) == 2 and out.shots[0].attempts == 1  # one more request in total: the shot of this render, no retry of it


async def test_a_clip_that_cannot_be_measured_is_used_as_it_is_and_never_retried(world, monkeypatch):
    s = world
    monkeypatch.setattr(orchestrator, "measure_motion", lambda clip, work_dir=None: UNKNOWN)  # no OpenCV, or a clip it cannot read
    out = await run(s, *make_spec(1))
    assert len(s.motion.requests) == 1 and out.shots[0].status == "generated" and out.shots[0].attempts == 1
    rep = out.report()
    assert rep["shots"][0]["motion"] == {"non_rigid": None, "total": None, "level": "unknown", "attempts": 1} and (rep["shots_low_motion"], rep["retries"]) == (0, 0)


async def test_a_clip_from_the_library_is_neither_generated_nor_measured_again(world, monkeypatch):
    s = world
    seen = scripted_scores(monkeypatch, 0.1, 0.9)  # the first clip barely moves, the retry does: the library keeps the second one together with its score
    spec, images = make_spec(1)
    first = await run(s, spec, images)
    assert len(seen) == 2 and first.shots[0].attempts == 2
    n_requests, spent = len(s.motion.requests), (await s.meter.summary())["total_usd"]
    again = await run(s, spec, images)  # measuring it again would be a third score the script does not have
    (shot,) = again.shots
    assert shot.status == "cached" and len(seen) == 2 and len(s.motion.requests) == n_requests
    assert shot.motion == first.shots[0].motion and (shot.attempts, shot.seed) == (2, first.shots[0].seed)
    rep, before = again.report(), first.report()
    assert (rep["gpu_seconds"], rep["retries"], rep["shots_low_motion"], rep["shots_generated"], rep["shots_cached"]) == (0.0, 0, 0, 1, 1)  # no GPU, and this render made no retry
    assert rep["shots"][0]["motion"] == {"non_rigid": 0.9, "total": 2.7, "level": "subtle", "attempts": 2}  # the clip remembers that it took two attempts
    assert (rep["shots"][0]["seed"], rep["shots"][0]["prompt_sha256"]) == (before["shots"][0]["seed"], before["shots"][0]["prompt_sha256"])
    assert (await s.meter.summary())["total_usd"] == spent


async def test_a_library_clip_from_before_the_gate_is_measured_once_and_remembered(world, monkeypatch):
    s, st = world, Studio(world)
    spec, images = make_spec(1)
    scripted_scores(monkeypatch, 0.9)
    await run(s, spec, images)
    (asset,) = await st.repo.query("assets", {"kind": "video"}, pk=CID)
    del asset["meta"]["motion_score"], asset["meta"]["attempts"]  # a clip generated before the gate existed
    await st.save_asset(asset)
    seen = scripted_scores(monkeypatch, 0.5)
    shot = (await run(s, spec, images)).shots[0]
    assert shot.status == "cached" and shot.attempts == 1 and shot.motion == MotionQuality(0.5, 1.5, "subtle", 25) and len(seen) == 1
    (asset,) = await st.repo.query("assets", {"kind": "video"}, pk=CID)
    assert asset["meta"]["motion_score"]["non_rigid"] == 0.5  # remembered on the asset
    assert (await run(s, spec, images)).shots[0].motion == shot.motion and len(seen) == 1  # and not measured a second time


async def test_the_report_carries_the_gate_for_every_shot_with_a_clip_and_nothing_for_the_others(world, monkeypatch):
    s = world
    s.motion.script = {2: MotionFailed("the worker crashed")}
    scripted_scores(monkeypatch, 0.9, 0.9)
    rep = (await run(s, *make_spec(3))).report()
    assert [x["status"] for x in rep["shots"]] == ["generated", "fallback", "generated"]
    assert [x["motion"] is not None for x in rep["shots"]] == [True, False, True] and all(len(x["plan_prompt_sha256"]) == 64 for x in rep["shots"])
    assert (rep["shots_low_motion"], rep["retries"], rep["shots_generated"], len(rep["shots_fallback"])) == (0, 0, 2, 1)


async def test_a_retry_is_announced_in_catalog_keys_and_the_progress_never_moves_back(world, monkeypatch):
    s = world
    scripted_scores(monkeypatch, 0.1, 0.9, 0.9)  # shot 1 barely moves and is made again, shot 2 is fine
    job = Recorder()
    await run(s, *make_spec(2), job=job)
    retry = [params for _, key, params in job.events if key == "job.msg.motion.retry"]
    assert retry and all(p == {"n": 1, "total": 2} for p in retry)
    fractions = [p for p, _, _ in job.events]
    assert fractions == sorted(fractions) and 0.06 <= fractions[0] and fractions[-1] <= 0.55
    assert has("job.msg.motion.retry", "en") and has("job.msg.motion.retry", "pl")
    assert t("job.msg.motion.retry", "en", n=2, total=3) == "Shot 2/3: the motion is too static — trying again with a different seed"
    assert t("job.msg.motion.retry", "pl", n=2, total=3) == "Ujęcie 2/3: zbyt statyczny ruch — ponawiam z innym ziarnem"
