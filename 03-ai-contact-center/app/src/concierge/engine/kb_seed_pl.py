"""Polish knowledge base (CC-03 / CC-19): the policy articles of `kb_seed` in Polish with the SAME business rules (the caps and limits are enforced in code
and stated here in EUR with the złoty equivalent at the fixed demo rate 1 EUR = 4.30 PLN), plus two Polish-only articles (rękojmia vs gwarancja, UOKiK and
out-of-court dispute resolution). Deterministic ids `<english-id>-pl`, `lang: pl`. Fictional demo content - not legal advice.

Each article ends with an English keyword line so that an English question can still reach it (the English articles carry German / French / Spanish
keywords for the same reason); a Polish question reaches the English articles through the embedder (and the offline synonym map)."""

from __future__ import annotations

from typing import Any

from ..core.i18n import nbsp_pl


def _p(en_id: str, title: str, category: str, tags: str, text: str) -> dict[str, Any]:
    return {"id": f"{en_id}-pl", "title": title, "category": category, "tags": [t.strip() for t in tags.split(",")], "lang": "pl", "text": nbsp_pl(text.strip()), "source": "seed"}


KB_DOCS_PL: list[dict[str, Any]] = [
    _p("returns-001", "Zasady zwrotów (30 dni)", "returns", "zwrot,zwrot środków,termin", """
# Zasady zwrotów
## Termin zwrotu
Większość towarów można zwrócić bezpłatnie w ciągu 30 dni od dostawy. Towar musi być nieużywany i w oryginalnym stanie. Termin 30 dni liczy się od daty dostawy widocznej w zamówieniu.
## Ustawowe prawo odstąpienia od umowy
Niezależnie od naszego 30-dniowego terminu konsument, który kupił towar na odległość, może w ciągu 14 dni od otrzymania towaru odstąpić od umowy bez podania przyczyny. Ten ustawowy termin 14 dni pozostaje bez zmian.
## Bezpłatny odbiór
Towary gabarytowe (sofy, materace, szafy, duże sprzęty AGD) odbieramy z domu bezpłatnie. Mniejsze towary można odesłać z opłaconą etykietą zwrotną.
## Zwrot środków
Po odebraniu lub otrzymaniu towaru zwrot środków trafia na pierwotną metodę płatności w ciągu 5–7 dni roboczych.
Keywords (en): return, refund, withdrawal, 30 days, free collection.
"""),
    _p("returns-002", "Towary, których nie można zwrócić", "returns", "zwrot,wyjątki,higiena,na wymiar", """
# Towary, których nie można zwrócić
## Wyjątki
Meble wykonane na zamówienie lub na wymiar, rozpakowane ochraniacze na materace oraz towary użyte ze względów higienicznych nie podlegają zwrotowi, chyba że są wadliwe lub dotarły uszkodzone.
Towary z wyprzedaży oznaczone „ostatnia sztuka bez zwrotu” są wyłączone z naszego 30-dniowego okresu zwrotu, ale zachowują gwarancję.
## Prawa ustawowe
Ustawowe uprawnienia konsumenta — prawo odstąpienia od umowy zawartej na odległość (14 dni) oraz rękojmia za wady towaru — nie są ograniczone tymi zasadami.
Keywords (en): items that cannot be returned, custom-made, hygiene, final sale, statutory rights.
"""),
    _p("returns-003", "Umawianie odbioru zwracanego towaru", "returns", "zwrot,odbiór,terminy", """
# Umawianie odbioru zwracanego towaru
## Okna odbioru
Odbiory odbywają się od poniedziałku do piątku w dwóch oknach czasowych: 09:00–13:00 i 13:00–17:00. Konsultanci mogą zarezerwować dla Państwa najbliższy wolny termin.
## Przygotowanie do odbioru
Towar powinien być łatwo dostępny; sofy i materace warto, jeśli to możliwe, owinąć folią. Sprzętu AGD nie trzeba pakować w oryginalny karton. Towary gabarytowe odbiera dwuosobowy zespół.
## Nieobecność w terminie odbioru
Jeśli w umówionym terminie odbioru nikogo nie będzie na miejscu, odbiór można bezpłatnie przełożyć jeden raz.
Keywords (en): pickup, collection, slots, windows, missed pickup, rebook.
"""),
    _p("returns-004", "Wymiana i towar zastępczy", "returns", "wymiana,towar zastępczy,czas realizacji", """
# Wymiana i towar zastępczy
## Towar zastępczy
Jeśli towar dotarł uszkodzony lub wadliwy, wysyłamy identyczny towar zastępczy bez dodatkowych kosztów. Dostawa towaru zastępczego trwa 3–10 dni roboczych w zależności od dostępności; uszkodzony towar odbieramy podczas dostawy nowego lub wcześniej na życzenie.
## Inny model
W przypadku wyboru innego modelu przyjmujemy zwrot i składamy nowe zamówienie; różnicę w cenie doliczamy do płatności albo zwracamy.
Keywords (en): exchange, replacement, lead time, different model.
"""),
    _p("returns-005", "Koszty zwrotu i roszczenia wobec przewoźnika", "returns", "zwrot,koszty,przewoźnik,roszczenia", """
# Koszty zwrotu i roszczenia wobec przewoźnika
Zwroty towarów gabarytowych oraz wszystkie przypadki uszkodzenia w transporcie są dla Państwa bezpłatne. Wszelkimi roszczeniami wobec przewoźnika (DPD Polska, DHL, InPost oraz NordFreight, SwiftHaul, BlueRoute) zajmuje się Contoso Home; nie trzeba samodzielnie kontaktować się z przewoźnikiem.
Keywords (en): return costs, carrier claims, free for you.
"""),
    _p("damage-001", "Uszkodzenie przy dostawie", "damage", "uszkodzenie,dostawa,transport,wymiana,zwrot środków", """
# Uszkodzenie przy dostawie
## Zgłoszenie w ciągu 14 dni
Widoczne uszkodzenia transportowe należy zgłosić w ciągu 14 dni od dostawy. Przepraszamy za kłopot — nie trzeba przechowywać opakowania.
## Dostępne opcje
Można wybrać bezpłatną wymianę albo pełny zwrot środków za uszkodzony towar. W obu przypadkach bezpłatnie organizujemy odbiór uszkodzonego towaru. Zdjęcia pomagają, ale nie są wymagane przy zamówieniach poniżej 500 EUR (ok. 2 150 zł); przy zamówieniach od 500 EUR (ok. 2 150 zł) prosimy o przesłanie zdjęć e-mailem lub przez konto klienta.
## Termin zwrotu środków
Zwrot środków następuje po odebraniu towaru i jego dotarciu do naszego magazynu, zwykle w ciągu 5–7 dni roboczych od odbioru.
Keywords (en): damaged on delivery, transit damage, replacement, refund, pickup, 14 days.
"""),
    _p("damage-003", "Zdjęcia potwierdzające uszkodzenie", "damage", "uszkodzenie,zdjęcia,dowody,zgłoszenie", """
# Zdjęcia potwierdzające uszkodzenie
## Kiedy potrzebne są zdjęcia
Przy zamówieniach poniżej 500 EUR (ok. 2 150 zł) zdjęcia są opcjonalne. Przy zamówieniach od 500 EUR (ok. 2 150 zł) lub gdy uszkodzenie jest sporne, prosimy o 2–4 zdjęcia: uszkodzone miejsce, cały towar oraz etykietę z opakowania.
## Jak je przesłać
Zdjęcia można dodać na koncie w zakładce „Moje zamówienia” albo wysłać je w odpowiedzi na e-mail z potwierdzeniem. Zdjęcia sprawdzamy w ciągu jednego dnia roboczego.
Keywords (en): photo evidence, damage claim, upload photos, 500 EUR.
"""),
    _p("damage-004", "Uszkodzenie zgłoszone po 14 dniach", "damage", "uszkodzenie,po terminie,wyjątek,bon", """
# Uszkodzenie zgłoszone po 14 dniach
Uszkodzenie zgłoszone po upływie 14 dni od dostawy rozpatruje specjalista — jako reklamację albo jako gest dobrej woli. Prosimy o kontakt i podanie daty dostawy; zespół specjalistów podejmuje decyzję indywidualnie.
Keywords (en): damage reported after 14 days, late report, goodwill, warranty.
"""),
    _p("refunds-001", "Termin i sposób zwrotu środków", "refunds", "zwrot środków,termin,metoda płatności,limit", """
# Termin i sposób zwrotu środków
## Jak wypłacamy zwroty
Zwroty zawsze wracają na pierwotną metodę płatności. Zwrot na kartę jest widoczny po 5–7 dniach roboczych od odebrania towaru; zwroty PayPal i BLIK są zwykle szybsze. Zamówienia opłacone z odroczonym terminem płatności (faktura) zaksięgowujemy na koncie klienta.
## Kto może zatwierdzić
Konsultanci mogą od razu zlecić zwrot do 500 EUR (ok. 2 150 zł). Zwroty powyżej 500 EUR (ok. 2 150 zł) rozpatruje specjalista, zwykle w ciągu jednego dnia roboczego.
Keywords (en): refund timing, payment method, refund cap 500 EUR, approval by a specialist.
"""),
    _p("refunds-002", "Częściowy zwrot i rabat za zatrzymanie towaru", "refunds", "zwrot częściowy,rabat,zatrzymanie towaru", """
# Częściowy zwrot i rabat za zatrzymanie towaru
Przy drobnych uszkodzeniach kosmetycznych można zatrzymać towar i otrzymać częściowy zwrot w wysokości 10–30% ceny towaru, zależnie od uszkodzenia. Kwotę ustala się przed zleceniem zwrotu.
Keywords (en): partial refund, keep-it discount, cosmetic damage.
"""),
    _p("refunds-003", "Sprawdzanie statusu zwrotu środków", "refunds", "zwrot środków,status,opóźnienie", """
# Sprawdzanie statusu zwrotu środków
Status zwrotu można sprawdzić u konsultanta lub w zakładce „Moje zamówienia > Zwroty”. Zwrot ma status „zrealizowany”, gdy go wypłaciliśmy; banki mogą potrzebować jeszcze 2–3 dni roboczych na jego zaksięgowanie. Jeśli od zeskanowania towaru przy odbiorze minęło ponad 10 dni roboczych, prosimy o kontakt — wszczynamy postępowanie wyjaśniające.
Keywords (en): refund status, delay, investigation, 10 business days.
"""),
    _p("refunds-004", "Gest dobrej woli i rekompensata za opóźnienie", "refunds", "bon,rekompensata,opóźnienie,gest dobrej woli", """
# Gest dobrej woli i rekompensata za opóźnienie
## Zasady
Przy opóźnieniu dostawy powyżej 3 dni lub niedotrzymaniu przez nas umówionego terminu konsultanci mogą zaproponować bon rekompensacyjny do 50 EUR (ok. 215 zł). Bony są ograniczone do 100 EUR (ok. 430 zł) na klienta w ciągu 90 dni, nie podlegają wymianie na gotówkę i są ważne 12 miesięcy.
## Wyższe kwoty
O rekompensacie powyżej tych limitów decyduje specjalista.
Keywords (en): goodwill, compensation, voucher, delay, 50 EUR, 100 EUR per 90 days.
"""),
    _p("delivery-001", "Opcje i okna dostawy", "delivery", "dostawa,okna dostawy,standardowa,gabaryt", """
# Opcje i okna dostawy
Dostawa standardowa trwa 3–7 dni roboczych; towary gabarytowe (sofy, szafy, sprzęt AGD) 5–10 dni roboczych. Okno dostawy jest 4-godzinne i można je wybrać spośród przedziałów 08:00–12:00, 12:00–16:00 oraz 16:00–20:00. Wieczorem w dniu poprzedzającym dostawę wysyłamy powiadomienie.
Keywords (en): delivery options, delivery windows, standard delivery, bulky items.
"""),
    _p("delivery-002", "Śledzenie dostawy i znaczenie statusów", "delivery", "śledzenie,status,przesyłka", """
# Śledzenie dostawy
Statusy: zamówienie przyjęte, etykieta wygenerowana, w drodze, w doręczeniu, dostarczone, opóźnione, problem z doręczeniem. Status „opóźnione” oznacza, że przewoźnik nie dotrzyma planowanego terminu; nową datę podajemy, gdy tylko przewoźnik ją potwierdzi. Śledzenie jest dostępne w zakładce „Moje zamówienia” oraz u konsultanta.
Keywords (en): tracking, status, shipment, delayed, out for delivery.
"""),
    _p("delivery-003", "Zmiana terminu dostawy", "delivery", "zmiana terminu,dostawa,termin,bezpłatnie", """
# Zmiana terminu dostawy
Termin dostawy można zmienić bezpłatnie do 24 godzin przed oknem dostawy. Konsultant zaproponuje najbliższe wolne okna (od poniedziałku do piątku). W ciągu ostatnich 24 godzin decyduje przewoźnik; postaramy się pomóc.
Keywords (en): reschedule delivery, change delivery date, slot, free of charge, 24 hours.
"""),
    _p("delivery-004", "Nieudane próby doręczenia", "delivery", "nieobecność,ponowna dostawa,przewoźnik,awizo", """
# Nieudane próby doręczenia
Jeśli nikogo nie będzie w domu, przewoźnik zostawia awizo i próbuje ponownie następnego dnia roboczego. Po drugiej nieudanej próbie przesyłka wraca do naszego magazynu; raz bezpłatnie umawiamy nowe okno dostawy.
Keywords (en): missed delivery attempts, redelivery, carrier, nobody home.
"""),
    _p("delivery-005", "Opóźnienia w dostawie", "delivery", "opóźnienie,hub przewoźnika,rekompensata", """
# Opóźnienia w dostawie
Opóźnienia wynikają zwykle z przepustowości hubu przewoźnika lub z pogody. Nowy termin dostawy podajemy, gdy tylko zostanie potwierdzony. Przy opóźnieniu dłuższym niż 3 dni konsultant może zaproponować bon rekompensacyjny do 50 EUR (ok. 215 zł) — zob. „Gest dobrej woli i rekompensata za opóźnienie”.
Keywords (en): delivery delays, late delivery, carrier hub, compensation.
"""),
    _p("delivery-006", "Pomiary i dojście (schody, drzwi)", "delivery", "schody,dojście,pomiary,wyższe piętro", """
# Pomiary i dojście
Przed zamówieniem prosimy o zmierzenie drzwi, schodów i wind. Nasze dwuosobowe zespoły wnoszą towar do wskazanego pomieszczenia, także na wyższe piętra, ale nie demontują drzwi ani okien. Wąskie dojście należy zgłosić przy umawianiu dostawy.
Keywords (en): measuring, access, stairs, doorways, upper floor.
"""),
    _p("delivery-007", "Zmiana adresu dostawy", "delivery", "adres,zmiana,wysyłka,weryfikacja", """
# Zmiana adresu dostawy
Adres można zmienić bezpłatnie do momentu wysyłki zamówienia. Ponieważ zmiany adresu są częstą metodą oszustw, konsultant najpierw weryfikuje klienta jednorazowym kodem i pytaniem zabezpieczającym. Po wysyłce prosimy o kontakt z przewoźnikiem; pomożemy w znalezieniu danych kontaktowych.
Keywords (en): change delivery address, dispatch, verification, one-time code.
"""),
    _p("delivery-008", "Przewoźnicy, z którymi współpracujemy", "delivery", "przewoźnik,InPost,DPD Polska,DHL", """
# Przewoźnicy
Na rynku polskim towary gabarytowe dostarczamy przez DPD Polska i DHL, a mniejsze przesyłki także przez InPost (kurier lub Paczkomat). W innych krajach współpracujemy z przewoźnikami NordFreight, SwiftHaul i BlueRoute. Nazwa przewoźnika jest widoczna w śledzeniu zamówienia. Towary gabarytowe dostarczają dwuosobowe zespoły.
Keywords (en): carriers, InPost, DPD, DHL, NordFreight, SwiftHaul, BlueRoute.
"""),
    _p("install-001", "Usługa montażu — przegląd", "installation", "montaż,sprzęt AGD,złożenie,cena", """
# Usługa montażu
Podłączenie sprzętu AGD (pralki, zmywarki, piekarniki) kosztuje 49 EUR (ok. 211 zł) za urządzenie; złożenie mebla kosztuje 39 EUR (ok. 168 zł) za sztukę. Wizyta trwa około 90 minut i można ją zarezerwować razem z dostawą lub później.
Keywords (en): installation service, appliance installation, assembly, price, 49 EUR.
"""),
    _p("install-002", "Nieobecność montera w umówionym terminie", "installation", "montaż,nieobecność,nowy termin,bon", """
# Nieobecność montera w umówionym terminie
Jeśli nasz monter nie przyjedzie w umówionym terminie, przysługuje Państwu priorytetowe przełożenie wizyty w ciągu 48 godzin oraz bon rekompensacyjny w wysokości 30 EUR (ok. 129 zł). Jeśli monter nie pojawi się w dwóch umówionych terminach, sprawę przejmuje starszy konsultant.
Keywords (en): missed installation appointment, installer did not show up, rebooking, goodwill 30 EUR.
"""),
    _p("install-003", "Montaż pralki — wymagania", "installation", "pralka,woda,przyłącze,montaż", """
# Montaż pralki
Prosimy o zapewnienie kranu z zimną wodą, odpływu i wolnego gniazdka w odległości do 1,5 m. Nasz zespół podłącza pralkę, uruchamia program próbny i usuwa śruby transportowe. Nie wykonujemy nowych przyłączy wody ani odpływu.
Keywords (en): washing machine installation, prerequisites, water connection, drain.
"""),
    _p("install-004", "Składanie mebli", "installation", "montaż,szafa,łóżko,składanie", """
# Składanie mebli
Szafy, łóżka i stoły można złożyć w wybranym pomieszczeniu; prosimy o zwolnienie miejsca. Montaż mebli wiszących wymaga odpowiednich ścian — zespół doradzi na miejscu.
Keywords (en): furniture assembly, wardrobe, bed, wall-mounted.
"""),
    _p("install-005", "Czego nie montujemy", "installation", "ograniczenia,gaz,instalacja elektryczna", """
# Czego nie montujemy
Nie podłączamy urządzeń gazowych, nie wykonujemy przeróbek instalacji elektrycznej ani nie montujemy sprzętu w kuchniach, które nie spełniają wymagań przyłączeniowych. Do takich prac należy wezwać uprawnionego fachowca.
Keywords (en): what we do not install, gas appliances, electrical rewiring.
"""),
    _p("warranty-001", "Gwarancja — przegląd", "warranty", "gwarancja,rękojmia,miesiące", """
# Gwarancja — przegląd
Wszystkie produkty objęte są 24-miesięczną gwarancją Contoso Home od daty dostawy; materace 36 miesięcy. Gwarancja obejmuje wady materiałowe i wykonawcze, które nie wynikają z niewłaściwego użytkowania. Gwarancja nie wyłącza ani nie ogranicza ustawowych uprawnień konsumenta z tytułu rękojmi za wady towaru.
Keywords (en): warranty, guarantee, 24 months, 36 months mattress, defects.
"""),
    _p("warranty-002", "Jak złożyć reklamację gwarancyjną", "warranty", "gwarancja,reklamacja,naprawa,wymiana", """
# Jak złożyć reklamację gwarancyjną
Prosimy o kontakt z obsługą klienta i podanie numeru zamówienia oraz krótkiego opisu usterki (pomocne będą zdjęcia). W ciągu 10 dni roboczych decydujemy, czy towar zostanie naprawiony, wymieniony, czy też zwrócimy zapłaconą kwotę. Jeśli naprawa jest niemożliwa, wymieniamy towar.
Keywords (en): warranty claim, repair, replacement, refund, 10 working days.
"""),
    _p("warranty-003", "Czego gwarancja nie obejmuje", "warranty", "gwarancja,wyłączenia,zużycie", """
# Czego gwarancja nie obejmuje
Gwarancja nie obejmuje normalnego zużycia, uszkodzeń wynikających z niewłaściwego użytkowania, wypadków, nieautoryzowanych napraw, użytkowania komercyjnego ani zmian kosmetycznych, takich jak blaknięcie od słońca.
Keywords (en): what the warranty does not cover, wear and tear, misuse, exclusions.
"""),
    _p("warranty-005", "Rękojmia a gwarancja — różnice", "warranty", "rękojmia,gwarancja,reklamacja,konsument", """
# Rękojmia a gwarancja — różnice
## Rękojmia (ustawowa)
Sprzedawca odpowiada wobec konsumenta za wady towaru (rękojmia; w ustawie o prawach konsumenta: niezgodność towaru z umową) przez 24 miesiące od wydania towaru. Konsument może żądać naprawy lub wymiany, a gdy naprawa lub wymiana nie jest możliwa albo nie została wykonana prawidłowo — obniżenia ceny lub odstąpienia od umowy. Rękojmia wynika z ustawy i nie wymaga żadnej karty gwarancyjnej.
## Gwarancja (dobrowolna)
Gwarancja Contoso Home (24 miesiące, materace 36 miesięcy) to dodatkowe zobowiązanie sprzedawcy. Nie ogranicza uprawnień z rękojmi — można wybrać korzystniejszą dla siebie podstawę reklamacji. To treść demonstracyjna i nie stanowi porady prawnej.
Keywords (en): statutory warranty, legal guarantee, complaint, consumer rights, defect.
"""),
    _p("billing-001", "Metody płatności", "billing", "płatność,karta,BLIK,PayPal,raty", """
# Metody płatności
Akceptujemy karty Visa i Mastercard, BLIK, PayPal oraz — dla zatwierdzonych klientów — płatność z odroczonym terminem na podstawie faktury. Zamówienia powyżej 300 EUR (ok. 1 290 zł) można opłacić w 6 ratach bez odsetek. Nie przyjmujemy gotówki ani kryptowalut.
Keywords (en): payment methods, card, PayPal, invoice, instalments, 300 EUR.
"""),
    _p("billing-002", "Bezpieczne przekazanie płatności", "billing", "płatność,pci,bezpieczny link,numer karty", """
# Bezpieczne przekazanie płatności
Nasi asystenci i konsultanci nigdy nie przyjmują numerów kart, dat ważności ani kodów bezpieczeństwa na czacie ani przez telefon. Gdy potrzebna jest płatność, otrzymują Państwo bezpieczny link do płatności albo — podczas rozmowy — wpisują cyfry na klawiaturze telefonu, aby nikt ich nie słyszał ani nie widział.
Keywords (en): secure payment hand-off, card number, CVV, never in chat.
"""),
    _p("billing-003", "Faktury i dokumenty VAT", "billing", "faktura,VAT,rachunek", """
# Faktury i dokumenty VAT
Faktury są dostępne w zakładce „Moje zamówienia” w formacie PDF i wysyłane e-mailem w dniu wysyłki. Obsługa klienta może ponownie wysłać fakturę na adres e-mail przypisany do konta. Faktury VAT dla firm wystawiamy na życzenie; wymagany jest wówczas numer NIP.
Keywords (en): invoices, VAT receipts, invoice for businesses, NIP.
"""),
    _p("billing-004", "Podwójne obciążenia i blokady środków", "billing", "podwójne obciążenie,autoryzacja,blokada", """
# Podwójne obciążenia i blokady środków
Oczekująca autoryzacja karty może wyglądać jak drugie obciążenie. Autoryzacje, które nie zostały rozliczone, znikają w ciągu 5–7 dni. Jeśli na koncie widoczne są dwa rozliczone obciążenia za jedno zamówienie, prosimy o kontakt — wyjaśniamy sprawę i zwracamy kwotę pobraną dwukrotnie.
Keywords (en): double charge, authorisation hold, duplicate payment, refund duplicates.
"""),
    _p("loyalty-001", "Klub Contoso Home", "loyalty", "lojalność,punkty,vip,poziomy", """
# Klub Contoso Home
Członkowie zdobywają 1 punkt za każde wydane 1 EUR (ok. 4,30 zł); 500 punktów odpowiada bonowi 10 EUR (ok. 43 zł). Członkowie VIP (roczne zakupy powyżej 3 000 EUR, czyli ok. 12 900 zł) mają priorytetową obsługę, bezpłatną dostawę i wydłużony termin zwrotu do 45 dni.
Keywords (en): Contoso Home Club, loyalty points, VIP tier, voucher, 45 days.
"""),
    _p("loyalty-002", "Bony i kody rabatowe", "loyalty", "bon,kod rabatowy,ważność", """
# Bony i kody rabatowe
Bony są ważne 12 miesięcy i nie podlegają wymianie na gotówkę. W jednym zamówieniu można użyć jednego kodu rabatowego; kodów nie łączy się z bonami Klubu, o ile nie zaznaczono inaczej.
Keywords (en): vouchers, promo codes, validity, 12 months.
"""),
    _p("privacy-001", "Ochrona danych i Państwa prawa (RODO)", "privacy", "rodo,prywatność,dane,usunięcie", """
# Ochrona danych i Państwa prawa (RODO)
Mogą Państwo żądać dostępu do swoich danych osobowych, ich sprostowania lub usunięcia (RODO). Odpowiadamy w ciągu 30 dni. Obsługa klienta może przyjąć wniosek po zweryfikowaniu tożsamości; realizuje go zespół ochrony danych. Mają Państwo także prawo wniesienia skargi do Prezesa Urzędu Ochrony Danych Osobowych (UODO).
Keywords (en): GDPR, data protection, personal data, deletion, access request, 30 days.
"""),
    _p("privacy-002", "Nagrywanie rozmów i informacja o AI", "privacy", "nagrywanie,ai,informacja,zgoda", """
# Nagrywanie rozmów i informacja o asystencie AI
Każda rozmowa zaczyna się informacją, że rozmawiają Państwo z asystentem AI i że rozmowa może być nagrywana w celu poprawy jakości obsługi i szkoleń. Można odmówić nagrywania — obsługa trwa wtedy bez nagrywania albo przejmuje ją konsultant. Nagrania przechowujemy 12 miesięcy, a następnie usuwamy.
Keywords (en): call and chat recording, AI disclosure, consent, 12 months.
"""),
    _p("privacy-003", "Dlaczego weryfikujemy tożsamość", "privacy", "weryfikacja,kod jednorazowy,bezpieczeństwo", """
# Dlaczego weryfikujemy tożsamość
Aby chronić konto, przed pokazaniem szczegółów zamówienia lub wprowadzeniem zmian wysyłamy jednorazowy kod na numer telefonu przypisany do konta. Nigdy nie prosimy o hasła, numery kart ani pełne dane bankowe, a kodu nie wolno nikomu podawać, jeśli ktoś kontaktuje się z Państwem niespodziewanie.
Keywords (en): identity verification, one-time code, OTP, security.
"""),
    _p("care-001", "Pielęgnacja sofy i czyszczenie", "product-care", "sofa,pielęgnacja,czyszczenie,tkanina", """
# Pielęgnacja sofy
Sofę zalecamy odkurzać raz w tygodniu końcówką do tapicerki. Plamy należy usuwać od razu, delikatnie przykładając ściereczkę, bez pocierania. Sofy tapicerowane tkaniną można czyścić łagodnym roztworem mydła; nie należy stosować wybielacza. Luźne poduszki warto obracać raz w miesiącu, a sofę ustawiać z dala od bezpośredniego światła słonecznego i grzejników.
Keywords (en): sofa care, cleaning, fabric.
"""),
    _p("care-002", "Pielęgnacja materaca", "product-care", "materac,pielęgnacja,obracanie", """
# Pielęgnacja materaca
Materac zalecamy obracać co 3 miesiące „głowa–stopy”, a pomieszczenie codziennie wietrzyć. Nowe materace piankowe mogą przez 24–48 godzin wydzielać lekki zapach. Warto stosować przewiewny ochraniacz; pokrowca materaca nie należy prać w temperaturze powyżej 30\u00a0°C, chyba że metka stanowi inaczej.
Keywords (en): mattress care, rotation, odour.
"""),
    _p("care-003", "Kody błędów pralki", "troubleshooting", "pralka,błąd,E18,E21", """
# Kody błędów pralki (Vera 8 kg)
Kod E18 oznacza problem z dopływem wody: należy sprawdzić kran i filtr dopływu. Kod E21 oznacza problem z odpływem: należy wyczyścić filtr pompy odpływowej, który znajduje się z przodu pralki, na dole. Jeśli kod nie znika po czyszczeniu, prosimy o kontakt z obsługą klienta w sprawie wizyty gwarancyjnej.
Keywords (en): washing machine error codes, E18, E21.
"""),
    _p("care-004", "Zmywarka nie odprowadza wody", "troubleshooting", "zmywarka,odpływ,filtr", """
# Zmywarka nie odprowadza wody
Proszę wyłączyć zmywarkę, wyjąć dolny kosz i wyczyścić filtr, a następnie sprawdzić, czy wąż odpływowy nie jest załamany. Jeśli po czyszczeniu woda nadal zalega, prosimy o kontakt z obsługą klienta w sprawie wizyty gwarancyjnej.
Keywords (en): dishwasher not draining, filter, drain hose.
"""),
    _p("care-005", "Wskazówki dotyczące montażu szaf i łóżek", "product-care", "montaż,szafa,łóżko,dokręcanie", """
# Wskazówki dotyczące montażu
Po dwóch tygodniach użytkowania warto dokręcić wszystkie śruby, ponieważ drewno „pracuje”. Meble najlepiej składać na miękkiej powierzchni, aby nie uszkodzić płyt ani podłogi. Złączy mimośrodowych nie należy dokręcać zbyt mocno.
Keywords (en): assembly tips, wardrobe, bed, tighten screws.
"""),
    _p("care-006", "Bezpieczeństwo: zapach gazu, dym lub iskry", "safety", "bezpieczeństwo,gaz,dym,iskry,pożar", """
# Bezpieczeństwo przede wszystkim
Jeśli czuć gaz, widać dym lub iskry albo produkt poraził prądem, proszę natychmiast przestać z niego korzystać. Jeśli to bezpieczne, proszę wyłączyć zasilanie na tablicy bezpieczników i przewietrzyć pomieszczenie. Przy zapachu gazu proszę opuścić pomieszczenie i zadzwonić pod numer alarmowy 112. Następnie prosimy o kontakt — zgłoszenia dotyczące bezpieczeństwa natychmiast przekazujemy specjaliście.
Keywords (en): safety, gas smell, smoke, sparks, emergency, 112.
"""),
    _p("service-001", "Godziny pracy i kanały kontaktu", "service", "godziny,kanały,kontakt", """
# Godziny pracy i kanały kontaktu
Asystent AI jest dostępny całą dobę na czacie i telefonie. Konsultanci są dostępni codziennie od 07:00 do 22:00 czasu środkowoeuropejskiego (czasu warszawskiego), a połączyć się z nimi można w każdej chwili z poziomu asystenta. Poza tymi godzinami można poprosić o oddzwonienie.
Keywords (en): opening hours, channels, human colleagues, callback.
"""),
    _p("service-002", "Dostępność i dodatkowe wsparcie", "service", "dostępność,wsparcie,oddzwonienie", """
# Dostępność i dodatkowe wsparcie
Oferujemy oddzwonienia, faktury drukiem powiększonym i obsługę z udziałem tłumacza migowego online. Klienci, którzy poinformują nas o potrzebie dodatkowego wsparcia (na przykład z powodu wieku, choroby lub żałoby), są łączeni z zespołem opieki w trybie priorytetowym.
Keywords (en): accessibility, extra support, vulnerable customers, callback, care team.
"""),
    _p("service-003", "Procedura reklamacyjna i skargi", "service", "skarga,reklamacja,eskalacja,rzecznik", """
# Procedura reklamacyjna i skargi
Prosimy o opisanie, co poszło nie tak — potwierdzamy przyjęcie skargi od razu. Starszy konsultant odpowiada w ciągu 5 dni roboczych. Jeśli odpowiedź nie rozwiąże sprawy, można zwrócić się do miejskiego lub powiatowego rzecznika konsumentów albo do instytucji pozasądowego rozwiązywania sporów konsumenckich; na życzenie podajemy dane kontaktowe.
Keywords (en): complaints procedure, escalation, consumer ombudsman, 5 working days.
"""),
    _p("service-004", "Dostawa do innej osoby lub sąsiada", "delivery", "sąsiad,upoważnienie,podpis", """
# Dostawa do sąsiada
Można upoważnić sąsiada lub inną osobę do odebrania przesyłki, informując o tym przewoźnika w dniu dostawy. Prosimy o sprawdzenie towaru pod kątem uszkodzeń przy odbiorze i zgłoszenie uszkodzenia w ciągu 14 dni.
Keywords (en): delivery to a neighbour, authorised person, signature, damage within 14 days.
"""),
    _p("service-005", "Odbiór starego sprzętu i recykling", "service", "recykling,odbiór,ekologia", """
# Odbiór starego sprzętu
Podczas montażu nowego urządzenia nasz zespół zabiera stary sprzęt do recyklingu bezpłatnie, jeśli jest odłączony i dostępny. Odbiór starych mebli kosztuje 29 EUR (ok. 125 zł) za sztukę.
Keywords (en): old appliance take-back, recycling, sustainability, 29 EUR.
"""),
    _p("service-006", "UOKiK i pozasądowe rozwiązywanie sporów", "service", "uokik,rzecznik konsumentów,spór,ADR,ODR", """
# UOKiK i pozasądowe rozwiązywanie sporów
## Gdzie szukać pomocy
Konsumenci mogą skorzystać z bezpłatnej pomocy miejskiego lub powiatowego rzecznika konsumentów oraz z informacji Urzędu Ochrony Konkurencji i Konsumentów (UOKiK). Spór można też rozwiązać polubownie przed instytucją pozasądowego rozwiązywania sporów konsumenckich (ADR). Europejska platforma ODR zakończyła działalność 20 lipca 2025 r., dlatego wnioski kieruje się bezpośrednio do wybranej instytucji ADR.
## Nasza praktyka
Zachęcamy do wcześniejszego kontaktu z nami: skargę potwierdzamy od razu, a starszy konsultant odpowiada w ciągu 5 dni roboczych. To treść demonstracyjna i nie stanowi porady prawnej.
Keywords (en): UOKiK, consumer ombudsman, out-of-court dispute resolution, ADR, ODR, legal threat.
"""),
]
