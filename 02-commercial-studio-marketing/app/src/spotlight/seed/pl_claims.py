"""Polish claims & compliance pack (rows ``clm-pl-*``): inflection-aware, diacritic-insensitive patterns.

Every pattern is a regex over *folded* text (``fold()``: ą→a, ć→c, ę→e, ł→l, ń→n, ó→o, ś→s, ź/ż→z), so the same rule fires on
"leczy poranny niepokój" and on "leczy poranny niepokoj" typed on a phone. Stems + ending classes cover Polish inflection
(leczy / leczyć / wyleczy / leczniczy · niepokój / niepokoju / niepokojem · cudowny / cudowna / cudowne · tani / tania / tanio).
Word boundaries keep words that merely contain a forbidden stem out (``stanie`` ⊅ ``tanie``, ``uzdrowisko`` ⊅ ``uzdrowić``,
``leczo`` ⊅ ``leczy``, ``łagodny`` ⊅ ``łagodzi``). Negation ("nie leczy") and the idiom "na zdrowie" are not claims.

Each row mirrors an English rule (``concept``), so for Polish text the Polish rule *replaces* its English twin. Content is demo
material — not legal advice.
"""

from __future__ import annotations

from typing import Any

BRAND_ID = "northwind"

DISCLAIMER_CAFFEINE_PL = "Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży."
DISCLAIMER_FINANCE_PL = "Inwestowanie wiąże się z ryzykiem utraty kapitału. Wyniki z przeszłości nie przesądzają o wynikach w przyszłości."
DISCLAIMER_PHARMA_PL = "Przed użyciem zapoznaj się z ulotką albo skonsultuj się z lekarzem lub farmaceutą."
DISCLAIMER_ALCOHOL_PL = "Pij odpowiedzialnie."

# ----------------------------------------------------------------------------------------------- regex building blocks (folded text)
_W = r"[^\W\d_]"
# Up to three more words of the same clause after the core of a claim (the complement: "chorobom serca", "ciśnienie krwi", "infekcjami sezonowymi"), so the whole predicate is
# quoted — and, when replaced, nothing is left dangling. Stops at punctuation and at words that start a new clause or an adverbial ("i", "na", "każdego", "codziennie" …).
_TAIL = (
    r"(?:\s+(?!(?:a|ale|bo|oraz|i|lub|albo|ktor\w+|gdy|kiedy|zeby|aby|jest|sa|na|w|z|ze|do|po|przed|przy|przez|dla|dzieki|od|nad|pod|bez|kazd\w+|codzienn\w+|caly|cala|cale|"
    r"rano|wieczor\w*|zawsze|juz|jeszcze|tez|takze|rowniez|wiecej|bardziej|naprawde|szybciej|szybko)\b)[^\s.,;:!?…()\u2014\u2013\"'\u201c\u201d\u201e\u00ab\u00bb]+){0,3}"
)
_GAP = r"[^.,;:!?…()\u2014\u2013\n\"\u201c\u201d\u201e\u00ab\u00bb]"  # inside one clause
# a word that does not start another predicate ("… i smakuje świetnie", "… i poprawia humor")
_ITEM = (
    r"(?!(?:\w*(?:uje|aje|eje|emy|amy|imy|ymy|esz|asz|isz|ysz|aja|eja|uja)|jest|sa|ma|maja|pachnie|smakuje|dziala|daje|wspiera|poprawia|pomaga|chroni|dba|sprzyja|ulatwia|wzmacnia"
    r"|polepsza|zwieksza|podnosi|obniza|lagodzi|leczy|koi|usuwa|pobudza|przyspiesza|sprawia|pozwala)\b)[^\s.,;:!?…()\u2014\u2013\"'\u201c\u201d\u201e\u00ab\u00bb]+"
)
# objects coordinated with the one just matched ("poprawia pamięć i koncentrację", "chroni serce i naczynia", "zmniejsza zmęczenie, senność i rozdrażnienie"): taken along,
# so that replacing the claim leaves nothing dangling
_COORD = rf"(?:(?:\s*,\s+{_ITEM}){{1,3}}\s+(?:i|oraz|lub|ani)\s+{_ITEM}|(?:\s+(?:i|oraz|lub|ani)\s+{_ITEM}){{1,2}})"
# what follows the core of a claim: its complement, then the coordinated objects with theirs ("ból głowy i napięcie mięśni")
_OBJECTS = rf"{_TAIL}(?:{_COORD}{_TAIL})?"
CURE_VERBS = (
    r"(?:(?:z|u|po)?lagodz\w*|lagodz[ae]c\w*|koi\b|koic\b|ukoi\w*|kojac\w*|kojeni\w*|uspokaja\w*|uspokoi\w*|usmierza\w*|zwalcza\w*|walcz(?:y|a|yc)\s+z|walce\s+z|przeciwdziala\w*"
    r"|zapobie(?:g\w*|c)|chron(?:i|ia|ic)\s+(?:\w+\s+){0,2}przed|ochron\w*\s+przed|niweluj\w+|likwiduj\w+|eliminuj\w+|redukuj\w+|zmniejsz\w+|obniz(?:a|aj|aja|ac|y|ysz|ymy|yc)|reguluj\w+|normalizuj\w+"
    r"|wspomag\w+\s+lecz\w+|ulg\w+\s+(?:w|od|na)|przynosi\w*\s+ulg\w*|daje\s+ulg\w*|zapomn\w+\s+o"
    r"|pomag\w+\s+(?:\w+\s+){0,2}(?:w\s+walce\s+z|zapomniec\s+o|uporac\s+sie\s+z|poradzic\s+sobie\s+z|radzic\s+sobie\s+z|pozbyc\s+sie|walczyc\s+z|odzyskac)|pomag\w+\s+(?:na|przy))"
)
CONDITIONS = (
    r"(?:niepokoj\w*|lek(?:u|iem|i|ow|owi|ach)?|stres\w*|napiec\w*|nerw\w*|depresj\w*|bezsenn\w+|zmeczen\w*|bol(?:u|em|e|ow|ach|i)?|migren\w*|kac(?:a|u|em|owi)?|przeziebien\w*|gryp\w*|infekcj\w*"
    r"|alergi\w*|dolegliw\w*|schorzen\w*|objaw\w*|chorob\w*|rak(?:a|u|iem|owi)?|nowotwor\w*|cukrzyc\w*|cisnien\w*|cholesterol\w*|poziom\w*\s+(?:cukru|glukozy|insulin\w*)|zaburzen\w*|nerwic\w*"
    r"|zakwas\w*|zapaleni\w*|stan(?:y|ow)?\s+zapaln\w*|refluks\w*|zgag\w*|wzdec\w*|nudnosc\w*|mdlosc\w*|kaszel|kaszlu|katar\w*|alzheimer\w*|demencj\w*|zawal\w*|udar\w*|miazdzyc\w*"
    r"|oslabien\w*|wyczerpani\w*|przemeczen\w*|ryzyk\w+\s+(?:\w+\s+){0,1}(?:chor|cukrzyc|zawal|nowotwor|udar|rak)\w*)"
)
# the conditions you can name after "na": "kawa na ból głowy", "najlepsza na kaca", "lek na stres"
_NA_CONDITION = r"(?:bol\w*|migren\w*|kac(?:a|u)?|przeziebien\w*|gryp\w*|bezsenn\w+|depresj\w*|nerw\w*|stres\w*|zmeczen\w*|niepokoj\w*|cisnien\w*|cholesterol\w*|cukrzyc\w*|alergi\w*|infekcj\w*|kaszel|katar\w*|wzdec\w*|zgag\w*)"
_THERAPY = (
    r"(?:(?:wy|u|za|po)?lecz(?:y|ysz|ymy|ycie|yc|yl\w*|a|e|enie|enia|eniu|eniem|ony|ona|one|onych)|lecz[ae]c\w*|lecznicz\w+|uzdrawia\w*|uzdrowi(?:c|l\w*)?|uzdrowieni\w*|lekarstw\w+|terapeutyczn\w+)"
)
_CURE_PARTS = [
    # verb + illness / symptom ("koi nerwy i napięcie", "chroni przed infekcjami sezonowymi", "obniża ciśnienie krwi", "zmniejsza ryzyko cukrzycy typu 2")
    rf"\b{CURE_VERBS}\b{_GAP}{{0,40}}?\b{CONDITIONS}\b{_OBJECTS}",
    # a cure by its name: leczy / wyleczy / lecząca / lecznicze / uzdrawia / lekarstwo / terapeutyczny — whatever the condition
    rf"\b{_THERAPY}\b{_TAIL}",
    # "remedy for": "kawa na ból głowy", "najlepsza na kaca", "lek na stres", "skuteczna na migrenę"
    rf"\b(?:kaw\w*|lek|lekarstw\w+|herbat\w*|napar\w*|napoj\w*|srodek|remedium|sposob|idealn\w+|najlepsz\w+|skuteczn\w+|dobr\w+|doskonal\w+|swietn\w+|polecan\w+)\s+na\s+{_NA_CONDITION}\b",
    r"\bprzeciw(?:ko)?\s+(?:\w+\s+)?(?:bol|migren|przeziebien|gryp|bezsenn|depresj|stres|nerw|zmeczen|alergi|infekcj)\w*",
    r"\bprzeciw(?:zapaln|bol|wirus|bakter|grzyb|nowotwor|cukrzyc|depres|utlen|alergi|zakrz|nadcisn)\w*",
]
CURE = "re:" + "|".join(_CURE_PARTS)
# contexts in which a match is not a claim: the proverb "czas leczy rany", machine pressure in a coffee-machine line
CURE_EXCLUDE = [
    r"czas\s+lecz\w+\s+rany",
    r"(?:\w+\s+){0,3}cisnien\w*\s+(?:wody|pary|parzenia|w\s+ekspresie|w\s+kolbie)",
    r"ekspres\w*\s+(?:\w+\s+){0,3}(?:reguluj|obniz|zmniejsz|utrzymuj|stabilizuj)\w*\s+cisnien\w*",
]

WEIGHT = [
    r"re:\bodchudz(?!on)\w*",  # odchudza / odchudzanie / odchudzająca — not the participle in "odchudzony wzór opakowania"
    r"re:\b(?:s)?chudn\w*",
    r"re:\bspal(?:a|aj|ac|anie|acz\w*|ajac\w*)\s+(?:\w+\s+){0,1}(?:tluszcz\w*|kalori\w*|kilogram\w*|zbedn\w*|nadmiar\w*|oponk\w*|boczk\w*)",
    r"re:\bspalacz\w*",
    r"re:\butra(?:t|c)\w*\s+(?:\w+\s+){0,1}(?:wag\w+|kilogram\w*)",
    r"re:\bzrzuc\w*\s+(?:\w+\s+){0,1}(?:kilogram\w*|kilo\b|zbedn\w*|wag\w+)",
    r"re:\bwyszczupl\w*",
    r"re:\bredukcj\w+\s+(?:wag\w+|tkank\w+|tluszcz\w*)",
    r"re:\b(?:diet\w*|diecie)\s+(?:odchudzaj|redukcyjn)\w*|\bredukcyjn\w+\s+(?:diet\w*|diecie)",
    r"re:\b(?:przyspiesz|pobudz|stymul|podkrec|usprawni|zwieksz|popraw)\w*\s+(?:\w+\s+){0,2}(?:metabolizm\w*|przemian\w*\s+materii|spalani\w*)",
    r"re:\bdetoks\w*|\bdetox\w*",
    r"re:\bodtru\w+",
    r"re:\b(?:oczyszcz|usuw|wydal)\w*\s+(?:\w+\s+){0,2}(?:toksyn\w*|organizm\w*|krew\w*|krwi|watrob\w*|nerk\w*)",
]
CLINICAL = [
    r"re:\bklinicznie\s+(?:udowodnion\w*|potwierdzon\w*|przebadan\w*|przetestowan\w*|sprawdzon\w*|dowiedzion\w*)(?:\s+(?:dzialani\w*|skutecznosc\w*|korzysc\w*))?",
    r"re:\bnaukowo\s+(?:udowodnion\w*|potwierdzon\w*|dowiedzion\w*|przebadan\w*|zweryfikowan\w*)(?:\s+(?:dzialani\w*|skutecznosc\w*|korzysc\w*))?",
    r"re:\b(?:testowan|przebadan|sprawdzon|zweryfikowan)\w*\s+(?:klinicznie|naukowo|dermatologicznie)\b",
    r"re:\bpotwierdzon\w*\s+(?:\w+\s+){0,2}(?:badani\w*|klinicz\w*|naukow\w*)(?:\s+(?:naukow|klinicz)\w+)?",
    r"re:\bbadani\w+\s+(?:\w+\s+){0,2}(?:wykaz\w*|potwierdz\w*|dowodz\w*|udowodni\w*|pokaz\w*)(?:\s*,\s*(?:ze|iz)\s+[^.!?]+)?",
    r"re:\bzgodnie\s+z\s+(?:\w+\s+){0,2}badani\w*",
    r"re:\b(?:rekomendowan|polecan|zalecan|sprawdzon|zatwierdzon|testowan|akceptowan|uznan|wybran)\w*\s+przez\s+(?:\w+\s+){0,2}(?:lekarz|dietetyk|ekspert|specjalist|farmaceut|naukowc|dermatolog|kardiolog)\w*",
    r"re:\b(?:lekarz|dietetyk|ekspert|specjalist|farmaceut|naukowc)\w*\s+(?:polecaj|zalecaj|rekomenduj|poleca\b|zaleca\b)\w*",
    r"re:\budowodnion\w*\s+(?:dzialani\w*|skutecznosc\w*|korzysc\w*)",
    r"re:\bwybor\s+(?:ekspertow|lekarzy|dietetykow|specjalistow)\b",
    r"re:\batest\w*\s+(?:pzh|gis)\b|\b(?:przebadan|przetestowan|sprawdzon)\w+\s+(?:w\s+)?(?:niezaleznym\s+)?laboratori\w+",  # "Atest PZH", "przebadana w niezależnym laboratorium": a document has to stand behind it
]
ENERGY = [
    r"re:\b(?:energi(?!czn)\w*|energet(?!yk)\w+|pobudz\w*|rozbudz\w*|doladuj\w*|doladowa\w*|boost\w*)\b",
    r"re:\b(?:stawi\w*|postawi\w*)\s+(?:cie\s+|ci\s+)?na\s+nogi\b",
    r"re:\bdodaj\w*\s+(?:ci\s+)?(?:energii|sil|wigoru|werwy|mocy)\b",
    r"re:\b(?:o|z)?budz(?:i|a)\w*\s+(?:cie|ci)\b",
    r"re:\b(?:popraw|zwieksz|wspom|wspier|podnos|wzmacni)\w*\s+(?:\w+\s+){0,2}(?:koncentracj\w*|czujnosc\w*|skupieni\w*|wydolnosc\w*)",
    r"re:\blepsz\w+\s+(?:koncentracj|skupieni|czujnosc)\w*",
    r"re:\b(?:kaw\w*|napoj\w*|idealn\w+|dobr\w+)\s+(?:\w+\s+){0,1}na\s+(?:koncentracj|czujnosc|skupieni)\w*",
    r"re:\bpomag\w+\s+(?:\w+\s+){0,2}(?:skupic|skoncentrowac)\b",
    r"re:\bdaj\w*\s+kopa\b|\bkop\w*\s+(?:energi\w*|kofein\w*)|\bkofeinow\w+\s+kop\w*",
]
# energy that is not a caffeine claim: "energia słoneczna", "zużywamy mniej energii", "palarnia zasilana energią z …"
ENERGY_EXCLUDE = [
    r"energi\w*\s+(?:sloneczn|odnawialn|elektryczn|wiatr|jadrow|cieplna|cieplnej|geotermaln|wodn)\w*",
    r"(?:sloneczn|odnawialn|elektryczn|wiatrow|jadrow|zielon)\w*\s+energi\w*",
    r"(?:zuzyci|zuzywa|zuzyw|oszczed|odzysk|zasilan|zasila|produkcj)\w*\s+(?:\w+\s+){0,2}energi\w*",
]
ARABICA = [r"re:\b100\s*%\s*arabik\w*", r"re:\b100\s*%\s*arabica\b", r"re:\bsto\s+procent\s+arabik\w*"]
SMALL_BATCH = [r"re:\bpal(?:ona|one|ony|onej|onych)\s+w\s+malych\s+partiach\b", r"re:\bmal(?:e|ych)\s+partie\b|\bmalych\s+partii\b|\bmalych\s+partiach\b", r"re:\bmala\s+palarni\w*"]
FAIRTRADE = [
    r"re:\bfair\s?trade\b",
    r"re:\bcertyfikowan\w*\s+fair\s?trade\b",
    r"re:\betyczn\w*\s+(?:pozyskiwan\w*|zrodl\w*|pochodz\w*)",
    r"re:\bpozyskiwan\w*\s+etycznie\b",
    r"re:\bsprawiedliw\w+\s+handel\w*",
]
GREEN = [
    r"re:\bneutraln\w*\s+(?:weglow\w*|klimatyczn\w*|dla\s+klimatu)",
    r"re:\bklimatycznie\s+neutraln\w*",
    r"re:\bneutralnosc\w*\s+(?:weglow\w*|klimatyczn\w*)",
    r"re:\bco2[\s-]*neutraln\w*",
    r"re:\bbez\s+sladu\s+weglow\w*",
    r"re:\bzero\s+emisji\b",
    r"re:\b100\s*%\s*zrownowazon\w*",
    r"re:\bprzyjazn\w*\s+(?:dla\s+)?(?:srodowisk\w*|klimat\w*|planet\w*)",
    r"re:\b(?:pozytywn\w*|dobr\w*)\s+dla\s+planet\w*",
    r"re:\bratuj\w+\s+planet\w*",
    r"re:\bcarbon[\s-]?neutral",
    r"re:\beko-?przyjazn\w*",
    r"re:\bzrownowazon\w+\s+(?:uprawa|upraw\w*|produkcj\w*|rolnictw\w*|pozyskiwan\w*|lancuch\w*)",  # generic "sustainable"; a "zrównoważony smak" (balanced taste) is not
]
BEST = [
    r"re:\bnajlepsz\w*\s+(?:\w+\s+){0,3}na\s+swiecie",
    r"re:\bnajlepsz\w*\s+(?:kaw\w*|ziarn\w*|espresso|palarni\w*|produkt\w*|wybor\w*|smak\w*|aromat\w*|jakosc\w*|cen\w*|oferta\w*|blend\w*|mieszank\w*)(?:\s+(?:swiata|w\s+polsce|w\s+miescie|pod\s+sloncem|na\s+rynku))?",
    r"re:\bnajlepsz\w*(?:\s+\w+){0,2}\s+(?:w\s+polsce|w\s+europie|w\s+miescie|w\s+kraju|w\s+regionie|w\s+okolicy|na\s+rynku|w\s+swojej\s+klasie|w\s+historii)\b",
    r"re:\bnaj(?:smaczniejsz|swiezsz|mocniejsz|zdrowsz|aromatyczniejsz|przyjemniejsz|ladniejsz)\w*\s+(?:\w+\s+){0,1}(?:kaw\w*|ziarn\w*|palarni\w*)",
    r"re:\bpierwsz\w+\s+(?:kaw\w*|palarni\w*|produkt\w*|ziarn\w*|marka|marki)\s+(?:\w+\s+){0,3}(?:w\s+polsce|na\s+swiecie|w\s+europie|na\s+rynku)\b|\bpierwsz\w+\s+w\s+(?:polsce|europie|swiecie)\b",
    r"re:\bnajbardziej\s+\w+\s+(?:\w+\s+){0,1}(?:kaw\w*|ziarn\w*|palarni\w*)",
    r"re:\bnajczesciej\s+(?:wybierana|kupowana|polecana)\w*(?:\s+\w+){0,2}",
    r"re:\bkaw\w*\s+(?:numer|nr)\s*(?:jeden|1)\b",
    r"re:\b(?:numer|nr)\s*(?:jeden|1)\b",
    r"re:(?<!powod )(?<!krok )(?<!punkt )(?<!zasada )(?<!miejsce )(?<!odcinek )(?<!sezon )#\s*1\b(?!\s*:)",
    r"re:\bnaj(?:wieksz|nizsz)\w*\s+(?:\w+\s+){0,1}(?:palarni|wybor|siec|producent|dystrybutor|cen|kawiarni|kaw|oferta)\w*",
    r"re:\b(?:bije|pokonuje|wyprzedza|rozbija)\s+(?:\w+\s+){0,1}(?:konkurencj\w*|rywali\w*)",
    r"re:\blider\w*\s+(?:\w+\s+){0,3}(?:w\s+polsce|rynku|wsrod|kategorii|branzy)",
    r"re:\bjedyn\w+\s+(?:taka|taki|takie|takiej|takiego|w\s+swoim\s+rodzaju|w\s+polsce|na\s+swiecie|w\s+swojej\s+klasie)(?:\s+kaw\w*)?",
    r"re:\bnie\s+ma\s+lepsz\w+(?:\s+kaw\w*)?",
    # comparative advertising: against "the competition", "all the others" or a named competitor
    r"re:\b(?:lepsz|smaczniejsz|zdrowsz|swiezsz|mocniejsz|aromatyczniejsz)\w*\s+(?:niz|od|ni)\s+(?:\w+\s+){0,2}(?:konkurencj|inn|wszystk|reszt|starbucks|costa(?!\s+rica)|nescafe|nespresso|jacobs|tchibo|lavazza|illy|segafredo|mccafe|dallmayr|douwe|kimbo|julius|dolce)\w*",
    r"re:\bidealn\w+\s+(?:\w+\s+){0,2}dla\s+(?:kazdego|wszystkich|kazdej|kazdych)\b",
    r"re:\b(?:bezpieczn|odpowiedn)\w+\s+dla\s+(?:kazdego|wszystkich)\b",
    r"re:\bkaw\w*\s+roku\b|\bwielokrotnie\s+nagradzan\w+|\bnagrodzon\w+\s+(?:\w+\s+){0,2}(?:kaw|palarni|produkt)\w*",
    r"re:\b(?:w\s+)?100\s*%\s*naturaln\w*",
    r"re:\bbez\s+(?:cukru|konserwantow|barwnikow|sztucznych\s+\w+|dodatkow\s+\w+|gmo|glutenu|laktozy|kalorii)\b|\b(?:0\s*%|zero)\s*(?:cukru|kalorii|tluszczu)\b|\bniskokalor\w+",
    r"re:\bbezkonkurencyjn\w+",
    r"re:\bniezrownan\w+",
    r"re:\b(?:starbucks|nescafe|nespresso|jacobs|tchibo|lavazza|segafredo|mccafe|dallmayr|douwe\s+egberts|costa\s+coffee)\w*",  # a competitor named in the copy
]
ORGANIC = [
    r"re:\bekologiczn\w*", r"re:\borganiczn\w*", r"re:\bbio(?:-\w+)?\b", r"re:\beko-\w+|\beko\b", r"re:\bcertyfikat\w*\s+bio\b",
    r"re:\beurolisc\w*|\brainforest\s+alliance\b|\butz\b|\bdemeter\b",  # other organic / sustainability seals: each needs its certificate on file
]
ORGANIC_EXCLUDE = [r"\bw\s+(?:naszym\s+|moim\s+|tym\s+)?bio\b"]  # "link w bio": the social-media profile, not an organic claim
_BENEFIT_VERB = (
    r"(?:wzmacni\w*|wzmocn\w*|wspier\w*|wspom\w+|popraw\w*|polepsz\w*|zwieksz\w*|podnos\w*|podniesi\w*|buduj\w*|stymul\w*|usprawni\w*|regener\w*|odzywi\w*|odmlad\w*|pobudz\w*|przyspiesz\w*"
    r"|optymalizuj\w*|chron\w*|sprzyja\w*|ulatwia\w*|dba\w*\s+o|zadba\w*\s+o|dbaj\w*\s+o|pomag\w+\s+(?:w|na|przy))"
)
_BODY_FUNCTION = (
    r"(?:odpornosc\w*|uklad\w*\s+\w+|serc\w+|krazeni\w*|trawieni\w*|jelit\w*|metabolizm\w*|przemian\w*\s+materii|watrob\w*|nerk\w*|mozg\w*|pamie\w+|sen|snu|snie|zasypani\w*|nastroj\w*|samopoczuci\w*"
    r"|kosci(?:ach|om|ami)?|staw(?:y|ow|om|ach|ami)|organizm\w*|witalnosc\w*|kondycj\w*|regeneracj\w*|naczyn\w*|krew|krwi|skor(?:a|e|y|ze)|wlos(?:y|ow|om|ach|ami)|paznokci\w*)"
)
_HEALTH_ADJ = r"zdrow(?:y|a|e|ego|ej|emu|ym|ych|ymi|o|iu|iem)|zdrowsz\w*|zdrowotn\w*|prozdrowotn\w*"
# "zdrowie/zdrowia" as a claim noun ("dbaj o zdrowie!", "zdrowie serca …"); a bare toast "Zdrowie!" opening a sentence is not a claim
_HEALTH_NOUN = (
    r"(?:(?<![.!?] )(?<![\"\u201e\u201c\u00ab(])(?<!\u2014 )(?<!\u2013 )(?<!^)zdrowi[ea]"
    r"|(?:^|(?<=[.!?] )|(?<=[\"\u201e\u201c\u00ab(])|(?<=\u2014 )|(?<=\u2013 ))zdrowi[ea](?!\s*!))"  # sentence-initial (also after an opening quote or a dialogue dash): "„Zdrowie!” — mówi sąsiad"
)
EU_HEALTH = [
    rf"re:(?<!na )\b(?:{_HEALTH_ADJ}|{_HEALTH_NOUN})\b",
    r"re:\bsuper-?foods?\b|\bsuperfood\w*|\bsuperzywnosc\w*|\bsuperfruits?\b",  # "superfood": a health halo with no authorised claim behind it
    r"re:\bantyoksyd\w*|\bantyutleni\w+|\bprzeciwutleni\w+|\bantioxidant\w*",  # no generic "antioxidant" claim is authorised
    r"re:\bdla\s+(?:diabetyk\w+|cukrzyk\w+|hipertonik\w+|nadcisnieniow\w+|osob\s+(?:z|chorych\s+na)\s+(?:cukrzyc\w+|nadcisnieni\w+|alergi\w+))\b",  # a food "for diabetics" is a medical-purpose claim
    rf"re:\b{_BENEFIT_VERB}\b{_GAP}{{0,25}}?\b{_BODY_FUNCTION}\b{_OBJECTS}",
    r"re:\buklad\w*\s+(?:odpornosciow|nerwow|krazeni|pokarmow)\w*",
    r"re:\b(?:kaw\w*|herbat\w*|napar\w*|ziol\w*|napoj\w*|mieszank\w*|idealn\w+|najlepsz\w+|dobr\w+|skuteczn\w+)\s+(?:\w+\s+){0,1}na\s+(?:sen|snu|odpornosc\w*|trawieni\w*|krazeni\w*|pamiec\w*|serce|jelita)\b",
    r"re:\blepsz\w+\s+(?:pamiec|pamieci|samopoczuci|nastroj|sen|snu|trawieni|odpornosc)\w*",
    r"re:\bpomag\w+\s+(?:\w+\s+){0,1}(?:zasnac|trawic|strawic|zregenerowac\s+sie)\b" + _TAIL,
    r"re:\bdobr(?:a|y|e|ego|ej)\s+dla\s+(?:twojego\s+|twoich\s+)?(?:serca|jelit|mozgu|ukladu\w*)\b",
    r"re:\b(?:na\s+)?(?:lepszy|spokojny|gleboki|zdrowy|dobry)\s+sen\b",
]
# contexts in which "zdrowie" is not a health claim: wishes, toasts, idioms, names of companies and institutions
EU_HEALTH_EXCLUDE = [
    r"zycz\w+\s+(?:\w+\s+){0,2}zdrowi[ae]\b",  # "Życzymy Wam zdrowia" (the noun in a wish); "zdrowego dnia" stays a claim wording
    r"(?:duzo|wiele|mnostwo|samego|przede\s+wszystkim)\s+zdrowi[ae]\b",
    r"zdrowi[ae]\s*,\s*(?:szczescia|radosci|spokoju|pomyslnosci|milosci)",
    r"(?:szczescia|radosci|spokoju|pomyslnosci|milosci)\s*(?:,|i)\s*zdrowi[ae]\b",
    r"zdrowi[ae]\s+i\s+(?:szczescia|radosci|spokoju|pomyslnosci|milosci)",
    r"(?:za|do|na)\s+(?:\w+\s+){0,2}zdrowi[eau]\b",
    r"zdrow\w+\s+(?:i\s+)?(?:\w+\s+){0,2}(?:swiat\w*|swieta|nowego\s+roku|nowym\s+roku|urodzin\w*|imienin\w*)",
    r"zdrow\w+\s+(?:rozsad\w*|dystans\w*|apetyt\w*|sceptycyzm\w*|konkurencj\w*|rywalizacj\w*|egoizm\w*|duch\w*|humor\w*)",
    r"zdrow\w+\s+dawk\w+\s+(?:humor|ironii|dystansu|sceptycyzmu|rozsadku|szalenstwa)\w*",
    r"zdrowo\s+(?:zakrecon|szalon|stukni)\w*",
    r"(?:\w+\s+){1,4}(?:sp\.?\s*z\s*o\.?\s*o|s\.\s?a|sp\.\s?j|sp\.\s?k)\b",
    r"(?:osrod\w+|centrum|fundusz\w*|ministerstw\w*|organizacj\w*|instytut\w*|przychodni\w*|poradni\w*)\s+(?:\w+\s+){0,1}zdrowi\w*",
    r"buduj\w*\s+(?:\w+\s+){0,1}nastroj\w*",  # "muzyka buduje nastrój": atmosphere, not mood
]
FIN_PROHIBITED = [
    r"re:\bgwarantowan\w*\s+(?:zysk|zwrot|dochod|stop)\w*",
    r"re:\bgwarantuj\w*\s+(?:zysk|zwrot|dochod)\w*",
    r"re:\b(?:bez|zero)\s+ryzyka\b",
    r"re:\b(?:pewn|zapewnion|stal|niezawodn)\w*\s+(?:zysk|zwrot|dochod)\w*",
    r"re:\bnie\s+(?:mozesz|mozna)\s+(?:stracic|przegrac)\b",
    r"re:\brisk-?free\b",
]
FIN_RETURNS = [r"re:\b(?:zwrot\w*|zysk\w*|dochod\w*|rentownosc\w*)\b"]
PHARMA = [
    r"re:\bklinicznie\s+udowodnion\w*",
    r"re:\blagodz\w*",
    r"re:\bprzynosi\w*\s+ulg\w*",
    r"re:\bnatychmiastow\w*\s+ulg\w*",
    r"re:\bszybko\s+dziala\w*",
]
ALCOHOL = [
    rf"re:\bpoprawia\w*\s+(?:wyniki|sprawnosc|kondycj\w*){_TAIL}",
    rf"re:\bzwieksza\w*\s+(?:popularnosc|atrakcyjnosc)\w*{_TAIL}",
    rf"re:\brozkreca\w*\s+(?:\w+\s+){{0,2}}imprez\w*{_TAIL}",
    rf"re:\bdodaje\s+(?:odwagi|pewnosci(?:\s+siebie)?|animuszu)\b{_TAIL}",
    rf"re:\bsukces\w*\s+towarzyski\w*{_TAIL}|\btowarzyski\w*\s+sukces\w*{_TAIL}",
]

_HEALTH_FORMS = {
    "zdrowy": "niespieszny", "zdrowa": "niespieszna", "zdrową": "niespieszną", "zdrowe": "niespieszne", "zdrowego": "niespiesznego", "zdrowej": "niespiesznej",
    "zdrowemu": "niespiesznemu", "zdrowym": "niespiesznym", "zdrowych": "niespiesznych", "zdrowymi": "niespiesznymi", "zdrowo": "niespiesznie",
    "zdrowszy": "spokojniejszy", "zdrowsza": "spokojniejsza", "zdrowszą": "spokojniejszą", "zdrowsze": "spokojniejsze", "zdrowszego": "spokojniejszego", "zdrowszej": "spokojniejszej",
    "zdrowie": "spokój", "zdrowia": "spokoju", "zdrowiu": "spokojowi", "zdrowiem": "spokojem",
    "zdrowotny": "smakowy", "zdrowotna": "smakowa", "zdrowotne": "smakowe", "zdrowotnych": "smakowych", "zdrowotnym": "smakowym", "zdrowotnej": "smakowej", "zdrowotnego": "smakowego",
    "prozdrowotny": "smakowy", "prozdrowotna": "smakowa", "prozdrowotne": "smakowe", "prozdrowotnych": "smakowych",
}
_FIN_FORMS = {
    "bez ryzyka": "z ryzykiem utraty kapitału", "zero ryzyka": "z ryzykiem utraty kapitału",
    "gwarantowany zysk": "możliwy zysk", "gwarantowane zyski": "możliwe zyski", "gwarantowanego zysku": "możliwego zysku", "gwarantowanych zysków": "możliwych zysków",
    "gwarantowany zwrot": "możliwy zwrot", "gwarantowane zwroty": "możliwe zwroty", "gwarantowany dochód": "możliwy dochód",
    "pewny zysk": "możliwy zysk", "pewne zyski": "możliwe zyski", "pewnego zysku": "możliwego zysku",
    "nie możesz stracić": "możesz stracić", "nie można stracić": "można stracić", "nie możesz przegrać": "możesz przegrać", "nie można przegrać": "można przegrać",
}
_WEIGHT_FORMS = {"odchudza": "jest częścią zbilansowanego poranka", "odchudzają": "są częścią zbilansowanego poranka"}
_ORGANIC_FORMS = {"ekologiczny": "starannie wybierany", "ekologiczna": "starannie wybierana", "ekologiczne": "starannie wybierane", "ekologicznego": "starannie wybieranego", "ekologicznej": "starannie wybieranej", "ekologiczną": "starannie wybieraną"}


def _row(rule_id: str, concept: str, text: str, type_: str, patterns: list[str], *, markets: list[str] | None = None, categories: list[str] | None = None, pack: str | None = None,
         severity: str = "block", alternative: str | None = None, forms: dict[str, str] | None = None, disclaimer: str | None = None, url: str | None = None, notes: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": rule_id, "brand_id": BRAND_ID, "lang": "pl", "concept": concept, "text": text, "type": type_, "markets": markets or ["*"], "categories": categories or ["*"],
        "patterns": patterns, "severity": severity, "notes": notes,
    }
    if pack:
        row["rule_pack"] = pack
    if alternative:
        row["alternative"] = alternative
    if forms:
        row["alternative_forms"] = forms
    if disclaimer:
        row["required_disclaimer"] = disclaimer
    if url:
        row["substantiation_url"] = url
    return row


def _claims_pl_rows() -> list[dict[str, Any]]:
    """The Polish pack (15 rows mirroring the English library: food & beverage, EU health claims, finance, pharma, alcohol)."""
    fb = ["food", "beverage"]
    return [
        _row("clm-pl-cure", "clm-cure", "Claimy o leczeniu, łagodzeniu lub zapobieganiu chorobom i dolegliwościom", "prohibited", [CURE], categories=fb, pack="food_beverage",
             alternative="daje spokojniejszy początek poranka", notes="Żywności i napojom nie wolno przypisywać właściwości leczniczych ani zapobiegających chorobom (m.in. rozporządzenie (WE) nr 1924/2006). Zapis „nie leczy” nie jest claimem."),
        _row("clm-pl-weight", "clm-weight", "Claimy o odchudzaniu, spalaniu tłuszczu lub detoksie", "prohibited", WEIGHT, categories=fb, pack="food_beverage",
             alternative="część zbilansowanego poranka", forms=_agree_forms(_WEIGHT_FORMS), notes="Żadnych claimów o odchudzaniu, redukcji masy ciała ani detoksie."),
        _row("clm-pl-clinical", "clm-clinical", "„Klinicznie / naukowo udowodnione” bez badań w dokumentacji", "needs_substantiation", CLINICAL, alternative="palona z troską",
             notes="Przed użyciem wymaga dokumentacji z badaniami."),
        _row("clm-pl-energy", "clm-energy", "Claimy o energii i pobudzeniu (kofeina) wymagają informacji o kofeinie", "approved", ENERGY, categories=fb, disclaimer=DISCLAIMER_CAFFEINE_PL,
             notes="Informacja o kofeinie jest obowiązkowa zawsze, gdy mowa o energii lub pobudzeniu."),
        _row("clm-pl-arabica", "clm-arabica", "100% arabika", "approved", ARABICA, url="https://northwind.example/specs/arabica", notes="Potwierdzone certyfikatami dostawcy zielonych ziaren."),
        _row("clm-pl-smallbatch", "clm-smallbatch", "Palona w małych partiach", "approved", SMALL_BATCH, notes="Palarnia na partie po 60 kg; udokumentowane w dziennikach produkcji."),
        _row("clm-pl-fairtrade", "clm-fairtrade", "Certyfikat Fairtrade / etyczne pozyskiwanie", "needs_substantiation", FAIRTRADE, url="northwind.example/sustainability/fair-trade-2026",
             alternative="z partnerskich plantacji, które odwiedzamy co roku", notes="Ważne tylko z aktualnym numerem certyfikatu Fairtrade pokazanym jako napis prawny."),
        _row("clm-pl-green", "clm-green", "Neutralność węglowa / 100% zrównoważone / przyjazne środowisku (ryzyko greenwashingu)", "prohibited", GREEN, alternative="pakowana w papier kraft nadający się do recyklingu",
             notes="Nieudokumentowane claimy środowiskowe są zakazane (unijne zasady dotyczące deklaracji środowiskowych, wytyczne UOKiK)."),
        _row("clm-pl-best", "clm-best", "Nieudokumentowane superlatywy („najlepsza kawa na świecie”)", "needs_substantiation", BEST, severity="warn", alternative="kawa, z której jesteśmy dumni",
             notes="Claimy porównawcze i superlatywy wymagają obiektywnego uzasadnienia."),
        _row("clm-pl-organic", "clm-organic", "„Ekologiczna” / „bio” bez certyfikatu", "needs_substantiation", ORGANIC, alternative="starannie wybierana", forms=_agree_forms(_ORGANIC_FORMS),
             notes="W prawie żywnościowym „ekologiczny” oznacza produkt z certyfikatem rolnictwa ekologicznego; Dawn Roast nie ma takiego certyfikatu."),
        _row("clm-pl-eu-health", "clm-eu-health", "UE: dozwolone są wyłącznie oświadczenia zdrowotne z unijnego wykazu (rozporządzenie (WE) nr 1924/2006)", "prohibited", EU_HEALTH, markets=["EU"], categories=fb, pack="eu_health_claims",
             alternative="niespieszny poranek", forms=_agree_forms(_HEALTH_FORMS), notes="Dotyczy PL, DE, FR i pozostałych rynków UE. „Na zdrowie” to toast, nie claim."),
        _row("clm-pl-fin-1", "clm-fin-1", "Gwarantowany zysk / inwestycja bez ryzyka", "prohibited", FIN_PROHIBITED, categories=["finance"], pack="finance", alternative="wyniki inwestycji mogą być różne", forms=_agree_forms(_FIN_FORMS)),
        _row("clm-pl-fin-2", "clm-fin-2", "Wzmianki o zyskach lub stopie zwrotu wymagają ostrzeżenia o ryzyku utraty kapitału", "approved", FIN_RETURNS, categories=["finance"], pack="finance", disclaimer=DISCLAIMER_FINANCE_PL),
        _row("clm-pl-ph-1", "clm-ph-1", "Farmacja: claimy o skuteczności wymagają odesłania do ulotki", "needs_substantiation", PHARMA, categories=["pharma"], pack="pharma", disclaimer=DISCLAIMER_PHARMA_PL,
             url="northwind.example/pharma/dossier", notes="Wzorowane na wymogach reklamy produktów leczniczych — materiał demonstracyjny, nie porada prawna."),
        _row("clm-pl-al-1", "clm-al-1", "Alkohol: bez claimów o poprawie wyników i sukcesie towarzyskim; wymagany komunikat o odpowiedzialnym piciu", "prohibited", ALCOHOL, categories=["alcohol"], pack="alcohol",
             disclaimer=DISCLAIMER_ALCOHOL_PL, alternative="do picia z umiarem", notes="W Polsce reklama alkoholu podlega dodatkowym ograniczeniom — wymaga weryfikacji prawnej."),
    ]


def _agree_forms(forms: dict[str, str]) -> dict[str, str]:
    from ..domain.text import fold

    out = dict(forms)
    for k, v in forms.items():
        out.setdefault(fold(k), v)
    return out


# ----------------------------------------------------------------------------------------------- context guards and clause-level rewrites
# Layered on the rows above. ``exclude``: contexts in which a match is not a claim (wishes, toasts, company names, machine pressure …).
# ``alternative_forms`` keys: "@sg3" / "@pl1" — a match that starts with that verb form ("leczy …" -> "daje …", "leczymy …" -> "dajemy …"); "re:<regex>" on the whole match.
# Value "=" is the row's own ``alternative``; a "^" in front ("=^") means it may only replace a span that starts a clause (a noun phrase for a whole clause).
# A row that has such keys offers no replacement for any other match — the Guardian then asks the LLM rewrite instead of putting a noun where a verb is needed.
_PL1_GIVES = "dajemy spokojniejszy początek poranka"
_FIN_FORMS_MORE = {"pewny zwrot": "możliwy zwrot", "pewnego zwrotu": "możliwego zwrotu", "pewne zwroty": "możliwe zwroty", "pewnych zwrotów": "możliwych zwrotów"}
# The English wording of the same claims, for mixed Polish–English copy ("detox blend", "eco-friendly packaging", "clinically proven"): added to the Polish rows, so that
# Polish text is judged on its own and the offline rewrite (which only loads this pack) sees them too.
_EN_LOAN = {
    "clm-pl-cure": [r"re:\b(?:cures?|cured|heals?|healed|treats?|prevents?)\b[^.!?]{0,40}\b(?:anxiety|depression|stress|insomnia|disease|cancer|diabetes|illness|headache|migraine|fatigue)\b"],
    "clm-pl-weight": [r"re:\b(?:burns?\s+fat|fat[\s-]?burn\w*|weight[\s-]?loss|lose\s+weight|slimming|detox\w*|cleanse\w*)\b"],
    "clm-pl-clinical": [r"re:\b(?:clinically|scientifically)\s+proven\b|\bdoctor[\s-]?recommended\b"],
    "clm-pl-energy": [r"re:\b(?:energy|energi[sz]\w*|boost\w*|stay\s+alert|alertness|wake\s+you\s+up)\b"],
    "clm-pl-fairtrade": [r"re:\b(?:fair[\s-]?trade\s+certified|ethically\s+sourced)\b"],
    "clm-pl-green": [r"re:\b(?:carbon[\s-]?neutral|100\s*%\s*sustainable|eco[\s-]?friendly|planet[\s-]?positive)\b"],
    "clm-pl-best": [r"re:\b(?:best\s+coffee\s+in\s+the\s+world|world'?s\s+best\s+coffee|the\s+best\s+coffee|number\s+one\s+coffee|best\s+(?:coffee|espresso))\b"],
    "clm-pl-organic": [r"re:\borganic\b|\bbio[\s-]?certified\b"],
    "clm-pl-eu-health": [r"re:\b(?:healthy|gesund|good\s+for\s+your\s+heart|boosts?\s+immunity|immune\s+system|supports?\s+your\s+health)\b"],
}


def _layers() -> dict[str, dict[str, Any]]:
    organic_more = {k.replace("ekologiczn", "organiczn"): v for k, v in _ORGANIC_FORMS.items()}
    return {
        "clm-pl-cure": {"exclude": CURE_EXCLUDE, "forms": {"@sg3": "=", "@pl1": _PL1_GIVES}},
        "clm-pl-weight": {"forms": {"@sg3": _WEIGHT_FORMS["odchudza"]}},
        "clm-pl-clinical": {"forms": {"re:.*": "=^"}},
        "clm-pl-energy": {"exclude": ENERGY_EXCLUDE},
        "clm-pl-green": {"forms": {"re:.*": "=^"}},
        "clm-pl-best": {"forms": {"re:.*": "=^"}},
        "clm-pl-organic": {"exclude": ORGANIC_EXCLUDE, "forms": {**organic_more, "re:(?:bio|eko)": "="}},
        "clm-pl-eu-health": {"exclude": EU_HEALTH_EXCLUDE, "forms": {"@sg3": "daje spokojniejszy początek poranka", "@pl1": _PL1_GIVES}},
        "clm-pl-fin-1": {"forms": _FIN_FORMS_MORE},
    }


def claims_pl() -> list[dict[str, Any]]:
    """The Polish pack as seeded: the rows with their context guards (``exclude``) and verb-form / clause-level rewrites."""
    layers = _layers()
    rows = _claims_pl_rows()
    for row in rows:
        if row["id"] in _EN_LOAN:
            row["patterns"] = [*row["patterns"], *_EN_LOAN[row["id"]]]
        layer = layers.get(row["id"])
        if not layer:
            continue
        if layer.get("exclude"):
            row["exclude"] = list(layer["exclude"])
        if layer.get("forms"):
            row["alternative_forms"] = {**_agree_forms(layer["forms"]), **row.get("alternative_forms", {})}
    return rows
