"""Proactive & outbound engagement rules (CC-18): consent, opt-out, quiet hours by recipient time zone, frequency caps, campaign controls.
Pure functions: every decision returns a record with the reason and the consent evidence used (audited by the caller)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..core import i18n
from ..core.textutil import fold

TZ = {"DE": "Europe/Berlin", "UK": "Europe/London", "FR": "Europe/Paris", "ES": "Europe/Madrid", "IT": "Europe/Rome", "NL": "Europe/Amsterdam", "PL": "Europe/Warsaw", "PT": "Europe/Lisbon"}
CHANNEL_ORDER = ["sms", "email", "voice"]
CONSENT_TEXT_VERSION = "contact-consent-2026-03"
AI_NOTE = {
    "en": "This is an automated message from Concierge, Contoso Home's AI assistant.", "de": "Dies ist eine automatische Nachricht von Concierge, dem KI-Assistenten von Contoso Home.",
    "fr": "Ceci est un message automatique de Concierge, l'assistant IA de Contoso Home.", "es": "Este es un mensaje automático de Concierge, el asistente de IA de Contoso Home.",
    "it": "Questo è un messaggio automatico di Concierge, l'assistente IA di Contoso Home.", "nl": "Dit is een automatisch bericht van Concierge, de AI-assistent van Contoso Home.",
    "pl": "To automatyczna wiadomość od Concierge, asystenta AI Contoso Home.", "pt": "Esta é uma mensagem automática do Concierge, o assistente de IA da Contoso Home.",
}  # fmt: skip
STOP = {"en": "Reply STOP to opt out.", "de": "Antworten Sie STOP zum Abmelden.", "fr": "Répondez STOP pour vous désabonner.", "es": "Responda STOP para darse de baja.", "it": "Rispondi STOP per annullare l'iscrizione.", "nl": "Antwoord STOP om u af te melden.", "pl": "Aby zrezygnować z powiadomień, prosimy o odpowiedź: STOP lub REZYGNUJĘ.", "pt": "Responda STOP para cancelar."}  # fmt: skip
TEMPLATES = {
    "shipment_delayed": {
        "en": "Hello {first_name}, your order {order_id} is delayed at {carrier}. New estimated delivery: {eta}. Reply here to reschedule, ask a question or request a callback.",
        "de": "Hallo {first_name}, Ihre Bestellung {order_id} verzögert sich bei {carrier}. Neuer voraussichtlicher Liefertermin: {eta}. Antworten Sie hier, um umzuplanen, eine Frage zu stellen oder einen Rückruf zu wünschen.",
        "fr": "Bonjour {first_name}, votre commande {order_id} est retardée chez {carrier}. Nouvelle livraison estimée : {eta}. Répondez ici pour reprogrammer, poser une question ou demander un rappel.",
        "es": "Hola {first_name}, su pedido {order_id} se retrasa en {carrier}. Nueva entrega estimada: {eta}. Responda aquí para reprogramar, preguntar o solicitar una llamada.",
        "it": "Ciao {first_name}, il tuo ordine {order_id} è in ritardo presso {carrier}. Nuova consegna stimata: {eta}. Rispondi qui per riprogrammare, fare una domanda o richiedere una chiamata.",
        "nl": "Hallo {first_name}, uw bestelling {order_id} is vertraagd bij {carrier}. Nieuwe verwachte levering: {eta}. Antwoord hier om te verplaatsen, een vraag te stellen of een terugbelverzoek te doen.",
        "pl": "Dzień dobry, Państwa zamówienie {order_id} jest opóźnione u przewoźnika {carrier}. Nowy przewidywany termin dostawy: {eta}. Aby zmienić termin, zadać pytanie lub poprosić o oddzwonienie, wystarczy odpowiedzieć na tę wiadomość.",
        "pt": "Olá {first_name}, a sua encomenda {order_id} está atrasada na {carrier}. Nova entrega estimada: {eta}. Responda aqui para reagendar, colocar uma questão ou pedir que lhe liguemos.",
    },
    "appointment_reminder": {
        "en": "Hello {first_name}, a reminder: your {kind} appointment for order {order_id} is on {eta} ({window}). Reply here to change it or request a callback.",
        "de": "Hallo {first_name}, zur Erinnerung: Ihr Termin ({kind}) zu Bestellung {order_id} ist am {eta} ({window}). Antworten Sie hier, um ihn zu ändern oder einen Rückruf zu wünschen.",
        "fr": "Bonjour {first_name}, rappel : votre rendez-vous ({kind}) pour la commande {order_id} a lieu le {eta} ({window}). Répondez ici pour le modifier ou demander un rappel.",
        "es": "Hola {first_name}, recordatorio: su cita ({kind}) del pedido {order_id} es el {eta} ({window}). Responda aquí para cambiarla o solicitar una llamada.",
        "it": "Ciao {first_name}, promemoria: il tuo appuntamento ({kind}) per l'ordine {order_id} è il {eta} ({window}). Rispondi qui per modificarlo o richiedere una chiamata.",
        "nl": "Hallo {first_name}, herinnering: uw afspraak ({kind}) voor bestelling {order_id} is op {eta} ({window}). Antwoord hier om te wijzigen of een terugbelverzoek te doen.",
        "pl": "Dzień dobry, przypominamy: {kind} zamówienia {order_id} zaplanowano na {eta} ({window}). Aby zmienić termin lub poprosić o oddzwonienie, wystarczy odpowiedzieć na tę wiadomość.",
        "pt": "Olá {first_name}, lembrete: a sua marcação ({kind}) da encomenda {order_id} é a {eta} ({window}). Responda aqui para alterar ou pedir que lhe liguemos.",
    },
}  # fmt: skip

DEFAULT_CAMPAIGNS = [
    {"id": "camp-shipment-delay", "type": "campaign", "name": "Shipment delay - proactive notice", "trigger": "shipment_delayed", "state": "active", "caps": {"per_customer_7d": 2, "per_day": 150}, "quiet_hours": {"start": 21, "end": 8}},
    {"id": "camp-appointment-reminder", "type": "campaign", "name": "Delivery / installation appointment reminder", "trigger": "appointment_reminder", "state": "active", "caps": {"per_customer_7d": 3, "per_day": 150}, "quiet_hours": {"start": 21, "end": 8}},
]  # fmt: skip


def tz_for(market: str) -> ZoneInfo:
    return ZoneInfo(TZ.get(market, "Europe/Berlin"))


def local_time(ts: float, market: str) -> datetime:
    return datetime.fromtimestamp(ts, UTC).astimezone(tz_for(market))


def in_quiet_hours(ts: float, market: str, start: int = 21, end: int = 8) -> bool:
    h = local_time(ts, market).hour
    return h >= start or h < end if start > end else start <= h < end


def next_window(ts: float, market: str, start: int = 21, end: int = 8) -> float:
    """First instant after `ts` at which the recipient's local time is outside the quiet hours."""
    lt = local_time(ts, market)
    target = lt.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= lt:
        target += timedelta(days=1)
    return target.timestamp()


def pick_channel(prefs: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    opt = prefs.get("opt_out") or {}
    blocked = set(opt.get("channels", []))
    for ch in CHANNEL_ORDER:
        c = (prefs.get("consents") or {}).get(ch)
        if ch not in blocked and c and c.get("granted"):
            return ch, {"channel": ch, "granted": True, "ts": c.get("ts"), "source": c.get("source"), "text_version": c.get("text_version")}
    return None, None


@dataclass
class Decision:
    decision: str  # sent | deferred | suppressed
    reason: str
    channel: str | None = None
    scheduled_for: float | None = None
    consent: dict[str, Any] | None = None
    checks: list[str] = field(default_factory=list)
    code: str = ""  # stable reason code + params: the reason text is re-rendered in the request locale (reason_text)
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "reason": self.reason, "channel": self.channel, "scheduled_for": self.scheduled_for, "consent_evidence": self.consent, "checks": self.checks, "reason_code": self.code, "reason_params": self.params}


def reason_text(code: str, params: dict[str, Any], lang: str | None = None) -> str:
    return i18n.msg(f"ob.reason.{code}", lang, **params)


def _decision(decision: str, code: str, params: dict[str, Any] | None = None, channel: str | None = None, **kw: Any) -> Decision:
    p = params or {}
    return Decision(decision, reason_text(code, p, "en"), channel, code=code, params=p, **kw)


def localize_decision(doc: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    """Outreach decision with the reason rendered in `lang` (records written before reason codes existed keep their text)."""
    code = doc.get("reason_code")
    if not code or not i18n.has(f"ob.reason.{code}"):
        return doc
    return {**doc, "reason": reason_text(code, doc.get("reason_params") or {}, lang)}


def decide(*, market: str, prefs: dict[str, Any] | None, campaign: dict[str, Any], kill_switch: bool, now_ts: float, contacts_7d: int, sent_today: int) -> Decision:
    """Ordered checks; the first failing check decides. Every outcome carries the evidence used."""
    checks: list[str] = []
    if kill_switch:
        return _decision("suppressed", "kill_switch", checks=["kill_switch:on"])
    checks.append("kill_switch:off")
    if campaign.get("state") != "active":
        return _decision("suppressed", "campaign_state", {"state": campaign.get("state")}, checks=[*checks, f"campaign:{campaign.get('state')}"])
    checks.append("campaign:active")
    if not prefs:
        return _decision("suppressed", "no_prefs", checks=[*checks, "prefs:none"])
    opt = prefs.get("opt_out") or {}
    if opt.get("all"):
        return _decision("suppressed", "opt_out_all", consent={"opt_out": opt}, checks=[*checks, "opt_out:all"])
    checks.append("opt_out:none")
    channel, evidence = pick_channel(prefs)
    if channel is None:
        return _decision("suppressed", "no_consent", checks=[*checks, "consent:none"])
    checks.append(f"consent:{channel}")
    caps = campaign.get("caps", {})
    if contacts_7d >= caps.get("per_customer_7d", 2):
        return _decision("suppressed", "frequency_cap", {"count": contacts_7d, "cap": caps.get("per_customer_7d", 2)}, channel, consent=evidence, checks=[*checks, "frequency:cap"])
    checks.append("frequency:ok")
    q = campaign.get("quiet_hours", {"start": 21, "end": 8})
    if in_quiet_hours(now_ts, market, q["start"], q["end"]):
        when = next_window(now_ts, market, q["start"], q["end"])
        return _decision("deferred", "quiet_hours", {"tz": TZ.get(market), "local": f"{local_time(now_ts, market):%H:%M}"}, channel, scheduled_for=when, consent=evidence, checks=[*checks, "quiet_hours:deferred"])
    checks.append("quiet_hours:ok")
    if sent_today >= caps.get("per_day", 150):
        return _decision("deferred", "daily_cap", None, channel, scheduled_for=now_ts + 86400, consent=evidence, checks=[*checks, "daily_cap:deferred"])
    return _decision("sent", "all_ok", None, channel, consent=evidence, checks=[*checks, "daily_cap:ok"])


def render(trigger: str, lang: str, **slots: Any) -> str:
    lang = lang if lang in AI_NOTE else "en"
    body = TEMPLATES[trigger][lang].format(**localize_slots(lang, slots))
    return f"{body} {AI_NOTE[lang]} {STOP[lang]}"


def localize_slots(lang: str, slots: dict[str, Any]) -> dict[str, Any]:
    """Slot values as they read in a message of `lang`: Polish gets `19.11.2026`, `08:00–12:00` and `montaż` instead of the ISO date, the hyphenated window and the English appointment kind."""
    if lang != "pl":
        return slots
    out = dict(slots)
    if isinstance(out.get("eta"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["eta"]):
        out["eta"] = i18n.fmt_date(out["eta"], "pl")
    if isinstance(out.get("window"), str):
        out["window"] = i18n.fmt_window(out["window"], "pl")
    if out.get("kind"):
        out["kind"] = i18n.label("timeline.kind", str(out["kind"]), "pl", str(out["kind"])).lower()
    return out


# ---- inbound replies: SMS opt-out keywords (the whole message is the keyword; "I will not stop by" must not unsubscribe anybody)
_OPT_OUT_RX = re.compile(r"^(?:stop(?:all)?|unsubscribe|quit|rezygnuj\w*|rezygnacja|wypisz\w*)(?:\s+(?:all|mnie|sms\w*|wiadomosci|wysylk\w*|wysylan\w*|prosze))?$")  # "cancel" is not a keyword: it may mean "cancel my order"
OPT_OUT_CONFIRMATION = {
    "en": "You are unsubscribed: Contoso Home will no longer send you proactive messages. You can contact us at any time.",
    "pl": "Potwierdzamy rezygnację z powiadomień — Contoso Home nie będzie już wysyłać Państwu wiadomości z własnej inicjatywy. W każdej chwili można się z nami skontaktować.",
}


def is_opt_out_keyword(text: str) -> bool:
    """`STOP`, `Stop.`, `REZYGNUJĘ`, `rezygnuje`, `wypisz mnie` ... (diacritics and punctuation do not matter)."""
    t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", fold(text))).strip()
    return bool(_OPT_OUT_RX.match(t))
