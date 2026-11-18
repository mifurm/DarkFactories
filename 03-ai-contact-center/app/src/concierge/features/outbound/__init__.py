"""CC-18 Proactive & outbound engagement: event-triggered outreach (shipment delayed, appointment reminder) with consent evidence, opt-out, quiet hours
(recipient time zone), frequency caps, campaign controls + kill switch, callbacks and a simulated delivery outbox (no PSTN / SMS / e-mail provider)."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.rbac import Actor, require
from ...core.registry import EPIC_D, FeatureInfo
from ...engine import outbound as ob

FEATURES = [
    FeatureInfo(
        "CC-18", "Proactive & outbound engagement", EPIC_D, "P2", "/outbound", "/api/outbound",
        "Event-triggered outreach (shipment delay, appointment reminder) only with valid consent: opt-outs, quiet hours by recipient time zone, frequency caps, campaign pause/kill-switch, callbacks and full audit; delivery is simulated.",
    ),
]  # fmt: skip
SEED_ORDER = 35

router = APIRouter(prefix="/api/outbound", tags=["outbound (CC-18)"])
DEMO_OVERRIDES = {  # deterministic personas for the demo narrative
    "CU-1005": {"sms": True, "email": True, "voice": False}, "CU-1006": {"sms": True, "email": False, "voice": True}, "CU-1003": {"sms": True, "email": True, "voice": False},
    "CU-1001": {"sms": True, "email": True, "voice": False}, "CU-1004": {"sms": False, "email": True, "voice": False}, "CU-1007": {"sms": True, "email": True, "voice": False},
}  # fmt: skip
DEMO_OPT_OUT = {"CU-1002"}  # opted out of everything - must never be contacted


def _strip(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in ("pk", "_ts", "ttl")}


async def seed(svc: Any, force: bool) -> dict[str, Any]:
    n = 0
    custs = await svc.repo.query("bo_customers")
    anchor = time.time() - 120 * 86400
    for i, c in enumerate(sorted(custs, key=lambda x: x["id"])):
        mc = {**(c.get("marketing_consent") or {}), **DEMO_OVERRIDES.get(c["id"], {})}
        consents = {ch: {"granted": bool(mc.get(ch, False)), "ts": anchor if mc.get(ch) else None, "source": "preference-centre (checkout)", "text_version": ob.CONSENT_TEXT_VERSION} for ch in ob.CHANNEL_ORDER}
        opt_out = {"all": True, "ts": anchor + 30 * 86400, "reason": "customer request (STOP)", "channels": ob.CHANNEL_ORDER} if (c["id"] in DEMO_OPT_OUT or (i % 11 == 5 and c["id"] not in DEMO_OVERRIDES)) else {"all": False, "channels": []}
        await svc.repo.put("contact_prefs", {"id": c["id"], "customer_id": c["id"], "market": c["market"], "timezone": ob.TZ.get(c["market"]), "consents": consents, "opt_out": opt_out, "updated_at": time.time()})
        n += 1
    for camp in ob.DEFAULT_CAMPAIGNS:
        if force or await svc.repo.get("campaigns", camp["id"]) is None:
            await svc.repo.put("campaigns", {**camp, "created_at": time.time()})
    if await svc.repo.get("settings", "outbound") is None:
        await svc.repo.put("settings", {"id": "outbound", "kill_switch": False})
    return {"contact_prefs": n}


async def _kill(svc: Any) -> bool:
    return bool((await svc.repo.get("settings", "outbound") or {}).get("kill_switch"))


async def _outreach(svc: Any, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return await svc.repo.query("campaigns", {"type": "outreach", **(where or {})}, order_by="ts", desc=True, limit=1000)


async def _compose(svc: Any, trigger: str, cust: dict[str, Any], lang: str, slots: dict[str, Any], use_llm: bool) -> tuple[str, str]:
    """The same agent stack writes the message (LLM when available) and the same guard layer checks it; templates are the fallback."""
    fallback = ob.render(trigger, lang, first_name=cust["first_name"], **slots)
    if not use_llm or getattr(svc.llm, "deterministic", True):
        return fallback, "template"
    try:
        res = await svc.llm.chat(
            [
                {"role": "system", "content": f"You write a proactive customer notification for Contoso Home Retail in language code '{lang}'. Max 330 characters, friendly, plain text. Required: greet by first name, state the facts given, offer to reply to reschedule/ask a question/request a callback, say it is an automated message from Concierge, the AI assistant, and end with the opt-out instruction (reply STOP). Never promise compensation, refunds or exact times beyond the facts."},
                {"role": "user", "content": f"Event: {trigger}. First name: {cust['first_name']}. Facts: {slots}."},
            ],
            role="nano", max_tokens=260, reasoning_effort=None, feature="outbound",
        )  # fmt: skip
        text = res.text.strip()
        og = svc.guard.inspect_output(text, lang=lang)
        if og.issues or len(text) < 40 or slots["order_id"] not in text or "STOP" not in text.upper():
            return fallback, "template (guard fallback)"
        return og.text, "llm+guard"
    except Exception:
        return fallback, "template"


async def _send(svc: Any, campaign: dict[str, Any], trigger: str, cust: dict[str, Any], dec: ob.Decision, slots: dict[str, Any], now_ts: float, use_llm: bool) -> dict[str, Any]:
    lang = cust.get("language", "en")
    text, composed_by = await _compose(svc, trigger, cust, lang, slots, use_llm)
    conv = await svc.orchestrator.start(channel="web_chat", language=lang, recording_consent="pending", disclose=False, tags=["outbound", campaign["id"]])
    async with svc.store.lock(conv.id):
        conv.customer_label = cust["first_name"]
        conv.entities["order_id"] = slots["order_id"]
        conv.entities["outbound_trigger"] = trigger
        conv.add("agent_ai", text, lang=lang, flags=["outbound", "disclosure"], meta={"campaign": campaign["id"], "channel": dec.channel, "composed_by": composed_by})
        conv.consent.ai_disclosure_shown_at = time.time()
        await svc.store.save(conv)
    delivery = {"simulated": True, "channel": dec.channel, "placed_on_pstn": False, "note": "no SMS/e-mail/voice provider is connected in the reference build"}
    return {"conversation_id": conv.id, "message": text, "composed_by": composed_by, "delivery": delivery, "link": f"/widget?c={conv.id}"}


async def _record(svc: Any, campaign: dict[str, Any], cust: dict[str, Any], trigger: str, dec: ob.Decision, slots: dict[str, Any], now_ts: float, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = {
        "id": f"out-{uuid.uuid4().hex[:10]}", "type": "outreach", "campaign_id": campaign["id"], "trigger": trigger, "customer_id": cust["id"], "market": cust["market"], "ts": now_ts,
        "slots": slots, **dec.to_dict(), **(extra or {}),
    }  # fmt: skip
    await svc.repo.put("campaigns", doc, ttl=90 * 86400)
    await svc.audit.log(f"outbound.{dec.decision}", actor="system:outbound", resource=cust["id"], conv_id=doc.get("conversation_id"), outcome="ok" if dec.decision == "sent" else "blocked", detail={"campaign": campaign["id"], "trigger": trigger, "reason": dec.reason, "channel": dec.channel, "consent": dec.consent, "checks": dec.checks, "scheduled_for": dec.scheduled_for, "order_id": slots.get("order_id")})
    return doc


def _fmt_date(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d") if ts else "TBC"


async def _candidates(svc: Any, trigger: str, carrier: str | None, now_ts: float) -> list[dict[str, Any]]:
    out = []
    if trigger == "shipment_delayed":
        for sh in await svc.repo.query("bo_shipments", {"status": "delayed"}):
            if carrier and sh["carrier"] != carrier:
                continue
            o = await svc.repo.get("bo_orders", sh["order_id"])
            if o:
                out.append({"customer_id": o["customer_id"], "slots": {"order_id": o["id"], "carrier": sh["carrier"], "eta": _fmt_date(max(sh.get("eta") or now_ts, now_ts) + 3 * 86400)}})
    elif trigger == "appointment_reminder":
        today = datetime.fromtimestamp(now_ts, UTC).strftime("%Y-%m-%d")
        horizon = datetime.fromtimestamp(now_ts + 2 * 86400, UTC).strftime("%Y-%m-%d")
        for ap in await svc.repo.query("bo_appointments", {"status": "booked"}):
            if today <= ap["date"] <= horizon:
                out.append({"customer_id": ap["customer_id"], "slots": {"order_id": ap["order_id"], "kind": ap["kind"], "eta": ap["date"], "window": ap["window"]}})
    return out


class EventBody(BaseModel):
    trigger: str = Field("shipment_delayed", pattern="^(shipment_delayed|appointment_reminder)$")
    carrier: str | None = Field(None, max_length=30)
    as_of: str | None = Field(None, max_length=32, description="ISO timestamp (UTC) to simulate the send time, e.g. 2026-11-18T22:30:00Z")
    max_customers: int = Field(40, ge=1, le=200)
    use_llm: bool = True


def _as_of(value: str | None) -> float:
    if not value:
        return time.time()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise HTTPException(422, "as_of must be an ISO timestamp") from None


async def run_event(svc: Any, body: EventBody, actor: str) -> dict[str, Any]:
    now_ts = _as_of(body.as_of)
    camp = next((c for c in await svc.repo.query("campaigns", {"type": "campaign", "trigger": body.trigger})), None)
    if camp is None:
        raise HTTPException(404, "no campaign for this trigger")
    kill = await _kill(svc)
    history = await _outreach(svc)
    cands = (await _candidates(svc, body.trigger, body.carrier, now_ts))[: body.max_customers]
    sent_today = sum(1 for h in history if h["campaign_id"] == camp["id"] and h["decision"] == "sent" and now_ts - h["ts"] < 86400)
    results, llm_budget = [], 6
    for cand in cands:
        cust = await svc.repo.get("bo_customers", cand["customer_id"])
        if cust is None:
            continue
        prefs = await svc.repo.get("contact_prefs", cust["id"])
        contacts_7d = sum(1 for h in history if h["customer_id"] == cust["id"] and h["decision"] == "sent" and now_ts - h["ts"] < 7 * 86400) + sum(1 for r in results if r["customer_id"] == cust["id"] and r["decision"] == "sent")
        dec = ob.decide(market=cust["market"], prefs=prefs, campaign=camp, kill_switch=kill, now_ts=now_ts, contacts_7d=contacts_7d, sent_today=sent_today)
        extra: dict[str, Any] = {}
        if dec.decision == "sent":
            sent_today += 1
            extra = await _send(svc, camp, body.trigger, cust, dec, cand["slots"], now_ts, body.use_llm and llm_budget > 0)
            llm_budget -= 1 if extra["composed_by"] == "llm+guard" else 0
        doc = await _record(svc, camp, cust, body.trigger, dec, cand["slots"], now_ts, extra)
        results.append(doc)
    counts = {k: sum(1 for r in results if r["decision"] == k) for k in ("sent", "deferred", "suppressed")}
    await svc.audit.log("outbound.event", actor=actor, resource=camp["id"], detail={"trigger": body.trigger, "candidates": len(cands), **counts, "carrier": body.carrier, "as_of": now_ts})
    return {"campaign": camp["id"], "trigger": body.trigger, "candidates": len(cands), "counts": counts, "decisions": [_strip(r) for r in results]}


async def release_due(svc: Any, now_ts: float | None = None) -> dict[str, Any]:
    """Deferred outreach whose window has opened is re-checked (kill switch, pause, consent, caps) and sent if still allowed."""
    now_ts = now_ts or time.time()
    kill = await _kill(svc)
    history = await _outreach(svc)
    released, blocked = 0, 0
    for d in [h for h in history if h["decision"] == "deferred" and (h.get("scheduled_for") or 0) <= now_ts]:
        camp = await svc.repo.get("campaigns", d["campaign_id"])
        cust = await svc.repo.get("bo_customers", d["customer_id"])
        prefs = await svc.repo.get("contact_prefs", d["customer_id"])
        if not camp or not cust:
            continue
        contacts_7d = sum(1 for h in history if h["customer_id"] == cust["id"] and h["decision"] == "sent" and now_ts - h["ts"] < 7 * 86400)
        dec = ob.decide(market=cust["market"], prefs=prefs, campaign=camp, kill_switch=kill, now_ts=now_ts, contacts_7d=contacts_7d, sent_today=0)
        if dec.decision == "sent":
            extra = await _send(svc, camp, d["trigger"], cust, dec, d["slots"], now_ts, False)
            d.update({**dec.to_dict(), **extra, "released_at": now_ts, "released_from": "deferred"})
            released += 1
        elif dec.decision == "suppressed":
            d.update({**dec.to_dict(), "released_at": now_ts, "released_from": "deferred"})
            blocked += 1
        else:
            continue
        await svc.repo.put("campaigns", d, ttl=90 * 86400)
        await svc.audit.log(f"outbound.release_{dec.decision}", actor="system:outbound", resource=cust["id"], conv_id=d.get("conversation_id"), outcome="ok" if dec.decision == "sent" else "blocked", detail={"campaign": camp["id"], "reason": dec.reason, "consent": dec.consent})
    return {"released": released, "blocked": blocked}


async def startup(svc: Any) -> None:
    async def loop() -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await release_due(svc)
            except Exception:  # pragma: no cover - background resilience
                pass

    if not svc.sandbox:
        svc.spawn(loop())


@router.get("/overview")
async def overview(request: Request, _: Actor = Depends(require("outbound.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    camps = [_strip(c) for c in await svc.repo.query("campaigns", {"type": "campaign"})]
    out = await _outreach(svc)
    counts = {k: sum(1 for r in out if r["decision"] == k) for k in ("sent", "deferred", "suppressed")}
    prefs = await svc.repo.query("contact_prefs")
    cb = await svc.repo.query("callbacks", limit=100)
    reasons: dict[str, int] = {}
    for r in out:
        if r["decision"] != "sent":
            reasons[r["reason"].split(" (")[0]] = reasons.get(r["reason"].split(" (")[0], 0) + 1
    return {
        "kill_switch": await _kill(svc), "campaigns": camps, "counts": counts, "reasons": reasons, "decisions": [_strip({k: v for k, v in r.items() if k != "slots"} | {"order_id": r["slots"].get("order_id")}) for r in out[:60]],
        "consent_coverage": {"customers": len(prefs), "sms": sum(1 for p in prefs if p["consents"]["sms"]["granted"]), "email": sum(1 for p in prefs if p["consents"]["email"]["granted"]), "voice": sum(1 for p in prefs if p["consents"]["voice"]["granted"]), "opted_out": sum(1 for p in prefs if p["opt_out"].get("all"))},
        "callbacks": len(cb), "simulated": True,
    }  # fmt: skip


@router.post("/events")
async def trigger_event(body: EventBody, request: Request, actor: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    return await run_event(request.app.state.services, body, f"{actor.role}:{actor.user}")


@router.post("/release-deferred")
async def release(request: Request, as_of: str | None = None, _: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    return await release_due(request.app.state.services, _as_of(as_of) if as_of else None)


class CampaignBody(BaseModel):
    state: str | None = Field(None, pattern="^(active|paused|killed)$")
    per_customer_7d: int | None = Field(None, ge=0, le=20)
    per_day: int | None = Field(None, ge=0, le=100000)
    quiet_start: int | None = Field(None, ge=0, le=23)
    quiet_end: int | None = Field(None, ge=0, le=23)


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, body: CampaignBody, request: Request, actor: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    c = await svc.repo.get("campaigns", campaign_id)
    if c is None or c.get("type") != "campaign":
        raise HTTPException(404, "campaign not found")
    if body.state:
        c["state"] = body.state
    caps = c.setdefault("caps", {})
    if body.per_customer_7d is not None:
        caps["per_customer_7d"] = body.per_customer_7d
    if body.per_day is not None:
        caps["per_day"] = body.per_day
    if body.quiet_start is not None or body.quiet_end is not None:
        q = c.setdefault("quiet_hours", {"start": 21, "end": 8})
        q["start"], q["end"] = body.quiet_start if body.quiet_start is not None else q["start"], body.quiet_end if body.quiet_end is not None else q["end"]
    c["updated_at"] = time.time()
    await svc.repo.put("campaigns", c)
    await svc.audit.log("outbound.campaign_updated", actor=f"{actor.role}:{actor.user}", resource=campaign_id, detail=body.model_dump(exclude_none=True))
    return _strip(c)


class KillBody(BaseModel):
    on: bool


@router.post("/kill-switch")
async def kill_switch(body: KillBody, request: Request, actor: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    await svc.repo.put("settings", {"id": "outbound", "kill_switch": body.on, "changed_by": actor.user, "changed_at": time.time()})
    await svc.audit.log("outbound.kill_switch", actor=f"{actor.role}:{actor.user}", detail={"on": body.on})
    return {"kill_switch": body.on}


class OptOutBody(BaseModel):
    all: bool = True
    channels: list[str] = Field(default_factory=list, max_length=3)
    reason: str = Field("customer request", max_length=120)


@router.get("/preferences/{customer_id}")
async def get_prefs(customer_id: str, request: Request, _: Actor = Depends(require("outbound.read"))) -> dict[str, Any]:
    p = await request.app.state.services.repo.get("contact_prefs", customer_id)
    if p is None:
        raise HTTPException(404, "no preferences on file")
    return _strip(p)


@router.put("/preferences/{customer_id}/opt-out")
async def opt_out(customer_id: str, body: OptOutBody, request: Request, actor: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    p = await svc.repo.get("contact_prefs", customer_id)
    if p is None:
        raise HTTPException(404, "no preferences on file")
    p["opt_out"] = {"all": body.all, "channels": body.channels or ob.CHANNEL_ORDER if body.all else body.channels, "ts": time.time(), "reason": body.reason}
    await svc.repo.put("contact_prefs", p)
    await svc.audit.log("outbound.opt_out", actor=f"{actor.role}:{actor.user}", resource=customer_id, detail=body.model_dump())
    return _strip(p)


@router.delete("/preferences/{customer_id}/opt-out")
async def opt_in_restore(customer_id: str, request: Request, actor: Actor = Depends(require("outbound.write"))) -> dict[str, Any]:
    svc = request.app.state.services
    p = await svc.repo.get("contact_prefs", customer_id)
    if p is None:
        raise HTTPException(404, "no preferences on file")
    p["opt_out"] = {"all": False, "channels": []}
    await svc.repo.put("contact_prefs", p)
    await svc.audit.log("outbound.opt_out_removed", actor=f"{actor.role}:{actor.user}", resource=customer_id)
    return _strip(p)


class CallbackBody(BaseModel):
    conversation_id: str = Field(max_length=40)
    window: str = Field("next business day 09:00-12:00", max_length=60)
    reason: str = Field("callback requested after outreach", max_length=160)


@router.post("/callbacks")
async def request_callback(body: CallbackBody, request: Request) -> dict[str, Any]:
    """Customer-initiated callback (e.g. from an outreach conversation); visible to WFM and supervisors. Delivery is simulated - no PSTN."""
    svc = request.app.state.services
    conv = await svc.store.get(body.conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    cb = {"id": f"cb_{uuid.uuid4().hex[:8]}", "conversation_id": conv.id, "customer_id": conv.identity.customer_id, "window": body.window, "reason": body.reason, "queue": conv.queue or "general", "status": "scheduled", "created_at": time.time(), "source": "customer", "language": conv.language, "simulated": True}
    await svc.repo.put("callbacks", cb)
    conv.add("system_notice", f"Callback scheduled: {body.window}.", lang=conv.language, flags=["callback"])
    await svc.store.save(conv)
    await svc.audit.log("outbound.callback_scheduled", actor="customer", resource=conv.id, conv_id=conv.id, detail={"window": body.window})
    return _strip(cb)


@router.get("/callbacks")
async def list_callbacks(request: Request, _: Actor = Depends(require("outbound.read", "wfm.read"))) -> list[dict[str, Any]]:
    return [_strip(r) for r in await request.app.state.services.repo.query("callbacks", order_by="created_at", desc=True, limit=100)]


@router.post("/reset-demo")
async def reset_demo(request: Request, actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    """Removes outreach decisions (not campaigns / preferences) so the demo can be replayed."""
    svc = request.app.state.services
    n = 0
    for r in await _outreach(svc):
        n += await svc.repo.delete("campaigns", r["id"])
    await svc.repo.put("settings", {"id": "outbound", "kill_switch": False})
    for c in ob.DEFAULT_CAMPAIGNS:
        await svc.repo.put("campaigns", {**c, "created_at": time.time()})
    await svc.audit.log("outbound.reset_demo", actor=f"{actor.role}:{actor.user}", detail={"deleted": n})
    return {"deleted": n}
