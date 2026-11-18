"""Brief parsing + completeness (deterministic first; the Briefing agent's LLM extraction fills the gaps)."""

from __future__ import annotations

import re
from typing import Any

COUNTRIES = {
    "us": "US", "usa": "US", "united states": "US", "america": "US", "de": "DE", "germany": "DE", "deutschland": "DE", "fr": "FR", "france": "FR",
    "pl": "PL", "poland": "PL", "polska": "PL", "es": "ES", "spain": "ES", "it": "IT", "italy": "IT", "pt": "PT", "portugal": "PT", "nl": "NL",
    "netherlands": "NL", "uk": "GB", "united kingdom": "GB", "gb": "GB", "canada": "CA", "ca": "CA",
}
CHANNELS = {
    "youtube": "youtube", "yt": "youtube", "meta": "meta", "instagram": "meta", "facebook": "meta", "reels": "meta", "tiktok": "tiktok",
    "linkedin": "linkedin", "ctv": "ctv", "connected tv": "ctv", "tv": "ctv", "display": "display", "ooh": "ooh", "email": "email", "web": "web",
}
REQUIRED = ["objective", "audience", "channels", "markets", "product", "kpis", "budget", "timeline", "tone", "key_message", "cta", "duration_targets"]
OPTIONAL = ["mandatories", "music_reference", "talent"]
LABELS = {
    "objective": ["objective", "goal", "purpose"],
    "audience": ["audience", "target", "target audience"],
    "channels": ["channels", "channel", "media", "platforms"],
    "markets": ["markets", "market", "countries", "regions"],
    "product": ["product", "products", "sku"],
    "kpis": ["kpi", "kpis", "success metrics", "success", "metrics"],
    "budget": ["budget", "spend"],
    "timeline": ["timeline", "timing", "deadline", "dates"],
    "mandatories": ["mandatories", "mandatory", "must include", "must-haves"],
    "tone": ["tone", "tone of voice", "voice"],
    "key_message": ["key message", "single-minded proposition", "proposition", "message"],
    "cta": ["cta", "call to action", "call-to-action"],
    "duration_targets": ["durations", "duration", "lengths", "formats"],
    "music_reference": ["music", "music reference", "soundtrack"],
    "talent": ["talent", "voice-over", "voiceover", "vo"],
}
QUESTIONS = {
    "objective": "What is the business objective of this campaign (e.g. trial, awareness, consideration) and how will you know it worked?",
    "audience": "Who exactly is the primary audience (age range, mindset, situation when they see the ad)?",
    "channels": "Which channels will the spots run on (YouTube, Meta, TikTok, CTV, …)?",
    "markets": "Which markets (countries) and languages do we need?",
    "product": "Which product is the hero of this campaign?",
    "kpis": "Which KPIs should we optimise for, and what target values (e.g. CPA, ROAS, completion rate)?",
    "budget": "What are the media and production budgets?",
    "timeline": "What are the key dates (concept, final delivery, go-live)?",
    "tone": "How should the spot sound and feel (three adjectives)?",
    "key_message": "What is the single thing a viewer should remember after the spot — in one sentence?",
    "cta": "What should viewers do next, and where should the spot send them (store, URL, offer)?",
    "duration_targets": "Which spot lengths do you need — 6 s bumper, 15 s, 30 s, 60 s?",
}


def _listify(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [p.strip() for p in re.split(r"[,;/]| and ", str(v or "")) if p.strip()]


def normalize_channels(items: list[str]) -> list[str]:
    out: list[str] = []
    for it in items:
        low = it.lower()
        for key, val in CHANNELS.items():
            if re.search(rf"\b{re.escape(key)}\b", low) and val not in out:
                out.append(val)
    return out


def normalize_markets(items: list[str] | str) -> list[str]:
    text = " ".join(items) if isinstance(items, list) else str(items)
    low = text.lower()
    found: list[tuple[int, str]] = []
    for key, code in COUNTRIES.items():
        if len(key) <= 2:  # 2-letter ISO codes only count when written in capitals (avoids 'it', 'de', 'ca', 'es' in prose)
            continue
        m = re.search(rf"\b{re.escape(key)}\b", low)
        if m:
            found.append((m.start(), code))
    for m in re.finditer(r"\b[A-Z]{2}\b", text):
        if m.group(0) in COUNTRIES.values():
            found.append((m.start(), m.group(0)))
    out: list[str] = []
    for _, code in sorted(found):
        if code not in out:
            out.append(code)
    return out


def parse_durations(value: Any) -> list[int]:
    if isinstance(value, list):
        nums = [int(x) for x in value if str(x).isdigit()]
    else:
        nums = [int(x) for x in re.findall(r"\d+", str(value))]
    return sorted({n for n in nums if n in (6, 10, 15, 20, 30, 45, 60)})


def parse_labeled(text: str) -> dict[str, Any]:
    """Heuristic extraction from a pasted brief: 'Label: value' lines + a few sentence patterns."""
    fields: dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z \-/]{1,32}):\s*(.+)$", line)
        if not m:
            continue
        label, value = m.group(1).strip().lower(), m.group(2).strip()
        for key, aliases in LABELS.items():
            if label in aliases:
                fields[key] = value
                break
    # product / markets / kpis hints from running text
    low = text.lower()
    if "product" not in fields:
        mm = re.search(r"launch(?:es|ing)?\s+([A-Z][\w ]+?)(?:,| our|\s+in\s|\.)", text)
        if mm:
            fields["product"] = mm.group(1).strip()
    if "markets" not in fields:
        mk = normalize_markets(text)
        if mk:
            fields["markets"] = mk
    if "kpis" not in fields:
        k = re.findall(r"\b\d[\d,\.]*\s*(?:k|m)?\s+(?:trial\s+)?(?:purchases|sales|leads|sign-?ups|installs|orders)[^.;\n]*", text, re.IGNORECASE)
        k += re.findall(r"\b(?:cpa|roas|ctr|vtr)\b[^.;\n]{0,40}\d[^.;\n]*", text, re.IGNORECASE)
        if k:
            fields["kpis"] = [x.strip() for x in k]
    if "tone" not in fields and "warm" in low:
        fields["tone"] = "warm, unhurried, honest"
    return fields


def mandatory_lines(raw: str | list[str]) -> list[str]:
    """Split a mandatories blurb into discrete items; quoted text stays verbatim."""
    if isinstance(raw, list):
        return [r.strip() for r in raw if r.strip()]
    items: list[str] = []
    for part in re.split(r";|\n", raw):
        part = part.strip(" .")
        if part:
            items.append(part[0].upper() + part[1:])
    return items


def quoted(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[\"“”']([^\"“”']{4,160})[\"“”']", text)]


def normalize_fields(f: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["objective"] = str(f.get("objective", "")).strip()
    out["audience"] = str(f.get("audience", "")).strip()
    out["channels"] = normalize_channels(_listify(f.get("channels")))
    mk = f.get("markets")
    out["markets"] = [str(m).upper() for m in mk] if isinstance(mk, list) else normalize_markets(str(mk or ""))
    out["product"] = str(f.get("product", "")).strip()
    out["kpis"] = _listify(f.get("kpis"))
    out["budget"] = str(f.get("budget", "")).strip()
    out["timeline"] = str(f.get("timeline", "")).strip()
    out["mandatories"] = mandatory_lines(f.get("mandatories", []))
    out["tone"] = _listify(f.get("tone"))
    out["key_message"] = str(f.get("key_message", "")).strip()
    out["cta"] = str(f.get("cta", "")).strip()
    out["duration_targets"] = parse_durations(f.get("duration_targets", []))
    out["music_reference"] = str(f.get("music_reference", "")).strip()
    out["talent"] = _listify(f.get("talent"))
    return out


def completeness(fields: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED if not fields.get(k)]
    score = round(100 * (len(REQUIRED) - len(missing)) / len(REQUIRED))
    return {"score": score, "missing": missing, "required": REQUIRED, "ready": score >= 80 and "objective" not in missing and "audience" not in missing}


def template_questions(missing: list[str], product: str = "") -> list[dict[str, str]]:
    priority = ["objective", "audience", "key_message", "cta", "duration_targets", "kpis", "markets", "channels", "budget", "timeline", "tone", "product"]
    ordered = sorted(missing, key=lambda m: priority.index(m) if m in priority else 99)
    out = []
    for m in ordered[:3]:
        q = QUESTIONS[m]
        if product and m in {"key_message", "cta"}:
            q = q.replace("the spot", f"the {product} spot")
        out.append({"field": m, "question": q, "why": f"Needed to write a brief-compliant script and choose the right formats ({m.replace('_', ' ')})."})
    return out
