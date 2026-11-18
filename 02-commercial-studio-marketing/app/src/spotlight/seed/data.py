"""Synthetic sample data: fictional Northwind Coffee Roasters brand, claims library, rights registry, sample briefs.

All content is invented for demonstration. Loaded idempotently (deterministic ids) on first start and via
POST /api/admin/reseed.
"""

from __future__ import annotations

from typing import Any

from ..util import days_from_now, now_iso

BRAND_ID = "northwind"
SEED_VERSION = "2026.11.1"

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

PALETTE = [
    {"name": "Espresso", "hex": "#2B1A12", "role": "Primary dark"},
    {"name": "Dawn Amber", "hex": "#F2A03D", "role": "Accent"},
    {"name": "Cream", "hex": "#F6EBDD", "role": "Background"},
    {"name": "Roast Red", "hex": "#B5452B", "role": "Secondary accent"},
    {"name": "Sage", "hex": "#5C7A5E", "role": "Supporting"},
]

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
            {"term": "Wake up slowly", "translate": True, "translations": {"de": "Wach langsam auf", "fr": "Réveillez-vous lentement", "pl": "Obudź się powoli", "es": "Despierta despacio", "it": "Svegliati piano", "pt": "Acorde devagar", "nl": "Word rustig wakker"}},
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
}

DISCLAIMER_CAFFEINE = "Contains caffeine. Not recommended for children or pregnant women."


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


def campaigns() -> list[dict[str, Any]]:
    return [
        {
            "id": "dawn-roast-launch",
            "campaign_id": "dawn-roast-launch",
            "name": "Dawn Roast — Launch (US · DE · FR · PL)",
            "brand_id": BRAND_ID,
            "status": "draft",
            "stage": "brief",
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
