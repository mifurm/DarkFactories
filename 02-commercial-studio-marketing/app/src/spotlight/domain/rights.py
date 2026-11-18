"""Rights & consent registry logic (CS-03): licences, talent consent, windows, territories, channels."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .claims import market_matches
from .text import normalize


class RightsEntry(BaseModel):
    id: str
    brand_id: str = "northwind"
    kind: Literal["music", "talent", "stock", "font", "other"]
    title: str
    licensor: str | None = None
    status: Literal["active", "pending", "revoked"] = "active"
    territories: list[str] = Field(default_factory=lambda: ["WW"])
    channels: list[str] = Field(default_factory=list)  # empty = unrestricted
    valid_from: str | None = None
    valid_to: str | None = None
    ai_voice_consent: bool = False
    ai_likeness_consent: bool = False
    library_track: dict[str, Any] | None = None  # procedural library track params (mood, bpm, key, seed)
    usage_notes: str = ""
    aliases: list[str] = Field(default_factory=list)


class RightsVerdict(BaseModel):
    ok: bool
    code: str
    severity: Literal["block", "warn", "info"]
    message: str
    entry_id: str | None = None


def _d(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def today() -> date:
    return datetime.now(UTC).date()


def find_entry(registry: list[RightsEntry], kind: str, title: str | None = None, rights_id: str | None = None) -> RightsEntry | None:
    if rights_id:
        for e in registry:
            if e.id == rights_id:
                return e
    if title:
        nt = normalize(title)
        for e in registry:
            if e.kind == kind and (normalize(e.title) == nt or nt in {normalize(a) for a in e.aliases}):
                return e
        for e in registry:  # looser: one name contains the other (e.g. "Maya Okafor" vs "Maya")
            if e.kind == kind and (nt in normalize(e.title) or normalize(e.title) in nt) and len(nt) > 3:
                return e
    return None


def check_use(
    entry: RightsEntry,
    markets: list[str],
    channels: list[str],
    air_start: str | None = None,
    air_end: str | None = None,
    now: date | None = None,
    ai_synthesis: bool = False,
    usage: str = "voice",
) -> list[RightsVerdict]:
    """All reasons this registry entry does (not) cover the intended use. Empty blocking list == cleared."""
    now = now or today()
    out: list[RightsVerdict] = []
    eid = entry.id
    if entry.status != "active":
        out.append(RightsVerdict(ok=False, code="rights.not_active", severity="block", message=f"'{entry.title}' licence status is {entry.status}", entry_id=eid))
    vf, vt = _d(entry.valid_from), _d(entry.valid_to)
    start, end = _d(air_start) or now, _d(air_end) or _d(air_start) or now
    if vt and vt < now:
        out.append(RightsVerdict(ok=False, code="rights.expired", severity="block", message=f"'{entry.title}' {'consent' if entry.kind == 'talent' else 'licence'} expired on {entry.valid_to}", entry_id=eid))
    elif vt and end > vt:
        out.append(RightsVerdict(ok=False, code="rights.window", severity="block", message=f"'{entry.title}' licence ends {entry.valid_to}, before the planned air window ends ({end.isoformat()})", entry_id=eid))
    if vf and start < vf:
        out.append(RightsVerdict(ok=False, code="rights.window", severity="block", message=f"'{entry.title}' licence starts {entry.valid_from}, after the planned air start ({start.isoformat()})", entry_id=eid))
    if vt and now <= vt <= now + timedelta(days=30) and not any(v.code.startswith("rights.expired") for v in out):
        out.append(RightsVerdict(ok=True, code="rights.expiring", severity="warn", message=f"'{entry.title}' licence expires on {entry.valid_to} (≤30 days)", entry_id=eid))
    if not market_matches(entry.territories, markets):
        out.append(RightsVerdict(ok=False, code="rights.territory", severity="block", message=f"'{entry.title}' is not licensed for territories {', '.join(markets)} (covers {', '.join(entry.territories)})", entry_id=eid))
    if entry.channels and channels:
        bad = [c for c in channels if c.lower() not in {x.lower() for x in entry.channels}]
        if bad:
            out.append(RightsVerdict(ok=False, code="rights.channel", severity="block", message=f"'{entry.title}' is not cleared for channel(s): {', '.join(bad)} (allowed: {', '.join(entry.channels)})", entry_id=eid))
    if entry.kind == "talent" and ai_synthesis:
        consent = entry.ai_voice_consent if usage == "voice" else entry.ai_likeness_consent
        if not consent:
            out.append(RightsVerdict(ok=False, code="rights.no_ai_consent", severity="block", message=f"'{entry.title}' has not consented to AI-synthesised {usage}", entry_id=eid))
    if not out:
        out.append(RightsVerdict(ok=True, code="rights.cleared", severity="info", message=f"'{entry.title}' is cleared for this use", entry_id=eid))
    return out


def is_cleared(verdicts: list[RightsVerdict]) -> bool:
    return not any(v.severity == "block" for v in verdicts)


def expiring(registry: list[RightsEntry], within_days: int = 30, now: date | None = None) -> list[dict[str, Any]]:
    now = now or today()
    out = []
    for e in registry:
        vt = _d(e.valid_to)
        if vt is None:
            continue
        left = (vt - now).days
        if left <= within_days:
            out.append({"id": e.id, "title": e.title, "kind": e.kind, "valid_to": e.valid_to, "days_left": left, "state": "expired" if left < 0 else "expiring"})
    return sorted(out, key=lambda r: r["days_left"])


def best_replacement_track(
    registry: list[RightsEntry],
    markets: list[str],
    channels: list[str],
    air_start: str | None,
    air_end: str | None,
    mood: str | None = None,
    exclude_ids: set[str] | None = None,
    now: date | None = None,
) -> RightsEntry | None:
    """Licensed library track that clears the intended use, preferring a matching mood."""
    cands = []
    for e in registry:
        if e.kind != "music" or not e.library_track or (exclude_ids and e.id in exclude_ids):
            continue
        if is_cleared(check_use(e, markets, channels, air_start, air_end, now)):
            score = 2 if mood and mood.lower() == str(e.library_track.get("mood", "")).lower() else 0
            cands.append((score, e.title, e))
    cands.sort(key=lambda t: (-t[0], t[1]))
    return cands[0][2] if cands else None
