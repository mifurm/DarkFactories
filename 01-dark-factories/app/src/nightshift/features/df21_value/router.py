import asyncio
import json
import logging
import math
import multiprocessing
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from nightshift.core.deps import get_rt
from nightshift.core.http import TokenBuckets, client_ip
from nightshift.features.df21_value.ab import METRICS, ABConfig, run_ab, run_seed, summarize
from nightshift.features.df21_value.calc_specs import override_specs
from nightshift.features.df23_rbac.rbac import Identity, require
from nightshift.sim.config import load_assumptions

router = APIRouter(prefix="/api/value", tags=["DF-21 value"])
log = logging.getLogger("nightshift.value")
BC = Path(__file__).parent / "business_case"


class ABBody(BaseModel):
    n_seeds: int = Field(default=16, ge=3, le=30)
    horizon_h: float = Field(default=8.0, ge=2, le=12)
    intensity: float = Field(default=1.0, ge=0.25, le=1.0)
    plant: str = "KAT-1"
    latency_min: int = Field(default=20, ge=0, le=120)
    window: str = Field(default="late", pattern="^(night|day|late)$")


class CalcBody(BaseModel):
    scenario: str = Field(default="base", pattern="^(conservative|base|upside)$")
    overrides: dict[str, Any] = Field(default_factory=dict, max_length=400)
    sensitivity: bool = True


def _model():
    from nightshift.features.df21_value.business_case import model

    return model


def _assumptions() -> dict[str, Any]:
    return _model().load_assumptions()


def _jobs(rt) -> dict[str, dict[str, Any]]:
    return rt.extras.setdefault("ab_jobs", {})


async def _run_ab_in_worker(cfg: ABConfig, progress) -> dict[str, Any]:
    """The replay is CPU-bound pure Python: in a thread it would hold the GIL and starve the event loop (live simulation, SSE, health probes),
    so it runs in a separate worker process, one seed per task, and only the summary comes back."""
    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    rows: list[dict[str, Any]] = []
    try:
        for seed in cfg.seeds:
            rows.append(await loop.run_in_executor(pool, run_seed, cfg, seed))
            progress(len(rows), len(cfg.seeds))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return summarize(cfg, rows, time.perf_counter() - t0)


async def run_job(rt, cfg: ABConfig, job: dict[str, Any]) -> None:
    def progress(done: int, total: int) -> None:
        job["progress"] = round(done / total, 3)

    try:
        try:
            res = await _run_ab_in_worker(cfg, progress)
        except (BrokenProcessPool, OSError, ImportError) as exc:  # no worker process available: degrade to a thread
            log.warning("A/B worker process unavailable (%s); running in a thread", exc)
            res = await asyncio.to_thread(run_ab, cfg, progress)
        job.update(status="done", progress=1.0, result=res, finished=time.time())
        rt.extras["ab_latest"] = res
        rt.writer.enqueue(
            "jobs",
            {
                "id": job["id"],
                "pk": "ab",
                "status": "done",
                "config": res["config"],
                "elapsed_s": res["elapsed_s"],
                "summary": {
                    k: {
                        "improvement": m["improvement"],
                        "ci_low": m["ci_low"],
                        "ci_high": m["ci_high"],
                        "p": m["p_one_sided"],
                    }
                    for k, m in res["metrics"].items()
                },
            },
        )
    except Exception as exc:
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])


def start_job(rt, cfg: ABConfig) -> dict[str, Any]:
    jobs = _jobs(rt)
    if any(j["status"] == "running" for j in jobs.values()):
        raise HTTPException(409, "an A/B replay is already running")
    job = {
        "id": f"ab-{int(time.time())}",
        "status": "running",
        "progress": 0.0,
        "started": time.time(),
        "config": cfg.__dict__,
    }
    jobs[job["id"]] = job
    while len(jobs) > 8:
        jobs.pop(next(iter(jobs)))
    asyncio.get_event_loop().create_task(run_job(rt, cfg, job))
    return job


@router.post("/ab/run")
async def ab_run(
    body: ABBody, rt=Depends(get_rt), ident: Identity = Depends(require("ab_run", "value.ab_run"))
) -> dict[str, Any]:
    cfg = ABConfig(
        seeds=list(range(101, 101 + body.n_seeds)),
        horizon_h=body.horizon_h,
        intensity=body.intensity,
        plant=body.plant,
        latency_min=body.latency_min,
        window=body.window,
    )
    if body.plant not in rt.settings.plants:
        raise HTTPException(404, "unknown plant")
    job = start_job(rt, cfg)
    return {k: v for k, v in job.items() if k != "result"}


@router.get("/ab/jobs/{job_id}")
async def ab_job(job_id: str, rt=Depends(get_rt)) -> dict[str, Any]:
    job = _jobs(rt).get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    out = {k: v for k, v in job.items() if k != "result"}
    if job["status"] == "done":
        out["result"] = _public(job["result"])
    return out


def _public(res: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: v for k, v in res.items() if k != "rows"},
        "rows": [
            {"seed": r["seed"], "off": {k: r["off"][k] for k in METRICS}, "on": {k: r["on"][k] for k in METRICS}}
            for r in res["rows"]
        ],
    }


@router.get("/ab/latest")
async def ab_latest(rt=Depends(get_rt)) -> dict[str, Any]:
    res = rt.extras.get("ab_latest")
    if res is None:
        running = any(j["status"] == "running" for j in _jobs(rt).values())
        return {"available": False, "running": running}
    return {"available": True, **_public(res)}


@router.get("/assumptions")
async def assumptions() -> dict[str, Any]:
    a = load_assumptions()
    return {
        "simulation": {k: a[k] for k in ("energy", "costs", "faults", "orders", "safety", "time")},
        "plants": a["plants"],
        "ab_design": {
            "warmup_min": 180,
            "fault_schedule": "8 disruptions per seed (bearing wear, tool wear, thermal/quality drift, supplier delay, rush order, price spike, intrusion, jam)",
            "baseline": "FIFO pull MES, hard-wired safety interlocks, periodic manual QC rounds, ERP min/max reorder, run-to-failure maintenance",
            "swarm": "Safety, Predictive Maintenance, Quality, Planner, Materials, Energy agents under the default policy (approvals answered after the assumed latency)",
        },
    }


@router.get("/calculator/meta")
async def calc_meta() -> dict[str, Any]:
    """Everything the calculator needs to render its controls: grouped drivers (core vs expansion levers vs unit prices), lever switches, reference headline."""
    a = _assumptions()
    ref = json.loads((BC / "outputs.json").read_text())
    specs = override_specs(a)
    return {
        "meta": {
            **{
                k: a["meta"][k]
                for k in ("name", "assumptions_version", "currency", "horizon_years", "reference_customer")
            },
            "model_version": ref["model_version"],
        },
        "scenarios": ["conservative", "base", "upside"],
        **specs,
        "reference": {"model_version": ref["model_version"], "headline": ref["headline"]},
        "price_basis": {
            "basis": a["meta"]["price_basis"]["basis"],
            "retrieved_on": a["meta"]["price_basis"]["retrieved_on"],
            "currency": a["meta"]["price_basis"]["currency"],
        },
    }


def _non_finite(v: Any) -> bool:
    if isinstance(v, float):
        return not math.isfinite(v)
    if isinstance(v, list):
        return any(_non_finite(x) for x in v)
    return False


SENS_PER_MIN = 20  # one sensitivity run re-runs the model ~50-370 times (0.1-0.6 s locally, several seconds on the 0.5 vCPU container)
SENS_CACHE_SIZE = 32


@router.post("/calculator/compute")
async def calc_compute(body: CalcBody, request: Request, rt=Depends(get_rt)) -> dict[str, Any]:
    """Runs the vendored business-case model. Validation of every override (ids, ranges, ramp lengths, price meters) is the model's own.

    Plain computations take a few ms. The tornado (``sensitivity=true``) is expensive, so it is cached per input set, runs one at a time
    and is rate-limited per client."""
    for key, value in body.overrides.items():
        if _non_finite(value):
            raise HTTPException(422, f"{key}: finite numbers required")

    async def run() -> dict[
        str, Any
    ]:  # pure function of its inputs: runs off the event loop so the live simulation keeps ticking
        try:
            return await asyncio.to_thread(
                lambda: dict(
                    _model().compute(_assumptions(), body.scenario, body.overrides, with_sensitivity=body.sensitivity)
                )
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, f"model rejected the inputs: {exc}") from exc

    if not body.sensitivity:
        return await run()
    cache: OrderedDict[str, dict[str, Any]] = rt.extras.setdefault("sens_cache", OrderedDict())
    ck = json.dumps([body.scenario, body.overrides], sort_keys=True)
    if ck in cache:
        cache.move_to_end(ck)
        return cache[ck]
    wait = rt.extras.setdefault("sens_buckets", TokenBuckets()).take(
        f"sens:{client_ip(request.scope, request.headers)}", SENS_PER_MIN
    )
    if wait:
        raise HTTPException(
            429,
            f"sensitivity analysis is limited to {SENS_PER_MIN} per minute per client",
            headers={"Retry-After": str(max(1, int(wait + 0.5)))},
        )
    async with rt.extras.setdefault("sens_lock", asyncio.Lock()):
        if ck not in cache:
            cache[ck] = await run()
            while len(cache) > SENS_CACHE_SIZE:
                cache.popitem(last=False)
    return cache[ck]


@router.get("/calculator/from-ab")
async def calc_from_ab(rt=Depends(get_rt)) -> dict[str, Any]:
    """Suggest calculator overrides from the measured A/B improvements (clamped to the model's allowed range)."""
    res = rt.extras.get("ab_latest")
    if res is None:
        raise HTTPException(404, "run the A/B replay first")
    A = _assumptions()["assumptions"]
    m = res["metrics"]
    sug: dict[str, float] = {}
    notes: list[str] = []

    def put(key: str, value: float, note: str) -> None:
        spec = A[key]
        lo, hi = spec.get("min", 0.0), spec.get("max", 1.0)
        sug[key] = round(max(lo, min(hi, value)), 4)
        notes.append(note)

    if m["downtime_h"]["improvement_pct"] is not None and m["downtime_h"]["off_mean"] > 0:
        put(
            "downtime_reduction_pct",
            m["downtime_h"]["improvement_pct"] / 100.0,
            f"measured unplanned-downtime reduction {m['downtime_h']['improvement_pct']:.0f} % (stress fault load)",
        )
    if m["scrap_units"]["improvement_pct"] is not None and m["scrap_units"]["off_mean"] > 0:
        put(
            "scrap_reduction_pct",
            m["scrap_units"]["improvement_pct"] / 100.0,
            f"measured scrap reduction {m['scrap_units']['improvement_pct']:.0f} %",
        )
    put(
        "oee_performance_uplift_pts",
        max(0.0, m["oee"]["improvement"] / 100.0),
        f"measured OEE uplift {m['oee']['improvement']:.1f} pts",
    )
    return {
        "suggested_overrides": sug,
        "notes": notes,
        "caveat": "Measured on a synthetic plant under an assumed fault load (8 disruptions per 8 h): use as an upper-bound illustration, "
        "not a customer forecast. The base case in the business model is deliberately more conservative.",
        "ab_config": res["config"],
    }


@router.get("/calculator/reference")
async def calc_reference() -> dict[str, Any]:
    ref = json.loads((BC / "outputs.json").read_text())

    def summary(r: dict[str, Any]) -> dict[str, Any]:
        h = r["expansion"]["headline"]
        fleet = next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")
        return (
            {k: r["roi"].get(k) for k in ("npv", "roi_pct", "payback_months", "irr_pct")}
            | {"acr_year3": r["acr"]["by_year"][2], "acr_run_rate_year3": r["acr"]["run_rate_year3"]}
            | {
                "expansion_acr_year3": h["acr_year3"],
                "expansion_acr_run_rate": h["acr_run_rate"],
                "expansion_npv": h["npv"],
                "fleet_plants": fleet["plants"],
                "fleet_run_rate_core": fleet["without_levers"]["total"],
                "fleet_run_rate_expansion": fleet["with_levers"]["total"],
            }
        )

    return {
        "model_version": ref["model_version"],
        "currency": ref["currency"],
        "price_retrieved_on": ref["price_retrieved_on"],
        "headline": ref["headline"],
        "scenario_summaries": {s: summary(ref["scenarios"][s]) for s in ref["scenarios"]},
    }


def warm_default(rt) -> None:
    """Pre-compute the default 10-seed replay once so the Value page has data on the first visit (background, ~3 s)."""
    if rt.extras.get("ab_latest") is None and not any(j["status"] == "running" for j in _jobs(rt).values()):
        start_job(rt, ABConfig())
