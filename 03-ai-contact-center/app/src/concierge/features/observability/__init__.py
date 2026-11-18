"""CC-22 Observability & FinOps: latency SLOs (chat TTFT, turn time, voice turn latency) with burn, per-interaction metering and cost per resolved contact,
price table (and its relation to the business-case unit prices), recent traces (relay -> model), PII-safe logging self-test, health summary."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.ai.usage import PRICES
from ...core.config import APP_VERSION, STARTED_AT
from ...core.rbac import Actor, require
from ...core.registry import EPIC_E, FeatureInfo
from ...core.telemetry import JsonFormatter

FEATURES = [
    FeatureInfo(
        "CC-22", "Observability & FinOps", EPIC_E, "P1", "/observability", "/api/observability",
        "Per-interaction metering (tokens, audio seconds, tool calls, estimated $), cost per resolved contact, latency SLOs with burn (chat TTFT, voice turn latency), traces from relay to model, OpenTelemetry to Application Insights, PII-redacted logs, daily AI budget guard.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/observability", tags=["observability (CC-22)"])

SLOS = [
    {"id": "chat_ttft", "name": "Chat time-to-first-token (visible answer)", "unit": "ms", "p50_target": 2500, "p95_target": 6000, "objective": 0.95, "note": "includes tool rounds before the first answer token"},
    {"id": "chat_ttft_notools", "name": "Chat TTFT - turns without tool calls (pure model latency)", "unit": "ms", "p50_target": 1500, "p95_target": 3000, "objective": 0.95, "note": "answers straight from the model / KB"},
    {"id": "chat_turn", "name": "Chat turn completion time", "unit": "ms", "p50_target": 4000, "p95_target": 12000, "objective": 0.95, "note": "request to final token incl. guard + groundedness"},
    {"id": "voice_first_audio", "name": "Voice turn latency (end of speech -> first audio)", "unit": "ms", "p50_target": 1200, "p95_target": 2000, "objective": 0.95, "note": "natural conversation aims at < 800 ms; gpt-realtime-2.1-mini measured ~1.0-1.9 s through the relay"},
]  # fmt: skip


def pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[int(q * (len(s) - 1))], 1)


async def conversations(svc: Any, limit: int = 400) -> list[dict[str, Any]]:
    docs = await svc.repo.query("conversations", order_by="updated_at", desc=True, limit=limit)
    return [d for d in docs if not d.get("eval_run_id")]


def slo_status(spec: dict[str, Any], vals: list[float]) -> dict[str, Any]:
    bad = sum(1 for v in vals if v > spec["p95_target"])
    allowed = 1 - spec["objective"]
    burn = (bad / len(vals)) / allowed if vals else 0.0
    p50, p95 = pct(vals, 0.5), pct(vals, 0.95)
    return {
        **spec, "samples": len(vals), "p50": p50, "p95": p95, "max": round(max(vals), 1) if vals else None, "over_threshold": bad, "burn_rate": round(burn, 2),
        "status": "no data" if not vals else ("ok" if burn <= 1 and (p95 or 0) <= spec["p95_target"] else "burning"), "p50_ok": None if p50 is None else p50 <= spec["p50_target"], "p95_ok": None if p95 is None else p95 <= spec["p95_target"],
    }  # fmt: skip


async def slo_samples(svc: Any) -> dict[str, list[float]]:
    ttft: list[float] = []
    ttft_nt: list[float] = []
    turn: list[float] = []
    voice: list[float] = list(svc.meter.latency.get("voice_turn", []))
    for d in await conversations(svc):
        turn += (d.get("metrics") or {}).get("turn_ms", [])
        voice += (d.get("metrics") or {}).get("voice_latency_ms", []) if not svc.meter.latency.get("voice_turn") else []
        for m in d.get("messages", []):
            t = (m.get("meta") or {}).get("ttft_ms")
            if m.get("role") == "agent_ai" and t is not None:
                ttft.append(t)
                if not m.get("tools"):
                    ttft_nt.append(t)
    return {"chat_ttft": ttft, "chat_ttft_notools": ttft_nt, "chat_turn": turn, "voice_first_audio": voice}


@router.get("/slo")
async def slo(request: Request, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    samples = await slo_samples(svc)
    mode = "azure" if svc.settings.is_azure else "offline stub (latencies are not representative)"
    return {"slos": [slo_status(s, samples[s["id"]]) for s in SLOS], "mode": mode, "window": "most recent 400 live conversations + in-process voice samples", "burn_definition": "share of samples above the p95 threshold divided by the error budget (1 - objective); > 1 means the budget is burning faster than allowed"}


@router.get("/metering")
async def metering(request: Request, limit: int = 40, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    snap = svc.meter.snapshot()
    rows = []
    ended = metered = resolved = 0
    cost_resolved = 0.0
    for d in await conversations(svc, 300):
        tools = sum(len(m.get("tools", [])) for m in d.get("messages", []))
        u = d.get("usage") or {}
        is_ended = d.get("status") in ("resolved", "closed")
        ai_used = any(m.get("role") == "agent_ai" and not (m.get("flags") and "disclosure" in m["flags"] and len(d["messages"]) <= 2) for m in d.get("messages", []))
        if is_ended and ai_used and d.get("handler") is not None:
            ended += 1
            metered += 1 if u.get("calls", 0) > 0 or u.get("cost_usd", 0) > 0 else 0
            if d.get("status") == "resolved":
                resolved += 1
                cost_resolved += u.get("cost_usd", 0.0)
        rows.append({"conversation_id": d["id"], "channel": d.get("channel"), "status": d.get("status"), "tool_calls": tools, "input_tokens": int(u.get("input_tokens", 0)), "output_tokens": int(u.get("output_tokens", 0)), "audio_seconds": round(u.get("audio_seconds", 0), 1), "calls": int(u.get("calls", 0)), "cost_usd": round(u.get("cost_usd", 0.0), 5), "updated_at": d.get("updated_at")})  # fmt: skip
    cost_all = sum(r["cost_usd"] for r in rows)
    return {
        "budget": {k: snap[k] for k in ("day", "budget_usd", "spent_usd", "remaining_usd", "budget_pct", "status", "blocked_calls")}, "by_model": snap["by_model"], "by_feature": snap["by_feature"], "conversations": rows[: max(1, min(limit, 100))],
        "completeness": {"ended_conversations_with_ai": ended, "metered": metered, "pct": round(100 * metered / ended, 1) if ended else 100.0, "target_pct": 100},
        "cost_per_resolved_contact_usd": round(cost_resolved / resolved, 4) if resolved else None, "avg_cost_per_conversation_usd": round(cost_all / len(rows), 5) if rows else None, "price_table": snap["price_table"],
    }  # fmt: skip


@router.get("/pricing")
async def pricing(request: Request, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    """Unit prices used by the live meter and how they relate to the business-case price list (`assumptions.json -> unit_prices`)."""
    from ..metrics import assumptions

    bc = assumptions()["unit_prices"]
    cmp = []
    for model, key_in, key_out in (("gpt-5.4-mini", "chat_mini_in", "chat_mini_out"), ("gpt-5.4", "chat_full_in", "chat_full_out"), ("gpt-5.4-nano", "nano_in", "nano_out")):
        p = PRICES["models"][model]
        cmp.append({"model": model, "meter_in": p["in"], "meter_out": p["out"], "business_case_global_in": bc[key_in]["global"], "business_case_global_out": bc[key_out]["global"], "business_case_datazone_in": bc[key_in]["datazone"], "business_case_datazone_out": bc[key_out]["datazone"]})
    for model, a_in, a_out in (("gpt-realtime-2.1-mini", "rt_mini_audio_in", "rt_mini_audio_out"), ("gpt-realtime-2.1", "rt_full_audio_in", "rt_full_audio_out")):
        p = PRICES["models"][model]
        cmp.append({"model": model + " (audio)", "meter_in": p["audio_in"], "meter_out": p["audio_out"], "business_case_global_in": bc[a_in]["global"], "business_case_global_out": bc[a_out]["global"], "business_case_datazone_in": bc[a_in]["datazone"], "business_case_datazone_out": bc[a_out]["datazone"]})
    return {"meter": PRICES, "comparison": cmp, "note": "The live meter prices the Global Standard deployments actually used; the business case lists Global and EU Data Zone prices (about 10 % higher) - both from the Azure Retail Prices API, validate before quoting."}


@router.get("/traces")
async def traces(request: Request, kind: str = "", limit: int = 15, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    return {"traces": svc.traces.recent(kind, limit), "buffer": len(svc.traces.spans), "exported_to_app_insights": bool(svc.traces.export_otel), "hint": "kind=voice follows a voice turn from the relay to the model; kind=chat shows agent turns with their tool calls"}


@router.get("/traces/{trace_id}")
async def one_trace(trace_id: str, request: Request, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    spans = request.app.state.services.traces.trace(trace_id)
    if not spans:
        raise HTTPException(404, "trace not found")
    return {"trace_id": trace_id, "spans": spans}


@router.get("/log-redaction")
async def log_redaction(_: Actor = Depends(require("metrics.read", "audit.read", "security.read"))) -> dict[str, Any]:
    """Self-test: the structured-log formatter is fed a message containing a card number, e-mail and phone; the JSON line shows what would be logged."""
    raw = "customer anna.becker@example.com paid with 4111 1111 1111 1111, call +49 30 5550 4412 about order CH-100231"
    rec = logging.LogRecord("concierge.demo", logging.INFO, __file__, 0, raw, (), None)
    line = JsonFormatter().format(rec)
    leaks = [s for s in ("anna.becker@example.com", "4111 1111 1111 1111", "5550 4412") if s in line]
    return {"input": raw, "logged": json.loads(line), "leaks": leaks, "passed": not leaks}


@router.get("/health")
async def health(request: Request, _: Actor = Depends(require("metrics.read", "audit.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    ready = (svc.ready_cache.get("v") or (0, 0, {}))[2]
    return {
        "version": APP_VERSION, "build": svc.settings.build_id, "mode": svc.settings.mode, "region": svc.settings.region, "uptime_s": round(time.time() - STARTED_AT), "readyz": ready.get("checks") if isinstance(ready, dict) else None, "seed": svc.seed_state.get("status"),
        "telemetry": {"application_insights": bool(svc.settings.app_insights_connection), "exporter": "azure-monitor-opentelemetry (managed identity ingestion)" if svc.settings.app_insights_connection else "disabled (offline)", "log_analytics_cap": "1 GB/day"},
        "repository": svc.repo.kind, "event_bus_subscribers": svc.bus.subscriber_count(),
    }  # fmt: skip
