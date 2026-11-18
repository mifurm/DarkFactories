"""Synthetic sample data: fictional Northwind Coffee Roasters brand, claims library, rights registry, sample briefs.

All content is invented for demonstration. Loaded idempotently (deterministic ids) on first start and via
POST /api/admin/reseed.
"""

from __future__ import annotations

from typing import Any

from ..domain.pl_morph import DEFAULT_PL_FORBIDDEN, DEFAULT_PL_REPLACEMENTS, HYPE_PATTERNS_PL
from ..util import days_from_now, now_iso
from .pl_claims import claims_pl

BRAND_ID = "northwind"
SEED_VERSION = "2026.11.3"  # 2026.11.3: Polish copy edit (brand book, kit overlay, claims texts, rights notes, sample brief); 2026.11.2: Polish content pack (brand book, kit overlay, claims pack, rights notes, sample campaign)

GUIDELINES_MD = """# Northwind Coffee Roasters — Brand Book (synthetic sample)

## Who we are
Northwind Coffee Roasters is a small-batch roaster founded in 2011 in Portland. We roast in 60 kg batches, taste every batch,
and buy from partner farms we visit every year. We believe mornings are better when you do not rush them.
Our promise is simple and quiet: good coffee, honestly made. Our tagline is "Wake up slowly."

## Voice and tone
We sound warm, unhurried, honest and quietly confident. We talk like a neighbour who happens to roast coffee, not like an
energy-drink brand. We use short sentences and concrete sensory details: steam, light, the first sip. We never shout,
never use more than one exclamation mark in a piece, and never promise health outcomes. We do not say cheap, miracle,
detox, hack or guaranteed. We prefer "ritual" and "slow morning" to "boost" and "fuel".

## Do and do not
Do: lead with a human moment before the product. Do: show the amber sun mark on the bag. Do: end on "Wake up slowly."
Do not: make medical or health claims (cure, treat, prevent, heal). Do not: compare ourselves to competitors by name.
Do not: use stock music without a licence on file. Do not: call the coffee "the best in the world".

## Visual identity
Palette: Espresso #2B1A12 (primary dark), Dawn Amber #F2A03D (accent), Cream #F6EBDD (background), Roast Red #B5452B
(secondary accent) and Sage #5C7A5E (supporting). Photography uses low, warm sunrise light, long soft shadows and real
textures: steam, ceramic, kraft paper. Typography: Fraunces for headlines, Inter for body text. The logo is the NORTHWIND
wordmark with the amber sun mark; it must be at least 12% of the frame width and keep a clear space of half the logo height.

## Products
Dawn Roast: medium roast, 100% Arabica, notes of caramel, orange peel and cocoa; 12 oz kraft bag with the amber sun mark.
Midnight Blend: dark roast, bold and smooth, for the evening ritual. Cold Brew Cans: slow-steeped for 18 hours, 250 ml.
All products contain caffeine. Not recommended for children or pregnant women.

## Audiences
Maya, 34, ICU nurse on early shifts: wants a calm first cup before a hard day. Dev, 41, commuting dad: wants ten quiet
minutes before the house wakes up. Lena, 26, remote designer: wants a ritual that marks the start of the working day.

## Sourcing and sustainability
We buy 100% Arabica from partner farms in Colombia, Ethiopia and Guatemala. Our Fair Trade certificate (2026) covers the
Dawn Roast and Midnight Blend lots. We do not claim to be carbon neutral. Packaging is recyclable kraft paper with a
compostable valve.

## Sample lines that sound like us
"Some mornings deserve a slower start." "Light comes up. Steam rises. Nothing else has to." "Roasted in small batches, poured
without hurry." "Wake up slowly."
"""

GUIDELINES_MD_PL = """# Northwind Coffee Roasters — Księga marki (przykład syntetyczny)

## Kim jesteśmy
Northwind Coffee Roasters to mała palarnia kawy założona w 2011 roku w Portland. Palimy w partiach po 60 kg, próbujemy każdą partię
i kupujemy ziarna od partnerskich plantacji, które odwiedzamy co roku. Wierzymy, że poranki są lepsze bez pośpiechu.
Nasza obietnica jest prosta i cicha: dobra kawa, uczciwie palona. Nasze hasło marki to „Obudź się powoli.”

## Głos i ton
Brzmimy ciepło, niespiesznie, szczerze i z cichą pewnością siebie. Mówimy jak sąsiad, który przy okazji prowadzi palarnię kawy — nie jak marka
napojów energetycznych. Używamy krótkich zdań i konkretnych szczegółów, które da się poczuć: para, światło, pierwszy łyk. Nigdy nie krzyczymy.
W jednym materiale używamy najwyżej jednego wykrzyknika i nie obiecujemy żadnych skutków zdrowotnych. Nie mówimy „tani”, „cudowny”, „detoks”,
„hack” ani „gwarantowany”. Wolimy „rytuał” i „powolny poranek” od „kopa” i „paliwa”.

## Rejestr: „ty”, nie „Pan/Pani”
W komunikacji reklamowej zwracamy się do odbiorcy na „ty”. Wybieramy tę formę świadomie: marka mówi jak życzliwy sąsiad, a nie jak
instytucja, więc „Nalej sobie kawy. Nic więcej nie musi się dziać.” brzmi u nas naturalniej niż „Proszę nalać sobie kawy”. „Ty” oznacza
bliskość, nigdy poufałość: bez slangu, bez żartów kosztem odbiorcy i bez nacisku. W tekstach prawnych, regulaminach i obsłudze klienta
używamy formy neutralnej i grzecznościowej („Niezalecane dla dzieci i kobiet w ciąży”, „Prosimy o kontakt”).

## Zasady: co robimy, a czego nie
Zawsze zaczynamy od ludzkiej chwili, a dopiero potem pokazujemy produkt. Zawsze pokazujemy bursztynowe słońce na opakowaniu.
Zawsze kończymy hasłem „Obudź się powoli.”
Nigdy nie przypisujemy kawie działania leczniczego ani zdrowotnego (leczy, łagodzi, zapobiega, uzdrawia). Nigdy nie wskazujemy konkurentów
z nazwy w porównaniach. Nigdy nie używamy muzyki, której licencji nie ma w rejestrze praw. Nigdy nie nazywamy naszej kawy „najlepszą na świecie”.

## Identyfikacja wizualna
Paleta: Espresso #2B1A12 (główny kolor ciemny), Bursztyn świtu #F2A03D (akcent), Krem #F6EBDD (tło), Czerwień palarni #B5452B (drugi akcent)
i Szałwia #5C7A5E (kolor uzupełniający). Fotografia: niskie, ciepłe światło wschodu słońca, długie miękkie cienie i prawdziwe
faktury: para, ceramika, papier kraft. Typografia: Fraunces w nagłówkach, Inter w tekście. Logo to logotyp NORTHWIND z bursztynowym
znakiem słońca; musi zajmować co najmniej 12% szerokości kadru, a wokół niego trzeba zachować pole ochronne równe połowie wysokości logo.

## Produkty
Dawn Roast: średnie palenie, 100% arabika, nuty karmelu, skórki pomarańczy i kakao; torba z papieru kraft 340 g z bursztynowym
znakiem słońca. Midnight Blend: ciemne palenie, intensywne i gładkie, na wieczorny rytuał. Cold Brew w puszkach: powoli zaparzany na zimno
przez 18 godzin, puszki 250 ml. Wszystkie produkty zawierają kofeinę. Niezalecane dla dzieci i kobiet w ciąży.

## Odbiorcy
Maja, 34 lata, pielęgniarka z OIOM-u, pracuje na pierwszej zmianie: chce spokojnie wypić pierwszą kawę przed trudnym dniem. Darek, 41 lat, tata
dojeżdżający do pracy: chce dziesięciu cichych minut, zanim dom się obudzi. Lena, 26 lat, projektantka pracująca zdalnie: chce rytuału,
który wyznacza początek dnia pracy.

## Pochodzenie i zrównoważony rozwój
Kupujemy 100% arabikę od partnerskich plantacji w Kolumbii, Etiopii i Gwatemali. Certyfikat Fairtrade (2026) obejmuje partie Dawn Roast
i Midnight Blend. Nie deklarujemy neutralności węglowej. Opakowania wykonujemy z papieru kraft nadającego się do recyklingu, z kompostowalnym zaworkiem.

## Przykładowe zdania, które brzmią jak my
„Są poranki, które zasługują na wolniejszy początek.” „Światło wstaje. Para się unosi. Reszta może poczekać.” „Palona w małych partiach,
nalewana bez pośpiechu.” „Obudź się powoli.”
"""

PALETTE = [
    {"name": "Espresso", "hex": "#2B1A12", "role": "Primary dark"},
    {"name": "Dawn Amber", "hex": "#F2A03D", "role": "Accent"},
    {"name": "Cream", "hex": "#F6EBDD", "role": "Background"},
    {"name": "Roast Red", "hex": "#B5452B", "role": "Secondary accent"},
    {"name": "Sage", "hex": "#5C7A5E", "role": "Supporting"},
]
# Polish names and roles of the palette colours, as written in the Polish Brand Book (the kit itself keeps the English names).
PALETTE_PL = {
    "Espresso": ("Espresso", "główny kolor ciemny"),
    "Dawn Amber": ("Bursztyn świtu", "akcent"),
    "Cream": ("Krem", "tło"),
    "Roast Red": ("Czerwień palarni", "drugi akcent"),
    "Sage": ("Szałwia", "kolor uzupełniający"),
}

KIT: dict[str, Any] = {
    "tagline": "Wake up slowly.",
    "palette": PALETTE,
    "typography": {"display": "Fraunces (serif)", "body": "Inter (sans-serif)"},
    "logo": {"wordmark": "NORTHWIND", "sub": "COFFEE ROASTERS", "min_width_pct": 12.0, "clear_space_ratio": 0.5, "notes": "Amber sun mark above the wordmark; never stretch, outline or recolour."},
    "voice": {
        "tone": ["warm", "unhurried", "honest", "quietly confident"],
        "dos": ["Lead with a human moment before the product", "Use short, sensory sentences", "End on the tagline 'Wake up slowly.'"],
        "donts": ["No medical or health claims", "No hype superlatives", "No competitor comparisons", "No unlicensed music"],
        "forbidden_words": ["cheap", "miracle", "detox", "hack", "addictive", "guaranteed", "game-changer"],
        "replacements": {"cheap": "great value", "miracle": "remarkable", "detox": "refresh", "hack": "habit", "addictive": "easy to love", "guaranteed": "dependable", "game-changer": "welcome change"},
        "max_exclamations": 1,
        "max_sentence_words": 22,
        "glossary": [
            {"term": "Dawn Roast", "translate": False},
            {"term": "Northwind", "translate": False},
            {"term": "Midnight Blend", "translate": False},
            {"term": "Wake up slowly", "translate": True, "translations": {"en": "Wake up slowly", "de": "Wach langsam auf", "fr": "Réveillez-vous lentement", "pl": "Obudź się powoli", "es": "Despierta despacio", "it": "Svegliati piano", "pt": "Acorde devagar", "nl": "Word rustig wakker"}},
        ],
    },
    "products": [
        {"id": "dawn-roast", "name": "Dawn Roast", "description": "Medium roast, 100% Arabica, notes of caramel, orange peel and cocoa. 12 oz kraft bag with the amber sun mark.", "sku": "NW-DR-12"},
        {"id": "midnight-blend", "name": "Midnight Blend", "description": "Dark roast, bold and smooth, for the evening ritual.", "sku": "NW-MB-12"},
        {"id": "cold-brew-cans", "name": "Cold Brew Cans", "description": "Slow-steeped for 18 hours; 250 ml cans.", "sku": "NW-CB-250"},
    ],
    "personas": [
        {"id": "maya", "name": "Maya, 34 — ICU nurse (early shifts)", "needs": "A calm first cup before a hard day", "channels": ["tiktok", "meta"]},
        {"id": "dev", "name": "Dev, 41 — commuting dad", "needs": "Ten quiet minutes before the house wakes up", "channels": ["youtube", "ctv"]},
        {"id": "lena", "name": "Lena, 26 — remote designer", "needs": "A ritual that marks the start of the working day", "channels": ["meta", "youtube"]},
    ],
    "markets": ["US", "DE", "FR", "PL"],
    "category": "beverage",
    # Per-language overlays (the Polish Brand Book content: register, voice rules, personas, products, sourcing text).
    "i18n": {
        "pl": {
            "tagline": "Obudź się powoli.",
            "register": "ty",
            "register_note": "W reklamie zwracamy się do odbiorcy na „ty” (ciepło, jak sąsiad, bez poufałości). W tekstach prawnych, regulaminach i obsłudze używamy formy neutralnej i grzecznościowej („Prosimy…”, „Niezalecane dla…”).",
            "voice": {
                "tone": ["ciepły", "niespieszny", "szczery", "z cichą pewnością siebie"],
                "dos": [
                    "Zacznij od ludzkiej chwili, dopiero potem pokaż produkt",
                    "Pisz krótkimi zdaniami i odwołuj się do zmysłów",
                    "Zakończ hasłem „Obudź się powoli.”",
                    "Zwracaj się do odbiorcy na „ty” — ciepło, ale bez poufałości",
                ],
                "donts": ["Żadnych claimów medycznych ani zdrowotnych", "Żadnych superlatywów reklamowych", "Żadnego wskazywania konkurentów z nazwy", "Żadnej muzyki bez licencji"],
                "forbidden_words": DEFAULT_PL_FORBIDDEN,
                "replacements": DEFAULT_PL_REPLACEMENTS,
                "hype_terms": HYPE_PATTERNS_PL,
                "max_exclamations": 1,
                "max_sentence_words": 20,
                "pronunciations": {"Dawn Roast": "dołn rołst", "Northwind": "nortłind", "Midnight Blend": "midnajt blend"},
            },
            "products": [
                {"id": "dawn-roast", "name": "Dawn Roast", "description": "Średnie palenie, 100% arabika, nuty karmelu, skórki pomarańczy i kakao. Torba z papieru kraft 340 g z bursztynowym znakiem słońca."},
                {"id": "midnight-blend", "name": "Midnight Blend", "description": "Ciemne palenie, intensywne i gładkie — na wieczorny rytuał."},
                {"id": "cold-brew-cans", "name": "Cold Brew w puszkach", "description": "Powoli zaparzany na zimno przez 18 godzin; puszki 250 ml."},
            ],
            "personas": [
                {"id": "maya", "name": "Maja, 34 lata — pielęgniarka z OIOM-u (pierwsza zmiana)", "needs": "Spokojna pierwsza filiżanka przed trudnym dniem"},
                {"id": "dev", "name": "Darek, 41 lat — tata dojeżdżający do pracy", "needs": "Dziesięć cichych minut, zanim dom się obudzi"},
                {"id": "lena", "name": "Lena, 26 lat — projektantka pracująca zdalnie", "needs": "Rytuał, który wyznacza początek dnia pracy"},
            ],
            "sourcing": "Kupujemy 100% arabikę od partnerskich plantacji w Kolumbii, Etiopii i Gwatemali, które odwiedzamy co roku. Certyfikat Fairtrade (2026) obejmuje partie Dawn Roast i Midnight Blend. "
            "Nie deklarujemy neutralności węglowej. Opakowania wykonujemy z papieru kraft nadającego się do recyklingu, z kompostowalnym zaworkiem.",
            "logo": {"notes": "Bursztynowy znak słońca nad logotypem; nie rozciągaj, nie obrysowuj ani nie zmieniaj kolorów."},
        }
    },
}

DISCLAIMER_CAFFEINE = "Contains caffeine. Not recommended for children or pregnant women."

# Polish descriptions of the English claim rules (shown when a Polish-speaking user reads a finding raised by an English rule).
CLAIM_TEXT_PL = {
    "clm-cure": "Claimy o leczeniu, łagodzeniu lub zapobieganiu chorobom",
    "clm-weight": "Claimy o odchudzaniu, spalaniu tłuszczu lub detoksie",
    "clm-clinical": "„Klinicznie / naukowo udowodnione” bez badań w dokumentacji",
    "clm-energy": "Claimy o energii i czujności (kofeina) wymagają informacji o kofeinie",
    "clm-arabica": "100% arabika",
    "clm-smallbatch": "Palona w małych partiach",
    "clm-fairtrade": "Certyfikat Fairtrade / etyczne pozyskiwanie",
    "clm-green": "Neutralność węglowa / 100% zrównoważone / przyjazne środowisku (ryzyko greenwashingu)",
    "clm-best": "Nieudokumentowane superlatywy („najlepsza kawa na świecie”)",
    "clm-organic": "„Ekologiczna” / „bio” bez certyfikatu",
    "clm-eu-health": "UE: dozwolone są wyłącznie oświadczenia zdrowotne z unijnego wykazu (rozporządzenie (WE) nr 1924/2006)",
    "clm-fin-1": "Gwarantowany zysk / inwestycja bez ryzyka",
    "clm-fin-2": "Wzmianki o zyskach lub stopie zwrotu wymagają ostrzeżenia o ryzyku utraty kapitału",
    "clm-ph-1": "Farmacja: claimy o skuteczności wymagają odesłania do ulotki",
    "clm-al-1": "Alkohol: bez claimów o poprawie wyników i sukcesie towarzyskim; wymagany komunikat o odpowiedzialnym piciu",
}
# English descriptions of the Polish rules (for English-speaking viewers).
CLAIM_TEXT_EN_OF_PL = {
    "clm-pl-cure": "Claims to cure, soothe or prevent a disease or ailment (Polish wording)",
    "clm-pl-weight": "Weight-loss, fat-burning or detox claims (Polish wording)",
    "clm-pl-clinical": "'Clinically / scientifically proven' without a study on file (Polish wording)",
    "clm-pl-energy": "Energy / stimulation statements (caffeine) need the caffeine disclaimer (Polish wording)",
    "clm-pl-arabica": "100% Arabica (Polish wording)",
    "clm-pl-smallbatch": "Roasted in small batches (Polish wording)",
    "clm-pl-fairtrade": "Fairtrade certificate / ethical sourcing (Polish wording)",
    "clm-pl-green": "Carbon-neutral / 100% sustainable / eco-friendly — greenwashing risk (Polish wording)",
    "clm-pl-best": "Unsubstantiated superlatives ('best coffee in the world') (Polish wording)",
    "clm-pl-organic": "'Organic' / 'bio' without a certificate (Polish wording)",
    "clm-pl-eu-health": "EU: only authorised health claims (Reg. 1924/2006) (Polish wording)",
    "clm-pl-fin-1": "Guaranteed / risk-free returns (Polish wording)",
    "clm-pl-fin-2": "Return statements need the capital-at-risk disclaimer (Polish wording)",
    "clm-pl-ph-1": "Pharma: efficacy claims need the leaflet disclaimer (Polish wording)",
    "clm-pl-al-1": "Alcohol: no performance/social-success claims; responsibility message required (Polish wording)",
}


def claims() -> list[dict[str, Any]]:
    b = BRAND_ID
    return [
        {"id": "clm-cure", "brand_id": b, "text": "Claims to cure, treat or prevent a medical condition", "type": "prohibited", "markets": ["*"], "categories": ["food", "beverage"], "rule_pack": "food_beverage", "severity": "block",
             "patterns": [r"re:\b(cure[sd]?|treat(?:s|ed|ing)?|heal(?:s|ed|ing)?|prevent(?:s|ed|ing)?|remed(?:y|ies))\b.{0,40}\b(anxiety|depression|stress|insomnia|disease|cancer|diabetes|illness|headache|migraine|fatigue)"],
             "alternative": "brings a calmer start to your morning", "notes": "Food and beverage products may not claim to treat, prevent or cure disease (e.g. EU 1924/2006, FDA structure/function rules)."},
        {"id": "clm-weight", "brand_id": b, "text": "Weight-loss, fat-burning or detox claims", "type": "prohibited", "markets": ["*"], "categories": ["food", "beverage"], "rule_pack": "food_beverage", "severity": "block",
             "patterns": ["burns fat", "fat burning", "weight loss", "lose weight", "slimming", "detox", "cleanse"], "alternative": "part of a balanced morning", "notes": "No weight-management or detox claims."},
        {"id": "clm-clinical", "brand_id": b, "text": "'Clinically / scientifically proven' without a study on file", "type": "needs_substantiation", "markets": ["*"], "categories": ["*"], "severity": "block",
             "patterns": ["clinically proven", "scientifically proven", "doctor recommended", "proven to"], "alternative": "roasted with care", "notes": "Requires a substantiation dossier before use."},
        {"id": "clm-energy", "brand_id": b, "text": "Energy / alertness statements (caffeine) need the caffeine disclaimer", "type": "approved", "markets": ["*"], "categories": ["food", "beverage"], "severity": "block",
             "patterns": ["re:\\b(energy|energi[sz]e|energi[sz]ing|stay alert|alertness|wake you up|boost)\\b"], "required_disclaimer": DISCLAIMER_CAFFEINE, "notes": "Caffeine disclosure is mandatory whenever energy or alertness is mentioned."},
        {"id": "clm-arabica", "brand_id": b, "text": "100% Arabica", "type": "approved", "markets": ["*"], "categories": ["*"], "patterns": ["100% arabica", "100 percent arabica"], "substantiation_url": "https://northwind.example/specs/arabica", "notes": "Verified by green-bean supplier certificates."},
        {"id": "clm-smallbatch", "brand_id": b, "text": "Roasted in small batches", "type": "approved", "markets": ["*"], "categories": ["*"], "patterns": ["roasted in small batches", "small-batch", "small batch"], "notes": "60 kg roaster; documented in production logs."},
        {"id": "clm-fairtrade", "brand_id": b, "text": "Fair Trade certified / ethically sourced", "type": "needs_substantiation", "markets": ["*"], "categories": ["*"], "severity": "block",
             "patterns": ["fair trade certified", "fairtrade certified", "ethically sourced", "fair trade"], "substantiation_url": "northwind.example/sustainability/fair-trade-2026", "alternative": "sourced from partner farms we visit every year",
             "notes": "Valid only with the current Fair Trade certificate reference shown as a legal super."},
        {"id": "clm-green", "brand_id": b, "text": "Carbon-neutral / 100% sustainable / eco-friendly (greenwashing risk)", "type": "prohibited", "markets": ["*"], "categories": ["*"], "severity": "block",
             "patterns": ["carbon neutral", "carbon-neutral", "100% sustainable", "eco-friendly", "planet positive"], "alternative": "packaged in recyclable kraft paper", "notes": "Unsubstantiated environmental claims are prohibited (EU Green Claims, FTC Green Guides)."},
        {"id": "clm-best", "brand_id": b, "text": "Unsubstantiated superlatives ('best coffee in the world')", "type": "needs_substantiation", "markets": ["*"], "categories": ["*"], "severity": "warn",
             "patterns": ["best coffee in the world", "world's best coffee", "the best coffee", "number one coffee", "#1 coffee"], "alternative": "a coffee we are proud of", "notes": "Comparative / superlative claims need objective support."},
        {"id": "clm-organic", "brand_id": b, "text": "'Organic' without a certificate", "type": "needs_substantiation", "markets": ["*"], "categories": ["*"], "severity": "block", "patterns": ["organic", "bio-certified"], "alternative": "carefully sourced", "notes": "No organic certification for Dawn Roast."},
        {"id": "clm-eu-health", "brand_id": b, "text": "EU: only authorised health claims (Reg. 1924/2006)", "type": "prohibited", "markets": ["EU"], "categories": ["food", "beverage"], "rule_pack": "eu_health_claims", "severity": "block",
             "patterns": ["healthy", "gesund", "good for your heart", "boosts immunity", "immune system", "supports your health"], "alternative": "unhurried", "notes": "Applies to DE/FR/PL and other EU markets."},
        {"id": "clm-fin-1", "brand_id": b, "text": "Guaranteed / risk-free returns", "type": "prohibited", "markets": ["*"], "categories": ["finance"], "rule_pack": "finance", "severity": "block", "patterns": ["guaranteed returns", "risk-free", "no risk", "can't lose"], "alternative": "returns are not guaranteed"},
        {"id": "clm-fin-2", "brand_id": b, "text": "Return statements need the capital-at-risk disclaimer", "type": "approved", "markets": ["*"], "categories": ["finance"], "rule_pack": "finance", "patterns": ["re:\\b(returns?|yield|growth)\\b"], "required_disclaimer": "Capital at risk. Past performance is not a guide to future returns."},
        {"id": "clm-ph-1", "brand_id": b, "text": "Pharma: efficacy claims need the leaflet disclaimer", "type": "needs_substantiation", "markets": ["*"], "categories": ["pharma"], "rule_pack": "pharma", "severity": "block", "patterns": ["clinically proven", "relieves", "fast-acting"], "required_disclaimer": "Always read the leaflet.", "substantiation_url": "northwind.example/pharma/dossier"},
        {"id": "clm-al-1", "brand_id": b, "text": "Alcohol: no performance/social-success claims; responsibility message required", "type": "prohibited", "markets": ["*"], "categories": ["alcohol"], "rule_pack": "alcohol", "severity": "block", "patterns": ["improves performance", "makes you popular", "gets the party started"], "required_disclaimer": "Drink responsibly.", "alternative": "enjoy responsibly"},
    ]


def rights() -> list[dict[str, Any]]:
    b = BRAND_ID
    return [
        {"id": "mus-dawn-pad", "brand_id": b, "kind": "music", "title": "Dawn Pad (library)", "licensor": "Spotlight Procedural Library (generated, CC0)", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2025-01-01", "valid_to": "2099-12-31",
             "library_track": {"mood": "calm", "bpm": 72, "key": "D", "seed": 11}, "usage_notes": "Licensed library track — procedurally generated by Spotlight; royalty-free.", "aliases": ["dawn pad"]},
        {"id": "mus-morning-pulse", "brand_id": b, "kind": "music", "title": "Morning Pulse (library)", "licensor": "Spotlight Procedural Library (generated, CC0)", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2025-01-01", "valid_to": "2099-12-31",
             "library_track": {"mood": "uplifting", "bpm": 96, "key": "G", "seed": 22}, "usage_notes": "Licensed library track — procedurally generated; royalty-free.", "aliases": ["morning pulse"]},
        {"id": "mus-slow-ember", "brand_id": b, "kind": "music", "title": "Slow Ember (library)", "licensor": "Spotlight Procedural Library (generated, CC0)", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2025-01-01", "valid_to": "2099-12-31",
             "library_track": {"mood": "warm", "bpm": 84, "key": "A", "seed": 33}, "usage_notes": "Licensed library track — procedurally generated; royalty-free.", "aliases": ["slow ember"]},
        {"id": "mus-golden-hour", "brand_id": b, "kind": "music", "title": "Golden Hour Pop (artist track)", "licensor": "Goldfinch Kids Music Ltd", "status": "pending", "territories": ["US"], "channels": ["ctv"], "valid_from": "2026-09-01", "valid_to": "2027-03-01",
             "usage_notes": "Negotiation pending — not cleared for paid social or EU markets.", "aliases": ["golden hour pop"]},
        {"id": "tal-maya", "brand_id": b, "kind": "talent", "title": "Maya Okafor", "licensor": "Okafor Talent Agency", "status": "active", "territories": ["EU", "US"], "channels": ["youtube", "meta", "tiktok", "ctv", "display"], "valid_from": "2026-01-01", "valid_to": "2027-12-31",
             "ai_voice_consent": True, "ai_likeness_consent": False, "usage_notes": "Voice-over consent including AI-assisted voice synthesis; NO likeness consent."},
        {"id": "tal-jonas", "brand_id": b, "kind": "talent", "title": "Jonas Weber", "licensor": "Weber Management GmbH", "status": "active", "territories": ["EU"], "channels": ["youtube", "meta"], "valid_from": "2024-12-01", "valid_to": "2025-12-31",
             "ai_voice_consent": True, "ai_likeness_consent": True, "usage_notes": "Consent window ended 2025-12-31 — renewal outstanding."},
        {"id": "tal-amara", "brand_id": b, "kind": "talent", "title": "Amara Diallo", "licensor": "Diallo Creative", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2026-01-01", "valid_to": days_from_now(20),
             "ai_voice_consent": False, "ai_likeness_consent": False, "usage_notes": "On-camera talent; consent expires soon (expiry alert demo)."},
        {"id": "stk-latte", "brand_id": b, "kind": "stock", "title": "Stock photo: latte art hero", "licensor": "Fabrikam Stock", "status": "active", "territories": ["US"], "channels": [], "valid_from": "2025-06-01", "valid_to": "2027-06-01", "usage_notes": "US only."},
        {"id": "stk-hills", "brand_id": b, "kind": "stock", "title": "Stock footage: sunrise hills", "licensor": "Fabrikam Stock", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2025-06-01", "valid_to": "2028-06-01"},
        {"id": "fnt-fraunces", "brand_id": b, "kind": "font", "title": "Fraunces & Inter (SIL OFL)", "licensor": "Open source (OFL)", "status": "active", "territories": ["WW"], "channels": [], "valid_from": "2020-01-01", "valid_to": "2099-12-31"},
    ]


def all_claims() -> list[dict[str, Any]]:
    """English rules (with Polish descriptions) + the Polish pack (with English descriptions) — what the seeder loads."""
    en = [{**c, "lang": "en", "text_i18n": {"pl": CLAIM_TEXT_PL[c["id"]]}} if c["id"] in CLAIM_TEXT_PL else c for c in claims()]
    pl = [{**c, "text_i18n": {"en": CLAIM_TEXT_EN_OF_PL[c["id"]]}} for c in claims_pl()]
    return en + pl


# Polish rendering of the registry's descriptive text (names of people, companies and tracks are proper nouns and stay as they are).
RIGHTS_I18N_PL: dict[str, dict[str, str]] = {
    "mus-dawn-pad": {"usage_notes": "Licencjonowany utwór z biblioteki muzycznej — generowany proceduralnie przez Spotlight; bez opłat licencyjnych.", "licensor": "Biblioteka proceduralna Spotlight (generowana, CC0)"},
    "mus-morning-pulse": {"usage_notes": "Licencjonowany utwór z biblioteki muzycznej — generowany proceduralnie; bez opłat licencyjnych.", "licensor": "Biblioteka proceduralna Spotlight (generowana, CC0)"},
    "mus-slow-ember": {"usage_notes": "Licencjonowany utwór z biblioteki muzycznej — generowany proceduralnie; bez opłat licencyjnych.", "licensor": "Biblioteka proceduralna Spotlight (generowana, CC0)"},
    "mus-golden-hour": {"usage_notes": "Negocjacje w toku — brak zgody na użycie w płatnych mediach społecznościowych i na rynkach UE."},
    "tal-maya": {"usage_notes": "Zgoda na użycie głosu jako lektora, także w postaci głosu syntetyzowanego z pomocą AI; BRAK zgody na wykorzystanie wizerunku."},
    "tal-jonas": {"usage_notes": "Zgoda wygasła 31.12.2025 — odnowienie jeszcze nie nastąpiło."},
    "tal-amara": {"usage_notes": "Talent występujący przed kamerą; zgoda wkrótce wygasa (demonstracja alertu o wygasaniu)."},
    "stk-latte": {"usage_notes": "Tylko USA."},
    "fnt-fraunces": {"licensor": "Open source (SIL OFL)"},
}


def all_rights() -> list[dict[str, Any]]:
    return [{**r, "i18n": {"pl": RIGHTS_I18N_PL[r["id"]]}} if r["id"] in RIGHTS_I18N_PL else r for r in rights()]


DAWN_ROAST_BRIEF = """Brief — Dawn Roast launch (Northwind Coffee Roasters)

We launch Dawn Roast, our new medium roast, in the US, Germany, France and Poland this September.
Objective: drive trial among early-shift workers and commuters — 150,000 trial purchases in 8 weeks.
Audience: 28–45, early risers — nurses, bakers, commuting parents and remote workers who start before 7am.
Channels: YouTube pre-roll, Meta/Instagram reels, TikTok, CTV.
Budget: media EUR 400k; we want production to stay under EUR 30k.
Timeline: concept in 1 week, final spots in 3 weeks, live on Sept 14.
Mandatories: end on the tagline "Wake up slowly."; show the amber sun bag; the legal team wants the line "Dawn Roast cures morning anxiety." in the spot.
Tone: warm, unhurried, honest.
Music: something like "Sunrise Anthem" by the Goldfinch Kids — our CEO loves it.
Talent: Maya Okafor (voice-over).
"""

DAWN_ROAST_BRIEF_PL = """Brief — premiera Dawn Roast w Polsce (Northwind Coffee Roasters)

Wprowadzamy na rynek Dawn Roast, naszą nową kawę średnio paloną — w styczniu, w Polsce.
Cel: zachęcić do pierwszego zakupu osoby, które zaczynają dzień przed siódmą rano — 120 000 zakupów próbnych w 8 tygodni.
Odbiorcy: 28–45 lat, ranne ptaszki — pielęgniarki, piekarze, rodzice dojeżdżający do pracy i osoby pracujące zdalnie, które zaczynają dzień przed 7:00.
Kanały: YouTube (pre-roll), Meta/Instagram (reels), TikTok, CTV.
Budżet: media 1 500 000 PLN; produkcja nie powinna przekroczyć 120 000 PLN.
Harmonogram: koncepcja w ciągu tygodnia, finalne spoty w ciągu 3 tygodni, emisja od 12 stycznia.
Elementy obowiązkowe: zakończyć hasłem „Obudź się powoli.”; pokazać torbę z bursztynowym słońcem; dział prawny chce w spocie zdanie „Dawn Roast leczy poranny niepokój.”
Ton: ciepły, niespieszny, szczery.
Muzyka: coś w stylu „Sunrise Anthem” zespołu Goldfinch Kids — nasz prezes uwielbia ten kawałek.
Lektor: Maya Okafor.
"""


def campaigns() -> list[dict[str, Any]]:
    return [
        {
            "id": "dawn-roast-launch",
            "campaign_id": "dawn-roast-launch",
            "name": "Dawn Roast — Launch (US · DE · FR · PL)",
            "brand_id": BRAND_ID,
            "status": "draft",
            "stage": "brief",
            "language": "en",
            "markets": ["US", "DE", "FR", "PL"],
            "channels": ["youtube", "meta", "tiktok", "ctv"],
            "product_id": "dawn-roast",
            "category": "beverage",
            "air_start": "2026-09-14",
            "air_end": "2027-02-28",
            "budget_cap_usd": 2.0,
            "premium_approved": False,
            "synthetic": True,
            "demo_brief": DAWN_ROAST_BRIEF,
            "created_at": now_iso(),
        },
        {
            "id": "midnight-blend-winter",
            "campaign_id": "midnight-blend-winter",
            "name": "Midnight Blend — Winter Relaunch",
            "brand_id": BRAND_ID,
            "status": "published",
            "stage": "performance",
            "language": "en",
            "markets": ["US", "DE"],
            "channels": ["youtube", "meta", "tiktok"],
            "product_id": "midnight-blend",
            "category": "beverage",
            "air_start": "2026-01-10",
            "air_end": "2026-03-31",
            "budget_cap_usd": 2.0,
            "premium_approved": False,
            "synthetic": True,
            "history": True,
            "created_at": "2026-01-02T09:00:00+00:00",
        },
    ]


def campaigns_pl() -> list[dict[str, Any]]:
    """The Polish sample campaign, seeded next to the English one (deterministic id; never overwritten once it exists)."""
    return [
        {
            "id": "dawn-roast-premiera-pl",
            "campaign_id": "dawn-roast-premiera-pl",
            "name": "Dawn Roast — premiera w Polsce",
            "brand_id": BRAND_ID,
            "status": "draft",
            "stage": "brief",
            "language": "pl",
            "markets": ["PL"],
            "channels": ["youtube", "meta", "tiktok", "ctv"],
            "product_id": "dawn-roast",
            "category": "beverage",
            "air_start": "2027-01-12",
            "air_end": "2027-03-31",
            "budget_cap_usd": 2.0,
            "premium_approved": False,
            "synthetic": True,
            "demo_brief": DAWN_ROAST_BRIEF_PL,
            "created_at": "2026-11-17T00:00:00+00:00",
        }
    ]
