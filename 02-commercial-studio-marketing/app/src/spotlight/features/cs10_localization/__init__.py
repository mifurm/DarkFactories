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
from ...core.studio import campaign_lang
from ...deps import mutate_limit, spend_limit
from ...domain import localize as lz
from ...domain.rights import RightsEntry
from ...domain.spot_builder import SpotBuildError, build_master_spec, music_spec
from ...domain.text import fold, normalize
from ...errors import ValidationFailed
from ...i18n import label, render_message, t
from ...i18n.directive import lang_directive
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
    "some mornings deserve a slower start": {"de": "Manche Morgen verdienen einen langsameren Start.", "fr": "Certains matins méritent un départ plus lent.", "pl": "Są poranki, które zasługują na wolniejszy początek.", "es": "Algunas mañanas merecen un comienzo más lento.", "it": "Alcune mattine meritano un inizio più lento.", "pt": "Algumas manhãs merecem um começo mais lento.", "nl": "Sommige ochtenden verdienen een rustigere start."},
    "medium roast roasted in small batches": {"de": "Mittlere Röstung, in kleinen Chargen geröstet.", "fr": "Torréfaction moyenne, torréfiée en petits lots.", "pl": "Średnio palona, w małych partiach.", "es": "Tueste medio, tostado en lotes pequeños.", "it": "Tostatura media, tostato in piccoli lotti.", "pt": "Torra média, torrada em pequenos lotes.", "nl": "Medium roast, in kleine batches gebrand."},
    "caramel orange peel and cocoa": {"de": "Karamell, Orangenschale und Kakao.", "fr": "Caramel, zeste d'orange et cacao.", "pl": "Karmel, skórka pomarańczy i kakao.", "es": "Caramelo, piel de naranja y cacao.", "it": "Caramello, scorza d'arancia e cacao.", "pt": "Caramelo, casca de laranja e cacau.", "nl": "Karamel, sinaasappelschil en cacao."},
    "poured without hurry": {"de": "Ohne Eile eingeschenkt.", "fr": "Servi sans se presser.", "pl": "Nalewana bez pośpiechu.", "es": "Servido sin prisa.", "it": "Versato senza fretta.", "pt": "Servido sem pressa.", "nl": "Zonder haast ingeschonken."},
    "wake up slowly": {"de": "Wach langsam auf.", "fr": "Réveillez-vous lentement.", "pl": "Obudź się powoli.", "es": "Despierta despacio.", "it": "Svegliati piano.", "pt": "Acorde devagar.", "nl": "Word rustig wakker."},
    "a slower start": {"de": "Ein langsamerer Start.", "fr": "Un départ plus lent.", "pl": "Wolniejszy początek.", "es": "Un comienzo más lento.", "it": "Un inizio più lento.", "pt": "Um começo mais lento.", "nl": "Een rustigere start."},
    "find dawn roast near you": {"de": "Finde Dawn Roast in deiner Nähe", "fr": "Trouvez Dawn Roast près de chez vous", "pl": "Znajdź Dawn Roast w pobliżu", "es": "Encuentra Dawn Roast cerca de ti", "it": "Trova Dawn Roast vicino a te", "pt": "Encontre Dawn Roast perto de si", "nl": "Vind Dawn Roast bij jou in de buurt"},
    "dawn roast brings a calmer start to your morning": {"de": "Dawn Roast bringt einen ruhigeren Start in deinen Morgen.", "fr": "Dawn Roast apporte un début de matinée plus calme.", "pl": "Dawn Roast daje spokojniejszy początek poranka.", "es": "Dawn Roast trae un comienzo de mañana más tranquilo.", "it": "Dawn Roast porta un inizio di mattina più calmo.", "pt": "Dawn Roast traz um começo de manhã mais calmo.", "nl": "Dawn Roast brengt een rustigere start van je ochtend."},
    "mornings called": {"de": "Der Morgen hat angerufen.", "fr": "Le matin a appelé.", "pl": "Poranek dzwonił.", "es": "La mañana llamó.", "it": "Il mattino ha chiamato.", "pt": "A manhã ligou.", "nl": "De ochtend belde."},
    "we let it ring": {"de": "Wir lassen es klingeln.", "fr": "On l'a laissé sonner.", "pl": "Nie odebraliśmy.", "es": "Dejamos que sonara.", "it": "Abbiamo lasciato squillare.", "pt": "Deixámos tocar.", "nl": "Wij lieten hem overgaan."},
}
_REV: dict[tuple[str, str], str] = {}
for _en, _tr in PB.items():
    for _lang, _txt in _tr.items():
        _REV[(_lang, re.sub(r"[^\w\s]", "", _txt.lower()).strip())] = _en.capitalize() + "."
_REV[("de", "enthält koffein")] = "Contains caffeine."

# Polish-source lines of the seeded Polish scripts with their English / German / French / … counterparts (offline stub only; the Azure path uses the LLM).
# Entries are {language: sentence}; any pair of languages in an entry translates both ways.
PB_PL: list[dict[str, str]] = [
    {"pl": "Zacznij dzień wolniej.", "en": "Start your day slower.", "de": "Starte langsamer in den Tag.", "fr": "Commencez la journée plus lentement.", "es": "Empieza el día más despacio.", "it": "Inizia la giornata con più calma.", "pt": "Comece o dia com mais calma.", "nl": "Begin je dag rustiger."},
    {"pl": "Wolniejszy start.", "en": "Slower start.", "de": "Ein langsamerer Start.", "fr": "Un départ plus lent.", "es": "Un comienzo más lento.", "it": "Un inizio più lento.", "pt": "Um começo mais lento.", "nl": "Een rustigere start."},
    {"pl": "Karmel, pomarańcza, kakao.", "en": "Caramel, orange, cocoa.", "de": "Karamell, Orange, Kakao.", "fr": "Caramel, orange, cacao.", "es": "Caramelo, naranja, cacao.", "it": "Caramello, arancia, cacao.", "pt": "Caramelo, laranja, cacau.", "nl": "Karamel, sinaasappel, cacao."},
    {"pl": "Bez pośpiechu.", "en": "No rush.", "de": "Ohne Eile.", "fr": "Sans se presser.", "es": "Sin prisa.", "it": "Senza fretta.", "pt": "Sem pressa.", "nl": "Zonder haast."},
    {"pl": "Dla tych, którzy wstają przed słońcem.", "en": "For the people who start before the sun.", "de": "Für alle, die vor der Sonne aufstehen.", "fr": "Pour ceux qui se lèvent avant le soleil.", "es": "Para quienes se levantan antes que el sol.", "it": "Per chi si alza prima del sole.", "pt": "Para quem acorda antes do sol.", "nl": "Voor wie opstaat voor de zon."},
    {"pl": "Przed słońcem.", "en": "Before the sun.", "de": "Vor der Sonne.", "fr": "Avant le soleil.", "es": "Antes del sol.", "it": "Prima del sole.", "pt": "Antes do sol.", "nl": "Voor de zon."},
    {"pl": "Kawa średnio palona, w małych partiach.", "en": "A medium roast, roasted in small batches.", "de": "Ein mittlerer Röstgrad, in kleinen Chargen geröstet.", "fr": "Un café de torréfaction moyenne, torréfié en petits lots.", "es": "Un café de tueste medio, tostado en lotes pequeños.", "it": "Un caffè a tostatura media, tostato in piccoli lotti.", "pt": "Um café de torra média, torrado em pequenos lotes.", "nl": "Een medium roast, in kleine batches gebrand."},
    {"pl": "Nuty karmelu, skórki pomarańczy i kakao.", "en": "Caramel, orange peel and cocoa notes.", "de": "Noten von Karamell, Orangenschale und Kakao.", "fr": "Notes de caramel, de zeste d'orange et de cacao.", "es": "Notas de caramelo, piel de naranja y cacao.", "it": "Note di caramello, scorza d'arancia e cacao.", "pt": "Notas de caramelo, casca de laranja e cacau.", "nl": "Tonen van karamel, sinaasappelschil en cacao."},
    {"pl": "Dziesięć cichych minut, zanim zacznie się dzień.", "en": "Ten quiet minutes before the day begins.", "de": "Zehn ruhige Minuten, bevor der Tag beginnt.", "fr": "Dix minutes de calme avant que la journée ne commence.", "es": "Diez minutos de calma antes de que empiece el día.", "it": "Dieci minuti di quiete prima che inizi la giornata.", "pt": "Dez minutos de silêncio antes de o dia começar.", "nl": "Tien stille minuten voordat de dag begint."},
    {"pl": "Dziesięć cichych minut", "en": "Ten quiet minutes", "de": "Zehn ruhige Minuten", "fr": "Dix minutes de calme", "es": "Diez minutos de calma", "it": "Dieci minuti di quiete", "pt": "Dez minutos de silêncio", "nl": "Tien stille minuten"},
    {"pl": "Daje spokojniejszy początek poranka.", "en": "Brings a calmer start to your morning.", "de": "Bringt einen ruhigeren Start in deinen Morgen.", "fr": "Apporte un début de matinée plus calme.", "es": "Trae un comienzo de mañana más tranquilo.", "it": "Porta un inizio di mattina più calmo.", "pt": "Traz um começo de manhã mais calmo.", "nl": "Brengt een rustigere start van je ochtend."},
    {"pl": "Dawn Roast daje spokojniejszy początek poranka.", "en": "Dawn Roast gives you a calmer start to your morning.", "de": "Dawn Roast gibt dir einen ruhigeren Start in den Morgen.", "fr": "Dawn Roast vous offre un début de matinée plus calme."},
    {"pl": "Jest godzina, która należy tylko do ciebie.", "en": "There is an hour that belongs only to you.", "de": "Es gibt eine Stunde, die nur dir gehört.", "fr": "Il y a une heure qui n'appartient qu'à vous."},
    {"pl": "Godzina tylko dla ciebie.", "en": "An hour just for you.", "de": "Eine Stunde nur für dich.", "fr": "Une heure rien que pour vous."},
    {"pl": "Średnio palona.", "en": "Medium roast.", "de": "Mittlere Röstung.", "fr": "Torréfaction moyenne."},
    {"pl": "W małych partiach.", "en": "In small batches.", "de": "In kleinen Chargen.", "fr": "En petits lots."},
    {"pl": "Palona w małych partiach.", "en": "Roasted in small batches.", "de": "In kleinen Chargen geröstet.", "fr": "Torréfié en petits lots."},
    {"pl": "Próbujemy każdą partię, bo pierwsza filiżanka liczy się najbardziej.", "en": "We taste every batch, because the first cup matters most.", "de": "Wir verkosten jede Charge, denn die erste Tasse zählt am meisten.", "fr": "Nous goûtons chaque lot, car la première tasse compte le plus."},
    {"pl": "Karmel.", "en": "Caramel.", "de": "Karamell.", "fr": "Caramel."},
    {"pl": "Skórka pomarańczy.", "en": "Orange peel.", "de": "Orangenschale.", "fr": "Zeste d'orange."},
    {"pl": "Kakao.", "en": "Cocoa.", "de": "Kakao.", "fr": "Cacao."},
    {"pl": "Różne poranki.", "en": "Different mornings.", "de": "Verschiedene Morgen.", "fr": "Des matins différents."},
    {"pl": "Ten sam spokojny początek.", "en": "The same slow start.", "de": "Derselbe ruhige Start.", "fr": "Le même départ en douceur."},
    {"pl": "Różne poranki", "en": "Different mornings", "de": "Verschiedene Morgen", "fr": "Des matins différents"},
    {"pl": "Nic jeszcze nie musi się dziać.", "en": "Nothing else has to happen yet.", "de": "Noch muss nichts anderes passieren.", "fr": "Rien d'autre n'a encore à arriver."},
    {"pl": "Nalewana bez pośpiechu.", "en": "Poured without hurry.", "de": "Ohne Eile eingeschenkt.", "fr": "Servi sans se presser."},
    {"pl": "Poranek dzwoni.", "en": "Mornings call.", "de": "Der Morgen ruft an.", "fr": "Le matin appelle."},
    {"pl": "Niech sobie dzwoni.", "en": "Let it ring.", "de": "Soll er ruhig klingeln.", "fr": "Laissons sonner."},
]
# English phrasebook entries (the keys are normalized English sentences) joined into the same {language: sentence} shape
_PB_ENTRIES: list[dict[str, str]] = [{"en": _k.capitalize() + ".", **_v} for _k, _v in PB.items()]
# Proper casing for the English side when the SOURCE is not English (the English-source back-translation keeps its original ``capitalize()`` forms)
_EN_DISPLAY: dict[str, str] = {
    "find dawn roast near you": "Find Dawn Roast near you.",
    "dawn roast brings a calmer start to your morning": "Dawn Roast brings a calmer start to your morning.",
    "medium roast roasted in small batches": "Medium roast, roasted in small batches.",
    "caramel orange peel and cocoa": "Caramel, orange peel and cocoa.",
    "some mornings deserve a slower start": "Some mornings deserve a slower start.",
    "a slower start": "A slower start.",
    "wake up slowly": "Wake up slowly.",
    "poured without hurry": "Poured without hurry.",
    "mornings called": "Mornings called.",
    "we let it ring": "We let it ring.",
}


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", fold(text.replace("'", "").replace("’", "")).lower())).strip()


def _build_index(entries: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for entry in entries:
        for lng, txt in entry.items():
            index.setdefault((lng, _norm_key(txt)), entry)
    return index


# English-source jobs keep the original phrasebook first (so English output is unchanged); any other source language prefers its own entries.
_INDEX_EN = _build_index(_PB_ENTRIES + PB_PL)
_INDEX_OTHER = _build_index(PB_PL + _PB_ENTRIES)


def _index(source: str) -> dict[tuple[str, str], dict[str, str]]:
    return _INDEX_EN if source == "en" else _INDEX_OTHER


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


_DNT_SENTENCES = {"dawn roast", "northwind"}
_BACK_ONLY = {("de", "enthalt koffein"): "Contains caffeine."}  # back-translation of the German disclaimer (never used as a translation source)


def _stub_translate_text(text: str, lang: str, source: str = "en") -> str:
    """Offline phrasebook translation from ``source`` to ``lang`` (any direction); unknown sentences pass through unchanged."""
    index = _index(source)
    out = []
    for sent in _sentences(text):
        key = _norm_key(sent)
        entry = index.get((source, key))
        if key in _DNT_SENTENCES:
            out.append(sent)
        elif entry is not None and lang in entry:
            t = entry[lang]
            if lang == "en" and source != "en":
                t = _EN_DISPLAY.get(_norm_key(t), t)
            unpunctuated = not sent.rstrip().endswith((".", "!", "?", "…"))
            out.append(t.rstrip(".") if unpunctuated and (key == "find dawn roast near you" if source == "en" else True) else t)
        else:
            out.append(sent)
    return " ".join(out)


def _stub_back(text: str, lang: str, source: str = "en") -> str:
    """Offline inverse phrasebook: ``text`` (in ``lang``) back into the source language."""
    index = _index(source)
    out = []
    for sent in _sentences(text):
        key = _norm_key(sent)
        entry = index.get((lang, key))
        if entry is not None and source in entry:
            out.append(entry[source])
        elif source == "en" and (lang, key) in _BACK_ONLY:
            out.append(_BACK_ONLY[(lang, key)])
        else:
            out.append(sent)
    return " ".join(out)


class LocLine(BaseModel):
    id: str
    text: str


class LocOut(BaseModel):
    lines: list[LocLine]
    notes: str


@stub_task("localize.transcreate")
def _stub_transcreate(ctx: dict[str, Any]) -> dict[str, Any]:
    lang, source = ctx["lang"], ctx.get("source", "en")
    return {"lines": [{"id": ln["id"], "text": _stub_translate_text(ln["text"], lang, source)} for ln in ctx["lines"]], "notes": "offline phrasebook transcreation"}


@stub_task("localize.backtranslate")
def _stub_backtranslate(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"lines": [{"id": ln["id"], "text": _stub_back(ln["text"], ctx["lang"], ctx.get("source", "en"))} for ln in ctx["lines"]], "notes": "offline inverse phrasebook"}


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


async def transcreate(s: Any, lines: list[dict[str, str]], lang: str, glossary: list[dict[str, Any]], tone_notes: str, source_lang: str = "en") -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Mask DNT terms -> transcreate ``source_lang`` -> ``lang`` -> verify/repair glossary -> returns ({id: text}, issues). Any direction (PL->EN/DE/FR…, EN->PL…)."""
    masked_lines, maps = [], {}
    for ln in lines:
        m, mp = lz.mask_terms(ln["text"], glossary)
        masked_lines.append({"id": ln["id"], "text": m})
        maps[ln["id"]] = mp
    forced = [(src_form, lz.source_form(g, lang)) for g in glossary if g.get("translate", True) and (src_form := lz.source_form(g, source_lang)) and lz.source_form(g, lang)]
    system = CREW_PREAMBLE + (
        f" You are the Localizer. TRANSCREATE (not literally translate) each line {'' if source_lang == 'en' else f'from {lz.LANGS[source_lang]} '}into {lz.LANGS[lang]} for the {lz.LANG_MARKET[lang]} market: keep the intent, rhythm and warmth of the brand voice, adapt idioms, keep length similar so voice-over fits. "
        "Placeholders like ⟦T1⟧ are protected brand terms: copy them unchanged. Keep supers short. Return one output line per input id."
    ) + (lang_directive(lang) if lang != "en" else "")
    user = (
        f"Market notes: {lz.MARKET_NOTES[lang]}\nGlossary (forced translations{'' if source_lang == 'en' else f', {source_lang} -> {lang}'}): {forced}\n"
        + untrusted("\n".join(f"{ln['id']}: {ln['text']}" for ln in masked_lines), 3000)
    )
    out = await s.llm.complete(task="localize.transcreate", system=system, user=user, schema=LocOut, context={"lang": lang, "source": source_lang, "lines": lines}, max_tokens=1500 if lang != "pl" else 2200)
    got = {ln.id: ln.text for ln in out.lines}
    result: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    for ln in lines:
        txt = got.get(ln["id"]) or ln["text"]
        mp = maps[ln["id"]]
        for ph, term in mp.items():
            if ph in txt:
                txt = txt.replace(ph, term)
        problems = lz.check_terms(ln["text"], txt, glossary, lang, source_lang)
        if problems:
            fixed = lz.repair_terms(ln["text"], txt, glossary, lang, source_lang)
            still = lz.check_terms(ln["text"], fixed, glossary, lang, source_lang)
            issues += [{"line": ln["id"], **p, "repaired": not still} for p in problems]
            txt = fixed
        result[ln["id"]] = txt
    return result, issues


async def back_translate(s: Any, texts: dict[str, str], lang: str, source_lang: str = "en") -> dict[str, str]:
    """The localized lines literally back into the SOURCE language, so a reviewer who reads the source language can check the meaning."""
    out = await s.llm.complete(
        task="localize.backtranslate",
        system=f"You are a translation QA assistant. Translate each line back into {lz.LANGS[source_lang]} literally so a reviewer can check meaning. Keep brand names unchanged.",
        user=untrusted("\n".join(f"{k}: {v}" for k, v in texts.items()), 3000),
        schema=LocOut,
        context={"lang": lang, "source": source_lang, "lines": [{"id": k, "text": v} for k, v in texts.items()]},
        max_tokens=1500,
    )
    return {ln.id: ln.text for ln in out.lines}


class LocIn(BaseModel):
    script_id: str | None = None
    langs: list[str] | None = Field(default=None, min_length=1, max_length=8)  # default: de/fr/pl for an English script, en/de/fr for any other source language
    render: bool = True


def default_targets(source_lang: str) -> list[str]:
    return ["de", "fr", "pl"] if source_lang == "en" else [c for c in ("en", "de", "fr") if c != source_lang]


@router.get("/languages")
async def languages() -> dict[str, Any]:
    return {"languages": [{"code": c, "name": n, "label": label("label.lang", c), "market": lz.LANG_MARKET[c], "notes": t(f"loc.note.{c}")} for c, n in lz.LANGS.items()], "directions": t("loc.directions"), "optional_not_shipped": {code: t(f"loc.optional.{code}") for code in ("ja", "zh", "ar")}, "scripts_supported": ["Latin", "Cyrillic", "Greek"]}


def _localize_issues(art: dict[str, Any]) -> dict[str, Any]:
    """A localization artifact with its glossary issues rendered in the viewer's language (stored as code + params)."""
    if not art.get("glossary_issues"):
        return art
    return {**art, "glossary_issues": [{**i, "message": render_message(i.get("key"), i.get("params"), i.get("message", ""))} for i in art["glossary_issues"]]}


@router.post("/generate", dependencies=[Depends(mutate_limit), Depends(spend_limit)])
async def generate(request: Request, campaign_id: str, body: LocIn | None = None, wait: bool = False, actor: Actor = Depends(require("generate"))) -> dict[str, Any]:
    body = body or LocIn()
    st = studio(request)
    camp0 = await st.campaign(campaign_id)
    script0 = await (st.artifact(campaign_id, body.script_id, "script") if body.script_id else st.gate_artifact(camp0, "script"))
    source_lang = (script0 or {}).get("lang") or campaign_lang(camp0)  # the language the creative was written in
    langs = body.langs or default_targets(source_lang)
    bad = [lang for lang in langs if lang not in lz.LANGS or lang == source_lang]
    if bad:
        supported = [c for c in lz.LANGS if c != source_lang]
        raise ValidationFailed(f"unsupported target language(s) {bad}; use {supported}", code="bad_language", params={"langs": ", ".join(bad), "supported": ", ".join(supported)})

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
        per = 0.9 / len(langs)
        for n, lang in enumerate(langs):
            base = 0.05 + per * n
            await job.progress(base, step=f"transcreate-{lang}", key="job.msg.loc.transcreate", params={"language": lang})
            lines = _source_lines(script)
            texts, issues = await transcreate(s, lines, lang, glossary, lz.MARKET_NOTES[lang], source_lang)
            legal = [lz.translate_legal(lg, source_lang, lang) for lg in script.get("legal", [])]
            tagline_src = script.get("tagline") or kit.get("tagline") or ("Obudź się powoli." if source_lang == "pl" else "Wake up slowly.")
            tagline = next((tf for g in glossary if g.get("translate", True) and (sf := lz.source_form(g, source_lang)) and (tf := lz.source_form(g, lang)) and normalize(sf) == normalize(tagline_src)), None)
            if tagline is None:
                tagline = (await transcreate(s, [{"id": "tagline", "text": tagline_src}], lang, glossary, "", source_lang))[0]["tagline"]
            await job.progress(base + per * 0.25, step=f"backtranslate-{lang}", key="job.msg.loc.backtranslate")
            back = await back_translate(s, texts, lang, source_lang)
            rows = []
            for ln in lines:
                sim = lz.similarity(ln["text"], back.get(ln["id"], ""), source_lang)
                iss = [i for i in issues if i["line"] == ln["id"] and not i.get("repaired")]
                rows.append({"id": ln["id"], "source": ln["text"], "text": texts[ln["id"]], "back_translation": back.get(ln["id"], ""), "similarity": sim, "status": lz.status_for(sim, iss)})
            loc_script = copy.deepcopy(script)
            loc_script["lang"] = lang
            for b in loc_script["beats"]:
                b["vo"] = texts.get(f"{b['id']}:vo", b.get("vo", "")) if b.get("vo") else b.get("vo", "")
                if b.get("super_text"):
                    b["super_text"] = texts.get(f"{b['id']}:super", b["super_text"])
            loc_script["cta"], loc_script["legal"], loc_script["tagline"] = texts.get("cta", script.get("cta")), legal, tagline
            subject = subject_from_script(camp, loc_script, lang, [lz.LANG_MARKET[lang]])
            report, _ = await evaluate(s, subject)
            art_extra: dict[str, Any] = {}
            if body.render and sb:
                await job.progress(base + per * 0.4, step=f"voice-{lang}", key="job.msg.loc.voice", params={"language": lang})
                voice_res = await build_voice(s, campaign_id, script["id"], lang, None, "female", 1.0, actor, job, script_override=loc_script, label=f"loc-{lang}")
                voice = await st.artifact(campaign_id, voice_res["artifact_id"], "voice")
                reg = [RightsEntry(**{k: v for k, v in r.items() if k in RightsEntry.model_fields}) for r in await st.repo.query("rights", {"kind": "music"}, pk=camp["brand_id"])]
                m_entry = next((e for e in reg if e.id == (master or {}).get("spec", {}).get("music", {}).get("rights_id")), None) or next((e for e in reg if e.id == camp.get("music_rights_id")), None) or next((e for e in reg if e.library_track), None)
                sb_loc = copy.deepcopy(sb)  # the keyframes are reused, the on-screen supers follow the target language
                loc_supers = {b["id"]: b.get("super_text") for b in loc_script["beats"]}
                for sh in sb_loc["shots"]:
                    if sh.get("beat_id") in loc_supers:
                        sh["super_text"] = loc_supers[sh["beat_id"]]
                try:
                    spec = build_master_spec(spec_id=new_id("spec"), campaign=camp, script=loc_script, storyboard=sb_loc, voice=voice, kit=kit, music=music_spec(m_entry), brief_fields=(brief or {}).get("fields"), lang=lang, title=f"{loc_script.get('title', 'Spot')} [{lang.upper()}]")
                except SpotBuildError as exc:
                    raise ValidationFailed(str(exc), code="inputs_missing", key=exc.key, params=exc.params or {"detail": str(exc)}) from exc
                await job.progress(base + per * 0.6, step=f"render-{lang}", key="job.msg.loc.render", params={"code": lang.upper()})
                spot = await render_spec_to_asset(s, st, camp, spec, script_id=script["id"], storyboard_id=sb["id"], voice_id=voice["id"], talent=script.get("talent", []), actor=actor, job=None, parent_id=(master or {}).get("id"), lineage_kind="localized", variant={"aspect": spec.aspect, "lang": lang, "cutdown_s": None}, markets=[lz.LANG_MARKET[lang]])
                spot = await post_render(s, st, camp, spot, actor)
                art_extra = {"voice_id": voice["id"], "spot_id": spot["id"], "video_asset_id": spot["assets"]["video"], "spot_guardian": spot["guardian"]}
            art = await st.create_artifact(campaign_id, "localization", {"title": t("artifact.title.localization", source_lang, language=label("label.lang", lang, source_lang)), "lang": lang, "source_lang": source_lang, "market": lz.LANG_MARKET[lang], "script_id": script["id"], "lines": rows, "legal": legal, "tagline": tagline, "glossary_issues": issues, "min_similarity": min(r["similarity"] for r in rows), "needs_review": [r["id"] for r in rows if r["status"] != "ok"], **art_extra}, actor=actor, parent_id=script["id"])
            art["guardian"] = summarize(report)
            await st.save_artifact(art)
            results.append({"lang": lang, "source_lang": source_lang, "artifact_id": art["id"], "needs_review": len(art["needs_review"]), "guardian": art["guardian"]["verdict"], **{k: v for k, v in art_extra.items() if k in {"spot_id", "video_asset_id"}}})
        await st.audit(campaign_id, actor, "localization.generated", {"script_id": script["id"]}, {"langs": langs, "source_lang": source_lang})
        return {"localizations": results}

    return await submit_job(request, "localization.generate", run, campaign_id, "job.title.localization", "CS-10", wait, timeout=178, title_params={"langs": ", ".join(code.upper() for code in langs)})


@router.get("")
async def list_localizations(request: Request, campaign_id: str) -> dict[str, Any]:
    st = studio(request)
    await st.campaign(campaign_id)
    return {"localizations": [_localize_issues(a) for a in await st.artifacts(campaign_id, "localization")]}


FEATURE = Feature(id="CS-10", summary="Transcreation to EN/DE/FR/ES/IT/PL/PT/NL with glossary + do-not-translate enforcement, back-translation QA, localized VO/captions/end card, local-market Guardian.", router=router)
