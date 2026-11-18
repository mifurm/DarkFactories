"""CC-05 Identity verification, consent & disclosure: verification levels, consent log, PII allow-list, secure payment hand-off."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.redaction import luhn_ok
from ...core.registry import EPIC_A, FeatureInfo
from ...engine import plan_text
from ...engine.models import now

FEATURES = [
    FeatureInfo(
        "CC-05", "Identity verification, consent & disclosure", EPIC_A, "P0", "/identity", "/api/identity",
        "OTP + KBA verification with levels (L0/L1/L2) gating tools, AI disclosure + recording consent capture, PII minimisation allow-list, PCI-safe payment hand-off (link / DTMF simulation).",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/identity", tags=["identity (CC-05)"])

LEVELS = [
    {"level": 0, "name": "L0 anonymous", "grants": "knowledge answers, create ticket, escalate", "how": "-"},
    {"level": 1, "name": "L1 verified", "grants": "order & shipment lookup, returns, pickups, goodwill, warranty, refunds up to the step-up amount", "how": "one-time code to the phone on file (OTP) or KBA fallback (postal code + last 4 phone digits)"},
    {"level": 2, "name": "L2 step-up", "grants": "address change, refunds above the step-up amount", "how": "OTP + KBA"},
]
PII_ALLOWLIST = {
    "customer_profile": ["first_name", "tier", "market", "language", "phone_masked", "email_masked", "city"],
    "order": ["order_id", "status", "total_eur", "items[item_id,name,qty,unit_price_eur,category,warranty_months]", "placed_on", "delivered_on", "carrier", "tracking_id", "delivery_city", "payment (brand + last four)", "installation_required", "dispatched"],
    "never_sent_to_the_model": ["card numbers / CVV (redacted, hand-off)", "full e-mail", "full phone number", "street address", "date of birth", "one-time codes (hashed)", "IBAN"],
}


@router.get("/levels")
async def levels() -> dict[str, Any]:
    return {"levels": LEVELS, "pii_allowlist": PII_ALLOWLIST, "otp": {"ttl_s": 300, "max_attempts": 3, "delivery": "simulated outbox (SMS)"}}


@router.get("/consents")
async def consents(request: Request, limit: int = 40) -> list[dict[str, Any]]:
    svc = request.app.state.services
    rows = await svc.audit.recent(limit=300)
    return [r for r in rows if r["action"] in ("consent.recorded", "conversation.started", "identity.verified", "identity.locked", "compliance.card_data_redacted")][:limit]


class PayBody(BaseModel):
    card_number: str = ""
    exp: str = ""
    cvv: str = ""
    name: str = ""


def _brand(pan: str) -> str:
    return "Visa" if pan.startswith("4") else "Mastercard" if re.match(r"^(5[1-5]|2[2-7])", pan) else "Amex" if re.match(r"^3[47]", pan) else "Card"


async def _complete(svc: Any, token: str, pan: str) -> dict[str, Any]:
    pay = await svc.repo.get("payments", token)
    if pay is None:
        raise HTTPException(404, "unknown payment session")
    if pay["status"] == "paid":
        return {"status": "paid", "brand": pay.get("brand"), "last4": pay.get("last4")}
    brand, last4 = _brand(pan), pan[-4:]
    pay.update({"status": "paid", "brand": brand, "last4": last4, "paid_at": now()})  # the PAN itself is never stored
    await svc.repo.put("payments", pay, ttl=3600)
    conv = await svc.store.get(pay["conv_id"])
    if conv:
        conv.payment = {"token": token, "status": "paid", "amount": pay.get("amount"), "brand": brand, "last4": last4}
        conv.add("system_notice", plan_text.payment_received(conv.language, amount=pay.get("amount"), brand=brand, last4=last4), lang=conv.language, flags=["payment_completed"])
        await svc.store.save(conv)
        await svc.bus.publish(f"conv:{conv.id}", {"type": "message", "message": conv.messages[-1].model_dump()})
    await svc.audit.log("payment.handoff_completed", actor="customer", resource=token, conv_id=pay["conv_id"], detail={"brand": brand, "last4": last4})
    return {"status": "paid", "brand": brand, "last4": last4}


@router.get("/payments/{token}")
async def payment_info(token: str, request: Request) -> dict[str, Any]:
    pay = await request.app.state.services.repo.get("payments", token)
    if pay is None:
        raise HTTPException(404, "unknown payment session")
    return {"amount": pay.get("amount"), "purpose": pay["purpose"], "status": pay["status"], "currency": "EUR", "simulated": True, "note": "Simulated hosted payment page - use a test card such as 4242 4242 4242 4242. Card data goes only to this page, never to the chat or the model."}


@router.post("/payments/{token}/submit")
async def payment_submit(token: str, body: PayBody, request: Request) -> dict[str, Any]:
    pan = re.sub(r"\D", "", body.card_number)
    if not luhn_ok(pan) or not re.fullmatch(r"\d{2}/\d{2}", body.exp.strip()) or not re.fullmatch(r"\d{3,4}", body.cvv.strip()):
        raise HTTPException(422, {"error": "invalid_card", "message": "Card number, expiry (MM/YY) or security code is not valid."})
    return await _complete(request.app.state.services, token, pan)


class DtmfBody(BaseModel):
    digit: str


@router.post("/payments/{token}/dtmf")
async def payment_dtmf(token: str, body: DtmfBody, request: Request) -> dict[str, Any]:
    """Keypad capture simulation: digits are accumulated server-side and masked; they never reach the transcript or the model."""
    svc = request.app.state.services
    buf: dict[str, str] = svc.ext.setdefault("dtmf", {})
    if body.digit == "#":
        pan = buf.pop(token, "")
        if not luhn_ok(pan):
            raise HTTPException(422, {"error": "invalid_card", "message": "The digits entered are not a valid card number."})
        return await _complete(svc, token, pan)
    if body.digit == "*":
        buf.pop(token, None)
        return {"digits_entered": 0, "complete": False}
    if not re.fullmatch(r"\d", body.digit):
        raise HTTPException(422, "digit must be 0-9, * or #")
    buf[token] = (buf.get(token, "") + body.digit)[:19]
    return {"digits_entered": len(buf[token]), "complete": False, "masked": "•" * len(buf[token])}
