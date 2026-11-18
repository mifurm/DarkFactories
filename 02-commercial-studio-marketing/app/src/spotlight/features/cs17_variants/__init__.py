"""CS-17 Variant engine & experimentation — variant matrix (hook × CTA × visual × segment), Thompson-sampling budget
allocation, significance testing, auto-pause of losers — running against the performance simulator."""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.base import set_ctx
from ...core.ai.stubs import stub_task
from ...deps import mutate_limit, spend_limit
from ...domain import bandit
from ...domain import perfsim as ps
from ...domain.scorecard import variant_score
from ...errors import NotFound, ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id, now_iso
from ..common import CREW_PREAMBLE, studio

router = APIRouter(prefix="/api/experiments", tags=["CS-17 Variants & Experiments"])
DEFAULT_DIMS = {"hook": ["Human moment first", "Product first", "Question hook"], "cta": ["Find it near you", "Try it today"], "visual": ["Warm kitchen", "Macro pour"]}
HOOK_COPY = {"Human moment first": "Before the house wakes up, there is a quiet hour.", "Product first": "Meet Dawn Roast: medium roast, small batches.", "Question hook": "When did you last start a morning slowly?", "Sensory close-up": "Listen: that is the sound of no rush."}


class VariantScore(BaseModel):
    variant_id: str
    panel_score: int
    rationale: str


class RankOut(BaseModel):
    scores: list[VariantScore]


@stub_task("experiments.rank")
def _stub_rank(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"scores": [{"variant_id": v["id"], "panel_score": variant_score(v["attrs"])["predicted_score"], "rationale": "simulated panel: " + ", ".join(f"{k}={x}" for k, x in v["attrs"].items())} for v in ctx["variants"]]}


class ExperimentIn(BaseModel):
    campaign_id: str
    name: str = Field(default="Dawn Roast variant test", max_length=100)
    dimensions: dict[str, list[str]] | None = None
    seed: int = Field(default=7, ge=1, le=10_000)


def _build_variants(dims: dict[str, list[str]], seed: int) -> list[dict[str, Any]]:
    names = list(dims)
    out = []
    for i, combo in enumerate(itertools.product(*[dims[n] for n in names]), start=1):
        attrs = dict(zip(names, combo, strict=True))
        tr = ps.true_rates(attrs, seed)
        out.append({
            "id": f"v{i:02d}", "attrs": attrs, "label": " · ".join(f"{v}" for v in combo), "status": "active",
            "copy": {"hook_line": HOOK_COPY.get(attrs.get("hook", ""), ""), "cta": attrs.get("cta", ""), "visual": attrs.get("visual", "")},
            "preflight": variant_score(attrs), "alpha": 1.0, "beta": 1.0, "impressions": 0, "clicks": 0, "conversions": 0, "spend": 0.0, "revenue": 0.0, "share": 0.0, "p_best": None,
            "truth": tr,  # simulator ground truth — hidden from API responses unless reveal=true
        })
    return out


def _view(doc: dict[str, Any], reveal: bool = False) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k != "variants"}
    vs = []
    for v in doc["variants"]:
        d = {k: x for k, x in v.items() if k != "truth"}
        d["ctr"] = round(v["clicks"] / v["impressions"], 5) if v["impressions"] else None
        d["cvr"] = round(v["conversions"] / v["clicks"], 5) if v["clicks"] else None
        d["post_mean_ctr"] = round(v["alpha"] / (v["alpha"] + v["beta"]), 5)
        if reveal:
            d["truth"] = v["truth"]
        vs.append(d)
    out["variants"] = vs
    return out


@router.get("")
async def list_experiments(request: Request, campaign_id: str | None = None) -> list[dict[str, Any]]:
    rows = await studio(request).repo.query("experiments", {"campaign_id": campaign_id} if campaign_id else None, order_by="created_at", desc=True, limit=50)
    return [{k: v for k, v in r.items() if k != "variants"} | {"variant_count": len(r["variants"])} for r in rows]


@router.post("", dependencies=[Depends(mutate_limit)])
async def create(request: Request, body: ExperimentIn, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(body.campaign_id)
    dims = body.dimensions or DEFAULT_DIMS
    for k, vals in dims.items():
        if k not in ps.EFFECTS and k not in {"hook", "cta", "visual", "segment"}:
            raise ValidationFailed(f"unsupported dimension {k!r}", code="bad_dimension")
        if not 1 <= len(vals) <= 6:
            raise ValidationFailed("each dimension needs 1–6 values", code="bad_dimension")
    n = int(np.prod([len(v) for v in dims.values()]))
    if n > 48 or n < 2:
        raise ValidationFailed(f"the matrix would have {n} variants; use between 2 and 48", code="bad_matrix")
    doc = {"id": new_id("exp"), "pk": body.campaign_id, "campaign_id": body.campaign_id, "name": body.name, "status": "draft", "dimensions": dims, "variants": _build_variants(dims, body.seed), "seed": body.seed, "hours_done": 0, "history": [], "leader": None, "strategy": "thompson", "created_at": now_iso(), "created_by": actor.name}
    await st.repo.upsert("experiments", doc)
    await st.audit(body.campaign_id, actor, "experiment.created", {"experiment_id": doc["id"]}, {"variants": n})
    return _view(doc)


async def _get(st: Any, exp_id: str) -> dict[str, Any]:
    d = await st.repo.get("experiments", exp_id)
    if not d:
        raise NotFound("experiment not found", code="experiment_not_found")
    return d


@router.get("/{exp_id}")
async def get_experiment(request: Request, exp_id: str, reveal: bool = False) -> dict[str, Any]:
    return _view(await _get(studio(request), exp_id), reveal)


@router.post("/{exp_id}/preflight", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def preflight(request: Request, exp_id: str, _: Actor = Depends(require("generate"))) -> dict[str, Any]:
    """Pre-flight ranking of all variants: heuristics + synthetic panel (predictive/simulated)."""
    s = request.app.state.services
    st = studio(request)
    d = await _get(st, exp_id)
    set_ctx(campaign_id=d["campaign_id"], feature="experiments")
    out = await s.llm.complete(
        task="experiments.rank",
        system=CREW_PREAMBLE + " You simulate an audience panel ranking ad variants. Give each variant a panel score 0-100 and a one-line rationale. This is a simulation used only for ordering.",
        user="Variants:\n" + "\n".join(f"{v['id']}: {v['attrs']}" for v in d["variants"]),
        schema=RankOut,
        context={"variants": d["variants"]},
        max_tokens=2500,
    )
    panel = {x.variant_id: x for x in out.scores}
    for v in d["variants"]:
        pr = panel.get(v["id"])
        h = variant_score(v["attrs"])["predicted_score"]
        v["preflight"] = {**v["preflight"], "panel_score": pr.panel_score if pr else None, "rationale": pr.rationale if pr else "", "predicted_score": round(0.6 * h + 0.4 * (pr.panel_score if pr else h))}
    d["preflight_at"] = now_iso()
    await st.repo.upsert("experiments", d)
    ranked = sorted(d["variants"], key=lambda v: -v["preflight"]["predicted_score"])
    return {"ranking": [{"id": v["id"], "label": v["label"], "predicted_score": v["preflight"]["predicted_score"], "rationale": v["preflight"].get("rationale")} for v in ranked], "label": "Predictive / simulated"}


class SimIn(BaseModel):
    hours: int = Field(default=24, ge=1, le=72)
    impressions_per_hour: int = Field(default=20000, ge=1000, le=200000)
    strategy: str = Field(default="thompson", pattern="^(thompson|uniform)$")
    cpm_usd: float = Field(default=9.0, gt=0, le=60)


@router.post("/{exp_id}/simulate", dependencies=[Depends(mutate_limit)])
async def simulate(request: Request, exp_id: str, body: SimIn | None = None, actor: Actor = Depends(require("performance.write"))) -> dict[str, Any]:
    """Run the allocation loop against the SIMULATED ad platform: hourly Thompson-sampling reallocation + auto-pause."""
    body = body or SimIn()
    st = studio(request)
    d = await _get(st, exp_id)
    rng = np.random.default_rng(int(d["seed"]) * 1000 + d["hours_done"])
    vs = d["variants"]
    k = len(vs)
    alpha = np.array([v["alpha"] for v in vs])
    beta = np.array([v["beta"] for v in vs])
    ctr_t = np.array([v["truth"]["ctr"] for v in vs])
    cvr_t = np.array([v["truth"]["cvr"] for v in vs])
    paused: list[dict[str, Any]] = []
    rows_by_variant: dict[str, dict[str, Any]] = {}
    reward_total = 0.0
    for _h in range(body.hours):
        active = np.array([v["status"] == "active" for v in vs])
        share = bandit.thompson_allocation(alpha, beta, rng, active) if body.strategy == "thompson" else active / max(active.sum(), 1)
        n = rng.multinomial(body.impressions_per_hour, share)
        clicks = rng.binomial(n, ctr_t)
        conv = rng.binomial(clicks, cvr_t)
        alpha += clicks
        beta += n - clicks
        reward_total += float(clicks.sum())
        for i, v in enumerate(vs):
            v["impressions"] += int(n[i])
            v["clicks"] += int(clicks[i])
            v["conversions"] += int(conv[i])
            v["spend"] = round(v["spend"] + n[i] * body.cpm_usd / 1000, 2)
            v["revenue"] = round(v["revenue"] + conv[i] * ps.AOV, 2)
            v["alpha"], v["beta"], v["share"] = float(alpha[i]), float(beta[i]), round(float(share[i]), 4)
            r = rows_by_variant.setdefault(v["id"], {"impressions": 0, "clicks": 0, "conversions": 0, "spend": 0.0, "revenue": 0.0})
            r["impressions"] += int(n[i])
            r["clicks"] += int(clicks[i])
            r["conversions"] += int(conv[i])
            r["spend"] += float(n[i] * body.cpm_usd / 1000)
            r["revenue"] += float(conv[i] * ps.AOV)
        d["hours_done"] += 1
        d["history"].append({"hour": d["hours_done"], "shares": {v["id"]: v["share"] for v in vs}, "impressions": {v["id"]: int(n[i]) for i, v in enumerate(vs)}})
        if body.strategy == "thompson" and d["hours_done"] >= 6 and d["hours_done"] % 3 == 0:
            pb = bandit.prob_best(alpha, beta, rng)
            for vid in bandit.auto_pause_candidates(vs, pb):
                v = next(x for x in vs if x["id"] == vid)
                v["status"], v["paused_at_hour"] = "paused", d["hours_done"]
                paused.append({"id": vid, "hour": d["hours_done"], "label": v["label"]})
                active = np.array([x["status"] == "active" for x in vs])
    pb = bandit.prob_best(alpha, beta, rng)
    for i, v in enumerate(vs):
        v["p_best"] = round(float(pb[i]), 4)
    leader = max(range(k), key=lambda i: alpha[i] / (alpha[i] + beta[i]))
    uniform_reward = float(ctr_t.mean() * body.hours * body.impressions_per_hour)
    sig = []
    ctrl = vs[0]
    for v in vs[1:]:
        z, p = bandit.two_proportion_z(v["clicks"], v["impressions"], ctrl["clicks"], ctrl["impressions"])
        sig.append({"variant_id": v["id"], "vs": ctrl["id"], "z": round(z, 3), "p_value": float(f"{p:.3g}"), "significant": p < 0.05})
    d.update(status="running" if d["hours_done"] < 24 else "completed", strategy=body.strategy, leader={"id": vs[leader]["id"], "label": vs[leader]["label"], "p_best": vs[leader]["p_best"]}, significance=sig,
             last_run={"hours": body.hours, "reward_clicks": round(reward_total), "uniform_expected_clicks": round(uniform_reward), "uplift_vs_uniform_pct": round((reward_total / uniform_reward - 1) * 100, 1) if uniform_reward else None, "paused": paused, "cpm_usd": body.cpm_usd})
    await st.repo.upsert("experiments", d)
    # write the simulated day's metrics into the performance store (CS-18)
    for vid, r in rows_by_variant.items():
        v = next(x for x in vs if x["id"] == vid)
        await st.repo.upsert("performance", {"id": f"{exp_id}-{vid}-{d['hours_done']}", "pk": d["campaign_id"], "campaign_id": d["campaign_id"], "source": "experiment-sim", "date": now_iso()[:10], "platform": "simulated", "variant_id": vid, "experiment_id": exp_id, "attrs": v["attrs"], "views": int(r["impressions"] * 0.35), "completes": int(r["impressions"] * 0.14), **{c: (round(r[c], 2) if c in {"spend", "revenue"} else int(r[c])) for c in ("impressions", "clicks", "conversions", "spend", "revenue")}})
    await st.audit(d["campaign_id"], actor, "experiment.simulated", {"experiment_id": exp_id}, {"hours": body.hours, "strategy": body.strategy, "paused": [p["id"] for p in paused]})
    return {**_view(d), "last_run": d["last_run"]}


@router.post("/{exp_id}/reset", dependencies=[Depends(mutate_limit)])
async def reset(request: Request, exp_id: str, actor: Actor = Depends(require("performance.write"))) -> dict[str, Any]:
    st = studio(request)
    d = await _get(st, exp_id)
    for v in d["variants"]:
        v.update(status="active", alpha=1.0, beta=1.0, impressions=0, clicks=0, conversions=0, spend=0.0, revenue=0.0, share=0.0, p_best=None)
        v.pop("paused_at_hour", None)
    d.update(status="draft", hours_done=0, history=[], leader=None, last_run=None, significance=[])
    for r in await st.repo.query("performance", {"experiment_id": exp_id}, pk=d["campaign_id"]):
        await st.repo.delete("performance", r["id"], pk=r["pk"])
    await st.repo.upsert("experiments", d)
    return _view(d)


@router.get("/{exp_id}/significance")
async def significance(request: Request, exp_id: str, control: str | None = None) -> dict[str, Any]:
    d = await _get(studio(request), exp_id)
    vs = d["variants"]
    ctrl = next((v for v in vs if v["id"] == control), vs[0])
    out = []
    for v in vs:
        if v["id"] == ctrl["id"]:
            continue
        z, p = bandit.two_proportion_z(v["clicks"], v["impressions"], ctrl["clicks"], ctrl["impressions"])
        out.append({"variant_id": v["id"], "label": v["label"], "ctr": round(v["clicks"] / v["impressions"], 5) if v["impressions"] else None, "control_ctr": round(ctrl["clicks"] / ctrl["impressions"], 5) if ctrl["impressions"] else None, "z": round(z, 3), "p_value": float(f"{p:.3g}"), "significant_at_5pct": p < 0.05})
    return {"control": ctrl["id"], "results": out}


FEATURE = Feature(id="CS-17", summary="Variant matrix (hook × CTA × visual × segment), pre-flight ranking, Thompson-sampling allocation, z-test significance, auto-pause of losers, against the performance simulator.", router=router)
