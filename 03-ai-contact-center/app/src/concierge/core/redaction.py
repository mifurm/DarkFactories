"""PII / PCI redaction (deterministic rules, Luhn / IBAN mod-97 validated). Used for transcripts, logs, audit and LLM context.

Card data must never reach the LLM, transcripts or logs: `redact()` is applied before anything is stored, logged or sent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
    "null": "0", "eins": "1", "ein": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5", "fuenf": "5",
    "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
}  # fmt: skip

_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){3,8}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w-])(?:\+|00)\d[\d ()./-]{7,17}\d(?![\w-])|(?<![\w+-])0\d{2,4}[ /-]?\d{3,}[ /-]?\d{2,}(?![\w-])|(?<![\w+-])\(0\d{2,5}\)[ /.-]?\d[\d .-]{4,12}\d(?![\w-])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_NI = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")
_CVV = re.compile(r"(?i)\b(?:cvv|cvc|security code|sicherheitscode|prüfziffer|pruefziffer)\D{0,6}(\d{3,4})\b")
_SPOKEN = re.compile(r"(?i)\b(?:(?:zero|oh|one|two|three|four|for|five|six|seven|eight|nine|null|eins|ein|zwei|drei|vier|f[uü]e?nf|sechs|sieben|acht|neun)[\s,.-]+){11,}(?:zero|oh|one|two|three|four|for|five|six|seven|eight|nine|null|eins|ein|zwei|drei|vier|f[uü]e?nf|sechs|sieben|acht|neun)\b")  # fmt: skip


@dataclass
class Finding:
    kind: str
    start: int
    end: int


@dataclass
class Redaction:
    text: str
    findings: list[Finding]

    @property
    def kinds(self) -> set[str]:
        return {f.kind for f in self.findings}

    def has(self, kind: str) -> bool:
        return kind in self.kinds


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    v = re.sub(r"\s+", "", value).upper()
    if not 15 <= len(v) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", v):
        return False
    rearranged = v[4:] + v[:4]
    num = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(num) % 97 == 1


def _spans(text: str) -> list[Finding]:
    found: list[Finding] = []
    for m in _CARD.finditer(text):
        if luhn_ok(m.group()):
            found.append(Finding("CARD", m.start(), m.end()))
    for m in _SPOKEN.finditer(text):
        digits = "".join(_DIGIT_WORDS.get(w.lower().replace("ü", "ü"), "") for w in re.findall(r"[A-Za-zü]+", m.group()))
        if len(digits) >= 13 and luhn_ok(digits):
            found.append(Finding("CARD", m.start(), m.end()))
    for m in _IBAN.finditer(text):
        if iban_ok(m.group()):
            found.append(Finding("IBAN", m.start(), m.end()))
    for m in _CVV.finditer(text):
        found.append(Finding("CVV", m.start(1), m.end(1)))
    for m in _EMAIL.finditer(text):
        found.append(Finding("EMAIL", m.start(), m.end()))
    for m in _SSN.finditer(text):
        found.append(Finding("SSN", m.start(), m.end()))
    for m in _NI.finditer(text):
        found.append(Finding("NATIONAL_ID", m.start(), m.end()))
    for m in _PHONE.finditer(text):
        if sum(c.isdigit() for c in m.group()) >= 9:
            found.append(Finding("PHONE", m.start(), m.end()))
    return found


def _merge(spans: list[Finding]) -> list[Finding]:
    priority = {"CARD": 0, "CVV": 1, "IBAN": 2, "SSN": 3, "NATIONAL_ID": 4, "EMAIL": 5, "PHONE": 6}
    spans = sorted(spans, key=lambda f: (f.start, priority.get(f.kind, 9), -(f.end - f.start)))
    out: list[Finding] = []
    for s in spans:
        if out and s.start < out[-1].end:
            continue
        out.append(s)
    return out


def redact(text: str, *, keep: set[str] | None = None) -> Redaction:
    """Replace PII/PCI with typed placeholders. `keep` lists kinds to leave in place (e.g. {'EMAIL'})."""
    if not text:
        return Redaction(text or "", [])
    spans = [s for s in _merge(_spans(text)) if not (keep and s.kind in keep)]
    out, pos = [], 0
    for s in spans:
        out.append(text[pos : s.start])
        out.append(f"[{s.kind}]")
        pos = s.end
    out.append(text[pos:])
    return Redaction("".join(out), spans)


def redact_text(text: str) -> str:
    return redact(text).text


def contains_card(text: str) -> bool:
    return redact(text).has("CARD")


def redact_obj(obj: Any) -> Any:
    """Recursively redact strings inside dict/list structures (for audit/log payloads)."""
    if isinstance(obj, str):
        return redact(obj).text
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact_obj(v) for v in obj]
    return obj


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    user, _, domain = email.partition("@")
    return f"{user[:1]}{'*' * max(len(user) - 1, 2)}@{domain}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"+{'•' * max(len(digits) - 4, 3)}{digits[-4:]}" if digits else "***"
