"""CS-12 Brand Guardian — automated multi-check on every asset/script/stage with scored report, fix suggestions,
auto-revise loop and waivers. Blocks approval on failures (see CS-13)."""

from __future__ import annotations

import functools
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.guardian_service import (
    apply_to_brief,
    apply_to_copy,
    apply_to_script,
    apply_to_spot,
    auto_revise,
    evaluate,
    subject_from_brief,
    subject_from_copy,
    subject_from_script,
    subject_from_spot,
    subject_from_storyboard,
    subject_from_strategy,
    summarize,
)
from ...deps import mutate_limit, spend_limit, svc
from ...domain.claims import ClaimRule, find_hits
from ...domain.guardian import (
    Disclosure,
    GuardianSubject,
    MusicUse,
    StockUse,
    TalentUse,
    TextItem,
    VisualItem,
    localize_report,
)
from ...domain.text import fold
from ...errors import NotFound, ValidationFailed
from ...i18n import current_locale
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id, now_iso
from ..common import studio

router = APIRouter(tags=["CS-12 Brand Guardian"])


@stub_task("guardian.tone")
def _stub_tone(ctx: dict[str, Any]) -> dict[str, Any]:
    text = ctx.get("text", "")
    bad = sum(text.count(c) for c in "!") + sum(1 for w in text.split() if w.isupper() and len(w) > 3)
    if ctx.get("lang") == "pl":
        return {"on_brand_score": max(40, 92 - 8 * bad), "strengths": ["Spokojny, obrazowy język", "Krótkie zdania"], "concerns": ["Sprawdź wykrzykniki i pisanie wielkimi literami"] if bad else []}
    return {"on_brand_score": max(40, 92 - 8 * bad), "strengths": ["Calm, sensory language", "Short sentences"], "concerns": ["Check exclamation marks and ALL-CAPS"] if bad else []}


@functools.lru_cache(maxsize=1)
def _pl_rule_set() -> tuple[list[ClaimRule], list[Any]]:
    """The Polish claim rules + forbidden-word regexes the offline rewrite stub uses to drop the offending sentences."""
    from ...domain.pl_morph import DEFAULT_PL_FORBIDDEN, term_for, term_regex
    from ...seed.pl_claims import claims_pl

    rules = [ClaimRule(**{k: v for k, v in c.items() if k in ClaimRule.model_fields}) for c in claims_pl()]
    return rules, [term_regex(term_for(w)) for w in DEFAULT_PL_FORBIDDEN]


@stub_task("guardian.rewrite")
def _stub_rewrite(ctx: dict[str, Any]) -> dict[str, Any]:
    text = ctx.get("text", "")
    if ctx.get("lang") == "pl":
        rules, forbidden = _pl_rule_set()
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("!", ".")) if s.strip()]
        kept = [s for s in sents if not find_hits(s, rules, ["PL"], "beverage", lang="pl") and not any(rx.search(fold(s)) for rx in forbidden)]
        return {"text": " ".join(kept) if kept else "Spokojniejszy początek twojego poranka."}
    sents = [s.strip() for s in text.replace("!", ".").split(".") if s.strip()]
    bad_words = ("stab", "kill", "murder", "shoot", "bomb", "cure", "treat", "heal", "prevent", "lyrics", "ignore previous")
    kept = [s for s in sents if not any(w in s.lower() for w in bad_words)]
    return {"text": (". ".join(kept) + ".") if kept else "A calmer start to your morning."}


def seeded_violation_subject(lang: str = "en") -> GuardianSubject:
    """The seven seeded violations from the demo script, plus two borderline-but-fine lines (English, or the Polish mirror for market PL)."""
    if lang == "pl":
        return GuardianSubject(
            type="adhoc", markets=["PL"], channels=["youtube", "meta"], category="beverage", has_video=True, captions_present=False, air_start="2026-12-01", air_end="2027-01-31", lang="pl",
            texts=[
                TextItem(id="v1", kind="vo", text="Dawn Roast leczy poranny niepokój.", lang="pl"),
                TextItem(id="v2", kind="vo", text="Tania porcja energii na poranną zmianę.", lang="pl"),
                TextItem(id="v3", kind="vo", text="Obudź się powoli.", lang="pl"),
                TextItem(id="v4", kind="headline", text="Zdrowy początek twojego dnia.", lang="pl"),
            ],
            music=[MusicUse(title="Sunrise Anthem", mood="warm")],
            talent=[TalentUse(name="Jonas Weber")],
            stock=[StockUse(title="Stock photo: latte art hero")],
            visuals=[VisualItem(id="endcard", kind="endcard", colors=["#FF2BD6", "#F6EBDD"])],
            disclosure=Disclosure(ai_generated=True, label_present=False),
        )
    return GuardianSubject(
        type="adhoc", markets=["DE"], channels=["youtube", "meta"], category="beverage", has_video=True, captions_present=False, air_start="2026-12-01", air_end="2027-01-31",
        texts=[
            TextItem(id="v1", kind="vo", text="Dawn Roast cures morning anxiety."),
            TextItem(id="v2", kind="vo", text="A cheap boost of energy for the early shift."),
            TextItem(id="v3", kind="vo", text="Wake up slowly."),
            TextItem(id="v4", kind="headline", text="A healthy start to your day."),
        ],
        music=[MusicUse(title="Sunrise Anthem", mood="warm")],
        talent=[TalentUse(name="Jonas Weber")],
        stock=[StockUse(title="Stock photo: latte art hero")],
        visuals=[VisualItem(id="endcard", kind="endcard", colors=["#FF2BD6", "#F6EBDD"])],
        disclosure=Disclosure(ai_generated=True, label_present=False),
    )


@router.get("/api/guardian/seeded")
async def seeded(language: str | None = None) -> dict[str, Any]:
    """The seeded-violations playground subject — in the content language (``?language=``, default: the request locale)."""
    lang = language if language in ("en", "pl") else current_locale()
    s = seeded_violation_subject(lang)
    return {"subject": s.model_dump(), "language": s.lang, "expected_rules": ["claims.prohibited", "voice.forbidden_word", "claims.missing_disclaimer", "rights.unlicensed", "rights.expired", "rights.territory", "visual.off_palette", "disclosure.missing_label"]}


class CheckIn(BaseModel):
    subject: GuardianSubject


@router.post("/api/guardian/check", dependencies=[Depends(spend_limit)])
async def check(request: Request, body: CheckIn) -> dict[str, Any]:
    """Ad-hoc check (the Guardian playground): deterministic rules + Azure AI Content Safety on every text."""
    if len(body.subject.texts) > 60:
        raise ValidationFailed("too many text items (max 60)", code="too_many_items", params={"max": 60})
    body.subject.campaign_id = None
    report, _ = await evaluate(svc(request), body.subject, persist=False, llm_assist=False)
    return report.model_dump()


class ReviseIn(BaseModel):
    subject: GuardianSubject
    max_iter: int = Field(default=3, ge=1, le=4)


@router.post("/api/guardian/revise", dependencies=[Depends(spend_limit)])
async def revise(request: Request, body: ReviseIn) -> dict[str, Any]:
    body.subject.campaign_id = None
    res = await auto_revise(svc(request), body.subject, max_iter=body.max_iter)
    return {"subject": res["subject"].model_dump(), "report": res["report"].model_dump(), "iterations": res["iterations"], "converged": res["converged"], "fixes_applied": res["fixes_applied"]}


class RunIn(BaseModel):
    artifact_id: str
    auto_revise: bool = False
    llm_assist: bool = False


async def _subject_for(st: Any, camp: dict[str, Any], art: dict[str, Any]) -> tuple[GuardianSubject, dict[str, bytes], Any]:
    kind = art["kind"]
    if kind == "brief":
        return subject_from_brief(camp, art), {}, apply_to_brief
    if kind == "strategy":
        return subject_from_strategy(camp, art), {}, None
    if kind == "script":
        return subject_from_script(camp, art), {}, apply_to_script
    if kind == "copy":
        return subject_from_copy(camp, art), {}, apply_to_copy
    if kind == "storyboard":
        subject, images = await subject_from_storyboard(st, camp, art)
        return subject, images, None
    if kind == "spot":
        return subject_from_spot(camp, art, markets=art.get("markets")), {}, apply_to_spot
    raise ValidationFailed(f"the Guardian does not review artifacts of kind {kind!r}", code="unsupported_kind", params={"kind": kind})


@router.post("/api/campaigns/{campaign_id}/guardian/run", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def run(request: Request, campaign_id: str, body: RunIn, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    s = svc(request)
    st = studio(request)
    camp = await st.campaign(campaign_id)
    art = await st.artifact(campaign_id, body.artifact_id)
    subject, images, apply_back = await _subject_for(st, camp, art)
    raw = art.get("raw_text") if art["kind"] == "brief" else None
    if not body.auto_revise:
        report, _ = await evaluate(s, subject, image_bytes=images, untrusted_text=raw, llm_assist=body.llm_assist)
        art["guardian"] = summarize(report)
        await st.save_artifact(art)
        await st.audit(campaign_id, actor, "guardian.run", {"artifact_id": art["id"]}, {"verdict": report.verdict, "score": report.score})
        return {"report": report.model_dump(), "revised": False}
    res = await auto_revise(s, subject, image_bytes=images, untrusted_text=raw)
    report, ctx = res["report"], res["ctx"]
    changed = res["fixes_applied"] > 0
    if changed and apply_back is not None:
        if art["kind"] in {"script", "spot"}:
            apply_back(art, res["subject"], ctx)
        else:
            apply_back(art, res["subject"])
        art["status"] = "draft"
        if art["kind"] == "spot":
            art["needs_rerender"] = True
        if art["kind"] == "script":
            art["revised_by_guardian"] = True
    doc = report.model_dump(mode="json")
    doc.update({"pk": campaign_id, "campaign_id": campaign_id, "type": "report", "subject": res["subject"].model_dump(mode="json")})
    await s.repo.upsert("reports", doc)
    art["guardian"] = summarize(report)
    await st.save_artifact(art)
    await st.audit(campaign_id, actor, "guardian.auto_revised", {"artifact_id": art["id"]}, {"iterations": len(res["iterations"]), "fixes": res["fixes_applied"], "verdict": report.verdict, "converged": res["converged"]})
    return {"report": report.model_dump(), "revised": changed, "iterations": res["iterations"], "converged": res["converged"], "artifact": art, "applied_to_artifact": apply_back is not None}


@router.get("/api/campaigns/{campaign_id}/guardian/reports")
async def reports(request: Request, campaign_id: str, artifact_id: str | None = None, limit: int = 30) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    where: dict[str, Any] = {"type": "report"}
    if artifact_id:
        where["artifact_id"] = artifact_id
    rows = await st.repo.query("reports", where, pk=campaign_id, order_by="created_at", desc=True, limit=min(limit, 100))
    waivers = await st.repo.query("reports", {"type": "waiver"}, pk=campaign_id, order_by="created_at", desc=True)
    return {"reports": [localize_report({k: v for k, v in r.items() if k != "subject"}) for r in rows], "waivers": waivers}


@router.get("/api/guardian/reports/{report_id}")
async def get_report(request: Request, report_id: str) -> dict[str, Any]:
    r = await studio(request).repo.get("reports", report_id)
    if not r or r.get("type") != "report":
        raise NotFound("report not found", code="report_not_found")
    return localize_report(r)


class WaiveIn(BaseModel):
    artifact_id: str
    finding_id: str
    justification: str = Field(min_length=10, max_length=500)


@router.post("/api/campaigns/{campaign_id}/guardian/waive", dependencies=[Depends(mutate_limit)])
async def waive(request: Request, campaign_id: str, body: WaiveIn, actor: Actor = Depends(require("waive"))) -> dict[str, Any]:
    """Legal/Admin can waive a single blocking finding with a recorded justification (audit-logged)."""
    st = studio(request)
    await st.campaign(campaign_id)
    art = await st.artifact(campaign_id, body.artifact_id)
    doc = {"id": new_id("wv"), "pk": campaign_id, "campaign_id": campaign_id, "type": "waiver", "artifact_id": art["id"], "finding_id": body.finding_id, "justification": body.justification, "by": actor.to_dict(), "created_at": now_iso()}
    await st.repo.upsert("reports", doc)
    await st.audit(campaign_id, actor, "guardian.waived", {"artifact_id": art["id"], "finding_id": body.finding_id}, {"justification": body.justification})
    camp = await st.campaign(campaign_id)
    subject, images, _ = await _subject_for(st, camp, art)
    report, _ = await evaluate(svc(request), subject, image_bytes=images)
    art["guardian"] = summarize(report)
    await st.save_artifact(art)
    return {"waiver": doc, "report": report.model_dump()}


__all__ = ["MusicUse"]
FEATURE = Feature(id="CS-12", summary="Multi-check Guardian: brand voice, visual identity, claims, regulated rules, rights, Azure AI Content Safety (text/image/protected material/Prompt Shields), scored report, fixes, auto-revise.", router=router)
