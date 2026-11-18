"""CS-04 Brief intake & Briefing agent — wizard + free-text/doc paste, completeness check, clarifying questions, normalized brief.

Also owns the campaign collection API (create / list / detail) that every other feature hangs off.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.gates import stage_overview
from ...core.jobs import render_job
from ...core.studio import campaign_lang
from ...deps import mutate_limit, spend_limit, svc
from ...domain import brief as bf
from ...domain.ingest import extract_text
from ...domain.text import fold
from ...errors import NotFound, PayloadTooLarge, ValidationFailed
from ...i18n import SUPPORTED, current_locale, t
from ...i18n.directive import lang_directive
from ...registry import Feature
from ...roles import Actor, require
from ...seed.data import DAWN_ROAST_BRIEF, DAWN_ROAST_BRIEF_PL
from ...util import new_id, now_iso, slugify
from ..common import CREW_PREAMBLE, studio, untrusted

router = APIRouter(prefix="/api/campaigns", tags=["CS-04 Brief & Campaigns"])
LANG_PATTERN = "^(" + "|".join(SUPPORTED) + ")$"


class BriefExtract(BaseModel):
    objective: str
    audience: str
    channels: list[str]
    markets: list[str]
    product: str
    kpis: list[str]
    budget: str
    timeline: str
    mandatories: list[str]
    tone: list[str]
    key_message: str
    cta: str
    duration_targets: list[int]
    music_reference: str
    talent: list[str]


class Question(BaseModel):
    field: str
    question: str
    why: str


class QuestionsOut(BaseModel):
    questions: list[Question]


@stub_task("brief.extract")
def _stub_extract(ctx: dict[str, Any]) -> dict[str, Any]:
    f = bf.normalize_fields(bf.parse_labeled(ctx.get("text", "")), ctx.get("lang", "en"))
    f["mandatories"] = _mandatory_items(ctx.get("text", ""), f, ctx.get("lang", "en"))
    f["music_reference"] = _music_ref(ctx.get("text", "")) or f["music_reference"]
    return f


@stub_task("brief.questions")
def _stub_questions(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"questions": bf.template_questions(ctx.get("missing", []), ctx.get("product", ""), ctx.get("lang", "en"))}


def _music_ref(text: str) -> str:
    import re

    m = re.search(r"(?:music|muzyka):?[^\n]*?[\"“„«]([^\"”“»]{3,60})[\"”»]", text, re.IGNORECASE)
    return m.group(1) if m else ""


def _mandatory_items(text: str, f: dict[str, Any], lang: str = "en") -> list[str]:
    import re

    m = re.search(r"(?:mandatories?|obowi[aą]zkow\w*):\s*(.+)", text, re.IGNORECASE)
    raw = m.group(1) if m else ""
    items = bf.mandatory_lines(raw) if raw else list(f.get("mandatories", []))
    out = []
    for it in items:
        q = bf.quoted(it)
        low = fold(it.lower())
        is_tagline = any(k in low for k in ("tagline", "end on", "hasl", "zakoncz", "slogan"))
        if q and is_tagline:
            out.append(f"Zakończ hasłem „{q[0]}”" if lang == "pl" else f"End on the tagline “{q[0]}”")
        elif q:
            out.append(f"Użyj dokładnie zdania „{q[0]}”" if lang == "pl" else f"Include the line “{q[0]}”")
        else:
            out.append(it)
    return out


def _normalize_for_storage(fields: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    return bf.normalize_fields(fields, lang)


class CampaignIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    brand_id: str = "northwind"
    markets: list[str] = Field(default_factory=lambda: ["US"])
    channels: list[str] = Field(default_factory=lambda: ["youtube", "meta"])
    product_id: str | None = "dawn-roast"
    category: str = "beverage"
    raw_text: str = Field(default="", max_length=20000)
    air_start: str | None = None
    air_end: str | None = None
    language: str | None = Field(default=None, pattern=LANG_PATTERN)  # content language of the campaign; default: the request locale


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    markets: list[str] | None = None
    channels: list[str] | None = None
    category: str | None = None
    air_start: str | None = None
    air_end: str | None = None
    product_id: str | None = None
    language: str | None = Field(default=None, pattern=LANG_PATTERN)


async def _summary(request: Request, c: dict[str, Any], arts: list[dict[str, Any]]) -> dict[str, Any]:
    s = svc(request)
    mine = [a for a in arts if a.get("campaign_id") == c["id"]]
    kinds: dict[str, int] = {}
    for a in mine:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    spots = [a for a in mine if a["kind"] == "spot"]
    return {
        "id": c["id"],
        "name": c["name"],
        "language": c.get("language") or "en",
        "status": c.get("status"),
        "stage": c.get("stage"),
        "markets": c.get("markets", []),
        "channels": c.get("channels", []),
        "synthetic": c.get("synthetic", False),
        "history": c.get("history", False),
        "created_at": c.get("created_at"),
        "artifacts": kinds,
        "spots": len(spots),
        "ai_spend_usd": await s.meter.campaign_total(c["id"]),
        "budget_cap_usd": c.get("budget_cap_usd"),
    }


@router.get("")
async def list_campaigns(request: Request) -> list[dict[str, Any]]:
    st = studio(request)
    camps = await st.repo.query("campaigns", order_by="created_at", desc=True, limit=100)
    arts = await st.repo.query("artifacts", limit=2000, fields=("id", "kind", "campaign_id"))
    return list(await asyncio.gather(*[_summary(request, c, arts) for c in camps]))


@router.get("/samples")
async def samples() -> list[dict[str, Any]]:
    """Sample briefs (each with its ``language``); the one in the request locale comes first."""
    out = [
        {"id": "dawn-roast", "language": "en", "name": "Dawn Roast — launch brief (sample, includes a risky mandatory line + unlicensed music reference)", "brief_text": DAWN_ROAST_BRIEF},
        {"id": "dawn-roast-pl", "language": "pl", "name": "Dawn Roast — brief premiery w Polsce (przykład z ryzykownym zdaniem obowiązkowym i utworem bez licencji)", "brief_text": DAWN_ROAST_BRIEF_PL},
    ]
    return sorted(out, key=lambda s: s["language"] != current_locale())


@router.post("", dependencies=[Depends(mutate_limit)])
async def create_campaign(request: Request, body: CampaignIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    await st.brand(body.brand_id)
    cid = f"{slugify(body.name, 36)}-{new_id('c')[2:8]}"
    language = body.language or current_locale()
    markets = body.markets if ("markets" in body.model_fields_set or language == "en") else ["PL"]  # a Polish campaign targets Poland unless told otherwise
    camp = {
        "id": cid, "pk": cid, "campaign_id": cid, "name": body.name, "brand_id": body.brand_id, "status": "briefing", "stage": "brief", "language": language,
        "markets": [m.upper() for m in markets], "channels": [c.lower() for c in body.channels], "product_id": body.product_id, "category": body.category,
        "air_start": body.air_start, "air_end": body.air_end, "budget_cap_usd": svc(request).settings.campaign_ai_budget_usd, "premium_approved": False,
        "synthetic": True, "created_by": actor.to_dict(), "created_at": now_iso(),
    }
    await st.save_campaign(camp)
    await st.repo.upsert("briefs", {"id": cid, "pk": cid, "campaign_id": cid, "lang": language, "raw_text": body.raw_text, "fields": {}, "answers": [], "status": "draft", "completeness": None, "questions": [], "version": 0})
    await st.audit(cid, actor, "campaign.created", {"campaign_id": cid}, {"name": body.name, "language": language})
    return camp


@router.get("/{campaign_id}")
async def get_campaign(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    c = await st.campaign(campaign_id)
    brief = await st.repo.get("briefs", campaign_id, pk=campaign_id)
    arts = await st.repo.query("artifacts", pk=campaign_id, order_by="created_at", desc=True, fields=("id", "kind", "campaign_id", "version", "status", "created_at", "guardian", "title", "variant", "lineage_kind"))
    jobs = [render_job(j) for j in await svc(request).jobs.list(campaign_id, 12)]
    return {
        "campaign": c,
        "brief": brief,
        "pipeline": await stage_overview(st, campaign_id),
        "summary": await _summary(request, c, arts),
        "recent_jobs": jobs,
        "artifacts": [{k: a.get(k) for k in ("id", "kind", "version", "status", "created_at", "guardian", "title", "variant", "lineage_kind")} for a in arts][:80],
    }


@router.put("/{campaign_id}", dependencies=[Depends(mutate_limit)])
async def update_campaign(request: Request, campaign_id: str, body: CampaignPatch, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    c = await st.campaign(campaign_id)
    for k, v in body.model_dump(exclude_none=True).items():
        c[k] = [x.upper() for x in v] if k == "markets" else ([x.lower() for x in v] if k == "channels" else v)
    await st.save_campaign(c)
    await st.audit(campaign_id, actor, "campaign.updated", {"campaign_id": campaign_id}, body.model_dump(exclude_none=True))
    return c


@router.delete("/{campaign_id}", dependencies=[Depends(mutate_limit)])
async def delete_campaign(request: Request, campaign_id: str, actor: Actor = Depends(require("admin"))) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    for coll in ("artifacts", "assets", "reports", "approvals", "briefs", "experiments", "performance", "provenance", "jobs"):
        for r in await st.repo.query(coll, pk=campaign_id):
            if coll == "assets" and r.get("blob"):
                await svc(request).blobs.delete(r["blob"])
            await st.repo.delete(coll, r["id"], pk=campaign_id)
    await st.repo.delete("campaigns", campaign_id, pk=campaign_id)
    await svc(request).vectors.delete_where("library", {"meta.campaign_id": campaign_id})
    await st.audit(None, actor, "campaign.deleted", {"campaign_id": campaign_id})
    return {"deleted": campaign_id}


# ------------------------------------------------------------------------------------------------ brief


async def _brief(st: Any, campaign_id: str) -> dict[str, Any]:
    b = await st.repo.get("briefs", campaign_id, pk=campaign_id)
    if not b:
        raise NotFound("brief not found", code="brief_not_found")
    return b


@router.get("/{campaign_id}/brief")
async def get_brief(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return await _brief(st, campaign_id)


class BriefIn(BaseModel):
    raw_text: str | None = Field(default=None, max_length=30000)
    fields: dict[str, Any] | None = None


@router.put("/{campaign_id}/brief", dependencies=[Depends(mutate_limit)])
async def save_brief(request: Request, campaign_id: str, body: BriefIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    camp = await st.campaign(campaign_id)
    b = await _brief(st, campaign_id)
    if body.raw_text is not None:
        b["raw_text"] = body.raw_text
    if body.fields:
        b["fields"] = _normalize_for_storage({**b.get("fields", {}), **body.fields}, campaign_lang(camp))
    b["status"] = "draft"
    await st.repo.upsert("briefs", b)
    return b


@router.post("/{campaign_id}/brief/upload", dependencies=[Depends(mutate_limit)])
async def upload_brief_doc(request: Request, campaign_id: str, file: UploadFile = File(...), actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    """Paste-from-document intake: extract text from a .md/.txt/.pdf/.docx brief (size limited)."""
    s = svc(request)
    st = studio(request)
    await st.campaign(campaign_id)
    data = await file.read(s.settings.max_upload_bytes + 1)
    if len(data) > s.settings.max_upload_bytes:
        raise PayloadTooLarge(f"upload exceeds {s.settings.max_upload_bytes} bytes", key="err.payload_too_large.upload", params={"limit": s.settings.max_upload_bytes})
    text = extract_text(file.filename or "brief.txt", data)[:30000]
    b = await _brief(st, campaign_id)
    b["raw_text"] = (b.get("raw_text", "") + "\n\n" + text).strip()
    await st.repo.upsert("briefs", b)
    return {"chars": len(text), "raw_text": b["raw_text"]}


@router.post("/{campaign_id}/brief/analyze", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def analyze(request: Request, campaign_id: str, body: BriefIn | None = None, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    """Briefing agent: extract structured fields, score completeness, ask up to 3 clarifying questions."""
    s = svc(request)
    st = studio(request)
    camp = await st.campaign(campaign_id)
    b = await _brief(st, campaign_id)
    if body and body.raw_text is not None:
        b["raw_text"] = body.raw_text
    if body and body.fields:
        b["fields"] = _normalize_for_storage({**b.get("fields", {}), **body.fields}, campaign_lang(camp))
    raw = (b.get("raw_text") or "").strip()
    if len(raw) < 30 and not b.get("fields"):
        raise ValidationFailed("Paste a brief (or fill the wizard fields) first.", code="empty_brief")
    if raw and await s.safety.shield_prompt(raw[:9000]):
        raise ValidationFailed("Prompt Shields flagged instructions aimed at the AI inside the pasted brief; it was not processed.", code="prompt_injection", key="err.prompt_injection.brief", hint="Remove the embedded instructions and retry.")
    lang = campaign_lang(camp)
    ctx = await st.brand_context(camp["brand_id"], raw[:500] or camp["name"], k=3, lang=lang)
    extracted = await s.llm.complete(
        task="brief.extract",
        system=CREW_PREAMBLE + " You are the Briefing agent. Extract the brief fields from the text. Use empty strings/lists for anything not stated; never invent. Channels are lower-case ids (youtube, meta, tiktok, ctv, display, linkedin); markets are ISO-2 codes; durations are integers in seconds." + lang_directive(lang),
        user=f"Brand: {ctx['brand']['name']} (category {ctx['brand']['category']}).\n\n{untrusted(raw, 8000)}",
        schema=BriefExtract,
        context={"text": raw, "lang": lang},
        max_tokens=1800,
    )
    explicit = bf.parse_labeled(raw)
    merged = {**extracted.model_dump(), **{k: v for k, v in explicit.items() if v and k in {"objective", "audience", "budget", "timeline", "key_message", "cta"}}}
    # user-entered wizard fields always win
    for k, v in (b.get("fields") or {}).items():
        if v:
            merged[k] = v
    fields = bf.normalize_fields(merged, lang)
    if not fields["markets"]:
        fields["markets"] = camp.get("markets", [])
    if not fields["channels"]:
        fields["channels"] = camp.get("channels", [])
    comp = bf.completeness(fields)
    qs: list[dict[str, str]] = []
    if comp["missing"]:
        out = await s.llm.complete(
            task="brief.questions",
            system=CREW_PREAMBLE + " You are the Briefing agent. Ask at most 3 short, specific clarifying questions, only about the missing fields, prioritising what blocks scriptwriting. Each question must reference the campaign." + lang_directive(lang),
            user=f"Product: {fields['product'] or camp.get('product_id')}\nMissing fields: {comp['missing']}\nKnown: objective={fields['objective'][:200]!r}",
            schema=QuestionsOut,
            context={"missing": comp["missing"], "product": fields["product"] or "Dawn Roast", "lang": lang},
            max_tokens=700,
        )
        qs = [q.model_dump() for q in out.questions if q.field in comp["missing"]][:3] or bf.template_questions(comp["missing"], fields["product"], lang)
    b.update(fields=fields, completeness=comp, questions=qs, status="analyzed", analyzed_at=now_iso(), lang=lang)
    await st.repo.upsert("briefs", b)
    await st.audit(campaign_id, actor, "brief.analyzed", {"campaign_id": campaign_id}, {"score": comp["score"], "missing": comp["missing"]})
    return b


class AnswersIn(BaseModel):
    answers: dict[str, Any]


@router.post("/{campaign_id}/brief/answers", dependencies=[Depends(mutate_limit)])
async def answer(request: Request, campaign_id: str, body: AnswersIn, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    st = studio(request)
    camp = await st.campaign(campaign_id)
    b = await _brief(st, campaign_id)
    fields = {**b.get("fields", {})}
    for k, v in body.answers.items():
        if k not in bf.REQUIRED + bf.OPTIONAL:
            raise ValidationFailed(f"unknown brief field {k!r}", code="bad_field", params={"field": repr(k)})
        fields[k] = v
        b.setdefault("answers", []).append({"field": k, "answer": v, "at": now_iso(), "by": actor.name})
    fields = bf.normalize_fields(fields, campaign_lang(camp))
    comp = bf.completeness(fields)
    b.update(fields=fields, completeness=comp, questions=bf.template_questions(comp["missing"], fields["product"], campaign_lang(camp)) if comp["missing"] else [])
    await st.repo.upsert("briefs", b)
    return b


@router.post("/{campaign_id}/brief/finalize", dependencies=[Depends(mutate_limit)])
async def finalize(request: Request, campaign_id: str, actor: Actor = Depends(require("campaign.write"))) -> dict[str, Any]:
    """Normalize + freeze the brief as a versioned artifact (the 'brief' stage gate) and run the Guardian over it."""
    from ...core.guardian_service import evaluate, subject_from_brief

    st = studio(request)
    camp = await st.campaign(campaign_id)
    b = await _brief(st, campaign_id)
    fields = bf.normalize_fields(b.get("fields", {}), campaign_lang(camp))
    comp = bf.completeness(fields)
    if not comp["ready"]:
        missing_pl = ", ".join(bf.FIELD_LABELS_PL.get(m, m) for m in comp["missing"])
        raise ValidationFailed(
            f"Brief is not complete enough yet ({comp['score']}%). Missing: {', '.join(comp['missing'])}",
            code="brief_incomplete",
            details=comp,
            params={"score": comp["score"], "missing": {"en": ", ".join(comp["missing"]), "pl": missing_pl}},
        )
    camp.update(markets=fields["markets"] or camp.get("markets", []), channels=fields["channels"] or camp.get("channels", []), stage="strategy", status="in_progress")
    await st.save_campaign(camp)
    art = await st.create_artifact(campaign_id, "brief", {"title": t("artifact.title.brief", campaign_lang(camp)), "fields": fields, "completeness": comp, "raw_text": b.get("raw_text", "")}, actor=actor)
    subject = subject_from_brief(camp, art)
    report, _ = await evaluate(svc(request), subject, untrusted_text=b.get("raw_text"))
    art["guardian"] = {"report_id": report.id, "verdict": report.verdict, "score": report.score, "blocks": sum(1 for f in report.findings if f.severity == "block" and not f.waived), "warns": sum(1 for f in report.findings if f.severity == "warn"), "at": now_iso()}
    await st.save_artifact(art)
    b.update(status="final", fields=fields, completeness=comp, artifact_id=art["id"])
    await st.repo.upsert("briefs", b)
    await st.audit(campaign_id, actor, "brief.finalized", {"artifact_id": art["id"]}, {"guardian": art["guardian"]["verdict"]})
    return {"artifact": art, "guardian_report": report.model_dump()}


FEATURE = Feature(id="CS-04", summary="Structured brief wizard + free-text/doc paste, completeness check, up to 3 clarifying questions, normalized versioned brief.", router=router)
