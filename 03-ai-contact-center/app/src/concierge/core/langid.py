"""Offline language identification (stop-word voting + Unicode script detection). Azure AI Language is used when available."""

from __future__ import annotations

import re

from .textutil import fold

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_NON_PL_LETTERS = re.compile(r"[šžčđřěůťďňľĺŕôäöüßåøæãõñ]")  # letters that Czech / Slovak / Slovenian / Croatian / Nordic / German / Spanish / Portuguese text has and Polish text never has
_PL_ONLY = "ąćęłńśźż"

STOPWORDS: dict[str, str] = {
    "en": "the and is are was were my your you i it this that with for have has not can please order delivered arrived damaged would like want need hello thanks thank how long do does did to a an of in on at be been will what when where why who which if or but about from by as any all some more many much get got give take make return refund item items product products money back policy days day week time old new first last just also then there their they them we our us me he she his her its should could may might must each every other such only same than too very so yes okay ok once again still already",
    "de": "der die das und ist sind war ich mein meine ihr nicht mit für auf ein eine einen bitte hallo danke bestellung beschädigt angekommen möchte habe haben kann sie wir zu von im zurück",
    "fr": "le la les et est sont je mon ma mes vous pas avec pour une un des bonjour merci commande endommagé reçu veux voudrais avoir besoin ce cette dans sur",
    "es": "el la los las y es son yo mi mis usted no con para una un hola gracias pedido dañado recibido quiero necesito tengo está en por que de favor entrega dirección cambiar nueva nuevo cuándo dónde reembolso devolver armario llegó sofá lavadora garantía",
    "it": "il lo la gli le e è sono io mio mia mie lei non con per una un ciao grazie ordine danneggiato ricevuto voglio ho bisogno questo questa nel sul di che vorrei restituire acquistato settimana scorsa armadio riceverò dov'è mio ancora",
    "nl": "de het een en is zijn ik mijn niet met voor hallo bedankt bestelling beschadigd ontvangen wil heb nodig deze dat van op naar jullie u",
    "pl": "i w nie na jest to się sie z do że ze mi mnie mam mamy macie jestem jesteśmy był była było byl bylo będzie bedzie czy jak kiedy gdzie dlaczego który ktory która ktora które ktore tak też tez jeszcze już juz bardzo dla od po przez oraz albo lub ale bo więc wiec tylko co ten ta te tym tego tej mój moj moja moje mojego mojej moim wasz wasza wasze państwa panstwa pan pani proszę prosze poproszę poprosze dzień dzien dobry dobra dziękuję dziekuje dzięki dzieki cześć czesc witam chcę chce chciałbym chcialbym chciałabym chcialabym potrzebuję potrzebuje mogę moge możecie mozecie zamówienie zamowienie zamówienia zamowienia zamówieniu zamowieniu uszkodzony uszkodzona uszkodzone uszkodzonej otrzymałem otrzymalem otrzymałam otrzymalam dotarł dotarla dotarła dotarlo dotarło przyszła przyszla przyszedł przyszedl kanapa kanapę kanape sofa sofę sofe dostawa dostawę dostawe dostawy przesyłka przesylka paczka paczkę paczke kurier gwarancja gwarancji reklamacja reklamację reklamacje faktura faktury adres adresu numer zwrot zwrotu zwrócić zwrocic pieniędzy pieniedzy pieniądze pieniadze wymiana wymienić wymienic termin terminu sprawa sprawę sprawe pomocy pomóc pomoc konsultant konsultanta konsultantem rozmowa rozmowy rozmowę gdy gdyby żeby zeby aby nic nikt coś cos kto komu wszystko wszystkiego nawet właśnie wlasnie przepraszam niestety dlaczego czemu teraz dzisiaj jutro wczoraj tydzień tydzien tygodniu dni dnia zł zl złotych zlotych",
    "sk": "a je som si sme ste sú su v na to že sa nie ale pre s z od do po ako čo co kto kde kedy prečo prečo môj moj moja moje mám mam chcem potrebujem ďakujem dakujem prosím prosim dobrý dobry deň den objednávka objednavka poškodená poskodena poškodený poskodeny doručená dorucena balík balik zásielka zasielka vrátenie vratenie peniaze reklamácia reklamacia záruka zaruka faktúra faktura adresa",
    "ru": "privet zdravstvuyte zdravstvujte spasibo pozhaluysta pozhaluista moy moya moi zakaz ne prishel prishla prishlo rabotaet khochu hochu vernut dengi dostavka tovar kogda gde mne nuzhno khorosho",
    "sv": "och är jag min mitt inte med för en ett hej tack beställning skadad mottagit vill behöver den det på av som till",
    "pt": "o a os as e é são eu meu minha não com para um uma olá obrigado pedido danificado recebido quero preciso tenho está em por que de da do dos das no na nos nas ao pelo pela já também muito foi estou há sem sobre quando vou receber reembolso encomenda cancelada máquina lavar deixou funcionar ainda tem garantia fui cobrado duas vezes mesmo pagamento fatura errada onde rastreio mostra nada devolver armário comprei semana passada podem reagendar entrega sexta-feira alterar morada nova favor sofá chegou número você vocês",
    "da": "og er jeg min mit ikke med for en et hej tak ordre beskadiget modtaget vil have brug for den det på af som til",
    "cs": "a je jsem jsme jste jsou můj moje ne s pro jeden dobrý den děkuji objednávka poškozené jsem chci potřebuji to na že se ale není mám chceme prosím prosim moje poškozená poškozený doručena balík zásilka vrácení peníze reklamace záruka faktura adresa kdy kde proč kdo jak už jen také když protože",
    "ro": "și este sunt eu meu mea nu cu pentru un o bună mulțumesc comanda deteriorat primit vreau am nevoie acest în pe că de",
    "tr": "ve bir bu ben benim değil ile için merhaba teşekkürler sipariş hasarlı geldi istiyorum ihtiyacım var çok ama",
    "fi": "ja on olen minun ei kanssa varten yksi hei kiitos tilaus vaurioitunut saapui haluan tarvitsen tämä että",
}
STRONG: dict[str, str] = {
    "pl": "dziękuję dziekuje proszę prosze poproszę poprosze dzień dzien dobry cześć czesc witam chcę chce chciałbym chcialbym chciałabym chcialabym zamówienie zamowienie zamówienia zamowienia uszkodzona uszkodzony uszkodzone dotarła dotarla dotarł dotarlo kanapa kanapę kanape przesyłka przesylka paczka paczkę paczke zwrot zwrotu zwrócić zwrocic pieniędzy pieniedzy gwarancja gwarancji reklamacja reklamację reklamacje mój moj moja moje mojego mojej konsultant konsultanta niestety przepraszam gdzie kiedy dzięki dzieki państwa panstwa",
    "cs": "děkuji prosím objednávka poškozená poškozený zásilka reklamace záruka",
    "sk": "ďakujem prosím objednávka poškodená poškodený zásielka reklamácia záruka",
}
_VOCAB = {lang: set(words.split()) for lang, words in STOPWORDS.items()}
_STRONG = {lang: set(words.split()) for lang, words in STRONG.items()}
for _lang in ("cs", "sk"):  # Czech / Slovak typed without diacritics ("dobry den, nedorazila mi zasilka") must not fall through to Polish
    _VOCAB[_lang] |= {fold(w) for w in _VOCAB[_lang]}
    _STRONG[_lang] |= {fold(w) for w in _STRONG[_lang]}
_SHARED: dict[str, int] = {}
for _vocab in _VOCAB.values():
    for _w in _vocab:
        _SHARED[_w] = _SHARED.get(_w, 0) + 1  # a word that several languages share ("do", "to", "i", "a") is weak evidence for each of them

_SCRIPTS = [
    ("ru", re.compile(r"[\u0400-\u04FF]")),
    ("el", re.compile(r"[\u0370-\u03FF]")),
    ("ar", re.compile(r"[\u0600-\u06FF]")),
    ("he", re.compile(r"[\u0590-\u05FF]")),
    ("hi", re.compile(r"[\u0900-\u097F]")),
    ("th", re.compile(r"[\u0E00-\u0E7F]")),
    ("ja", re.compile(r"[\u3040-\u30FF]")),
    ("ko", re.compile(r"[\uAC00-\uD7AF]")),
    ("zh", re.compile(r"[\u4E00-\u9FFF]")),
]
_UKRAINIAN = re.compile(r"[іїєґІЇЄҐ]")
_RUSSIAN_ONLY = re.compile(r"[ыэъёЫЭЪЁ]")


def _polish_letters(text: str) -> set[str]:
    """The Polish-only letters of the text, ignoring names in the middle of a sentence ("Please ship to ul. Długa 5, Gdańsk" is English)."""
    found: set[str] = set()
    for m in _WORD.finditer(text):
        w = m.group()
        before = text[: m.start()].rstrip()
        abbreviation = before.endswith(".") and bool(re.search(r"(?<![^\W\d_])[a-ząćęłńóśźż]{1,3}\.$", before))  # "ul.", "al.", "nr.", "tel." do not end a sentence
        if len(w) > 1 and w[0].isupper() and w[1:].islower() and before and (abbreviation or before[-1] not in ".!?:;\n\"'("):
            continue
        found.update(c for c in w.lower() if c in _PL_ONLY)
    return found


def detect_language(text: str, default: str = "en") -> tuple[str, float]:
    """Return (iso-639-1 code, confidence 0..1)."""
    if not text or not text.strip():
        return default, 0.0
    for lang, rx in _SCRIPTS:
        hits = len(rx.findall(text))
        if hits >= max(2, len(text) // 8):
            if lang == "ru" and _UKRAINIAN.search(text) and not _RUSSIAN_ONLY.search(text):
                return "uk", 0.9
            return lang, 0.9
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return default, 0.0
    scores: dict[str, float] = {}
    for lang, vocab in _VOCAB.items():
        strong = _STRONG.get(lang, ())
        hit = sum((2.0 if w in strong else 1.0) / _SHARED[w] for w in words if w in vocab)
        # accented characters characteristic of a language add weight
        scores[lang] = float(hit)
    if re.search(r"[äöüß]", text.lower()):
        scores["de"] += 1.5
    if re.search(r"[ãõ]", text.lower()):
        scores["pt"] += 2
    if re.search(r"[ñ¿¡]", text.lower()):
        scores["es"] += 2
    if re.search(r"[çœêèàù]", text.lower()):
        scores["fr"] += 1
    low = text.lower()
    pl_letters = _polish_letters(text)  # ł/ą/ę/ń/ś/ź/ż are Polish-only in this set of languages (Czech/Slovak use ě š č ř ž ů ť ď ň); `ć` is shared with Croatian / Serbian
    if pl_letters - {"ć"} or (pl_letters and not _NON_PL_LETTERS.search(low)):
        scores["pl"] += 1.5 + 0.5 * min(len(pl_letters) - 1, 3)
    elif _NON_PL_LETTERS.search(low):
        scores["pl"] = 0.0  # `moja pošiljka`, `oštećena`, `narudžba`: Slovenian / Croatian share words with Polish ("moja", "dobar dan") but never its letters
    if re.search(r"[ěřůťďň]", low):
        scores["cs"] += 2
    if re.search(r"[äôľĺŕ]", low) and not re.search(r"[ěřů]", low):
        scores["sk"] += 1.5
    if re.search(r"[åäö]", text.lower()) and not re.search(r"ß", text.lower()):
        scores["sv"] += 0.5
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] <= 0:
        return default, 0.0
    margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0)
    conf = min(0.99, 0.35 + 0.15 * ranked[0] + 0.1 * margin)
    if ranked[0] < 1.0 or (len(words) <= 2 and ranked[0] < 2):
        return default, round(conf * 0.4, 2)
    return best, round(conf, 2)
