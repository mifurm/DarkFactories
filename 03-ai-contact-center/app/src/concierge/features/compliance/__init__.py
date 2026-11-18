"""CC-11 Compliance & risk guard: redaction / inspection playground, red-team regression pack, retention policies + purge job,
hash-chained audit log with tamper test."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core import i18n
from ...core.rbac import Actor, require
from ...core.redaction import redact
from ...core.registry import EPIC_C, FeatureInfo
from ...engine import evalrun, redteam
from ...engine.audit import GENESIS, _digest
from ...engine.guard import DISCLOSURE_MARKERS, find_risky_promises, sanitize_untrusted_document

FEATURES = [
    FeatureInfo(
        "CC-11", "Compliance & risk guard", EPIC_C, "P0", "/compliance", "/api/compliance",
        "PII/PCI redaction (Luhn/IBAN validated), prompt-injection defences (rules + Prompt Shields), toxicity, risky-promise + disclosure checks, retention purge, hash-chained audit log, 44-case red-team pack.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/compliance", tags=["compliance (CC-11)"])

RETENTION = [
    {"class": "conversation transcripts (recording consent granted)", "days": 365, "enforced_by": "Cosmos TTL + retention job", "legal_hold": "tag legal_hold"},
    {"class": "conversation transcripts (consent declined)", "days": 7, "enforced_by": "text never stored; metadata TTL", "legal_hold": "n/a"},
    {"class": "audit log (hash-chained)", "days": 400, "enforced_by": "Cosmos TTL", "legal_hold": "extend on hold"},
    {"class": "idempotency records", "days": 90, "enforced_by": "Cosmos TTL", "legal_hold": "n/a"},
    {"class": "AI usage metering", "days": 120, "enforced_by": "Cosmos TTL", "legal_hold": "n/a"},
    {"class": "one-time codes / payment sessions", "days": 0.04, "enforced_by": "memory only / 1 h TTL", "legal_hold": "n/a"},
]


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(None, max_length=8, description="Language of the text (the safe replacement is returned in it); omitted = the request locale")


class RedTeamBody(BaseModel):
    level: str = Field("guard", pattern="^(guard|e2e|stress)$")


@router.post("/redact")
async def redact_text(body: TextBody) -> dict[str, Any]:
    r = redact(body.text)
    return {"text": r.text, "findings": [{"kind": f.kind, "start": f.start, "end": f.end} for f in r.findings], "kinds": sorted(r.kinds)}


@router.post("/inspect")
async def inspect(body: TextBody, request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    v = await svc.guard.inspect_input(body.text)
    return {"clean_text": v.text, "flags": v.flags, "injection": v.injection, "injection_reasons": v.injection_reasons, "social_engineering": v.social_engineering, "toxic": v.toxic, "toxicity": v.toxicity, "card_detected": v.card_detected, "pii_kinds": v.pii_kinds, "explicit_human_request": v.explicit_human_request, "azure_prompt_shields": v.azure_shield}


@router.post("/output-check")
async def output_check(body: TextBody, request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    o = svc.guard.inspect_output(body.text, lang=body.language or i18n.current_locale())
    return {"text": o.text, "issues": o.issues, "risky_promises": find_risky_promises(body.text), "has_ai_disclosure": bool(DISCLOSURE_MARKERS.search(body.text))}


@router.post("/kb-scan")
async def kb_scan(body: TextBody) -> dict[str, Any]:
    clean, reasons = sanitize_untrusted_document(body.text)
    return {"clean_text": clean, "quarantine_reasons": reasons, "quarantined": bool(reasons)}


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    return {"guard": svc.guard.stats, "azure_content_safety": svc.guard.use_azure, "bypass_mode": svc.guard.bypass_injection}


@router.get("/redteam/pack")
async def pack() -> dict[str, Any]:
    return {"attacks": [{k: v for k, v in a.items()} | {"payload": a["payload"].replace("\u200b", "·")} for a in redteam.ATTACKS], "benign": redteam.BENIGN}


@router.post("/redteam/run")
async def run_pack(body: RedTeamBody, request: Request, _: Actor = Depends(require("compliance.read", "evals.read"))) -> dict[str, Any]:
    svc = request.app.state.services
    if body.level == "guard":
        return {"level": "guard", **redteam.run_guard_pack()}
    rep = await evalrun.run_suite(svc, "redteam", stress=body.level == "stress")
    blocked = sum(1 for r in rep["results"] for t in r["tools"] if t.split(":")[1] in ("blocked", "approval_required", "error", "confirmation_required"))
    return {"level": body.level, "must_pass_rate": rep["totals"]["pass_rate"], "total": rep["totals"]["scenarios"], "passed": rep["totals"]["passed"], "failures": rep["failures"], "forbidden_attempts_stopped_by_policy": blocked, "dimensions": rep["dimensions"], "duration_s": rep["duration_s"], "cost_usd": rep["cost_usd"], "stress_note": "guard bypass + deliberately gullible model: only code-level policy stands between the attack and the tools" if body.level == "stress" else None}


@router.get("/retention")
async def retention() -> dict[str, Any]:
    return {"policies": RETENTION, "mechanism": "Cosmos DB container TTL (per-item ttl set at write) + an explicit purge job below; conversations tagged legal_hold are never purged."}


@router.post("/retention/run")
async def run_retention(request: Request, dry_run: bool = False, actor: Actor = Depends(require("compliance.run"))) -> dict[str, Any]:
    """Purge conversations whose retention period has elapsed (audited). Synthetic history is excluded."""
    svc = request.app.state.services
    docs = await svc.repo.query("conversations")
    purged, held, kept = [], 0, 0
    for d in docs:
        days = 7 if "consent_declined" in d.get("tags", []) else d.get("retention_days", 365)
        ref = d.get("closed_at") or d.get("updated_at") or d.get("created_at", time.time())
        if time.time() < ref + days * 86400:
            kept += 1
        elif "legal_hold" in d.get("tags", []):
            held += 1
        else:
            purged.append(d["id"])
            if not dry_run:
                svc.store.cache.pop(d["id"], None)
                await svc.repo.delete("conversations", d["id"])
    if purged and not dry_run:
        await svc.audit.log("retention.purged", actor=actor.user, resource="conversations", detail={"count": len(purged), "ids": purged[:20]})
    return {"dry_run": dry_run, "purged": len(purged), "legal_hold": held, "kept": kept, "ids": purged[:20]}


@router.get("/audit")
async def audit(request: Request, limit: int = 80, action: str | None = None, _: Actor = Depends(require("audit.read", "compliance.read"))) -> list[dict[str, Any]]:
    rows = await request.app.state.services.audit.recent(limit=max(1, min(limit, 400)), where={"action": action} if action else None)
    return [{k: v for k, v in r.items() if k not in ("pk", "_ts", "ttl")} for r in rows]


@router.get("/audit/verify")
async def verify(request: Request, _: Actor = Depends(require("audit.read", "compliance.read"))) -> dict[str, Any]:
    return await request.app.state.services.audit.verify()


@router.post("/audit/tamper-test")
async def tamper_test(request: Request, _: Actor = Depends(require("audit.read", "compliance.read"))) -> dict[str, Any]:
    """Demonstrates tamper evidence on an isolated copy: alter one record and re-verify the chain."""
    svc = request.app.state.services
    rows = sorted(await svc.repo.query("audit", order_by="seq", desc=True, limit=40), key=lambda r: r["seq"])
    if len(rows) < 3:
        return {"ok": False, "reason": "not enough audit records yet"}
    copy_rows = copy.deepcopy(rows)

    def check(rs: list[dict[str, Any]]) -> int | None:
        for prev, cur in itertools.pairwise(rs):
            body = {k: cur[k] for k in ("seq", "ts", "actor", "action", "resource", "outcome", "conv_id", "detail")}
            if cur["prev_hash"] != prev["hash"] or _digest(cur["prev_hash"], body) != cur["hash"]:
                return cur["seq"]
        return None

    before = check(copy_rows)
    victim = copy_rows[len(copy_rows) // 2]
    victim["detail"] = {"tampered": True}
    after = check(copy_rows)
    return {"chain_intact_before": before is None, "tampered_seq": victim["seq"], "break_detected_at": after, "tamper_detected": after is not None, "records_checked": len(rows), "genesis": GENESIS, "hash_alg": "sha256(prev_hash + canonical_json(record))", "sample_hash": hashlib.sha256(json.dumps(rows[-1]["hash"]).encode()).hexdigest()[:16]}
