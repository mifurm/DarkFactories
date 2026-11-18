"""CC-15 Supervisor console: live queues + SLA clocks, active AI/human conversations, sentiment heat map, SLA-risk alerts (raise/clear), AI containment
panel, worker roster, interventions (take over, whisper via CC-08, simulated monitor/barge, presence) and the live event feed (/ws/events)."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.rbac import PERMISSIONS, ROLES, Actor, actor_from_request, require
from ...core.registry import EPIC_D, FeatureInfo
from ...core.security import ws_origin_ok
from ...engine import localize
from ...engine.models import now
from ...engine.routing import QUEUES

FEATURES = [
    FeatureInfo(
        "CC-15", "Supervisor console", EPIC_D, "P0", "/supervisor", "/api/supervisor",
        "Live queues with SLA clocks, AI + human conversations, sentiment heat map, SLA-risk alerts, AI containment panel and interventions (take over, whisper, simulated monitor/barge, approve/deny); role-enforced, live via WebSocket.",
    ),
]  # fmt: skip

router = APIRouter(tags=["supervisor (CC-15)"])
AVG_HANDLE_S = 420.0
RISK_FRACTION = 0.8  # alert when the oldest waiter used 80 % of the SLA or the projected wait exceeds it

DEMO_SCRIPTS = [
    ("de", "web_chat", "Hallo, ich möchte bitte einen Mitarbeiter sprechen. Mein Sofa ist beschädigt angekommen."),
    ("en", "web_chat", "I want to speak to a human about my delivery, this is unacceptable."),
    ("fr", "web_chat", "Je veux parler à un conseiller humain, ma commande est en retard !"),
    ("es", "web_chat", "Quiero hablar con una persona sobre mi reembolso, por favor."),
    ("it", "web_chat", "Vorrei parlare con un operatore, la mia consegna non è mai arrivata."),
    ("nl", "web_chat", "Ik wil graag een medewerker spreken over mijn bestelling."),
    ("pl", "web_chat", "Chcę rozmawiać z konsultantem, moja dostawa się opóźnia."),
    ("pt", "web_chat", "Quero falar com uma pessoa sobre a minha encomenda."),
]  # fmt: skip
# A Polish operator console (request locale pl) fills up with Polish customers only
DEMO_SCRIPTS_PL = [
    ("pl", "web_chat", "Chcę rozmawiać z konsultantem, moja dostawa się opóźnia."),
    ("pl", "web_chat", "To skandal, trzeci raz nikt nie przyjechał! Zgłoszę sprawę do UOKiK i do sądu."),
    ("pl", "web_chat", "Dzień dobry, proszę o połączenie z konsultantem. Moja sofa dotarła uszkodzona."),
    ("pl", "web_chat", "Proszę o rozmowę z człowiekiem w sprawie zwrotu pieniędzy za materac."),
]  # fmt: skip


def _waiting(svc: Any) -> list[Any]:
    return [c for c in svc.store.cache.values() if c.status == "waiting_human" and c.handoff and not c.eval_run_id]


def queue_stats(svc: Any) -> list[dict[str, Any]]:
    t = now()
    workers = svc.ext.setdefault("workers", [])
    by_q: dict[str, list[Any]] = defaultdict(list)
    for c in _waiting(svc):
        by_q[c.queue or "general"].append(c)
    with_human = Counter(c.queue or "general" for c in svc.store.cache.values() if c.status == "with_human" and not c.eval_run_id)
    abandons = Counter(
        (c.queue or "general") for c in svc.store.cache.values()
        if c.status in ("closed", "abandoned") and c.handoff and not c.handoff.get("accepted_at") and t - (c.closed_at or t) < 3600
    )  # fmt: skip
    rows = []
    for q, spec in QUEUES.items():
        waiting = by_q.get(q, [])
        need = set(spec["skills"])
        capable = [w for w in workers if need <= set(w["skills"]) and w["presence"] != "offline"]
        available = [w for w in capable if w["presence"] == "available" and len(w["active"]) < w["capacity"]["chat"]]
        longest = max((t - c.handoff["created_at"] for c in waiting), default=0.0)
        depth = len(waiting)
        projected = (depth * AVG_HANDLE_S / max(1, len(available))) if available else ((depth + 1) * AVG_HANDLE_S / max(1, len(capable)))
        if depth == 0 and available:
            projected = 0.0
        sla = float(spec["sla_s"])
        risk = depth > 0 and (longest >= RISK_FRACTION * sla or projected >= sla)
        rows.append(
            {
                "queue": q, "name": spec["name"], "waiting": depth, "with_human": with_human.get(q, 0), "longest_wait_s": round(longest, 1), "sla_s": spec["sla_s"], "sla_clock_pct": round(100 * longest / sla, 1),
                "projected_wait_s": round(projected, 1), "agents_available": len(available), "agents_capable": len(capable), "abandons_1h": abandons.get(q, 0), "state": "breach" if depth and longest >= sla else "at_risk" if risk else "ok",
                "conversations": [c.id for c in waiting],
            }
        )  # fmt: skip
    return rows


def evaluate_alerts(svc: Any) -> list[dict[str, Any]]:
    """SLA-risk alerts fire per queue when its state is at_risk/breach and clear when the queue is healthy again; history is kept."""
    store: dict[str, Any] = svc.ext.setdefault("sla_alerts", {"active": {}, "history": []})
    t = now()
    for row in queue_stats(svc):
        active = store["active"].get(row["queue"])
        if row["state"] != "ok":
            if active is None:
                store["active"][row["queue"]] = {
                    "id": f"sla-{row['queue']}-{int(t)}", "queue": row["queue"], "name": row["name"], "severity": "critical" if row["state"] == "breach" else "warning", "raised_at": t, "cleared_at": None,
                    "reason": f"oldest wait {row['longest_wait_s']:.0f}s of {row['sla_s']}s SLA; projected wait {row['projected_wait_s']:.0f}s; {row['agents_available']} agent(s) available",
                    "params": {"wait": f"{row['longest_wait_s']:.0f}", "sla": row["sla_s"], "projected": f"{row['projected_wait_s']:.0f}", "agents": row["agents_available"]},  # the reason is re-rendered in the request locale
                    "worst_wait_s": row["longest_wait_s"], "waiting": row["waiting"],
                }  # fmt: skip
            else:
                active["worst_wait_s"] = max(active["worst_wait_s"], row["longest_wait_s"])
                active["waiting"] = row["waiting"]
                active["severity"] = "critical" if row["state"] == "breach" else active["severity"]
        elif active is not None:
            active["cleared_at"] = t
            store["history"] = ([active] + store["history"])[:30]
            del store["active"][row["queue"]]
    return list(store["active"].values())


def heat_map(svc: Any) -> list[dict[str, Any]]:
    rows: dict[str, Counter] = defaultdict(Counter)
    for c in svc.store.cache.values():
        if c.status not in ("active", "waiting_human", "with_human") or c.eval_run_id:
            continue
        key = "AI agent" if c.handler == "ai" else (QUEUES.get(c.queue or "", {}).get("name") or "Human queue")
        rows[key][c.understanding.emotion if c.understanding else "neutral"] += 1
    return [{"key": k, "counts": dict(v), "total": sum(v.values())} for k, v in sorted(rows.items())]


async def containment_panel(svc: Any) -> dict[str, Any]:
    recent = await svc.store.recent(limit=300)
    recent = [r for r in recent if not r.get("eval_run_id") and not r.get("sim")]
    ended = [r for r in recent if r["status"] in ("resolved", "closed")]
    ai_only = [r for r in ended if r["handler"] == "ai"]
    sent = [r["sentiment"] for r in recent]
    return {
        "live_ai": sum(1 for r in recent if r["status"] == "active" and r["handler"] == "ai"), "live_waiting": sum(1 for r in recent if r["status"] == "waiting_human"), "live_with_human": sum(1 for r in recent if r["status"] == "with_human"),
        "ended": len(ended), "ai_contained": len(ai_only), "containment_pct": round(100 * len(ai_only) / len(ended), 1) if ended else None,
        "avg_sentiment": round(sum(sent) / len(sent), 2) if sent else None, "scope": "most recent 300 live (non-simulated) conversations",
    }  # fmt: skip


async def overview(svc: Any) -> dict[str, Any]:
    live = await svc.store.list_live()
    live.sort(key=lambda c: (-(1 if c.handler == "queue" else 0), -c.priority, c.updated_at))
    approvals = await svc.repo.query("approvals", {"status": "pending"}, order_by="created_at", desc=True, limit=20)
    return {
        "ts": now(), "queues": queue_stats(svc), "alerts": evaluate_alerts(svc), "alert_history": svc.ext.get("sla_alerts", {}).get("history", [])[:10],
        "conversations": [svc.store.summary(c) for c in live[:60]], "heat_map": heat_map(svc), "containment": await containment_panel(svc),
        "approvals": [{k: v for k, v in a.items() if k not in ("pk", "_ts", "ttl", "fingerprint")} for a in approvals],
        "workers": [{"id": w["id"], "name": w["name"], "skills": w["skills"], "languages": w["languages"], "presence": w["presence"], "active": len(w["active"])} for w in svc.ext.get("workers", [])],
    }  # fmt: skip


@router.get("/api/supervisor/overview")
async def get_overview(request: Request, _: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    return localize.localize_overview(await overview(request.app.state.services))


@router.get("/api/supervisor/alerts")
async def get_alerts(request: Request, _: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    alerts = {"active": evaluate_alerts(svc), "history": svc.ext.get("sla_alerts", {}).get("history", [])}
    lang = i18n.current_locale()
    return {
        "active": [localize.localize_sla_alert(a, lang) for a in alerts["active"]], "history": [localize.localize_sla_alert(a, lang) for a in alerts["history"]],
        "rule": i18n.msg("sla.rule", lang, pct=int(RISK_FRACTION * 100)),
    }


class TakeoverBody(BaseModel):
    agent_id: str | None = Field(None, max_length=40)


class MonitorBody(BaseModel):
    mode: str = Field("listen", pattern="^(listen|barge|coach)$")


class PresenceBody(BaseModel):
    presence: str = Field(pattern="^(available|busy|offline)$")


class DemoBody(BaseModel):
    count: int = Field(3, ge=1, le=8)


@router.post("/api/supervisor/{conv_id}/takeover")
async def takeover(conv_id: str, body: TakeoverBody, request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if conv.status in ("resolved", "closed", "abandoned"):
        raise HTTPException(409, "conversation already ended")
    agent = body.agent_id or actor.user
    was = conv.handler
    conv = await svc.orchestrator.takeover(conv_id, agent, by_role="supervisor")
    await svc.audit.log("supervisor.takeover", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, detail={"from": was, "to": agent, "history_messages": len(conv.messages)})
    return {"status": conv.status, "handler": conv.handler, "assigned_agent": conv.assigned_agent, "messages_preserved": len(conv.messages)}


@router.post("/api/supervisor/{conv_id}/monitor")
async def monitor(conv_id: str, body: MonitorBody, request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    """Silent monitor / coach / barge. Live for chat (the supervisor receives the conversation feed); simulated for voice (no PSTN, no real audio bridge)."""
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    simulated = conv.channel == "voice"
    await svc.audit.log("supervisor.monitor", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, detail={"mode": body.mode, "simulated": simulated})
    await svc.access_audit.log("transcript.viewed", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, detail={"via": "supervisor.monitor"})
    return {"ok": True, "mode": body.mode, "simulated": simulated, "feed": f"/ws/events?topics=conv:{conv_id}", "note": i18n.msg("sup.monitor.voice_sim") if simulated else i18n.msg("sup.monitor.live")}


@router.post("/api/supervisor/workers/{worker_id}/presence")
async def set_presence(worker_id: str, body: PresenceBody, request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    svc = request.app.state.services
    w = next((x for x in svc.ext.get("workers", []) if x["id"] == worker_id), None)
    if w is None:
        raise HTTPException(404, "worker not found")
    w["presence"] = body.presence
    await svc.audit.log("supervisor.presence", actor=f"{actor.role}:{actor.user}", resource=worker_id, detail={"presence": body.presence})
    return {"id": worker_id, "presence": body.presence}


@router.post("/api/supervisor/demo-traffic")
async def demo_traffic(body: DemoBody, request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    """Starts scripted customer conversations that ask for a human, so the console visibly fills up (no LLM call is needed for the handoff)."""
    svc = request.app.state.services
    started = []
    pool = DEMO_SCRIPTS_PL if i18n.current_locale() == "pl" else DEMO_SCRIPTS
    for i in range(body.count):
        lang, channel, text = pool[(int(time.time()) + i) % len(pool)]
        conv = await svc.orchestrator.start(channel=channel, language=lang, recording_consent="granted", sim=True, tags=["demo-traffic"])
        svc.spawn(svc.orchestrator.handle_message(conv.id, text))
        started.append({"conversation_id": conv.id, "language": lang})
    await svc.audit.log("supervisor.demo_traffic", actor=f"{actor.role}:{actor.user}", detail={"count": body.count})
    return {"started": started}


@router.post("/api/supervisor/demo-traffic/clear")
async def clear_demo(request: Request, actor: Actor = Depends(require("supervisor"))) -> dict[str, Any]:
    """Ends all demo-traffic conversations still open (keeps the console tidy between demos)."""
    svc = request.app.state.services
    closed = 0
    for c in list(svc.store.cache.values()):
        if "demo-traffic" in c.tags and c.status in ("active", "waiting_human", "with_human"):
            await svc.orchestrator.close(c.id, by=f"supervisor:{actor.user}", resolved=False)
            closed += 1
    return {"closed": closed}


# ------------------------------------------------------------------------------------------------ live event feed
TOPIC_PERMISSION = {"supervisor": "supervisor", "agents": "agent.console", "queue": "agent.console", "conv": "agent.console", "approvals": "approvals.decide"}


def topic_allowed(role: str, topic: str) -> bool:
    perms = PERMISSIONS.get(role, set())
    need = TOPIC_PERMISSION.get(topic.split(":", 1)[0])
    return bool(need) and ("*" in perms or need in perms)


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, topics: str = "supervisor", role: str = "customer") -> None:
    """Live event bus for the staff consoles. Topics: supervisor | agents | queue:<id> | conv:<id>. Role is checked against the permission matrix."""
    svc = ws.app.state.services
    if not ws_origin_ok({k.lower(): v for k, v in ws.headers.items()}):
        await ws.close(code=1008)
        return
    role = role if role in ROLES else "customer"
    if svc.settings.auth_mode == "entra":
        role = "customer"  # query-string roles are only honoured by the demo role switcher
    wanted = [t for t in topics.split(",") if t][:6]
    allowed = [t for t in wanted if topic_allowed(role, t)]
    if not allowed:
        await ws.close(code=4403)
        return
    await ws.accept()
    sub = svc.bus.subscribe(allowed, replay=True)
    await ws.send_text(json.dumps({"type": "subscribed", "topics": allowed, "role": role}))
    try:
        while True:
            ev = await sub.get(timeout=15)
            await ws.send_text(json.dumps(ev if ev is not None else {"type": "ping", "ts": now()}, default=str))
    except (asyncio.CancelledError, Exception):
        pass
    finally:
        svc.bus.unsubscribe(sub)


__all__ = ["FEATURES", "actor_from_request", "evaluate_alerts", "overview", "queue_stats", "router"]
