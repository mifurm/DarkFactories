"""CC-19 Multilingual & accessibility: 40+ language catalogue with an honest coverage statement, per-utterance language detection, evaluation on the
seeded multilingual set (detection + intent, per language), translation (agent <-> customer language) with a round-trip check, and downloadable
transcripts / WebVTT captions for chat and voice."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...core.rbac import Actor, actor_from_request, require
from ...core.registry import EPIC_E, FeatureInfo
from ...engine.translate import translate
from ...engine.understanding import analyze

FEATURES = [
    FeatureInfo(
        "CC-19", "Multilingual & accessibility", EPIC_E, "P1", "/i18n", "/api/i18n",
        "Per-utterance language detection, 40+ languages (8 Contoso markets evaluated, others best-effort), real-time translation for human agents, live captions and downloadable transcripts for chat and voice, WCAG-oriented UI.",
    ),
]  # fmt: skip

router = APIRouter(prefix="/api/i18n", tags=["i18n (CC-19)"])

EVALUATED = ["en", "de", "fr", "es", "it", "nl", "pl", "pt"]
# code, English name, native name, right-to-left, Azure Speech locale
LANGUAGES: list[tuple[str, str, str, bool, str]] = [
    ("en", "English", "English", False, "en-GB"), ("de", "German", "Deutsch", False, "de-DE"), ("fr", "French", "Français", False, "fr-FR"), ("es", "Spanish", "Español", False, "es-ES"),
    ("it", "Italian", "Italiano", False, "it-IT"), ("nl", "Dutch", "Nederlands", False, "nl-NL"), ("pl", "Polish", "Polski", False, "pl-PL"), ("pt", "Portuguese", "Português", False, "pt-PT"),
    ("sv", "Swedish", "Svenska", False, "sv-SE"), ("da", "Danish", "Dansk", False, "da-DK"), ("nb", "Norwegian", "Norsk bokmål", False, "nb-NO"), ("fi", "Finnish", "Suomi", False, "fi-FI"),
    ("cs", "Czech", "Čeština", False, "cs-CZ"), ("sk", "Slovak", "Slovenčina", False, "sk-SK"), ("sl", "Slovenian", "Slovenščina", False, "sl-SI"), ("hr", "Croatian", "Hrvatski", False, "hr-HR"),
    ("sr", "Serbian", "Srpski", False, "sr-RS"), ("hu", "Hungarian", "Magyar", False, "hu-HU"), ("ro", "Romanian", "Română", False, "ro-RO"), ("bg", "Bulgarian", "Български", False, "bg-BG"),
    ("el", "Greek", "Ελληνικά", False, "el-GR"), ("tr", "Turkish", "Türkçe", False, "tr-TR"), ("uk", "Ukrainian", "Українська", False, "uk-UA"), ("ru", "Russian", "Русский", False, "ru-RU"),
    ("lt", "Lithuanian", "Lietuvių", False, "lt-LT"), ("lv", "Latvian", "Latviešu", False, "lv-LV"), ("et", "Estonian", "Eesti", False, "et-EE"), ("ca", "Catalan", "Català", False, "ca-ES"),
    ("ga", "Irish", "Gaeilge", False, "ga-IE"), ("is", "Icelandic", "Íslenska", False, "is-IS"), ("ar", "Arabic", "العربية", True, "ar-SA"), ("he", "Hebrew", "עברית", True, "he-IL"),
    ("fa", "Persian", "فارسی", True, "fa-IR"), ("ur", "Urdu", "اردو", True, "ur-PK"), ("hi", "Hindi", "हिन्दी", False, "hi-IN"), ("bn", "Bengali", "বাংলা", False, "bn-IN"),
    ("ta", "Tamil", "தமிழ்", False, "ta-IN"), ("ja", "Japanese", "日本語", False, "ja-JP"), ("ko", "Korean", "한국어", False, "ko-KR"), ("zh", "Chinese (Mandarin)", "中文", False, "zh-CN"),
    ("th", "Thai", "ไทย", False, "th-TH"), ("vi", "Vietnamese", "Tiếng Việt", False, "vi-VN"), ("id", "Indonesian", "Bahasa Indonesia", False, "id-ID"), ("ms", "Malay", "Bahasa Melayu", False, "ms-MY"),
    ("fil", "Filipino", "Filipino", False, "fil-PH"), ("sw", "Swahili", "Kiswahili", False, "sw-KE"), ("af", "Afrikaans", "Afrikaans", False, "af-ZA"),
]  # fmt: skip

# Seed set for the evaluation: (language, text, expected intent). Short, realistic opening messages.
EVAL_SET: list[tuple[str, str, str]] = [
    ("en", "My sofa arrived damaged, the order number is CH-100231.", "damaged_item"), ("en", "Where is my order? The tracking page shows nothing.", "order_status"), ("en", "I would like to return the wardrobe I bought last week.", "return_request"),
    ("en", "When will I get my refund for the cancelled order?", "refund_status"), ("en", "Can you reschedule my delivery to Friday?", "delivery_change"), ("en", "The washing machine stopped working, is it still under warranty?", "warranty_claim"),
    ("en", "I was charged twice for the same payment.", "billing_question"), ("en", "I need to change the delivery address, I moved house.", "address_change"),
    ("de", "Mein Sofa ist beschädigt angekommen, die Bestellnummer ist CH-100231.", "damaged_item"), ("de", "Wo ist meine Bestellung? Die Sendungsverfolgung zeigt nichts an.", "order_status"), ("de", "Ich möchte den Schrank zurückgeben, den ich letzte Woche gekauft habe.", "return_request"),
    ("de", "Wann bekomme ich meine Rückerstattung für die stornierte Bestellung?", "refund_status"), ("de", "Können Sie meine Lieferung auf Freitag verschieben?", "delivery_change"), ("de", "Die Waschmaschine funktioniert nicht mehr, gibt es noch Garantie?", "warranty_claim"),
    ("de", "Ich wurde für dieselbe Zahlung doppelt belastet, die Rechnung stimmt nicht.", "billing_question"), ("de", "Ich muss die Adresse ändern, ich bin umgezogen. Neue Adresse bitte.", "address_change"),
    ("fr", "Mon canapé est arrivé endommagé, le numéro de commande est CH-100231.", "damaged_item"), ("fr", "Où est ma commande ? Le suivi n'affiche rien.", "order_status"), ("fr", "Je voudrais retourner l'armoire achetée la semaine dernière.", "return_request"),
    ("fr", "Quand vais-je recevoir mon remboursement pour la commande annulée ?", "refund_status"), ("fr", "Pouvez-vous reprogrammer ma livraison à vendredi ?", "delivery_change"), ("fr", "Le lave-linge ne fonctionne plus, est-il encore sous garantie ?", "warranty_claim"),
    ("fr", "J'ai été prélevé deux fois pour le même paiement, la facture est fausse.", "billing_question"), ("fr", "Je dois changer l'adresse de livraison, nouvelle adresse s'il vous plaît.", "address_change"),
    ("es", "Mi sofá llegó dañado, el número de pedido es CH-100231.", "damaged_item"), ("es", "¿Dónde está mi pedido? El seguimiento no muestra nada.", "order_status"), ("es", "Quiero devolver el armario que compré la semana pasada.", "return_request"),
    ("es", "¿Cuándo recibiré el reembolso del pedido cancelado?", "refund_status"), ("es", "¿Pueden reprogramar mi entrega para el viernes?", "delivery_change"), ("es", "La lavadora dejó de funcionar, ¿sigue en garantía?", "warranty_claim"),
    ("es", "Me cobraron dos veces el mismo pago, la factura es incorrecta.", "billing_question"), ("es", "Necesito cambiar la dirección de entrega, nueva dirección por favor.", "address_change"),
    ("it", "Il mio divano è arrivato danneggiato, il numero d'ordine è CH-100231.", "damaged_item"), ("it", "Dov'è il mio ordine? Il tracking non mostra nulla.", "order_status"), ("it", "Vorrei restituire l'armadio acquistato la settimana scorsa.", "return_request"),
    ("it", "Quando riceverò il rimborso per l'ordine annullato?", "refund_status"), ("it", "Potete riprogrammare la mia consegna a venerdì?", "delivery_change"), ("it", "La lavatrice non funziona più, è ancora in garanzia?", "warranty_claim"),
    ("it", "Mi hanno addebitato due volte lo stesso pagamento, la fattura è sbagliata.", "billing_question"), ("it", "Devo cambiare l'indirizzo di consegna, nuovo indirizzo per favore.", "address_change"),
    ("nl", "Mijn bank is beschadigd aangekomen, het bestelnummer is CH-100231.", "damaged_item"), ("nl", "Waar is mijn bestelling? De tracking toont niets.", "order_status"), ("nl", "Ik wil de kast retourneren die ik vorige week heb gekocht.", "return_request"),
    ("nl", "Wanneer krijg ik mijn terugbetaling voor de geannuleerde bestelling?", "refund_status"), ("nl", "Kunt u mijn levering verplaatsen naar vrijdag?", "delivery_change"), ("nl", "De wasmachine werkt niet meer, is er nog garantie?", "warranty_claim"),
    ("nl", "Ik ben twee keer belast voor dezelfde betaling, de factuur klopt niet.", "billing_question"), ("nl", "Ik moet het afleveradres wijzigen, nieuw adres alstublieft.", "address_change"),
    ("pl", "Moja sofa dotarła uszkodzona, numer zamówienia to CH-100231.", "damaged_item"), ("pl", "Gdzie jest moje zamówienie? Śledzenie nic nie pokazuje.", "order_status"), ("pl", "Chciałbym zwrócić szafę kupioną w zeszłym tygodniu.", "return_request"),
    ("pl", "Kiedy dostanę zwrot pieniędzy za anulowane zamówienie?", "refund_status"), ("pl", "Czy możecie przełożyć moją dostawę na piątek?", "delivery_change"), ("pl", "Pralka przestała działać, czy jest jeszcze gwarancja?", "warranty_claim"),
    ("pl", "Pobrano mi dwa razy tę samą płatność, faktura jest błędna.", "billing_question"), ("pl", "Muszę zmienić adres dostawy, nowy adres proszę.", "address_change"),
    ("pt", "O meu sofá chegou danificado, o número da encomenda é CH-100231.", "damaged_item"), ("pt", "Onde está a minha encomenda? O rastreio não mostra nada.", "order_status"), ("pt", "Quero devolver o armário que comprei na semana passada.", "return_request"),
    ("pt", "Quando vou receber o reembolso da encomenda cancelada?", "refund_status"), ("pt", "Podem reagendar a minha entrega para sexta-feira?", "delivery_change"), ("pt", "A máquina de lavar deixou de funcionar, ainda tem garantia?", "warranty_claim"),
    ("pt", "Fui cobrado duas vezes pelo mesmo pagamento, a fatura está errada.", "billing_question"), ("pt", "Preciso de alterar a morada de entrega, nova morada por favor.", "address_change"),
]  # fmt: skip


def catalogue() -> list[dict[str, Any]]:
    return [{"code": c, "name": n, "native": nat, "rtl": rtl, "speech_locale": loc, "tier": "evaluated" if c in EVALUATED else "best-effort"} for c, n, nat, rtl, loc in LANGUAGES]


async def evaluate_detection(svc: Any) -> dict[str, Any]:
    """Detection (Azure AI Language when available, rules otherwise) and rule-based intent accuracy per evaluated language."""
    sem = asyncio.Semaphore(8)

    async def one(lang: str, text: str, intent: str) -> dict[str, Any]:
        async with sem:
            det, conf = await svc.cognitive.detect_language(text)
        u = analyze(text, lang_hint=det)
        return {"lang": lang, "text": text, "detected": det, "confidence": round(conf, 3), "detect_ok": det == lang, "intent": u.intent, "intent_expected": intent, "intent_ok": u.intent == intent}

    rows = await asyncio.gather(*(one(*item) for item in EVAL_SET))
    per: dict[str, dict[str, Any]] = {}
    for lang in EVALUATED:
        rs = [r for r in rows if r["lang"] == lang]
        per[lang] = {"n": len(rs), "detection_accuracy": round(sum(r["detect_ok"] for r in rs) / len(rs), 3), "intent_accuracy": round(sum(r["intent_ok"] for r in rs) / len(rs), 3)}
    return {
        "n": len(rows), "detection_accuracy": round(sum(r["detect_ok"] for r in rows) / len(rows), 3), "intent_accuracy": round(sum(r["intent_ok"] for r in rows) / len(rows), 3), "per_language": per,
        "provider": getattr(svc.cognitive, "name", "rules"), "failures": [r for r in rows if not (r["detect_ok"] and r["intent_ok"])][:20], "targets": {"detection": 0.95, "intent": 0.85},
    }  # fmt: skip


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w{3,}", s.lower())}


async def round_trip(svc: Any, per_language: int = 3) -> dict[str, Any]:
    """customer language -> English (agent language) -> customer language; token overlap with the original measures meaning preservation."""
    items = [(lang, text) for lang in EVALUATED if lang != "en" for text in [t for ln, t, _ in EVAL_SET if ln == lang][:per_language]]
    sem = asyncio.Semaphore(6)

    async def one(lang: str, text: str) -> dict[str, Any]:
        async with sem:
            en = await translate(svc, text, "en", lang)
            back = await translate(svc, en["text"], lang, "en")
        a, b = _tokens(text), _tokens(back["text"])
        score = len(a & b) / max(len(a | b), 1)
        return {"lang": lang, "original": text, "english": en["text"], "back": back["text"], "overlap": round(score, 2), "via": en.get("provider")}

    rows = await asyncio.gather(*(one(*i) for i in items))
    return {"n": len(rows), "avg_overlap": round(sum(r["overlap"] for r in rows) / len(rows), 3), "rows": rows, "provider": rows[0]["via"] if rows else None, "note": "token-overlap proxy for meaning preservation; glossary translation offline, LLM translation in Azure mode"}


@router.get("/languages")
async def languages() -> dict[str, Any]:
    cat = catalogue()
    return {
        "languages": cat, "total": len(cat), "evaluated": EVALUATED,
        "coverage_statement": f"{len(EVALUATED)} Contoso markets (EN, DE, FR, ES, IT, NL, PL, PT) are evaluated for chat; the other {len(cat) - len(EVALUATED)} languages are best-effort (model-native, not evaluated). Voice quality varies by language; only evaluated languages are claimed.",
    }  # fmt: skip


class DetectBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/detect")
async def detect(body: DetectBody, request: Request) -> dict[str, Any]:
    svc = request.app.state.services
    lang, conf = await svc.cognitive.detect_language(body.text)
    meta = next((x for x in catalogue() if x["code"] == lang), None)
    return {"language": lang, "confidence": round(conf, 3), "name": meta["name"] if meta else lang, "tier": meta["tier"] if meta else "unlisted", "provider": getattr(svc.cognitive, "name", "rules")}


@router.get("/eval")
async def eval_detection(request: Request, _: Actor = Depends(require("evals.read", "agent.console", "supervisor"))) -> dict[str, Any]:
    return await evaluate_detection(request.app.state.services)


@router.post("/eval/round-trip")
async def eval_round_trip(request: Request, _: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    return await round_trip(request.app.state.services)


class TranslateBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    target: str = Field(max_length=8)
    source: str | None = Field(None, max_length=8)


@router.post("/translate")
async def translate_text(body: TranslateBody, request: Request, _: Actor = Depends(require("agent.console", "supervisor"))) -> dict[str, Any]:
    return await translate(request.app.state.services, body.text, body.target, body.source)


def _vtt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


@router.get("/transcript/{conv_id}", response_class=PlainTextResponse)
async def transcript(conv_id: str, request: Request, format: str = "txt") -> Any:
    """Downloadable transcript (txt | json) or WebVTT captions (vtt). The conversation id is the capability for the customer; staff access is audited."""
    svc = request.app.state.services
    conv = await svc.store.get(conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    actor = actor_from_request(request)
    if actor.role != "customer":
        await svc.access_audit.log("transcript.downloaded", actor=f"{actor.role}:{actor.user}", resource=conv_id, conv_id=conv_id, detail={"format": format})
    masked = conv.consent.recording == "declined"
    msgs = [m for m in conv.messages if m.visible_to_customer and m.role in ("customer", "agent_ai", "agent_human", "system_notice")]
    label = {"customer": "Customer", "agent_ai": "Concierge (AI)", "agent_human": "Colleague", "system_notice": "Notice"}
    start = conv.created_at
    text_of = (lambda m: "[not recorded - recording consent declined]") if masked else (lambda m: m.text)
    if format == "json":
        return PlainTextResponse(json.dumps({"conversation_id": conv.id, "language": conv.language, "channel": conv.channel, "started": datetime.fromtimestamp(start, UTC).isoformat(), "messages": [{"t": round(m.ts - start, 2), "speaker": label[m.role], "text": text_of(m), "lang": m.lang} for m in msgs]}, ensure_ascii=False, indent=1), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{conv.id}.json"'})
    if format == "vtt":
        lines = ["WEBVTT", ""]
        for i, m in enumerate(msgs):
            t0 = max(0.0, m.ts - start)
            t1 = (msgs[i + 1].ts - start) if i + 1 < len(msgs) else t0 + max(2.0, len(m.text) / 14)
            lines += [str(i + 1), f"{_vtt_time(t0)} --> {_vtt_time(max(t1 - 0.05, t0 + 1))}", f"<v {label[m.role]}>{text_of(m)}", ""]
        return PlainTextResponse("\n".join(lines), media_type="text/vtt", headers={"Content-Disposition": f'attachment; filename="{conv.id}.vtt"'})
    body = "\n".join(f"[{_vtt_time(m.ts - start)[:8]}] {label[m.role]}: {text_of(m)}" for m in msgs)
    head = f"Contoso Home - conversation {conv.id} ({conv.channel}, {conv.language}) - started {datetime.fromtimestamp(start, UTC):%Y-%m-%d %H:%M} UTC\n{'-' * 72}\n"
    return PlainTextResponse(head + body + "\n", headers={"Content-Disposition": f'attachment; filename="{conv.id}.txt"'})
