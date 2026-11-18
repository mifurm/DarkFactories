"""Deterministic offline implementations of Language / Content Safety / Speech (rules + heuristics).
They are also the always-on baseline when Azure services are unreachable."""

from __future__ import annotations

import logging
import math
import re
import struct
from typing import Any

from ..core.ai.base import PiiEntity, TranscriptResult
from ..core.langid import detect_language
from ..core.redaction import redact
from ..core.textutil import fold
from .guard import detect_injection, toxicity_rules

_TOKEN = re.compile(r"[\w€$%.,-]+", re.UNICODE)
_STOP = frozenset(
    ["a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those", "i", "you", "we", "they", "he", "she", "my", "your", "our", "will", "can", "may", "would", "should", "please", "we'll", "i'll", "you'll", "it's", "that's", "there", "their", "them", "us", "as", "by", "from", "if", "so", "but", "not", "no", "yes", "do", "does", "did", "have", "has", "had", "more", "any", "all", "also", "just", "then", "than"]
)
_NUM = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)(?:[.,]\d+)?|\d+(?:[.,]\d+)?")  # 1 599,00 (Polish grouping) or 379.00
_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)|(?<![\d.])(\d{1,2})\.(\d{1,2})\.(?:\d{2,4})?(?!\d)")
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?!\d)")
_WINDOW = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})(?!\d)")


def _date_of(m: re.Match[str]) -> tuple[int, int] | None:
    day, month = (int(m.group(3)), int(m.group(2))) if m.group(1) else (int(m.group(4)), int(m.group(5)))
    return (day, month) if 1 <= day <= 31 and 1 <= month <= 12 else None


def _time_of(m: re.Match[str]) -> tuple[int, int] | None:
    hour, minute = int(m.group(1)), int(m.group(2))
    return (hour, minute) if hour < 24 and minute < 60 else None


def _dates(text: str) -> set[tuple[int, int]]:
    """(day, month) of ISO dates (2026-11-19) and day-first dates (19.11. / 19.11.2026): compared as dates, never as decimal numbers."""
    return {d for m in _DATE.finditer(text) if (d := _date_of(m))}


def _times(text: str) -> set[tuple[int, int]]:
    return {t for m in _TIME.finditer(text) if (t := _time_of(m))}


def _without_dates_and_times(text: str) -> str:
    text = _DATE.sub(lambda m: " " if _date_of(m) else m.group(0), text)
    return _TIME.sub(lambda m: " " if _time_of(m) else m.group(0), text)


_ABSOLUTE = re.compile(r"\b(lifetime|free of charge|no questions asked|for all customers|unlimited|always|never|guaranteed|no matter what)\b", re.IGNORECASE)
# Polish absolute claims, matched on diacritic-folded text and compared by their stem (gwarantowany / gwarantowanego)
_ABSOLUTE_PL = re.compile(r"\b(gwarantow\w*|gwarantuj\w*|dozywotn\w*|bez zadnych pytan|bez wzgledu na wszystko|dla wszystkich klientow|bez ograniczen|za darmo|bezplatn\w*)")
_FREE_SOURCE = re.compile(r"\bfree\b|no charge|no cost|kostenlos|gratuit|bezplatn|za darmo|bez oplat")
# Apologies, thanks and "reply with ..." prompts carry no policy claim; their numbers and absolutes are still checked.
_COURTESY = re.compile(r"^\W*(?:i['’]?m sorry|i am sorry|sorry|my apologies|i apologi[sz]e|thank|thanks|please|if you(?:['’]d| would)? (?:like|prefer|want|wish)|would you like|let me know|just (?:let|reply|tell)|reply with|feel free|of course|certainly)\b", re.IGNORECASE)
# Polish counterpart, matched on diacritic-folded text: thanks, apologies, "please let me know", offers of further help, and what the agent itself
# can or cannot do / will do next ("I can pass this to a colleague", "I can't delete that myself", "I'll check") - statements about the agent, not claims about policy
_COURTESY_PL = re.compile(
    r"^\W*(?:dziekuj\w*|dzieki|bardzo prosze|prosze\b|przepraszam|przykro mi|rozumiem|oczywiscie|chetnie|z przyjemnoscia|jesli (?:chce|pan|pani|mozna)|czy (?:chcialby|chcialaby|mam|moge|mozna|zyczy)|w czym jeszcze|milego dnia|do widzenia"
    r"|(?:niestety )?nie moge\b|(?:(?:tez|takze|rowniez|od razu|chetnie|oczywiscie|natomiast|jednak) )*moge\b"
    r"|(?:zaraz |od razu )?(?:przekaze|polacze|sprawdze|zapytam|zaloze|zarezerwuje|zlece|ustawie|poprosze|zglosze|zarejestruje|wysle))\b"
)
# Words that carry no fact in a Polish answer (connectives / fillers); only the groundedness check uses them, retrieval keeps its own stop list
_GROUND_STOP_PL = frozenset(["albo", "oraz", "wiec", "jednak", "rowniez", "takze", "wtedy", "teraz", "zaraz", "razu", "moge", "mozemy", "prosze"])


def _stem(tok: str) -> str:
    for suf in ("ings", "ing", "ed", "es", "s", "en", "er", "ly"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def _content_tokens(text: str) -> list[str]:
    return [_stem(t.lower().strip(".,")) for t in _TOKEN.findall(text) if t.lower() not in _STOP and len(t) > 2]


def _content_tokens_pl(text: str) -> list[str]:
    """Polish content words, diacritic-folded and stemmed the way the Polish retrieval does it (roboczego / roboczych -> robocz); numbers of any
    length count (a slot list "20.11 08:00-12:00" is as supported as the tool result it repeats - the number check verifies their values)."""
    from .kb import _STOP_PL, _stem_pl

    return [_stem_pl(t) for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in _STOP_PL and t not in _GROUND_STOP_PL and (len(t) > 2 or t.isdigit())]


def mostly_polish(texts: list[str]) -> bool:
    lang, conf = detect_language(" ".join(texts)[:4000], default="en")
    return lang == "pl" and conf >= 0.5


def _num(n: str) -> float:
    return round(float(re.sub(r"[ \u00a0\u202f]", "", n).replace(",", ".")), 2)


def lexical_groundedness(answer: str, sources: list[str], check_words: bool = True, lang: str | None = None) -> dict[str, Any]:
    """Sentence-level support check: numbers must appear in sources (numerically) and >=55 % of content words must be supported
    (the word check is skipped when answer and sources are in different languages; `lang="pl"` compares Polish stems)."""
    tokenize = _content_tokens_pl if lang == "pl" else _content_tokens
    src_text = " ".join(sources)
    src_tokens = set(tokenize(src_text))
    src_numbers = {_num(n) for n in _NUM.findall(src_text)}
    for m in _WINDOW.finditer(src_text):  # the length of a time window (08:00-12:00 -> 4 hours) is a supported fact
        hours = (int(m.group(3)) * 60 + int(m.group(4)) - int(m.group(1)) * 60 - int(m.group(2))) / 60
        if hours > 0:
            src_numbers.add(round(hours, 2))
    src_dates, src_times = _dates(src_text), _times(src_text)
    src_folded = fold(src_text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if s.strip()]
    ungrounded: list[dict[str, str]] = []
    checked = 0
    for s in sentences:
        if s.endswith("?"):
            continue
        toks = tokenize(s)
        nums = {_num(n) for n in _NUM.findall(_without_dates_and_times(s))}
        dates, times = _dates(s), _times(s)
        if len(toks) < 4 and not nums and not dates and not times:
            continue
        checked += 1
        support = sum(1 for t in toks if t in src_tokens) / max(len(toks), 1)
        bad_numbers = {n for n in nums if n not in src_numbers and n not in (1.0, 2.0, 3.0)}
        bad_schedule = {d for d in dates if src_dates and d not in src_dates} | {t for t in times if src_times and t not in src_times}
        absolutes = {m.group(0).lower() for m in _ABSOLUTE.finditer(s)} if check_words else set()
        unsupported_absolute = {a for a in absolutes if a not in src_text.lower() and not (a == "free of charge" and re.search(r"\bfree\b|no charge|no cost|kostenlos|gratuit", src_text, re.IGNORECASE))}
        for m in _ABSOLUTE_PL.finditer(fold(s)):  # applied to every answer: a Polish promise must be backed by the sources whatever the check_words setting
            claim = m.group(0)
            root = claim if " " in claim else claim[:7]
            if root not in src_folded and not (root in ("bezplat", "za darmo") and _FREE_SOURCE.search(src_folded)):
                unsupported_absolute.add(claim)
        weak = check_words and not _COURTESY.match(s) and not (lang == "pl" and _COURTESY_PL.match(fold(s))) and support < 0.55
        if bad_numbers or bad_schedule or unsupported_absolute or weak:
            ungrounded.append({"text": s, "hard": bool(bad_numbers or bad_schedule or unsupported_absolute)})
    pct = len(ungrounded) / checked if checked else 0.0
    return {"ungroundedDetected": bool(ungrounded), "hardViolation": any(u["hard"] for u in ungrounded), "ungroundedPercentage": round(pct, 3), "ungroundedDetails": ungrounded, "provider": "lexical"}


def _norm_claim(text: str) -> str:
    return " ".join(re.sub(r"[^\w€$%]+", " ", str(text).casefold()).split())


def _same_claim_flagged(remote: dict[str, Any], local: dict[str, Any]) -> bool:
    """Soft verdict: Azure and the deterministic check must flag the same sentence (an Azure-only flag on an empathy line plus a local-only
    flag on a procedural line are two independent false alarms, not one confirmed ungrounded claim)."""
    if not (remote.get("ungroundedDetected") and local.get("ungroundedDetected")):
        return False
    azure = [_norm_claim(d.get("text", "")) for d in remote.get("ungroundedDetails", []) if isinstance(d, dict) and d.get("text")]
    if not azure:
        return True
    mine = [_norm_claim(d["text"]) for d in local.get("ungroundedDetails", [])]
    return any(a and b and (a in b or b in a) for a in azure for b in mine)


class OfflineCognitive:
    name = "offline"

    async def detect_language(self, text: str) -> tuple[str, float]:
        return detect_language(text)

    async def pii_entities(self, text: str, language: str = "en") -> list[PiiEntity]:
        return [PiiEntity(f.kind, text[f.start : f.end], f.start, f.end - f.start) for f in redact(text).findings]

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> dict[str, Any]:
        return {"userPromptAttack": bool(detect_injection(user_prompt)), "documentsAttack": [bool(detect_injection(d)) for d in documents or []]}

    async def analyze_text(self, text: str) -> dict[str, int]:
        return toxicity_rules(text)

    async def groundedness(self, query: str, answer: str, sources: list[str], language: str = "en") -> dict[str, Any]:
        polish = language == "pl" and mostly_polish(sources)  # a Polish answer is compared word by word only with Polish sources (a cross-language answer cannot be)
        return lexical_groundedness(answer, sources, check_words=language == "en" or polish, lang="pl" if polish else None)

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "provider": "offline-rules"}

    async def close(self) -> None:
        return None


class ResilientCognitive:
    """Azure first; any failure (throttling, outage, policy) falls back to the deterministic rules so the product keeps working."""

    name = "azure+rules"

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback
        self.failures = 0

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await getattr(self.primary, method)(*args, **kwargs)
        except Exception as exc:
            self.failures += 1
            logging.getLogger("concierge.cognitive").warning("%s failed (%s); using rules", method, type(exc).__name__)
            return await getattr(self.fallback, method)(*args, **kwargs)

    async def detect_language(self, text: str) -> tuple[str, float]:
        return await self._call("detect_language", text)

    async def pii_entities(self, text: str, language: str = "en") -> list[PiiEntity]:
        return await self._call("pii_entities", text, language)

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> dict[str, Any]:
        return await self._call("shield_prompt", user_prompt, documents)

    async def analyze_text(self, text: str) -> dict[str, int]:
        return await self._call("analyze_text", text)

    async def groundedness(self, query: str, answer: str, sources: list[str], language: str = "en") -> dict[str, Any]:
        """Two-key verdict. Hard evidence (a number or an absolute claim that no source contains) replaces an answer on its own; soft evidence
        (low word support - Azure Content Safety groundedness is tuned for English and can flag paraphrases and cross-language answers)
        needs both Azure and the deterministic check to agree. An Azure flag alone never replaces an answer."""
        local = await self.fallback.groundedness(query, answer, sources, language)
        try:
            remote = await self.primary.groundedness(query, answer, sources, language)
        except Exception as exc:
            self.failures += 1
            logging.getLogger("concierge.cognitive").warning("groundedness failed (%s); using rules", type(exc).__name__)
            return local
        flag = bool(local.get("hardViolation")) or _same_claim_flagged(remote, local)
        return {**remote, "ungroundedDetected": flag, "azure_flag": bool(remote["ungroundedDetected"]), "local_flag": bool(local["ungroundedDetected"]), "local_hard": bool(local.get("hardViolation")), "provider": "azure-content-safety+rules"}

    async def ping(self) -> dict[str, Any]:
        return await self.primary.ping()

    async def close(self) -> None:
        await self.primary.close()


def synth_tone_wav(text: str, rate: int = 24000) -> bytes:
    """Offline 'TTS': a soft two-tone chirp whose length follows the text length (UI/pipeline demonstration only)."""
    seconds = min(max(len(text) / 15.0, 0.6), 8.0)
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        envelope = min(1.0, t * 20, (seconds - t) * 20)
        f = 330 + 110 * math.sin(2 * math.pi * 3 * t)
        frames += struct.pack("<h", int(9000 * envelope * math.sin(2 * math.pi * f * t)))
    from ..core.ai.azure_cognitive import wav_from_pcm16

    return wav_from_pcm16(bytes(frames), rate)


class OfflineSpeech:
    name = "offline-speech"

    async def transcribe(self, audio: bytes, *, mime: str = "audio/wav", language: str | None = None) -> TranscriptResult:
        # Test/demo convenience: audio payloads that start with b"TEXT:" carry their own transcript.
        if audio.startswith(b"TEXT:"):
            txt = audio[5:].decode("utf-8", "ignore").strip()
            return TranscriptResult(text=txt, language=detect_language(txt)[0], duration_s=max(len(txt) / 15.0, 0.5))
        return TranscriptResult(text="", language=language or "en", duration_s=len(audio) / 48000.0)

    async def synthesize(self, text: str, *, language: str = "en", voice: str | None = None) -> tuple[bytes, str]:
        return synth_tone_wav(text), "audio/wav"

    async def close(self) -> None:
        return None
