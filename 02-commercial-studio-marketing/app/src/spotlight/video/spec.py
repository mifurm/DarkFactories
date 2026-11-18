"""Render specification — the 'master' timeline the compositor renders (and the format factory derives from)."""

from __future__ import annotations

import itertools
from typing import Literal

from pydantic import BaseModel, Field

ASPECTS: dict[str, tuple[int, int]] = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720), "4:5": (576, 720)}
MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax")
# Platform UI keeps the bottom / sides of vertical video busy: keep captions & supers out of these margins.
SAFE_AREAS = {
    "16:9": {"top": 0.06, "bottom": 0.10, "left": 0.06, "right": 0.06},
    "9:16": {"top": 0.10, "bottom": 0.22, "left": 0.07, "right": 0.12},
    "1:1": {"top": 0.06, "bottom": 0.10, "left": 0.07, "right": 0.07},
    "4:5": {"top": 0.07, "bottom": 0.14, "left": 0.07, "right": 0.08},
}


class SceneSpec(BaseModel):
    id: str
    shot_id: str | None = None
    asset_id: str | None = None
    duration: float = Field(gt=0.2, le=30)
    motion: Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "parallax"] = "zoom_in"
    focal: tuple[float, float] = (0.5, 0.5)
    role: str = "hook"
    super_text: str | None = None
    beat_id: str | None = None


class VoLine(BaseModel):
    id: str
    text: str
    start: float
    duration: float
    asset_id: str | None = None
    speed: float = 1.0
    beat_id: str | None = None


class Cue(BaseModel):
    id: str
    start: float
    end: float
    text: str


class MusicSpec(BaseModel):
    rights_id: str | None = None
    title: str = "Dawn Pad (library)"
    mood: str = "calm"
    bpm: int = 72
    key: str = "D"
    seed: int = 11
    gain_db: float = -19.0
    duck_db: float = -11.0
    fade_in: float = 0.5
    fade_out: float = 1.4


class EndCardSpec(BaseModel):
    duration: float = 2.4
    headline: str = "Wake up slowly."
    cta: str | None = None
    url: str | None = None
    legal: list[str] = Field(default_factory=list)
    bg: str = "#2B1A12"
    fg: str = "#F6EBDD"
    accent: str = "#F2A03D"


class BrandStyle(BaseModel):
    name: str = "Northwind Coffee Roasters"
    wordmark: str = "NORTHWIND"
    sub: str = "COFFEE ROASTERS"
    palette: list[str] = Field(default_factory=lambda: ["#2B1A12", "#F2A03D", "#F6EBDD", "#B5452B", "#5C7A5E"])
    logo_min_width_pct: float = 12.0
    logo_clear_space_ratio: float = 0.5


class Lineage(BaseModel):
    kind: Literal["master", "format", "cutdown", "localized"] = "master"
    parent_id: str | None = None
    cutdown_s: int | None = None
    notes: list[str] = Field(default_factory=list)


class RenderSpec(BaseModel):
    id: str
    campaign_id: str | None = None
    title: str = "Spot"
    lang: str = "en"
    aspect: Literal["16:9", "9:16", "1:1", "4:5"] = "16:9"
    fps: int = 25
    scenes: list[SceneSpec]
    vo: list[VoLine] = Field(default_factory=list)
    captions: list[Cue] = Field(default_factory=list)
    legal_supers: list[str] = Field(default_factory=list)
    music: MusicSpec | None = None
    endcard: EndCardSpec | None = None
    brand: BrandStyle = Field(default_factory=BrandStyle)
    disclosure_badge: str | None = None
    captions_burned: bool = True
    loudness_lufs: float = -16.0
    true_peak_db: float = -1.5
    seed: int = 7
    grade_strength: float = 0.0
    lineage: Lineage = Field(default_factory=Lineage)

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS[self.aspect]

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.scenes) + (self.endcard.duration if self.endcard else 0.0), 3)

    def scene_starts(self) -> list[float]:
        t, out = 0.0, []
        for s in self.scenes:
            out.append(round(t, 3))
            t += s.duration
        return out


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    out = []
    for i, c in enumerate(sorted(cues, key=lambda c: c.start), start=1):
        out.append(f"{i}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{c.text}\n")
    return "\n".join(out)


def make_captions(vo: list[VoLine], max_chars: int = 38) -> list[Cue]:
    """Split each VO line into short caption cues timed proportionally to character counts (monotonic, no overlap)."""
    cues: list[Cue] = []
    for line in sorted(vo, key=lambda v: v.start):
        words = line.text.split()
        chunks: list[str] = []
        cur = ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                chunks.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            chunks.append(cur)
        total = sum(len(c) for c in chunks) or 1
        t = line.start
        span = max(0.3, line.duration)
        for n, ch in enumerate(chunks):
            d = span * len(ch) / total
            cues.append(Cue(id=f"{line.id}-c{n}", start=round(t, 3), end=round(t + d - 0.04, 3), text=ch))
            t += d
    # enforce monotonic, non-overlapping cues
    cues.sort(key=lambda c: c.start)
    for a, b in itertools.pairwise(cues):
        if a.end > b.start:
            a.end = max(a.start + 0.2, b.start - 0.02)
    return cues
