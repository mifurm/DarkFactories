"""Polish content of the synthetic analytics history (CC-12 / CC-10 / CC-14 / CC-15).

Every record of the base generator keeps its id, numbers and English `summary` (so clustering, QA, metrics and the planted "damaged on delivery"
spike do not move by a single digit) and gains `summary_pl`, the same wrap-up summary in Polish, so a Polish operator reads every record in Polish.
The records of the PL market additionally carry a Polish customer opening message in `text`. Nothing here draws a random number: the Polish
variant is picked by the index of the English template the base generator already chose, and the opening message by the record number - so the
data is deterministic and the English fields stay byte-identical (proved by a unit test)."""

from __future__ import annotations

from typing import Any

PRODUCT_PL = {
    "3-seater sofa": "sofa 3-osobowa", "oak dining table": "dębowy stół jadalniany", "wardrobe": "szafa", "king-size mattress": "materac king-size", "washing machine": "pralka",
    "bookshelf": "regał na książki", "coffee table": "stolik kawowy", "armchair": "fotel", "dishwasher": "zmywarka", "bed frame": "rama łóżka", "kitchen island": "wyspa kuchenna",
    "floor lamp": "lampa podłogowa",
}  # fmt: skip

TOPIC_LABEL_PL = {
    "order_status": "Gdzie jest moje zamówienie?", "delivery_reschedule": "Zmiana terminu dostawy", "damaged_on_delivery": "Uszkodzenie przy dostawie", "return_request": "Zwrot lub wymiana",
    "refund_status": "Status zwrotu środków", "installation_issue": "Problem z terminem montażu", "warranty_claim": "Reklamacje i naprawy", "billing_dispute": "Płatności i faktury",
    "address_change": "Zmiana adresu dostawy", "product_info": "Pytania o produkt i dostępność", "loyalty_points": "Punkty lojalnościowe i bony", "complaint_service": "Skarga na obsługę",
    "cancel_order": "Anulowanie zamówienia",
}  # fmt: skip

REASON_PL = {
    "order_status": "Powód: śledzenie dostawy i termin", "delivery_reschedule": "Powód: zmiana terminu dostawy", "damaged_on_delivery": "Powód: uszkodzenie towaru przy dostawie",
    "return_request": "Powód: zwrot lub wymiana towaru", "refund_status": "Powód: status i wypłata zwrotu środków", "installation_issue": "Powód: problem z terminem montażu",
    "warranty_claim": "Powód: reklamacja towaru", "billing_dispute": "Powód: spór o płatność lub fakturę", "address_change": "Powód: zmiana adresu dostawy",
    "product_info": "Powód: informacje o produkcie i dostępności", "loyalty_points": "Powód: punkty lojalnościowe i bony", "complaint_service": "Powód: skarga na obsługę i prośba o telefon od kierownika",
    "cancel_order": "Powód: anulowanie zamówienia",
}  # fmt: skip

# Same topics, same number and order of templates as `synth.SUMMARY_TEMPLATES`; the product is always named in the nominative ("produkt: ...").
SUMMARY_TEMPLATES_PL: dict[str, list[str]] = {
    "order_status": [
        "Klient pyta, gdzie jest zamówienie (produkt: {product}) i kiedy dotrze przesyłka {carrier}; śledzenie pokazuje status „w drodze”.",
        "Zapytanie o śledzenie: klient nie widzi terminu dostawy (produkt: {product}); sprawdzono status przesyłki u przewoźnika {carrier}.",
        "Klient chce poznać przewidywany termin dostawy zamówienia (produkt: {product}) oraz link do śledzenia.",
    ],
    "delivery_reschedule": [
        "Klient prosi o zmianę terminu dostawy {carrier} na inny dzień (produkt: {product}).",
        "Prośba o przeniesienie terminu dostawy (produkt: {product}); klient nie będzie w domu w zaplanowanym dniu.",
        "Klient prosi o nowy termin dostawy z powodu wyjazdu; dostawę (produkt: {product}) przełożono.",
    ],
    "damaged_on_delivery": [
        "Klient zgłasza, że towar (produkt: {product}) dotarł uszkodzony — dostawa {carrier}: wgnieciony panel i zarysowania; prosi o wymianę lub zwrot środków.",
        "Uszkodzenie w transporcie: towar (produkt: {product}) dostarczony przez {carrier} ma widoczne uszkodzenia; przesłano zdjęcia, klient chce odbioru i zwrotu środków.",
        "Towar (produkt: {product}) dotarł rozbity po dostawie {carrier}; klient jest zdenerwowany i prosi o wymianę.",
    ],
    "return_request": [
        "Klient chce zwrócić towar (produkt: {product}) w terminie zwrotu, bo nie pasuje do pomieszczenia.",
        "Prośba o zwrot (produkt: {product}): klient zmienił zdanie, pyta o odbiór zwracanego towaru i termin zwrotu środków.",
        "Klient pyta, jak wymienić towar (produkt: {product}) na inny kolor i jak wygląda procedura zwrotu.",
    ],
    "refund_status": [
        "Klient pyta, kiedy zwrot środków za odesłany towar (produkt: {product}) pojawi się na karcie; zwrot zlecono, wypłata potrwa 3–5 dni.",
        "Zapytanie o status zwrotu środków: klient nie widzi jeszcze pieniędzy za anulowane zamówienie (produkt: {product}).",
        "Klient chce potwierdzenia, że zwrot środków za zamówienie (produkt: {product}) został zrealizowany i jaką metodą.",
    ],
    "installation_issue": [
        "Monter nie przyjechał na umówiony termin montażu (produkt: {product}); klient prosi o nowy termin i przeprosiny.",
        "Problem z montażem: montaż (produkt: {product}) nie został dokończony i technik musi wrócić.",
        "Klient skarży się, że ekipa montażowa (produkt: {product}) spóźniła się i zostawiła części; prosi o ponowną wizytę.",
    ],
    "warranty_claim": [
        "Towar (produkt: {product}) przestał działać po 14 miesiącach; klient prosi o naprawę gwarancyjną w ramach 24-miesięcznej gwarancji.",
        "Reklamacja gwarancyjna (produkt: {product}): wada ujawniła się po upływie terminu zwrotu; klient udokumentował usterkę zdjęciem.",
        "Klient zgłasza wadę fabryczną (produkt: {product}) i chce otworzyć sprawę naprawczą.",
    ],
    "billing_dispute": [
        "Klient widzi podwójne obciążenie karty za zamówienie (produkt: {product}) i prosi o cofnięcie duplikatu płatności.",
        "Pytanie o rozliczenie: kwota na fakturze za zamówienie (produkt: {product}) różni się od sumy w koszyku; klient prosi o wyjaśnienie.",
        "Klient kwestionuje blokadę środków na karcie za zamówienie (produkt: {product}), która nadal jest w toku.",
    ],
    "address_change": [
        "Klient przeprowadził się i prosi o zmianę adresu dostawy zamówienia (produkt: {product}) przed wysyłką.",
        "Korekta adresu zamówienia (produkt: {product}): przy składaniu zamówienia wpisano zły kod pocztowy.",
        "Klient chce, aby towar (produkt: {product}) dostarczono na adres służbowy zamiast domowego.",
    ],
    "product_info": [
        "Klient pyta o wymiary i dostępne kolory (produkt: {product}) przed złożeniem zamówienia.",
        "Pytanie o produkt (produkt: {product}): czy w zestawie jest instrukcja montażu i czy towar jest dostępny w najbliższym sklepie.",
        "Klient porównuje dwa modele (produkt: {product}) i pyta o materiały oraz czas dostawy.",
    ],
    "loyalty_points": [
        "Klient pyta, ile punktów lojalnościowych ma na koncie i jak wykorzystać bon przy kolejnym zamówieniu.",
        "Pytanie o program lojalnościowy: punkty za zakup (produkt: {product}) nie zostały naliczone; klient pyta, kiedy się pojawią.",
        "Klient chce poznać korzyści poszczególnych poziomów programu i czy bon można łączyć z promocją.",
    ],
    "complaint_service": [
        "Klient skarży się na ciągle niską jakość obsługi i brak odpowiedzi na e-maile w sprawie zamówienia (produkt: {product}); prosi o telefon od kierownika.",
        "Formalna skarga: klienta trzykrotnie przełączano między działami i nikt nie rozwiązał problemu (produkt: {product}).",
        "Zdenerwowany klient mówi, że mimo obietnicy nikt do niego nie oddzwonił, i grozi eskalacją skargi.",
    ],
    "cancel_order": [
        "Klient chce anulować zamówienie (produkt: {product}) przed wysyłką, bo termin dostawy jest zbyt odległy.",
        "Prośba o anulowanie zamówienia (produkt: {product}) złożonego omyłkowo; klient prosi o potwierdzenie i zwrot środków.",
        "Klient prosi o anulowanie zamówienia (produkt: {product}) po znalezieniu lepszej oferty w innym sklepie.",
    ],
}  # fmt: skip
GENERIC_SUMMARY_PL = "Krótki kontakt w sprawie zamówienia (produkt: {product}); sprawa załatwiona i zamknięta."

# Customer opening messages as typed in the chat / said on the phone (a few of them without diacritics, as on a phone keyboard).
OPENING_PL: dict[str, list[str]] = {
    "order_status": ["Dzień dobry, gdzie jest moje zamówienie? Kurier miał być dzisiaj, a śledzenie nic nie pokazuje.", "Kiedy dotrze moja paczka? Numer zamówienia mam w mailu, ale status się nie zmienia.", "prosze o informacje o terminie dostawy mojego zamowienia"],
    "delivery_reschedule": ["Chciałbym przełożyć dostawę na piątek, w czwartek nie będzie mnie w domu.", "Czy można zmienić termin dostawy? Wyjeżdżam służbowo.", "dzien dobry, prosze o nowy termin dostawy, nie moge odebrac w umowionym dniu"],
    "damaged_on_delivery": ["Dzień dobry, towar dotarł uszkodzony: ma wgniecenie i porysowane nogi. Proszę o wymianę lub zwrot pieniędzy.", "Kurier dostarczył rozbitą paczkę, w środku wszystko jest połamane. Co mam teraz zrobić?", "towar dotarl uszkodzony, mam zdjecia, prosze o odbior i zwrot srodkow"],
    "return_request": ["Chciałbym zwrócić towar, bo nie pasuje do pokoju. Jak to zrobić?", "Zmieniłam zdanie i chcę odstąpić od umowy. Kiedy przyjedzie kurier po paczkę?", "Czy mogę wymienić ten produkt na inny kolor?"],
    "refund_status": ["Kiedy dostanę zwrot pieniędzy za odesłany towar? Minął już tydzień.", "Zamówienie zostało anulowane, a pieniędzy nadal nie widzę na karcie.", "prosze o potwierdzenie ze zwrot srodkow zostal zrealizowany"],
    "installation_issue": ["Monter nie przyjechał w umówionym terminie, a czekałam cały dzień. Proszę o nowy termin.", "Montaż nie został dokończony, brakuje części. Kiedy technik wróci?", "Ekipa montażowa spóźniła się trzy godziny i zostawiła bałagan."],
    "warranty_claim": ["Urządzenie przestało działać po czternastu miesiącach. Chcę skorzystać z gwarancji.", "Zgłaszam reklamację: produkt ma wadę fabryczną, mam zdjęcia usterki.", "Czy gwarancja obejmuje naprawę w moim domu?"],
    "billing_dispute": ["Z mojej karty pobrano dwa razy tę samą kwotę za zamówienie. Proszę o zwrot nadpłaty.", "Kwota na fakturze jest inna niż w podsumowaniu zamówienia. Skąd ta różnica?", "Blokada środków na karcie nadal jest aktywna, choć zapłaciłam już za zamówienie."],
    "address_change": ["Przeprowadziłam się, proszę zmienić adres dostawy mojego zamówienia.", "W zamówieniu wpisałem zły kod pocztowy, proszę o poprawę przed wysyłką.", "Czy mogę dostać towar na adres do pracy zamiast domowego?"],
    "product_info": ["Jakie wymiary ma ten produkt i w jakich kolorach jest dostępny?", "Czy do zestawu dołączona jest instrukcja montażu? Czy mogę go zobaczyć w sklepie?", "Chcę porównać dwa modele: z czego są wykonane i ile trwa dostawa?"],
    "loyalty_points": ["Ile punktów mam na koncie lojalnościowym i jak użyć bonu przy następnym zamówieniu?", "Punkty za ostatni zakup nie zostały naliczone. Kiedy się pojawią?", "Czy bon rabatowy można łączyć z promocją?"],
    "complaint_service": ["To skandal: trzeci raz piszę w tej sprawie i nikt nie odpowiada. Proszę o telefon od kierownika.", "Przełączano mnie między działami i nikt nie rozwiązał mojego problemu. Składam skargę.", "Nikt do mnie nie oddzwonił, choć mi to obiecano. Jeśli sprawa się nie wyjaśni, zgłoszę ją dalej."],
    "cancel_order": ["Proszę anulować zamówienie, zanim zostanie wysłane, bo termin dostawy jest za późny.", "Zamówienie złożyłam przez pomyłkę. Proszę o anulowanie i zwrot pieniędzy.", "Znalazłem lepszą ofertę, chcę zrezygnować z zamówienia."],
}  # fmt: skip


def summary_pl(topic: str, product: str, carrier: str | None, template_index: int | None) -> str:
    """Polish rendering of a record's wrap-up summary (the Polish template with the index of the English one the base generator chose)."""
    template = GENERIC_SUMMARY_PL if template_index is None else SUMMARY_TEMPLATES_PL[topic][template_index]
    return f"{REASON_PL[topic]}. " + template.format(product=PRODUCT_PL.get(product, product), carrier=carrier or "przewoźnika")


def opening_text(topic: str, n: int) -> str:
    """Customer opening message of a PL-market record, picked by the record number."""
    pool = OPENING_PL[topic]
    return pool[n % len(pool)]


def record_fields(topic: str, product: str, carrier: str | None, template_index: int | None, n: int, market: str) -> dict[str, Any]:
    """Polish fields of a record: every record gets `summary_pl`; a PL-market record also gets the customer's opening message as `text`."""
    out: dict[str, Any] = {"summary_pl": summary_pl(topic, product, carrier, template_index)}
    if market == "PL":
        out["text"] = opening_text(topic, n)
    return out
