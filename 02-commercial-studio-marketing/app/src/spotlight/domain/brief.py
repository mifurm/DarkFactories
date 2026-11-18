"""Brief parsing + completeness (deterministic first; the Briefing agent's LLM extraction fills the gaps).

English and Polish briefs are both understood: labels are matched folded (``Budżet:`` = ``Budzet:``), countries by their Polish and
English names, KPIs with Polish nouns/number formats (``120 000 zakupów próbnych``), quotes in ``„…”`` style.
"""

from __future__ import annotations

import re
from typing import Any

from .text import fold

COUNTRIES = {
    "us": "US", "usa": "US", "united states": "US", "america": "US", "de": "DE", "germany": "DE", "deutschland": "DE", "fr": "FR", "france": "FR",
    "pl": "PL", "poland": "PL", "polska": "PL", "es": "ES", "spain": "ES", "it": "IT", "italy": "IT", "pt": "PT", "portugal": "PT", "nl": "NL",
    "netherlands": "NL", "uk": "GB", "united kingdom": "GB", "gb": "GB", "canada": "CA", "ca": "CA",
    # Polish names (folded: "Polsce" = "Polsce", "Włoszech" = "wloszech")
    "polsce": "PL", "polski": "PL", "polske": "PL", "niemcy": "DE", "niemczech": "DE", "niemiec": "DE", "francja": "FR", "francji": "FR", "francje": "FR",
    "stany zjednoczone": "US", "stanach zjednoczonych": "US", "stanow zjednoczonych": "US", "wielka brytania": "GB", "wielkiej brytanii": "GB",
    "hiszpania": "ES", "hiszpanii": "ES", "wlochy": "IT", "wloszech": "IT", "portugalia": "PT", "portugalii": "PT", "holandia": "NL", "holandii": "NL",
    "niderlandy": "NL", "niderlandach": "NL", "kanada": "CA", "kanadzie": "CA",
}
CHANNELS = {
    "youtube": "youtube", "yt": "youtube", "meta": "meta", "instagram": "meta", "facebook": "meta", "reels": "meta", "tiktok": "tiktok",
    "linkedin": "linkedin", "ctv": "ctv", "connected tv": "ctv", "tv": "ctv", "telewizja": "ctv", "telewizji": "ctv", "display": "display", "ooh": "ooh", "email": "email", "web": "web",
}
REQUIRED = ["objective", "audience", "channels", "markets", "product", "kpis", "budget", "timeline", "tone", "key_message", "cta", "duration_targets"]
OPTIONAL = ["mandatories", "music_reference", "talent"]
LABELS = {
    "objective": ["objective", "goal", "purpose", "cel", "cel kampanii", "cele", "zadanie"],
    "audience": ["audience", "target", "target audience", "odbiorcy", "odbiorca", "grupa docelowa", "grupa odbiorcow"],
    "channels": ["channels", "channel", "media", "platforms", "kanaly", "kanal", "platformy"],
    "markets": ["markets", "market", "countries", "regions", "rynki", "rynek", "kraje", "regiony"],
    "product": ["product", "products", "sku", "produkt", "produkty"],
    "kpis": ["kpi", "kpis", "success metrics", "success", "metrics", "wskazniki", "miary sukcesu", "mierniki"],
    "budget": ["budget", "spend", "budzet", "wydatki"],
    "timeline": ["timeline", "timing", "deadline", "dates", "harmonogram", "terminy", "termin", "daty"],
    "mandatories": ["mandatories", "mandatory", "must include", "must-haves", "obowiazkowe", "elementy obowiazkowe", "obowiazkowo", "wymagane", "musi zawierac"],
    "tone": ["tone", "tone of voice", "voice", "ton", "ton komunikacji", "styl"],
    "key_message": ["key message", "single-minded proposition", "proposition", "message", "kluczowy przekaz", "glowny przekaz", "przekaz", "propozycja"],
    "cta": ["cta", "call to action", "call-to-action", "wezwanie do dzialania"],
    "duration_targets": ["durations", "duration", "lengths", "formats", "dlugosci", "dlugosc", "czas trwania", "formaty"],
    "music_reference": ["music", "music reference", "soundtrack", "muzyka", "podklad muzyczny", "sciezka dzwiekowa"],
    "talent": ["talent", "voice-over", "voiceover", "vo", "lektor", "glos lektorski", "aktor"],
}
_ALIAS_TO_FIELD = {alias: key for key, aliases in LABELS.items() for alias in aliases}

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
QUESTIONS_PL = {
    "objective": "Jaki jest cel biznesowy kampanii (np. pierwszy zakup, zasięg, rozważanie zakupu) i po czym będzie widać, że się udała?",
    "audience": "Kto dokładnie jest odbiorcą kampanii (wiek, nastawienie, sytuacja, w której zobaczy reklamę)?",
    "channels": "Na jakich kanałach będą emitowane spoty (YouTube, Meta, TikTok, CTV, …)?",
    "markets": "Jakie rynki (kraje) i języki są potrzebne?",
    "product": "Który produkt jest bohaterem kampanii?",
    "kpis": "Jakie KPI mają być optymalizowane i jakie są ich wartości docelowe (np. CPA, ROAS, odsetek obejrzeń do końca)?",
    "budget": "Jaki jest budżet mediowy, a jaki produkcyjny?",
    "timeline": "Jakie są kluczowe terminy (koncepcja, dostawa finalnych materiałów, start emisji)?",
    "tone": "Jak spot ma brzmieć i jakie wrażenie robić (trzy przymiotniki)?",
    "key_message": "Co dokładnie widz ma zapamiętać po obejrzeniu spotu (jedno zdanie)?",
    "cta": "Co widzowie mają zrobić dalej i dokąd spot ma ich skierować (sklep, adres URL, oferta)?",
    "duration_targets": "Jakich długości spotów potrzeba: bumper 6 s, 15 s, 30 s, 60 s?",
}
FIELD_LABELS_PL = {
    "objective": "cel", "audience": "odbiorcy", "channels": "kanały", "markets": "rynki", "product": "produkt", "kpis": "KPI", "budget": "budżet", "timeline": "harmonogram",
    "tone": "ton", "key_message": "kluczowy przekaz", "cta": "wezwanie do działania", "duration_targets": "długości spotów",
}
_STOP_NUM = r"\d[\d\s\u00a0\u202f,\.]*"


def _listify(v: Any, lang: str = "en") -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    sep = r"[,;/]| and " if lang == "en" else r"[,;/]| and | i | oraz "
    return [p.strip() for p in re.split(sep, str(v or "")) if p.strip()]


def normalize_channels(items: list[str]) -> list[str]:
    out: list[str] = []
    for it in items:
        low = fold(it.lower())
        for key, val in CHANNELS.items():
            if re.search(rf"\b{re.escape(key)}\b", low) and val not in out:
                out.append(val)
    return out


def normalize_markets(items: list[str] | str) -> list[str]:
    text = " ".join(items) if isinstance(items, list) else str(items)
    low = fold(text).lower()  # "Włoszech" -> "wloszech"; offsets stay aligned with ``text``
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
    """Heuristic extraction from a pasted brief: 'Label: value' lines + a few sentence patterns (English or Polish)."""
    fields: dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([^\W\d_][\w \-/]{1,32}):\s*(.+)$", line)
        if not m:
            continue
        label, value = fold(m.group(1).strip().lower()), m.group(2).strip()
        key = _ALIAS_TO_FIELD.get(label)
        if key:
            fields[key] = value
    # product / markets / kpis hints from running text
    low = fold(text).lower()
    if "product" not in fields:
        mm = re.search(r"launch(?:es|ing)?\s+([A-Z][\w ]+?)(?:,| our|\s+in\s|\.)", text)
        if not mm:
            mm = re.search(r"(?:[Ww]prowadzamy(?:\s+na\s+rynek)?|[Pp]remiera|[Ll]ansujemy|[Uu]ruchamiamy)\s+([A-ZŁŚŻŹĆ][\w ]+?)(?:,|\s+naszą|\s+naszego|\s+w\s|\s+na\s|\.)", text)
        if mm:
            fields["product"] = mm.group(1).strip()
    if "markets" not in fields:
        mk = normalize_markets(text)
        if mk:
            fields["markets"] = mk
    if "kpis" not in fields:
        k = re.findall(r"\b\d[\d,\.]*\s*(?:k|m)?\s+(?:trial\s+)?(?:purchases|sales|leads|sign-?ups|installs|orders)[^.;\n]*", text, re.IGNORECASE)
        k += re.findall(r"\b(?:cpa|roas|ctr|vtr)\b[^.;\n]{0,40}\d[^.;\n]*", text, re.IGNORECASE)
        pl_nouns = r"(?:prob\w*\s+)?(?:zakup\w*|sprzedaz\w*|lead\w*|rejestracj\w*|instalacj\w*|zamowien\w*|transakcj\w*)"
        for m in re.finditer(rf"\b{_STOP_NUM}\s*(?:tys\.|mln)?\s*{pl_nouns}[^.;\n]*", low):
            k.append(text[m.start() : m.end()].strip())
        if k:
            fields["kpis"] = [x.strip() for x in k]
    if "tone" not in fields and ("warm" in low or "cieplo" in low or "ciepl" in low):
        fields["tone"] = "warm, unhurried, honest" if "warm" in low else "ciepły, niespieszny, szczery"
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
    return [q.strip() for q in re.findall(r"[\"“”„«»']([^\"“”„«»']{4,160})[\"“”„«»']", text)]


def normalize_fields(f: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """Normalise the brief fields. Trailing sentence periods on list items ("ciepły, szczery.") are dropped for non-English briefs only."""
    strip = (lambda x: x) if lang == "en" else (lambda x: x.rstrip("."))
    out: dict[str, Any] = {}
    out["objective"] = str(f.get("objective", "")).strip()
    out["audience"] = str(f.get("audience", "")).strip()
    out["channels"] = normalize_channels(_listify(f.get("channels"), lang))
    mk = f.get("markets")
    out["markets"] = [str(m).upper() for m in mk] if isinstance(mk, list) else normalize_markets(str(mk or ""))
    out["product"] = str(f.get("product", "")).strip()
    out["kpis"] = _listify(f.get("kpis"), lang)
    out["budget"] = str(f.get("budget", "")).strip()
    out["timeline"] = str(f.get("timeline", "")).strip()
    out["mandatories"] = mandatory_lines(f.get("mandatories", []))
    out["tone"] = [strip(x) for x in _listify(f.get("tone"), lang)]
    out["key_message"] = str(f.get("key_message", "")).strip()
    out["cta"] = str(f.get("cta", "")).strip()
    out["duration_targets"] = parse_durations(f.get("duration_targets", []))
    out["music_reference"] = str(f.get("music_reference", "")).strip()
    out["talent"] = [strip(x) for x in _listify(f.get("talent"), lang)]
    return out


def completeness(fields: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED if not fields.get(k)]
    score = round(100 * (len(REQUIRED) - len(missing)) / len(REQUIRED))
    return {"score": score, "missing": missing, "required": REQUIRED, "ready": score >= 80 and "objective" not in missing and "audience" not in missing}


def template_questions(missing: list[str], product: str = "", lang: str = "en") -> list[dict[str, str]]:
    """At most three clarifying questions (priority order) in the campaign language — also the offline Briefing agent's output."""
    priority = ["objective", "audience", "key_message", "cta", "duration_targets", "kpis", "markets", "channels", "budget", "timeline", "tone", "product"]
    ordered = sorted(missing, key=lambda m: priority.index(m) if m in priority else 99)
    out = []
    for m in ordered[:3]:
        if lang == "pl":
            q = QUESTIONS_PL[m]
            if product and m in {"key_message", "cta"}:
                q = q.replace("po obejrzeniu spotu", f"po obejrzeniu spotu {product}").replace("dokąd spot ma", f"dokąd spot {product} ma")
            why = f"Potrzebne, aby napisać scenariusz zgodny z briefem i wybrać właściwe formaty ({FIELD_LABELS_PL.get(m, m)})."
        else:
            q = QUESTIONS[m]
            if product and m in {"key_message", "cta"}:
                q = q.replace("the spot", f"the {product} spot")
            why = f"Needed to write a brief-compliant script and choose the right formats ({m.replace('_', ' ')})."
        out.append({"field": m, "question": q, "why": why})
    return out
