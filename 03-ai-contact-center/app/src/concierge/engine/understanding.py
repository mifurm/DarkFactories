"""Intent / entity / sentiment / urgency / risk-flag understanding (CC-06). Deterministic multilingual rules (en, de, fr, es, it, nl, pl, sv, pt)
are the always-on baseline; the LLM refines them in azure mode (see orchestrator.llm_understanding)."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from ..core.langid import detect_language
from .models import Understanding

_I = re.IGNORECASE


def fold(text: str) -> str:
    """Lower-case and strip accents so 'beschädigt' == 'beschadigt' style variants still match."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _rx(*phrases: str) -> re.Pattern[str]:
    return re.compile("|".join(fold(p) for p in phrases), _I)


INTENT_RX: dict[str, re.Pattern[str]] = {
    "damaged_item": _rx(r"damag", r"broken", r"cracked", r"scratch", r"dented", r"defectiv", r"arrived (?:broken|damaged)", r"beschadig", r"kaputt", r"defekt", r"zerkratzt", r"gebrochen", r"transportschaden", r"\bschaden\b", r"endommag", r"\bcasse", r"abime", r"rayure", r"danad", r"\broto\b", r"rota\b", r"rayad", r"danneggiat", r"\brott[oa]\b", r"graffiat", r"kapot", r"uszkodzon", r"zepsut", r"wadliw", r"skadad", r"trasig", r"danificad", r"avariad"),
    "return_request": _rx(r"\breturn", r"send (?:it )?back", r"take (?:it )?back", r"exchange", r"replacement", r"replace", r"zuruck(?:geben|senden|schicken)", r"ruckgabe", r"umtausch", r"\bersatz", r"retoure", r"retourner", r"\bretour\b", r"echange", r"remplacement", r"devolver", r"devolucion", r"cambiar", r"reemplazo", r"restituire", r"\breso\b", r"sostituzione", r"retourneren", r"terugsturen", r"omruilen", r"\bzwrot\b", r"zwrocic", r"wymian", r"returnera", r"\bbyte\b"),
    "refund_status": _rx(r"refund", r"money back", r"reimburse", r"erstattung", r"ruckerstattung", r"geld zuruck", r"ruckzahlung", r"remboursement", r"rembourser", r"reembolso", r"rimborso", r"terugbetaling", r"restitutie", r"zwrot pieni", r"refundac", r"aterbetalning", r"pengarna tillbaka"),
    "order_status": _rx(r"where is my (?:order|parcel|delivery|package)", r"\btrack", r"order status", r"delivery status", r"when will .{0,30}(?:arrive|be delivered)", r"shipment", r"parcel", r"wo ist meine bestellung", r"sendungsverfolgung", r"lieferstatus", r"wann kommt", r"\bpaket\b", r"ou est ma commande", r"\bsuivi\b", r"livraison prevue", r"donde esta mi pedido", r"seguimiento", r"estado del pedido", r"dov'e il mio ordine", r"tracciamento", r"stato dell'ordine", r"waar is mijn bestelling", r"gdzie jest moje zamowienie", r"var ar min bestallning", r"spara"),
    "delivery_change": _rx(r"re-?schedule", r"re-?book", r"change (?:the )?(?:delivery (?:date|slot|time|appointment|day)|appointment|date|slot)", r"different (?:day|date|time)", r"postpone", r"termin verschieben", r"neuer liefertermin", r"lieferung verschieben", r"umbuchen", r"neuen termin", r"reporter la livraison", r"changer la date", r"reprogrammer", r"reprogramar", r"cambiar la fecha", r"riprogrammare", r"verplaatsen", r"andere datum", r"przelozyc", r"zmienic termin", r"boka om", r"andra leveransen"),
    "address_change": _rx(r"(?:change|update|wrong|new) (?:my |the |delivery )?address", r"moved (?:house|flat)", r"adresse (?:andern|aendern)", r"neue adresse", r"falsche adresse", r"umgezogen", r"changer l'adresse", r"nouvelle adresse", r"cambiar la direccion", r"nueva direccion", r"cambiare indirizzo", r"adres wijzigen", r"zmiana adresu", r"andra adress"),
    "warranty_claim": _rx(r"warranty", r"guarantee claim", r"stopped working", r"\brepair", r"garantie", r"gewahrleistung", r"reparatur", r"funktioniert nicht mehr", r"reparation", r"garantia", r"reparacion", r"garanzia", r"riparazione", r"reparatie", r"gwarancj", r"naprawa", r"garanti\b"),
    "cancel_order": _rx(r"cancel (?:my |the )?order", r"cancellation", r"stornier", r"bestellung stornieren", r"annuler", r"annulation", r"cancelar", r"cancelacion", r"annullare", r"annuleren", r"anulowac", r"avbestall"),
    "goodwill_request": _rx(r"compensat", r"goodwill", r"voucher", r"discount for", r"entschadigung", r"kulanz", r"gutschein", r"wiedergutmachung", r"dedommagement", r"geste commercial", r"compensacion", r"risarcimento", r"indennizzo", r"compensatie", r"odszkodowanie", r"rekompensata", r"kompensation"),
    "billing_question": _rx(r"invoice", r"\bbill\b", r"charged twice", r"double charge", r"payment", r"rechnung", r"abgebucht", r"doppelt belastet", r"zahlung", r"facture", r"preleve", r"paiement", r"factura", r"\bcobro", r"fattura", r"addebito", r"pagamento", r"factuur", r"betaling", r"faktura", r"platnosc", r"betalning"),
    "installation_info": _rx(r"install", r"assembl", r"assembly", r"\bmontage\b", r"aufbau", r"montaz", r"instalacion", r"montaje", r"installazione", r"montaggio", r"installatie"),
    "privacy_request": _rx(r"gdpr", r"delete my (?:data|account)", r"my personal data", r"data protection", r"datenschutz", r"meine daten loschen", r"dsgvo", r"rgpd", r"supprimer mes donnees", r"borrar mis datos"),
    "complaint": _rx(r"complain", r"unacceptable", r"terrible service", r"worst", r"disgust", r"furious", r"beschwerde", r"unzumutbar", r"inakzeptabel", r"frechheit", r"katastrophe", r"unverschamt", r"reclamation", r"inacceptable", r"scandaleux", r"\bqueja\b", r"inaceptable", r"vergonzoso", r"reclamo", r"klacht", r"skarga", r"klagomal"),
    "policy_question": _rx(r"\bpolicy\b", r"how long (?:do|can|is|have)", r"do you (?:accept|offer|have)", r"what(?:'s| is) (?:the|your)", r"can i (?:return|exchange|cancel|change)", r"am i (?:eligible|entitled)", r"conditions", r"terms", r"wie lange", r"richtlinie", r"bedingungen", r"kann ich .{0,25}(?:zuruck|umtausch|stornier)", r"quelle est", r"combien de temps", r"cuanto tiempo", r"quanto tempo", r"hoe lang", r"jak dlugo", r"hur lange"),
    "product_info": _rx(r"dimension", r"specs?\b", r"does it come with", r"colou?r", r"available in", r"material", r"abmessung", r"farbe", r"erhaltlich", r"mesure", r"couleur", r"medidas", r"colore"),
    "greeting": _rx(r"^(?:hi|hello|hey|good (?:morning|afternoon|evening))\b", r"^(?:hallo|guten (?:tag|morgen|abend)|moin|servus)\b", r"^(?:bonjour|salut|bonsoir)\b", r"^(?:hola|buenos dias|buenas)\b", r"^(?:ciao|buongiorno)\b", r"^(?:hej|goddag)\b", r"^(?:dzien dobry|czesc)\b", r"^goedendag\b"),
    "goodbye": _rx(r"\bbye\b", r"that(?:'s| is) all", r"nothing else", r"no,? thanks", r"that(?:'s| is) it\b", r"tschuss", r"auf wiedersehen", r"das war's", r"mehr nicht", r"nein,? danke", r"au revoir", r"c'est tout", r"adios", r"eso es todo", r"nada mas", r"arrivederci", r"doei", r"do widzenia", r"hej da"),
}
INTENT_ORDER = ["damaged_item", "refund_status", "address_change", "return_request", "delivery_change", "warranty_claim", "cancel_order", "goodwill_request", "order_status", "installation_info", "billing_question", "privacy_request", "complaint", "policy_question", "product_info", "goodbye", "greeting"]
ACCOUNT_INTENTS = {"damaged_item", "refund_status", "return_request", "delivery_change", "address_change", "warranty_claim", "cancel_order", "goodwill_request", "order_status", "billing_question"}

RISK_RX: dict[str, re.Pattern[str]] = {
    "legal_threat": _rx(r"lawyer", r"solicitor", r"attorney", r"\bsue\b", r"suing", r"legal (?:action|steps|proceedings)", r"\bcourt\b", r"trading standards", r"consumer (?:protection|authority|ombudsman)", r"anwalt", r"rechtsanwalt", r"\bklage\b", r"verklag", r"rechtliche schritte", r"\bgericht\b", r"verbraucherzentrale", r"avocat", r"tribunal", r"poursuite", r"action en justice", r"abogado", r"demanda", r"acciones legales", r"avvocato", r"\bcausa\b", r"azione legale", r"advocaat", r"rechtszaak", r"prawnik", r"adwokat", r"pozew", r"advokat", r"stamma", r"domstol"),
    "vulnerable_customer": _rx(r"\bvulnerable\b", r"elderly", r"pensioner", r"disabled", r"disability", r"wheelchair", r"i am (?:blind|deaf)", r"mental health", r"bereave", r"my (?:husband|wife|mother|father) (?:has )?(?:just )?(?:died|passed)", r"can't cope", r"cannot cope", r"\bcarer\b", r"in hospital", r"i am (?:7\d|8\d|9\d) years", r"schwerbehindert", r"rollstuhl", r"\bblind\b", r"\btaub\b", r"pflegebedurftig", r"rentner", r"trauerfall", r"verstorben", r"uberfordert", r"ich bin (?:7\d|8\d|9\d) jahre", r"handicape", r"personne agee", r"deuil", r"discapacitad", r"anciano", r"luto", r"disabile", r"anziano", r"gehandicapt", r"\bziek\b", r"\bkrank\b", r"overlijden", r"niepelnosprawn", r"zaloba", r"funktionsnedsattning"),
    "fraud_suspected": _rx(r"\bfraud", r"\bscam", r"unauthori[sz]ed", r"did not order", r"didn't order", r"stolen card", r"hacked", r"someone (?:used|opened) my account", r"betrug", r"nicht autorisiert", r"nicht bestellt", r"gestohlen", r"gehackt", r"fraude", r"arnaque", r"pirate", r"estafa", r"no autorizado", r"hackead", r"truffa", r"oplichting", r"oszust"),
    "safety_issue": _rx(r"smell(?:s|ing)? (?:of )?gas", r"gas leak", r"\bsmoke\b", r"\bfire\b", r"sparks?", r"electric shock", r"burning smell", r"overheat", r"carbon monoxide", r"injur", r"gasgeruch", r"\brauch\b", r"\bfeuer\b", r"funken", r"stromschlag", r"brandgeruch", r"uberhitzt", r"verletzt", r"odeur de gaz", r"fumee", r"incendie", r"etincelles", r"choc electrique", r"olor a gas", r"humo", r"incendio", r"chispas", r"herido"),
    "regulatory_complaint": _rx(r"ombudsman", r"regulator", r"data protection authority", r"datenschutzbehorde", r"schlichtungsstelle", r"cnil", r"aepd"),
    "churn_risk": _rx(r"cancel (?:my )?(?:membership|loyalty|account)", r"never (?:buy|order|shop) (?:from you|here) again", r"switch(?:ing)? to", r"last time", r"nie wieder", r"kundigen", r"werde woanders", r"plus jamais", r"jamas volvere", r"mai piu"),
}
SELF_HARM_RX = _rx(r"kill myself", r"end my life", r"suicid", r"hurt myself", r"mich umbringen", r"selbstmord")

NEG_WORDS: dict[str, float] = {}
for _w, _v in {
    "furious": 1.2, "angry": 1.0, "terrible": 0.9, "awful": 0.9, "unacceptable": 1.0, "ridiculous": 0.9, "disgusting": 1.0, "useless": 0.9, "worst": 1.0,
    "hate": 0.9, "annoyed": 0.6, "frustrat": 0.8, "disappointed": 0.7, "again": 0.35, "still": 0.3, "never": 0.35, "third time": 0.8, "waiting": 0.3,
    "unhappy": 0.7, "not happy": 0.7, "joke": 0.6, "rubbish": 0.7, "incompetent": 0.9, "liar": 1.0, "lied": 0.9, "scam": 0.9, "outrageous": 1.0, "damaged": 0.35,
    "wutend": 1.1, "sauer": 0.7, "verargert": 0.8, "unverschamt": 1.0, "frechheit": 1.0, "katastrophe": 0.9, "schlecht": 0.6, "enttauscht": 0.7, "inakzeptabel": 1.0,
    "nervt": 0.6, "genervt": 0.6, "schon wieder": 0.5, "immer noch": 0.4, "furchtbar": 0.9, "schrecklich": 0.9, "lacherlich": 0.9, "zum kotzen": 1.0, "unzumutbar": 1.0, "nie wieder": 0.9,
    "furieux": 1.1, "inacceptable": 1.0, "scandaleux": 1.0, "nul": 0.7, "decu": 0.7, "encore": 0.3, "toujours pas": 0.5, "honteux": 0.9,
    "furioso": 1.1, "inaceptable": 1.0, "vergonzoso": 1.0, "horrible": 0.9, "decepcionado": 0.7, "otra vez": 0.4, "todavia": 0.25, "indignante": 1.0,
    "furioso ": 1.1, "inaccettabile": 1.0, "vergognoso": 1.0, "orribile": 0.9, "deluso": 0.7, "ancora": 0.25,
    "boos": 0.8, "onacceptabel": 1.0, "schandalig": 1.0, "teleurgesteld": 0.7, "weer": 0.3,
    "wsciekly": 1.0, "nie do przyjecia": 1.0, "skandal": 1.0, "rozczarowany": 0.7, "znowu": 0.4,
    "arg": 0.9, "oacceptabelt": 1.0, "skandal ": 1.0, "besviken": 0.7, "igen": 0.3,
}.items():
    NEG_WORDS[fold(_w)] = _v
NEG_PATTERNS = [(re.compile(rf"\b{re.escape(k)}\b" if len(k) <= 4 else rf"\b{re.escape(k)}"), v) for k, v in NEG_WORDS.items()]
POS_WORDS: dict[str, float] = {fold(k): v for k, v in {
    "thank": 0.5, "thanks": 0.5, "great": 0.6, "perfect": 0.7, "helpful": 0.6, "appreciate": 0.6, "happy": 0.6, "wonderful": 0.7, "excellent": 0.8, "awesome": 0.7, "good": 0.35, "love": 0.6, "brilliant": 0.7,
    "danke": 0.5, "super": 0.6, "toll": 0.6, "perfekt": 0.7, "prima": 0.6, "zufrieden": 0.6, "freundlich": 0.5, "hilfreich": 0.6, "vielen dank": 0.7, "klasse": 0.6,
    "merci": 0.5, "parfait": 0.7, "genial": 0.7, "gracias": 0.5, "perfecto": 0.7, "genial ": 0.7, "grazie": 0.5, "perfetto": 0.7, "bedankt": 0.5, "dziekuje": 0.5, "dzieki": 0.5, "tack": 0.5,
}.items()}
STRONG_PROFANITY = re.compile(r"\b(fuck\w*|shit\w*|bastard|asshole|moron\w*|scheis\w*|arschloch|merde|connard|putain|mierda|cabron|cazzo|stronzo)\b", _I)
URGENT_RX = _rx(r"urgent", r"immediately", r"emergency", r"asap", r"right now", r"dringend", r"sofort", r"urgence", r"immediatement", r"urgente", r"subito")

POSSESSIVE = re.compile(r"\b(my|mein|meine|meinen|meinem|meiner|mon|ma|mes|mi|mis|mio|mia|mijn|moj|moja|moje|min|mitt)\b")
ORDER_ID = re.compile(r"\b([A-Z]{2}-\d{5,7})\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
AMOUNT = re.compile(r"(?:€|eur(?:o)?\s?)\s?(\d{1,6}(?:[.,]\d{1,2})?)|(\d{1,6}(?:[.,]\d{1,2})?)\s?(?:€|eur\b|euro)", _I)
OTP_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
POSTAL = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")
PRODUCTS = {
    "sofa": r"sofa|couch|settee|sectional", "mattress": r"mattress|matratze|colchon|matelas|materasso", "washing machine": r"washing machine|waschmaschine|lave-linge|lavadora|lavatrice",
    "dishwasher": r"dishwasher|spulmaschine|lave-vaisselle|lavavajillas|lavastoviglie", "fridge": r"fridge|refrigerator|kuhlschrank|frigo|nevera|frigorifero",
    "table": r"\btable\b|\btisch\b|\bmesa\b|\btavolo\b", "chair": r"\bchair\b|\bstuhl\b|\bsilla\b|\bchaise\b|\bsedia\b", "wardrobe": r"wardrobe|kleiderschrank|\bschrank\b|armoire|armario|guardaroba",
    "bed": r"\bbed\b|\bbett\b|\blit\b|\bcama\b|\bletto\b", "lamp": r"\blamp\b|\blampe\b|\blampara\b|\blampada\b", "desk": r"\bdesk\b|schreibtisch|bureau|escritorio|scrivania", "blender": r"blender|mixer|standmixer",
    "oven": r"\boven\b|backofen|\bfour\b|\bhorno\b|\bforno\b",
}
NEW_ADDRESS = re.compile(r"([A-Za-zÀ-ÿ][\wÀ-ÿ. -]{2,40}?\s\d{1,4}\w?),?\s+(\d{4}-\d{3}|\d{4,5}|\d{3} \d{2})\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ -]{1,30})")
CARRIERS = {"nordfreight": "NordFreight", "swifthaul": "SwiftHaul", "blueroute": "BlueRoute"}


def extract_entities(text: str) -> dict[str, Any]:
    ents: dict[str, Any] = {}
    if m := ORDER_ID.search(text):
        ents["order_id"] = m.group(1).upper()
    if m := EMAIL.search(text):
        ents["email_present"] = True
    if m := AMOUNT.search(text):
        ents["amount"] = float((m.group(1) or m.group(2)).replace(",", "."))
    folded = fold(text)
    for prod, rx in PRODUCTS.items():
        if re.search(fold(rx), folded):
            ents["product"] = prod
            break
    for key, name in CARRIERS.items():
        if key in folded:
            ents["carrier"] = name
    if m := OTP_CODE.search(text):
        ents["code"] = m.group(1)
    if m := NEW_ADDRESS.search(text):
        ents["new_address"] = {"street": m.group(1).strip(" ,"), "postal_code": m.group(2), "city": m.group(3).strip(" .")}
    return ents


def _sentiment(text: str, lang: str) -> tuple[float, str]:
    folded = fold(text)
    neg = sum(w for rx, w in NEG_PATTERNS if rx.search(folded))
    pos = sum(w for k, w in POS_WORDS.items() if re.search(rf"\b{re.escape(k)}", folded))
    letters = [c for c in text if c.isalpha()]
    caps = (sum(1 for c in letters if c.isupper()) / len(letters)) if len(letters) > 12 else 0.0
    if caps > 0.55:
        neg += 0.8
    neg += min(text.count("!"), 4) * 0.12
    profane = bool(STRONG_PROFANITY.search(folded))
    if profane:
        neg += 1.2
    negated = bool(re.search(r"\b(not|n't|kein|nicht|pas|no)\b.{0,12}\b(happy|satisfied|zufrieden|content|contento)", folded))
    if negated:
        neg += 0.7
        pos = max(pos - 0.6, 0)
    score = math.tanh(pos * 0.9 - neg * 0.95)
    emotion = "neutral"
    if score <= -0.55 or profane:
        emotion = "angry"
    elif score <= -0.2:
        emotion = "frustrated"
    elif score >= 0.35:
        emotion = "satisfied"
    elif re.search(r"worried|afraid|anxious|besorgt|angst|inquiet|preocupad|preoccupat", folded):
        emotion = "anxious"
    return round(score, 3), emotion


def analyze(text: str, *, lang_hint: str | None = None, prior: Understanding | None = None) -> Understanding:
    """Rule-based understanding for one customer message."""
    folded = fold(text.strip())
    lang, conf = detect_language(text, default=lang_hint or (prior.language if prior else "en"))
    if conf < 0.45 and lang_hint:
        lang = lang_hint
    scores = {i: len(INTENT_RX[i].findall(folded)) for i in INTENT_ORDER}
    hits = [i for i in INTENT_ORDER if scores[i] > 0]
    intent = hits[0] if hits else "other"
    if "policy_question" in hits and intent in ACCOUNT_INTENTS and not ORDER_ID.search(text) and not POSSESSIVE.search(folded):
        intent = "policy_question"  # a general question about rules, not a request about the customer's own order
    if intent in ("greeting", "goodbye") and len(hits) > 1:
        intent = hits[1]
    if intent == "greeting" and len(text.split()) > 6:
        rest = [h for h in hits if h != "greeting"]
        intent = rest[0] if rest else intent
    ents = extract_entities(text)
    risks = [name for name, rx in RISK_RX.items() if rx.search(folded)]
    if SELF_HARM_RX.search(folded):
        risks.append("welfare_concern")
    if ents.get("order_id") is None and prior and prior.entities.get("order_id"):
        ents["order_id"] = prior.entities["order_id"]
    sentiment, emotion = _sentiment(text, lang)
    if "legal_threat" in risks and sentiment > -0.45:
        sentiment = -0.45
        emotion = "angry"
    urgency = "normal"
    if "safety_issue" in risks or "welfare_concern" in risks or URGENT_RX.search(folded):
        urgency = "critical" if "safety_issue" in risks or "welfare_concern" in risks else "high"
    elif (risks and any(r in risks for r in ("legal_threat", "vulnerable_customer", "fraud_suspected"))) or sentiment <= -0.6:
        urgency = "high"
    elif intent in ("greeting", "goodbye", "product_info", "policy_question"):
        urgency = "low"
    if intent == "other" and "legal_threat" in risks:
        intent = "complaint"
    return Understanding(
        intent=intent,
        secondary=[h for h in hits if h != intent][:3],
        entities=ents,
        sentiment=sentiment,
        emotion=emotion,
        urgency=urgency,
        risk_flags=sorted(set(risks)),
        language=lang,
        confidence=round(min(0.95, 0.5 + 0.15 * scores.get(intent, 0) + (0.1 if ents else 0)), 2) if intent != "other" else 0.35,
        source="rules",
    )


AFFIRM_RX = _rx(r"^(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please do|go ahead|proceed|confirm(?:ed)?|that(?:'s| is) fine|sounds good|do it|correct|alright|absolutely|of course)\b", r"^(?:ja|jawohl|gerne|bitte|klar|einverstanden|mach das|passt|in ordnung|genau|stimmt|na klar)\b", r"^(?:oui|d'accord|volontiers|allez-y|c'est bon|parfait)\b", r"^(?:si|vale|de acuerdo|adelante|claro|por favor)\b", r"^(?:va bene|certo|procedi|d'accordo)\b", r"^(?:akkoord|graag|doe maar|prima)\b", r"^(?:tak|dobrze|zgoda|jasne)\b", r"^(?:okej|visst|kor pa)\b", r"\bplease (?:proceed|go ahead|do that|refund)", r"\bja,? bitte\b", r"\bja,? gerne\b", r"\bja,? erstatt")
NEGATE_RX = _rx(r"^(?:no|nope|nah)\b", r"\bdon't\b", r"\bdo not\b", r"\bcancel\b", r"\bstop\b", r"\bnot now\b", r"^(?:nein|nee|lieber nicht)\b", r"\babbrechen\b", r"\bnicht\b", r"^(?:non|pas)\b", r"^(?:nada)\b", r"^(?:nie|nej)\b", r"\bwait\b", r"\bhold on\b")


def is_affirmative(text: str) -> bool:
    f = fold(text.strip())
    if not f or NEGATE_RX.search(f):
        return False
    if len(f.split()) > 12 and re.search(r"\b(but|however|aber|mais|pero|ma|maar|ale|men)\b", f):
        return False
    return bool(AFFIRM_RX.search(f))


def is_negative(text: str) -> bool:
    return bool(NEGATE_RX.search(fold(text.strip())))


def similar(a: str, b: str) -> float:
    ta, tb = set(fold(a).split()), set(fold(b).split())
    return len(ta & tb) / max(len(ta | tb), 1)


# ---------------------------------------------------------------- Portuguese (PT market) additions
def _extend(rx: re.Pattern[str], *phrases: str) -> re.Pattern[str]:
    return re.compile(rx.pattern + "|" + "|".join(fold(p) for p in phrases), _I)


_PT_INTENTS: dict[str, tuple[str, ...]] = {
    "damaged_item": (r"danificad", r"estragad", r"\bpartid[oa]", r"avariad", r"riscad", r"defeituos", r"chegou (?:partid|danific|estrag)"),
    "return_request": (r"devolver", r"devoluc", r"enviar de volta", r"\btroca\b", r"\btrocar\b", r"substituic"),
    "refund_status": (r"reembols", r"dinheiro de volta", r"restituic"),
    "order_status": (r"onde esta (?:a minha|o meu)", r"rastre", r"estado da (?:encomenda|entrega)", r"quando (?:chega|vai chegar|e entregue)", r"acompanhar a encomenda"),
    "delivery_change": (r"reagendar", r"remarcar", r"alterar a data de entrega", r"mudar a entrega", r"adiar a entrega", r"outro dia"),
    "address_change": (r"(?:alterar|mudar|atualizar) a morada", r"nova morada", r"morada errada", r"mudei de casa"),
    "warranty_claim": (r"garantia", r"reparacao", r"deixou de funcionar", r"\bavariou"),
    "cancel_order": (r"cancelar (?:a |o )?(?:minha |meu )?(?:encomenda|pedido)", r"cancelamento"),
    "goodwill_request": (r"compensac", r"vale de desconto", r"gesto comercial", r"indemniza"),
    "billing_question": (r"\bfatura", r"\bcobrad", r"\bcobranca", r"pagamento", r"debitado duas vezes"),
    "installation_info": (r"instalac", r"montagem", r"\bmontar\b"),
    "complaint": (r"reclamac", r"inaceitavel", r"vergonh", r"pessimo servico", r"indignad"),
    "policy_question": (r"qual e a politica", r"quanto tempo", r"posso devolver", r"tenho direito", r"condicoes"),
    "greeting": (r"^(?:ola|bom dia|boa tarde|boa noite)\b",),
    "goodbye": (r"\badeus\b", r"e tudo\b", r"so isso", r"nao,? obrigad", r"ate logo"),
}
for _k, _ph in _PT_INTENTS.items():
    INTENT_RX[_k] = _extend(INTENT_RX[_k], *_ph)
_PT_RISKS: dict[str, tuple[str, ...]] = {
    "legal_threat": (r"advogado", r"tribunal", r"acao judicial", r"processar", r"\bdeco\b", r"direitos do consumidor"),
    "vulnerable_customer": (r"\bidos[oa]\b", r"cadeira de rodas", r"deficiente", r"faleceu", r"em luto", r"\bsozinh[oa]\b e doente"),
    "fraud_suspected": (r"fraude", r"\bburla", r"nao autorizad", r"nao encomendei", r"cartao roubado", r"conta pirateada"),
    "safety_issue": (r"cheiro a gas", r"fuga de gas", r"\bfumo\b", r"incendio", r"faiscas", r"choque eletrico", r"cheiro a queimado"),
    "regulatory_complaint": (r"livro de reclamacoes", r"provedor", r"entidade reguladora", r"\basae\b", r"\bcnpd\b"),
}
for _k, _ph in _PT_RISKS.items():
    RISK_RX[_k] = _extend(RISK_RX[_k], *_ph)
for _w, _v in {"inaceitavel": 1.0, "vergonhoso": 1.0, "pessimo": 0.9, "horrivel": 0.9, "desiludido": 0.7, "outra vez": 0.4, "ainda nao": 0.4, "ridiculo": 0.9, "indignado": 1.0, "revoltante": 1.0, "zangado": 0.8, "irritado": 0.8, "incompetentes": 0.9, "nunca mais": 0.9}.items():
    NEG_PATTERNS.append((re.compile(rf"\b{re.escape(fold(_w))}\b" if len(_w) <= 4 else rf"\b{re.escape(fold(_w))}"), _v))
POS_WORDS.update({"obrigado": 0.5, "obrigada": 0.5, "perfeito": 0.7, "excelente": 0.8, "otimo": 0.6, "muito bom": 0.6})
STRONG_PROFANITY = _extend(STRONG_PROFANITY, r"merda", r"caralho", r"idiota")
URGENT_RX = _extend(URGENT_RX, r"imediatamente", r"agora mesmo")
POSSESSIVE = re.compile(POSSESSIVE.pattern.replace("|mitt)", "|mitt|meu|minha|meus|minhas)"))
AFFIRM_RX = _extend(AFFIRM_RX, r"^(?:sim|claro|pode ser|combinado|esta bem|com certeza|avance|pode avancar|por favor)\b")
NEGATE_RX = _extend(NEGATE_RX, r"^(?:nao)\b", r"\bcancelar\b")

# ---------------------------------------------------------------- additional coverage found by the multilingual evaluation (CC-19)
_MORE_INTENTS: dict[str, tuple[str, ...]] = {
    "delivery_change": (r"verschieb", r"przełoż", r"przesun"),
    "address_change": (r"cambiar la direccion", r"cambiare l'?indirizzo", r"indirizzo di consegna", r"zmieni\w* adres", r"nowy adres", r"nouvelle adresse", r"nieuw adres", r"afleveradres"),
}
for _k, _ph in _MORE_INTENTS.items():
    INTENT_RX[_k] = _extend(INTENT_RX[_k], *_ph)
