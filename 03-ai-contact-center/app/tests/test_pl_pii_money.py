"""Polish PII (spec §4.7), numbers / money / plurals / dates (§4.4, §4.5) and the text helpers: every identifier VALID and with a broken checksum, inside
Polish sentences; the oracles below are written independently of `core/redaction.py` (they generate numbers from the published algorithms)."""

from __future__ import annotations

import json
import time
from datetime import date

import pytest

from concierge.core import i18n
from concierge.core.money import (
    format_money,
    format_number,
    from_eur,
    number_words_pl,
    parse_money,
    parse_number,
    plural_form_pl,
    speakable_pl,
    spoken_money_pl,
    to_eur,
)
from concierge.core.redaction import id_card_ok, nip_ok, nrb_ok, pesel_ok, redact, regon_ok
from conftest import say

NBSP = "\u00a0"


# ------------------------------------------------------------------------------------------------------------------ oracles (published algorithms)
def make_pesel(y: int, m: int, d: int, serial: int = 1234) -> str:
    month = m + {1800: 80, 1900: 0, 2000: 20, 2100: 40, 2200: 60}[y // 100 * 100]
    body = f"{y % 100:02d}{month:02d}{d:02d}{serial:04d}"
    ctrl = (10 - sum(int(c) * w for c, w in zip(body, (1, 3, 7, 9, 1, 3, 7, 9, 1, 3), strict=True)) % 10) % 10
    return body + str(ctrl)


def make_nip(first9: str) -> str:
    c = sum(int(a) * w for a, w in zip(first9, (6, 5, 7, 2, 3, 4, 5, 6, 7), strict=True)) % 11
    assert c != 10, "pick another 9-digit prefix"
    return first9 + str(c)


def make_regon9(first8: str) -> str:
    c = sum(int(a) * w for a, w in zip(first8, (8, 9, 2, 3, 4, 5, 6, 7), strict=True)) % 11
    return first8 + str(0 if c == 10 else c)


def make_regon14(first13: str) -> str:
    c = sum(int(a) * w for a, w in zip(first13, (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8), strict=True)) % 11
    return first13 + str(0 if c == 10 else c)


def make_id_card(letters: str, digits5: str) -> str:
    vals = [ord(c) - 55 for c in letters]
    weights = (7, 3, 1, 9, 7, 3, 1, 7, 3)
    rest = sum(v * w for v, w in zip(vals, weights[:3], strict=True)) + sum(int(d) * w for d, w in zip(digits5, weights[4:], strict=True))
    check = (-rest * 9) % 10  # 9 * 9 = 81 = 1 (mod 10)
    return f"{letters} {check}{digits5}"


def make_nrb(bban24: str) -> str:
    check = 98 - int(bban24 + "252100") % 97
    return f"{check:02d}{bban24}"


def corrupt(number: str) -> str:
    """Same number with the last digit changed (a broken checksum)."""
    return number[:-1] + str((int(number[-1]) + 3) % 10)


PESEL = make_pesel(1990, 5, 14)
PESEL_2000S = make_pesel(2005, 11, 3, 5678)
PESEL_1800S = make_pesel(1899, 12, 31, 4321)
NIP = make_nip("526025099")
REGON9 = make_regon9("12345678")
REGON14 = make_regon14("1234567850123")
ID_CARD = make_id_card("ABC", "23456")
NRB = make_nrb("109010140000071219812874")


def test_oracles_are_consistent_with_the_validators():
    assert pesel_ok(PESEL) and pesel_ok(PESEL_2000S) and not pesel_ok(corrupt(PESEL))
    assert not pesel_ok(PESEL_1800S), "a valid checksum encoding 1899 is not a plausible customer (older than 126)"
    assert nip_ok(NIP) and not nip_ok(corrupt(NIP))
    assert regon_ok(REGON9) and regon_ok(REGON14) and not regon_ok(corrupt(REGON9)) and not regon_ok(corrupt(REGON14))
    assert id_card_ok(ID_CARD[:3], ID_CARD[4:]) and not id_card_ok("ABC", corrupt(ID_CARD[4:]))
    assert nrb_ok(NRB) and nrb_ok("61109010140000071219812874"), "the published NRB example is valid"
    assert not nrb_ok(corrupt(NRB))


def test_pesel_requires_a_plausible_birth_date():
    assert not pesel_ok(make_pesel(1990, 13, 14)[:2] + "13" + make_pesel(1990, 5, 14)[4:]), "month 13 is no date"
    assert not pesel_ok("90023012345"), "30 February"
    assert not pesel_ok(make_pesel(2199, 1, 1)) and not pesel_ok(make_pesel(2100, 1, 1)), "born in the future"


# ------------------------------------------------------------------------------------------------------------------ in Polish sentences
SENTENCES = [
    ("Mój PESEL to {v}, proszę zweryfikować dane.", "PESEL", PESEL),
    ("Podaję numer PESEL: {v}.", "PESEL", f"{PESEL[:6]} {PESEL[6:]}"),
    ("pesel {v} dziekuje", "PESEL", PESEL_2000S),
    ("Faktura na firmę, NIP: {v}, proszę o wysyłkę.", "NIP", NIP),
    ("NIP {v}", "NIP", f"{NIP[:3]}-{NIP[3:6]}-{NIP[6:8]}-{NIP[8:]}"),
    ("Dane firmy: {v} - Contoso sp. z o.o.", "NIP", f"{NIP[:3]}-{NIP[3:6]}-{NIP[6:8]}-{NIP[8:]}"),
    ("numer VAT PL{v} proszę uwzględnić", "NIP", NIP),
    ("REGON {v} firmy", "REGON", REGON9),
    ("Regon: {v}, adres ul. Długa 5/12, 80-001 Gdańsk", "REGON", REGON14),
    ("Dowód osobisty {v} został okradziony", "ID_CARD", ID_CARD),
    ("seria i numer dowodu: {v}", "ID_CARD", ID_CARD.replace(" ", "")),
    ("Mój paszport AA 1234567 wygasł", "PASSPORT", "AA 1234567"),
    ("numer paszportu: ZS7654321", "PASSPORT", "ZS7654321"),
    ("Proszę o zwrot na rachunek PL{v}, dziękuję.", "IBAN", NRB),
    ("konto {v} proszę zwrócić tam pieniądze", "IBAN", " ".join([NRB[:2], *(NRB[i : i + 4] for i in range(2, 26, 4))])),
    ("NRB {v}", "IBAN", NRB),
]


@pytest.mark.parametrize(("template", "kind", "value"), SENTENCES)
def test_valid_polish_identifiers_inside_sentences_are_redacted(template, kind, value):
    text = template.format(v=value)
    out = redact(text)
    assert out.has(kind), (text, out.text)
    assert f"[{kind}]" in out.text
    digits = "".join(c for c in value if c.isdigit())
    assert digits not in "".join(c for c in out.text if c.isdigit()) or len(digits) < 6, out.text


@pytest.mark.parametrize(
    ("template", "kind", "value"),
    [
        ("Mój PESEL to {v}, proszę zweryfikować dane.", "PESEL", corrupt(PESEL)),
        ("NIP: {v}, proszę o wysyłkę.", "NIP", corrupt(NIP)),
        ("NIP {v}", "NIP", "526-025-09-96"),
        ("REGON {v} firmy", "REGON", corrupt(REGON9)),
        ("Regon: {v}", "REGON", corrupt(REGON14)),
        ("Dowód osobisty {v} został okradziony", "ID_CARD", f"ABC {corrupt(ID_CARD[4:])}"),
        ("Proszę o zwrot na rachunek PL{v}, dziękuję.", "IBAN", corrupt(NRB)),
        ("konto {v}", "IBAN", corrupt(NRB)),
    ],
)
def test_polish_identifiers_with_a_broken_checksum_are_not_redacted_as_that_type(template, kind, value):
    text = template.format(v=value)
    assert not redact(text).has(kind), (text, redact(text).text)


def test_polish_phone_numbers_in_every_common_notation():
    for number in ["600 123 456", "600-123-456", "600123456", "+48 600 123 456", "+48600123456", "0048 600 123 456", "0048600123456", "22 555 01 66", "(22) 555-01-66", "+48 22 555 01 66", "58 555 03 12"]:
        text = f"Proszę o telefon pod numer {number}, jestem dostępny po 16."
        out = redact(text)
        assert out.has("PHONE") and number not in out.text and out.text.endswith("po 16."), (number, out.text)


def test_spoken_polish_digits_are_redacted_as_phone_card_or_pesel():
    phone = "sześć zero zero jeden dwa trzy cztery pięć sześć"
    assert redact(f"Mój numer to {phone}, proszę oddzwonić").has("PHONE")
    assert redact("szesc zero zero jeden dwa trzy cztery piec szesc").has("PHONE"), "without diacritics"
    card = "cztery jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden jeden"
    assert redact(f"numer karty: {card}").has("CARD")
    pesel_words = " ".join({"0": "zero", "1": "jeden", "2": "dwa", "3": "trzy", "4": "cztery", "5": "pięć", "6": "sześć", "7": "siedem", "8": "osiem", "9": "dziewięć"}[c] for c in PESEL)
    assert redact(f"mój pesel to {pesel_words}").has("PESEL")


def test_card_numbers_and_cvv_in_polish_sentences():
    out = redact("Moja karta to 4111 1111 1111 1111, kod CVV 123, ważna do 12/29.")
    assert out.text.startswith("Moja karta to [CARD], kod CVV [CVV]") and out.has("CARD")
    assert redact("kod bezpieczeństwa 4417 z tyłu karty").has("CVV")
    assert not redact("numer 1234 5678 9012 3456 nie jest kartą (zła suma kontrolna)").has("CARD")


@pytest.mark.parametrize(
    "text",
    [
        "Zamówienie CH-100350 zostało dostarczone 18.11.2026 pod adres ul. Marszałkowska 12/4, 00-001 Warszawa.",
        "Kwota do zwrotu to 1 599,00 zł, a rata 133,25 zł miesięcznie.",
        "Numer przesyłki InPost: 6200012345678901234567 nie jest numerem konta.",
        "Kod weryfikacyjny to 482913, ważny 5 minut.",
        "Okno dostawy 09:00-13:00, czwartek 19.11.2026.",
        "Proszę o fakturę za zamówienie CH-100352 na kwotę 1029 zł.",
    ],
)
def test_polish_business_text_is_left_untouched(text):
    assert redact(text).text == text


# ------------------------------------------------------------------------------------------------------------------ adversarial QA: separators, keyword + mistyped number, spoken forms, look-alikes
def _grouped_nrb(sep: str) -> str:
    return sep.join([NRB[:2], *(NRB[i : i + 4] for i in range(2, 26, 4))])


@pytest.mark.parametrize(
    ("template", "kind", "value"),
    [
        ("Mój PESEL to {v}, ul. Długa 5/12, 80-001 Gdańsk", "PESEL", f"{PESEL[:2]} {PESEL[2:4]} {PESEL[4:6]} {PESEL[6:]}"),
        ("PESEL:{v}.", "PESEL", PESEL), ("pesel {v} dzięki", "PESEL", f"{PESEL[:6]}{NBSP}{PESEL[6:]}"), ("PESEL {v}", "PESEL", f"{PESEL[:6]}-{PESEL[6:]}"),
        ("NIP {v}", "NIP", f"{NIP[:3]} {NIP[3:6]} {NIP[6:8]} {NIP[8:]}"), ("numer identyfikacji podatkowej {v}", "NIP", NIP), ("NIP: PL{v}", "NIP", NIP),
        ("NIP {v}", "NIP", NBSP.join([NIP[:3], NIP[3:6], NIP[6:8], NIP[8:]])),
        ("dowód osobisty {v} zgubiony", "ID_CARD", ID_CARD.lower()), ("numer dowodu {v}", "ID_CARD", ID_CARD.replace(" ", "")),
        ("Mój paszport to {v}", "PASSPORT", "AA 1234567"), ("passport number: {v}", "PASSPORT", "ZS7654321"), ("paszport nr {v}", "PASSPORT", "AA1234567"),
        ("na konto {v} proszę", "IBAN", NRB), ("pl{v} dziekuje", "IBAN", NRB), ("konto {v}", "IBAN", _grouped_nrb("-")), ("konto PL {v}", "IBAN", _grouped_nrb(NBSP)),
    ],
)
def test_identifier_formats_found_in_the_wild(template, kind, value):
    text = template.format(v=value)
    out = redact(text)
    digits = "".join(c for c in value if c.isdigit())
    assert out.has(kind), (text, out.text)
    assert digits not in "".join(c for c in out.text if c.isdigit()), out.text


def test_a_lowercase_country_prefix_does_not_swallow_the_next_word():
    assert redact(f"pl{NRB} dziekuje").text == "[IBAN] dziekuje"


@pytest.mark.parametrize(
    "text",
    [f"Mój PESEL to {corrupt(PESEL)}", f"NIP: {corrupt(NIP)}", f"REGON {corrupt(REGON9)} firmy", f"konto {corrupt(NRB)}", f"Dowód osobisty ABC {corrupt(ID_CARD[4:])} zgubiony"],
)
def test_a_keyword_followed_by_a_mistyped_identifier_is_still_masked_but_not_as_that_type(text):
    out = redact(text)
    assert out.has("ID_NUMBER") and "[ID_NUMBER]" in out.text, out.text
    assert not any(ch.isdigit() for ch in out.text), out.text


@pytest.mark.parametrize("number", ["022 555 01 66", "600 12 34 56", f"+48{NBSP}600{NBSP}123{NBSP}456", "(+48) 600 123 456", "(0-22) 555-01-66", "601-234-567"])
def test_more_polish_phone_notations_keep_the_surrounding_text(number):
    out = redact(f"Proszę dzwonić pod {number} po 16.")
    assert out.has("PHONE") and out.text == "Proszę dzwonić pod [PHONE] po 16.", out.text


@pytest.mark.parametrize(
    "words",
    ["sześćset jeden dwa trzy cztery pięć sześć", "sześćset jeden dwadzieścia trzy czterdzieści pięć sześćdziesiąt siedem", "plus czterdzieści osiem sześćset jeden dwa trzy cztery pięć sześć", "szescset jeden dwa trzy cztery piec szesc"],
)
def test_spoken_polish_numbers_with_hundreds_and_tens_are_redacted_as_a_phone(words):
    assert redact(f"mój numer to {words}").has("PHONE"), words


@pytest.mark.parametrize("card", ["4111-1111-1111-1111", "4111.1111.1111.1111", f"4111{NBSP}1111{NBSP}1111{NBSP}1111", "4111 1111 1111 1111 123"])
def test_card_numbers_in_every_separator_style_and_with_stray_digits(card):
    assert redact(f"karta {card} dziękuję").text == "karta [CARD] dziękuję"


@pytest.mark.parametrize("text", ["kod BLIK 123 456", "trzy cyfry z tyłu karty to 123", "kod CVV: 123"])
def test_blik_codes_and_spoken_cvv_are_masked(text):
    assert redact(text).has("CVV"), text


@pytest.mark.parametrize("text", ["anna.kowalska małpa example kropka pl", "anna.kowalska (at) example.pl", "ąęś@example.pl", "Pisać na anna.kowalska@example.com"])
def test_emails_with_polish_letters_or_a_spoken_at_sign_are_masked(text):
    assert redact(text).has("EMAIL"), text


@pytest.mark.parametrize(
    "text",
    [
        "numer przesyłki 62000123456 nie dotarł", "Zamówienie CH-100350 z 12.03.2026 na kwotę 3 790,00 zł", "Dowód zakupu: paragon nr 12345/2026", "dowód zakupu CH-100350",
        "ID zgłoszenia 20261118001", "Termin 18.11.2026 r., godz. 09:00-13:00", "2026-11-18 14:30",
    ],
)
def test_order_numbers_tracking_ids_dates_and_amounts_are_not_mistaken_for_identifiers(text):
    assert redact(text).text == text


def test_redaction_stays_linear_on_long_runs_of_word_characters():
    t0 = time.perf_counter()
    for text in ("a" * 40000, "ą" * 40000, "1." * 20000, "-" * 40000):
        redact(text)
    assert time.perf_counter() - t0 < 3.0


async def test_polish_pii_never_reaches_the_llm_the_transcript_the_store_or_the_audit_log(svc):
    seen: list[str] = []
    original = svc.llm.brain

    def spy(messages, tools, hints):
        seen.append(json.dumps(messages, default=str, ensure_ascii=False))
        return original(messages, tools, hints)

    svc.llm.brain = spy
    conv = await svc.orchestrator.start(language="pl", recording_consent="granted")
    text = f"Mój PESEL to {PESEL}, NIP {NIP}, konto PL{NRB}, karta 4111 1111 1111 1111 cvv 123, tel. 600 123 456, e-mail anna.kowalska@example.com. Gdzie jest zamówienie CH-100351?"
    await say(svc, conv.id, text)
    c = await svc.store.get(conv.id)
    stored_text = next(m.text for m in c.messages if m.role == "customer")
    assert "[PESEL]" in stored_text and "[NIP]" in stored_text and "[IBAN]" in stored_text and "[CARD]" in stored_text and "[PHONE]" in stored_text and "[EMAIL]" in stored_text
    assert "CH-100351" in stored_text
    secrets = (PESEL, NIP, NRB, "4111 1111", "600 123 456", "anna.kowalska@example.com", "cvv 123")
    assert seen and not any(s in blob for blob in seen for s in secrets), "the LLM context is redacted"
    stored = json.dumps(await svc.repo.get("conversations", conv.id), default=str, ensure_ascii=False)
    audit = json.dumps(await svc.audit.recent(200), default=str, ensure_ascii=False)
    assert not any(s in stored or s in audit for s in secrets), "store and audit are redacted"


# ------------------------------------------------------------------------------------------------------------------ numbers & money
@pytest.mark.parametrize(
    ("text", "value"),
    [("379,00", 379.0), ("379.00", 379.0), ("1 599,00", 1599.0), ("1\u00a0599,00", 1599.0), ("1.599,00", 1599.0), ("1,599.00", 1599.0), ("12,5", 12.5), ("1599", 1599.0), ("2 345 678,90", 2345678.9), ("1,234", 1234.0)],
)
def test_parse_number_accepts_polish_and_english_notation(text, value):
    assert parse_number(text) == value


def test_parse_money_finds_every_amount_and_currency_in_a_sentence():
    assert parse_money("Zwrot 379,00 zł na kartę") == [(379.0, "PLN")]
    assert parse_money("Razem 1 599,00 zł i 1.029,50 PLN oraz EUR 12.50 i 500 euro i €30") == [(1599.0, "PLN"), (1029.5, "PLN"), (12.5, "EUR"), (500.0, "EUR"), (30.0, "EUR")]
    assert parse_money("sto złotych, 5 zlotych i 2 zł") == [(5.0, "PLN"), (2.0, "PLN")], "digits only; ASCII `zlotych` and `zl` are the common phone typing"
    assert parse_money("zamówienie CH-100350 z dnia 18.11.2026") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Refund of 2500 euros please", [(2500.0, "EUR")]), ("Rembourse-moi 3000 euros", [(3000.0, "EUR")]), ("Refund 1,599.00 euros", [(1599.0, "EUR")]), ("Zwrot 2 500 eurów", [(2500.0, "EUR")]),
        ("Zwrot 2500 eurow", [(2500.0, "EUR")]), ("Zwrot euro 500", [(500.0, "EUR")]), ("Razem 379,00 zł i 30 euros", [(379.0, "PLN"), (30.0, "EUR")]),
        ("I bought 5 eurostar tickets", []), ("100 europe", []),
    ],
)
def test_parse_money_reads_the_plural_euro_words(text, expected):
    assert parse_money(text) == expected


def test_voice_reads_a_plural_euro_amount_as_euro():
    assert speakable_pl("Zwrot 30 euros") == "Zwrot trzydzieści euro"


def test_money_formatting_in_both_languages():
    assert format_money(379, "PLN", "pl") == f"379,00{NBSP}zł"
    assert format_money(1599, "PLN", "pl") == f"1{NBSP}599,00{NBSP}zł"
    assert format_money(1234567.5, "PLN", "pl") == f"1{NBSP}234{NBSP}567,50{NBSP}zł"
    assert format_money(379, "EUR", "pl") == f"379,00{NBSP}EUR"
    assert format_money(379, "EUR", "en") == "EUR 379.00", "the historic English rendering"
    assert format_money(1599, "PLN", "en") == "PLN 1599.00"
    assert format_number(-1599.5, "pl") == f"-1{NBSP}599,50" and format_number(0.5, "pl", 1) == "0,5"


def test_fixed_demo_fx_rate_is_applied_both_ways():
    assert to_eur(430, "PLN") == pytest.approx(100.0) and to_eur(100, "EUR") == 100.0 and to_eur(100, None) == 100.0
    assert from_eur(100, "PLN") == pytest.approx(430.0) and from_eur(100, "EUR") == 100.0
    assert to_eur(100, "USD") == 100.0, "an unknown currency is treated as the base currency, never as free money"


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"), (1, "jeden"), (12, "dwanaście"), (21, "dwadzieścia jeden"), (100, "sto"), (379, "trzysta siedemdziesiąt dziewięć"), (1000, "tysiąc"), (1599, "tysiąc pięćset dziewięćdziesiąt dziewięć"),
        (2000, "dwa tysiące"), (5000, "pięć tysięcy"), (12000, "dwanaście tysięcy"), (22000, "dwadzieścia dwa tysiące"), (3849, "trzy tysiące osiemset czterdzieści dziewięć"), (1_000_000, "milion"),
        (2_500_000, "dwa miliony pięćset tysięcy"),
    ],
)
def test_amounts_in_words_for_voice(n, words):
    assert number_words_pl(n) == words


def test_spoken_money_uses_the_correct_plural_of_zloty_and_grosz():
    assert spoken_money_pl(379, "PLN") == "trzysta siedemdziesiąt dziewięć złotych"
    assert spoken_money_pl(1, "PLN") == "jeden złoty" and spoken_money_pl(2, "PLN") == "dwa złote" and spoken_money_pl(5, "PLN") == "pięć złotych"
    assert spoken_money_pl(22, "PLN") == "dwadzieścia dwa złote" and spoken_money_pl(12, "PLN") == "dwanaście złotych"
    assert spoken_money_pl(12.5, "PLN") == "dwanaście złotych pięćdziesiąt groszy"
    assert spoken_money_pl(0.02, "PLN") == "zero złotych dwa grosze"
    assert speakable_pl(f"Zwrot 379,00{NBSP}zł jest w drodze, sofa kosztuje 1 599,00 zł.") == "Zwrot trzysta siedemdziesiąt dziewięć złotych jest w drodze, sofa kosztuje tysiąc pięćset dziewięćdziesiąt dziewięć złotych."
    assert speakable_pl("Zamówienie CH-100350 przyjdzie jutro.") == "Zamówienie CH-100350 przyjdzie jutro."


@pytest.mark.parametrize(("n", "form"), [(1, "plik"), (2, "pliki"), (4, "pliki"), (5, "plików"), (12, "plików"), (13, "plików"), (14, "plików"), (21, "plików"), (22, "pliki"), (25, "plików"), (112, "plików"), (0, "plików")])
def test_polish_plural_forms_one_few_many(n, form):
    assert plural_form_pl(n, "plik", "pliki", "plików") == form
    assert i18n.plural("pl", n, {"one": "plik", "few": "pliki", "many": "plików", "other": "pliku"}) == form


def test_polish_fractions_use_the_other_form_and_english_has_one_other():
    assert i18n.plural("pl", 1.5, {"one": "plik", "few": "pliki", "many": "plików", "other": "pliku"}) == "pliku"
    assert i18n.plural("en", 1, {"one": "file", "other": "files"}) == "file" and i18n.plural("en", 2, {"one": "file", "other": "files"}) == "files"


# ------------------------------------------------------------------------------------------------------------------ dates & times
def test_polish_dates_weekdays_and_months():
    d = date(2026, 11, 19)
    assert i18n.fmt_date(d, "pl") == "19.11.2026" and i18n.fmt_date(d, "pl", long=True) == "19 listopada 2026"
    assert i18n.fmt_date("2026-03-01", "pl", long=True) == "1 marca 2026" and i18n.fmt_date(d, "en") == "2026-11-19"
    assert i18n.weekday_name(d, "pl") == "czwartek" and i18n.weekday_name(date(2026, 11, 22), "pl") == "niedziela" and i18n.weekday_name(d, "en") == "Thursday"
    assert [i18n.month_name(m, "pl") for m in (1, 9, 12)] == ["stycznia", "września", "grudnia"]
    assert i18n.slot_phrase("2026-11-19", "09:00-13:00", "pl") == "czwartek 19.11.2026 w godzinach 09:00-13:00"
    assert i18n.slot_phrase("2026-11-19", "09:00-13:00", "en") == "Thursday 2026-11-19 between 09:00-13:00"


def test_polish_times_use_the_24_hour_clock_in_warsaw_including_dst():
    from datetime import UTC, datetime

    winter = datetime(2026, 11, 18, 8, 20, tzinfo=UTC).timestamp()  # CET = UTC+1
    summer = datetime(2026, 6, 9, 9, 33, tzinfo=UTC).timestamp()  # CEST = UTC+2
    assert i18n.fmt_datetime(winter, "pl") == "18.11.2026 09:20"
    assert i18n.fmt_datetime(summer, "pl") == "09.06.2026 11:33" and i18n.fmt_datetime(summer, "en") == "2026-06-09 09:33"


def test_locale_resolution_order_and_normalisation():
    assert i18n.resolve_locale("pl", "en", "en") == "pl" and i18n.resolve_locale(None, "pl", "en") == "pl"
    assert i18n.resolve_locale(None, None, "pl-PL,pl;q=0.9,en;q=0.8") == "pl" and i18n.resolve_locale(None, None, "en-GB,en;q=0.9,pl;q=0.8") == "en"
    assert i18n.resolve_locale(None, None, "de-DE,de;q=0.9,pl;q=0.5") == "pl", "the best SUPPORTED language wins"
    assert i18n.resolve_locale("xx", "pl_PL", None) == "pl" and i18n.resolve_locale("PL", None, None) == "pl"
    assert i18n.resolve_locale(None, None, None) == "en" and i18n.resolve_locale("fr", "de", "fr-FR") == "en"
    assert i18n.resolve_locale(None, None, "pl;q=0,en;q=0.1") == "en", "q=0 means not acceptable"
