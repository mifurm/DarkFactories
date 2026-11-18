"""CC-14 Workforce forecasting & staffing: interval forecast (seasonal-naive vs Holt-Winters x intraday profile), Erlang-C requirement,
AI-vs-human capacity plan with containment what-ifs, shift schedule recommendation, discrete-event SLA simulation, CSV export."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_D, FeatureInfo
from ...engine import synth, wfm
from ...engine.history_seed import seed_history
from ...engine.routing import QUEUES

FEATURES = [
    FeatureInfo(
        "CC-14", "Workforce forecasting & staffing", EPIC_D, "P1", "/wfm", "/api/wfm",
        "Interval volume forecast per queue (seasonal-naive vs Holt-Winters with daily/weekly seasonality, MAPE backtests), Erlang-C staffing, AI-vs-human capacity plan with containment what-ifs, shift schedule recommendation validated by discrete-event simulation, CSV export.",
    ),
]  # fmt: skip
SEED_ORDER = 61

router = APIRouter(prefix="/api/wfm", tags=["wfm (CC-14)"])
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    return await seed_history(svc, force)


def _slabel(i: int) -> str:
    return f"{i // 2:02d}:{30 * (i % 2):02d}"


async def _days(svc: Any, queue: str) -> list[dict[str, Any]]:
    if queue not in synth.WFM_QUEUES:
        raise HTTPException(404, f"unknown queue '{queue}' (planned queues: {', '.join(synth.WFM_QUEUES)})")
    rows = await svc.repo.query("wfm_history", {"queue": queue}, order_by="date", limit=400)
    if not rows:
        await seed_history(svc)
        rows = await svc.repo.query("wfm_history", {"queue": queue}, order_by="date", limit=400)
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]


def _date_of(days: list[dict[str, Any]], offset: int) -> str:
    return (datetime.strptime(days[-1]["date"], "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")


class PlanBody(BaseModel):
    queue: str = Field("delivery", max_length=20)
    day_offset: int = Field(2, ge=1, le=7)
    containment: float = Field(0.3, ge=0, le=0.6)
    sl_target: float = Field(0.8, ge=0.5, le=0.99)
    sl_seconds: int | None = Field(None, ge=5, le=600)
    shrinkage: float = Field(0.15, ge=0, le=0.5)
    max_occupancy: float = Field(0.88, ge=0.5, le=0.98)
    promo_offsets: list[int] = Field(default_factory=list, max_length=7)
    simulate: bool = True
    method: str = Field("hw", pattern="^(hw|naive)$")


def _sl_seconds(queue: str, body_value: int | None) -> int:
    return body_value or int(QUEUES.get(queue, {}).get("sla_s", 120))


def build_plan(days: list[dict[str, Any]], queue: str, body: PlanBody, *, with_sim: bool = True, offsets: list[int] | None = None) -> dict[str, Any]:
    fc = wfm.forecast_days(days, 7, body.method, tuple(body.promo_offsets))
    aht = synth.WFM_QUEUES[queue]["aht_s"]
    t_s = _sl_seconds(queue, body.sl_seconds)
    out = []
    week_hours = 0.0
    for d in fc["days"]:
        if offsets is not None and d["offset"] not in offsets and d["offset"] != body.day_offset:
            continue
        plan = wfm.plan_day(d["intervals"], aht, containment=body.containment, sl_target=body.sl_target, t_s=t_s, shrinkage=body.shrinkage, max_occupancy=body.max_occupancy)
        sched = wfm.build_schedule(plan["agents_required"])
        week_hours += sched["paid_hours"]
        entry = {"offset": d["offset"], "date": _date_of(days, d["offset"]), "dow": DOW[d["dow"]], "forecast_total": d["total"], "promo": d["promo"], "plan": plan, "schedule": sched}
        if with_sim and d["offset"] == body.day_offset:
            seats = [round(c * (1 - body.shrinkage)) for c in sched["coverage"]]
            entry["simulation"] = {**wfm.simulate(plan["human_volume"], seats, plan["aht_human_s"], t_s), "sl_target": body.sl_target, "t_s": t_s}
            entry["simulation"]["meets_target"] = entry["simulation"]["sl_mean"] >= body.sl_target
        out.append(entry)
    return {"queue": queue, "aht_s": aht, "sl_seconds": t_s, "params": body.model_dump(), "days": out, "week_paid_hours": round(week_hours, 1), "fte_week": round(week_hours / wfm.PAID_H_PER_FTE_WEEK, 1)}


@router.get("/queues")
async def queues(request: Request, _: Actor = Depends(require("wfm.read"))) -> list[dict[str, Any]]:
    svc = request.app.state.services
    out = []
    for q, spec in synth.WFM_QUEUES.items():
        days = await _days(svc, q)
        out.append({"queue": q, "name": QUEUES.get(q, {}).get("name", q), "aht_s": spec["aht_s"], "sl_target": 0.8, "sl_seconds": QUEUES.get(q, {}).get("sla_s", 120), "avg_daily": round(sum(d["total"] for d in days) / len(days), 1), "history_days": len(days), "last_date": days[-1]["date"]})
    return out


@router.get("/history")
async def history(request: Request, queue: str = "delivery", _: Actor = Depends(require("wfm.read"))) -> dict[str, Any]:
    days = await _days(request.app.state.services, queue)
    heat = [[0.0] * wfm.N_INT for _ in range(7)]
    cnt = [0] * 7
    for d in days:
        cnt[d["dow"]] += 1
        for i, v in enumerate(d["intervals"]):
            heat[d["dow"]][i] += v
    heat = [[round(v / max(cnt[dw], 1), 1) for v in row] for dw, row in enumerate(heat)]
    return {"queue": queue, "daily": [{"date": d["date"], "dow": DOW[d["dow"]], "total": d["total"], "event": d.get("event")} for d in days], "heatmap": heat, "intervals": [_slabel(i) for i in range(wfm.N_INT)], "synthetic": True}


@router.get("/forecast")
async def forecast(request: Request, queue: str = "delivery", method: str = Query("hw", pattern="^(hw|naive)$"), promo: str = "", _: Actor = Depends(require("wfm.read"))) -> dict[str, Any]:
    days = await _days(request.app.state.services, queue)
    offsets = tuple(int(x) for x in promo.split(",") if x.strip().isdigit() and 1 <= int(x) <= 7)
    fc = wfm.forecast_days(days, 7, method, offsets)
    bt = wfm.backtest(days)
    band = bt["summary"][method]["mape_daily"] * 1.28
    for d in fc["days"]:
        d["date"] = _date_of(days, d["offset"])
        d["dow_label"] = DOW[d["dow"]]
        d["low"], d["high"] = round(d["total"] * (1 - band), 1), round(d["total"] * (1 + band), 1)
    return {"queue": queue, **fc, "backtest": bt["summary"], "band_pct": round(100 * band, 1), "intervals": [_slabel(i) for i in range(wfm.N_INT)]}


@router.get("/backtest")
async def backtest(request: Request, queue: str | None = None, _: Actor = Depends(require("wfm.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    res = {}
    for q in [queue] if queue else list(synth.WFM_QUEUES):
        res[q] = wfm.backtest(await _days(svc, q))
    return {"queues": res, "method": "rolling origin, 4 folds x 7 days; event days excluded; WAPE on 30-min intervals within 07:00-22:00", "targets": {"mape_daily_max": 0.10, "min_improvement_vs_naive_pct": 15}}


@router.post("/plan")
async def plan(body: PlanBody, request: Request, _: Actor = Depends(require("wfm.read"))) -> dict[str, Any]:
    days = await _days(request.app.state.services, body.queue)
    res = build_plan(days, body.queue, body)
    res["intervals"] = [_slabel(i) for i in range(wfm.N_INT)]
    return res


@router.get("/sweep")
async def sweep(request: Request, queue: str = "delivery", sl_target: float = 0.8, _: Actor = Depends(require("wfm.read"))) -> dict[str, Any]:
    """Containment slider what-if (0-60 %): weekly human FTE, peak agents and the AI capacity Azure has to provide."""
    days = await _days(request.app.state.services, queue)
    rows = []
    for c in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
        body = PlanBody(queue=queue, containment=c, sl_target=sl_target)
        res = build_plan(days, queue, body, with_sim=False)
        tot = [d["plan"]["totals"] for d in res["days"]]
        rows.append({"containment": c, "fte_week": res["fte_week"], "peak_agents": max(t["peak_agents"] for t in tot), "human_contacts_week": round(sum(t["human_contacts"] for t in tot)), "peak_ai_sessions": round(max(t["peak_ai_sessions"] for t in tot), 1), "ai_voice_minutes_week": round(sum(t["ai_voice_minutes"] for t in tot))})
    return {"queue": queue, "rows": rows}


@router.get("/erlang")
async def erlang(calls: float = Query(100, ge=0, le=5000), aht: float = Query(180, ge=10, le=3600), t: float = Query(20, ge=1, le=600), sl: float = Query(0.8, ge=0.5, le=0.999), interval: int = Query(1800, ge=60, le=3600), occupancy: float = Query(1.0, ge=0.3, le=1.0)) -> dict[str, Any]:
    """Erlang-C calculator (public, pure maths)."""
    a = calls * aht / interval
    n = wfm.agents_required(calls, aht, interval_s=interval, sl_target=sl, t_s=t, max_occupancy=occupancy)
    return {"traffic_erlangs": round(a, 3), "agents_required": n, "service_level": round(wfm.service_level(n, a, aht, t), 4) if n else None, "p_wait": round(wfm.erlang_c(n, a), 4) if n else None, "asa_s": round(wfm.asa(n, a, aht), 2) if n else None, "occupancy": round(a / n, 4) if n else None}


@router.get("/export/forecast.csv")
async def export_forecast(request: Request, queue: str = "delivery", _: Actor = Depends(require("wfm.read"))) -> Response:
    days = await _days(request.app.state.services, queue)
    fc = wfm.forecast_days(days, 7, "hw")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["queue", "date", "dow", "interval", "forecast_contacts"])
    for d in fc["days"]:
        for i, v in enumerate(d["intervals"]):
            w.writerow([queue, _date_of(days, d["offset"]), DOW[d["dow"]], _slabel(i), v])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="forecast-{queue}.csv"'})


@router.get("/export/plan.csv")
async def export_plan(request: Request, queue: str = "delivery", containment: float = Query(0.3, ge=0, le=0.6), day_offset: int = Query(2, ge=1, le=7), _: Actor = Depends(require("wfm.read"))) -> Response:
    days = await _days(request.app.state.services, queue)
    res = build_plan(days, queue, PlanBody(queue=queue, containment=containment, day_offset=day_offset), with_sim=False, offsets=[day_offset])
    d = next(x for x in res["days"] if x["offset"] == day_offset)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["queue", "date", "interval", "human_contacts", "agents_required", "heads_scheduled", "coverage", "ai_concurrent_sessions", "ai_voice_minutes"])
    for i in range(wfm.N_INT):
        w.writerow([queue, d["date"], _slabel(i), d["plan"]["human_volume"][i], d["plan"]["agents_required"][i], d["plan"]["heads_scheduled"][i], d["schedule"]["coverage"][i], d["plan"]["ai_concurrent_sessions"][i], d["plan"]["ai_voice_minutes"][i]])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="plan-{queue}-{d["date"]}.csv"'})


@router.get("/callbacks")
async def callbacks(request: Request, _: Actor = Depends(require("wfm.read", "supervisor"))) -> dict[str, Any]:
    """Callbacks scheduled by handoff (CC-07) and outbound (CC-18): the demand WFM must staff for."""
    rows = await request.app.state.services.repo.query("callbacks", order_by="created_at", desc=True, limit=100)
    return {"count": len(rows), "callbacks": [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]}


async def plan_summary(svc: Any, containment: float = 0.3) -> dict[str, Any]:
    """Weekly human FTE across all planned queues with and without AI containment (consumed by CC-13)."""
    totals = {"with_ai": 0.0, "without_ai": 0.0}
    for q in synth.WFM_QUEUES:
        days = await _days(svc, q)
        for key, c in (("with_ai", containment), ("without_ai", 0.0)):
            totals[key] += build_plan(days, q, PlanBody(queue=q, containment=c), with_sim=False)["fte_week"]
    return {"containment": containment, "fte_with_ai": round(totals["with_ai"], 1), "fte_without_ai": round(totals["without_ai"], 1), "fte_saved": round(totals["without_ai"] - totals["with_ai"], 1)}


@router.get("/summary")
async def summary(request: Request, containment: float = Query(0.3, ge=0, le=0.6), _: Actor = Depends(require("wfm.read", "metrics.read"))) -> dict[str, Any]:
    return await plan_summary(request.app.state.services, containment)
