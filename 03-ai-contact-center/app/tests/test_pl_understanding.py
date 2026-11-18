"""Polish understanding (CC-06) and language identification (CC-19): golden sets with AND without diacritics, `ł` folding, inflection, entities,
risk flags, sentiment / profanity / urgency, escalation triggers and false-positive controls."""

from __future__ import annotations

import pytest

from concierge.core.langid import detect_language
from concierge.core.textutil import fold, strip_diacritics
from concierge.engine.models import Conversation
from concierge.engine.routing import evaluate_triggers
from concierge.engine.understanding import analyze, extract_entities, is_affirmative, is_negative

# ------------------------------------------------------------------------------------------------------------------ fold / ł


def test_fold_maps_the_letters_nfkd_cannot_decompose():
    assert fold("wściekły") == "wsciekly" and fold("Łódź") == "lodz" and fold("ŁÓDŹ ŻÓŁĆ") == "lodz zolc"
    assert fold("Straße") == "strasse" and fold("Ørsted") == "orsted" and fold("Đuro") == "duro" and fold("œuvre") == "oeuvre"
    assert fold("beschädigt") == "beschadigt" and fold("dañado") == "danado", "the other accents keep working"
    assert strip_diacritics("Zażółć gęślą jaźń") == "Zazolc gesla jazn", "case is kept by strip_diacritics, folded by fold"
    assert fold("ą ć ę ł ń ó ś ź ż") == "a c e l n o s z z"


def test_understanding_fold_is_the_shared_fold():
    from concierge.engine import understanding

    assert understanding.fold("Zażółć") == "zazolc"


# ------------------------------------------------------------------------------------------------------------------ golden utterances
# (utterance, intent, risk flags, extra expectations)
GOLDEN: list[tuple[str, str, set[str]]] = [
    ("Moja kanapa dotarła uszkodzona, numer zamówienia CH-100350.", "damaged_item", set()),
    ("Sofa przyszła zniszczona, ma pęknięty bok i porysowane nogi.", "damaged_item", set()),
    ("Zamówiony stół dotarł rozbity, proszę o pomoc.", "damaged_item", set()),
    ("Gdzie jest moje zamówienie CH-100351? Kurier nie dotarł.", "order_status", set()),
    ("Kiedy dotrze moja paczka?", "order_status", set()),
    ("Proszę o status przesyłki z numerem śledzenia.", "order_status", set()),
    ("Chciałbym zwrócić krzesła, zmieniłem zdanie.", "return_request", set()),
    ("Chcę odstąpić od umowy i oddać lampę.", "return_request", set()),
    ("Chcę odesłać materac i dostać zwrot pieniędzy.", "refund_status", set()),
    ("Kiedy dostanę zwrot pieniędzy za anulowane zamówienie?", "refund_status", set()),
    ("Gdzie są moje pieniądze? Zwrot jeszcze nie wpłynął.", "refund_status", set()),
    ("Czy możecie przełożyć dostawę na piątek?", "delivery_change", set()),
    ("Chcę zmienić termin dostawy, jestem w delegacji.", "delivery_change", set()),
    ("Muszę zmienić adres dostawy, przeprowadziłem się.", "address_change", set()),
    ("Nowy adres: ul. Marszałkowska 12/4, 00-001 Warszawa.", "address_change", set()),
    ("Pralka przestała działać, chcę skorzystać z gwarancji.", "warranty_claim", set()),
    ("Chcę złożyć reklamację na lodówkę.", "warranty_claim", set()),
    ("Piekarnik ma wadę fabryczną, zgłaszam rękojmię.", "warranty_claim", set()),
    ("Proszę anulować moje zamówienie CH-100310.", "cancel_order", set()),
    ("Należy mi się odszkodowanie za opóźnioną dostawę.", "goodwill_request", set()),
    ("Pobrano ode mnie dwa razy tę samą płatność, faktura jest błędna.", "billing_question", set()),
    ("Ile kosztuje montaż pralki?", "installation_info", set()),
    ("Proszę o usunięcie moich danych osobowych zgodnie z RODO.", "privacy_request", set()),
    ("Składam skargę na waszą obsługę.", "complaint", set()),
    ("Jak długo mam czas na zwrot towaru?", "policy_question", set()),
    ("Czy ta sofa jest dostępna w kolorze szarym?", "product_info", set()),
    ("Dzień dobry", "greeting", set()),
    ("Dzień dobry, chciałbym zwrócić sofę, która dotarła uszkodzona.", "damaged_item", set()),
    ("Dziękuję, to wszystko.", "goodbye", set()),
    ("Jeśli sprawa nie zostanie rozwiązana, wystąpię na drogę prawną i pozwę was do sądu.", "complaint", {"legal_threat"}),
    ("Zgłoszę sprawę do UOKiK i do Rzecznika Praw Konsumenta.", "complaint", {"legal_threat"}),
    ("Skontaktuję się z prawnikiem w sprawie tej dostawy.", "complaint", {"legal_threat"}),
    ("Mój adwokat przygotowuje pozew przeciwko waszej firmie.", "complaint", {"legal_threat"}),
    ("Radca prawny już zajmuje się tą sprawą, sprawa trafi do sądu.", "complaint", {"legal_threat"}),
    ("Wniosę skargę do powiatowego rzecznika konsumentów.", "complaint", {"legal_threat"}),
    ("Nie składałem tego zamówienia, to oszustwo!", "other", {"fraud_suspected"}),
    ("Ktoś wyłudził dane mojej karty i zamówił telewizor.", "other", {"fraud_suspected"}),
    ("Jestem osobą starszą i niewidomą, potrzebuję pomocy przy dostawie.", "other", {"vulnerable_customer"}),
    ("Mam 82 lata i nie radzę sobie z aplikacją.", "other", {"vulnerable_customer"}),
    ("Jestem na wózku inwalidzkim, a kurier nie wniósł sofy.", "other", {"vulnerable_customer"}),
    ("Z piekarnika czuć zapach gazu!", "other", {"safety_issue"}),
    ("Z lampy sypią się iskry i czuć dym.", "other", {"safety_issue"}),
    ("W pralce iskrzy, grozi pożar!", "other", {"safety_issue"}),
    ("Zgłaszam sprawę do UODO, bo nie usunęliście moich danych.", "privacy_request", {"regulatory_complaint"}),
    ("Nigdy więcej nic od was nie kupię.", "other", {"churn_risk"}),
]


def strip_text(text: str) -> str:
    return strip_diacritics(text)


@pytest.mark.parametrize(("text", "intent", "risks"), GOLDEN)
def test_polish_golden_with_diacritics(text, intent, risks):
    u = analyze(text, lang_hint="pl")
    assert u.intent == intent, (text, u.intent, u.secondary)
    assert risks <= set(u.risk_flags), (text, u.risk_flags)
    assert u.language == "pl"


@pytest.mark.parametrize(("text", "intent", "risks"), GOLDEN)
def test_polish_golden_without_diacritics_gives_the_same_reading(text, intent, risks):
    plain = strip_text(text)
    a, b = analyze(text, lang_hint="pl"), analyze(plain, lang_hint="pl")
    assert (b.intent, set(b.risk_flags), b.urgency, b.emotion) == (a.intent, set(a.risk_flags), a.urgency, a.emotion), plain
    assert b.entities.get("order_id") == a.entities.get("order_id") and b.entities.get("amount") == a.entities.get("amount")


def test_polish_without_a_language_hint_is_detected_even_without_diacritics():
    for text in ["kanapa dotarla uszkodzona, prosze o pomoc", "gdzie jest moje zamowienie", "chce zwrocic krzesla"]:
        u = analyze(text)
        assert u.language == "pl", text


def test_legal_threat_stem_does_not_fire_on_pozwolic_or_gas_appliances():
    for text in ["Czy mogę pozwolić sobie na zmianę terminu?", "Pozwala pan na odbiór w sobotę?", "Czy kuchenka gazowa ma 24 miesiące gwarancji?"]:
        u = analyze(text, lang_hint="pl")
        assert "legal_threat" not in u.risk_flags and "safety_issue" not in u.risk_flags, (text, u.risk_flags)


def test_reklamacja_is_a_warranty_claim_and_skarga_is_a_service_complaint():
    assert analyze("Chcę złożyć reklamację", lang_hint="pl").intent == "warranty_claim"
    assert analyze("Chcę złożyć skargę", lang_hint="pl").intent == "complaint"


# ------------------------------------------------------------------------------------------------------------------ sentiment, profanity, urgency
@pytest.mark.parametrize(
    ("text", "emotion", "max_sentiment"),
    [
        ("To skandal, jestem wściekły, trzeci raz piszę w tej sprawie!", "angry", -0.6),
        ("To skandal, jestem wsciekly, trzeci raz pisze w tej sprawie!", "angry", -0.6),
        ("To jest kurwa skandal, jesteście debilami.", "angry", -0.6),
        ("Co za idioci, spierdalajcie z tym sklepem", "angry", -0.6),
        ("Nie jestem zadowolony z dostawy, nadal nic nie dotarło.", "frustrated", -0.2),
        ("Wkurza mnie ta obsługa, to jakiś żart.", "frustrated", -0.2),
    ],
)
def test_polish_negative_sentiment_and_profanity_with_inflection(text, emotion, max_sentiment):
    u = analyze(text, lang_hint="pl")
    assert u.sentiment <= max_sentiment, (text, u.sentiment)
    assert u.emotion in (emotion, "angry"), (text, u.emotion)


def test_polish_positive_sentiment():
    for text in ["Bardzo dziękuję za pomoc, wszystko świetnie załatwione!", "Dziekuje, swietna obsluga, polecam"]:
        u = analyze(text, lang_hint="pl")
        assert u.sentiment >= 0.35 and u.emotion == "satisfied", (text, u.sentiment)


def test_polish_urgency():
    assert analyze("Proszę pilnie o kontakt, sprawa jest pilna.", lang_hint="pl").urgency == "high"
    assert analyze("Potrzebuję tego natychmiast.", lang_hint="pl").urgency == "high"
    assert analyze("Czuję zapach gazu", lang_hint="pl").urgency == "critical"
    assert analyze("Ile kosztuje montaż?", lang_hint="pl").urgency in ("low", "normal")


# ------------------------------------------------------------------------------------------------------------------ entities
def test_entities_order_id_amount_postal_address_and_carriers():
    e = extract_entities("Zamówienie ch-100231, zwrot 379,00 zł na kartę.")
    assert e["order_id"] == "CH-100231" and e["amount"] == 379.0 and e["currency"] == "PLN"
    assert extract_entities("Zamówienie CH 100231")["order_id"] == "CH-100231"
    assert extract_entities("Kwota to 1 599,00 zł")["amount"] == 1599.0
    assert extract_entities("Zapłaciłem 1599.50 PLN")["amount"] == 1599.5
    assert extract_entities("Refund of EUR 379.00 please")["currency"] == "EUR", "English EUR amounts are unchanged"
    addr = extract_entities("Nowy adres to ul. Długa 5/12, 80-001 Gdańsk")["new_address"]
    assert addr == {"street": "ul. Długa 5/12", "postal_code": "80-001", "city": "Gdańsk"}
    addr2 = extract_entities("al. Jerozolimskie 44, 00-024 Warszawa")["new_address"]
    assert addr2["postal_code"] == "00-024" and addr2["city"] == "Warszawa"
    assert extract_entities("Mój adres: Lindenstraße 5, 10969 Berlin")["new_address"]["city"] == "Berlin"
    assert extract_entities("Paczka InPost nie dotarła")["carrier"] == "InPost"
    assert extract_entities("Kurier DPD Polska zostawił awizo")["carrier"] == "DPD Polska"
    assert extract_entities("Przesyłkę DHL zwrócono do nadawcy")["carrier"] == "DHL"
    assert extract_entities("Moja kanapa jest szara")["product"] == "sofa"
    assert extract_entities("Szafa Arden")["product"] == "wardrobe"
    assert extract_entities("Pralka Vera nie wiruje")["product"] == "washing machine"


# ------------------------------------------------------------------------------------------------------------------ confirmations
def test_polish_confirmation_and_refusal():
    for yes in ["Tak, proszę.", "Tak, poproszę", "Zgoda", "Potwierdzam", "Jasne, realizuj", "tak prosze", "Dobrze, zgadzam się"]:
        assert is_affirmative(yes), yes
    for no in ["Nie", "Nie, dziękuję", "Anuluj to", "Nie chcę", "nie teraz"]:
        assert not is_affirmative(no) and is_negative(no), no


# ------------------------------------------------------------------------------------------------------------------ escalation triggers (same behaviour as English)
def conv_for(text: str) -> tuple[Conversation, object]:
    conv = Conversation(id="pl-1", language="pl")
    u = analyze(text, lang_hint="pl")
    conv.add("customer", text)
    conv.understanding = u
    conv.sentiment_trajectory.append(u.sentiment)
    conv.intent_trail.append(u.intent)
    conv.risk_flags = sorted(set(u.risk_flags))
    return conv, u


@pytest.mark.parametrize(
    ("text", "trigger"),
    [
        ("Wystąpię na drogę prawną, mój prawnik się z wami skontaktuje.", "legal_threat"),
        ("Z piekarnika czuć zapach gazu!", "safety_issue"),
        ("Ktoś wyłudził dane mojej karty, to oszustwo.", "fraud_suspected"),
        ("Jestem osobą niewidomą i potrzebuję pomocy.", "vulnerable_customer"),
        ("To jest kurwa skandal, jesteście debilami!", "sentiment"),
    ],
)
def test_escalation_triggers_fire_for_polish_text_with_and_without_diacritics(text, trigger):
    for variant in (text, strip_text(text)):
        conv, u = conv_for(variant)
        codes = [t.code for t in evaluate_triggers(conv, u)]
        assert codes and codes[0] == trigger, (variant, codes)


# ------------------------------------------------------------------------------------------------------------------ language identification
LANGID_CASES: list[tuple[str, str]] = [
    # Polish, with and without diacritics, short and long
    ("Moja sofa dotarła uszkodzona", "pl"), ("moja sofa dotarla uszkodzona", "pl"), ("kanapa dotarla uszkodzona", "pl"), ("Dzień dobry", "pl"), ("dzien dobry", "pl"),
    ("Dziękuję", "pl"), ("dziekuje", "pl"), ("Tak, proszę", "pl"), ("tak prosze", "pl"), ("Gdzie jest moje zamówienie?", "pl"), ("gdzie jest moje zamowienie CH-100231", "pl"),
    ("Chcę zwrócić kanapę", "pl"), ("chce zwrocic kanape", "pl"), ("Czesc, chcialbym zlozyc reklamacje", "pl"), ("Jestem wściekły, to skandal", "pl"),
    ("Proszę o zwrot pieniędzy na kartę", "pl"), ("Nie mam pojęcia, co z tym zrobić", "pl"), ("Kiedy przyjedzie kurier?", "pl"),
    ("Poproszę o kontakt z konsultantem", "pl"), ("Pralka przestała działać po tygodniu", "pl"),
    # other languages (must NOT be Polish)
    ("Where is my order?", "en"), ("My sofa arrived damaged, please help", "en"), ("Mein Sofa ist beschädigt angekommen", "de"), ("Wo ist meine Bestellung?", "de"),
    ("Mon canapé est arrivé endommagé", "fr"), ("Hola, mi pedido llegó dañado", "es"), ("Ciao, dov'è il mio ordine?", "it"), ("Goedendag, waar is mijn bestelling", "nl"),
    ("Hej, var är min beställning", "sv"), ("Olá, a minha encomenda chegou danificada", "pt"),
    # similar languages
    ("Dobrý den, moje objednávka je poškozená", "cs"), ("Dobrý deň, moja objednávka je poškodená", "sk"), ("Děkuji, prosím o vrácení peněz", "cs"), ("Ďakujem, prosím o vrátenie peňazí", "sk"),
    ("Zdravstvuyte, moy zakaz ne prishel", "ru"), ("Здравствуйте, мой заказ не пришёл", "ru"),
]


@pytest.mark.parametrize(("text", "expected"), LANGID_CASES)
def test_language_identification_golden(text, expected):
    lang, conf = detect_language(text)
    assert lang == expected, (text, lang, conf)
    assert conf >= 0.5


def test_langid_has_at_least_thirty_cases_and_ambiguous_one_word_falls_back_to_the_default():
    assert len(LANGID_CASES) >= 30
    lang, conf = detect_language("ok", default="pl")
    assert lang == "pl" and conf < 0.45
    assert detect_language("", default="pl") == ("pl", 0.0)
    assert detect_language("12345 67890", default="en")[0] == "en"


# ------------------------------------------------------------------------------------------------------------------ adversarial QA: questions about the rules vs real requests
POLICY_QUESTIONS = [
    "Jakie są Wasze zasady zwrotów?", "Jaka jest polityka zwrotów?", "Jakie są warunki zwrotu towaru?", "Gdzie znajdę regulamin zwrotów?", "Co mówi regulamin o zwrotach?",
    "Ile mam dni na zwrot?", "W jakim terminie mogę zwrócić zakupiony towar?", "Czy mogę zwrócić sofę?", "Czy można zwrócić rozpakowany materac?", "Czy mogę oddać produkt po miesiącu?",
    "Czy przysługuje mi zwrot po 14 dniach?", "Czy zwrot jest bezpłatny?", "Czy zwroty są darmowe?", "Kto pokrywa koszty zwrotu?", "Czy koszt zwrotu ponosi klient?",
    "Jak wygląda procedura zwrotu?", "Jak zrobić zwrot?", "Jak mogę dokonać zwrotu?", "Jak złożyć reklamację?", "Jakie są zasady reklamacji?", "Jakie macie zasady wymiany?",
    "Do kiedy mogę zwrócić towar?", "Do kiedy obowiązuje zwrot?", "Czy macie darmowy zwrot?", "Czy mogę odstąpić od umowy po 14 dniach?", "Jakie są zasady odstąpienia od umowy?",
    "Czy zwracacie pieniądze za zwrócone towary?", "Czy potrzebuję paragonu do zwrotu?", "Czy muszę mieć oryginalne opakowanie do zwrotu?", "Jak szybko wracają pieniądze po zwrocie?",
    "Potrzebuję informacji o zasadach zwrotów", "Proszę o informację o warunkach zwrotu", "Chciałbym zapytać o zasady zwrotów", "Chcę wiedzieć, ile mam dni na zwrot", "Proszę o wyjaśnienie zasad zwrotów",
    "Zasady zwrotów?", "Regulamin zwrotów", "Warunki zwrotu", "Jakie są warunki gwarancji na lodówkę?", "Jak działa gwarancja?",
]
# a first-person request keeps its action intent even when it quotes the rules, mentions an order number or waits for its own money
REQUESTS_THAT_MENTION_THE_RULES = [
    ("Chcę zwrot", "return_request"), ("Zwracam sofę", "return_request"), ("Chciałbym zwrócić sofę", "return_request"), ("Odsyłam towar", "return_request"),
    ("Chcę zwrot zgodnie z regulaminem", "return_request"), ("Chcę zwrócić sofę zgodnie z polityką zwrotów", "return_request"), ("Odstępuję od umowy zgodnie z regulaminem sklepu", "return_request"),
    ("Zwracam sofę na warunkach z regulaminu", "return_request"), ("Chciałbym zwrócić sofę. Jakie są warunki?", "return_request"), ("Chcę odesłać sofę, ile mam na to dni?", "return_request"),
    ("Wasze zasady są niejasne, chcę zwrot", "return_request"), ("w zasadzie chcę zwrot", "return_request"), ("Chcę zwrócić moją sofę, czy to możliwe po 20 dniach?", "return_request"),
    ("Jak mogę zwrócić zamówienie CH-100350?", "return_request"), ("Czy mogę zwrócić zamówienie CH-100350?", "return_request"),
    ("Kiedy dostanę mój zwrot? Ile to trwa?", "refund_status"), ("Jak długo jeszcze mam czekać na zwrot?", "refund_status"), ("Ile dni mam czekać na zwrot?", "refund_status"),
    ("Czy zwrot jest już zaksięgowany?", "refund_status"), ("Czy zwrócicie mi pieniądze?", "refund_status"), ("Czy reklamacja jest rozpatrzona?", "warranty_claim"),
]


@pytest.mark.parametrize("text", POLICY_QUESTIONS)
def test_questions_about_rules_terms_and_procedure_are_policy_questions_not_requests(text):
    for variant in (text, strip_text(text)):
        u = analyze(variant, lang_hint="pl")
        assert u.intent == "policy_question", (variant, u.intent, u.secondary)


@pytest.mark.parametrize(("text", "intent"), REQUESTS_THAT_MENTION_THE_RULES)
def test_requests_stay_requests_even_when_they_quote_the_rules(text, intent):
    for variant in (text, strip_text(text)):
        assert analyze(variant, lang_hint="pl").intent == intent, variant


# ------------------------------------------------------------------------------------------------------------------ adversarial QA: SMS style, inflection, slang, Polish-English mix
INTENT_CASES: list[tuple[str, str]] = [
    ("kanapa dotarla uszkodzona, chce zwrot", "damaged_item"), ("gdzie jest moja paczka??", "order_status"), ("zamowienie CH-100351 nie dotarlo od tygodnia", "order_status"),
    ("prosze o zwrot pieniedzy za zamowienie CH-100350", "refund_status"), ("pralka sie zepsula po tygodniu", "warranty_claim"), ("lodowka nie chlodzi", "warranty_claim"),
    ("chce anulowac zamowienie CH-100310", "cancel_order"), ("czy moge przelozyc dostawe na piatek", "delivery_change"), ("faktura jest zla, prosze o korekte", "billing_question"),
    ("sofa jest za duza, chce oddac", "return_request"), ("chce zlozyc reklamacje na krzeslo", "warranty_claim"), ("szafa przyszla zarysowana", "damaged_item"),
    ("stol ma pekniety blat", "damaged_item"), ("chce zwrocic towar, zly rozmiar", "return_request"), ("nie chce juz tego zamowienia", "cancel_order"),
    ("usunac moje dane z waszej bazy, rodo", "privacy_request"), ("paczka uszkodzona, kurier nie chcial spisac protokolu", "damaged_item"), ("piekarnik nie grzeje", "warranty_claim"),
    ("zmywarka przestala dzialac", "warranty_claim"), ("od trzech dni czekam na kuriera", "order_status"), ("mialo byc wczoraj a dalej nic, gdzie to jest", "order_status"),
    ("zly adres wpisalem, prosze poprawic", "address_change"), ("pomylilem adres dostawy, mieszkanie 12 a nie 21", "address_change"), ("telewizor nie wlacza sie od wczoraj", "warranty_claim"),
    ("kasa mi się należy z powrotem", "refund_status"), ("Oddajcie mi pieniądze!", "refund_status"), ("chcę moją kasę z powrotem", "refund_status"), ("Gdzie jest mój zwrot?", "refund_status"),
    ("Czekam na zwrot od trzech tygodni", "refund_status"), ("Nie dostałem jeszcze zwrotu", "refund_status"), ("Pieniądze nie wróciły na kartę", "refund_status"),
    ("ten order jest delayed", "order_status"), ("Mój order jest delayed od tygodnia", "order_status"), ("chcę refund", "refund_status"), ("Proszę o refund za zamówienie CH-100350", "refund_status"),
    ("Złożyłem wniosek o zwrot", "return_request"), ("Przy zwrocie sofy kurier odmówił odbioru", "return_request"), ("Zajmuję się zwrotem zamówienia CH-100350", "return_request"),
    ("Składam reklamację na sofę", "warranty_claim"), ("Dotyczy reklamacji z zeszłego tygodnia", "warranty_claim"), ("Co z moją reklamacją?", "warranty_claim"), ("Reklamacją zajmuje się serwis", "warranty_claim"),
    ("Dostałem uszkodzone krzesła", "damaged_item"), ("Uszkodzenie wykryłem po rozpakowaniu", "damaged_item"), ("Zepsuty ekspres, nie działa", "damaged_item"), ("Pralka jest zepsuta", "damaged_item"),
    ("Nie chcę zwrotu, chcę wymianę", "return_request"), ("Dostałam sofę w złym kolorze", "return_request"), ("Odstępuję od umowy", "return_request"),
    ("Zamówienie zostało dostarczone, ale ja go nie odebrałem", "order_status"), ("Kurier twierdzi, że mnie nie było, a siedziałem cały dzień w domu", "order_status"),
    ("Proszę o wystawienie faktury korygującej na zamówienie CH-100409", "billing_question"), ("Czy sofa jest dostępna w innym kolorze?", "product_info"), ("Proszę o połączenie z przełożonym", "other"),
]


@pytest.mark.parametrize(("text", "intent"), INTENT_CASES)
def test_polish_intents_in_sms_style_slang_inflected_and_mixed_language_text(text, intent):
    for variant in (text, strip_text(text)):
        u = analyze(variant, lang_hint="pl")
        assert u.intent == intent, (variant, u.intent, u.secondary)


RISK_CASES: list[tuple[str, str]] = [
    ("Wystąpię z pozwem", "legal_threat"), ("Pozwę was", "legal_threat"), ("Zamierzam was pozwać", "legal_threat"), ("Spotkamy się w sądzie", "legal_threat"), ("Mam prawnika", "legal_threat"),
    ("Skontaktuję się z adwokatem", "legal_threat"), ("Moja radca prawny już pisze pozew", "legal_threat"), ("Poinformuję Rzecznika Konsumentów", "legal_threat"), ("Zgłoszę to do UOKiK", "legal_threat"),
    ("Zostałem oszukany", "fraud_suspected"), ("Oszukali mnie na pieniądze", "fraud_suspected"), ("To wyłudzenie", "fraud_suspected"), ("Ktoś użył mojej karty", "fraud_suspected"), ("Czuję się oszukana", "fraud_suspected"),
    ("Jestem starszą osobą", "vulnerable_customer"), ("Mój dziadek jest niepełnosprawny", "vulnerable_customer"), ("Jestem niewidomy", "vulnerable_customer"), ("Mam 85 lat", "vulnerable_customer"),
    ("Moja mama ma 87 lat i nie umie obsługiwać telefonu", "vulnerable_customer"),
    ("Czuć gaz w kuchni", "safety_issue"), ("Z pralki wydobywa się dym", "safety_issue"), ("Pożar w kuchni po włączeniu piekarnika", "safety_issue"), ("Pachnie gazem", "safety_issue"),
    ("Palą się przewody", "safety_issue"), ("Przewody się palą", "safety_issue"), ("Pali się wtyczka", "safety_issue"), ("Czy to bezpieczne? Pachnie jakby coś się paliło", "safety_issue"),
    ("Ulatnia się czad z piecyka", "safety_issue"),
    ("Pójdę do sądu", "legal_threat"), ("Podam was do sądu", "legal_threat"), ("Złożę pozew", "legal_threat"), ("Mój prawnik się z wami skontaktuje", "legal_threat"),
    ("Czy muszę iść do sądu? Jeśli tak, to pójdę", "legal_threat"), ("Nie zamawiałem tej paczki", "fraud_suspected"), ("Nie zamawiałem tego zamówienia", "fraud_suspected"),
    ("Nie zamawiałem niczego", "fraud_suspected"),
]
# false-positive controls: a forbidden stem inside a normal sentence, a negated threat, a lamp that is simply on
NO_RISK_CASES: list[tuple[str, str]] = [
    ("Nie zamierzam pozywać nikogo", "legal_threat"), ("Nie będę pozywać", "legal_threat"), ("Nie chcę iść do sądu, chcę tylko rozwiązać problem", "legal_threat"),
    ("Mój przełożony zatwierdził ten termin", "legal_threat"), ("Czy mogę pozwolić sobie na zmianę terminu?", "legal_threat"), ("To nie jest oszustwo, po prostu pomyłka", "fraud_suspected"),
    ("Nie czuję żadnego zapachu gazu", "safety_issue"), ("Na pralce pali się czerwona lampka", "safety_issue"), ("Palą się lampki na pilocie", "safety_issue"), ("Pali się światło w lodówce", "safety_issue"),
    ("Ale czad, dziękuję!", "safety_issue"), ("Czy kuchenka gazowa ma 24 miesiące gwarancji?", "safety_issue"), ("Naprawdę dziękuję za pomoc", "legal_threat"),
    ("Czy muszę iść do sądu?", "legal_threat"), ("Czy trzeba iść do sądu w tej sprawie?", "legal_threat"), ("Nie zamawiałem tej wersji", "fraud_suspected"),
    ("Nie zamawiałem tego koloru", "fraud_suspected"), ("Nie zamawiałem tego krzesła", "fraud_suspected"),
]


@pytest.mark.parametrize(("text", "risk"), RISK_CASES)
def test_polish_risk_flags_in_every_inflection_with_and_without_diacritics(text, risk):
    for variant in (text, strip_text(text)):
        assert risk in analyze(variant, lang_hint="pl").risk_flags, variant


@pytest.mark.parametrize(("text", "risk"), NO_RISK_CASES)
def test_polish_risk_flags_do_not_fire_on_negations_and_look_alikes(text, risk):
    for variant in (text, strip_text(text)):
        assert risk not in analyze(variant, lang_hint="pl").risk_flags, variant


def test_english_and_german_behaviour_is_not_changed_by_the_polish_lexicon():
    assert "legal_threat" not in analyze("I am so sad about this delivery", lang_hint="en").risk_flags, "`sąd` folds to `sad`"
    assert analyze("My washing machine arrived damaged", lang_hint="en").entities["product"] == "washing machine"
    assert analyze("Mein Kühlschrank ist kaputt", lang_hint="de").entities["product"] == "fridge"
    assert analyze("Refund of 2500 euros please", lang_hint="en").entities.get("amount") == 2500.0
    assert extract_entities("Rembourse-moi 3000 euros")["amount"] == 3000.0
    assert analyze("This is the soft version, not the one I stole", lang_hint="en").entities.get("product") is None, "`sof` / `stole` are whole words only"


# ------------------------------------------------------------------------------------------------------------------ adversarial QA: entities, confirmations, sentiment, language identification
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("zamówienie CH100350 nie dotarło", {"order_id": "CH-100350"}), ("Zamówienie CH\u2011100350 nie dotarło", {"order_id": "CH-100350"}), ("Zamówienie ch 100350", {"order_id": "CH-100350"}),
        ("Cena 2 tys. zł za sofę", {"amount": 2000.0, "currency": "PLN"}), ("Zapłaciłem 1,5 tys. zł", {"amount": 1500.0, "currency": "PLN"}),
        ("Oddajcie mi tysiąc dwieście złotych", {"amount": 1200.0, "currency": "PLN"}), ("Zapłaciłem 379,- zł", {"amount": 379.0}), ("Zapłaciłem 379 zł", {"amount": 379.0}),
        ("Zapłaciłem 379.00 PLN", {"amount": 379.0}), ("Kwota 1.599,00 zł", {"amount": 1599.0}),
        ("Nowy adres to ul. 3 Maja 5/7, 00-001 Warszawa", {"new_address": {"street": "ul. 3 Maja 5/7", "postal_code": "00-001", "city": "Warszawa"}}),
        ("Dostawa na al. Jerozolimskie 100 m. 7, 00-807 Warszawa", {"new_address": {"street": "al. Jerozolimskie 100 m. 7", "postal_code": "00-807", "city": "Warszawa"}}),
        ("os. Słoneczne 3/15, 61-001 Poznań", {"new_address": {"street": "os. Słoneczne 3/15", "postal_code": "61-001", "city": "Poznań"}}),
        ("80-001 Gdańsk, ul. Długa 5/12", {"new_address": {"street": "ul. Długa 5/12", "postal_code": "80-001", "city": "Gdańsk"}}),
        ("Marszałkowska 12/4, 00-001 Warszawa", {"new_address": {"street": "Marszałkowska 12/4", "postal_code": "00-001", "city": "Warszawa"}}),
        ("Dostawa na ul. Długa 5/12, 80-001 Gdańsk proszę o dostawę w piątek", {"new_address": {"street": "ul. Długa 5/12", "postal_code": "80-001", "city": "Gdańsk"}}),
    ],
)
def test_polish_entities_in_many_notations(text, expected):
    ents = extract_entities(text)
    assert {k: ents.get(k) for k in expected} == expected, (text, ents)


@pytest.mark.parametrize(
    ("text", "order_id"),
    [
        ("Zamówienie 100350 nie dotarło", "CH-100350"), ("numer zamówienia: 100350", "CH-100350"), ("nr 100350 proszę o zwrot", "CH-100350"), ("Zamowienie numer 100350 jest opoznione", "CH-100350"),
        ("numer przesyłki 100350", None), ("mój telefon 600123456", None), ("zamówienie 1003500", None), ("kod weryfikacyjny 482913", None),
    ],
)
def test_a_bare_six_digit_number_is_an_order_id_only_right_behind_zamowienie_nr_numer(text, order_id):
    assert analyze(text, lang_hint="pl").entities.get("order_id") == order_id, text


def test_a_bare_order_number_counts_as_an_order_for_the_policy_question_rule_and_english_is_untouched():
    assert analyze("Czy mogę zwrócić zamówienie 100350?", lang_hint="pl").intent == "return_request", "an own order is not a general policy question"
    assert analyze("Czy mogę zwrócić zamówienie?", lang_hint="pl").intent == "policy_question"
    assert analyze("order 100350 is late", lang_hint="en").entities.get("order_id") is None
    assert extract_entities("zamówienie 100350").get("order_id") is None, "Polish context is decided by `analyze`, not by the extractor default"


def test_polish_confirmations_are_not_fooled_by_conditions_or_idioms():
    for yes in ["no dobra", "Nie ma problemu", "spoko", "oki"]:
        assert is_affirmative(yes) and not is_negative(yes), yes
    for not_yet in ["Tak, ale najpierw proszę o fakturę", "Dobrze, tylko jeśli będzie bezpłatnie"]:
        assert not is_affirmative(not_yet), not_yet
    assert is_negative("nie, dzięki")


def test_polish_slang_caps_emoji_and_masked_profanity_read_as_anger():
    for text in ["wkurza mnie to", "WASZA OBSŁUGA TO PORAŻKA!!!", "Masakra, porażka, trzeci raz dzwonię", "k***a mać, znowu nie dotarło", "ch*j z wami", "😡😡😡 gdzie moja paczka?!"]:
        u = analyze(text, lang_hint="pl")
        assert u.emotion in ("angry", "frustrated") and u.sentiment <= -0.2, (text, u.emotion, u.sentiment)
    assert analyze("Czy w zestawie jest szmatka do czyszczenia?", lang_hint="pl").sentiment >= -0.1, "`szmatka` is a cleaning cloth"
    assert analyze("Czy sprzedajecie pilnik do metalu?", lang_hint="pl").urgency in ("low", "normal"), "`pilnik` is not `pilny`"


@pytest.mark.parametrize(
    "text",
    [
        "Czy macie kutasy do zasłon?", "Kurczak z ryżem na obiad", "Oglądam mecz na nowym telewizorze", "Palantir Technologies", "Jebel Ali port", "Hujan is the Malay word for rain",
        "Debilitating back pain", "Kurier przywiózł paczkę", "Kurort w Ciechocinku", "Dupont and Dupuy from Szczecin", "Bombki choinkowe do salonu",
    ],
)
def test_profanity_and_sentiment_stems_do_not_hit_tassels_chicken_matches_and_foreign_names(text):
    u = analyze(text, lang_hint="pl")
    assert u.sentiment >= -0.1 and u.emotion in ("neutral", "satisfied"), (text, u.sentiment, u.emotion)


@pytest.mark.parametrize("text", ["ty kutasie", "Jesteście palanci", "To jest hujowe", "Co za jebany bałagan", "gówniana obsługa", "Kurczę, znowu nie działa", "To mnie męczy", "Męczące to wszystko"])
def test_genuine_insults_and_tiredness_still_read_as_negative(text):
    for variant in (text, strip_text(text)):
        assert analyze(variant, lang_hint="pl").sentiment <= -0.2, variant


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please ship to ul. Długa 5/12, 80-001 Gdańsk", "en"), ("Привіт, де моє замовлення?", "uk"), ("Wo ist meine Bestellung, bitte schnell", "de"),
    ],
)
def test_langid_names_and_polish_street_abbreviations_do_not_make_other_languages_polish(text, expected):
    assert detect_language(text)[0] == expected, text


@pytest.mark.parametrize("text", ["Ahoj, kde je moje objednávka?", "Kde je moja objednávka?", "Dober dan, kje je moje naročilo?", "Dobar dan, gdje je moja narudžba?", "Kde je moje objednavka, dekuji"])
def test_langid_czech_slovak_slovenian_and_croatian_are_not_polish(text):
    lang, conf = detect_language(text, default="en")
    assert lang != "pl" or conf < 0.45, (text, lang, conf)
