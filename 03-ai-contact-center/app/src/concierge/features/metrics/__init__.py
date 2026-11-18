"""CC-13 CX metrics & ROI view: operational metrics from stored interaction records (synthetic baseline + live conversations) and the ROI / Azure-ACR
calculator that serves the vendored business-case model (`business_case/model.py` + `assumptions.json`)."""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_C, FeatureInfo
from ...engine import metrics as mx
from ...engine.history_seed import load_history
from ...engine.voc import HUMAN_COST_PER_MIN_USD
from .business_case import model as bc_model

FEATURES = [
    FeatureInfo(
        "CC-13", "CX metrics & ROI view", EPIC_C, "P0", "/metrics", "/api/metrics",
        "Containment, verified resolution, AHT, FCR, predicted CSAT, cost per contact and per resolved contact with AI-vs-human comparison, per-queue/interval roll-ups that reconcile, plus the ROI & Azure-ACR calculator (vendored business-case model) with scenarios and tornado.",
    ),
]  # fmt: skip

router = APIRouter(tags=["metrics (CC-13)"])
BC_DIR = Path(bc_model.__file__).resolve().parent
PARITY_TOLERANCE = 0.005
HEADLINE_KEYS = (("roi", "npv"), ("roi", "roi_pct"), ("roi", "payback_months"), ("acr", "run_rate_year3"))
DRIVER_KEYS = ["agents", "contacts_per_year", "voice_share_of_contacts", "cost_per_contact_usd", "ai_containment_pct", "aht_reduction_pct", "attrition_rate", "qa_coverage_target", "discount_rate", "adoption_ramp"]


@lru_cache(maxsize=1)
def assumptions() -> dict[str, Any]:
    return bc_model.load_assumptions(BC_DIR / "assumptions.json")


@lru_cache(maxsize=1)
def reference_outputs() -> dict[str, Any]:
    import json

    return json.loads((BC_DIR / "outputs.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------------- metrics
async def gather(svc: Any, days: int, source: str) -> list[dict[str, Any]]:
    rs: list[dict[str, Any]] = []
    if source in ("all", "synthetic"):
        rs += [{**h, "source": "synthetic"} for h in await load_history(svc)]
    if source in ("all", "live"):
        docs = await svc.repo.query("conversations", {"status": {"$in": ["resolved", "closed"]}}, limit=1500)
        rs += [r for r in (mx.live_record(d) for d in docs) if r]
    if not rs:
        return []
    end = max(r["ts"] for r in rs)
    return [r for r in rs if r["ts"] >= end - days * 86400]


async def build(svc: Any, days: int = 90, source: str = "all") -> dict[str, Any]:
    rs = await gather(svc, days, source)
    cpm = HUMAN_COST_PER_MIN_USD
    overall = mx.kpis(rs, cost_per_min=cpm)
    by_queue = mx.rollup(rs, lambda r: r["queue"], cpm)
    by_hour = mx.rollup(rs, lambda r: r["hour"], cpm)
    by_day = mx.rollup(rs, lambda r: r["date"], cpm)
    by_source = mx.rollup(rs, lambda r: r["source"], cpm)
    cap = None
    if overall.get("contacts"):
        try:
            from ..wfm import plan_summary

            cap = await plan_summary(svc, min(0.6, round(overall["containment_pct"] / 100, 2)))
        except Exception:  # capacity view is optional context
            cap = None
    return {
        "window_days": days, "source": source, "kpis": overall, "ai_vs_human": mx.ai_vs_human(rs, cpm), "by_queue": [{"queue": q, "name": mx.QUEUES.get(q, {}).get("name", q), **v} for q, v in by_queue.items()],
        "by_hour": [{"hour": h, **v} for h, v in by_hour.items()], "daily": [{"date": d, **{k: v[k] for k in ("contacts", "containment_pct", "verified_resolution_pct", "cost_per_contact_usd", "csat_pred")}} for d, v in by_day.items()],
        "by_source": by_source, "reconcile": mx.reconcile(rs, overall, by_queue, by_hour, by_day), "capacity": cap,
        "assumptions": {"human_cost_per_minute_usd": cpm, "basis": "loaded agent cost / productive minutes (business-case assumptions); AI cost = metered Azure cost per interaction (CC-22)", "synthetic_sample_factor": 90},
        "synthetic_note": "Baseline history is synthetic (seeded); live rows come from conversations in this deployment.",
    }  # fmt: skip


@router.get("/api/metrics")
async def metrics_all(request: Request, days: int = 90, source: str = "all", _: Actor = Depends(require("metrics.read"))) -> dict[str, Any]:
    if source not in ("all", "synthetic", "live"):
        raise HTTPException(422, "source must be all | synthetic | live")
    return await build(request.app.state.services, max(1, min(days, 365)), source)


@router.get("/api/metrics/reconcile")
async def metrics_reconcile(request: Request, days: int = 90, source: str = "all", _: Actor = Depends(require("metrics.read"))) -> list[dict[str, Any]]:
    return (await build(request.app.state.services, days, source))["reconcile"]


@router.get("/api/metrics/definitions")
async def definitions(_: Actor = Depends(require("metrics.read"))) -> dict[str, str]:
    return {
        "containment": "share of contacts handled start-to-finish by the AI agent (never handed to a human)",
        "verified_resolution": "contained AND the outcome was confirmed (action executed / answer grounded / customer confirmed) - never higher than containment",
        "aht": "handle time incl. after-call work for humans; conversation duration for the AI agent",
        "fcr": "first-contact resolution: no repeat contact about the same intent within 7 days",
        "csat_pred": "predicted CSAT (1-5) from end-of-contact sentiment",
        "cost_per_resolved": "(human minutes x cost per minute + metered Azure AI cost) / resolved contacts",
        "sla": "share of human-handled contacts answered within the queue SLA; abandon = left the queue before an agent joined",
    }  # fmt: skip


# ------------------------------------------------------------------------------------------------------------- ROI / ACR calculator
def _driver(key: str, a: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    if key == "cost_per_contact_usd":
        v = base["inputs"]["derived"]["cost_per_contact_usd"]
        return {"key": key, "label": "Blended human cost per contact", "unit": "USD per contact", "base": round(v, 2), "low": round(v * 0.7, 2), "high": round(v * 1.3, 2), "kind": "derived", "step": 0.1}
    s = a["assumptions"][key]
    base_v = s.get("base", s.get("value"))
    out = {"key": key, "label": s["label"], "unit": s.get("unit", ""), "base": base_v, "low": s.get("low"), "high": s.get("high"), "kind": s.get("kind"), "rationale": s.get("rationale"), "source": s.get("source")}
    if isinstance(base_v, list):
        out["kind"] = "ramp"
    return out


@router.get("/api/roi/model")
async def roi_model(_: Actor = Depends(require("metrics.read"))) -> dict[str, Any]:
    a = assumptions()
    base = bc_model.compute(a, "base")
    return {
        "model_version": a["meta"].get("model_version"), "scenarios": list(bc_model.SCENARIOS), "stress": list(bc_model.STRESS_SCENARIOS), "drivers": [_driver(k, a, base) for k in DRIVER_KEYS],
        "footnote": {"price_basis": a["meta"].get("price_basis"), "price_date": a["meta"].get("price_date"), "disclaimer": a["meta"].get("disclaimer"), "reference_customer": a["meta"].get("reference_customer")},
        "override_keys": ["agents", "contacts_per_year", "voice_share_of_contacts", "cost_per_contact_usd", "ai_containment_pct", "aht_reduction_pct", "attrition_rate", "qa_coverage_target", "discount_rate", "adoption_ramp", "azure_usage_multiplier", "openai_deployment_type", "rt_full_model_share", "comms_azure_billed_share"],
        "headline_base": _headline(base),
    }  # fmt: skip


def _headline(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "npv_usd": res["roi"]["npv"], "roi_pct": res["roi"]["roi_pct"], "payback_months": res["roi"]["payback_months"], "irr_pct": res["roi"].get("irr_pct"), "acr_year3_usd": res["acr"]["run_rate_year3"],
        "acr_three_year_usd": res["acr"].get("three_year_total"), "benefit_total_usd": res["benefits"]["total"], "cost_total_usd": res["costs"]["total"], "pull_through_ratio": res["acr"].get("pull_through_ratio"),
    }  # fmt: skip


class RoiBody(BaseModel):
    scenario: str = Field("base", pattern="^(conservative|base|upside|stacked_downside|stacked_upside)$")
    overrides: dict[str, Any] = Field(default_factory=dict, max_length=20)


@router.post("/api/roi/compute")
async def roi_compute(body: RoiBody, _: Actor = Depends(require("metrics.read"))) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        res = bc_model.compute(assumptions(), body.scenario, body.overrides or None)
    except KeyError as exc:
        raise HTTPException(422, {"error": "unknown_override", "message": f"unknown assumption key {exc}"}) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, {"error": "invalid_override", "message": str(exc)[:200]}) from exc
    return {
        "scenario": res["scenario"], "headline": _headline(res), "roi": res["roi"], "benefits": res["benefits"], "costs": res["costs"],
        "acr": {k: res["acr"][k] for k in ("by_year", "by_family", "family_labels", "run_rate_year3", "three_year_total", "tiers", "pull_through_ratio", "by_purpose_year3") if k in res["acr"]},
        "tornado": sorted(res["sensitivity"], key=lambda s: -abs(s["delta_at_high"] - s["delta_at_low"]))[:12], "derived": res["inputs"]["derived"], "overrides": body.overrides, "compute_ms": round((time.perf_counter() - t0) * 1000, 1),
        "footnote": "Illustrative and assumption-driven; Azure list prices (pay-as-you-go, no discount). Validate with the customer's own data.",
    }  # fmt: skip


@router.get("/api/roi/scenarios")
async def roi_scenarios(_: Actor = Depends(require("metrics.read"))) -> dict[str, Any]:
    a = assumptions()
    return {s: _headline(bc_model.compute(a, s)) for s in bc_model.SCENARIOS}


def parity_report() -> dict[str, Any]:
    """The calculator must reproduce business-case/outputs.json (all three scenarios) within 0.5 %."""
    a, ref = assumptions(), reference_outputs()
    rows = []
    for scen in bc_model.SCENARIOS:
        res = bc_model.compute(a, scen)
        for sec, key in HEADLINE_KEYS:
            expected, got = ref["scenarios"][scen][sec][key], res[sec][key]
            err = abs(got - expected) / abs(expected) if expected else abs(got)
            rows.append({"scenario": scen, "metric": f"{sec}.{key}", "expected": expected, "calculated": got, "rel_error": err, "ok": err <= PARITY_TOLERANCE})
    return {"tolerance": PARITY_TOLERANCE, "rows": rows, "ok": all(r["ok"] for r in rows), "reference": "business-case/outputs.json", "model_version": a["meta"].get("model_version")}


@router.get("/api/roi/parity")
async def roi_parity(_: Actor = Depends(require("metrics.read"))) -> dict[str, Any]:
    return parity_report()
