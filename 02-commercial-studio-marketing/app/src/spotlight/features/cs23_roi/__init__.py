"""CS-23 ROI & ACR calculator — agency baseline vs Studio: ROI, payback, NPV and Azure ACR by service, using the vendored
business-case model (the SAME model.py / assumptions.json / outputs.json the PRD and deck quote)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...core.ai.meter import cost_per_approved_asset
from ...deps import svc
from ...errors import ValidationFailed
from ...registry import Feature
from ...vendor import model
from ..common import studio

router = APIRouter(prefix="/api/roi", tags=["CS-23 ROI & ACR Calculator"])
VENDOR = Path(__file__).resolve().parents[2] / "vendor"


@lru_cache
def assumptions() -> dict[str, Any]:
    return model.load_assumptions(str(VENDOR / "assumptions.json"))


@lru_cache
def reference_outputs() -> dict[str, Any]:
    return json.loads((VENDOR / "outputs.json").read_text(encoding="utf-8"))


@router.get("/meta")
async def meta() -> dict[str, Any]:
    a = assumptions()
    return {
        "model_version": model.MODEL_VERSION,
        "assumptions_sha256": model.assumptions_hash(a),
        "reference_outputs_sha256": reference_outputs()["meta"]["assumptions_sha256"],
        "customer": reference_outputs()["meta"]["customer"],
        "currency": reference_outputs()["meta"]["currency"],
        "pricing_retrieved_at": reference_outputs()["meta"]["pricing_retrieved_at"],
        "scenarios": list(model.SCENARIOS),
        "overrides": {k: dict(spec) for k, spec in model.override_specs().items() if spec.get("calculator")},
        "advanced": {k: dict(spec) for k, spec in model.override_specs().items() if not spec.get("calculator")},  # every other validated override key, rendered dynamically by the UI
        "all_overrides": list(model.override_specs()),
        "lever_labels": dict(model.LEVER_LABELS),
        "headline": reference_outputs()["meta"]["summary"],
        "tiers": [t.get("label", t.get("id")) if isinstance(t, dict) else t for t in a.get("tiers", [])],
        "disclaimer": "Illustrative business case: every figure derives from business-case/assumptions.json (sources + labelled assumptions). Validate with customer data.",
    }


class ComputeIn(BaseModel):
    scenario: str = Field(default="base", pattern="^(conservative|base|upside)$")
    overrides: dict[str, Any] | None = None


@router.post("/compute")
async def compute(body: ComputeIn) -> dict[str, Any]:
    specs = model.override_specs()
    for k, v in (body.overrides or {}).items():
        if k not in specs:
            raise ValidationFailed(f"unknown override {k!r}", code="bad_override")
        spec = specs[k]
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                raise ValidationFailed(f"override {k!r} must be numeric", code="bad_override")
            if not (spec["min"] <= x <= spec["max"]):
                raise ValidationFailed(f"override {k!r} must be between {spec['min']} and {spec['max']}", code="bad_override")
    return model.compute(assumptions(), body.scenario, body.overrides)


def _close(a: float | None, b: float | None) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= max(0.005 * abs(b), 1e-6))


@router.get("/reference")
async def reference() -> dict[str, Any]:
    """The published reference outputs + a live parity check (recompute every scenario and compare with outputs.json within 0.5%)."""
    ref = reference_outputs()
    parity: list[dict[str, Any]] = []

    def check(scenario: str, metric: str, live_v: float | None, published: float | None) -> None:
        parity.append({"scenario": scenario, "metric": metric, "live": live_v, "published": published, "ok": _close(live_v, published)})

    for sc in model.SCENARIOS:
        live = model.compute(assumptions(), sc)
        pub = ref["scenarios"][sc]
        summary = ref["meta"]["summary"][sc]
        for key in ("npv", "roi_pct", "payback_months", "irr_pct"):
            check(sc, key, live["roi"][key], pub["roi"][key])
        for year in (1, 2, 3):
            check(sc, f"acr_year{year}", live["acr"]["by_year"][year], pub["acr"]["by_year"][year])
        check(sc, "acr_run_rate_year3", live["acr"]["run_rate_year3"], pub["acr"]["run_rate_year3"])
        tier = next(t for t in live["acr"]["tiers"] if t["tier"] == "enterprise_scale")
        check(sc, "enterprise_tier_acr_run_rate", tier["acr_run_rate_usd"], summary["enterprise_tier_acr_run_rate_usd"])
        full = model.compute(assumptions(), sc, {"expansion_scale": 1.0})
        check(sc, "full_expansion_acr_year3", full["acr"]["by_year"][3], summary["full_expansion_acr_by_year"][3])
        check(sc, "full_expansion_npv", full["roi"]["npv"], summary["full_expansion_npv"])
    return {"summary": ref["meta"]["summary"], "meta": ref["meta"], "parity": parity, "parity_ok": all(p["ok"] for p in parity)}


@router.get("/live")
async def live(request: Request) -> dict[str, Any]:
    """Studio vs agency baseline, measured on THIS deployment: metered $/approved asset, cycle time, variants per campaign."""
    s = svc(request)
    st = studio(request)
    camps = await st.repo.query("campaigns")
    assets = await st.repo.query("assets", {"kind": "video", "status": "approved"}, limit=2000)
    spend = 0.0
    cycle_hours: list[float] = []
    for c in camps:
        spend += await s.meter.campaign_total(c["id"])
        entries = await s.audit.entries(c["id"])
        start = next((e["ts"] for e in entries if e["action"] == "campaign.created"), None)
        end = next((e["ts"] for e in reversed(entries) if e["action"] == "approval.approve" and e["subject"].get("stage") == "final"), None)
        if start and end:
            from ...util import parse_iso

            cycle_hours.append((parse_iso(end) - parse_iso(start)).total_seconds() / 3600)  # type: ignore[operator]
    a = assumptions()["assumptions"]
    entry = a.get("baseline_cost_adapted_video", {})
    baseline = float(model._pick(entry, "base")) if isinstance(entry, dict) else 0.0
    kpi = cost_per_approved_asset(spend, len(assets), baseline or 1850.0)
    exps = await st.repo.query("experiments")
    by_kind = (await s.meter.summary())["by_kind"]
    return {
        "kpi": kpi,
        "agency_baseline_source": "business-case/assumptions.json → baseline_cost_adapted_video (base)",
        "cycle_time_hours_measured": round(sum(cycle_hours) / len(cycle_hours), 2) if cycle_hours else None,
        "cycle_time_reference": "Agency baseline: 6–10 weeks from brief to final delivery (brief §4).",
        "variants_per_campaign": round(sum(len(e["variants"]) for e in exps) / max(1, len({e["campaign_id"] for e in exps})), 1) if exps else 0,
        "azure_consumption_today_usd": {k: v["cost_usd"] for k, v in by_kind.items()},
        "approved_assets": len(assets),
        "simulated_prices": s.meter.simulated,
        "note": "Metered AI consumption of this demo deployment at list-price estimates; the full ACR model is computed by /api/roi/compute.",
    }


FEATURE = Feature(id="CS-23", summary="ROI / payback / NPV and Azure ACR by service from the vendored business-case model (parity-tested against outputs.json), plus a live agency-vs-Studio comparison from the metered deployment.", router=router)
