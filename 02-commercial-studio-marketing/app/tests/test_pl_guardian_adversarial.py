"""Adversarial QA of the Polish Guardian / claims engine and the Polish voice-over arithmetic: what real copywriters write that the golden cases of
``test_pl_guardian`` do not cover.

Violations: implied and euphemistic health / weight / energy claims in many inflections and word orders, typed without diacritics, in capitals or with
typographic tricks (soft hyphens, zero-width characters, letter-spacing, NBSP, line-break hyphenation), superlatives and comparisons with named competitors,
finance / pharma / alcohol wording. Negative controls: ordinary Polish that merely contains a forbidden stem, negation, wishes, toasts, names, "link w bio",
technical copy. Then: language detection on short copy, English invariance with the Polish pack present, auto-revise that has to end in grammatical Polish,
the AI label and the caffeine line in every typesetting, numbers read out for the voice-over and the "line too long for its beat" arithmetic.
"""

from __future__ import annotations

import pytest

from spotlight.core.guardian_service import auto_revise
from spotlight.domain import polish, timing
from spotlight.domain.claims import ClaimRule
from spotlight.domain.guardian import (
    BrandRules,
    Disclosure,
    GuardianContext,
    GuardianSubject,
    TextItem,
    VoicePack,
    apply_fix,
    build_report,
    revise_once,
    run_rules,
)
from spotlight.domain.rights import RightsEntry
from spotlight.domain.text import detect_lang, fold
from spotlight.features import cs12_guardian as _cs12  # noqa: F401  (registers the offline rewrite that auto-revise falls back to)
from spotlight.seed import data

SUBSTANTIVE = {"claims.prohibited", "claims.needs_substantiation", "claims.missing_disclaimer", "voice.forbidden_word", "voice.hype"}
CAFFEINE = "Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży."


def _context(*, polish_pack: bool = True) -> GuardianContext:
    v = data.KIT["voice"]
    pl = data.KIT["i18n"]["pl"]["voice"]
    claims = [ClaimRule(**{k: x for k, x in c.items() if k in ClaimRule.model_fields}) for c in data.all_claims()]
    return GuardianContext(
        brand=BrandRules(
            palette=[p["hex"] for p in data.PALETTE], forbidden_words=v["forbidden_words"], replacements=v["replacements"], max_exclamations=1,
            packs={"pl": VoicePack(forbidden_words=pl["forbidden_words"], replacements=pl["replacements"], hype_terms=pl["hype_terms"], max_sentence_words=pl["max_sentence_words"])} if polish_pack else {},
        ),
        claims=claims if polish_pack else [c for c in claims if c.lang != "pl"],
        rights=[RightsEntry(**{k: x for k, x in r.items() if k in RightsEntry.model_fields}) for r in data.all_rights()],
        today="2026-11-17",
    )


@pytest.fixture(scope="module")
def ctx() -> GuardianContext:
    return _context()


@pytest.fixture(scope="module")
def ctx_without_polish() -> GuardianContext:
    return _context(polish_pack=False)


def subject(text: str, *, lang: str | None = "pl", kind: str = "vo", category: str = "beverage", markets: tuple[str, ...] = ("PL",), extra: tuple[tuple[str, str], ...] = ()) -> GuardianSubject:
    """``lang=None``: nothing is declared (the ad-hoc API), so the engine has to recognise the language itself."""
    tag = {"lang": lang} if lang else {}
    items = [TextItem(id="t1", kind=kind, text=text, **tag), *(TextItem(id=f"x{i}", kind=k, text=t, **tag) for i, (k, t) in enumerate(extra))]  # type: ignore[arg-type]
    return GuardianSubject(type="script", markets=list(markets), category=category, channels=["youtube"], texts=items, **tag)


def run(ctx_: GuardianContext, text: str, **kw):
    return run_rules(subject(text, **kw), ctx_)


def seen(fs) -> list[tuple[str, str, str]]:
    return [(f.rule_id, f.severity, f.evidence) for f in fs if f.rule_id in SUBSTANTIVE]


def ids(rows) -> list[str]:
    return [(r[0] if isinstance(r, tuple) else r)[:50] for r in rows]


# ------------------------------------------------------------------------------------------------ violations: (text, rule, severity, category)


def _group(rule: str, severity: str, *texts: str, category: str = "beverage") -> list[tuple[str, str, str, str]]:
    return [(t, rule, severity, category) for t in texts]


VIOLATIONS = [
    # cures, relief, prevention: other persons, word orders, clitics, figurative use, nouns and adjectives
    *_group(
        "claims.prohibited", "block",
        "Kawa, która leczy.", "Ta kawa wyleczy Twoje zmęczenie.", "Stres? Wyleczysz go jedną filiżanką.", "Niepokój znika po pierwszym łyku, bo ta kawa go leczy.",
        "Lecząca moc porannej kawy.", "Kawa o właściwościach leczniczych.", "Naturalne lekarstwo na poniedziałkowe zmęczenie.", "Lek na stres w każdym ziarnie.", "Kawa na ból głowy.",
        "Uspokaja nerwy po ciężkim dyżurze.", "Koi nerwy i napięcie.", "Łagodzi objawy przeziębienia.", "Zapobiega chorobom serca.", "Chroni przed infekcjami sezonowymi.",
        "Obniża ciśnienie krwi.", "Reguluje poziom cukru we krwi.", "Zmniejsza ryzyko cukrzycy typu 2.", "Pomaga zapomnieć o stresie.", "Pomaga uporać się z napięciem po pracy.",
        "Pomaga zasnąć po ciężkim dniu.", "Wypij filiżankę i zapomnij o bólu głowy.", "Ulga w bólu głowy już po pierwszym łyku.", "Kawa przeciw migrenie.", "Najlepsza na kaca.",
        "Zapobiega demencji i chorobie Alzheimera.", "Działa przeciwzapalnie.", "Zmniejsza ryzyko zawału.", "Walczy z bezsennością.", "Kawa łagodząca ból brzucha.",
        "Kawa, która leczy duszę.", "Wyleczy każdego kawosza z porannego marazmu.", "Naturalny środek na zmęczenie.", "Chroni komórki przed stresem oksydacyjnym.",
        "Łagodzi ból gardła.", "Eliminuje objawy przemęczenia.", "Dawn Roast leczy poranny niepokuj.",
        # a coordinated complement is part of the claim: replacing half of it would leave "… poranka i napięcie mięśni"
        "Zmniejsza zmęczenie i znużenie.", "Łagodzi ból głowy i napięcie mięśni.", "Likwiduje stres oraz niepokój.", "Chroni przed zawałem i udarem.",
        "Zmniejsza zmęczenie, senność i rozdrażnienie.", "Obniża ciśnienie i poziom cukru.",
    ),
    # EU health claims and their euphemisms (Regulation 1924/2006): only authorised wording is allowed
    *_group(
        "claims.prohibited", "block",
        "Na lepszy sen.", "Poprawia jakość snu.", "Wzmacnia odporność każdego dnia.", "Wspiera odporność w sezonie jesienno-zimowym.", "Wspomaga trawienie po obiedzie.",
        "Poprawia krążenie.", "Dla zdrowego serca.", "Prozdrowotne właściwości zielonej kawy.", "Wzmacnia organizm przed zimą.", "Przyspiesza regenerację mięśni po treningu.",
        "Wspiera pracę mózgu.", "Poprawia nastrój.", "Dbaj o zdrowie z każdą filiżanką.", "Zadbaj o zdrowe jelita.", "Pij zdrowo, żyj zdrowo.", "Dla Twojego zdrowia.",
        "Chroni serce i naczynia krwionośne.", "Zdrowszy poranek zaczyna się od Dawn Roast.", "Herbata ziołowa na sen.", "Kawa na odporność.", "Zioła i kawa na trawienie.",
        "Lepsza pamięć i lepsze samopoczucie.", "Pomaga w trawieniu.", "Dla zdrowych nawyków.", "Zdrowa dawka kofeiny.", "Wspiera zdrowe nawyki.", "Jak zdrowo zacząć dzień?",
        "Wspiera układ odpornościowy zimą.", "Dobra dla Twojego serca.", "Healthy start dnia.", "Superfood z Etiopii.", "Nasz superfood na każdy poranek.",
        "Antyoksydanty w każdej filiżance.", "Dla diabetyków.",
    ),
    # weight, detox
    *_group(
        "claims.prohibited", "block",
        "Ta kawa odchudza.", "Odchudzająca kawa na poranek.", "Spalaj tłuszcz z każdą filiżanką.", "Kawa, która spala kalorie.", "Przyspiesza metabolizm.", "Przyspiesz przemianę materii.",
        "Naturalny detoks.", "Detoksykujący poranek.", "Oczyszcza organizm z toksyn.", "Odtruwa organizm po weekendzie.", "Wspiera odchudzanie.", "Pomaga schudnąć bez wysiłku.",
        "Zrzuć zbędne kilogramy z Dawn Roast.", "Kawa na odchudzanie.", "Wspomaga redukcję tkanki tłuszczowej.", "Burn fat: spalaj tłuszcz od rana.", "Wyszczuplająca kawa.",
        "Idealna na diecie redukcyjnej.", "Zielona kawa, która odchudza.", "Detoksykuje wątrobę i nerki.", "Detox blend na poranek.", "Cold brew detox.", "Detox your morning.",
    ),
    # environmental claims
    *_group(
        "claims.prohibited", "block",
        "Neutralna dla klimatu.", "Kawa neutralna węglowo.", "Opakowanie przyjazne środowisku.", "Dobra dla planety.", "Zero emisji CO₂.", "Bez śladu węglowego.", "W 100% zrównoważona.",
        "Nasze eco-friendly opakowanie.",
    ),
    # authority and certificates need documents
    *_group(
        "claims.needs_substantiation", "block",
        "Klinicznie przebadana.", "Klinicznie udowodnione działanie.", "Potwierdzone badaniami naukowymi.", "Polecana przez lekarzy.", "Lekarze polecają.", "9 na 10 lekarzy poleca Dawn Roast.",
        "Rekomendowana przez dietetyków.", "Naukowo udowodniona skuteczność.", "Testowana klinicznie.", "Zalecana przez specjalistów.", "Sprawdzona przez lekarzy.", "Zatwierdzona przez dietetyków.",
        "Ekologiczna palarnia.", "Eko-opakowanie na Twoją kawę.", "Kawa z certyfikatem Fairtrade.", "Bio kawa z Etiopii.", "Etycznie pozyskiwana kawa.",
        "Kawa organiczna z Gwatemali.", "Euroliść na każdej torbie.", "Z certyfikatem Rainforest Alliance.", "Kawa z certyfikatem UTZ.",
    ),
    # superlatives, absolutes, comparisons with named competitors, free-from claims (a warning: "needs a source")
    *_group(
        "claims.needs_substantiation", "warn",
        "Najlepsza kawa na świecie.", "Najlepsza w Polsce.", "Numer 1 w Polsce.", "Nr 1 wśród kaw ziarnistych.", "Numer jeden.", "Jedyna taka kawa.", "Jedyna taka.", "Bezkonkurencyjny aromat.",
        "Niezrównany smak.", "Idealna dla każdego.", "Lepsza niż Starbucks.", "Smaczniejsza od kawy z Costa Coffee.", "Lepsza niż Nescafé i Jacobs razem wzięte.", "Nie ma lepszej kawy.",
        "Lider wśród palarni w Polsce.", "Najczęściej wybierana kawa w Polsce.", "Najlepszy wybór dla kawoszy.", "Najbardziej aromatyczna kawa w mieście.", "Najlepsza kawa świata.",
        "Najlepsza kawa pod słońcem.", "Kawa roku 2026.", "Najlepsza kawa, jaką piłeś.", "100% naturalna.", "Bez cukru.", "Naturalny skład, bez konserwantów.", "W 100% naturalna kawa.",
        "Pierwsza kawa w Polsce bez kofeiny.", "Pierwszy w Polsce zimny napar z certyfikatem smaku.", "Pierwsza w Polsce palarnia kawy bez kofeiny.", "Niskokaloryczna kawa na każdą porę.",
        "Zero kalorii, zero wyrzutów.", "Zero cukru.", "0% cukru.",
    ),
    # brand-voice forbidden words (stem + ending classes; "tani" is forbidden in every form and degree)
    *_group(
        "voice.forbidden_word", "block",
        "Najtańsza kawa w mieście.", "Tania kawa dla każdego.", "Tanio i smacznie.", "Kup taniej.", "Cudowna kawa na poranek.", "To po prostu cud w filiżance.", "Cudownie pachnie.",
        "Uzależniający aromat.", "Możesz się od niej uzależnić.", "Gwarantujemy świeżość.", "Przełomowa receptura.", "Game changer wśród kaw.", "Life hack na poranek.", "Tańsza niż w kawiarni.",
        "Gwarancja jakości.", "Kawowy hack na wczesne poranki.", "50% taniej!", "T A N I A kawa", "Kawa c u d o w n a",
    ),
    *_group("voice.hype", "warn", "Kawa, która zmienia życie.", "Rewolucyjny smak."),
    # caffeine claims need the caffeine line (and it is the missing line that is reported)
    *_group(
        "claims.missing_disclaimer", "block",
        "Kawa dodaje energii na cały dzień.", "Pobudza lepiej niż budzik.", "Poprawia koncentrację.", "Zwiększa czujność przed ważnym spotkaniem.", "Doładuj baterie przed zmianą.",
        "Stawia na nogi o szóstej rano.", "Daje kopa na cały dzień.", "Dodaje wigoru.", "Obudzi Cię szybciej niż budzik.", "Kofeinowy kop na start dnia.", "Naładuj się energią.",
        "Energia na całą zmianę.", "Boost na poranek.", "Boost energii na cały dzień.", "Lepsza koncentracja od pierwszego łyku.", "Kawa na koncentrację.",
    ),
    # regulated categories
    *_group("claims.prohibited", "block", "Gwarantowany zysk bez ryzyka.", "Zainwestuj dziś — pewny zwrot.", "Nie możesz stracić.", category="finance"),
    *_group("claims.missing_disclaimer", "block", "Zysk 12% w skali roku.", category="finance"),
    *_group("claims.missing_disclaimer", "block", "Skutecznie łagodzi ból.", "Szybko działa.", category="pharma"),
    *_group("claims.prohibited", "block", "Rozkręca każdą imprezę.", "Dodaje odwagi.", "Sukces towarzyski gwarantowany.", category="alcohol"),
]

# lines with nothing recognisably Polish in them once the diacritics are gone: an undeclared language cannot be told, so only the tagged run is expected to catch them
NO_DIACRITICS_GAPS = {"Zrzuć zbędne kilogramy z Dawn Roast.", "Szybko działa."}
# too little Polish in the line to tell it from English when the language is not declared: only the tagged run is expected to catch it
TAGGED_ONLY = [("Atest PZH.", "claims.needs_substantiation", "block", "beverage")]


@pytest.mark.parametrize(("text", "rule", "severity", "category"), [*VIOLATIONS, *TAGGED_ONLY], ids=ids([*VIOLATIONS, *TAGGED_ONLY]))
def test_violation_is_caught_in_tagged_polish_and_without_diacritics(ctx, text, rule, severity, category):
    for variant in (text, fold(text)):
        fs = run(ctx, variant, category=category)
        assert any(f.rule_id == rule and f.severity == severity for f in fs), (variant, seen(fs))


@pytest.mark.parametrize(("text", "rule", "severity", "category"), VIOLATIONS, ids=ids(VIOLATIONS))
def test_violation_is_caught_when_the_language_is_not_declared_and_in_capitals(ctx, text, rule, severity, category):
    variants = [text, text.upper(), *([] if text in NO_DIACRITICS_GAPS else [fold(text)])]
    for variant in variants:
        fs = run(ctx, variant, lang=None, category=category)
        assert any(f.rule_id == rule and f.severity == severity for f in fs), (variant, seen(fs))


TRICKS = {
    "soft hyphens": "Dawn Roast le\u00adczy po\u00adranny nie\u00adpokój.",
    "zero-width space inside the word": "Dawn Roast le\u200bczy niepokój.",
    "zero-width space after the word": "Dawn Roast leczy\u200b poranny niepokój.",
    "letter-spaced": "l e c z y niepokój",
    "letter-spaced capitals": "L E C Z Y   S T R E S",
    "hyphen instead of a space": "leczy-niepokój",
    "capitals": "DAWN ROAST LECZY PORANNY NIEPOKÓJ!",
    "mixed case": "dawn roast lecZy poranny nIePokÓj",
    "NBSP": "Dawn Roast leczy\u00a0poranny\u00a0niepokój.",
    "thin space": "Kawa, która koi\u2009nerwy.",
    "double spaces": "Dawn Roast leczy  poranny   niepokój.",
    "hyphen and line break": "Dawn Roast le-\nczy niepokój.",
    "typographic quotes": "„Dawn Roast leczy niepokój” — mówią klienci.",
}


@pytest.mark.parametrize("text", list(TRICKS.values()), ids=list(TRICKS))
@pytest.mark.parametrize("lang", ["pl", None], ids=["tagged", "undeclared"])
def test_typographic_tricks_do_not_hide_a_claim_and_the_fix_still_applies(ctx, text, lang):
    s = subject(text, lang=lang)
    f = next((f for f in run_rules(s, ctx) if f.rule_id == "claims.prohibited"), None)
    assert f is not None and f.severity == "block"
    assert f.params["span"] in text  # the offsets map back onto the characters the copywriter typed
    if f.fix["op"] == "replace_text":
        assert apply_fix(s, f.fix, ctx)
        assert not [x for x in run_rules(s, ctx) if x.rule_id == "claims.prohibited"], s.texts[0].text


KNOWN_GAPS = [
    ("Dawn Roast leczi poranny niepokój.", "pl", "typos beyond diacritics are not matched"),
    ("Kawa dla dzieci.", "pl", "no rule family for targeting minors (neither in English): the caffeine line says 'niezalecane dla dzieci'"),
    ("Bezpieczna w ciąży.", "pl", "no rule family for pregnancy claims"),
    ("Gratis przy każdym zamówieniu.", "pl", "'gratis' / free-gift offers are not checked for terms"),
    ("Serce będzie Ci wdzięczne.", "pl", "implied cardio benefit without a verb from the pattern families"),
    ("Eko.", None, "one word and no declared language: nothing to tell Polish from English"),
    ("Best coffee w mieście.", None, "English words dominate an undeclared mixed line, so the English rules judge it"),
    ("Atest PZH.", None, "two words with nothing recognisably Polish in an undeclared line"),
]


@pytest.mark.parametrize(("text", "lang", "why"), KNOWN_GAPS, ids=[g[0] for g in KNOWN_GAPS])
@pytest.mark.xfail(strict=True, reason="documented residual gap (see the reason in KNOWN_GAPS)")
def test_known_gaps_stay_documented(ctx, text, lang, why):
    assert seen(run(ctx, text, lang=lang)), why


# ------------------------------------------------------------------------------------------------ negative controls: (text, kind)

NEGATIVES: list[tuple[str, str]] = [
    (t, "vo")
    for t in [
        # compliant brand copy
        "Obudź się powoli.", "Zacznij dzień wolniej.", "Karmel, pomarańcza, kakao. Bez pośpiechu.", "Palona w małych partiach, nalewana bez pośpiechu.", "Średnie palenie, 100% arabiki.",
        "Światło wstaje. Para się unosi. Reszta może poczekać.", "Są poranki, które zasługują na wolniejszy początek.", "Znajdź Dawn Roast w pobliżu.", "Dziesięć cichych minut, zanim dom się obudzi.",
        "Pierwsza filiżanka znaczy najwięcej.", "Pachnie karmelem, skórką pomarańczy i kakao.", "Kawa jak z palarni, tylko w Twojej kuchni.", "Zamów do 14:00, wyślemy jeszcze dziś.",
        "Darmowa dostawa przy zamówieniach od 150 zł.", "Dostępna w sklepach i na northwind.example.", "Kawa, która smakuje jak spokojny poranek.", "Nic nie musi się jeszcze dziać.",
        "Dla tych, którzy wstają przed wszystkimi.", "Pielęgniarka po nocnej zmianie zasługuje na spokojną filiżankę.", "Poranek — rytuał, nie wyścig.", "Dawn Roast® — palona w Gdańsku.",
        "Nie czekaj w kolejce, zamów w aplikacji.", "Bez stresu: wyślemy do domu.", "Mocna jak poniedziałek, łagodna jak niedziela.", "Mocne ziarna, delikatne nuty.",
        "Kawa bez pośpiechu i bez wyrzutów sumienia.", "Słodka jak poniedziałek rano.", "Pij, ile chcesz.", "Najpierw cisza, potem kawa.", "Dawn Roast. Kawa na wolniejszy start.",
        # words that merely CONTAIN a forbidden stem, or look like one
        "Zostanie z Tobą na cały dzień.", "Pytanie brzmi: czarna czy z mlekiem?", "Dostanie Pan prezent do pierwszego zamówienia.", "Przestanie padać, a kawa jeszcze będzie ciepła.",
        "Leczo z cukinii i kawa z kardamonem.", "Weekend w Krynicy-Zdroju i kawa na deptaku.", "Łagodny smak i długi, słodki finisz.", "Energiczny taniec na deszczu, a potem kawa.",
        "Odchudzony wzór opakowania.", "Odchudzona wersja aplikacji ładuje się szybciej.", "Taniec w kuchni o szóstej rano.", "Hackathon w kawiarni, w której kawa jest dodatkiem.",
        "Z rąk palacza prosto do Twojej kuchni.", "Stanowisko do parzenia kawy stoi przy oknie.", "Wstajemy o piątej, bo kawa sama się nie zaparzy.", "Lekki aromat, lekka kwasowość.",
        "Spalona słońcem Etiopia i kawa z jej wzgórz.", "Ziarna z Etiopii i Kolumbii.", "Pałac Kultury i Nauki o świcie.", "Dostępna w sieci Żabka i w sklepach Carrefour Polska.",
        "Zbieramy ziarna w górach Gwatemali.", "Kwiaty kawowca pachną jaśminem.", "Ścieżka do plantacji prowadzi przez las.", "Rzeczna dolina i kawa na brzegu.", "Gwar kawiarni i szum ekspresu.",
        "Najpierw kawa, potem cała reszta.", "Najwięcej radości daje pierwszy łyk.", "Najlepsze życzenia z okazji Dnia Kobiet!", "Wszystkiego najlepszego w nowym roku.",
        "Najlepsze rzeczy dzieją się powoli.", "To najlepszy moment na pierwszą filiżankę.", "Pierwszy w kolejce dostaje najlepszy stolik.", "Zamówienie nr 1042 jest w drodze.",
        "Numer telefonu: 22 555 01 66.", "Kawiarnia przy ulicy Długiej 1.", "Poranek w Tanzanii pachnie ziemią.", "Kawa z Costa Rica, palona w Gdańsku.", "Kupisz ją w Costa Rica? Nie, w Gdańsku.",
        "Zbieramy ziarna w Kostaryce i Etiopii.", "Zielona herbata i zielona kawa.", "Kawa neutralna w smaku.", "Zdrowa dawka humoru na dobry początek.",
        # idioms, negation, wishes, toasts, reported speech about what the brand does NOT claim
        "Na zdrowie!", "Zdrowie! — mówi sąsiad i unosi kubek.", "„Zdrowie!” — mówi sąsiad i unosi kubek.", "Za Wasze zdrowie, drodzy goście!", "Zdrowia i radości w Nowym Roku!",
        "Życzymy Wam zdrowych i spokojnych Świąt.", "Wesołych Świąt i dużo zdrowia w nowym roku!", "Kawa nie leczy chorób, to po prostu dobra kawa.", "Kawa nie jest lekiem. To kawa.",
        "Nie obiecujemy cudów. Obiecujemy dobrą kawę.", "Bez cudów na kiju — tylko ziarno, ogień i czas.", "Nie ma cudów: dobra kawa potrzebuje czasu.", "Kawa nie odchudza i nie leczy — po prostu smakuje.",
        "To nie jest tania kawa, ale każdy grosz ma sens.", "Zdrowy rozsądek podpowiada: wypij filiżankę teraz.", "Zachowaj zdrowy dystans do poniedziałku.", "Zdrowa konkurencja nas motywuje.",
        "Kawa nie jest detoksem i nie zastępuje snu.", "Bez lifehacków i bez skrótów.", "Żadnych cudownych obietnic.", "Nie twierdzimy, że kawa leczy. Twierdzimy, że jest smaczna.",
        "Nigdy nie mówimy, że kawa odchudza.", "Kawa nie wzmacnia odporności — po prostu smakuje.", "Czas leczy rany, a kawa dodaje im smaku.", "Nic nie leczy poniedziałku tak jak niedziela.",
        "Czy kawa leczy? Nie. Ale poprawia poranek.", "Mamy zdrowo zakręcony zespół baristów.",
        # ordinary verbs of the claim families used about things that are not health, weight or energy
        "Pomaga w wyborze kawy nasz barista.", "Chroni aromat szczelna torba.", "Wspiera lokalnych rolników.", "Poprawia smak każdej kanapki.", "Dbamy o jakość ziaren.",
        "Wzmacniamy relacje z plantatorami.", "Budujemy zaufanie, filiżanka po filiżance.", "Zwiększamy dostępność kawy w sklepach.", "Eliminujemy plastik z opakowań.",
        "Muzyka buduje nastrój poranka.", "Chroni przed deszczem solidny parasol.", "Wspiera nas sąsiedzka palarnia.", "Poprawia się pogoda, poprawia się humor.", "Obniżyliśmy cenę kawy do 29 zł.",
        "Zmniejsza zużycie wody i energii w palarni.", "Zmniejszamy ilość odpadów i emisję spalin.", "Redukujemy opakowania i koszty dostawy.", "Eliminuje kolejki i czekanie na zamówienie.",
        "Zmniejsza liczbę kliknięć do zamówienia.", "Chroni przed deszczem i wiatrem.", "Obniża ceny dostawy dla stałych klientów.", "Poprawia się komfort pracy baristy.",
        "Pierwszy raz w Polsce? Zacznij od małej czarnej.", "W pierwszym tygodniu w Polsce kupiłem ekspres.", "Stres kolejki? Zamów w aplikacji.", "Palarnia zasilana energią słoneczną.",
        "Zużywamy mniej energii dzięki nowemu piecowi.", "Lekarz polecił mi odpoczynek, a barista kawę.", "Ekspert od palenia kawy opowiada o swojej pracy.",
        # social media, technical and numeric copy, mixed Polish–English wording
        "Link w bio.", "Zamów — link w bio!", "Więcej w naszym bio na Instagramie.", "#DawnRoast #ObudźSięPowoli #kawa", "Ekspres sam reguluje ciśnienie wody.", "Ciśnienie w ekspresie: 9 barów.",
        "Dziewięć barów ciśnienia i trzydzieści sekund parzenia.", "Obniżka cen. Zero stresu przy zakupach.", "340 g kawy, 18 godzin parzenia, 250 ml w puszce.", "Cena od 39,99 zł za 340 g.",
        "12 filiżanek z jednej torby.", "Otwarte od 7:00 do 19:00.", "Od 1 do 5 stopni palenia.", "Poziom palenia: średni.", "Kwasowość na poziomie 7 w skali 10.", "Cold brew w puszce, bez pośpiechu.",
        "Single origin z Etiopii.", "Specialty coffee od małej palarni.", "Flat white na dobry początek dnia.", "Barista poleca filtr z Kolumbii.", "Slow morning, slow coffee.",
        "Pour-over dla cierpliwych.", "Dawn Roast — single origin, small batch.", "Brunch w niedzielę, kawa w sobotę.", "Dla każdego, kto lubi kawę.", "Dla wszystkich, którzy wstają wcześnie.",
        "Idealna na początek dnia.", "Kawa, którą pamiętasz.", "Kawa jak z dzieciństwa.", "Dla dużych i małych — filiżanka mleka z odrobiną kawy zbożowej.", "Gwarancja: 24 miesiące na ekspres.",
        # typographic noise in compliant copy
        "„Obudź się powoli” — tak brzmi nasze hasło.", "Dawn\u00a0Roast — kawa na\u00a0wolniejszy początek.", "Obudź się powoli…", "Po\u00adranna kawa bez po\u00adśpie\u00adchu.", "Kawa\u200b i cisza\u200b.",
    ]
] + [
    ("Zdrowo Żywieni sp. z o.o., ul. Długa 5, 80-001 Gdańsk.", "super"),
    ("Zdrowo Żywieni sp. z o.o. — dystrybutor kawy.", "cta"),
    (CAFFEINE, "legal"),
    ("Źródło: northwind.example/sustainability/fair-trade-2026", "legal"),
    ("„Fairtrade” jest znakiem towarowym Fairtrade International.", "legal"),
    ("Produkt nie jest lekiem i nie służy do leczenia chorób.", "legal"),
    ("Kawa nie leczy, nie zapobiega chorobom i nie zastępuje zdrowej diety.", "legal"),
]


@pytest.mark.parametrize(("text", "kind"), NEGATIVES, ids=ids(NEGATIVES))
def test_compliant_polish_is_not_flagged_declared_or_not_with_or_without_diacritics(ctx, text, kind):
    for lang in ("pl", None):
        for variant in (text, fold(text)):
            fs = seen(run(ctx, variant, lang=lang, kind=kind))
            assert not fs, (variant, lang, fs)


def test_the_negative_set_is_big_enough_to_mean_something():
    assert len(NEGATIVES) >= 160 and len({t for t, _ in NEGATIVES}) == len(NEGATIVES)


# ------------------------------------------------------------------------------------------------ language detection on short copy

POLISH_COPY = [
    "Dzień dobry", "Dzięki!", "kawa", "dziekuje bardzo", "Znajdź nas w pobliżu", "nie wiem co robić", "kiedy będzie premiera?", "prosze o oferte", "Czy kawa zawiera kofeinę?", "Kup teraz",
    "Pielęgniarka na wczesnej zmianie", "zamow kawe", "Obudz sie powoli", "Tani i cudowny detoks", "Bez pośpiechu", "Słońce wschodzi nad torbą", "niepokoj", "Na zdrowie!", "Poznaj naszą historię",
    "Nasza palarnia znajduje się w Gdańsku", "Szukasz idealnego prezentu?", "Nowy smak już w sprzedaży", "Zapisz się do newslettera", "Do zobaczenia jutro rano!", "Smacznego",
    "Dawn Roast leczy poranny niepokoj", "Ta kawa odchudza", "Kawa lagodzi stres",
]
OTHER_COPY = [
    "Wake up slowly.", "Doctor recommended.", "Clinically proven to boost energy.", "Better than Starbucks.", "Find Dawn Roast near you.", "Roasted in small batches, poured without hurry.",
    "Wach langsam auf.", "Réveillez-vous lentement", "Café de tueste medio", "Svegliati piano", "Goedemorgen, wij branden sinds 2011 in kleine batches", "Dobrý den, děkuji vám za objednávku",
    "Buenos días, tostamos en pequeños lotes desde 2011", "Wir rösten seit 2011 in kleinen Chargen", "Szia, kérek egy kávét",
]


@pytest.mark.parametrize("text", POLISH_COPY, ids=ids(POLISH_COPY))
def test_short_polish_copy_is_recognised(text):
    assert detect_lang(text) == "pl"


@pytest.mark.parametrize("text", OTHER_COPY, ids=ids(OTHER_COPY))
def test_english_and_other_languages_are_never_taken_for_polish(text):
    assert detect_lang(text) != "pl"


ENGLISH_LINES = [
    "Dawn Roast cures morning anxiety.", "A cheap boost of energy for the early shift.", "Wake up slowly.", "A healthy start to your day.", "The best coffee in the world.", "Number one coffee in the US.",
    "Clinically proven to boost energy.", "Doctor recommended.", "Burns fat and detoxes your body.", "Carbon neutral and eco-friendly packaging.", "Organic, fair trade certified coffee.",
    "Guaranteed returns, no risk.", "A game changer for your morning ritual.", "Stress relief and better sleep with every cup.", "Improves focus and concentration.", "Supports your immune system.",
    "Treats headaches and migraine.", "Lose weight fast with green coffee.", "Superfood blend for everyone.", "Better than Starbucks.", "Only today: 50% off.", "Link in bio.", "Our bio is on the profile page.",
    "Contains caffeine. Not recommended for children or pregnant women.", "Roasted in small batches, poured without hurry.", "100% Arabica from Colombia, Ethiopia and Guatemala.", "Costa Rica Tarrazu",
    "Nescafe Gold", "Tanzania Peaberry", "Hotel Bristol Warsaw", "Wroclaw office opening", "Miracle in a cup.", "Addictive aroma.", "Guaranteed freshness.",
]


def _signature(fs):
    return [(f.rule_id, f.severity, f.evidence, f.fix) for f in fs]


@pytest.mark.parametrize("text", ENGLISH_LINES, ids=ids(ENGLISH_LINES))
def test_english_copy_is_judged_the_same_with_and_without_the_polish_pack(ctx, ctx_without_polish, text):
    for lang in ("en", None):
        for kind in ("vo", "headline", "legal"):
            kw = {"lang": lang, "kind": kind, "markets": ("US", "DE")}
            assert _signature(run(ctx, text, **kw)) == _signature(run(ctx_without_polish, text, **kw)), (text, lang, kind)


# ------------------------------------------------------------------------------------------------ auto-revise: the output has to be grammatical Polish

# deterministic rewrites (no LLM): the replacement agrees with the words around it, or there is none and the line is left for the LLM
DETERMINISTIC_REVISIONS = [
    ("Dawn Roast leczy poranny niepokój.", "beverage", "Dawn Roast daje spokojniejszy początek poranka."),
    ("Koi nerwy i napięcie.", "beverage", "Daje spokojniejszy początek poranka."),
    ("Zmniejsza zmęczenie i znużenie.", "beverage", "Daje spokojniejszy początek poranka."),
    ("Łagodzi ból głowy i napięcie mięśni.", "beverage", "Daje spokojniejszy początek poranka."),
    ("Zmniejsza zmęczenie, senność i rozdrażnienie.", "beverage", "Daje spokojniejszy początek poranka."),
    ("Kawa, która leczy.", "beverage", "Kawa, która daje spokojniejszy początek poranka."),
    ("Uspokaja nerwy po ciężkim dyżurze.", "beverage", "Daje spokojniejszy początek poranka po ciężkim dyżurze."),
    ("Wspiera odporność w sezonie jesienno-zimowym.", "beverage", "Daje spokojniejszy początek poranka w sezonie jesienno-zimowym."),
    ("Ta kawa odchudza.", "beverage", "Ta kawa jest częścią zbilansowanego poranka."),
    ("Kawa, która spala kalorie.", "beverage", "Kawa, która jest częścią zbilansowanego poranka."),
    ("Zielona kawa, która odchudza.", "beverage", "Zielona kawa, która jest częścią zbilansowanego poranka."),
    ("Naturalny detoks.", "beverage", "Naturalny rytuał."),
    ("Najtańsza kawa w mieście.", "beverage", "Przystępna kawa w mieście."),
    ("Tania kawa dla każdego.", "beverage", "Przystępna kawa dla każdego."),
    ("Tanio i smacznie.", "beverage", "W dobrej cenie i smacznie."),
    ("Tańsza niż w kawiarni.", "beverage", "Korzystniejsza niż w kawiarni."),
    ("Cudownie pachnie.", "beverage", "Wyjątkowo pachnie."),
    ("Uzależniający aromat.", "beverage", "Łatwy do pokochania aromat."),
    ("Gwarantujemy świeżość.", "beverage", "Dbamy o świeżość."),
    ("Game changer wśród kaw.", "beverage", "Mile widziana zmiana wśród kaw."),
    ("Najlepsza kawa na świecie.", "beverage", "Kawa, z której jesteśmy dumni."),
    ("Zero cukru.", "beverage", "Kawa, z której jesteśmy dumni."),
    ("Klinicznie przebadana.", "beverage", "Palona z troską."),
    ("Dla zdrowych nawyków.", "beverage", "Dla niespiesznych nawyków."),
    ("Jak zdrowo zacząć dzień?", "beverage", "Jak niespiesznie zacząć dzień?"),
    ("Wspiera zdrowe nawyki.", "beverage", "Wspiera niespieszne nawyki."),
    ("Dbaj o zdrowie z każdą filiżanką.", "beverage", "Dbaj o spokój z każdą filiżanką."),
    ("Pij zdrowo, żyj zdrowo.", "beverage", "Pij niespiesznie, żyj niespiesznie."),
    ("Zdrowszy poranek zaczyna się od Dawn Roast.", "beverage", "Spokojniejszy poranek zaczyna się od Dawn Roast."),
    ("Prozdrowotne właściwości zielonej kawy.", "beverage", "Smakowe właściwości zielonej kawy."),
    ("Ekologiczna palarnia.", "beverage", "Starannie wybierana palarnia."),
    ("Kawa organiczna z Gwatemali.", "beverage", "Kawa starannie wybierana z Gwatemali."),
    ("Gwarantowany zysk bez ryzyka.", "finance", "Możliwy zysk z ryzykiem utraty kapitału."),
    ("Zainwestuj dziś — pewny zwrot.", "finance", "Zainwestuj dziś — możliwy zwrot."),
    ("Nie możesz stracić.", "finance", "Możesz stracić."),
    ("Rozkręca każdą imprezę.", "alcohol", "Do picia z umiarem."),
    ("Sukces towarzyski gwarantowany.", "alcohol", "Do picia z umiarem."),
    ("Dawn Roast le\u00adczy po\u00adranny nie\u00adpokój.", "beverage", "Dawn Roast daje spokojniejszy początek poranka."),
    ("DAWN ROAST LECZY PORANNY NIEPOKÓJ!", "beverage", "DAWN ROAST DAJE SPOKOJNIEJSZY POCZĄTEK PORANKA!"),
    ("Dawn Roast le-\nczy niepokój.", "beverage", "Dawn Roast daje spokojniejszy początek poranka."),
    ("„Dawn Roast leczy niepokój” — mówią klienci.", "beverage", "„Dawn Roast daje spokojniejszy początek poranka” — mówią klienci."),
]


@pytest.mark.parametrize(("text", "category", "expected"), DETERMINISTIC_REVISIONS, ids=ids(DETERMINISTIC_REVISIONS))
def test_deterministic_revision_is_grammatical_polish_and_compliant(ctx, text, category, expected):
    s = subject(text, category=category)
    for _ in range(4):
        if not revise_once(s, run_rules(s, ctx), ctx):
            break
    assert s.texts[0].text == expected
    assert build_report(s, ctx).verdict != "block", seen(run_rules(s, ctx))


@pytest.mark.parametrize(
    ("text", "op"),
    [
        ("Dawn Roast leczy poranny niepokój.", "replace_text"),
        ("Niepokój znika po pierwszym łyku, bo ta kawa go leczy.", "llm_rewrite"),  # "go leczy": the clitic would be left stranded
        ("Kawa na ból głowy.", "llm_rewrite"),  # a noun phrase, not a verb: "daje spokojniejszy początek poranka" would not fit
        ("Kup taniej.", "llm_rewrite"),  # "taniej" has no agreeing stand-in
        ("Pierwsza kawa w Polsce bez kofeiny.", "llm_rewrite"),  # a replacement noun phrase cannot take the hanging "bez kofeiny"
        ("Best coffee w mieście.", "llm_rewrite"),
    ],
)
def test_a_rewrite_is_deterministic_only_when_it_is_grammatical(ctx, text, op):
    fixes = {f.fix["op"] for f in run(ctx, text) if f.rule_id in SUBSTANTIVE and f.fix}
    assert fixes == {op}


REVISE_CONVERGES = [
    ("Dawn Roast leczy poranny niepokój.", "beverage"), ("Kawa na ból głowy.", "beverage"), ("Niepokój znika po pierwszym łyku, bo ta kawa go leczy.", "beverage"),
    ("Stres? Wyleczysz go jedną filiżanką.", "beverage"), ("Wypij filiżankę i zapomnij o bólu głowy.", "beverage"), ("Kup taniej.", "beverage"), ("Najlepsza kawa na świecie.", "beverage"),
    ("Pierwsza kawa w Polsce bez kofeiny.", "beverage"), ("Best coffee w mieście.", "beverage"), ("Zero kalorii, zero wyrzutów.", "beverage"), ("Lekarze polecają.", "beverage"),
    ("9 na 10 lekarzy poleca Dawn Roast.", "beverage"), ("Kawa z certyfikatem Fairtrade.", "beverage"), ("Neutralna dla klimatu.", "beverage"), ("Poprawia pamięć i koncentrację.", "beverage"),
    ("Boost na poranek.", "beverage"), ("Detox blend na poranek.", "beverage"), ("Healthy start dnia.", "beverage"), ("Dla diabetyków.", "beverage"), ("Antyoksydanty w każdej filiżance.", "beverage"),
    ("Zmniejsza zmęczenie, senność i rozdrażnienie.", "beverage"), ("l e c z y niepokój", "beverage"), ("Dawn Roast le\u00adczy po\u00adranny nie\u00adpokój.", "beverage"),
    ("DAWN ROAST LECZY PORANNY NIEPOKÓJ!", "beverage"), ("Uzależniający aromat.", "beverage"), ("Zdrowa dawka kofeiny.", "beverage"), ("Superfood z Etiopii.", "beverage"),
    ("Euroliść na każdej torbie.", "beverage"), ("Ekologiczna palarnia.", "beverage"), ("Najtańsza kawa w mieście.", "beverage"), ("Zdrowy początek twojego dnia.", "beverage"),
    ("Gwarantowany zysk bez ryzyka.", "finance"), ("Zysk 12% w skali roku.", "finance"), ("Skutecznie łagodzi ból.", "pharma"), ("Szybko działa.", "pharma"),
    ("Rozkręca każdą imprezę.", "alcohol"), ("Sukces towarzyski gwarantowany.", "alcohol"), ("Dodaje odwagi.", "alcohol"),
]


async def test_auto_revise_converges_to_compliant_polish_without_new_violations(services):
    problems = []
    for text, category in REVISE_CONVERGES:
        res = await auto_revise(services, subject(text, category=category))
        live = [f for f in res["report"].findings if not f.waived]
        first = set(res["iterations"][0]["findings"])
        new = {f.rule_id for f in live if f.rule_id in SUBSTANTIVE} - first
        revised = res["subject"].texts[0].text
        if res["report"].verdict == "block" or new or not revised.strip() or detect_lang(revised) == "en" or (text[:1].isalpha() and revised[:1].isupper() != text[:1].isupper()):
            problems.append((text, revised, res["report"].verdict, sorted(new)))
    assert not problems, problems


# ------------------------------------------------------------------------------------------------ AI-disclosure label and the caffeine line, however they are typeset


def _spot(label: str | None, *, shown: bool = True) -> GuardianSubject:
    return GuardianSubject(
        type="spot", has_video=True, captions_present=True, markets=["PL"], channels=["youtube"], category="beverage", lang="pl",
        disclosure=Disclosure(ai_generated=True, label_present=shown, label_text=label), texts=[],
    )


@pytest.mark.parametrize(
    "label",
    ["Wygenerowano przez AI", "Wygenerowano przez AI.", "wygenerowano przez ai", "WYGENEROWANO PRZEZ AI", "Wygenerowano\u00a0przez\u00a0AI", "  Wygenerowano   przez AI  ", "Wygenerowano przez\u00a0AI", None],
)
def test_the_polish_ai_label_is_recognised_however_it_is_typeset(ctx, label):
    assert not {f.rule_id for f in run_rules(_spot(label), ctx)} & {"disclosure.missing_label", "disclosure.label_language"}


@pytest.mark.parametrize("label", ["AI-generated", "Made with AI", "Wygenerowane przez AI"])
def test_a_label_in_the_wrong_wording_is_flagged_with_the_polish_badge_as_the_fix(ctx, label):
    f = next(f for f in run_rules(_spot(label), ctx) if f.rule_id == "disclosure.label_language")
    assert f.fix and f.fix["text"] == "Wygenerowano przez AI"


def test_a_missing_ai_label_blocks_and_names_the_polish_badge(ctx):
    f = next(f for f in run_rules(_spot(None, shown=False), ctx) if f.rule_id == "disclosure.missing_label")
    assert f.severity == "block" and f.evidence == "Wygenerowano przez AI"


@pytest.mark.parametrize(
    "legal",
    [CAFFEINE, fold(CAFFEINE), CAFFEINE.upper(), CAFFEINE.replace(" ", "\u00a0"), "Zawiera ko\u00adfeinę. Niezalecane dla dzieci i kobiet w ciąży.", "  Zawiera kofeinę.   Niezalecane dla dzieci i kobiet w ciąży.  ",
     CAFFEINE + " Pij z umiarem.", "Zawiera kofeinę! Niezalecane dla dzieci i kobiet w ciąży"],
)
@pytest.mark.parametrize("kind", ["legal", "super"])
def test_the_caffeine_line_satisfies_the_disclaimer_however_it_is_typeset_and_wherever_it_is_shown(ctx, legal, kind):
    fs = run(ctx, "Kawa dodaje energii na cały dzień.", extra=((kind, legal),))
    assert "claims.missing_disclaimer" not in {f.rule_id for f in fs}


@pytest.mark.parametrize(
    ("kind", "legal"),
    [("vo", CAFFEINE), ("legal", "Zawiera kofeinę."), ("legal", "Niezalecane dla dzieci i kobiet w ciąży."), ("legal", "Pij odpowiedzialnie.")],
    ids=["only spoken, never on the end card", "half of the line", "the other half", "another regulated line"],
)
def test_a_caffeine_claim_stays_blocked_when_the_line_is_not_really_there(ctx, kind, legal):
    fs = run(ctx, "Kawa dodaje energii na cały dzień.", extra=((kind, legal),))
    assert "claims.missing_disclaimer" in {f.rule_id for f in fs if f.severity == "block"}


# ------------------------------------------------------------------------------------------------ voice-over: numbers read out, typography, timing

TTS = [
    ("Zadzwoń: 22 555 01 66.", "Zadzwoń: dwa dwa, pięć pięć pięć, zero jeden, sześć sześć."),
    ("Tel. 600 100 200", "telefon sześć zero zero, jeden zero zero, dwa zero zero"),
    ("Kod pocztowy 80-001 Gdańsk", "Kod pocztowy osiemdziesiąt, zero zero jeden Gdańsk"),
    ("Otwarte od 7:00 do 19:00.", "Otwarte od siódmej do dziewiętnastej."),
    ("Czynne 7:00-19:00", "Czynne od siódmej do dziewiętnastej"),
    ("Czynne od 7 do 19", "Czynne od siódmej do dziewiętnastej"),
    ("Otwarte od 10 do 18.", "Otwarte od dziesiątej do osiemnastej."),
    ("Zniżka od 7 do 19 zł", "Zniżka od siedmiu do dziewiętnastu złotych"),  # not opening hours: a price range
    ("Zamów do 14:30.", "Zamów do czternastej trzydzieści."),
    ("W 2026 r. otwieramy trzy kawiarnie.", "W dwa tysiące dwudziestym szóstym roku otwieramy trzy kawiarnie."),
    ("Parzymy przez 21 godzin.", "Parzymy przez dwadzieścia jeden godzin."),
    ("3. miejsce w rankingu", "trzecie miejsce w rankingu"),
    ("Wi-Fi 5G, druk 3D i papier A4", "Wi-Fi 5G, druk 3D i papier A4"),
    ("Temperatura −5 °C", "Temperatura minus pięć stopni Celsjusza"),
    ("-50% tylko dziś", "minus pięćdziesiąt procent tylko dziś"),
    ("1/2 kilograma", "pół kilograma"),
    ("Czynne 24/7", "Czynne dwadzieścia cztery na siedem"),
    ("dr Anna Nowak i prof. Kowalski", "doktor Anna Nowak i profesor Kowalski"),
    ("2 kawy", "dwie kawy"),
    ("22 kawy", "dwadzieścia dwie kawy"),
    ("5 kaw", "pięć kaw"),
    ("Adres: ul. Marszałkowska 12/4, 00-001 Warszawa", "Adres: ulica Marszałkowska dwanaście łamane przez cztery, zero zero, zero zero jeden Warszawa"),
    ("Znajdziesz nas przy ul. Długiej 5 w Gdańsku.", "Znajdziesz nas przy ulicy Długiej pięć w Gdańsku."),
    ("Spotkajmy się na pl. Zamkowym.", "Spotkajmy się na placu Zamkowym."),
    # after od / do / bez / dla / poniżej the numeral is genitive too; elsewhere it is not
    ("Kawa od 39 zł", "Kawa od trzydziestu dziewięciu złotych"),
    ("Zapłać 39 zł", "Zapłać trzydzieści dziewięć złotych"),
    ("Cena od 39,99 zł za 340 g.", "Cena od trzydziestu dziewięciu złotych dziewięćdziesięciu dziewięciu groszy za trzysta czterdzieści gramów"),
    ("Do 150 zł zniżki", "Do stu pięćdziesięciu złotych zniżki"),
    ("Poniżej 1 000 zł", "Poniżej tysiąca złotych"),
    ("Od 2 500 zł", "Od dwóch tysięcy pięciuset złotych"),
    ("Od 21 zł", "Od dwudziestu jeden złotych"),
    ("Od 1 zł", "Od jednego złotego"),
    ("Od 120 tys. zł", "Od stu dwudziestu tysięcy złotych"),
    ("Od 2 do 5 minut", "Od dwóch do pięciu minut"),
    ("5-10 min parzenia", "pięć do dziesięciu minut parzenia"),
    ("Do 24 godzin dostawa", "Do dwudziestu czterech godzin dostawa"),
    ("Zestaw dla 2 osób", "Zestaw dla dwóch osób"),
    ("Zestaw dla 1 osoby", "Zestaw dla jednej osoby"),
    ("Rabat od 20%", "Rabat od dwudziestu procent"),
    ("od 250 g do 1 kg", "od dwustu pięćdziesięciu gramów do jednego kilograma"),
    ("Przez 18 godzin", "Przez osiemnaście godzin"),
]


@pytest.mark.parametrize(("written", "spoken"), TTS, ids=ids(TTS))
def test_numbers_units_prices_times_and_addresses_are_read_out_in_grammatical_polish(written, spoken):
    assert polish.tts_text(written) == spoken
    assert polish.tts_text(polish.typeset(written)) == spoken  # NBSP typography never changes how a line is read


def test_typeset_keeps_abbreviations_years_and_numbers_with_what_they_belong_to():
    nb = polish.NBSP
    out = polish.typeset("W 2026 r. otwieramy kawiarnię przy ul. Długiej, tel. 600 100 200, ok. 200 g, dr Anna Nowak, nr 5.")
    assert f"2026{nb}r." in out and f"ul.{nb}Długiej" in out and f"tel.{nb}600{nb}100{nb}200" in out and f"ok.{nb}200{nb}g" in out and f"dr{nb}Anna" in out and f"nr{nb}5" in out
    assert polish.typeset("Wszystko OK. Dalej nic.") == "Wszystko OK. Dalej nic."  # a sentence end is not glued
    assert polish.typeset("Daj im Dawn Roast.") == f"Daj im Dawn{nb}Roast."  # "im" without a dot is the pronoun, not an abbreviation


@pytest.mark.parametrize(
    "line",
    ["Obudź się powoli.", "Dawn Roast. Palona w małych partiach, nalewana bez pośpiechu.", "Palona w małych partiach, nalewana bez pośpiechu, z dziewięcioma barami ciśnienia i szczyptą cierpliwości.",
     "Nasza palarnia w Gdańsku zaprasza codziennie od 7:00 do 19:00."],
)
def test_plain_polish_copy_is_estimated_at_a_comfortable_advertising_pace(line):
    cps = len(line) / timing.estimate_vo_seconds(line, "pl")
    assert 12.0 <= cps <= 16.0, cps  # about 13-15 characters a second, pauses included


def test_numbers_are_timed_as_they_are_spoken_not_as_they_are_written():
    for line in ("Cena od 39,99 zł za 340 g.", "Zadzwoń: 22 555 01 66."):
        assert timing.estimate_vo_seconds(line, "pl") > 3.5  # six written tokens, seventeen spoken words
    assert timing.beat_fit({"t_start": 0, "t_end": 3, "vo": "Cena od 39,99 zł za 340 g."}, "pl")["too_long"]
    assert not timing.beat_fit({"t_start": 0, "t_end": 3, "vo": "Obudź się powoli."}, "pl")["too_long"]
    long_line = "Palona w małych partiach, nalewana bez pośpiechu, z dziewięcioma barami ciśnienia i szczyptą cierpliwości."
    assert timing.beat_fit({"t_start": 0, "t_end": 3, "vo": long_line}, "pl")["too_long"]
    assert not timing.beat_fit({"t_start": 0, "t_end": 9, "vo": long_line}, "pl")["too_long"]
