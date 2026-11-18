"""Build the master RenderSpec from the approved building blocks (script beats, storyboard keyframes, voice timing, music)."""

from __future__ import annotations

import re
from typing import Any

from ..video.spec import BrandStyle, EndCardSpec, MusicSpec, RenderSpec, SceneSpec, VoLine, make_captions
from .disclosure import BADGE_TEXT, required_labels
from .rights import RightsEntry


class SpotBuildError(ValueError):
    pass


def _url_from(text: str, default: str) -> str:
    m = re.search(r"([a-z0-9-]+\.[a-z]{2,}(?:/[\w\-./]*)?)", text or "", re.IGNORECASE)
    return m.group(1) if m else default


def music_spec(entry: RightsEntry | None, fallback_title: str = "", mood: str = "warm") -> MusicSpec:
    """Licensed library track -> params. Unlicensed reference => procedural *temp* bed in the requested mood (flagged by the Guardian)."""
    if entry and entry.library_track:
        lt = entry.library_track
        return MusicSpec(rights_id=entry.id, title=entry.title, mood=lt["mood"], bpm=lt["bpm"], key=lt["key"], seed=lt["seed"])
    moods = {"calm": (72, "D", 11), "warm": (84, "A", 33), "uplifting": (96, "G", 22), "reflective": (66, "E", 44)}
    bpm, key, seed = moods.get(mood, moods["warm"])
    return MusicSpec(rights_id=None, title=fallback_title or "Temp bed (unlicensed reference)", mood=mood if mood in moods else "warm", bpm=bpm, key=key, seed=seed)


def build_master_spec(
    *,
    spec_id: str,
    campaign: dict[str, Any],
    script: dict[str, Any],
    storyboard: dict[str, Any],
    voice: dict[str, Any],
    kit: dict[str, Any],
    music: MusicSpec | None,
    brief_fields: dict[str, Any] | None = None,
    aspect: str = "16:9",
    lang: str = "en",
    loudness_lufs: float = -16.0,
    grade_strength: float = 0.0,
    title: str | None = None,
) -> RenderSpec:
    beats = script["beats"]
    if len(beats) < 2:
        raise SpotBuildError("script needs at least 2 beats (scene + brand beat)")
    shots = {s["beat_id"]: s for s in storyboard["shots"]}
    scenes: list[SceneSpec] = []
    for b in beats[:-1]:
        sh = shots.get(b["id"])
        if not sh or not sh.get("asset_id"):
            raise SpotBuildError(f"keyframe for beat {b['id']} is missing — generate the storyboard frames first")
        scenes.append(SceneSpec(id=f"sc-{b['id']}", shot_id=sh["id"], asset_id=sh["asset_id"], duration=max(0.8, round(b["t_end"] - b["t_start"], 2)), motion=sh.get("movement", "zoom_in"), focal=tuple(sh.get("focal", [0.5, 0.55])), role=b.get("role", "proof"), super_text=(sh.get("super_text") or b.get("super_text") or None), beat_id=b["id"]))  # type: ignore[arg-type]
    last = beats[-1]
    palette = [p["hex"] for p in kit.get("palette", [])] or BrandStyle().palette
    logo = kit.get("logo", {})
    brand = BrandStyle(name=kit.get("name", "Northwind Coffee Roasters"), wordmark=logo.get("wordmark", "NORTHWIND"), sub=logo.get("sub", "COFFEE ROASTERS"), palette=palette, logo_min_width_pct=logo.get("min_width_pct", 12.0), logo_clear_space_ratio=logo.get("clear_space_ratio", 0.5))
    legal = [x for x in script.get("legal", []) if x.strip()]
    tagline = script.get("tagline") or kit.get("tagline") or "Wake up slowly."
    url = _url_from((brief_fields or {}).get("cta", "") + " " + script.get("cta", ""), "northwind.example/dawn-roast")
    endcard = EndCardSpec(duration=max(2.0, min(3.2, round(last["t_end"] - last["t_start"], 2))), headline=tagline, cta=script.get("cta") or "Find Dawn Roast near you", url=url, legal=legal, bg=palette[0], fg=palette[2] if len(palette) > 2 else "#F6EBDD", accent=palette[1] if len(palette) > 1 else "#F2A03D")
    vo = [VoLine(id=ln["id"], text=ln["text"], start=ln["start"], duration=ln["duration"], asset_id=ln.get("asset_id"), speed=ln.get("speed", 1.0), beat_id=ln.get("beat_id")) for ln in voice["lines"]]
    labels = required_labels(campaign.get("markets", []), campaign.get("channels", []), True, lang)
    badge = BADGE_TEXT.get(lang, BADGE_TEXT["en"]) if (labels["burn_in_required"] or labels["burn_in_advised"]) else None
    return RenderSpec(
        id=spec_id, campaign_id=campaign["id"], title=title or script.get("title", "Spot"), lang=lang, aspect=aspect,  # type: ignore[arg-type]
        scenes=scenes, vo=vo, captions=make_captions(vo), legal_supers=legal, music=music, endcard=endcard, brand=brand,
        disclosure_badge=badge, loudness_lufs=loudness_lufs, grade_strength=grade_strength, seed=7,
    )
