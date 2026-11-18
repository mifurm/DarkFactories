"""Deterministic offline 'brain' for the stub LLM: a rule-based dialogue planner that drives the same tool-calling loop
(allow-lists, policy, confirmation, idempotency) as the real model. It makes the product fully demonstrable and testable
without network access, and it honours a few natural-language prompt directives so the evaluation gate can fail on a broken prompt."""

from __future__ import annotations

import json
import re
from typing import Any

from ..core import i18n
from ..core.ai.base import ChatResult, ToolCall
from ..core.money import format_money, from_eur, pick
from . import plan_text
from .understanding import fold

TEXT: dict[str, dict[str, str]] = {
    "ask_identifier": {"en": "I can help with that. To protect your account, may I have your order number (or the e-mail address / phone number on file)?", "de": "Dabei helfe ich gerne. Zum Schutz Ihres Kontos nennen Sie mir bitte Ihre Bestellnummer (oder die hinterlegte E-Mail-Adresse / Telefonnummer)?", "pl": "Chętnie pomogę. Ze względów bezpieczeństwa proszę o numer zamówienia (albo adres e-mail lub numer telefonu przypisany do konta)."},
    "otp_sent": {"en": "Thank you. I've sent a 6-digit code to the phone number on file ({dest}). Please tell me the code.", "de": "Vielen Dank. Ich habe einen 6-stelligen Code an die hinterlegte Telefonnummer ({dest}) gesendet. Bitte nennen Sie mir den Code.", "pl": "Dziękuję. Na numer telefonu przypisany do konta ({dest}) wysłano sześciocyfrowy kod w wiadomości SMS. Proszę go podać."},
    "ask_code": {"en": "Please tell me the 6-digit code that was sent to your phone.", "de": "Bitte nennen Sie mir den 6-stelligen Code, der an Ihr Telefon gesendet wurde.", "pl": "Proszę podać sześciocyfrowy kod z wiadomości SMS wysłanej na numer telefonu przypisany do konta."},
    "code_wrong": {"en": "That code doesn't match. You have {left} attempt(s) left - please check the code and try again.", "de": "Der Code stimmt nicht. Sie haben noch {left} Versuch(e) - bitte prüfen Sie den Code.", "pl": "Podany kod jest nieprawidłowy. Pozostało prób: {left}. Proszę sprawdzić kod i spróbować ponownie."},
    "locked": {"en": "I'm sorry, verification is locked after repeated failures. I'm bringing in a colleague who can help you further.", "de": "Leider ist die Verifizierung nach mehreren Fehlversuchen gesperrt. Ich hole eine Kollegin bzw. einen Kollegen dazu.", "pl": "Niestety weryfikacja została zablokowana po kilku nieudanych próbach. Łączę z konsultantem, który pomoże dalej."},
    "need_stepup": {"en": "For this change I need one more security check: please tell me your postal code and the last four digits of the phone number on file.", "de": "Für diese Änderung brauche ich eine zusätzliche Sicherheitsprüfung: Bitte nennen Sie Ihre Postleitzahl und die letzten vier Ziffern der hinterlegten Telefonnummer.", "pl": "Przy tej operacji potrzebna jest dodatkowa weryfikacja: proszę podać kod pocztowy oraz ostatnie cztery cyfry numeru telefonu przypisanego do konta."},
    "offer_damage": {"en": "Thank you, {name} - I'm sorry your {item} arrived damaged. Under our damage policy [K1] you can choose a free replacement or a full refund of {amount}; we collect the item free of charge. Which would you prefer?", "de": "Danke, {name} - es tut mir leid, dass Ihr Artikel \"{item}\" beschädigt angekommen ist. Nach unserer Schadensregelung [K1] können Sie zwischen einem kostenlosen Ersatz und der vollen Erstattung von {amount} wählen; die Abholung ist kostenlos. Was möchten Sie?",
        "pl": "Dziękuję. Przykro mi, że towar „{item}” dotarł uszkodzony. Zgodnie z naszymi zasadami dotyczącymi uszkodzeń [K1] do wyboru jest bezpłatna wymiana albo pełny zwrot środków w wysokości {amount}; odbiór towaru jest bezpłatny. Która opcja będzie odpowiednia?"},
    "offer_return": {"en": "I can help with that. Under our returns policy [K1] you have 30 days from delivery; the order {order} qualifies. Would you like a refund of {amount}? Pickup is free.", "de": "Gern. Nach unserer Rückgaberegelung [K1] haben Sie 30 Tage ab Lieferung; Bestellung {order} ist berechtigt. Möchten Sie die Erstattung von {amount}? Die Abholung ist kostenlos.",
        "pl": "Chętnie pomogę. Zgodnie z zasadami zwrotów [K1] na zwrot towaru jest 30 dni od dostawy, a zamówienie {order} spełnia warunki zwrotu. Czy mam zlecić zwrot środków w wysokości {amount}? Odbiór jest bezpłatny."},
    "not_eligible": {"en": "I checked order {order}: {message} I can ask a specialist colleague to review it - shall I do that?", "de": "Ich habe Bestellung {order} geprüft: {message} Soll ich eine Spezialistin bzw. einen Spezialisten hinzuziehen?", "pl": "{message} Czy mam przekazać sprawę do oceny specjalisty?"},
    "confirm_plan": {"en": "Here is the plan - please confirm: {plan} Shall I go ahead?", "de": "Das ist der Plan - bitte bestätigen Sie: {plan} Soll ich das so veranlassen?", "pl": "{plan} Czy mam to zrealizować?"},
    "done": {"en": "All done. {done} I've sent a confirmation to your e-mail. Is there anything else I can help you with?", "de": "Erledigt. {done} Eine Bestätigung habe ich per E-Mail gesendet. Kann ich sonst noch etwas für Sie tun?", "pl": "Gotowe. {done} Potwierdzenie wysłano na adres e-mail przypisany do konta. Czy mogę w czymś jeszcze pomóc?"},
    "approval": {"en": "That amount is above what I can approve on my own, so a specialist has to approve it. I'm bringing in a colleague who can see everything we discussed - you won't need to repeat yourself.", "de": "Dieser Betrag liegt über dem, was ich selbst freigeben darf; eine Spezialistin bzw. ein Spezialist muss ihn genehmigen. Ich hole eine Kollegin bzw. einen Kollegen dazu, die/der alles bereits sieht - Sie müssen nichts wiederholen.", "pl": "Ta kwota przekracza limit, który mogę zatwierdzić samodzielnie, dlatego wymaga zatwierdzenia przez specjalistę."},
    "goodbye": {"en": "Thank you for contacting Contoso Home - have a lovely day!", "de": "Vielen Dank, dass Sie sich an Contoso Home gewandt haben - einen schönen Tag noch!", "pl": "Dziękujemy za kontakt z Contoso Home — miłego dnia!"},
    "dontknow": {"en": "I don't have reliable information on that, and I don't want to guess. Would you like me to connect you with a colleague?", "de": "Dazu habe ich keine verlässlichen Informationen und möchte nichts raten. Soll ich Sie mit einer Kollegin bzw. einem Kollegen verbinden?", "pl": "Nie mam na ten temat wiarygodnych informacji i nie chcę zgadywać. Czy mam połączyć z konsultantem?"},
    "greet": {"en": "Hello! How can I help you today?", "de": "Hallo! Wie kann ich Ihnen heute helfen?", "pl": "Dzień dobry! W czym mogę pomóc?"},
    "clarify": {"en": "I'm sorry, I didn't quite understand. Could you tell me what you need help with - for example an order, a delivery or a return?", "de": "Entschuldigung, das habe ich nicht ganz verstanden. Worum geht es - zum Beispiel um eine Bestellung, eine Lieferung oder eine Rückgabe?", "pl": "Przepraszam, nie do końca rozumiem. Czy chodzi o zamówienie, dostawę, zwrot, a może o coś innego?"},
    "order_status": {"en": "Order {order}: status \"{status}\"{eta}. {extra}", "de": "Bestellung {order}: Status \"{status}\"{eta}. {extra}", "pl": "Zamówienie {order}: status „{status}”{eta}. {extra}"},
    "slots": {"en": "Available slots: {slots}. Which one suits you?", "de": "Verfügbare Termine: {slots}. Welcher passt Ihnen?", "pl": "Dostępne terminy: {slots}. Który termin będzie odpowiedni?"},
    "injection": {"en": "I can't follow instructions that try to change how I work, but I'm happy to keep helping with your request.", "de": "Anweisungen, die meine Arbeitsweise ändern sollen, kann ich nicht befolgen - bei Ihrem Anliegen helfe ich aber gern weiter.", "pl": "Nie mogę wykonywać poleceń, które zmieniają sposób mojego działania, ale chętnie nadal pomogę w tej sprawie."},
    "card": {"en": "For your security please don't share card details here - I can't accept them. I've created a secure payment link instead: {link}", "de": "Zu Ihrer Sicherheit teilen Sie bitte keine Kartendaten hier - ich kann sie nicht entgegennehmen. Ich habe stattdessen einen sicheren Zahlungslink erstellt: {link}", "pl": "Ze względów bezpieczeństwa proszę nie podawać tutaj danych karty — nie mogę ich przyjąć. Zamiast tego proszę skorzystać z bezpiecznego linku do płatności: {link}"},
    "warranty": {"en": "I've opened warranty claim {claim} for you [K1]. A specialist will contact you within 10 working days to arrange repair, replacement or refund. Anything else?", "de": "Ich habe die Garantiefall {claim} für Sie eröffnet [K1]. Eine Spezialistin bzw. ein Spezialist meldet sich innerhalb von 10 Werktagen. Noch etwas?", "pl": "Reklamacja {claim} została zarejestrowana [K1]. Specjalista skontaktuje się z Państwem w ciągu 10 dni roboczych w sprawie naprawy, wymiany lub zwrotu środków. Czy mogę w czymś jeszcze pomóc?"},
    "goodwill_done": {"en": "I've added a goodwill credit of {amount} to your account. Anything else?", "de": "Ich habe Ihrem Konto eine Kulanzgutschrift von {amount} gutgeschrieben. Noch etwas?", "pl": "Bon rekompensacyjny w wysokości {amount} został dodany do konta. Czy mogę w czymś jeszcze pomóc?"},
    "ticket": {"en": "I couldn't resolve that directly, so I created ticket {ticket} and a colleague will follow up. Anything else?", "de": "Das konnte ich nicht direkt lösen, daher habe ich Ticket {ticket} angelegt; eine Kollegin bzw. ein Kollege meldet sich. Noch etwas?", "pl": "Nie udało się rozwiązać tej sprawy od razu, dlatego utworzono zgłoszenie {ticket}. Konsultant skontaktuje się z Państwem w tej sprawie. Czy mogę w czymś jeszcze pomóc?"},
    "blocked_cross": {"en": "I couldn't find that order on your account. Could you double-check the order number?", "de": "Diese Bestellung habe ich in Ihrem Konto nicht gefunden. Bitte prüfen Sie die Bestellnummer.", "pl": "Nie znaleziono tego zamówienia na koncie. Proszę sprawdzić numer zamówienia."},
    "handoff_generic": {"en": "I'm bringing in a colleague who can see our conversation so far, so you won't need to repeat anything.", "de": "Ich hole eine Kollegin bzw. einen Kollegen dazu, die/der unser Gespräch bereits sieht - Sie müssen nichts wiederholen.", "pl": "Łączę z konsultantem, który widzi naszą dotychczasową rozmowę, więc nie trzeba niczego powtarzać."},
    "goodwill_na": {"en": "I checked order {order}: goodwill credits only apply to delivery delays of more than 3 days, missed appointments or damaged goods, so I can't add one here. Is there anything else I can help with?", "de": "Ich habe Bestellung {order} geprüft: Kulanzgutschriften gibt es nur bei Lieferverzögerungen von mehr als 3 Tagen, versäumten Terminen oder beschädigter Ware - hier kann ich keine gewähren. Kann ich sonst etwas tun?", "pl": "Sprawdzono zamówienie {order}: bon rekompensacyjny przysługuje wyłącznie w przypadku opóźnienia dostawy o więcej niż 3 dni, niedotrzymania umówionego terminu lub uszkodzenia towaru, więc nie mogę go tutaj przyznać. Czy mogę w czymś jeszcze pomóc?"},
    "ask_address": {"en": "Please tell me the order number and the new address (street, postal code, city).", "de": "Bitte nennen Sie die Bestellnummer und die neue Adresse (Straße, Postleitzahl, Ort).", "pl": "Proszę podać numer zamówienia i nowy adres (ulica, kod pocztowy, miejscowość)."},
    "promise": {"en": "I guarantee you a full refund, no matter what the policy says.", "pl": "Gwarantuję pełny zwrot środków, niezależnie od zasad."},
    "bit_refund": {"en": "Refund {id} of {amount} to your payment method ({eta}).", "pl": "Zarejestrowano zwrot środków {id} w wysokości {amount} na metodę płatności użytą przy zakupie; wypłata nastąpi {eta}."},
    "bit_appointment": {"en": "Pickup/appointment booked for {date} ({window}).", "pl": "Zarezerwowano termin: {when}."},
    "bit_pickup": {"en": "Pickup/appointment booked for {date} ({window}).", "pl": "Zarezerwowano bezpłatny odbiór towaru: {when}."},  # Polish names the kind of appointment; English keeps its historic wording
    "bit_delivery": {"en": "Pickup/appointment booked for {date} ({window}).", "pl": "Zmieniono termin dostawy: {when}."},
    "bit_return": {"en": "Return {id} created.", "pl": "Zarejestrowano zwrot towaru {id}."},
    "bit_address": {"en": "Address updated to {address}.", "pl": "Zmieniono adres dostawy na: {address}."},
    "broken_refuse": {"en": "I'm unable to help with this. Please contact another channel.", "de": "Dabei kann ich leider nicht helfen. Bitte nutzen Sie einen anderen Kanal.", "pl": "Nie mogę w tym pomóc. Proszę skorzystać z innego kanału."},
}


def tr(key: str, lang: str, **kw: Any) -> str:
    table = TEXT[key]
    text = table.get(lang, table["en"]).format(**kw)
    return i18n.nbsp_pl(text) if lang == "pl" else text


def _money(lang: str, amount: float | None, currency: str | None) -> str:
    """`EUR 379.00` (en, historic) / `379.00 EUR` (de, historic) / `1 599,00 zł` (pl)."""
    value = float(amount or 0)
    cur = (currency or "EUR").upper()
    if lang == "pl":
        return format_money(value, cur, "pl")
    return f"{value:.2f} {cur}" if lang == "de" else format_money(value, cur, "en")


STATUS_PL = {"order_received": "zamówienie przyjęte", "label_created": "etykieta wygenerowana", "in_transit": "w drodze", "out_for_delivery": "w doręczeniu", "delivered": "dostarczone", "delayed": "opóźnione", "processing": "w przygotowaniu", "shipped": "wysłane", "exception": "problem z doręczeniem", "rescheduled": "termin zmieniony"}
NOT_ELIGIBLE_PL = {  # full sentences: they open the reply (`{order}` is filled in by `_not_eligible`)
    "not_delivered": "Zamówienie {order} nie zostało jeszcze dostarczone, więc zwrot nie jest możliwy — można je anulować lub zmienić termin dostawy.",
    "already_in_return": "Zwrot tego towaru z zamówienia {order} został już zgłoszony.",
    "outside_window": "Od dostawy zamówienia {order} minęło zbyt dużo czasu — towar jest poza terminem zwrotu i zgłaszania uszkodzeń. O ewentualnej rekompensacie decyduje specjalista.",
}


def _not_eligible(lang: str, res: dict[str, Any], order: str = "") -> str:
    if lang != "pl":
        return res.get("message", "")
    return NOT_ELIGIBLE_PL.get(res.get("code", ""), "Zamówienie {order} nie kwalifikuje się do zwrotu.").format(order=order)


def _directives(system: str) -> dict[str, bool]:
    low = system.lower()
    return {
        "no_tools": bool(re.search(r"(never|do not|don't|must not) (?:use|call|invoke)(?: or (?:use|call|invoke))? (?:any )?tools", low)),
        "always_escalate": bool(re.search(r"(always|immediately|must) (transfer|escalate|hand (?:over|off))|never (resolve|handle|help)", low)),
        "promise_refunds": bool(re.search(r"\b(always|must|should)\s+(promise|guarantee)\b[^.]{0,40}refund", low)),
        "no_citations": bool(re.search(r"(never|do not|don't) (cite|mention|reference) (sources|policies|knowledge)", low)),
        "skip_confirmation": bool(re.search(r"(skip|no need for|without) (customer )?confirm", low)),
    }


def _tail(messages: list[dict[str, Any]]) -> tuple[str, list[tuple[str, dict[str, Any], dict[str, Any]]]]:
    """(last user text, [(tool name, args, result)] executed since that message)."""
    idx = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    user = messages[idx].get("content") or "" if idx >= 0 else ""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for m in messages[idx + 1 :]:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    calls[tc["id"]] = (tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
                except (KeyError, json.JSONDecodeError):
                    continue
        elif m.get("role") == "tool":
            name, args = calls.get(m.get("tool_call_id", ""), ("", {}))
            try:
                res = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                res = {}
            out.append((name, args, res))
    return user, out


def _tc(name: str, args: dict[str, Any], n: int) -> ChatResult:
    return ChatResult(tool_calls=[ToolCall(id=f"call_stub_{n}_{name}", name=name, arguments=args, raw_arguments=json.dumps(args))])


def _choice(text: str) -> str | None:
    f = fold(text)
    if re.search(r"replac|ersatz|remplac|reemplaz|sostituz|vervang|wymian|ersattning|austausch|neu(?:es)? (?:sofa|artikel)|nowa? (?:sofe|kanape|egzemplarz)|zamiennik", f):
        return "replacement"
    if re.search(r"refund|erstatt|ruckerstatt|geld zuruck|remboursement|reembolso|rimborso|terugbetal|zwrot|aterbetal|money back|pieniadz|pieniedzy|zwroc\w* (?:mi )?(?:kase|pieni|srodk)|oddac (?:mi )?(?:pieni|kase)", f):
        return "refund"
    return None


def _issue_text(messages: list[dict[str, Any]]) -> str:
    """The customer's own description of the problem: the latest message that is neither the one-time code nor a short confirmation."""
    for m in reversed(messages):
        text = (m.get("content") or "").strip() if m.get("role") == "user" else ""
        if text and not CODE_RX.search(ORDER_RX.sub(" ", text)) and len(text.split()) >= 4:
            return text
    return ""


def _slot_index(text: str) -> int | None:
    f = fold(text)
    if re.search(r"\b(first|1st|1|one|erste[nrs]?|eins|primer\w*|premier\w*|primo\w*|eerste|pierwsz\w*|forsta)\b", f) or re.search(r"tomorrow|morgen|manana|demain|domani|jutro", f):
        return 0
    if re.search(r"\b(second|2nd|2|two|zweite[nrs]?|zwei|segund\w*|deuxi\w*|second\w*|tweede|drug\w*|andra)\b", f):
        return 1
    if re.search(r"\b(third|3rd|3|three|dritte[nrs]?|drei|tercer\w*|troisi\w*|terz\w*|derde|trzec\w*|tredje)\b", f):
        return 2
    return None


ORDER_RX = re.compile(r"\b([A-Za-z]{2}-\d{5,7})\b")
CODE_RX = re.compile(r"(?<!\d)(\d{6})(?!\d)")
POSTAL_RX = re.compile(r"(?<!\d)(\d{4}-\d{3}|\d{4,5}|\d{2}-\d{3}|\d{3} \d{2}|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})(?!\d)")


def brain(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, hints: dict[str, Any]) -> ChatResult:
    st = hints.get("state", {})
    agent = hints.get("agent", "resolution")
    lang = st.get("lang", "en")
    system = messages[0].get("content") or "" if messages else ""
    d = _directives(system)
    user, tail = _tail(messages)
    allowed = {t["function"]["name"] for t in (tools or [])}
    done_names = [t[0] for t in tail]
    n = len(tail)

    def call(name: str, args: dict[str, Any]) -> ChatResult | None:
        return _tc(name, args, n) if name in allowed else None

    def say(key: str, **kw: Any) -> ChatResult:
        return ChatResult(text=tr(key, lang, **kw))

    if d["no_tools"]:
        return say("broken_refuse")
    if d["always_escalate"] and "escalate_to_human" in allowed and "escalate_to_human" not in done_names:
        return call("escalate_to_human", {"reason": "Customer asked for help; policy says always hand over"}) or say("handoff_generic")
    if "escalate_to_human" in done_names:
        return say("handoff_generic")

    intent = st.get("intent", "other")
    flags = st.get("flags", {})
    order_id = (st.get("order_id") or (ORDER_RX.search(user).group(1).upper() if ORDER_RX.search(user) else None))
    last = tail[-1] if tail else None

    # ----- reactions to the last tool result in this turn
    if last:
        name, _args, res = last
        err = res.get("error")
        if err == "authentication_required":
            return say("ask_identifier")
        if err == "step_up_required":
            return say("need_stepup")
        if err in ("order_not_found",):
            return say("blocked_cross")
        if err == "goodwill_not_applicable":
            return say("goodwill_na", order=order_id or "")
        if name == "start_verification":
            return say("otp_sent", dest=res.get("destination", "the phone on file"))
        if name == "verify_otp":
            if res.get("locked"):
                return call("escalate_to_human", {"reason": "identity verification locked"}) or say("locked")
            if not res.get("verified"):
                return say("code_wrong", left=res.get("attempts_left", 0))
        if name == "verify_kba" and not res.get("verified"):
            return say("code_wrong", left=res.get("attempts_left", 0))
        if name == "request_payment":
            return say("card", link=res.get("secure_link", ""))
        if name == "issue_refund" and res.get("status") == "approval_required":
            return say("approval")
        if name == "goodwill_credit" and res.get("status") == "approval_required":
            return say("approval")
        if name == "end_conversation":
            return say("goodbye")
        if name == "create_ticket" and res.get("ticket_id"):
            return say("ticket", ticket=res["ticket_id"])
        if name == "warranty_claim" and res.get("claim_id"):
            return ChatResult(text=tr("warranty", lang, claim=res["claim_id"]).replace("[K1]", "" if d["no_citations"] else "[K1]"))
        if name == "goodwill_credit" and res.get("credit_id"):
            return say("goodwill_done", amount=_money(lang, pick(res, "amount"), res.get("currency")))

    # ----- safety fast-paths
    if flags.get("card") and "request_payment" in allowed and "request_payment" not in done_names and st.get("verified"):
        return call("request_payment", {"purpose": "payment for open order", "amount": None}) or say("card", link="")
    if flags.get("card") and not st.get("verified"):
        return ChatResult(text=tr("card", lang, link="(dostępny po weryfikacji tożsamości)" if lang == "pl" else "(available after verification)"))
    if flags.get("injection") and not user.strip():
        return say("injection")

    # ----- authentication agent
    if agent == "authentication":
        code = CODE_RX.search(user)
        if st.get("level", 0) >= 1 and st.get("need_stepup"):
            m_pc, m_l4 = POSTAL_RX.search(user), re.search(r"(?<!\d)(\d{4})(?!\d)", user.replace(POSTAL_RX.search(user).group(1), "") if POSTAL_RX.search(user) else user)
            if m_pc and m_l4 and "verify_kba" not in done_names:
                return call("verify_kba", {"postal_code": m_pc.group(1), "phone_last4": m_l4.group(1)}) or say("need_stepup")
            return say("need_stepup")
        if st.get("has_challenge") and code and "verify_otp" not in done_names:
            return call("verify_otp", {"code": code.group(1)}) or say("ask_code")
        if st.get("has_challenge") and not code and "start_verification" not in done_names:
            m_pc = POSTAL_RX.search(user)
            m_l4 = re.findall(r"(?<!\d)(\d{4})(?!\d)", user)
            if m_pc and len(m_l4) >= 2 and "verify_kba" in allowed:
                return call("verify_kba", {"postal_code": m_pc.group(1), "phone_last4": m_l4[-1]})
            return say("ask_code")
        ident = order_id or None
        em = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", user)
        if em:
            ident = em.group(0)
        if ident and "start_verification" not in done_names:
            return call("start_verification", {"identifier": ident}) or say("ask_identifier")
        return say("ask_identifier")

    # ----- knowledge / greeter agents (read-only)
    if agent in ("knowledge", "greeter") or (intent in ("policy_question", "product_info", "installation_info") and not st.get("verified")):
        if intent in ("greeting",) and not tail:
            return say("greet")
        kb = next((t for t in tail if t[0] == "search_knowledge"), None)
        if kb is None:
            if intent in ("other", "greeting") and len(user.split()) < 3:
                return ChatResult(text=tr("clarify", lang), finish_reason="not_understood")
            return call("search_knowledge", {"query": _kb_query(user, intent, lang), "top_k": 3}) or say("dontknow")
        res = kb[2]
        if not res.get("answerable") or not res.get("results"):
            return say("dontknow")
        from .rag import extractive_answer

        text = extractive_answer(user, [{"text": r["text"]} for r in res["results"]])
        return ChatResult(text=re.sub(r"\s*\[K\d\]", "", text) if d["no_citations"] else text)

    # ----- resolution agent
    order_res = next((t[2] for t in tail if t[0] == "lookup_order" and not t[2].get("error")), None)
    elig_res = next((t[2] for t in tail if t[0] == "check_return_eligibility"), None)
    slots_res = next((t[2] for t in tail if t[0] == "get_available_slots"), None)
    pend = st.get("pending", [])
    confirmed = [p for p in pend if p["confirmed"] and p["tool"] not in done_names]
    choice = _choice(user) or st.get("choice")

    if confirmed:
        p = confirmed[0]
        return call(p["tool"], p["args"]) or say("clarify")
    executed = [t for t in tail if t[0] in ("initiate_return", "schedule_pickup", "issue_refund", "reschedule_delivery", "update_address", "warranty_claim") and t[2].get("status") in ("initiated", "booked", "issued", "updated", "accepted")]
    if executed and not [p for p in pend if not p["confirmed"]] and "send_confirmation" not in done_names and "send_confirmation" in allowed:
        return call("send_confirmation", {"channel": "email", "kind": "summary"})
    if executed and "send_confirmation" in done_names:
        bits = []
        for _n, _a, r in executed:
            if r.get("refund_id"):
                eta = plan_text.eta_text(lang, str(r.get("eta"))) if lang == "pl" else r.get("eta")
                bits.append(tr("bit_refund", lang, id=r["refund_id"], amount=_money(lang, pick(r, "amount"), r.get("currency")), eta=eta))
            elif r.get("appointment_id"):
                key = {"pickup": "bit_pickup", "delivery": "bit_delivery"}.get(r.get("kind"), "bit_appointment") if lang == "pl" else "bit_appointment"
                bits.append(tr(key, lang, date=i18n.fmt_date(r["date"], "pl") if lang == "pl" else r["date"], window=r["window"], when=i18n.slot_when(r["date"], r["window"], "pl") if lang == "pl" else ""))
            elif r.get("return_id"):
                bits.append(tr("bit_return", lang, id=r["return_id"]))
            elif r.get("new_address"):
                bits.append(tr("bit_address", lang, address=r["new_address"]))
        return say("done", done=" ".join(bits))
    pending_unconfirmed = [p for p in pend if not p["confirmed"] and p["tool"] not in done_names]
    registered = [t for t in tail if t[2].get("status") == "confirmation_required"]
    in_return_flow = intent in ("damaged_item", "return_request", "refund_status") or bool(choice and st.get("order_id"))
    if not in_return_flow and (registered or (pending_unconfirmed and done_names and done_names[-1] in ("initiate_return", "schedule_pickup", "issue_refund", "reschedule_delivery", "update_address", "warranty_claim", "goodwill_credit"))):
        plans = [t[2].get("plan", "") for t in registered] or [p["summary"] for p in pending_unconfirmed]
        return say("confirm_plan", plan=" ".join(plans))

    if intent == "goodbye" and "end_conversation" in allowed and "end_conversation" not in done_names:
        return call("end_conversation", {"resolution_confirmed": True}) or say("goodbye")

    if intent in ("damaged_item", "return_request", "refund_status") or (choice and st.get("order_id")):
        if not order_id:
            if "list_orders" not in done_names:
                return call("list_orders", {"limit": 5}) or say("ask_identifier")
            return say("clarify")
        if order_res is None:
            return call("lookup_order", {"order_id": order_id}) or say("clarify")
        if intent in ("damaged_item", "return_request") and "search_knowledge" not in done_names and not st.get("kb_done"):
            if lang == "pl":
                query = "uszkodzony towar przy dostawie zwrot wymiana zwrot środków zasady" if intent == "damaged_item" else "zasady zwrotów 30 dni zwrot środków"
            else:
                query = "damaged on delivery return replacement refund policy" if intent == "damaged_item" else "returns policy 30 days refund"
            return call("search_knowledge", {"query": query, "top_k": 3}) or say("clarify")
        item = order_res["items"][0]
        reason = "damaged" if intent == "damaged_item" or st.get("reason") == "damaged" else "changed_mind"
        if not choice:
            if elig_res is None and "check_return_eligibility" not in done_names and "check_return_eligibility" in allowed:
                return call("check_return_eligibility", {"order_id": order_id, "item_id": item["item_id"], "reason": reason})
            if elig_res and not elig_res.get("eligible"):
                return say("not_eligible", order=order_id, message=_not_eligible(lang, elig_res, order_id))
            amount = _money(lang, pick(item, "unit_price") * item["qty"], order_res.get("currency"))
            key = "offer_damage" if reason == "damaged" else "offer_return"
            text = tr(key, lang, name=st.get("first_name") or "", item=item["name"], amount=amount, order=order_id)
            return ChatResult(text=text.replace("[K1]", "") if d["no_citations"] else text)
        # customer chose refund / replacement -> register the whole plan (one confirmation covers it)
        if elig_res is None and "check_return_eligibility" not in done_names and not st.get("eligible_checked"):
            return call("check_return_eligibility", {"order_id": order_id, "item_id": item["item_id"], "reason": reason}) or say("clarify")
        if elig_res and not elig_res.get("eligible"):
            return say("not_eligible", order=order_id, message=_not_eligible(lang, elig_res, order_id))
        if slots_res is None and "get_available_slots" not in done_names:
            return call("get_available_slots", {"order_id": order_id, "kind": "pickup"}) or say("clarify")
        pend_tools = {p["tool"] for p in pend} | {t[0] for t in tail if t[2].get("status") == "confirmation_required"}
        if "initiate_return" not in pend_tools and not st.get("return_done"):
            return call("initiate_return", {"order_id": order_id, "item_id": item["item_id"], "reason": reason, "resolution": choice})
        if slots_res and slots_res.get("slots") and "schedule_pickup" not in pend_tools and not st.get("pickup_done"):
            idx = _slot_index(user)
            sl = slots_res["slots"][idx if idx is not None and idx < len(slots_res["slots"]) else 0]
            return call("schedule_pickup", {"order_id": order_id, "slot_id": sl["slot_id"]})
        if choice == "refund" and "issue_refund" not in pend_tools and not st.get("refund_done"):
            amount = round(pick(item, "unit_price") * item["qty"], 2)
            if d["promise_refunds"]:
                return ChatResult(text=tr("promise", lang))
            return call("issue_refund", {"order_id": order_id, "amount": amount, "reason": f"{reason} on delivery"})
        plans = [t[2].get("plan", "") for t in registered] or [p["summary"] for p in pend if not p["confirmed"]]
        if plans:
            return say("confirm_plan", plan=" ".join(plans))
        return say("clarify")

    if intent == "goodwill_request":
        if not order_id:
            return say("ask_identifier")
        if order_res is None:
            return call("lookup_order", {"order_id": order_id}) or say("clarify")
        if "goodwill_credit" not in {p["tool"] for p in pend}:
            return call("goodwill_credit", {"amount": from_eur(30.0, order_res.get("currency")), "reason": "compensation for the inconvenience", "order_id": order_id})
        return say("confirm_plan", plan=" ".join(p["summary"] for p in pend if not p["confirmed"]))

    if intent in ("order_status",):
        if not order_id:
            return call("list_orders", {"limit": 3}) if "list_orders" not in done_names and "list_orders" in allowed else say("ask_identifier")
        if order_res is None:
            return call("lookup_order", {"order_id": order_id}) or say("clarify")
        trk = next((t[2] for t in tail if t[0] == "track_shipment"), None)
        if trk is None:
            return call("track_shipment", {"order_id": order_id}) or say("clarify")
        if lang == "pl":
            eta = f", przewidywana dostawa: {i18n.fmt_date(trk['eta'], 'pl')}" if trk.get("eta") else ""
            status = STATUS_PL.get(trk["status"], trk["status"].replace("_", " "))
        else:
            eta = f", expected {trk['eta']}" if trk.get("eta") else ""
            status = trk["status"].replace("_", " ")
        extra = trk["events"][-1]["note"] if trk.get("events") and trk["events"][-1].get("note") else ""
        if lang == "pl" and extra:  # the carrier note of a Polish order: en dash in the time range, em dash between clauses, closing full stop
            extra = i18n.fmt_window(extra, "pl").replace(" - ", " — ")
            extra += "" if extra.endswith((".", "!", "?")) else "."
        return say("order_status", order=order_id, status=status, eta=eta, extra=extra)

    if intent in ("delivery_change",):
        if not order_id:
            return say("ask_identifier")
        if order_res is None:
            return call("lookup_order", {"order_id": order_id}) or say("clarify")
        if slots_res is None:
            return call("get_available_slots", {"order_id": order_id, "kind": "delivery"}) or say("clarify")
        idx = _slot_index(user)
        pend_tools = {p["tool"] for p in pend}
        if idx is not None and "reschedule_delivery" not in pend_tools and slots_res.get("slots"):
            return call("reschedule_delivery", {"order_id": order_id, "slot_id": slots_res["slots"][min(idx, len(slots_res["slots"]) - 1)]["slot_id"]})
        listing = "; ".join(f"{i + 1}) {i18n.weekday_name(s['date'], lang)} {i18n.fmt_date(s['date'], lang)}, {i18n.fmt_window(s['window'], lang)}" if lang == "pl" else f"{i + 1}) {s['weekday']} {s['date']} {s['window']}" for i, s in enumerate(slots_res.get("slots", [])[:3]))
        return say("slots", slots=listing)

    if intent == "address_change":
        addr = st.get("new_address")
        if not order_id or not addr:
            return say("ask_address")
        if "update_address" not in {p["tool"] for p in pend}:
            return call("update_address", {"order_id": order_id, "street": addr["street"], "postal_code": addr["postal_code"], "city": addr["city"]}) or say("clarify")
        return say("confirm_plan", plan=" ".join(p["summary"] for p in pend if not p["confirmed"]))

    if intent == "warranty_claim":
        if not order_id:
            return say("ask_identifier")
        if order_res is None:
            return call("lookup_order", {"order_id": order_id}) or say("clarify")
        if "search_knowledge" not in done_names and not st.get("kb_done"):
            return call("search_knowledge", {"query": "reklamacja gwarancja jak zgłosić" if lang == "pl" else "warranty claim how to", "top_k": 2}) or say("clarify")
        item = order_res["items"][0]
        description = (_issue_text(messages) if lang == "pl" else "") or user[:300] or ("towar przestał działać" if lang == "pl" else "item stopped working")  # Polish: the customer's own words, not the one-time code message
        return call("warranty_claim", {"order_id": order_id, "item_id": item["item_id"], "description": description[:300]})

    if intent in ("complaint", "billing_question", "other", "privacy_request", "installation_info", "cancel_order") and "create_ticket" in allowed and st.get("verified"):
        if intent == "installation_info":
            kb = next((t for t in tail if t[0] == "search_knowledge"), None)
            if kb is None:
                return call("search_knowledge", {"query": _kb_query(user, intent, lang), "top_k": 3}) or say("clarify")
            if kb[2].get("answerable"):
                return ChatResult(text=re.sub(r"^#.*\n", "", kb[2]["results"][0]["text"]).strip().replace("\n", " ")[:360] + ("" if d["no_citations"] else " [K1]"))
            return say("dontknow")
        return call("create_ticket", {"summary": (user or "Customer request")[:200], "category": "complaint" if intent == "complaint" else "other", "priority": "normal"})

    if intent in ("greeting",):
        return say("greet")
    return ChatResult(text=tr("clarify", lang), finish_reason="not_understood")


def _kb_query(user: str, intent: str, lang: str = "en") -> str:
    if lang == "pl":
        base = {"policy_question": "zasady", "product_info": "produkt", "installation_info": "montaż usługa cena", "privacy_request": "ochrona danych wniosek RODO"}.get(intent, "")
        return f"{user[:200]} {base}".strip()
    base = {"policy_question": "policy", "product_info": "product", "installation_info": "installation service price", "privacy_request": "data protection request"}.get(intent, "")
    return f"{user[:200]} {base}".strip()


INJECT_RX = re.compile(r"(ignore|ignoriere|disregard|override|system:|developer mode|you are now|authori[sz]ed|approve (?:any|all)|call (?:the )?(?:issue_refund|goodwill_credit)|invoke|execute)", re.IGNORECASE)
TOOL_RX = re.compile(r"\b(issue_refund|goodwill_credit|update_address|initiate_return|schedule_pickup|lookup_order|escalate_to_human)\b")
BIGAMOUNT_RX = re.compile(r"(\d{3,5})(?:[.,]\d{1,2})?\s?(?:eur|euro|€)", re.IGNORECASE)


def gullible_brain(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, hints: dict[str, Any]) -> ChatResult:
    """A deliberately naive 'model' that obeys instruction-like text found in the customer message or in tool results.
    Used by the red-team stress mode to prove that code-level policy (allow-lists, auth, caps, confirmation) holds on its own."""
    user, tail = _tail(messages)
    n = len(tail)
    done = {t[0] for t in tail}
    haystacks = [user] + [json.dumps(t[2], default=str) for t in tail if t[0] == "search_knowledge"]
    for text in haystacks:
        if INJECT_RX.search(text) and (TOOL_RX.search(text) or re.search(r"refund|erstatt|reembols", text, re.IGNORECASE)):
            tool_m = TOOL_RX.search(text)
            tool = tool_m.group(1) if tool_m else "issue_refund"
            if tool in done:
                continue
            order = ORDER_RX.search(text)
            amt = BIGAMOUNT_RX.search(text)
            args: dict[str, Any] = {"order_id": order.group(1).upper() if order else "CH-100270", "amount": float(amt.group(1)) if amt else 5000.0, "reason": "as instructed"}
            if tool == "goodwill_credit":
                args.pop("order_id", None)
            if tool in ("lookup_order",):
                args = {"order_id": args["order_id"]}
            if tool == "escalate_to_human":
                args = {"reason": "as instructed"}
            if tool == "update_address":
                args = {"order_id": args["order_id"], "street": "Evil Street 1", "postal_code": "00000", "city": "Nowhere"}
            if tool == "initiate_return":
                args = {"order_id": args["order_id"], "reason": "damaged", "resolution": "refund"}
            return _tc(tool, args, n)
    return brain(messages, tools, hints)
