"""Polish lexicon for the rule-based understanding (CC-06): stems / inflection-aware regex fragments, written with real Polish letters.

Every fragment is passed through `fold()` (ł→l, ą→a, ó→o, ...) when it is compiled and the customer text is folded the same way, so the rules match
`wściekły` AND the very common diacritic-less phone typing `wsciekly`. Polish is highly inflected (uszkodzony/-a/-e/-enie, zwrócić/zwrot/zwrotu, sąd/sądu/
sądzie), so the fragments are stems with `\\w*` suffixes and explicit word boundaries where a short stem would otherwise over-match (`pozwolić` is NOT `pozwać`).
Do not use upper-case regex escapes (`\\W`, `\\S`): the fragments are lower-cased by `fold()`.

The Polish fragments are merged INTO the multilingual patterns of `understanding.py`, so every fragment is audited against English words (`gown`, `idiot`,
`sad`, `soft`, `stole`, `debilitating`); what cannot be made safe is gated: `WEAK_INTENTS` count only when nothing more specific matched, `*_PL_CONTEXT` only
when the text is Polish, `RISKS_RAW` is matched WITHOUT folding (`sąd` = court, `sad` = English), `NEGATED` removes a negated threat before the risk rule runs
("nie zamierzam pozywać", "to nie jest oszustwo", "nie czuję zapachu gazu"). `NEG_RX` / `POS_RX` are weighted sentiment fragments, `MASKED_PROFANITY` undoes
"k***a" / "ch*j" / "k u r w a". `REQUEST_RX` / `INFO_LEAD_RX` separate "Chcę zwrot zgodnie z regulaminem" (a request) from "Chciałbym zapytać o zasady zwrotów"
(a policy question)."""

from __future__ import annotations

INTENTS: dict[str, tuple[str, ...]] = {
    "damaged_item": (
        r"uszkodz\w*", r"zniszczon\w*", r"zepsut\w*", r"wadliw\w*", r"rozbit\w*", r"stłuczon\w*", r"potłuczon\w*", r"połaman\w*", r"złaman\w*", r"pęk(?:ł|n)\w*", r"pęknięci\w*", r"porysowan\w*",
        r"zarysowan\w*", r"wgniecion\w*", r"wgnieceni\w*", r"pogniecion\w*", r"pogięt\w*", r"wygięt\w*", r"poobijan\w*", r"obtłuczon\w*", r"ukruszon\w*", r"wyszczerbion\w*", r"odprysk\w*", r"rozwalon\w*",
        r"rozdarta?\b", r"rozerwan\w*", r"podarta?\b", r"podarty\b", r"podarte\b", r"poplamion\w*", r"odpad(?:ł|ła|ło|ły)\b", r"urwan\w*", r"urwał\w*", r"defekt\w*",
        r"\bbubel\w*", r"niekompletn\w*", r"brak(?:uje|uj[ąa])\s+(?:\w+\s+){0,2}(?:element|części|część|śrub|nóg|nóż|półek|drzwi|uchwyt|kółek)\w*", r"zapadł\w*\s+się", r"się\s+zapad(?:ł|ła|ło|ły|a|ają)\b", r"zapadnięt\w*",
        r"dotarł\w*\s+(?:uszkodz|zniszczon|zepsut|rozbit|pęk)", r"przyszł\w*\s+(?:uszkodz|zniszczon|zepsut|rozbit|pęk)", r"z\s+uszkodzeniami", r"ślady\s+uszkodzeń",
    ),
    "return_request": (
        r"\bzwrot\w*", r"zwróc\w*\b(?!\s+(?:się|uwag))", r"zwrac(?:am|amy|asz|ać|acie|ają)\b(?!\s+(?:się|uwag))", r"odesła\w*", r"odsyła\w*", r"odeślę", r"odda(?:ć|m|nia|ję)\b", r"\boddać", r"wymian\w*", r"wymieni\w*",
        r"odstąpi\w*\s+od\s+umowy", r"odst[ęe]pu\w*\s+od\s+umowy", r"odstąpieni\w*\s+od\s+umowy", r"prawo\s+do\s+odstąpienia", r"(?<!termin\s)(?<!terminu\s)(?<!data\s)nie\s+pasuje\s+mi", r"zmieniłe[mą]\s+zdanie",
        r"(?:dostał|przysła|przyszł|otrzymał)\w*\s+(?:zł\w*|inn\w*|nie\s+te\w*)\s+(?:produkt|towar|model|kolor|rozmiar|wymiar|sof|kanap|szaf|krzes|stoł|łóżk|materac|pralk|lodówk|zmywark|rzecz)\w*",
        r"zł(?:y|a|e|ą|ego|ym|ej|ych)\s+(?:produkt|towar|model|kolor|rozmiar|wymiar|sof|kanap|szaf|krzes|stoł|łóżk|materac|pralk|lodówk|zmywark)\w*",
        r"(?:dostał|przysła|przyszł|przyjecha|otrzymał)\w*\s+(?:\w+\s+){0,2}w\s+(?:zł|inn)(?:ym|ej|ych)\s+(?:kolor|rozmiar|wymiar|wzor|model)\w*",
        r"nie\s+ten\s+(?:produkt|towar|model|kolor|rozmiar)", r"pomyłk\w*\s+(?:w\s+zamówieni|przy\s+wysyłce)\w*", r"pomylon\w*\s+(?:towar|zamówieni|produkt)\w*",
    ),
    "refund_status": (
        r"zwrot\w*\s+(?:pieni|środk|kosztów|płatnoś|należnoś|kas[yęą]|gotówk)", r"zwróc\w*\s+(?:mi\s+|nam\s+)?(?:moje\s+|nasze\s+)?(?:pieni|środk|kas[ęyą]|koszt|należnoś|gotówk)",
        r"odda(?:ć|c)\s+(?:mi\s+)?(?:moje\s+)?(?:pieni|kas[ęyą])", r"oddaj\w*\s+(?:mi\s+|nam\s+)?(?:moje\s+|nasze\s+)?(?:pieni|kas[ęyą]|środk|gotówk)",
        r"(?:pieni|kas[ęyą])\w*\s+z\s+powrotem", r"(?:pieni|kas)\w*\s+(?:mi\s+)?(?:się\s+)?nale\w+", r"pieni[ąa]dz\w*\s+(?:nie\s+wróci|jeszcze\s+nie)", r"refundac\w*", r"refund\w*",
        r"kiedy\s+(?:dostan|otrzym|wróc)\w*\s+(?:mi\s+)?(?:mój\s+|swój\s+|moj\w*\s+)?(?:zwrot|pieni|środk)", r"kiedy\s+(?:będzie|dotrze|wpłynie|przyjdzie)\s+(?:mi\s+)?(?:mój\s+)?(?:zwrot|zwrócone|pieni)", r"kiedy\s+(?:mój\s+)?zwrot",
        r"gdzie\s+(?:są|jest)\s+(?:moj\w*\s+|moi\s+)?(?:pieni|zwrot|kasa|środk)", r"zwrot\w*\s+nie\s+(?:dotarł|przyszedł|wpłynął)",
        r"nie\s+(?:dostał|otrzymał|dotarł)\w*\s+(?:jeszcze\s+)?(?:mojego\s+)?(?:zwrot|pieni|kasy|środk)", r"czek\w*\s+(?:\w+\s+){0,3}na\s+(?:mój\s+|swój\s+)?(?:zwrot|pieni|kas|środk)", r"dostał\w*\s+(?:już\s+|jeszcze\s+)?(?:mój\s+)?zwrot",
        r"zwrot\w*\s+(?:jest\s+|został\s+)?(?:już\s+)?(?:zaksięgowan|zrealizowan|wysłan|zlecon|wypłacon|przelan)\w*", r"zwrot\w*\s+(?:już\s+)?(?:wpłynął|wrócił)",
    ),
    "order_status": (
        r"gdzie\s+(?:jest|są)\s+(?:moje|moja|mój|moj\w*)\s+(?:zamówieni|przesyłk|paczk|dostaw|towar)", r"status\s+(?:zamówieni|przesyłk|dostaw)", r"śledzeni\w*",
        r"numer\s+(?:śledzeni|przesyłk)", r"kiedy\s+(?:dotrze|przyjdzie|przyjedzie|dojdzie|będzie|dostanę|otrzymam)\s+.{0,30}(?:zamówieni|paczk|przesyłk|dostaw|towar|kurier)",
        r"\bprzesyłk\w*", r"\bpaczk\w*", r"gdzie\s+(?:jest|są)\s+(?:moje\s+)?zamówieni", r"termin\s+dostawy", r"kiedy\s+dostaw", r"kiedy\s+(?:ją|go|je)\s+dostan",
        r"\bnie\s+(?:dotarł|przyszł|przyjechał|dojechał|doszł|dostarczono|dostarczył)\w*", r"kurier\w*\s+(?:jeszcze\s+)?nie\s+(?:przyjechał|dojechał|dotarł|zadzwonił|był|dostarczył)\w*", r"kuriera\s+(?:nie\s+było|brak)",
        r"czekam\s+(?:już\s+)?(?:\w+\s+){0,3}na\s+(?:kurier|paczk|przesyłk|dostaw|zamówieni|towar)", r"opóźni\w*", r"spóźni\w*", r"spóźnia\w*", r"miało\s+być\s+(?:wczoraj|dzisiaj|dziś|w\s+\w+)", r"dalej\s+nic\b",
        r"nic\s+nie\s+(?:dotarło|przyszło|przyjechało)", r"nadal\s+nie\s+(?:ma\b|dotarł|przyszł)\w*", r"ciągle\s+nie\s+ma\b", r"kiedy\s+(?:ją|go|je|to)\s+(?:otrzym|dostan|doręcz|dostarcz)\w*", r"w\s+realizacji",
        r"\bnie\s+odebra\w*", r"\bdostarczon\w*", r"kurier\w*\s+(?:twierdzi|mówi|pisze|napisał|zgłosił|powiedział)",
    ),
    "delivery_change": (
        r"zmien\w*\s+(?:termin|datę|godzin|dostaw)", r"zmian\w*\s+(?:terminu|daty|dostaw|godzin)", r"przełoż(?!on)\w*", r"przeniesi\w*\s+(?:dostaw|termin)", r"przesun\w*", r"przesuwa(?:ć|m|my|cie)\b",
        r"inny\s+(?:termin|dzień)", r"inną\s+datę", r"nowy\s+termin", r"nowego\s+terminu", r"umówi\w*\s+(?:się\s+)?(?:na\s+)?(?:nowy|inny)", r"dostaw\w*\s+na\s+(?:piątek|poniedziałek|wtorek|środ|czwartek|sobot|niedziel)",
        r"(?:termin|dat|godzin)\w*\s+(?:\w+\s+){0,2}(?:mi\s+)?nie\s+pasuj\w*", r"kurier\w*\s+(?:ma\s+)?przyjechać\s+(?:w\s+inny|innego)",
    ),
    "address_change": (
        r"zmien\w*\s+(?:mój\s+|moj\w*\s+|naszego\s+)?adres", r"zmian\w*\s+adresu", r"nowy\s+adres", r"nowego\s+adresu", r"zły\s+adres", r"błędn\w*\s+adres", r"adres\s+dostawy",
        r"przeprowadz\w*\s+(?:się|sie)", r"zmieni\w*\s+miejsc\w*\s+dostawy", r"dostarczy\w*\s+(?:pod|na)\s+inny\s+adres", r"inny\s+adres",
        r"pomyli\w*\s+(?:się\s+)?(?:w\s+)?adres\w*", r"pomyłk\w*\s+w\s+adres\w*", r"literówk\w*\s+w\s+adres\w*", r"źle\s+(?:wpisał|podał|wpisan)\w*\s+adres", r"adres\w*\s+(?:jest\s+)?(?:zły|błędny|nieprawidłowy)", r"popraw\w*\s+adres",
    ),
    "warranty_claim": (
        r"gwarancj\w*", r"rękojmi\w*", r"reklamacj\w*", r"reklamow\w*", r"reklamuj\w*", r"napraw(?!d)\w*", r"usterk\w*", r"awari\w*", r"zepsuł\w*", r"popsuł\w*", r"serwis\w*\s+gwarancyjn\w*",
        r"\bwad(?:a|y|ę|ą|zie|ach)\s+(?:fabryczn|produkcyjn|ukryt|materiał)\w*", r"\b(?:ma|mają|miał\w*|z)\s+wad(?:ę|ą|a|y)\b",
        r"przestał\w*\s+(?:się\s+)?(?:działać|funkcjonować|grzać|chłodzić|pracować|wirować|ładować|włączać|świecić|mrozić|suszyć|pompować|odpływać|zasysać|domykać|otwierać)",
        r"\bnie\s+(?:chce\s+się\s+)?(?:włącz|uruchamia|startuje|ładuje|grzeje|chłodzi|mrozi|wiruje|świeci|odpływa|suszy|pompuje|zasysa|domyka|otwiera)\w*", r"\bpadł(?:a|o|y)\b", r"wysiad(?:ł|ła|ło|ły)\b",
        r"ciek(?:nie|ną)\b", r"przecieka\w*", r"skrzyp\w*", r"trzeszcz\w*", r"chwieje\s+się", r"hałasuj\w*", r"głośno\s+pracuje",
    ),
    "cancel_order": (
        r"anulow\w*", r"anuluj\w*", r"anulacj\w*", r"zrezygnow\w*\s+z\s+(?:zamówieni|zakup)", r"rezygnuj\w*\s+z\s+(?:zamówieni|zakup)", r"rezygnacj\w*\s+z\s+(?:zamówieni|zakup)",
        r"odwołać\s+(?:moje\s+)?zamówieni", r"cofnąć\s+zamówieni", r"nie\s+chcę\s+(?:już\s+)?(?:tego\s+)?(?:zamówieni|zakup)",
    ),
    "goodwill_request": (
        r"odszkodowan\w*", r"rekompensat\w*", r"zadośćuczynieni\w*", r"\bbon\s+(?:podarunk|rabat)\w*", r"\bkupon\w*", r"\brabat\w*", r"\bupust\w*", r"\bzniżk\w*", r"gest\s+(?:dobrej\s+woli|handlow)\w*",
        r"wynagrodz\w*", r"zadośćuczyni\w*", r"jakieś\s+(?:odszkodowanie|wyrównanie)", r"wyrównani\w*",
    ),
    "billing_question": (
        r"faktur\w*", r"rachun\w*", r"płatnoś\w*", r"zapłaci\w*", r"zapłacił\w*", r"pobran\w*", r"podwójn\w*", r"dwa\s+razy\s+(?:pobra|obciąż|zapłac)", r"obciążon\w*", r"obciąży\w*", r"obciążeni\w*\s+(?:karty|konta|rachunku)", r"opłat\w*",
        r"(?:do|nad)płat\w*", r"korekt\w*\s+faktur\w*", r"\bparagon(?:u|em|ie|y|ów|ach)\b", r"\bparagon\s+(?:fiskaln|za\b|do\b)",
        r"\bblik\b", r"przelew\w*", r"blokad\w*\s+(?:środków|na\s+karcie)", r"autoryzacj\w*", r"\brata\b", r"\braty\b", r"transakcj\w*", r"abonament",
    ),
    "installation_info": (r"montaż\w*", r"zamontow\w*", r"zainstalow\w*", r"instalacj\w*", r"instalow\w*", r"podłączeni\w*", r"podłącz\w*", r"złożeni\w*\s+(?:mebl|szaf|łóżk|biurk)", r"skręci\w*", r"\bmonter(?:a|owi|em|ze|zy|ów|ach)?\b"),
    "privacy_request": (
        r"\brodo\b", r"dane\s+osobow\w*", r"danych\s+osobowych", r"usuń\w*\s+(?:moje\s+)?(?:dane|konto)", r"usunięci\w*\s+(?:danych|konta)", r"prawo\s+do\s+bycia\s+zapomnian\w*",
        r"(?:skasow|wykasow|wymaz)\w*\s+(?:moje\s+|moich\s+)?(?:dane|danych|konto)", r"ochron\w*\s+danych", r"przetwarzani\w*\s+(?:moich\s+)?danych", r"zapomnij\s+(?:o\s+)?mnie", r"administrator\w*\s+danych", r"\buodo\b", r"wgląd\s+(?:do|w)\s+(?:moich\s+)?danych",
    ),
    "complaint": (
        r"skarg\w*", r"skarż\w*", r"zażaleni\w*", r"niedopuszczaln\w*", r"skandal\w*", r"oburza\w*", r"oburzon\w*", r"karygodn\w*", r"fatalna\s+obsługa", r"okropn\w*\s+(?:obsług|serwis)", r"skandaliczn\w*",
        r"bezczeln\w*", r"składam\s+skargę", r"nie\s+do\s+przyjęcia", r"wymagam\s+(?:rozmowy|kontaktu)",
    ),
    "policy_question": (
        r"jak\s+długo", r"jak\s+szybko", r"ile\s+(?:mam\s+|macie\s+|mamy\s+)?czasu", r"ile\s+(?:mam|macie|mamy|jest)\s+(?:dni|tygodni|miesięcy)\b", r"w\s+jakim\s+terminie", r"jaki\s+jest\s+termin",
        r"czy\s+(?:mogę|można|wolno)\s+(?:jeszcze\s+|w\s+ogóle\s+)?(?:zwróci|oddać|odesłać|wymieni|anulow|zmieni|odstąpi|zareklamow|reklamow)", r"\bwarunki\b", r"warunków",
        r"regulamin\w*", r"polityk\w*", r"jakie\s+są\s+warunki", r"ile\s+dni", r"czy\s+przysługuje", r"czy\s+mam\s+prawo", r"czy\s+(?:oferujecie|macie|przyjmujecie|akceptujecie)",
        # rules / terms / procedure as the subject of the question ("Jakie są Wasze zasady zwrotów?", "Zasady zwrotu", "Jakie macie warunki gwarancji")
        r"\bzasad(?:y|ach|ami|om)?\b", r"\bzasada\s+(?:zwrot|reklamacj|wymian|gwarancj|rękojmi|odstąpieni|dostaw)\w*", r"jak(?:a|ie|i)\s+(?:\w+\s+){0,2}(?:zasad|warunk|procedur|regulamin|polityk)\w*",
        r"\bwarunk(?:i|ach|ami|ów|om|u)\s+(?:zwrot|reklamacj|wymian|gwarancj|rękojmi|odstąpieni|dostaw|montaż|anulowani|płatnoś)\w*", r"\bprocedur(?:a|y|ę|ą|ze|om|ach|ami)\s+(?:zwrot|reklamacj|wymian|odstąpieni|anulowani)\w*",
        r"(?:informacj|wyjaśni|wiedzie|zapyta|dowiedzie|pytani)\w*\s+(?:\w+\s+){0,2}(?:o|na\s+temat|dotycz\w*|odnośnie|co\s+do)\s+(?:\w+\s+)?(?:zasad|warunk|regulamin|polityk|procedur|terminach|terminie)\w*",
        # eligibility / cost questions ("Czy zwrot jest bezpłatny?", "Czy potrzebuję paragonu do zwrotu?", "Czy zwracacie koszty przesyłki?")
        r"czy\s+(?:zwrot|zwroty|wymian\w*|reklamacj\w*|odstąpieni\w*|dostaw\w*|montaż\w*|odbiór)\s+(?:jest|są)\s+(?:\w+\s+)?(?:bezpłatn|darmow|płatn|możliw|dostępn|przyjmowan|uznawan|honorowan|obowiązując|ograniczon|limitowan)\w*",
        r"czy\s+(?:jest|są)\s+(?:\w+\s+)?(?:darmow|bezpłatn)\w*\s+(?:zwrot|wymian|dostaw|montaż|odbiór)\w*", r"czy\s+(?:koszt|koszty|opłat)\w*\s+(?:\w+\s+){0,3}(?:ponosi|pokrywa|ponoszę|pokrywam|ponosimy|ponosicie|pokrywacie)",
        r"czy\s+(?:zwracacie|przyjmiecie|odbieracie|honorujecie|uznajecie|refundujecie)\b(?!\s+mi\b)", r"czy\s+(?:muszę|trzeba|potrzebuję|potrzeba|konieczn\w*|wymagan\w*)\s+(?:\w+\s+){0,4}?(?:do\s+zwrotu|przy\s+zwrocie|do\s+reklamacji|przy\s+reklamacji|do\s+wymiany|do\s+odstąpienia)",
        r"jak\s+(?:mogę|można)\s+(?:zgłosić|złożyć|usunąć)", r"jak\s+(?:\w+\s+){0,2}(?:zgłosić|złożyć|zwrócić|wymienić|anulować|odstąpić|odesłać|skontaktować|zrobić|dokonać|przeprowadzić|wykonać|rozpocząć|zainicjować|uzyskać|odzyskać|oddać|reklamować|zareklamować|nadać)", r"jak\s+przebieg\w*",
        r"jakie\s+metody", r"w\s+jakich\s+godzinach", r"godziny\s+(?:pracy|otwarcia)",
        r"jak\s+działa", r"co\s+się\s+stanie\s+(?:jeśli|gdy)", r"czym\s+(?:się\s+)?różni\w*", r"jaka\s+jest\s+różnica", r"jakie\s+są\s+różnice", r"na\s+czym\s+polega", r"co\s+to\s+(?:jest|znaczy)", r"co\s+oznacza",
        r"jak(?:a|ie|i)\s+(?:jest|są)\s+(?:gwarancj|rękojmi|okres|zasad|warunk|koszt|cen)\w*", r"ile\s+(?:kosztuje|kosztują|wynosi|trwa)", r"do\s+kiedy\s+(?:mogę|można|mam|obowiązuj|trwa|przysługuj|ważn)\w*", r"w\s+ciągu\s+ilu\s+dni", r"po\s+ilu\s+dniach",
        r"czy\s+(?:da\s+się|jest\s+możliwość|istnieje\s+możliwość)", r"jak\s+wygląda\s+(?:procedur|proces)\w*", r"na\s+jakich\s+(?:zasadach|warunkach)", r"jak(?:ie|ich)\s+dokument", r"kto\s+(?:pokrywa|ponosi|płaci|zapłaci)", r"ile\s+(?:lat|miesięcy|tygodni)\b",
        r"mam\s+pytanie\s+(?:dotycz\w*|odnośnie|co\s+do)\s+(?:\w+\s+)?(?:gwarancj|rękojmi|zwrot|reklamacj|regulamin|warunk|polityk)\w*",
    ),
    "product_info": (r"wymiar\w*", r"rozmiar\w*", r"kolor\w*", r"dostępn\w*\s+(?:w|jest)", r"materiał\w*", r"parametr\w*", r"specyfikacj\w*", r"w\s+jakim\s+kolorze", r"czy\s+jest\s+dostępn\w*"),
    "greeting": (r"^(?:dzień\s+dobry|dobry\s+wieczór|dobry\s+dzień|cześć|witam|witaj\w*|hej|hejka|halo|siema\w*|hejo|elo)\b",),
    "goodbye": (
        r"do\s+widzenia", r"dowidzenia", r"to\s+(?:już\s+)?wszystko[\s,.!]*(?:dziękuj\w*|dzięki|na\s+dzisiaj|na\s+razie)?[\s.!]*$", r"nic\s+więcej[\s,.!]*(?:dziękuj\w*|dzięki)?[\s.!]*$", r"nie,?\s+dziękuję",
        r"^[^\w\s]*(?:no\s+to\s+)?na\s+razie[\s.!]*(?:dziękuj\w*|dzięki|pa)?[\s.!]*$", r"pozdrawiam", r"miłego\s+dnia", r"do\s+usłyszenia", r"dziękuję\s+za\s+pomoc", r"to\s+tyle[\s.!]*$", r"to\s+by\s+było\s+na\s+tyle", r"wszystko\s+jasne,?\s+dziękuję",
    ),
}

# weak evidence: counts only when nothing else matched ("pralka nie działa" is a warranty claim, "mój tracking nie działa" an order-status question, "kod rabatowy nie działa" a voucher question)
WEAK_INTENTS: dict[str, tuple[str, ...]] = {"warranty_claim": (r"nie\s+działa\w*",)}
# English loan words that Poles mix into Polish sentences ("order jest delayed", "status ordera"); matched only when the text is known to be Polish, so English behaviour cannot change
INTENTS_PL_CONTEXT: dict[str, tuple[str, ...]] = {
    "order_status": (r"\bdelay(?:ed|s)?\b", r"\bstatus(?:u|em|ie)?\b", r"\bstatus\s+order\w*", r"\border\w*\s+(?:jest\s+)?(?:late|delayed)\b"),
    "cancel_order": (r"\bcancel\w*\s+(?:zamówieni|order)\w*",),
}

RISKS: dict[str, tuple[str, ...]] = {
    "legal_threat": (
        r"\bpozew\w*", r"\bpozw(?:u|em|ie|y|ów|om|ami|ach)\b", r"\bpozwać\b", r"\bpozwę\b", r"\bpozwie(?:my|cie)?\b", r"\bpozwą\b", r"\bpozyw\w*", r"\bsąd(?:u|zie|em|y|ów|ach|owi)\b", r"\bsądow\w*",
        r"prawnik\w*", r"adwokat\w*", r"radc\w*\s+prawn\w*", r"kancelari\w*\s+(?:prawn|adwokack|radcowsk)\w*", r"(?:wezwani\w*|pism\w*)\s+(?:od|z)\s+kancelari\w*", r"\buokik\w*",
        r"rzecznik\w*\s+(?:praw\s+)?konsument\w*", r"rzecznik\w*\s+konsumenck\w*", r"powiatow\w*\s+rzecznik\w*", r"federacj\w*\s+konsument\w*", r"centrum\s+konsumenck\w*", r"inspekcj\w*\s+handlow\w*",
        r"urząd\w*\s+ochrony\s+konkurencji", r"na\s+drogę\s+prawną", r"drog\w*\s+prawn\w*", r"krok\w*\s+prawn\w*", r"skierować\s+sprawę\s+do\s+sądu", r"zgłoszę\s+(?:to\s+)?(?:do|na)\s+(?:uokik|policj|prokurat)",
        r"prokurat\w*", r"pozwolę\s+(?:was|firmę)\s+do\s+sądu", r"przedsądow\w*", r"dochodzi\w*\s+(?:swoich\s+)?(?:praw|roszcze\w*|odszkodowani\w*)", r"pomoc\w*\s+prawn\w*", r"wystąp\w*\s+z\s+roszczeni\w*",
        r"roszczeni\w*\s+(?:o|z\s+tytułu)\s+(?:odszkodowani|zadośćuczynieni)",
    ),
    "vulnerable_customer": (
        r"osob\w*\s+(?:starsz|niepełnosprawn|niewidom|ślep|głuch|chor|samotn)\w*", r"starsz\w*\s+(?:osob|pan|pani)", r"jestem\s+(?:już\s+)?(?:starsz|niepełnosprawn|niewidom|ślep|głuch|chor|samotn|po\s+operacji|po\s+udarze|po\s+zawale|po\s+wylewie|po\s+chemioterapii)\w*",
        r"niepełnosprawn\w*", r"niewidom\w*", r"słabowidząc\w*", r"niedowidz\w*", r"niedosłysz\w*", r"\bgłuch(?:y|a|e|ą|ego|ej|ym|ych|ymi|emu|oniem\w*)\b", r"wózk\w*\s+inwalidzk\w*", r"(?:jestem|poruszam\s+się|siedzę|jeżdżę)\s+na\s+wózku",
        r"jestem\s+(?:już\s+)?(?:na\s+)?(?:emeryt\w*|rencist\w*)", r"jestem\s+na\s+(?:emeryturze|rencie)", r"mam\s+(?:małą\s+|niską\s+)?(?:emerytur\w*|rent(?:ę|e|a))\b",
        r"opiekuj\w*\s+się\s+(?:chor|starsz|niepełnosprawn|matk|ojc|mam|tat|babci|dziadk|rodzic|męż|żon|teśc)\w*", r"jestem\s+(?:czyimś\s+)?opiekun\w*", r"opiekun\w*\s+(?:osob|chor|starsz|niepełnosprawn)\w*",
        r"w\s+żałobie", r"zmarł\w*", r"umar(?:ł|ła)\s+mi\b", r"(?:mama|babcia|dziadek|dziadkowie|tata|ojciec|matka|teściowa|teść|rodzice)\s+(?:ma|mają)\s+(?:już\s+)?(?:7\d|8\d|9\d)\s+lat", r"owdowiał\w*", r"pochowa\w*", r"mam\s+(?:już\s+)?(?:7\d|8\d|9\d)\s+lat", r"\b(?:7\d|8\d|9\d)[\s-]?letni\w*", r"w\s+podeszłym\s+wieku",
        r"jestem\s+w\s+szpital\w*", r"leżę\s+w\s+szpital\w*", r"ciężko\s+chor\w*", r"choruj\w*\s+na", r"depresj\w*", r"autyzm\w*", r"nie\s+radzę\s+sobie", r"ledwo\s+chodzę", r"trudno\s+mi\s+(?:chodzić|otworzyć|wyjść|się\s+poruszać)",
        r"mam\s+trudnośc\w*\s+(?:z|w)\s+(?:chodzeni|poruszani|widzeni|słyszeni|mówieni|oddychani)\w*", r"słabo\s+widzę", r"źle\s+widzę", r"nie\s+widzę\s+(?:dobrze|zbyt\s+dobrze)",
        r"problem\w*\s+(?:ze\s+wzrokiem|ze\s+słuchem|z\s+chodzeniem|z\s+poruszaniem\s+się|ze\s+słyszeniem|z\s+widzeniem)", r"słab\w*\s+(?:wzrok|słuch)", r"\bseniork\w*", r"\bseniorz\w*", r"\bseniorem\b",
        r"(?:jest|była|był|są)\s+po\s+(?:udarze|operacji|zawale|wylewie|chemioterapii)", r"słabo\s+słyszę\b(?!\s+(?:pana|pani|was|państwa|ciebie|cię))", r"nie\s+mogę\s+(?:chodzić|wstać|wychodzić\s+z\s+domu)",
    ),
    "fraud_suspected": (
        r"oszust\w*", r"oszuk\w*", r"wyłudz\w*", r"kradzie\w*", r"\b(?:u|s|o|wy)?krad(?:ł|n|z)\w*", r"nie\s+składał\w*\s+(?:tego\s+|żadnego\s+)?zamówieni\w*",
        # "Nie zamawiałem tego zamówienia / tej paczki / niczego / tego." is a transaction the customer does not know; "nie zamawiałem tej wersji / tego koloru / tego krzesła" is a wrong item
        r"nie\s+zamawiał\w*(?=\s*(?:$|[.,!?;]|(?:tego|tej|tych|żadn\w+)\s+(?:\w+\s+)?(?:zamówieni|zakup|transakcj|przesyłk|paczk|płatnoś|operacj)\w*|(?:tego|tych)\s*(?:$|[.,!?;])|niczego|ani\b|nic\b|na\s+moje))",
        r"nie\s+(?:robił|wykonywał|dokonywał|dokonał|zlecał|autoryzowa)\w*\s+(?:tej\s+|tego\s+|żadnej\s+|żadnego\s+)?(?:transakcj|płatnoś|przelew|zakup|obciążeni|zamówieni)\w*",
        r"nie\s+rozpoznaj\w*\s+(?:tej\s+|tego\s+|tych\s+)?(?:transakcj|płatnoś|obciążeni|zamówieni|zakup|przelew)\w*", r"nie\s+ja\s+(?:zamawia|kupowa|płaci|robi|składa)\w*",
        r"(?:pobra|obciąż|zapłac|zamów|transakcj|płatnoś|konto|konta|kart|przelew|zakup)\w*[^.!?]{0,60}\bbez\s+(?:mojej\s+)?(?:wiedzy\s+(?:i|oraz)\s+)?zgody",
        r"\bbez\s+(?:mojej\s+)?(?:wiedzy\s+(?:i|oraz)\s+)?zgody[^.!?]{0,60}(?:pobra|obciąż|zapłac|zamów|transakcj|płatnoś|konto|kart|przelew|zakup)\w*",
        r"nieautoryzowan\w*", r"nieuprawnion\w*", r"przej(?:ął|ęł|ęt|ęci)\w*\s+(?:moje\s+|mojego\s+|mojej\s+)?(?:konto|konta|kart)\w*", r"włam\w*", r"zhakow\w*", r"\bhaker\w*", r"hakowan\w*",
        r"ktoś\s+(?:\w+\s+){0,2}(?:użył|używa|wykorzystał|założył|zamówił|zalogował|zmienił|przejął|dostał\s+się|podszył|wszedł|włamał|zhakował|kupił|zapłacił|wyłudził)", r"podszy\w*", r"phishing", r"\bfraud\w*",
        r"fałszyw\w*\s+(?:sms|mail|e-?mail|strona|witryn|wiadomo|link|faktur|sklep)", r"obc\w+\s+(?:transakcj|obciążeni|zamówieni|płatnoś)\w*", r"nieznan\w*\s+(?:zamówieni|transakcj|obciążeni|płatnoś)\w*",
        r"podejrzan\w*\s+(?:transakcj|obciążeni|zamówieni|płatnoś|sms|mail|e-?mail|wiadomo|link|logowani|aktywnoś)\w*", r"nie\s+moje\s+zamówieni", r"wyciek\w*\s+(?:moich\s+)?(?:danych|hasł|numeru\s+karty|karty)",
        r"(?:transakcj|płatnoś|przelew|zakup|obciążeni)\w*,?\s+(?:których|której|którego|którą|którym)\s+nie\s+\w+",
    ),
    "safety_issue": (
        r"zapach\w*\s+gazu", r"(?:czuć|czuję|czuje|czujemy|czuły|czuła|czuli|wyczułem|wyczułam|śmierdzi|pachnie|cuchnie|zalatuje|capi)\s+(?:\w+\s+){0,2}(?:gaz|dym|spalen|spalon|palon|pożar|czad)\w*",
        r"(?:czuć|czuję|czuje|czujemy|wyczułem|wyczułam|śmierdzi|pachnie|cuchnie|zalatuje)\s+(?:\w+\s+){0,3}(?:się\s+)?pali(?:ł|ło|ła)?\b",
        r"ulatnia\w*\s+się\s+(?:gaz|czad)\w*", r"wyciek\w*\s+(?:gazu|czadu)", r"ulatniając\w*\s+się", r"gaz\w*\s+(?:się\s+)?(?:ulatnia|wydobywa)\w*",
        r"\bpożar(?:u|owi|em|ze|y|ów|ach)?\b", r"straż\w*\s+pożarn\w*", r"płomie\w*", r"\bdym(?:u|em|ie|y|ów)?\b", r"\bdymi(?!sj)\w*", r"(?<!na\s)\biskr\w*", r"poraż\w*\s+(?:mnie\s+)?prąd\w*", r"porażeni\w*\s+prąd\w*",
        r"razi\s+prądem", r"kopi\w*\s+(?:mnie\s+)?prąd\w*", r"prąd\w*\s+(?:mnie\s+)?(?:poraz|kopn|kopie|razi|uderz)\w*", r"kopnął\s+(?:mnie\s+)?prąd", r"zwarci\w*", r"przegrz\w*", r"stopił\w*",
        r"(?:kabel|przewód|wtyczk|gniazd|obudow|plastik|ładowark|zasilacz)\w*\s+(?:się\s+)?(?:topi|stopi|pal(?:i|ą)|iskrz|dymi|żar|tli)\w*", r"topi\w*\s+się\s+(?:kabel|przewód|wtyczk|gniazd|obudow|plastik|ładowark|zasilacz)\w*",
        r"spaleni\w*", r"spalon\w*\s+(?:kabel|wtyczk|przewod|zasilacz|gniazdk|bezpiecznik|silnik|grzałk|kuchenk|piekarnik|ładowark|płyt)\w*", r"spali(?:ł|ła|ło)\w*\s+się", r"czarn\w*\s+od\s+spalenia",
        r"zapach\w*\s+spalenizn\w*", r"\bpal(?:i(?:ł|ło|ła|ły)?|ą)\s+się\b(?!\s+(?:\w+\s+){0,2}(?:lampk|diod|kontrol|światł|led\b|wskaźnik|ikon|ekran))",
        r"zapali(?:ł|ła|ło|ły)\w*\s+się\b(?!\s+(?:\w+\s+){0,2}(?:lampk|diod|kontrol|światł|led\b|wskaźnik|ikon|ekran))", r"zapłon\w*", r"zagrożeni\w*\s+(?:życia|zdrowia)", r"zagraża\w*\s+(?:życiu|zdrowiu|bezpieczeństw\w*)",
        r"\bran(?:ny|na)\b", r"zrani(?:ł|ła|łem|łam|ło)\w*", r"skalecz\w*", r"poparz\w*", r"oparz\w*", r"\buraz(?:u|em|y|ów)?\b", r"obrażeni\w*", r"krwaw\w*", r"krwotok\w*",
        r"przewróci\w*\s+się\s+na\s+(?:dziecko|mnie|syna|córk|psa|kota)\w*", r"przygnio\w*", r"zadław\w*", r"udławi\w*", r"połkn\w*\s+(?:\w+\s+){0,2}(?:śrub|bateri|magnes|element|część|części|monet)\w*",
        r"\bwybuch(?:ł|ła|ło|ły|nęła|nęło|nął|u|em|ie)?\b", r"(?:nadym|puchn)\w*\s+(?:się\s+)?bateri\w*", r"bateri\w*\s+(?:się\s+)?(?:nadym|puchn)\w*",
        r"\bczad(?:u|em|zie)\b", r"(?:ulatnia\w*\s+się|wydziela\w*|wyczuwam|alarm|czujnik\w*)\s+(?:\w+\s+)?czad\b", r"tlenek\s+węgla", r"\bzatru(?:cie|ci|ł|ła|ć)\w*", r"pogotowi\w*", r"karetk\w*",
        r"\bparz(?:y|ą|yło)\b", r"sycz\w*[^.!?]{0,40}\bgaz\w*", r"\bgaz\w*[^.!?]{0,60}\bsycz\w*", r"gazow\w*[^.!?]{0,60}\bczu(?:ć|ję|je)\s+(?:jakiś\s+|dziwny\s+|silny\s+)?zapach", r"(?:uderz|przygni)\w*\s+(?:mnie|dzieck\w*|moje\w*\s+dzieck\w*|syna|córk\w*)",
    ),
    "regulatory_complaint": (r"\buodo\w*", r"urz[ęe]d\w*\s+ochrony\s+danych", r"rzecznik\w*\s+finansow\w*", r"rzecznik\w*\s+praw\s+obywatelsk\w*", r"\bknf\b", r"\bgiodo\b", r"komisj\w*\s+nadzor\w*", r"\bombudsman\w*", r"organ\w*\s+nadzor\w*"),
    "churn_risk": (
        r"nigdy\s+więcej", r"więcej\s+(?:u\s+was|od\s+was|tu)\s+nie\s+(?:kupi|zamów|będę)", r"przechodzę\s+do\s+(?:konkurencji|innego)", r"(?:idę|pójdę|przejdę|zmieniam)\s+(?:już\s+)?(?:do\s+)?(?:konkurencji|innego\s+sklepu|innej\s+firmy)",
        r"zrezygnuj\w*\s+z\s+(?:klubu|konta|członkostwa)", r"rezygnuję\s+z\s+(?:waszych\s+usług|współpracy|zakupów|klubu|konta)", r"zamykam\s+konto", r"(?:to|jest|był|było)\s+(?:już\s+)?(?:mój\s+)?ostatni\s+(?:raz|zakup)",
        r"przeniosę\s+się\s+do", r"kupię\s+gdzie\s+indziej", r"nie\s+będę\s+już\s+(?:u\s+was\s+)?(?:kupować|zamawiać)", r"nie\s+będę\s+(?:już\s+)?(?:wa\w+\s+)?klient\w*", r"nie\s+polec\w*\s+was",
    ),
}
# diacritic-SENSITIVE rules (matched on the lower-cased text, not on the folded text): `sąd` = court, but the folded `sad` is also the English adjective
RISKS_RAW: dict[str, tuple[str, ...]] = {"legal_threat": (r"\bsąd\b",)}
# diacritic-less forms that are only safe when the text is known to be Polish (the conversation language or Polish letters / words around it)
RISKS_PL_CONTEXT: dict[str, tuple[str, ...]] = {"legal_threat": (r"\bsad\b",)}
# negated phrasing ("nie zamierzam pozywać", "to nie jest oszustwo", "nie czuję zapachu gazu") is removed from the text before the risk rule runs; `contrast` = a "ale / jednak / jeśli" keeps a soft threat alive
NEGATED: dict[str, tuple[bool, tuple[str, ...]]] = {
    "legal_threat": (
        True,
        (
            r"\bnie\s+(?:zamierzam|chcę|chce|będę|planuję|mam\s+zamiaru)\s+(?:(?:was|firmy|nikogo|nikomu|tego|w\s+ogóle|jeszcze|teraz)\s+)?(?:pozywać|pozwać|iść\s+do\s+sądu|wnosić\s+pozwu|składać\s+pozwu|kierować\s+sprawy\s+do\s+sądu|angażować\s+prawników|podejmować\s+kroków\s+prawnych)",
            r"\bnie\s+planuj\w*\s+(?:żadnych\s+)?kroków\s+prawnych", r"\bbez\s+(?:sądu|sądów|prawników|adwokatów|pozwu|pozwów|kroków\s+prawnych)",
            # a question about an obligation ("Czy muszę iść do sądu?") is not a threat to go there
            r"\bczy\s+(?:muszę|trzeba|będę\s+musiał\w*|będzie\s+trzeba|konieczn\w*)\s+(?:\w+\s+){0,3}do\s+sądu",
        ),
    ),
    "fraud_suspected": (
        False,
        (
            r"\bto\s+nie\s+(?:jest\s+)?(?:żadne\s+)?(?:oszustwo|wyłudzenie|kradzież)", r"\bnie\s+(?:podejrzewam|sądzę|myślę|twierdzę)\s+(?:o\s+)?(?:oszustw\w*|wyłudzeni\w*|kradzież\w*)",
            r"\bnie\s+(?:chodzi|mówię)\s+o\s+(?:oszustw\w*|wyłudzeni\w*|kradzież\w*)", r"\bbez\s+oszustw\w*",
        ),
    ),
    "safety_issue": (
        False,
        (
            r"\bnie\s+(?:czuć|czuję|czujemy|czuje)\s+(?:żadnego\s+|zapachu\s+)*(?:gazu|dymu|spalenizny)", r"\bnie\s+ma\s+(?:żadnego\s+)?(?:dymu|zapachu\s+(?:gazu|spalenizny)|ognia|pożaru)",
            r"\bbez\s+(?:zapachu\s+(?:gazu|spalenizny)|dymu)", r"\bani\s+(?:dymu|zapachu\s+(?:gazu|spalenizny))",
        ),
    ),
}
SELF_HARM = (
    r"zabij\w*\s+się", r"zabić\s+się", r"\bsię\s+zabi\w*", r"samobójstw\w*", r"samobójcz\w*", r"odebrać\s+sobie\s+życie", r"odbiorę\s+sobie\s+życie", r"nie\s+chcę\s+(?:już\s+)?żyć", r"nie\s+chce\s+mi\s+się\s+żyć",
    r"nie\s+mam\s+po\s+co\s+żyć", r"skrzywdz\w*\s+się", r"(?:zrobię|zrobić)\s+sobie\s+krzywd\w*", r"targnąć\s+się\s+na\s+życie", r"targnę\s+się\s+na\s+życie", r"chcę\s+umrzeć", r"skończę\s+ze\s+sobą", r"skończyć\s+ze\s+sobą",
    r"powieszę\s+się", r"rzucę\s+się\s+(?:pod|z)\b", r"wolałbym\s+nie\s+żyć",
)

# (regex fragment, weight): matched on the folded text; fragments carry their own `\b` so that short stems stay prefixes (`kpin` -> kpina) and English words cannot collide (`dramat` -> dramatic)
NEG_RX: tuple[tuple[str, float], ...] = (
    (r"\bwściek\w*", 1.1), (r"\bwkurz\w*", 1.0), (r"\bzdenerwow\w*", 0.8), (r"\bzłoszcz\w*", 0.8), (r"\bwnerw\w*", 0.9), (r"\bskandal\w*", 1.0), (r"\boburz\w*", 1.0), (r"\bkarygodn\w*", 1.0),
    (r"\bniedopuszczaln\w*", 1.0), (r"\bbezczeln\w*", 1.0), (r"\barogan\w*", 0.9), (r"\bokropn\w*", 0.9), (r"\bfataln\w*", 0.9), (r"\btragedi\w*", 0.9), (r"\btragiczn\w*", 0.9), (r"\bkatastrof\w*", 0.9),
    (r"\bbeznadziejn\w*", 0.9), (r"\bkiepsk\w*", 0.6), (r"\bmarnie\b", 0.6), (r"\brozczarow\w*", 0.7), (r"\bzawiod\w*", 0.7), (r"\bzawiedzen\w*", 0.7), (r"\bzawiedli\w*", 0.7), (r"\bzawiedzion\w*", 0.7), (r"\bniezadowol\w*", 0.7),
    (r"\bdenerw\w*", 0.7), (r"\birytuj\w*", 0.7), (r"\birytac\w*", 0.7), (r"\bmam\s+(?:już\s+)?dość", 0.9), (r"\b(?:dość|dosyć)\s+tego", 0.9), (r"\bjakiś\s+żart", 0.8), (r"\bto\s+żart", 0.8), (r"\bkpin\w*", 0.9),
    (r"\bkłamc\w*", 0.9), (r"\bokłama\w*", 0.9), (r"\bkłamie\w*", 0.9), (r"\boszust\w*", 0.9), (r"\bzłodziej\w*", 0.9), (r"\bnikt\s+nie\s+(?:odpowiada|odbiera|odpisuje|reaguje|oddzwania)", 0.6),
    (r"\bznowu\b", 0.4), (r"\bznów\b", 0.4), (r"\bponownie\b", 0.3), (r"\bwciąż\b", 0.4), (r"\bnadal\b", 0.4), (r"\bjeszcze\s+nie\b", 0.4), (r"\bdo\s+tej\s+pory\s+nie\b", 0.5), (r"\bdalej\s+nie\b", 0.4),
    (r"\bnigdy\b", 0.35), (r"\bkolejn\w*\s+raz\b", 0.8), (r"\btrzeci\s+raz\b", 0.8), (r"\bpo\s+raz\s+trzeci\b", 0.8), (r"\bczekam\b", 0.3), (r"\buszkodz", 0.35), (r"\bnie\s+działa", 0.3), (r"\bcholern\w*", 0.7),
    (r"\bcholera\b", 0.7), (r"\bzła\s+obsługa", 0.8), (r"\bdo\s+niczego\b", 0.8), (r"\bniekompetent\w*", 0.9), (r"\bżenując\w*", 0.9), (r"\bżenad\w*", 0.9), (r"\bwstyd\w*", 0.8), (r"\bnie\s+do\s+przyjęcia\b", 1.0),
    (r"\bnie\s+wierzę\b", 0.5), (r"\bdramat(?:u|em|y|ów|om|ami|ach|ie|yczn\w*)?\b", 0.8), (r"\bnie\s+macie\b", 0.4), (r"\bbałagan\w*", 0.7), (r"\b(?:bajzel|burdel)\w*", 0.8), (r"\bstraszn\w*", 0.8), (r"\bpaskudn\w*", 0.8),
    (r"\bobrzydliw\w*", 0.9), (r"\bkoszmar\w*", 1.0), (r"\bmęcz(?:y|yć|ą|yl\w*|ąc\w*|arn\w*)\b", 0.5),
    (r"\bporażk\w*", 0.9), (r"\bmasakr\w*", 0.9), (r"\bbubel\w*", 0.9), (r"\bbadziew\w*", 0.9), (r"\bszmelc\w*", 0.9), (r"\bchłam(?:u|em|ie|y)?\b", 0.9), (r"\btandet\w*", 0.9), (r"\bsyf\b", 0.9), (r"\blipa\b", 0.7), (r"\bkicha\b", 0.7),
    (r"\bw\s+szoku\b", 0.6), (r"\bręce\s+opadają", 0.8), (r"\bolew\w*", 0.7), (r"\blekceważ\w*", 0.8), (r"\bzero\s+(?:kontaktu|odpowiedzi|reakcji)", 0.8), (r"\bbrak\s+(?:kontaktu|odpowiedzi|reakcji)", 0.6),
    (r"\bawari\w*", 0.5), (r"\bpsia\s+krew\b|\bpsiakrew\b", 0.6), (r"\bdo\s+diabła\b", 0.6), (r"\bkurde\b|\bkurcz(?:ę|e)\b|\bkurn(?:a|o)\b", 0.6),
)
# emoji are language-neutral, so they only count for Polish text (the shared English rules ignore them and must stay as they are)
EMOJI_NEG = ("😡", "🤬", "😠", "😤", "👎", "💩", "🖕", "😒")
EMOJI_POS = ("👍", "😊", "🙂", "😀", "😃", "😁", "🙏", "❤", "😍", "👌", "👏", "😄")
POS_RX: tuple[tuple[str, float], ...] = (
    (r"\bdziękuj", 0.5), (r"\bdziękuję\s+bardzo", 0.7), (r"\bbardzo\s+dziękuj", 0.7), (r"\bserdecznie\s+dziękuj", 0.7), (r"\b(?:wielkie|ogromne)\s+dzięki\b|\bdzięki\s+wielkie\b|\bogromnie\s+dziękuj", 0.7), (r"\bświetn", 0.7),
    (r"\bdoskonał", 0.8), (r"\bznakomit", 0.8), (r"\bidealn", 0.7), (r"\bwspaniał", 0.7), (r"\brewelacyjn", 0.8), (r"\bbardzo\s+dobr", 0.6), (r"\bdobrze\b", 0.35), (r"\bzadowol", 0.6), (r"\bpolecam\b", 0.7),
    (r"\bpomocn", 0.6), (r"\bmiło\b", 0.4), (r"\bmił(?:a|y|e|ą|ego|ej)\s+(?:obsług|pani|pan|rozmow|osob|atmosfer|dziewczyn|człowiek|konsultant)", 0.4), (r"\bsympatyczn", 0.5), (r"\bfantastyczn", 0.7), (r"\bperfekcyjn", 0.7),
    (r"\bgenialn", 0.7), (r"\bcenię\b", 0.5), (r"\buprzejm", 0.5), (r"\bsprawnie\b", 0.5), (r"\bprofesjonaln", 0.6), (r"\bratujecie\b|\bratujesz\b|\buratowa", 0.6),
)  # "super" and "dzięki" are already in the shared (en / de / ...) table - adding them here would count them twice
# a praise followed (in the same breath) by a complaint is sarcasm: "No super, znowu nie dotarło", "Świetnie, kolejna awaria"
SARCASM = (
    r"\b(?:no\s+)?(?:super|świetnie|świetna|świetny|brawo|rewelacja|rewelacyjnie|gratuluję|doskonale|wspaniale)\b[^.!?]{0,40}\b(?:znowu|znów|kolejn\w*\s+(?:raz|awari\w*|opóźnieni\w*|problem\w*)|ponownie|awari\w*|zepsut\w*|uszkodz\w*|opóźnion\w*|nie\s+(?:dotarł\w*|działa\w*|przyszł\w*|odpowiada\w*|odbiera\w*))",
)
# "nie jestem wcale zadowolona" (the English rule only looks 12 characters back)
NEGATED_SATISFACTION_PL = r"\bnie\b(?:\s+\w+){0,4}\s+(?:zadowol\w*|usatysfakcjonowan\w*)"
PROFANITY = (
    r"kurw\w*", r"\bchuj\w*", r"\bhuj(?:|a|u|em|ow\w*|ek|ki|nia)\b", r"\bjeb(?:a|ie|ią|n|ł)\w*", r"pierdol\w*", r"pierdz\w*", r"spierdal\w*", r"spieprz\w*", r"wypierdal\w*", r"\bdup(?:a|ek|ie|y|ki|sk\w*)\b",
    r"\bgówn(?:o|a|e|em|ie|u|y|iar\w*|ian\w*)\b", r"\bdebil(?!it)\w*", r"\bidiot(?:a|o|y|ów|om|ami|ach|ycz\w*|yzm\w*|k\w*)\b|\bidioci\b|\bidiocie\b", r"kretyn\w*", r"skurwysyn\w*", r"skurwiel\w*", r"sukinsyn\w*",
    r"pojeb\w*", r"zjeb\w*", r"pizd\w*", r"\bcwel\w*", r"dziwk\w*", r"\bszmato\b", r"\bszmaciar\w*", r"\bfiut\w*", r"\bkutasie\b|\b(?:ty|jesteś|jesteście|ale|zwykły|stary|pieprzony)\s+kutas(?:y|ie)?\b", r"\bpalant(?:|a|y|em|ów|om|ami|ach|owi|ka|ki)\b|\bpalanci\b|\bpalancie\b",
    r"\bmatoł\w*", r"\bgnoj\w*", r"zasran\w*", r"popierdol\w*", r"\bpieprzon\w*",
)  # (`gown`, `debilitating`, `idiot`/`idiotic`, `Jebel`, `Hujan`, `Palantir` are English / foreign words and `kutasy` are tassels: the stems carry explicit endings; `szmatka` is a cleaning cloth, not an insult)
_M = r"[*#@._\-]"
# masked / spelled-out profanity ("k***a", "ch*j", "j*bany", "pier***lę", "k u r w a") -> canonical stem, applied to the folded text before the profanity rule runs
MASKED_PROFANITY: tuple[tuple[str, str], ...] = (
    (rf"\bk[*#@]{{2,4}}a\b|\bku[*#@]{{1,2}}a\b|\bku{_M}wa\b|\bkur{_M}a\b|\bk{_M}rwa\b|\bkur{_M}wa\b|\bkurw[*#@]|\bk[.\-_ ]u[.\-_ ]r[.\-_ ]w[.\-_ ]a\b", "kurwa"),
    (rf"\bch{_M}{{1,2}}j\w*|\bchu[*#@](?!\w)|\bh[*#@]j\b", "chuj"),
    (r"\bj[*#@]{1,2}b(?:an|ac|ni|ie)\w*|\bjeb[*#@]{1,2}\w*", "jebany"),
    (r"\bpier[*#@]{1,4}(?:ol|l)\w*|\bpierd[*#@]{1,3}l\w*|\bp[*#@]{3,6}r?dol\w*|\bpi[*#@]{2,4}r?dol\w*", "pierdole"),
    (r"\bsp[*#@]{3,8}(?:laj|lac)\w*|\bspier[*#@]{1,4}(?:laj|lac)\w*", "spierdalaj"),
    (r"\bsk[*#@]rw\w*", "skurwysyn"),
    (r"\bpi[*#@]{1,3}d(?:a|y|e|zie|om|ami|ach)?\b|\bp[*#@]{2,3}zd\w*", "pizda"),
)
THREATS = (r"zabij\w*\s+(?:cię|ciebie|was|pana|panią)", r"zniszcz\w*\s+(?:was|firmę|cię)", r"połamię", r"znajdę\s+(?:cię|was)", r"wysadz\w*", r"\bbomb\w*", r"spalę\s+(?:was|sklep|firmę)", r"zrobię\s+wam\s+krzywdę")
URGENT = (
    r"\bpiln(?:y|a|e|ie|ego|ej|ym|ych|ą|ymi|emu)\b", r"\bpilnoś\w*", r"natychmiast\w*", r"od\s+razu", r"od\s+zaraz", r"na\s+już\b", r"jak\s+najszybciej", r"niezwłocznie", r"bez\s+zwłoki", r"w\s+trybie\s+pilnym",
    r"nagł\w*\s+sprawa", r"\bnagły\b", r"awaryjn\w*", r"bardzo\s+szybko", r"w\s+trybie\s+nagłym", r"najpóźniej\s+(?:dzisiaj|dziś|jutro)",
)
AFFIRM = (
    r"^(?:ta{1,}k+|owszem|oczywiście|jasne|pewnie|zgoda|dobrze|dobra|okej|oki|okey|ok|spoko|w\s+porządku|może\s+być|niech\s+będzie|potwierdzam|zgadzam\s+się|proszę\s+(?:zrealizować|realizować|o\s+realizację|robić|zlecić|działać|kontynuować|dalej)|realizuj|zrób\s+to|dawaj|robimy\s+to|jak\s+najbardziej|tak\s+jest|no\s+(?:tak|dobra|dobrze|ok|okej)|nie\s+ma\s+(?:problemu|sprawy))\b",
    r"\btak,?\s+(?:proszę|poproszę|zgadzam|potwierdzam|zrób|zlecaj|realizuj)", r"\bpotwierdzam\b", r"\bzgadzam\s+się\b",
)
# "Tak, ale najpierw ..." / "Dobrze, tylko jeśli ..." is a conditional answer, not a confirmation of the pending action
CONDITIONAL = r"^(?:tak|dobrze|dobra|zgoda|jasne|ok|okej|oczywiście|pewnie|spoko|niech\s+będzie)\b[^.!?]{0,60}\b(?:ale|jednak|chyba\s+że|pod\s+warunkiem|o\s+ile|tylko\s+(?:jeśli|jeżeli|gdy|pod))\b"
NEGATE = (
    r"^(?:nie(?!\s+ma\s+(?:problemu|sprawy|za\s+co))|stop)\b", r"\bnie\s+chcę\b", r"\bnie\s+zgadzam\b", r"\banuluj\b", r"\bzrezygnuj\b", r"\bnie\s+teraz\b", r"\bpoczekaj\b", r"\bnie\s+rób\b", r"\bnie\s+zlecaj\b", r"\bodwołaj\b",
    r"\bwstrzymaj\b", r"\bodmawiam\b", r"\brozmyśli\w*\s+się\b", r"\bprzerwij\b",
)
POSSESSIVE = ("mojego", "mojej", "moja", "moje", "moim", "moimi", "mojemu", "moj", "swoje", "swoja", "swojego")
# in Polish `mi` ("przysługuje mi") and `ma` ("sofa ma gwarancję") are NOT possessives, unlike in Spanish / Italian / French - used instead of the shared pattern for Polish text
POSSESSIVE_RX = r"\b(?:my|moj\w*|moi|moim\w*|moich|swoj\w*|swoi|swoim\w*|nasz\w*)\b"
# a first-person request (or "I am waiting") keeps its action intent even when it quotes the rules ("Chcę zwrot zgodnie z regulaminem"); asking FOR information about the rules does not ("Chciałbym zapytać o zasady zwrotów")
REQUEST_RX = (
    r"\b(?:chc(?:ę|emy)|chciał(?:bym|abym|byśmy|em|am)|chcieli(?:byśmy|śmy)|proszę\s+o|prosimy\s+o|żądam|żądamy|wnoszę|składam|zgłaszam|zwracam(?!\s+uwag)|zwracamy(?!\s+uwag)|odsyłam|odsyłamy|odstępuję|odstępujemy|rezygnuję|reklamuję|anuluję|oddaję"
    r"|czekam|czekamy|czekał(?:em|am)|czekaliśmy|(?:mam|muszę|będę|musimy|będziemy)\s+(?:jeszcze\s+)?czekać)\b"
)
INFO_LEAD_RX = (
    r"\b(?:chc\w*|chciał\w*|prosz\w*|potrzebuj\w*|zależy\s+mi|interesuje\s+mnie|mogł(?:bym|abym))\s+(?:się\s+)?(?:o\s+)?"
    r"(?:wiedzieć|zapytać|dowiedzieć|upewnić|sprawdzić|poznać|informacj\w*|wyjaśni\w*|przesłani\w*|przesłać|zasad\w*|warunk\w*|regulamin\w*|polityk\w*|procedur\w*)"
)

# Merged INTO the English / German / ... patterns (never replacing them). Whole-word forms only: `\bsof\w*` would hit `soft` / `sofort`, `\bstole\b` the English `stole`.
PRODUCTS: dict[str, str] = {
    "sofa": r"\bsof(?:a|y|ie|e|ach|ami|om)?\b|\bkanap(?:a|y|ie|e|o|ach|ami|om)?\b|wersalk\w*|narożnik\w*",
    "mattress": r"materac\w*",
    "washing machine": r"pralk\w*",
    "dishwasher": r"zmywark\w*",
    "fridge": r"lodówk\w*|chłodziark\w*",
    "table": r"\bstół\b|\bstoł(?:u|owi|em|y|ów|om|ami|ach)\b|\bstolik\w*|\b(?:na|przy|pod|ze|do|nad)\s+stole\b",
    "chair": r"krzesł\w*|krzesel",
    "wardrobe": r"\bszaf\w*",
    "bed": r"łóżk\w*|\błóżko\b|łóżek\b",
    "lamp": r"\blamp(?:a|y|ie|ę|ą|o|ach|ami|om|k\w*)?\b",
    "desk": r"biurk\w*",
    "blender": r"blender\w*|mikser\w*",
    "oven": r"piekarnik\w*",
    "armchair": r"fotel\w*",
}
CARRIERS: dict[str, str] = {"inpost": "InPost", "dpd": "DPD Polska", "dhl": "DHL", "poczta polska": "Poczta Polska", "gls": "GLS", "orlen paczka": "Orlen Paczka"}
