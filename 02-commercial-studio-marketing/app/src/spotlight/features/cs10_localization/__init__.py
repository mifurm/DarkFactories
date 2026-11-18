"""CS-10 Localization agent — transcreation (not literal translation) to 8 languages with glossary / do-not-translate enforcement,
back-translation QA, localized VO + captions + end card, local-market Guardian review."""

from __future__ import annotations

import copy
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.ai.stubs import stub_task
from ...core.guardian_service import evaluate, subject_from_script, summarize
from ...core.jobs import JobContext
from ...deps import mutate_limit, spend_limit
from ...domain import localize as lz
from ...domain.rights import RightsEntry
from ...domain.spot_builder import SpotBuildError, build_master_spec, music_spec
from ...errors import ValidationFailed
from ...registry import Feature
from ...roles import Actor, require
from ...util import new_id
from ..common import CREW_PREAMBLE, studio, untrusted
from ..cs08_spot import post_render, render_spec_to_asset
from ..cs09_voice import build_voice
from ..jobs_util import submit_job

router = APIRouter(prefix="/api/campaigns/{campaign_id}/localization", tags=["CS-10 Localization"])

# Sentence-level phrasebook for the OFFLINE stub only (Azure mode uses the LLM). Keys: normalized English sentence.
PB: dict[str, dict[str, str]] = {
    "some mornings deserve a slower start": {"de": "Manche Morgen verdienen einen langsameren Start.", "fr": "Certains matins méritent un départ plus lent.", "pl": "Niektóre poranki zasługują na wolniejszy początek.", "es": "Algunas mañanas merecen un comienzo más lento.", "it": "Alcune mattine meritano un inizio più lento.", "pt": "Algumas manhãs merecem um começo mais lento.", "nl": "Sommige ochtenden verdienen een rustigere start."},
    "medium roast roasted in small batches": {"de": "Mittlere Röstung, in kleinen Chargen geröstet.", "fr": "Torréfaction moyenne, torréfiée en petits lots.", "pl": "Średnie palenie, palone w małych partiach.", "es": "Tueste medio, tostado en lotes pequeños.", "it": "Tostatura media, tostato in piccoli lotti.", "pt": "Torra média, torrada em pequenos lotes.", "nl": "Medium roast, in kleine batches gebrand."},
    "caramel orange peel and cocoa": {"de": "Karamell, Orangenschale und Kakao.", "fr": "Caramel, zeste d'orange et cacao.", "pl": "Karmel, skórka pomarańczy i kakao.", "es": "Caramelo, piel de naranja y cacao.", "it": "Caramello, scorza d'arancia e cacao.", "pt": "Caramelo, casca de laranja e cacau.", "nl": "Karamel, sinaasappelschil en cacao."},
    "poured without hurry": {"de": "Ohne Eile eingeschenkt.", "fr": "Servi sans se presser.", "pl": "Nalewana bez pośpiechu.", "es": "Servido sin prisa.", "it": "Versato senza fretta.", "pt": "Servido sem pressa.", "nl": "Zonder haast ingeschonken."},
    "wake up slowly": {"de": "Wach langsam auf.", "fr": "Réveillez-vous lentement.", "pl": "Obudź się powoli.", "es": "Despierta despacio.", "it": "Svegliati piano.", "pt": "Acorde devagar.", "nl": "Word rustig wakker."},
    "a slower start": {"de": "Ein langsamerer Start.", "fr": "Un départ plus lent.", "pl": "Wolniejszy początek.", "es": "Un comienzo más lento.", "it": "Un inizio più lento.", "pt": "Um começo mais lento.", "nl": "Een rustigere start."},
    "find dawn roast near you": {"de": "Finde Dawn Roast in deiner Nähe", "fr": "Trouvez Dawn Roast près de chez vous", "pl": "Znajdź Dawn Roast w pobliżu", "es": "Encuentra Dawn Roast cerca de ti", "it": "Trova Dawn Roast vicino a te", "pt": "Encontre Dawn Roast perto de si", "nl": "Vind Dawn Roast bij jou in de buurt"},
    "dawn roast brings a calmer start to your morning": {"de": "Dawn Roast bringt einen ruhigeren Start in deinen Morgen.", "fr": "Dawn Roast apporte un début de matinée plus calme.", "pl": "Dawn Roast przynosi spokojniejszy początek poranka.", "es": "Dawn Roast trae un comienzo de mañana más tranquilo.", "it": "Dawn Roast porta un inizio di mattina più calmo.", "pt": "Dawn Roast traz um começo de manhã mais calmo.", "nl": "Dawn Roast brengt een rustigere start van je ochtend."},
    "mornings called": {"de": "Der Morgen hat angerufen.", "fr": "Le matin a appelé.", "pl": "Poranek dzwonił.", "es": "La mañana llamó.", "it": "Il mattino ha chiamato.", "pt": "A manhã ligou.", "nl": "De ochtend belde."},
    "we let it ring": {"de": "Wir lassen es klingeln.", "fr": "On l'a laissé sonner.", "pl": "Pozwoliliśmy mu dzwonić.", "es": "Dejamos que sonara.", "it": "Abbiamo lasciato squillare.", "pt": "Deixámos tocar.", "nl": "Wij lieten hem overgaan."},
}
_REV: dict[tuple[str, str], str] = {}
for _en, _tr in PB.items():
    for _lang, _txt in _tr.items():
        _REV[(_lang, re.sub(r"[^\w\s]", "", _txt.lower()).strip())] = _en.capitalize() + "."
_REV[("de", "enthält koffein")] = "Contains caffeine."


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _stub_translate_text(text: str, lang: str) -> str:
    out = []
    for sent in _sentences(text):
        key = re.sub(r"[^\w\s']", "", sent.lower()).replace("'", "").strip()
        key = re.sub(r"\s+", " ", key)
        if key in {"dawn roast", "northwind"}:
            out.append(sent)
        elif key in PB and lang in PB[key]:
            t = PB[key][lang]
            out.append(t.rstrip(".") if not sent.rstrip().endswith(".") and key in {"find dawn roast near you"} else t)
        else:
            out.append(sent)
    return " ".join(out)


def _stub_back(text: str, lang: str) -> str:
    out = []
    for sent in _sentences(text):
        key = re.sub(r"[^\w\s]", "", sent.lower()).strip()
        out.append(_REV.get((lang, key), sent))
    return " ".join(out)


class LocLine(BaseModel):
    id: str
    text: str


class LocOut(BaseModel):
    lines: list[LocLine]
    notes: str


@stub_task("localize.transcreate")
def _stub_transcreate(ctx: dict[str, Any]) -> dict[str, Any]:
    lang = ctx["lang"]
    return {"lines": [{"id": ln["id"], "text": _stub_translate_text(ln["text"], lang)} for ln in ctx["lines"]], "notes": "offline phrasebook transcreation"}


@stub_task("localize.backtranslate")
def _stub_backtranslate(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"lines": [{"id": ln["id"], "text": _stub_back(ln["text"], ctx["lang"])} for ln in ctx["lines"]], "notes": "offline inverse phrasebook"}


def _source_lines(script: dict[str, Any]) -> list[dict[str, str]]:
    lines = []
    for b in script["beats"]:
        if b.get("vo"):
            lines.append({"id": f"{b['id']}:vo", "text": b["vo"]})
        if b.get("super_text"):
            lines.append({"id": f"{b['id']}:super", "text": b["super_text"]})
    if script.get("cta"):
        lines.append({"id": "cta", "text": script["cta"]})
    return lines


async def transcreate(s: Any, lines: list[dict[str, str]], lang: str, glossary: list[dict[str, Any]], tone_notes: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Mask DNT terms -> transcreate -> verify/repair glossary -> returns ({id: text}, issues)."""
    masked_lines, maps = [], {}
    for ln in lines:
        m, mp = lz.mask_terms(ln["text"], glossary)
        masked_lines.append({"id": ln["id"], "text": m})
        maps[ln["id"]] = mp
    forced = {ln["id"]: lz.forced_translations(ln["text"], glossary, lang) for ln in lines}
    system = CREW_PREAMBLE + (
        f" You are the Localizer. TRANSCREATE (not literally translate) each line into {lz.LANGS[lang]} for the {lz.LANG_MARKET[lang]} market: keep the intent, rhythm and warmth of the brand voice, adapt idioms, keep length similar so voice-over fits. "
        "Placeholders like ⟦T1⟧ are protected brand terms: copy them unchanged. Keep supers short. Return one output line per input id."
    )
    user = (
        f"Market notes: {lz.MARKET_NOTES[lang]}\nGlossary (forced translations): {[(g['term'], g['translations'].get(lang)) for g in glossary if g.get('translate', True) and g.get('translations', {}).get(lang)]}\n"
        + untrusted("\n".join(f"{ln['id']}: {ln['text']}" for ln in masked_lines), 3000)
    )
    out = await s.llm.complete(task="localize.transcreate", system=system, user=user, schema=LocOut, context={"lang": lang, "lines": lines}, max_tokens=1500)
    got = {ln.id: ln.text for ln in out.lines}
    result: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    for ln in lines:
        txt = got.get(ln["id"]) or ln["text"]
        mp = maps[ln["id"]]
        for ph, term in mp.items():
            if ph in txt:
                txt = txt.replace(ph, term)
        problems = lz.check_terms(ln["text"], txt, glossary, lang)
        if problems:
            fixed = lz.repair_terms(ln["text"], txt, glossary, lang)
            still = lz.check_terms(ln["text"], fixed, glossary, lang)
            issues += [{"line": ln["id"], **p, "repaired": not still} for p in problems]
            txt = fixed
        result[ln["id"]] = txt
    _ = forced
    return result, issues


async def back_translate(s: Any, texts: dict[str, str], lang: str) -> dict[str, str]:
    out = await s.llm.complete(
        task="localize.backtranslate",
        system="You are a translation QA assistant. Translate each line back into English literally so a reviewer can check meaning. Keep brand names unchanged.",
        user=untrusted("\n".join(f"{k}: {v}" for k, v in texts.items()), 3000),
        schema=LocOut,
        context={"lang": lang, "lines": [{"id": k, "text": v} for k, v in texts.items()]},
        max_tokens=1500,
    )
    return {ln.id: ln.text for ln in out.lines}


class LocIn(BaseModel):
    script_id: str | None = None
    langs: list[str] = Field(default_factory=lambda: ["de", "fr", "pl"], min_length=1, max_length=8)
    render: bool = True


@router.get("/languages")
async def languages() -> dict[str, Any]:
    return {"languages": [{"code": c, "name": n, "market": lz.LANG_MARKET[c], "notes": lz.MARKET_NOTES[c]} for c, n in lz.LANGS.items()], "optional_not_shipped": {"ja": "needs CJK fonts (Noto Sans CJK ~16 MB)", "zh": "needs CJK fonts", "ar": "needs Arabic shaping + RTL layout"}, "scripts_supported": ["Latin", "Cyrillic", "Greek"]}


@router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate(request: Request, campaign_id: str, body: LocIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or LocIn()
    bad = [lang for lang in body.langs if lang not in lz.LANGS or lang == "en"]
    if bad:
        raise ValidationFailed(f"unsupported target language(s) {bad}; use {[c for c in lz.LANGS if c != 'en']}", code="bad_language")
    st = studio(request)
    await st.campaign(campaign_id)

    async def run(job: JobContext) -> dict[str, Any]:
        s = request.app.state.services
        camp = await st.campaign(campaign_id)
        script = await (st.artifact(campaign_id, body.script_id, "script") if body.script_id else st.gate_artifact(camp, "script"))
        if not script:
            raise ValidationFailed("Generate a script first (CS-06).", code="script_missing")
        kit_doc = await st.brand_kit(camp["brand_id"])
        kit = {**kit_doc["kit"], "name": kit_doc["name"]}
        glossary = kit["voice"].get("glossary", [])
        sb = next((x for x in await st.artifacts(campaign_id, "storyboard") if x.get("script_id") == script["id"]), None) or await st.latest(campaign_id, "storyboard")
        master = await st.gate_artifact(camp, "spot")
        brief = await st.latest(campaign_id, "brief")
        results = []
        per = 0.9 / len(body.langs)
        for n, lang in enumerate(body.langs):
            base = 0.05 + per * n
            await job.progress(base, f"Transcreating to {lz.LANGS[lang]}", step=f"transcreate-{lang}")
            lines = _source_lines(script)
            texts, issues = await transcreate(s, lines, lang, glossary, lz.MARKET_NOTES[lang])
            legal = [lz.DISCLAIMER_TRANSLATIONS[lang] if lg.strip() == lz.DISCLAIMER else lg for lg in script.get("legal", [])]
            tagline_src = script.get("tagline") or kit.get("tagline") or "Wake up slowly."
            tagline = next((g["translations"][lang] for g in glossary if g.get("translations") and g["term"].lower() == tagline_src.lower().rstrip(".")), None)
            if tagline is None:
                tagline = (await transcreate(s, [{"id": "tagline", "text": tagline_src}], lang, glossary, ""))[0]["tagline"]
            await job.progress(base + per * 0.25, "Back-translation QA", step=f"backtranslate-{lang}")
            back = await back_translate(s, texts, lang)
            rows = []
            for ln in lines:
                sim = lz.similarity(ln["text"], back.get(ln["id"], ""))
                iss = [i for i in issues if i["line"] == ln["id"] and not i.get("repaired")]
                rows.append({"id": ln["id"], "source": ln["text"], "text": texts[ln["id"]], "back_translation": back.get(ln["id"], ""), "similarity": sim, "status": lz.status_for(sim, iss)})
            loc_script = copy.deepcopy(script)
            for b in loc_script["beats"]:
                b["vo"] = texts.get(f"{b['id']}:vo", b.get("vo", "")) if b.get("vo") else b.get("vo", "")
                if b.get("super_text"):
                    b["super_text"] = texts.get(f"{b['id']}:super", b["super_text"])
            loc_script["cta"], loc_script["legal"], loc_script["tagline"] = texts.get("cta", script.get("cta")), legal, tagline
            subject = subject_from_script(camp, loc_script, lang, [lz.LANG_MARKET[lang]])
            report, _ = await evaluate(s, subject)
            art_extra: dict[str, Any] = {}
            if body.render and sb:
                await job.progress(base + per * 0.4, f"Voicing {lz.LANGS[lang]}", step=f"voice-{lang}")
                voice_res = await build_voice(s, campaign_id, script["id"], lang, None, "female", 1.0, actor, job, script_override=loc_script, label=f"loc-{lang}")
                voice = await st.artifact(campaign_id, voice_res["artifact_id"], "voice")
                reg = [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in await st.repo.query("rights", {"kind": "music"}, pk=camp["brand_id"])]
                m_entry = next((e for e in reg if e.id == (master or {}).get("spec", {}).get("music", {}).get("rights_id")), None) or next((e for e in reg if e.id == camp.get("music_rights_id")), None) or next((e for e in reg if e.library_track), None)
                try:
                    spec = build_master_spec(spec_id=new_id("spec"), campaign=camp, script=loc_script, storyboard=sb, voice=voice, kit=kit, music=music_spec(m_entry), brief_fields=(brief or {}).get("fields"), lang=lang, title=f"{loc_script.get('title', 'Spot')} [{lang.upper()}]")
                except SpotBuildError as exc:
                    raise ValidationFailed(str(exc), code="inputs_missing") from exc
                await job.progress(base + per * 0.6, f"Rendering {lang.upper()} version", step=f"render-{lang}")
                spot = await render_spec_to_asset(s, st, camp, spec, script_id=script["id"], storyboard_id=sb["id"], voice_id=voice["id"], talent=script.get("talent", []), actor=actor, job=None, parent_id=(master or {}).get("id"), lineage_kind="localized", variant={"aspect": spec.aspect, "lang": lang, "cutdown_s": None}, markets=[lz.LANG_MARKET[lang]])
                spot = await post_render(s, st, camp, spot, actor)
                art_extra = {"voice_id": voice["id"], "spot_id": spot["id"], "video_asset_id": spot["assets"]["video"], "spot_guardian": spot["guardian"]}
            art = await st.create_artifact(campaign_id, "localization", {"title": f"Localization — {lz.LANGS[lang]}", "lang": lang, "market": lz.LANG_MARKET[lang], "script_id": script["id"], "lines": rows, "legal": legal, "tagline": tagline, "glossary_issues": issues, "min_similarity": min(r["similarity"] for r in rows), "needs_review": [r["id"] for r in rows if r["status"] != "ok"], **art_extra}, actor=actor, parent_id=script["id"])
            art["guardian"] = summarize(report)
            await st.save_artifact(art)
            results.append({"lang": lang, "artifact_id": art["id"], "needs_review": len(art["needs_review"]), "guardian": art["guardian"]["verdict"], **{k: v for k, v in art_extra.items() if k in {"spot_id", "video_asset_id"}}})
        await st.audit(campaign_id, actor, "localization.generated", {"script_id": script["id"]}, {"langs": body.langs})
        return {"localizations": results}

    return await submit_job(request, "localization.generate", run, campaign_id, f"Localizer: {', '.join(code.upper() for code in body.langs)}", "CS-10", wait, timeout=178)


@router.get("")
async def list_localizations(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return {"localizations": await st.artifacts(campaign_id, "localization")}


FEATURE = Feature(id="CS-10", summary="Transcreation to EN/DE/FR/ES/IT/PL/PT/NL with glossary + do-not-translate enforcement, back-translation QA, localized VO/captions/end card, local-market Guardian.", router=router)
