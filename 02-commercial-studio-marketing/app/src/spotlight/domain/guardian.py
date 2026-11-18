"""Brand Guardian (CS-12): deterministic multi-check rule engine + fix operators. LLMs only assist (never gate)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..util import new_id, now_iso, sha256_hex, stable_hash
from . import colors as col
from .claims import ClaimRule, find_hits, unsatisfied_disclaimers
from .disclosure import required_labels
from .rights import RightsEntry, check_use, find_entry
from .rights import best_replacement_track as _best_track
from .text import contains_phrase, replace_ci, sentences, word_count

TextKind = Literal["vo", "super", "caption", "headline", "cta", "legal", "body", "brief", "dialogue"]
Check = Literal["brand_voice", "visual_identity", "claims", "regulated", "rights", "content_safety", "disclosure", "accessibility"]
CHECKS: list[Check] = ["brand_voice", "visual_identity", "claims", "regulated", "rights", "content_safety", "disclosure", "accessibility"]
SUPPORT_KINDS = {"legal", "super", "caption"}


class TextItem(BaseModel):
    id: str
    kind: TextKind = "vo"
    text: str
    lang: str = "en"
    beat_id: str | None = None


class VisualItem(BaseModel):
    id: str
    kind: Literal["frame", "endcard", "logo", "overlay"] = "frame"
    colors: list[str] = Field(default_factory=list)
    dominant: list[dict[str, Any]] = Field(default_factory=list)
    logo: dict[str, Any] | None = None
    elements: list[dict[str, Any]] = Field(default_factory=list)
    contrast_pairs: list[dict[str, Any]] = Field(default_factory=list)


class MusicUse(BaseModel):
    title: str
    rights_id: str | None = None
    mood: str | None = None


class TalentUse(BaseModel):
    name: str
    usage: Literal["voice", "likeness"] = "voice"
    rights_id: str | None = None
    ai_synthesis: bool = False


class StockUse(BaseModel):
    title: str
    rights_id: str | None = None


class Disclosure(BaseModel):
    ai_generated: bool = True
    label_present: bool = False


class GuardianSubject(BaseModel):
    type: Literal["brief", "concept", "script", "storyboard", "spot", "localization", "copy", "adhoc"] = "adhoc"
    campaign_id: str | None = None
    brand_id: str = "northwind"
    artifact_id: str | None = None
    markets: list[str] = Field(default_factory=lambda: ["US"])
    category: str = "beverage"
    channels: list[str] = Field(default_factory=list)
    air_start: str | None = None
    air_end: str | None = None
    texts: list[TextItem] = Field(default_factory=list)
    visuals: list[VisualItem] = Field(default_factory=list)
    music: list[MusicUse] = Field(default_factory=list)
    talent: list[TalentUse] = Field(default_factory=list)
    stock: list[StockUse] = Field(default_factory=list)
    disclosure: Disclosure = Field(default_factory=Disclosure)
    captions_present: bool | None = None
    has_video: bool = False
    lang: str = "en"


class BrandRules(BaseModel):
    palette: list[str] = Field(default_factory=lambda: ["#2B1A12", "#F2A03D", "#F6EBDD", "#B5452B", "#5C7A5E"])
    forbidden_words: list[str] = Field(default_factory=list)
    replacements: dict[str, str] = Field(default_factory=dict)
    hype_terms: list[str] = Field(default_factory=lambda: ["best ever", "world's best", "#1", "number one", "ultimate", "unbeatable", "life-changing"])
    max_exclamations: int = 1
    max_sentence_words: int = 24
    logo_min_width_pct: float = 12.0
    logo_clear_space_ratio: float = 0.5
    spec_color_tolerance: float = 18.0
    image_palette_warn: float = 22.0
    image_palette_block: float = 45.0


class SafetyObs(BaseModel):
    text: dict[str, dict[str, Any]] = Field(default_factory=dict)  # item_id -> {max, categories, protected, attack}
    images: dict[str, dict[str, Any]] = Field(default_factory=dict)  # visual_id -> {max, categories}
    block_at: int = 4
    warn_at: int = 2


class GuardianContext(BaseModel):
    brand: BrandRules = Field(default_factory=BrandRules)
    claims: list[ClaimRule] = Field(default_factory=list)
    rights: list[RightsEntry] = Field(default_factory=list)
    safety: SafetyObs = Field(default_factory=SafetyObs)
    waivers: list[str] = Field(default_factory=list)  # finding ids waived by Legal/Admin
    today: str | None = None


class Finding(BaseModel):
    id: str
    check: Check
    rule_id: str
    severity: Literal["block", "warn", "info"]
    message: str
    evidence: str = ""
    item_id: str | None = None
    suggestion: str | None = None
    fix: dict[str, Any] | None = None
    waived: bool = False


class GuardianReport(BaseModel):
    id: str
    subject_type: str
    campaign_id: str | None = None
    artifact_id: str | None = None
    created_at: str
    verdict: Literal["pass", "warn", "block"]
    score: int
    checks: list[dict[str, Any]]
    findings: list[Finding]
    rules_version: str
    iterations: list[dict[str, Any]] = Field(default_factory=list)
    llm_assist: dict[str, Any] | None = None
    subject_hash: str = ""


def _fid(rule: str, item: str | None, evidence: str) -> str:
    return sha256_hex(f"{rule}|{item}|{evidence.lower()}")[:10]


def _f(check: Check, rule: str, sev: str, msg: str, *, item: str | None = None, ev: str = "", sug: str | None = None, fix: dict[str, Any] | None = None) -> Finding:
    return Finding(id=_fid(rule, item, ev or msg), check=check, rule_id=rule, severity=sev, message=msg, evidence=ev, item_id=item, suggestion=sug, fix=fix)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------ checks


def check_voice(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out: list[Finding] = []
    b = ctx.brand
    for it in s.texts:
        low = it.text
        for w in b.forbidden_words:
            m = re.search(r"(?<!\w)" + re.escape(w) + r"\w{0,3}(?!\w)", low, re.IGNORECASE)
            if m:
                rep = b.replacements.get(w.lower())
                out.append(
                    _f("brand_voice", "voice.forbidden_word", "block", f"Forbidden word “{m.group(0)}” in {it.kind} text", item=it.id, ev=m.group(0),
                       sug=f"Use “{rep}” instead" if rep else "Rephrase without the forbidden word",
                       fix={"op": "replace_text", "item_id": it.id, "find": m.group(0), "replace": rep} if rep else {"op": "llm_rewrite", "item_id": it.id, "reason": f"remove forbidden word {w}"})
                )
        if it.kind in {"vo", "headline", "body", "dialogue", "caption", "super", "cta"}:
            ex = it.text.count("!")
            if ex > b.max_exclamations:
                out.append(_f("brand_voice", "voice.exclamations", "warn", f"{ex} exclamation marks — brand voice is calm and unhurried (max {b.max_exclamations})", item=it.id, ev="!" * ex,
                              sug="Replace exclamation marks with full stops", fix={"op": "replace_text", "item_id": it.id, "find": "!", "replace": ".", "all": True}))
            if re.search(r"\b[A-Z]{3,}(?:\s+[A-Z]{3,}){2,}\b", it.text):
                out.append(_f("brand_voice", "voice.shouting", "warn", "ALL-CAPS shouting is off-brand", item=it.id, ev=it.text[:40]))
            for sent in sentences(it.text):
                if word_count(sent) > b.max_sentence_words and it.kind in {"vo", "body", "dialogue"}:
                    out.append(_f("brand_voice", "voice.long_sentence", "warn", f"Sentence has {word_count(sent)} words (>{b.max_sentence_words}) — hard to voice", item=it.id, ev=sent[:60]))
            for h in b.hype_terms:
                if re.search(r"(?<!\w)" + re.escape(h) + r"(?!\w)", it.text, re.IGNORECASE):
                    out.append(_f("brand_voice", "voice.hype", "warn", f"Hype term “{h}” — Northwind speaks with quiet confidence", item=it.id, ev=h))
    return out


def check_claims(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out: list[Finding] = []
    support = " ".join(t.text for t in s.texts if t.kind in SUPPORT_KINDS)
    all_hits = []
    for it in s.texts:
        if it.kind == "legal":
            continue
        hits = find_hits(it.text, ctx.claims, s.markets, s.category, it.id)
        all_hits += hits
        for h in hits:
            r = h.rule
            check: Check = "regulated" if (r.rule_pack and r.type == "prohibited") else "claims"
            if r.type == "prohibited":
                out.append(
                    _f(check, "claims.prohibited", r.severity, f"Prohibited claim “{h.span}” ({'regulated-category rule' if r.rule_pack else 'claims library'}: {r.text})", item=it.id, ev=h.span,
                       sug=(f"Use the approved wording: “{r.alternative}”" if r.alternative else "Remove or rephrase the claim"),
                       fix={"op": "replace_text", "item_id": it.id, "find": h.span, "replace": r.alternative} if r.alternative else {"op": "llm_rewrite", "item_id": it.id, "reason": f"remove prohibited claim: {r.text}"})
                )
            elif r.type == "needs_substantiation":
                substantiated = bool(r.substantiation_url and contains_phrase(support, f"source {r.substantiation_url}")) or bool(r.substantiation_url and r.substantiation_url in support)
                if not substantiated:
                    out.append(
                        _f("claims", "claims.needs_substantiation", r.severity, f"Claim “{h.span}” needs substantiation before use", item=it.id, ev=h.span,
                           sug=("Add the substantiation source as a legal super, or use: " + (r.alternative or "an approved claim")),
                           fix={"op": "append_text", "kind": "legal", "text": f"Source: {r.substantiation_url}", "lang": it.lang} if r.substantiation_url else ({"op": "replace_text", "item_id": it.id, "find": h.span, "replace": r.alternative} if r.alternative else None))
                    )
    support_after = support
    for h in unsatisfied_disclaimers(all_hits, support_after):
        out.append(
            _f("claims", "claims.missing_disclaimer", "block", f"Required disclaimer missing for claim “{h.span}”: “{h.rule.required_disclaimer}”", item=h.item_id, ev=h.rule.required_disclaimer or "",
               sug="Add the disclaimer as a legal super", fix={"op": "append_text", "kind": "legal", "text": h.rule.required_disclaimer, "lang": "en"})
        )
    return out


def _rect(d: dict[str, Any]) -> tuple[float, float, float, float]:
    return d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]


def check_visual(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out: list[Finding] = []
    b = ctx.brand
    for v in s.visuals:
        for c in dict.fromkeys(v.colors):
            near, d = col.nearest_palette(c, b.palette)
            if d > b.spec_color_tolerance:
                out.append(_f("visual_identity", "visual.off_palette", "block", f"Colour {c} is outside the brand palette (ΔE {d} from {near})", item=v.id, ev=c.upper(),
                              sug=f"Use brand colour {near}", fix={"op": "snap_colors", "visual_id": v.id, "mapping": {c: near}}))
        if v.dominant:
            d = col.palette_distance(v.dominant, b.palette)
            if d >= b.image_palette_block:
                out.append(_f("visual_identity", "visual.image_palette", "block", f"Image palette is far off-brand (mean ΔE {d} ≥ {b.image_palette_block})", item=v.id, ev=f"dE={d}", sug="Regenerate with palette conditioning / apply the brand grade"))
            elif d >= b.image_palette_warn:
                out.append(_f("visual_identity", "visual.image_palette", "warn", f"Image palette drifts from the brand (mean ΔE {d})", item=v.id, ev=f"dE={d}", sug="Apply the brand colour grade"))
        if v.logo:
            lg = v.logo
            pct = 100.0 * lg["w"] / max(1.0, lg["frame_w"])
            if pct + 1e-9 < b.logo_min_width_pct:
                out.append(_f("visual_identity", "visual.logo_size", "block", f"Logo is {pct:.1f}% of frame width (min {b.logo_min_width_pct}%)", item=v.id, ev=f"{pct:.1f}%",
                              sug="Enlarge the logo", fix={"op": "resize_logo", "visual_id": v.id, "min_width_pct": b.logo_min_width_pct}))
            pad = b.logo_clear_space_ratio * lg["h"]
            zone = (lg["x"] - pad, lg["y"] - pad, lg["x"] + lg["w"] + pad, lg["y"] + lg["h"] + pad)
            for el in v.elements:
                x0, y0, x1, y1 = _rect(el)
                if x0 < zone[2] and x1 > zone[0] and y0 < zone[3] and y1 > zone[1]:
                    out.append(_f("visual_identity", "visual.logo_clear_space", "block", f"“{el.get('name', 'element')}” intrudes into the logo clear-space ({b.logo_clear_space_ratio}× logo height)", item=v.id, ev=str(el.get("name", "element")), sug="Move the element away from the logo"))
    return out


def check_contrast(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out = []
    for v in s.visuals:
        for p in v.contrast_pairs:
            cr = col.contrast_ratio(p["fg"], p["bg"])
            if cr < 4.5:
                out.append(_f("accessibility", "a11y.contrast", "warn", f"{p.get('label', 'text')} contrast {cr}:1 is below WCAG AA 4.5:1", item=v.id, ev=f"{cr}:1", sug="Use a darker/lighter text colour or a scrim"))
    return out


def check_rights(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    from datetime import date

    out: list[Finding] = []
    now = date.fromisoformat(ctx.today) if ctx.today else None
    for m in s.music:
        e = find_entry(ctx.rights, "music", m.title, m.rights_id)
        if e is None:
            rep = _best_track(ctx.rights, s.markets, s.channels, s.air_start, s.air_end, m.mood, now=now)
            out.append(_f("rights", "rights.unlicensed", "block", f"Music cue “{m.title}” has no licence in the Rights Registry", item=m.title, ev=m.title,
                          sug=(f"Swap to licensed library track “{rep.title}”" if rep else "License the track or choose a library track"),
                          fix={"op": "swap_music", "from_title": m.title, "rights_id": rep.id, "title": rep.title, "mood": (rep.library_track or {}).get("mood")} if rep else None))
            continue
        verdicts = check_use(e, s.markets, s.channels, s.air_start, s.air_end, now)
        for v in verdicts:
            if v.severity == "info":
                continue
            rep = _best_track(ctx.rights, s.markets, s.channels, s.air_start, s.air_end, m.mood or (e.library_track or {}).get("mood"), exclude_ids={e.id}, now=now) if v.severity == "block" else None
            out.append(_f("rights", v.code, v.severity, v.message, item=m.title, ev=e.title,
                          sug=(f"Swap to licensed library track “{rep.title}”" if rep else None),
                          fix={"op": "swap_music", "from_title": m.title, "rights_id": rep.id, "title": rep.title, "mood": (rep.library_track or {}).get("mood")} if rep else None))
    for t in s.talent:
        e = find_entry(ctx.rights, "talent", t.name, t.rights_id)
        if e is None:
            out.append(_f("rights", "rights.unlicensed", "block", f"Talent “{t.name}” ({t.usage}) has no consent record in the Rights Registry", item=t.name, ev=t.name,
                          sug="Obtain consent or use a synthetic library voice", fix={"op": "swap_talent", "name": t.name}))
            continue
        for v in check_use(e, s.markets, s.channels, s.air_start, s.air_end, now, ai_synthesis=t.ai_synthesis, usage=t.usage):
            if v.severity == "info":
                continue
            out.append(_f("rights", v.code, v.severity, v.message, item=t.name, ev=e.title, sug="Obtain renewed consent, or replace with a synthetic library voice" if v.severity == "block" else None,
                          fix={"op": "swap_talent", "name": t.name} if v.severity == "block" else None))
    for st in s.stock:
        e = find_entry(ctx.rights, "stock", st.title, st.rights_id)
        if e is None:
            out.append(_f("rights", "rights.unlicensed", "block", f"Stock asset “{st.title}” has no licence in the Rights Registry", item=st.title, ev=st.title, sug="License the asset or remove it", fix={"op": "remove_stock", "title": st.title}))
            continue
        for v in check_use(e, s.markets, s.channels, s.air_start, s.air_end, now):
            if v.severity != "info":
                out.append(_f("rights", v.code, v.severity, v.message, item=st.title, ev=e.title, fix={"op": "remove_stock", "title": st.title} if v.severity == "block" else None))
    return out


def check_safety(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out: list[Finding] = []
    sf = ctx.safety
    for it in s.texts:
        obs = sf.text.get(it.id)
        if not obs:
            continue
        sev = int(obs.get("max", 0))
        cats = ", ".join(f"{k}={v}" for k, v in (obs.get("categories") or {}).items() if v)
        if sev >= sf.block_at:
            out.append(_f("content_safety", "safety.text", "block", f"Azure AI Content Safety flagged this text ({cats})", item=it.id, ev=cats, sug="Rewrite the line", fix={"op": "llm_rewrite", "item_id": it.id, "reason": f"content safety: {cats}"}))
        elif sev >= sf.warn_at:
            out.append(_f("content_safety", "safety.text", "warn", f"Content Safety low-severity signal ({cats})", item=it.id, ev=cats))
        if obs.get("protected"):
            out.append(_f("content_safety", "safety.protected_material", "block", "Protected material detected (possible lyrics / copyrighted text)", item=it.id, ev=it.text[:50], sug="Rewrite in original wording", fix={"op": "llm_rewrite", "item_id": it.id, "reason": "protected material"}))
        if obs.get("attack"):
            out.append(_f("content_safety", "safety.prompt_injection", "block", "Prompt Shields detected an injection attempt in user-provided content", item=it.id, ev=it.text[:50], sug="Remove the embedded instructions", fix={"op": "remove_text", "item_id": it.id}))
    for v in s.visuals:
        obs = sf.images.get(v.id)
        if obs and int(obs.get("max", 0)) >= sf.block_at:
            cats = ", ".join(f"{k}={x}" for k, x in (obs.get("categories") or {}).items() if x)
            out.append(_f("content_safety", "safety.image", "block", f"Azure AI Content Safety flagged this image ({cats})", item=v.id, ev=cats, sug="Regenerate the frame"))
    return out


def check_disclosure(s: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    out: list[Finding] = []
    if s.has_video and s.disclosure.ai_generated:
        labels = required_labels(s.markets, s.channels, True, s.lang)
        if labels["burn_in_required"] and not s.disclosure.label_present:
            out.append(_f("disclosure", "disclosure.missing_label", "block", f"AI-disclosure label “{labels['badge_text']}” is required for {', '.join(j['code'] for j in labels['jurisdictions'])} but not burned in", ev=labels["badge_text"],
                          sug="Enable the on-screen AI-generated badge", fix={"op": "set_disclosure"}))
        elif labels["burn_in_advised"] and not s.disclosure.label_present:
            out.append(_f("disclosure", "disclosure.advised_label", "warn", "An on-screen AI-generated label is advised for these markets", ev=labels["badge_text"], fix={"op": "set_disclosure"}))
    if s.has_video and s.captions_present is False:
        out.append(_f("accessibility", "a11y.captions", "warn", "No captions / SRT — required for accessibility and sound-off viewing", sug="Enable burned-in captions + SRT", fix={"op": "enable_captions"}))
    return out


def run_rules(subject: GuardianSubject, ctx: GuardianContext) -> list[Finding]:
    findings = [*check_voice(subject, ctx), *check_claims(subject, ctx), *check_visual(subject, ctx), *check_contrast(subject, ctx), *check_rights(subject, ctx), *check_safety(subject, ctx), *check_disclosure(subject, ctx)]
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        f.waived = f.id in set(ctx.waivers) and f.severity == "block"
        out.append(f)
    return out


def score_of(findings: list[Finding]) -> int:
    pen = 0
    for f in findings:
        if f.waived:
            pen += 3
        elif f.severity == "block":
            pen += 22
        elif f.severity == "warn":
            pen += 6
    return max(0, 100 - pen)


def verdict_of(findings: list[Finding]) -> Literal["pass", "warn", "block"]:
    live = [f for f in findings if not f.waived]
    if any(f.severity == "block" for f in live):
        return "block"
    return "warn" if any(f.severity == "warn" for f in live) else "pass"


def rules_version(ctx: GuardianContext) -> str:
    return stable_hash({"c": sorted(c.id for c in ctx.claims), "r": sorted(r.id for r in ctx.rights), "b": ctx.brand.model_dump()})[:12]


def build_report(subject: GuardianSubject, ctx: GuardianContext, findings: list[Finding] | None = None, iterations: list[dict[str, Any]] | None = None) -> GuardianReport:
    findings = findings if findings is not None else run_rules(subject, ctx)
    checks = []
    for c in CHECKS:
        fs = [f for f in findings if f.check == c and not f.waived]
        status = "block" if any(f.severity == "block" for f in fs) else ("warn" if any(f.severity == "warn" for f in fs) else "pass")
        checks.append({"check": c, "status": status, "findings": len(fs)})
    return GuardianReport(
        id=new_id("rpt"), subject_type=subject.type, campaign_id=subject.campaign_id, artifact_id=subject.artifact_id, created_at=now_iso(),
        verdict=verdict_of(findings), score=score_of(findings), checks=checks, findings=findings, rules_version=rules_version(ctx),
        iterations=iterations or [], subject_hash=stable_hash(subject.model_dump())[:16],
    )


# ------------------------------------------------------------------------------------------ fix operators


def apply_fix(subject: GuardianSubject, fix: dict[str, Any], ctx: GuardianContext) -> bool:
    """Apply one deterministic fix in place. Returns True when the subject changed."""
    op = fix.get("op")
    if op == "replace_text":
        for it in subject.texts:
            if it.id == fix["item_id"] and re.search(re.escape(fix["find"]), it.text, re.IGNORECASE):
                if fix.get("all"):
                    it.text = re.sub(re.escape(fix["find"]), fix["replace"], it.text, flags=re.IGNORECASE)
                else:
                    it.text = re.sub(r"\s{2,}", " ", replace_ci(it.text, fix["find"], fix["replace"])).strip()
                return True
        return False
    if op == "append_text":
        if any(t.kind == fix["kind"] and contains_phrase(t.text, fix["text"]) for t in subject.texts):
            return False
        subject.texts.append(TextItem(id=f"{fix['kind']}_{len(subject.texts) + 1}", kind=fix["kind"], text=fix["text"], lang=fix.get("lang", "en")))
        return True
    if op == "remove_text":
        n = len(subject.texts)
        subject.texts = [t for t in subject.texts if t.id != fix["item_id"]]
        return len(subject.texts) != n
    if op == "swap_music":
        for m in subject.music:
            if m.title == fix["from_title"]:
                m.title, m.rights_id, m.mood = fix["title"], fix["rights_id"], fix.get("mood") or m.mood
                return True
        return False
    if op == "swap_talent":
        n = len(subject.talent)
        subject.talent = [t for t in subject.talent if t.name != fix["name"]]
        return len(subject.talent) != n
    if op == "remove_stock":
        n = len(subject.stock)
        subject.stock = [t for t in subject.stock if t.title != fix["title"]]
        return len(subject.stock) != n
    if op == "snap_colors":
        for v in subject.visuals:
            if v.id == fix["visual_id"]:
                mp = {k.lower(): val for k, val in fix["mapping"].items()}
                v.colors = [mp.get(c.lower(), c) for c in v.colors]
                for p in v.contrast_pairs:
                    p["fg"] = mp.get(p["fg"].lower(), p["fg"])
                    p["bg"] = mp.get(p["bg"].lower(), p["bg"])
                return True
        return False
    if op == "resize_logo":
        for v in subject.visuals:
            if v.id == fix["visual_id"] and v.logo:
                lg = v.logo
                new_w = lg["frame_w"] * (fix["min_width_pct"] + 1) / 100.0
                ratio = new_w / lg["w"]
                cx = lg["x"] + lg["w"] / 2
                lg["w"], lg["h"] = new_w, lg["h"] * ratio
                lg["x"] = max(0.0, min(cx - new_w / 2, lg["frame_w"] - new_w))
                return True
        return False
    if op == "set_disclosure":
        changed = not subject.disclosure.label_present
        subject.disclosure.label_present = True
        return changed
    if op == "enable_captions":
        changed = subject.captions_present is not True
        subject.captions_present = True
        return changed
    return False


def revise_once(subject: GuardianSubject, findings: list[Finding], ctx: GuardianContext) -> list[dict[str, Any]]:
    """Apply every deterministic fix attached to a live (non-waived) blocking/warning finding."""
    applied: list[dict[str, Any]] = []
    for f in findings:
        if f.waived or f.severity == "info" or not f.fix or f.fix.get("op") == "llm_rewrite":
            continue
        if apply_fix(subject, f.fix, ctx):
            applied.append({"finding": f.id, "rule": f.rule_id, "op": f.fix["op"], "detail": f.suggestion or f.message})
    return applied
