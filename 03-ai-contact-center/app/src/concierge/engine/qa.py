"""100 % auto-QA (CC-10): rubric scoring with evidence snippets and auto-fail rules (deterministic rules + optional LLM judge),
calibration agreement metrics (exact / within-1 / MAE / quadratic-weighted kappa) and per-agent coaching suggestions."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from typing import Any

from .guard import DISCLOSURE_MARKERS, find_risky_promises
from .models import Conversation, Message, now
from .understanding import fold

DIMENSIONS = ["greeting", "empathy", "accuracy", "policy", "resolution", "compliance", "clarity"]
WEIGHTS = {"greeting": 10, "empathy": 15, "accuracy": 20, "policy": 20, "resolution": 20, "compliance": 10, "clarity": 5}
AGENT_ROLES = {"agent_ai", "agent_human"}
EMPATHY_RX = re.compile(r"\b(sorry|apolog\w*|understand|regret|unfortunate\w*|frustrat\w*|inconvenien\w*|appreciate|patience|es tut mir leid|entschuldig\w*|verst(?:a|ä)ndnis|bedauer\w*|d[ée]sol[ée]|excuse|lamento|siento|dispiace|scusi|sorry)\b", re.IGNORECASE)
GREETING_RX = re.compile(r"\b(hello|hi|good (?:morning|afternoon|evening)|welcome|hallo|guten (?:tag|morgen|abend)|bonjour|hola|ciao|how can i help|wie kann ich)\b", re.IGNORECASE)
HELP_RX = re.compile(r"\b(help|assist|how can i|what can i|wie kann ich|worum geht|besoin|ayudar|aiutare)\b", re.IGNORECASE)
MONEY_RX = re.compile(r"(?:€|eur\s?)\s?(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s?(?:€|eur\b)", re.IGNORECASE)
STATE_TOOLS = {"initiate_return", "schedule_pickup", "reschedule_delivery", "update_address", "issue_refund", "goodwill_credit", "warranty_claim"}
RECOMMENDATIONS = {
    "greeting": ("Open with a warm greeting, state who you are (AI or human) and ask how you can help.", "Keep the disclosure + greeting template in the first message; add the customer's name once known."),
    "empathy": ("Acknowledge the customer's situation in the first reply after they express frustration or a problem.", "Add a rule to the resolution prompt: 'Start with a short apology/acknowledgement when the customer reports damage, delay or frustration.'"),
    "accuracy": ("Only state policy facts that you can cite; verify amounts against the system before saying them.", "Tighten KB retrieval (more specific documents) and keep groundedness enforcement on; review ungrounded answers in the QA workbench."),
    "policy": ("Read back the plan and wait for an explicit yes before any state-changing action; respect caps and approval rules.", "Review tool allow-lists and confirmation behaviour in the config; keep confirmations enforced in code."),
    "resolution": ("Close the loop: confirm the outcome, next steps and timeline before ending the conversation.", "Improve the end-to-end flow prompts (offer concrete options, book the follow-up in the same conversation)."),
    "compliance": ("Always give the AI/recording disclosure, never promise outcomes, never handle card data.", "Keep the guard layer on; extend the red-team pack with the observed violations."),
    "clarity": ("Use short sentences and one question at a time; avoid jargon.", "Shorten the reply-length rule in the prompt (max 4 short sentences) and avoid lists in voice."),
}  # fmt: skip


def quote(m: Message, n: int = 150) -> str:
    return re.sub(r"\s+", " ", m.text).strip()[:n]


def _ev(dim: str, m: Message | None, note: str, q: str | None = None) -> dict[str, Any]:
    return {"dimension": dim, "turn": m.idx if m else None, "role": m.role if m else None, "quote": (q if q is not None else (quote(m) if m else "")), "note": note}


def _score_greeting(msgs: list[Message], human: bool) -> tuple[int, list[dict[str, Any]]]:
    first = next((m for m in msgs if m.role in AGENT_ROLES), None)
    if first is None:
        return 1, [_ev("greeting", None, "no agent message")]
    score = 1
    ev = []
    if human:
        score += 2 if GREETING_RX.search(first.text) else 0
        score += 1 if re.search(r"\b(my name is|i'm|ich bin|mein name|je suis|soy)\b", first.text, re.IGNORECASE) else 0
        score += 1 if HELP_RX.search(first.text) else 0
    else:
        score += 2 if (DISCLOSURE_MARKERS.search(first.text) or "disclosure" in first.flags) else 0
        score += 1 if GREETING_RX.search(first.text) or "disclosure" in first.flags else 0
        score += 1 if HELP_RX.search(first.text) or "disclosure" in first.flags else 0
    score = min(score, 5)
    if score < 5:
        ev.append(_ev("greeting", first, "first agent message lacks " + ("a greeting / name / offer to help" if human else "disclosure, greeting or offer to help")))
    return score, ev


def _score_empathy(conv: Conversation, roles: set[str]) -> tuple[int, list[dict[str, Any]]]:
    msgs = conv.messages
    need_idx = next((m.idx for m in msgs if m.role == "customer" and (m.meta.get("understanding", {}).get("sentiment", 0) <= -0.25 or m.meta.get("understanding", {}).get("intent") in ("damaged_item", "complaint") or m.meta.get("understanding", {}).get("emotion") in ("angry", "frustrated"))), None)
    replies = [m for m in msgs if m.role in roles and (need_idx is None or m.idx > need_idx)]
    marked = [m for m in replies if EMPATHY_RX.search(m.text)]
    if need_idx is None:
        return (5, []) if marked else (4, [])
    if marked and replies and replies.index(marked[0]) <= 1:
        return 5, []
    if marked:
        return 3, [_ev("empathy", marked[0], "empathy shown but not in the first reply after the customer raised a problem")]
    first_reply = replies[0] if replies else None
    return 1, [_ev("empathy", first_reply, "customer was frustrated / reported a problem but no acknowledgement or apology was given")]


def _amount_set(conv: Conversation) -> set[float]:
    out: set[float] = set()
    for m in conv.messages:
        for t in m.tools:
            for v in t.result.values() if isinstance(t.result, dict) else []:
                if isinstance(v, int | float) and not isinstance(v, bool):
                    out.add(round(float(v), 2))
            for i in t.result.get("items", []) if isinstance(t.result, dict) else []:
                if isinstance(i, dict) and isinstance(i.get("unit_price_eur"), int | float):
                    out.add(round(float(i["unit_price_eur"]), 2))
    return out


def _score_accuracy(conv: Conversation, roles: set[str]) -> tuple[int, list[dict[str, Any]]]:
    score, ev = 5, []
    amounts = _amount_set(conv)
    for m in conv.messages:
        if m.role not in roles:
            continue
        if "ungrounded" in m.flags:
            score -= 2
            ev.append(_ev("accuracy", m, "answer was flagged as not supported by the knowledge base"))
        for g in MONEY_RX.findall(m.text):
            val = round(float((g[0] or g[1]).replace(",", ".")), 2)
            if amounts and val not in amounts and val > 0 and "handoff_notice" not in m.flags:
                score -= 2
                ev.append(_ev("accuracy", m, f"amount EUR {val:.2f} does not match any system value", q=quote(m)))
                break
        if re.search(r"\b(\d+)[- ](?:day|days|tage|jours|días)\b", m.text, re.IGNORECASE) and not m.citations and not m.tools and m.role == "agent_ai" and "disclosure" not in m.flags:
            score -= 1
            ev.append(_ev("accuracy", m, "policy time-frame stated without a citation"))
    return max(score, 1), ev


def _score_policy(conv: Conversation) -> tuple[int, list[dict[str, Any]]]:
    score, ev = 5, []
    msgs = {m.idx: m for m in conv.messages}
    confirmed_at = next((s["ts"] for s in conv.steps if s["tool"] == "customer_confirmation" and s["status"] == "ok"), None)
    for m in conv.messages:
        for t in m.tools:
            if t.name in STATE_TOOLS and t.status == "ok" and t.actor == "ai" and t.idempotency_key is not None:
                if confirmed_at is None or confirmed_at > t.ts + 0.5:
                    score -= 3
                    ev.append(_ev("policy", m, f"{t.name} executed without a prior customer confirmation"))
                if t.name == "issue_refund" and isinstance(t.result.get("amount_eur"), int | float) and t.result["amount_eur"] > 500 and not t.result.get("approved_by"):
                    score -= 5
                    ev.append(_ev("policy", m, "refund above the autonomous cap executed without approval"))
            if t.status == "blocked" and t.error == "tool_not_allowed":
                score -= 1
                ev.append(_ev("policy", m, f"attempted a tool outside the allow-list: {t.name}"))
    if any(f.startswith("risky_promise") for m in msgs.values() for f in m.flags):
        score -= 2
        m = next(m for m in msgs.values() if any(f.startswith("risky_promise") for f in m.flags))
        ev.append(_ev("policy", m, "tried to promise an outcome that policy does not guarantee (blocked by the guard)"))
    return max(score, 1), ev


def _score_resolution(conv: Conversation, disposition: str) -> tuple[int, list[dict[str, Any]]]:
    last_sent = conv.sentiment_trajectory[-1] if conv.sentiment_trajectory else 0.0
    last_agent = next((m for m in reversed(conv.messages) if m.role in AGENT_ROLES), None)
    if disposition.startswith("RESOLVED"):
        return (4 if last_sent <= -0.5 else 5), []
    if disposition.startswith("ESCALATED"):
        ok_pkg = bool(conv.handoff and conv.handoff.get("package") and conv.handoff["package"].get("completeness", 0) >= 80)
        return (4 if ok_pkg else 3), []
    if disposition == "TICKET_CREATED":
        return 3, [_ev("resolution", last_agent, "customer issue was deferred to a ticket")]
    if disposition in ("VERIFICATION_FAILED", "OUT_OF_SCOPE"):
        return 2, [_ev("resolution", last_agent, f"conversation ended with {disposition}")]
    return 1, [_ev("resolution", last_agent, "no resolution reached")]


def _score_compliance(conv: Conversation) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    score, ev, fails = 5, [], []
    first_agent = next((m for m in conv.messages if m.role in AGENT_ROLES), None)
    early = [m for m in conv.messages if m.role in AGENT_ROLES][:2]
    if not any("disclosure" in m.flags or DISCLOSURE_MARKERS.search(m.text) for m in early):
        fails.append({"rule": "missing_ai_disclosure", **_ev("compliance", first_agent, "no AI disclosure at the start of the conversation")})
        score = 1
    for m in conv.messages:
        if m.role in AGENT_ROLES and find_risky_promises(m.text):
            fails.append({"rule": "risky_promise", **_ev("compliance", m, "risky promise delivered to the customer")})
            score = min(score, 1)
        if m.role in AGENT_ROLES and re.search(r"\b(?:\d[ -]?){13,19}\b", m.text) and re.search(r"\d{4}[ -]?\d{4}[ -]?\d{4}", m.text):
            fails.append({"rule": "pci_in_transcript", **_ev("compliance", m, "card-number-like digits in the transcript")})
            score = 1
    if conv.consent.recording == "pending" and conv.channel == "voice":
        score = min(score, 4)
        ev.append(_ev("compliance", first_agent, "recording consent was never captured"))
    redacted = [m for m in conv.messages if any(f.startswith("pii_in_output") for f in m.flags)]
    if redacted:
        score = min(score, 4)
        ev.append(_ev("compliance", redacted[0], "agent output contained PII that had to be redacted"))
    return score, ev, fails


def _score_clarity(conv: Conversation, roles: set[str]) -> tuple[int, list[dict[str, Any]]]:
    msgs = [m for m in conv.messages if m.role in roles and "disclosure" not in m.flags and "handoff_notice" not in m.flags]
    if not msgs:
        return 4, []
    avg = sum(len(m.text.split()) for m in msgs) / len(msgs)
    longest = max(msgs, key=lambda m: len(m.text.split()))
    score = 5 if avg <= 55 else 4 if avg <= 85 else 3 if avg <= 125 else 2
    ev = [] if score == 5 else [_ev("clarity", longest, f"replies average {avg:.0f} words; keep chat replies short and focused")]
    if re.search(r"[A-Z]{12,}", " ".join(m.text for m in msgs)):
        score = min(score, 3)
        ev.append(_ev("clarity", longest, "shouting / all-caps text"))
    return score, ev


def overall_score(dims: dict[str, int]) -> float:
    return round(sum(WEIGHTS[d] * (dims[d] / 5.0) for d in DIMENSIONS), 1)


def band(overall: float, auto_fail: bool) -> str:
    return "fail" if auto_fail else "excellent" if overall >= 85 else "good" if overall >= 70 else "needs_improvement" if overall >= 50 else "poor"


def rule_score(conv: Conversation, disposition: str | None = None) -> dict[str, Any]:
    from .wrapup import classify_disposition

    disposition = disposition or classify_disposition(conv)
    ai_msgs = [m for m in conv.messages if m.role == "agent_ai"]
    human_msgs = [m for m in conv.messages if m.role == "agent_human"]
    segments: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []

    def seg(name: str, roles: set[str], msgs: list[Message], human: bool) -> dict[str, int]:
        g, e1 = _score_greeting(msgs, human)
        em, e2 = _score_empathy(conv, roles)
        ac, e3 = _score_accuracy(conv, roles)
        cl, e4 = _score_clarity(conv, roles)
        evidence.extend([*e1, *e2, *e3, *e4])
        return {"greeting": g, "empathy": em, "accuracy": ac, "clarity": cl}

    ai_dims = seg("ai", {"agent_ai"}, ai_msgs, False) if ai_msgs else None
    hu_dims = seg("human", {"agent_human"}, human_msgs, True) if human_msgs else None
    pol, e5 = _score_policy(conv)
    res, e6 = _score_resolution(conv, disposition)
    com, e7, fails = _score_compliance(conv)
    evidence.extend([*e5, *e6, *e7])
    dims: dict[str, int] = {}
    for d in ("greeting", "empathy", "accuracy", "clarity"):
        vals = [x[d] for x in (ai_dims, hu_dims) if x]
        w = [len(ai_msgs), len(human_msgs)] if ai_dims and hu_dims else [1]
        dims[d] = max(1, min(5, round(sum(v * wt for v, wt in zip(vals, w, strict=False)) / sum(w)))) if vals else 3
    dims.update({"policy": pol, "resolution": res, "compliance": com})
    if ai_dims:
        segments["ai"] = {**ai_dims, "policy": pol, "resolution": res, "compliance": com}
    if hu_dims:
        segments["human"] = {**hu_dims, "policy": pol, "resolution": res, "compliance": com}
    return {"dimensions": dims, "segments": segments, "evidence": evidence, "auto_fail": fails, "disposition": disposition}


async def score_conversation(svc: Any, conv: Conversation, *, use_llm: bool | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    res = rule_score(conv)
    dims = dict(res["dimensions"])
    scorer = "rules"
    notes: list[str] = []
    if use_llm is None:
        use_llm = not svc.llm.deterministic
    if use_llm and any(m.role in AGENT_ROLES for m in conv.messages):
        try:
            convo = "\n".join(f"[{m.idx}] {m.role}: {m.text}" for m in conv.messages if m.visible_to_customer)[-5500:]
            out = await svc.llm.chat(
                [{"role": "system", "content": "You are a strict contact-center QA analyst. Score ONLY empathy, accuracy and clarity (1-5 each) of the AGENT messages. For every score below 5 quote the exact words from the transcript as evidence. Return JSON {\"empathy\": {\"score\": int, \"quote\": str, \"turn\": int}, \"accuracy\": {...}, \"clarity\": {...}}. Accuracy: penalise facts not supported by the transcript tool results."},
                 {"role": "user", "content": convo}],
                role="reasoning", max_tokens=700, reasoning_effort="low", json_mode=True, feature="qa", conv_id=conv.id,
            )  # fmt: skip
            data = json.loads(out.text or "{}")
            transcript = " ".join(m.text for m in conv.messages)
            for d in ("empathy", "accuracy", "clarity"):
                item = data.get(d) or {}
                s = item.get("score")
                if isinstance(s, int) and 1 <= s <= 5:
                    if abs(s - dims[d]) >= 2:
                        notes.append(f"{d}: rules={dims[d]} llm={s}")
                    dims[d] = round((dims[d] + s) / 2)
                    q = str(item.get("quote") or "")
                    if s < 5 and q and q[:60] in transcript:  # evidence must exist in the transcript
                        res["evidence"].append({"dimension": d, "turn": item.get("turn"), "role": "agent", "quote": q[:200], "note": "LLM judge evidence", "source": "llm"})
            scorer = "rules+llm"
        except Exception:
            scorer = "rules"
    overall = overall_score(dims)
    auto_fail = bool(res["auto_fail"])
    if auto_fail:
        overall = min(overall, 39.0)
    participants = sorted({"concierge-ai" if m.role == "agent_ai" else (m.author or "human") for m in conv.messages if m.role in AGENT_ROLES})
    record = {
        "id": conv.id, "conversation_id": conv.id, "channel": conv.channel, "language": conv.language, "scored_at": now(), "scorer": scorer,
        "dimensions": dims, "segments": res["segments"], "overall": overall, "band": band(overall, auto_fail), "auto_fail": res["auto_fail"],
        "evidence": [e for e in res["evidence"] if e.get("quote")], "disposition": res["disposition"], "participants": participants,
        "config_version": conv.config_version, "notes": notes, "latency_s": round(time.perf_counter() - t0, 3), "sla_ok": True, "calibration": None,
    }  # fmt: skip
    # every non-perfect dimension must carry evidence that exists in the transcript
    present = " ".join(fold(m.text) for m in conv.messages)
    for e in record["evidence"]:
        e["verified"] = fold(e["quote"])[:60] in present
    await svc.repo.put("qa_reviews", record)
    return record


# ------------------------------------------------------------------------------------ calibration & agreement
def weighted_kappa(a: list[int], b: list[int], k: int = 5) -> float:
    """Quadratic-weighted Cohen's kappa on a 1..k scale."""
    n = len(a)
    if n == 0:
        return 0.0
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        obs[x - 1][y - 1] += 1
    ra = [sum(row) for row in obs]
    cb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) ** 2) / ((k - 1) ** 2)
            num += w * obs[i][j]
            den += w * ra[i] * cb[j] / n
    return round(1 - num / den, 4) if den else 1.0


def agreement(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "exact_pct": None, "within1_pct": None, "mae": None, "kappa": None}
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    n = len(pairs)
    return {"n": n, "exact_pct": round(100 * sum(x == y for x, y in pairs) / n, 1), "within1_pct": round(100 * sum(abs(x - y) <= 1 for x, y in pairs) / n, 1), "mae": round(sum(abs(x - y) for x, y in pairs) / n, 3), "kappa": weighted_kappa(a, b)}


async def calibrate(svc: Any, conv_id: str, human_scores: dict[str, int], analyst: str, note: str = "") -> dict[str, Any]:
    rec = await svc.repo.get("qa_reviews", conv_id)
    if not rec:
        raise KeyError(conv_id)
    deltas = {d: human_scores[d] - rec["dimensions"][d] for d in human_scores if d in rec["dimensions"]}
    rec["calibration"] = {"analyst": analyst, "ts": now(), "human_scores": {d: human_scores[d] for d in deltas}, "deltas": deltas, "note": note[:300]}
    await svc.repo.put("qa_reviews", rec)
    await svc.audit.log("qa.calibrated", actor=analyst, resource=conv_id, detail={"deltas": deltas})
    return rec


async def agreement_report(svc: Any) -> dict[str, Any]:
    rows = [r for r in await svc.repo.query("qa_reviews") if r.get("calibration")]
    rows.sort(key=lambda r: r["calibration"]["ts"])
    pairs = [(r["dimensions"][d], r["calibration"]["human_scores"][d]) for r in rows for d in r["calibration"]["human_scores"]]
    per_dim: dict[str, dict[str, Any]] = {}
    for d in DIMENSIONS:
        p = [(r["dimensions"][d], r["calibration"]["human_scores"][d]) for r in rows if d in r["calibration"]["human_scores"]]
        if p:
            per_dim[d] = agreement(p)
    drift = {"flag": False, "recent_mae": None, "earlier_mae": None}
    if len(rows) >= 6:
        half = len(rows) // 2
        def mae(rs: list[dict[str, Any]]) -> float:
            xs = [abs(r["calibration"]["deltas"][d]) for r in rs for d in r["calibration"]["deltas"]]
            return sum(xs) / len(xs) if xs else 0.0

        drift = {"recent_mae": round(mae(rows[half:]), 3), "earlier_mae": round(mae(rows[:half]), 3)}
        drift["flag"] = drift["recent_mae"] - drift["earlier_mae"] > 0.3
    return {"overall": agreement(pairs), "by_dimension": per_dim, "calibrated_conversations": len(rows), "drift": drift}


def coaching(dim_scores: list[dict[str, int]], evidence: list[dict[str, Any]], is_ai: bool) -> list[dict[str, Any]]:
    """Top-3 coaching suggestions from recurring low-scoring dimensions."""
    if not dim_scores:
        return []
    avg = defaultdict(float)
    for s in dim_scores:
        for d, v in s.items():
            avg[d] += v / len(dim_scores)
    low = sorted(((v, d) for d, v in avg.items() if d in DIMENSIONS), key=lambda x: x[0])[:3]
    out = []
    for v, d in low:
        if v >= 4.8:
            continue
        ex = next((e for e in evidence if e.get("dimension") == d and e.get("quote")), None)
        out.append({"dimension": d, "avg_score": round(v, 2), "suggestion": RECOMMENDATIONS[d][1 if is_ai else 0], "example": ex.get("quote") if ex else None, "target": "prompt/knowledge (CC-17)" if is_ai else "agent coaching session"})
    return out
