"""Format factory (CS-11): safe-area-aware reframing to 16:9 / 9:16 / 1:1 / 4:5 and cutdowns (6/15/30 s) from a master spec."""

from __future__ import annotations

from typing import Any

from ..util import new_id
from ..video.spec import ASPECTS, Lineage, RenderSpec, SceneSpec, VoLine, make_captions

PRIORITY = {"hook": 0, "product": 1, "proof": 2, "cta": 3, "brand": 4}
MIN_SCENE = 1.6
LEAD = 0.25


def reframe(spec: RenderSpec, aspect: str) -> RenderSpec:
    """Same timeline on a different canvas. Each scene keeps its focal point, so the crop window follows the subject
    (safe-area-aware); captions/supers/logo/end card are laid out per aspect by the compositor."""
    if aspect not in ASPECTS:
        raise ValueError(f"unsupported aspect {aspect}")
    new = spec.model_copy(deep=True)
    new.id = new_id("spec")
    new.aspect = aspect  # type: ignore[assignment]
    for sc in new.scenes:  # generated clips are native to one aspect: a reframed version gets its own (generated from the crop of the same keyframe, cached per aspect)
        sc.clip_asset_id, sc.clip = None, None
    new.lineage = Lineage(kind="format", parent_id=spec.id, notes=[f"reframed {spec.aspect} → {aspect} with per-scene focal points"], note_keys=[{"key": "format.note.reframed", "params": {"src": spec.aspect, "dst": aspect}}])
    return new


def plan_cutdown(spec: RenderSpec, target_s: int) -> tuple[RenderSpec, dict[str, Any]]:
    """Shorter version: keep the hook + strongest scenes + the end card, re-time voice-over lines to the new scene windows."""
    total = spec.duration
    if target_s >= total - 0.3:
        raise ValueError(f"cutdown target {target_s}s must be shorter than the master ({total:.1f}s)")
    ec = spec.endcard
    ec_dur = min(ec.duration, max(2.0, 0.34 * target_s)) if ec else 0.0
    room = target_s - ec_dur
    ranked = sorted(range(len(spec.scenes)), key=lambda i: (PRIORITY.get(spec.scenes[i].role, 5), i))
    chosen: list[int] = []
    used = 0.0
    for i in ranked:
        if used + MIN_SCENE <= room + 1e-6:
            chosen.append(i)
            used += MIN_SCENE
    if not chosen:
        chosen = [ranked[0]]
    chosen.sort()
    weights = [spec.scenes[i].duration for i in chosen]
    scale = room / sum(weights)
    scenes: list[SceneSpec] = []
    starts: dict[str, float] = {}
    t = 0.0
    for i, w in zip(chosen, weights, strict=True):
        s = spec.scenes[i].model_copy(deep=True)
        s.duration = round(max(MIN_SCENE, w * scale), 2)
        starts[s.beat_id or s.id] = t
        t += s.duration
        scenes.append(s)
    # voice-over: lines whose beat survived (plus the end-card/tagline line), re-timed into the new windows
    kept: list[VoLine] = []
    dropped: list[str] = []
    old_scene_by_beat = {s.beat_id: s for s in spec.scenes}
    last_beat = spec.vo[-1].beat_id if spec.vo else None
    for ln in spec.vo:
        if ln.beat_id in starts:
            window = next(s.duration for s in scenes if (s.beat_id or s.id) == ln.beat_id)
            if ln.duration + LEAD <= window + 0.2:
                kept.append(ln.model_copy(update={"start": round(starts[ln.beat_id] + LEAD, 3)}))
            else:
                dropped.append(ln.id)
        elif ln.beat_id == last_beat and ec:
            if ln.duration + LEAD <= ec_dur + 0.2:
                kept.append(ln.model_copy(update={"start": round(t + LEAD, 3)}))
            else:
                dropped.append(ln.id)
        elif ln.beat_id not in old_scene_by_beat:
            pass
        else:
            dropped.append(ln.id)
    new = spec.model_copy(deep=True)
    new.id = new_id("spec")
    new.scenes = scenes
    new.vo = kept
    new.captions = make_captions(kept, lang=spec.lang)
    if new.endcard:
        new.endcard.duration = round(ec_dur, 2)
    notes = [f"{len(chosen)}/{len(spec.scenes)} scenes kept by priority (hook → product → proof)", *([f"dropped VO lines that no longer fit: {dropped}"] if dropped else [])]
    note_keys = [{"key": "format.note.cutdown_scenes", "params": {"kept": len(chosen), "total": len(spec.scenes)}}, *([{"key": "format.note.cutdown_dropped", "params": {"lines": list(dropped)}}] if dropped else [])]
    new.lineage = Lineage(kind="cutdown", parent_id=spec.id, cutdown_s=target_s, notes=notes, note_keys=note_keys)
    return new, {"scenes_kept": [spec.scenes[i].id for i in chosen], "vo_dropped": dropped, "duration": new.duration}
