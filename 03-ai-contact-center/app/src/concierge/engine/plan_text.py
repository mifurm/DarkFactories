"""Customer-facing deterministic texts of the tool layer (confirmation plans, approval notices, OTP SMS, confirmation e-mail, payment link), rendered in
the CONVERSATION language: English (historic wording, byte-identical) and Polish; every other language falls back to English as before.

Amounts are formatted per language and currency (`EUR 379.00` / `379,00 EUR` / `1 599,00 zł`)."""

from __future__ import annotations

from typing import Any

from ..core.i18n import fmt_date, nbsp_pl, slot_when, weekday_name
from ..core.money import format_money


def _lang(lang: str | None) -> str:
    return "pl" if lang == "pl" else "en"


REASON_PL = {"damaged": "uszkodzenie towaru", "defective": "wada towaru", "changed_mind": "rezygnacja z zakupu", "wrong_item": "dostarczono niewłaściwy towar", "other": "inny powód"}
KIND_PL = {"refund": "zwrot środków", "goodwill": "bon rekompensacyjny"}


def payment_method_pl(brand: str, last4: str) -> str:
    return f"kartę {brand} kończącą się na {last4}"


# The Polish plans are short formal sentences in the first person ("Zlecę ...", "Zarezerwuję ..."): the assistant reads them back as they are and asks
# "Czy mam to zrealizować?". `done_text` turns the same sentence into the record of what was done ("zlecono ...") for wrap-ups, hand-off notes and e-mails.
def return_plan(lang: str, *, item: str, order: str, reason: str, resolution: str, amount: float, currency: str) -> str:
    if _lang(lang) == "pl":
        kind = "z bezpłatną wymianą" if resolution == "replacement" else f"wraz ze zwrotem środków w wysokości {format_money(amount, currency, 'pl')}"
        return nbsp_pl(f"Zlecę zwrot towaru „{item}” z zamówienia {order} (powód: {REASON_PL.get(reason, reason)}) {kind}; odbiór towaru będzie bezpłatny.")
    kind = "free replacement" if resolution == "replacement" else f"refund of {format_money(amount, currency, 'en')}"
    return f"Start a return for '{item}' from order {order} ({reason}) with a {kind}; the damaged/returned item is collected free of charge."


def pickup_plan(lang: str, *, slot: dict[str, Any], city: str) -> str:
    if _lang(lang) == "pl":
        return nbsp_pl(f"Zarezerwuję bezpłatny odbiór towaru z adresu dostawy ({city}): {slot_when(slot['date'], slot['window'], 'pl')}.")
    return f"Book a free pickup on {slot['weekday']} {slot['date']} between {slot['window']} at the delivery address in {city}."


def reschedule_plan(lang: str, *, order: str, slot: dict[str, Any]) -> str:
    if _lang(lang) == "pl":
        return nbsp_pl(f"Przeniosę dostawę zamówienia {order} na {slot_when(slot['date'], slot['window'], 'pl', accusative=True)}; zmiana jest bezpłatna.")
    return f"Move the delivery of order {order} to {slot['weekday']} {slot['date']} between {slot['window']} (free of charge)."


def address_plan(lang: str, *, order: str, street: str, postal_code: str, city: str) -> str:
    if _lang(lang) == "pl":
        return nbsp_pl(f"Zmienię adres dostawy zamówienia {order} na: {street}, {postal_code} {city}.")
    return f"Change the delivery address of order {order} to {street}, {postal_code} {city}."


def refund_plan(lang: str, *, amount: float, currency: str, item: str, order: str, brand: str, last4: str) -> str:
    if _lang(lang) == "pl":
        return nbsp_pl(f"Zarejestruję zwrot środków w wysokości {format_money(amount, currency, 'pl')} za „{item}” (zamówienie {order}) na {payment_method_pl(brand, last4)} — wypłata nastąpi w ciągu 5–7 dni roboczych od odbioru towaru.")
    return f"Refund {format_money(amount, currency, 'en')} for '{item}' (order {order}) to your {brand} ending {last4}; paid within 5-7 business days after the item is collected."


def goodwill_plan(lang: str, *, amount: float, currency: str) -> str:
    if _lang(lang) == "pl":
        return nbsp_pl(f"Dodam do konta Contoso Home bon rekompensacyjny w wysokości {format_money(amount, currency, 'pl')} (ważny 12 miesięcy, nie podlega wymianie na gotówkę).")
    return f"Grant a goodwill credit of {format_money(amount, currency, 'en')} to your Contoso Home account (valid 12 months, not payable in cash)."


def warranty_plan(lang: str, *, item: str, order: str, description: str) -> str:
    if _lang(lang) == "pl":
        text = description.strip()
        shown = f"{text[:120].rstrip()}…" if len(text) > 120 else text
        return nbsp_pl(f"Zarejestruję reklamację towaru „{item}” (zamówienie {order}); opis usterki: „{shown}”.")
    return f"Open a warranty claim for '{item}' (order {order}): {description[:120]}"


_DONE_PL = {"Zlecę": "zlecono", "Zarezerwuję": "zarezerwowano", "Przeniosę": "przeniesiono", "Zmienię": "zmieniono", "Dodam": "dodano", "Zarejestruję": "zarejestrowano"}


def done_text(lang: str | None, summary: str, *, capitalize: bool = False) -> str:
    """The plan sentence as the record of what was done. Polish: `Zlecę zwrot ...` -> `zlecono zwrot ...` (impersonal past, no final full stop, so that several
    records read as one list); other languages and old-style summaries are returned unchanged."""
    if _lang(lang) != "pl":
        return summary
    first, _, rest = summary.partition(" ")
    past = _DONE_PL.get(first)
    if past is None:
        return summary
    text = f"{past} {rest}".rstrip(".")
    return text[:1].upper() + text[1:] if capitalize else text


def otp_sms(lang: str, *, code: str, minutes: int) -> str:
    if _lang(lang) == "pl":
        return f"Contoso Home: kod weryfikacyjny to {code}. Wygasa za {minutes} min. Prosimy nie udostępniać go nikomu."
    return f"Contoso Home: your verification code is {code}. It expires in {minutes} minutes. Never share it with anyone."


def payment_link_sms(lang: str, *, token: str) -> str:
    if _lang(lang) == "pl":
        return f"Bezpieczny link do płatności: /pay/{token} (dane karty należy podawać wyłącznie na tej stronie, nigdy na czacie)."
    return f"Secure payment link: /pay/{token} (card details are entered on this page, never in the chat)."


def confirmation_email(lang: str, *, first_name: str, lines: list[str], reference: str) -> str:
    if _lang(lang) == "pl":
        records = [f"- {done_text('pl', ln[2:], capitalize=True)}" if ln.startswith("- ") and not ln.startswith("- (") else ln for ln in lines]
        # no first name: the vocative case (Anno, Tomaszu) cannot be derived reliably
        return nbsp_pl(f"Dzień dobry,\npotwierdzamy Państwa zgłoszenie w Contoso Home:\n{chr(10).join(records)}\nNumer referencyjny: {reference}\n\nZ poważaniem\nZespół obsługi klienta Contoso Home")
    return "Hello " + first_name + ",\nthis confirms your request with Contoso Home:\n" + "\n".join(lines) + "\nReference: " + reference


NO_CHANGES = {"en": "- (no changes were made)", "pl": "- (nie wprowadzono żadnych zmian)"}

# The tool results carry fixed English phrases for the model; operator-facing texts render the known ones in the conversation language.
ETA_PL = {"5-7 business days after the item is collected": nbsp_pl("w ciągu 5–7 dni roboczych od odbioru towaru")}


def eta_text(lang: str | None, eta: str) -> str:
    return ETA_PL.get(eta, eta) if _lang(lang) == "pl" else eta


def approval_notice(lang: str, *, approved: bool, kind: str, amount: float, currency: str, error: str | None = None) -> str:
    if _lang(lang) == "pl":
        if approved:
            return f"Specjalista zatwierdził {KIND_PL.get(kind, kind)} w wysokości {format_money(amount, currency, 'pl')}."
        if error:
            return f"Nie udało się dokończyć zatwierdzonej operacji: {error}"
        return f"Wniosek o {KIND_PL.get(kind, kind)} w wysokości {format_money(amount, currency, 'pl')} został odrzucony przez specjalistę."
    if approved:
        return f"A specialist approved the {kind} of {format_money(amount, currency, 'en')}."
    if error:
        return f"The approval could not be completed: {error}"
    return f"The {kind} request of {format_money(amount, currency, 'en')} was declined by a specialist."


def returned_to_ai(lang: str) -> str:
    return "Asystent wrócił do rozmowy." if _lang(lang) == "pl" else "The assistant is back on the conversation."


def payment_received(lang: str, *, amount: float | None, brand: str, last4: str) -> str:
    """System notice after the secure payment page completed (English: the historic EUR wording; Polish: PLN)."""
    if _lang(lang) == "pl":
        return f"Bezpieczna płatność{f' w wysokości {format_money(amount, "PLN", "pl")}' if amount else ''} została przyjęta (karta {brand} kończąca się na {last4}). Dane karty nie zostały przekazane asystentowi."
    amt = f" of EUR {amount:.2f}" if amount else ""
    return f"Secure payment{amt} received ({brand} ending {last4}). Card data was never shared with the assistant."


def auto_refund_reason(lang: str, reason: str) -> str:
    """Reason text of the refund the platform books automatically after a pickup (operator-facing; Polish for Polish conversations)."""
    if _lang(lang) == "pl":
        return f"{REASON_PL.get(reason, reason)} — towar zwrócony, pełny zwrot środków"
    return f"{reason} item returned - full refund"


def agent_joined(lang: str, name: str) -> str:
    if lang == "de":
        return f"{name} ist jetzt im Gespräch und sieht alles, was wir besprochen haben."
    if lang == "pl":
        return f"{name} jest już w rozmowie i widzi wszystko, co zostało ustalone."
    return f"{name} has joined the conversation and can see everything we discussed."


def callback_scheduled(lang: str, window: str) -> str:
    if lang == "pl":
        return f"Umówiono oddzwonienie ({window}). Wszystko, co ustaliliśmy, zostało dołączone — nie trzeba niczego powtarzać."
    return f"A callback has been scheduled ({window}). Everything we discussed is attached - you won't need to repeat it."


def callback_short(lang: str, window: str) -> str:
    return f"Umówiono oddzwonienie: {window}." if lang == "pl" else f"Callback scheduled: {window}."


def date_label(value: Any, lang: str = "en") -> str:
    return f"{weekday_name(value, lang)} {fmt_date(value, lang)}"
