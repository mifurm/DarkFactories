"""Guardian service: gathers context + Azure AI Content Safety observations, runs the deterministic rules, persists reports,
and drives the auto-revise loop. Also maps every artifact type to/from a GuardianSubject."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from ..domain.guardian import (
    Disclosure,
    GuardianContext,
    GuardianReport,
    GuardianSubject,
    MusicUse,
    TalentUse,
    TextItem,
    VisualItem,
    apply_fix,
    build_report,
    revise_once,
    run_rules,
)
from ..domain.rights import RightsEntry
from ..domain.script import trim_to_window
from ..util import now_iso
from ..video.overlays import endcard_layout
from ..video.spec import RenderSpec
from .studio import Studio

MAX_ITER = 3


class RewriteOut(BaseModel):
    text: str


# ------------------------------------------------------------------------------------------ subject builders


def _base(campaign: dict[str, Any], stype: str, artifact_id: str | None = None, markets: list[str] | None = None, lang: str = "en") -> GuardianSubject:
    return GuardianSubject(
        type=stype,  # type: ignore[arg-type]
        campaign_id=campaign["id"],
        brand_id=campaign.get("brand_id", "northwind"),
        artifact_id=artifact_id,
        markets=markets or campaign.get("markets") or ["US"],
        category=campaign.get("category", "beverage"),
        channels=campaign.get("channels", []),
        air_start=campaign.get("air_start"),
        air_end=campaign.get("air_end"),
        lang=lang,
    )


def subject_from_brief(campaign: dict[str, Any], art: dict[str, Any]) -> GuardianSubject:
    f = art.get("fields", {})
    s = _base(campaign, "brief", art["id"])
    for i, m in enumerate(f.get("mandatories", [])):
        s.texts.append(TextItem(id=f"mand-{i}", kind="brief", text=m))
    if f.get("key_message"):
        s.texts.append(TextItem(id="key_message", kind="headline", text=f["key_message"]))
    if f.get("cta"):
        s.texts.append(TextItem(id="cta", kind="cta", text=f["cta"]))
    if f.get("music_reference"):
        s.music.append(MusicUse(title=f["music_reference"]))
    s.talent = [TalentUse(name=t.split("(")[0].strip()) for t in f.get("talent", []) if t.strip()]
    return s


def subject_from_strategy(campaign: dict[str, Any], art: dict[str, Any]) -> GuardianSubject:
    s = _base(campaign, "concept", art["id"])
    if art.get("positioning"):
        s.texts.append(TextItem(id="positioning", kind="body", text=art["positioning"]))
    for t in art.get("territories", []):
        s.texts.append(TextItem(id=f"{t['id']}:idea", kind="body", text=t["big_idea"]))
        for i, h in enumerate(t.get("hook_examples", [])):
            s.texts.append(TextItem(id=f"{t['id']}:hook{i}", kind="headline", text=h))
    return s


def subject_from_script(campaign: dict[str, Any], art: dict[str, Any], lang: str = "en", markets: list[str] | None = None) -> GuardianSubject:
    s = _base(campaign, "script", art["id"], markets, lang)
    for b in art.get("beats", []):
        if b.get("vo"):
            s.texts.append(TextItem(id=f"{b['id']}:vo", kind="vo", text=b["vo"], beat_id=b["id"], lang=lang))
        if b.get("super_text"):
            s.texts.append(TextItem(id=f"{b['id']}:super", kind="super", text=b["super_text"], beat_id=b["id"], lang=lang))
    if art.get("cta"):
        s.texts.append(TextItem(id="cta", kind="cta", text=art["cta"], lang=lang))
    for i, ln in enumerate(art.get("legal", [])):
        s.texts.append(TextItem(id=f"legal-{i}", kind="legal", text=ln, lang=lang))
    m = art.get("music") or {}
    if m.get("reference_title") or m.get("title"):
        s.music.append(MusicUse(title=str(m.get("reference_title") or m.get("title")), rights_id=m.get("rights_id"), mood=m.get("mood")))
    s.talent = [TalentUse(name=t["name"], usage=t.get("usage", "voice"), ai_synthesis=bool(t.get("ai_synthesis"))) for t in art.get("talent", [])]
    return s


def subject_from_copy(campaign: dict[str, Any], art: dict[str, Any]) -> GuardianSubject:
    s = _base(campaign, "copy", art["id"])
    for it in art.get("items", []):
        s.texts.append(TextItem(id=it["id"], kind="headline" if it["kind"] == "headline" else "body", text=it["text"]))
    return s


async def subject_from_storyboard(st: Studio, campaign: dict[str, Any], art: dict[str, Any]) -> tuple[GuardianSubject, dict[str, bytes]]:
    s = _base(campaign, "storyboard", art["id"])
    images: dict[str, bytes] = {}
    for sh in art.get("shots", []):
        if sh.get("super_text"):
            s.texts.append(TextItem(id=f"{sh['id']}:super", kind="super", text=sh["super_text"], beat_id=sh.get("beat_id")))
        v = VisualItem(id=sh["id"], kind="frame")
        if sh.get("asset_id"):
            try:
                data = await st.asset_bytes(await st.asset(sh["asset_id"], campaign["id"]))
                images[sh["id"]] = data
                v.dominant = st.dominant(data)
            except Exception:
                pass
        s.visuals.append(v)
    s.has_video = False
    return s, images


def subject_from_spot(campaign: dict[str, Any], art: dict[str, Any], spec: RenderSpec | None = None, markets: list[str] | None = None) -> GuardianSubject:
    spec = spec or RenderSpec.model_validate(art["spec"])
    mk = markets or art.get("markets") or campaign.get("markets") or ["US"]
    s = _base(campaign, "spot" if spec.lineage.kind != "localized" else "localization", art["id"], mk, spec.lang)
    for ln in spec.vo:
        s.texts.append(TextItem(id=f"vo:{ln.id}", kind="vo", text=ln.text, lang=spec.lang, beat_id=ln.beat_id))
    for sc in spec.scenes:
        if sc.super_text:
            s.texts.append(TextItem(id=f"super:{sc.id}", kind="super", text=sc.super_text, lang=spec.lang))
    ec = spec.endcard
    if ec:
        if ec.headline:
            s.texts.append(TextItem(id="endcard:headline", kind="headline", text=ec.headline, lang=spec.lang))
        if ec.cta:
            s.texts.append(TextItem(id="endcard:cta", kind="cta", text=ec.cta, lang=spec.lang))
        for i, legal_line in enumerate(ec.legal):
            s.texts.append(TextItem(id=f"endcard:legal-{i}", kind="legal", text=legal_line, lang=spec.lang))
    for i, legal_line in enumerate(spec.legal_supers):
        s.texts.append(TextItem(id=f"legal:{i}", kind="legal", text=legal_line, lang=spec.lang))
    if spec.captions_burned:
        for c in spec.captions:
            s.texts.append(TextItem(id=f"cap:{c.id}", kind="caption", text=c.text, lang=spec.lang))
    if ec:
        w, h = spec.size
        lay = endcard_layout(spec, w, h)
        s.visuals.append(
            VisualItem(
                id="endcard", kind="endcard", colors=[ec.bg, ec.fg, ec.accent], logo=lay["logo"],
                elements=[{"name": e["name"], "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]} for e in lay["elements"]],
                contrast_pairs=[{"fg": ec.fg, "bg": ec.bg, "label": "end-card text"}, {"fg": ec.bg, "bg": ec.accent, "label": "CTA button"}],
            )
        )
    s.visuals.append(VisualItem(id="captions", kind="overlay", contrast_pairs=[{"fg": "#F7F0E6", "bg": "#150D09", "label": "captions"}]))
    if spec.music:
        s.music.append(MusicUse(title=spec.music.title, rights_id=spec.music.rights_id, mood=spec.music.mood))
    s.talent = [TalentUse(name=t["name"], usage=t.get("usage", "voice"), ai_synthesis=bool(t.get("ai_synthesis"))) for t in art.get("talent", [])]
    s.has_video = True
    s.captions_present = bool(spec.captions) and spec.captions_burned
    s.disclosure = Disclosure(ai_generated=True, label_present=bool(spec.disclosure_badge))
    return s


# ------------------------------------------------------------------------------------------ apply revised subject back


def apply_to_brief(art: dict[str, Any], s: GuardianSubject) -> None:
    f = art["fields"]
    f["mandatories"] = [t.text for t in s.texts if t.id.startswith("mand-")]
    for t in s.texts:
        if t.id == "key_message":
            f["key_message"] = t.text
        if t.id == "cta":
            f["cta"] = t.text
    f["music_reference"] = s.music[0].title if s.music else ""
    keep = {t.name for t in s.talent}
    f["talent"] = [t for t in f.get("talent", []) if t.split("(")[0].strip() in keep]


def apply_to_script(art: dict[str, Any], s: GuardianSubject, ctx: GuardianContext) -> None:
    by_id = {t.id: t.text for t in s.texts}
    for b in art.get("beats", []):
        if f"{b['id']}:vo" in by_id:
            b["vo"] = by_id[f"{b['id']}:vo"]
        elif b.get("vo") is not None:
            b["vo"] = ""
        if f"{b['id']}:super" in by_id:
            b["super_text"] = by_id[f"{b['id']}:super"]
        elif b.get("super_text"):
            b["super_text"] = None
        trim_to_window(b)
    if "cta" in by_id:
        art["cta"] = by_id["cta"]
    art["legal"] = [t.text for t in s.texts if t.kind == "legal"]
    if s.music:
        m = art.setdefault("music", {})
        if m.get("reference_title") != s.music[0].title or m.get("rights_id") != s.music[0].rights_id:
            entry = next((r for r in ctx.rights if r.id == s.music[0].rights_id), None)
            m.update(reference_title=s.music[0].title, title=s.music[0].title, rights_id=s.music[0].rights_id, mood=s.music[0].mood or m.get("mood"))
            if entry and entry.library_track:
                m["library_track"] = entry.library_track
    keep = {t.name for t in s.talent}
    art["talent"] = [t for t in art.get("talent", []) if t["name"] in keep]


def apply_to_spot(art: dict[str, Any], s: GuardianSubject, ctx: GuardianContext) -> None:
    spec = RenderSpec.model_validate(art["spec"])
    by_id = {t.id: t.text for t in s.texts}
    for ln in spec.vo:
        ln.text = by_id.get(f"vo:{ln.id}", ln.text)
    for sc in spec.scenes:
        if sc.super_text:
            sc.super_text = by_id.get(f"super:{sc.id}", sc.super_text)
    if spec.endcard:
        spec.endcard.headline = by_id.get("endcard:headline", spec.endcard.headline)
        spec.endcard.cta = by_id.get("endcard:cta", spec.endcard.cta)
        spec.endcard.legal = [t.text for t in s.texts if t.kind == "legal"]
        ec = next((v for v in s.visuals if v.id == "endcard"), None)
        if ec and len(ec.colors) == 3:
            spec.endcard.bg, spec.endcard.fg, spec.endcard.accent = ec.colors
    spec.legal_supers = [t.text for t in s.texts if t.kind == "legal"]
    if s.music and spec.music and (spec.music.rights_id != s.music[0].rights_id or spec.music.title != s.music[0].title):
        entry: RightsEntry | None = next((r for r in ctx.rights if r.id == s.music[0].rights_id), None)
        if entry and entry.library_track:
            lt = entry.library_track
            spec.music.rights_id, spec.music.title = entry.id, entry.title
            spec.music.mood, spec.music.bpm, spec.music.key, spec.music.seed = lt["mood"], lt["bpm"], lt["key"], lt["seed"]
    if s.disclosure.label_present and not spec.disclosure_badge:
        from ..domain.disclosure import BADGE_TEXT

        spec.disclosure_badge = BADGE_TEXT.get(spec.lang, BADGE_TEXT["en"])
    if s.captions_present:
        spec.captions_burned = True
    art["spec"] = spec.model_dump(mode="json")
    keep = {t.name for t in s.talent}
    art["talent"] = [t for t in art.get("talent", []) if t["name"] in keep]


def apply_to_copy(art: dict[str, Any], s: GuardianSubject) -> None:
    by_id = {t.id: t.text for t in s.texts}
    for it in art.get("items", []):
        it["text"] = by_id.get(it["id"], it["text"])


# ------------------------------------------------------------------------------------------ evaluation + auto-revise


async def load_waivers(st: Studio, campaign_id: str | None, artifact_id: str | None) -> list[str]:
    if not campaign_id:
        return []
    rows = await st.repo.query("reports", {"type": "waiver"}, pk=campaign_id)
    return [r["finding_id"] for r in rows if not artifact_id or r.get("artifact_id") in (artifact_id, None)]


async def evaluate(svc: Any, subject: GuardianSubject, *, image_bytes: dict[str, bytes] | None = None, untrusted_text: str | None = None, persist: bool = True, iterations: list[dict[str, Any]] | None = None, llm_assist: bool = False) -> tuple[GuardianReport, GuardianContext]:
    st = Studio(svc)
    ctx = await st.guardian_context(subject.brand_id, waivers=await load_waivers(st, subject.campaign_id, subject.artifact_id))
    ctx.safety = await st.gather_safety(subject, image_bytes, untrusted_text)
    findings = run_rules(subject, ctx)
    report = build_report(subject, ctx, findings, iterations)
    if llm_assist and subject.texts:
        report.llm_assist = await _tone_assist(svc, subject, ctx)
    if persist:
        doc = report.model_dump(mode="json")
        doc.update({"pk": subject.campaign_id or "adhoc", "campaign_id": subject.campaign_id, "type": "report", "subject": subject.model_dump(mode="json")})
        await svc.repo.upsert("reports", doc)
    return report, ctx


class ToneOut(BaseModel):
    on_brand_score: int
    strengths: list[str]
    concerns: list[str]


async def _tone_assist(svc: Any, subject: GuardianSubject, ctx: GuardianContext) -> dict[str, Any]:
    """LLM assistant (advisory only — never gates): rates tone-of-voice fit."""
    from ..features.common import CREW_PREAMBLE, untrusted

    text = "\n".join(t.text for t in subject.texts if t.kind in {"vo", "headline", "body", "super", "cta"})[:3000]
    try:
        out = await svc.llm.complete(
            task="guardian.tone",
            system=CREW_PREAMBLE + " You are a brand-voice reviewer. Score how on-brand the copy is (0-100) given the brand voice and list at most 3 strengths and 3 concerns. Advisory only.",
            user=f"Brand tone: warm, unhurried, honest, quietly confident. Forbidden: {', '.join(ctx.brand.forbidden_words)}.\n{untrusted(text, 3000)}",
            schema=ToneOut,
            context={"text": text},
            max_tokens=600,
        )
        return {**out.model_dump(), "advisory": True}
    except Exception as exc:
        return {"error": str(exc)[:120], "advisory": True}


class _Rewrite(BaseModel):
    text: str


async def llm_rewrite(svc: Any, text: str, reason: str) -> str:
    out = await svc.llm.complete(
        task="guardian.rewrite",
        system="You are the Brand Guardian's rewrite assistant. Rewrite the line so it keeps its marketing intent but resolves the stated compliance problem. Keep it under the original length, in the brand's warm, unhurried voice. Return JSON.",
        user=f"Problem to fix: {reason}\n<untrusted_input>\n{text}\n</untrusted_input>",
        schema=_Rewrite,
        context={"text": text, "reason": reason},
        max_tokens=400,
    )
    return out.text.strip()


async def auto_revise(svc: Any, subject: GuardianSubject, *, image_bytes: dict[str, bytes] | None = None, untrusted_text: str | None = None, max_iter: int = MAX_ITER, use_llm: bool = True) -> dict[str, Any]:
    """evaluate -> apply fixes -> re-evaluate, until no blocking findings remain (or nothing more can be fixed)."""
    trace: list[dict[str, Any]] = []
    ctx: GuardianContext | None = None
    report: GuardianReport | None = None
    for i in range(1, max_iter + 1):
        report, ctx = await evaluate(svc, subject, image_bytes=image_bytes, untrusted_text=untrusted_text, persist=False)
        live = [f for f in report.findings if not f.waived]
        entry: dict[str, Any] = {"iteration": i, "verdict": report.verdict, "score": report.score, "blocks": sum(1 for f in live if f.severity == "block"), "warns": sum(1 for f in live if f.severity == "warn"), "findings": [f.rule_id for f in live if f.severity != "info"], "fixes": []}
        if report.verdict == "pass":
            trace.append(entry)
            break
        applied = revise_once(subject, report.findings, ctx)
        if use_llm:
            for f in report.findings:
                if f.waived or not f.fix or f.fix.get("op") != "llm_rewrite":
                    continue
                item = next((t for t in subject.texts if t.id == f.fix["item_id"]), None)
                if item is None:
                    continue
                try:
                    new = await llm_rewrite(svc, item.text, f.fix.get("reason", f.message))
                except Exception:
                    continue
                if new and new != item.text:
                    item.text = new
                    applied.append({"finding": f.id, "rule": f.rule_id, "op": "llm_rewrite", "detail": f.fix.get("reason", "")})
        entry["fixes"] = applied
        trace.append(entry)
        if not applied:
            break
    final, ctx = await evaluate(svc, subject, image_bytes=image_bytes, untrusted_text=untrusted_text, persist=False, iterations=trace)
    return {"subject": subject, "report": final, "ctx": ctx, "iterations": trace, "converged": final.verdict != "block", "fixes_applied": sum(len(t["fixes"]) for t in trace)}


def summarize(report: GuardianReport) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "verdict": report.verdict,
        "score": report.score,
        "blocks": sum(1 for f in report.findings if f.severity == "block" and not f.waived),
        "warns": sum(1 for f in report.findings if f.severity == "warn" and not f.waived),
        "at": now_iso(),
    }


__all__ = [
    "apply_fix", "apply_to_brief", "apply_to_copy", "apply_to_script", "apply_to_spot", "auto_revise", "evaluate", "llm_rewrite", "re",
    "subject_from_brief", "subject_from_copy", "subject_from_script", "subject_from_spot", "subject_from_storyboard", "subject_from_strategy", "summarize",
]
