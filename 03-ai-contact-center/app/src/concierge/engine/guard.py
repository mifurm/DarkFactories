"""Compliance & risk guard (CC-11): PII/PCI redaction, prompt-injection defences, toxicity, risky promises,
disclosure checks. Deterministic rules always run; Azure AI Language / Content Safety (Prompt Shields) enrich when available."""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..core.ai.base import CognitiveClient
from ..core.i18n import nbsp_pl
from ..core.redaction import Redaction, redact
from ..core.textutil import fold
from .lexicon_pl import MASKED_PROFANITY

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)


def normalize(text: str) -> str:
    """NFKC fold + strip zero-width characters so obfuscated attacks are matched."""
    return unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)


_I = re.IGNORECASE
_DX = {"ą": "[ąa]", "ć": "[ćc]", "ę": "[ęe]", "ł": "[łl]", "ń": "[ńn]", "ó": "[óo]", "ś": "[śs]", "ź": "[źz]", "ż": "[żz]"}


def dx(pattern: str) -> str:
    """Make a Polish pattern diacritic-insensitive (`ł`→`[łl]`, ...): customers often type Polish on phones without diacritics."""
    return "".join(_DX.get(c, c) for c in pattern)


_QUAL_PL = r"(?:poprzedni\w*|wcześniejsz\w*|powyższ\w*|dotychczasow\w*|wszystk\w*|wszelk\w*|swoj\w*|swoi\w*|swój|twoj\w*|twoi\w*|twój|wasz\w*|systemow\w*|pierwotn\w*|początkow\w*|obecn\w*|aktualn\w*|obowiązując\w*|ukryt\w*|wewnętrzn\w*|te|previous|prior|above|earlier|all|any|your|the|system)"
_RULE_NOUN_PL = r"(?:instrukcj\w*|zasad\w*|polecen\w*|reguł\w*|wytyczn\w*|ograniczeni\w*|zabezpieczeni\w*|restrykcj\w*|promp\w*|programowani\w*|filtr\w*|dyrektyw\w*|instructions?|rules?|prompts?|polic(?:y|ies)|guidelines?|restrictions?)"
_OVERRIDE_VERB_PL = r"(?:z?ignoruj\w*|z?ignorować|pomiń\w*|pomin\w*|pomijaj\w*|odrzuć|odrzuc\w*|zapomnij\w*|zapomnieć|obejdź|obejdz\w*|nie\s+zwracaj\s+uwagi\s+na|nie\s+stosuj\s+się\s+do|nie\s+przestrzegaj|przestań\s+przestrzegać)"
_REVEAL_VERB_PL = r"(?:pokaż|pokaz\w*|ujawnij\w*|wypisz\w*|powtórz\w*|podaj\w*|wyświetl\w*|zdradź\w*|wydrukuj\w*|zacytuj\w*|cytuj\w*|przepisz\w*|wklej\w*|odtwórz\w*|przeczytaj\w*|wyjaw\w*|jak(?:ie|i|a)\s+(?:masz|są|jest|otrzymał\w*)|co\s+(?:jest\s+w|zawiera|masz\s+w))"
_REVEAL_QUAL_PL = r"(?:systemow\w*|ukryt\w*|wewnętrzn\w*|początkow\w*|pierwotn\w*|swój|swoj\w*|swoi\w*|twój|twoj\w*|twoi\w*|pełn\w*|system|deweloper\w*|developer\w*)"

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the|system)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|polic(?:y|ies)|guidelines?|restrictions?)\b", _I)),
    ("override_instructions_de", re.compile(r"\b(ignorier\w*|vergiss\w*|missachte\w*|umgehe\w*)\b[^.\n]{0,40}\b(anweisung\w*|regel\w*|instruktion\w*|richtlinie\w*|vorgabe\w*)\b", _I)),
    ("override_instructions_fr_es_it", re.compile(r"\b(ignore\w*|oublie\w*|ignora\w*|olvida\w*|dimentica\w*)\b[^.\n]{0,40}\b(instructions?|instrucciones|istruzioni|consignes|règles|reglas|regole)\b", _I)),
    # a Polish verb + (Polish or English) object: "Ignoruj poprzednie instrukcje", "Zapomnij o swoich zasadach", "zapomnij o all previous instructions"
    ("override_instructions_pl", re.compile(dx(rf"\b{_OVERRIDE_VERB_PL}\b[^.\n]{{0,40}}\b{_QUAL_PL}\b[^.\n]{{0,30}}\b{_RULE_NOUN_PL}\b"), _I)),
    # the bare imperative with the object right behind it: "Ignoruj instrukcje", "Zapomnij zasady"
    ("override_instructions_bare_pl", re.compile(dx(r"\b(?:z?ignoruj\w*|z?ignorować|zapomnij\w*|zapomnieć|pomiń|pomijaj\w*|odrzuć)\s+(?:o\s+|na\s+temat\s+)?(?:instrukcj\w*|zasad\w*|polecen\w*|reguł\w*|wytyczn\w*|ograniczeni\w*|zabezpieczeni\w*|restrykcj\w*|promp\w*|instructions?|rules?|prompts?|guidelines?|restrictions?)\b"), _I)),
    # an English verb + a Polish object ("ignore poprzednie instrukcje", "forget swoje zasady"): needs a Polish noun, so pure English text cannot match it
    ("override_instructions_mixed_pl", re.compile(dx(rf"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{{0,40}}\b{_QUAL_PL}\b[^.\n]{{0,30}}\b(?:instrukcj\w*|zasad\w*|polecen\w*|reguł\w*|wytyczn\w*|ograniczeni\w*|zabezpieczeni\w*)\b"), _I)),
    ("reveal_prompt_pl", re.compile(dx(rf"\b{_REVEAL_VERB_PL}\b[^.\n]{{0,40}}\b{_REVEAL_QUAL_PL}\b[^.\n]{{0,20}}\b(?:promp\w*|instrukcj\w*|polecen\w*)\b"), _I)),
    # the qualifier behind the noun ("instrukcje systemowe") and the system rules (a customer's "wasze zasady zwrotów" is a policy question, never this)
    ("reveal_prompt_pl_2", re.compile(dx(rf"\b{_REVEAL_VERB_PL}\b[^.\n]{{0,40}}\b(?:(?:promp|instrukcj|polecen|zasad)\w*\s+(?:systemow|ukryt|wewnętrzn|początkow|pierwotn)\w*|(?:systemow|ukryt|wewnętrzn|początkow|pierwotn)\w*\s+(?:\w+\s+)?zasad\w*|system\s*promp\w*)"), _I)),
    ("role_hijack_pl", re.compile(dx(r"\b(jesteś\s+teraz|teraz\s+jesteś|od\s+(?:teraz|dziś|dzisiaj|tej\s+chwili)\s+(?:jesteś|będziesz|musisz|działasz|zachowujesz\s+się)|(?<!nie\s)udawaj\w*|wciel\s+się|wejdź\s+w\s+rolę|odgrywaj\w*|zagraj\s+(?:rolę|role)|zachowuj\s+się\s+jak|działaj\s+jako|bądź\s+teraz)\b[^.\n]{0,60}"), _I)),
    ("jailbreak_terms_pl", re.compile(dx(r"\b(?:tryb\w*|w\s+trybie)\s+(?:deweloperski\w*|dewelopera|develop\w*|admin\w*|administrator\w*|programisty|boga|bez\s+ogranicze\w*|nieograniczon\w*|jailbreak\w*|dan\b|debug\w*|root\b|sudo\b)"), _I)),
    ("tool_invocation_text_pl", re.compile(dx(r"\b(wywołaj|uruchom|wykonaj|użyj)\b[^.\n]{0,25}\b(issue_refund|goodwill_credit|update_address|initiate_return|escalate|lookup_order|create_ticket)\b"), _I)),
    ("exfiltration_pl", re.compile(dx(r"\b(wyślij|prześlij|przekaż\w*|wyeksportuj)\b[^.\n]{0,50}\b(dane\s+klientów|dane\s+wszystkich|wszystkie\s+(?:zamówienia|dane)|bazę\s+danych|hasła|klucze|tokeny|poświadczenia)\b"), _I)),
    ("approve_override_pl", re.compile(dx(r"\b(zwrot\w*|zwróć|kredyt\w*|rekompensat\w+|odszkodowani\w+)\b[^.\n]{0,70}\b(bez)\b[^.\n]{0,25}\b(zatwierdzeni\w+|weryfikacj\w+|potwierdzeni\w+|sprawdzeń|limit\w*)\b"), _I)),
    ("bypass_controls_pl", re.compile(dx(r"\b(pomiń|pomin\w*|obejdź|zignoruj\w*|wyłącz)\b[^.\n]{0,25}\b(weryfikacj\w+|limit\w*|zatwierdzeni\w+|sprawdzeni\w+|potwierdzeni\w+|zabezpieczeni\w+)\b"), _I)),
    ("reveal_prompt", re.compile(r"\b(reveal|show|print|repeat|output|leak|tell me|display|verrate|zeige|nenne)\b[^.\n]{0,40}\b(system|hidden|internal|initial|developer)\b[^.\n]{0,20}\b(prompt|instructions?|message|anweisung\w*)\b", _I)),
    ("role_hijack", re.compile(r"\b(you are now (?:a|an|the|in|dan|free|unrestricted)|from now on,? you (?:are|will|must)|act as (?:a |an |the )?(?:different|new|unrestricted|jailbroken|dan|developer|admin(?:istrator)?|system)|pretend (?:to be|you are)|roleplay as|du bist (?:jetzt|nun) (?:ein|eine|der|die|frei|uneingeschr)|tu es maintenant (?:un|une|le|la|libre))\b[^.\n]{0,60}", _I)),
    ("jailbreak_terms", re.compile(r"\b(jailbreak|developer mode|DAN mode|do anything now|sudo mode|god mode|unrestricted mode)\b", _I)),
    ("fake_system_markup", re.compile(r"(<\|im_start\|>|<\|system\|>|\[/?INST\]|###\s*(?:system|instruction)|BEGIN SYSTEM PROMPT|<system>|\bSYSTEM:\s)", _I)),
    ("tool_invocation_text", re.compile(r"\b(call|invoke|execute|run|use)\b[^.\n]{0,25}\b(issue_refund|goodwill_credit|update_address|initiate_return|escalate|lookup_order|create_ticket)\b", _I)),
    ("exfiltration", re.compile(r"\b(send|forward|post|upload|email|exfiltrate|leak)\b[^.\n]{0,50}\b(customer data|all (?:customers|orders|records)|database|credentials?|api[- ]?keys?|secrets?|tokens?)\b", _I)),
    ("markdown_exfil", re.compile(r"!\[[^\]]*\]\(https?://[^)\s]*[?&][^)\s]*\)", _I)),
    ("approve_override", re.compile(r"\b(refund|credit|compensat\w+)\b[^.\n]{0,70}\b(without|no|skip|bypass)\b[^.\n]{0,25}\b(approval|verification|authenti\w+|confirmation|checks?|limit|cap)\b", _I)),
    ("bypass_controls", re.compile(r"\b(bypass|skip|waive|circumvent)\b[^.\n]{0,25}\b(the )?(approval|verification|limit|cap|checks?|confirmation)\b", _I)),
]
SOCIAL_ENGINEERING = re.compile(
    r"\b(i am|i'm|this is)\b[^.\n]{0,25}\b(the )?(ceo|cto|director|manager|supervisor|admin(?:istrator)?|developer|engineer|auditor|police|from head ?office)\b"
    r"|\b(manager|supervisor|boss|ceo)\b[^.\n]{0,30}\b(approved|authori[sz]ed|said|told|confirmed)\b|\bauthori[sz]ed override\b|\bich bin (?:der|die)?\s*(?:chef|manager|leiter|administrator)\b",
    _I,
)
_AUTHORITY_PL = (
    r"kierownik\w*|dyrektor\w*|prezes\w*|manager\w*|menedżer\w*|szef\w*|administrator\w*|deweloper\w*|programist\w*|audytor\w*|policj\w*|funkcjonariusz\w*|komisarz\w*|prokurator\w*|inspektor\w*"
    r"|ceo\b|cto\b|z\s+centrali|z\s+(?:działu\s+)?(?:it|helpdesk\w*|bezpieczeństwa|zarządu|supportu)\b"
)
_AUTHORITY_ORG_PL = r"policj\w*|prokuratur\w*|uokik\w*|knf\b|urzęd\w*|centrali|zarządu|działu\s+\w+|it\b|helpdesk\w*|abw\b|cba\b|komend\w*|inspekcj\w*|straży|komornik\w*"
SOCIAL_ENGINEERING_PL = re.compile(
    dx(
        rf"\b(jestem|to)\b[^.\n]{{0,25}}\b({_AUTHORITY_PL})\b"
        r"|\b(kierownik\w*|szef\w*|dyrektor\w*|prezes\w*|przełożon\w*|manager\w*|menedżer\w*)\b[^.\n]{0,30}\b(zatwierdzi\w*|zgodzi\w*|autoryzowa\w*|potwierdzi\w*|powiedzia\w*|kaza\w*|pozwoli\w*|zaakceptowa\w*)\b|\bautoryzuj\w+|\bautoryzowan\w+\s+wyjątk"
        # impersonating an authority: "Dzwonię z policji", "Piszę w imieniu UOKiK", "Tu prokuratura" (reporting a call TO the police, "zgłoszę do UOKiK", is neither)
        rf"|\b(?:dzwonię|dzwonimy|piszę|piszemy|pracuję|występuję|reprezentuję)\b[^.\n]{{0,25}}\b(?:z|ze|w\s+imieniu|na\s+zlecenie)\s+(?:\w+\s+){{0,2}}(?:{_AUTHORITY_ORG_PL})"
        rf"|\bjestem\s+(?:tu\s+|tutaj\s+)?(?:z|ze)\s+(?:{_AUTHORITY_ORG_PL})"
        r"|\b(?:tu|tutaj|to\s+jest|mówi)\s+(?:\w+\s+)?(?:policj\w*|prokuratur\w*|uokik\w*|abw\b|cba\b|komisarz\w*)"
        r"|\b(?:mam|posiadam)\s+(?:pełne\s+)?(?:uprawnieni\w*|upoważnieni\w*|zgod\w*|pełnomocnictw\w*)\b[^.\n]{0,30}\b(?:kierownik\w*|dyrektor\w*|prezes\w*|zarząd\w*|szef\w*|administrator\w*)"
        r"|\bjako\s+(?:administrator|admin|kierownik|dyrektor|prezes|szef)\w*\b[^.\n]{0,40}\b(?:nakazuję|polecam|rozkazuję|zatwierdzam|upoważniam|wymagam|żądam|każę)"
        r"|\b(?:upoważniam|zezwalam)\s+(?:cię|ciebie|was|ci|wam|asystenta|system|bota)\b"
    ),
    _I,
)
SOCIAL_ENGINEERING = re.compile(SOCIAL_ENGINEERING.pattern + "|" + SOCIAL_ENGINEERING_PL.pattern, _I)
_HUMAN_ADJ_PL = r"(?:żyw|prawdziw|ludzk|jakimś|jakąś|innym|kompetentn)\w*"
_HUMAN_NOUN_PL = r"(?:konsultant|pracownik|człowiek|ludź|przedstawiciel|kierownik|przełożon|operator|opiekun)\w*"
EXPLICIT_HUMAN_PL = re.compile(
    dx(
        rf"(?:rozmow\w+|kontakt\w*|połącz\w*|przełącz\w*|przekaż\w*|poproszę|proszę|chc\w+|potrzebuj\w+|daj\w*)[^.\n]{{0,30}}\b(?:z|do|ze)\s+(?:(?:{_HUMAN_ADJ_PL})\s+)?(?:{_HUMAN_NOUN_PL})"
        rf"|\b(?:połącz|przełącz|przekieruj)\w*[^.\n]{{0,30}}\bna\s+(?:(?:{_HUMAN_ADJ_PL})\s+)?(?:{_HUMAN_NOUN_PL})"
        r"|(?:rozmow\w+|kontakt\w*|połącz\w*|przełącz\w*|poproszę|proszę|chc\w+|potrzebuj\w+)[^.\n]{0,30}\b(?:z|do|ze|na)\s+(?:żyw|prawdziw|ludzk)\w*\s+(?:osob|człowiek|konsultant|pracownik|agent|głos)\w*"
        r"|\b(?:poproszę|proszę|potrzebuję|chcę|chciałbym|chciałabym)\s+(?:o\s+)?(?:(?:żyw|prawdziw|ludzk)\w*\s+)?(?:konsultant\w*|człowiek\w*|przedstawiciel\w*|kierownik\w*|żyw\w+\s+osob\w*|operator\w*|agent\w*)"
        r"|\bkonsultant\w*\s+(?:proszę|poproszę)\b|\b(?:żywy\s+człowiek|żywego\s+człowieka|prawdziwego\s+człowieka)\b"
        # "Człowieka proszę", "Daj mi kogoś żywego", "Przekażcie sprawę konsultantowi", "Chcę z kimś porozmawiać", "Czy jest tam jakiś człowiek?"
        rf"|\b(?:{_HUMAN_NOUN_PL})\s+(?:proszę|poproszę|natychmiast)\b"
        r"|\bdaj\w*\s+(?:mi\s+)?(?:kogoś|człowieka|konsultanta|pracownika|przedstawiciela)"
        r"|\bprzekaż(?:cie|my)?\b[^.\n]{0,25}\b(?:konsultant|człowiek|pracownik|przedstawiciel|kierownik)\w*|\bprzekazać\b[^.\n]{0,25}\b(?:konsultant|człowiek|pracownik|przedstawiciel|kierownik)\w*"
        r"|\bz\s+kimś\s+(?:\w+\s+){0,2}(?:porozmawiać|pogadać|pomówić|połączyć|skontaktować)|\b(?:porozmawiać|pogadać|pomówić)\s+z\s+kimś\b"
        r"|\bczy\s+(?:jest\s+(?:tam\s+)?(?:jakiś|jakaś|ktoś)\s+(?:żywy\s+)?(?:człowiek|osoba|konsultant)|rozmawiam\s+z\s+(?:żywym\s+)?człowiekiem|ktoś\s+żywy)"
        r"|\bnie\s+chc\w+\s+(?:już\s+)?(?:rozmawiać|gadać|pisać|mówić)\s+(?:z|do|ze)\s+(?:bot\w*|robot\w*|automat\w*|maszyn\w*|komputer\w*|sztuczn\w*|chatbot\w*|ai\b|wirtualn\w*)"
    ),
    _I,
)
EXPLICIT_HUMAN = re.compile(
    r"\b(human|real person|live agent|agent|representative|operator|someone else|manager|supervisor|mitarbeiter\w*|mensch\w*|berater\w*|"
    r"echte[nr]? person|jemand(?:en)? (?:anders|echten)|vorgesetzte\w*|conseiller|humain|personne r[ée]elle|agente|persona real|operatore|persona vera|"
    r"una persona|persona humana|asesor\w*|persona\b|medewerker\w*|echte persoon|iemand|"
    r"pessoa|atendente|colega|funcion[aá]rio|humano|umano|collega)\b",
    _I,
)
EXPLICIT_HUMAN = re.compile(EXPLICIT_HUMAN.pattern + "|" + EXPLICIT_HUMAN_PL.pattern, _I)  # the stand-alone check (features/assist) must understand Polish too

PROFANITY = re.compile(
    r"\b(fuck\w*|shit(?!-?t?ake)\w*|bastard|asshole|idiot\w*|stupid|useless|moron\w*|scheiß\w*|scheiss\w*|arschloch|idiot|dumm(?!y|ie)\w*|"
    r"verdammt|merde|connard|putain|mierda|cabr[oó]n|cazzo|stronzo)\b"
    # the Polish stems carry explicit inflection endings or look-aheads, so that `debilitating`, `gown`, `Jebel`, `Hujan`, `Palantir` are not insults
    + dx(
        r"|\b(?:w?kurw\w*|chuj\w*|huj(?:|a|u|em|ow\w*|ek|ki|nia)|jeb(?:a|ie|ią|n|ł)\w*|pierdol\w*|pierdz\w*|spierdal\w*|spieprz\w*|wypierdal\w*|dup(?:a|ek|ie|y|ki|sk\w*)|gówn(?:o|a|e|em|ie|u|y|iar\w*|ian\w*)|debil(?!it)\w*|kretyn\w*|skurwysyn\w*|skurwiel\w*|"
        r"sukinsyn\w*|pojeb\w*|zjeb\w*|pizd\w*|cwel\w*|dziwk\w*|szmat\w*|fiut\w*|palant(?:|a|y|em|ów|om|ami|ach|owi|ka|ki)|palanci|palancie|matoł\w*|gnoj\w*|zasran\w*|popierdol\w*|głup(?:i|ia|ek|cy|ich|ku)|bezużyteczn\w*)\b"
    ),
    _I,
)
THREATS = re.compile(
    r"\b(i will (?:hurt|kill|destroy|find you)|ich werde (?:dich|sie) (?:fertigmachen|töten)|bomb|threat)\b"
    + dx(
        r"|\b(?:zabij\w*\s+(?:cię|ciebie|was|pana|panią)|zniszcz\w*\s+(?:was|firmę|cię|ciebie|pana|panią)|połamię|znajdę\s+(?:cię|was)|wysadz\w*|bomb(?:a|y|ę|ą|ie|om|ami|ach)\b|spalę\s+(?:was|sklep|firmę)|zrobię\s+wam\s+krzywdę"
        # a first-person threat with a person or a place as the object: "Spalę wasz sklep", "Zabiję was wszystkich", "Rozwalę wam biuro"
        r"|(?:spal|podpal|wysadz|zabij|zastrzel|pobij|rozwal|połam|zniszcz|zatłuk|udusz|dopadn)(?:ę|ię|imy|emy)\s+(?:\w+\s+){0,2}(?:cię|ciebie|was|wam|pana|panią|państwa|sklep\w*|firm\w*|biur\w*|magazyn\w*|siedzib\w*|kurier\w*|konsultant\w*|pracowni\w*|oddział\w*)"
        r"|wiem,?\s+gdzie\s+(?:mieszkasz|mieszkacie|pracujesz|pracujecie))\b"
    ),
    _I,
)
# innocuous Polish words the stems above would hit: a cleaning cloth (`szmatka`), a furniture glide (`dupki` as a product part)
_PROFANITY_SAFE_PL = re.compile(
    dx(r"\b(?:szmatk\w*|ściereczk\w*|(?:gumow|filcow|plastikow|ochronn|meblow|silikonow|samoprzylepn)\w*\s+dupki|dupki\s+(?:do|na|pod)\s+(?:mebl|nóż|krzes|stoł|szaf|podłog|łóż)\w*)\b"), _I
)
_PROFANITY_FORMS_PL = re.compile(dx(r"\bdup(?:ku|ka|kiem|ków|kom|kami|kach)\b"), _I)  # the inflected forms of `dupek` (the base list stops at `dupek` / `dupki`)
# "k***a", "ch*j", "j*bani", "k.u.r.w.a", "k u r w a": the same masked forms the NLU unmasks (lexicon_pl.MASKED_PROFANITY), matched on the folded text
_MASKED_PROFANITY_PL = [re.compile(pattern, _I) for pattern, _canonical in MASKED_PROFANITY]


def is_profane(text: str) -> bool:
    """Profanity in any supported language, including Polish words typed without diacritics, masked with `*` / `.` or spelled letter by letter."""
    if PROFANITY.search(_PROFANITY_SAFE_PL.sub(" ", text)) or _PROFANITY_FORMS_PL.search(text):
        return True
    folded = fold(text)
    return any(rx.search(folded) for rx in _MASKED_PROFANITY_PL)

RISKY_PROMISES: list[tuple[str, re.Pattern[str]]] = [
    ("guaranteed_refund", re.compile(r"\b(guarantee[ds]?|guaranteed|promise|assure|definitely|certainly will|100\s?%)\b[^.\n]{0,40}\b(refund|credit|compensation|replacement|reimburse\w*)\b|\b(refund|credit|compensation|replacement)\b[^.\n]{0,30}\b(is |are )?(guaranteed|100\s?%|for sure|no matter what)\b", _I)),
    ("guaranteed_refund_de", re.compile(r"\b(garantier\w*|auf jeden fall|definitiv|versprech\w*|sicher)\b[^.\n]{0,40}\b(erstattung|rückerstattung|gutschrift|entschädigung|ersatz)\b", _I)),
    ("guaranteed_refund_pl", re.compile(dx(r"\b(gwarantuj\w*|zagwarantuj\w*|obiecuj\w*|obiecam|zapewniam|zapewniamy|na\s+pewno|bezwarunkow\w*|100\s?%|na\s+sto\s+procent|stuprocentow\w*)\b[^.\n]{0,40}\b(zwrot\w*|zwróc\w*|rekompensat\w*|odszkodowani\w*|zadośćuczynieni\w*|wymian\w*|kredyt\w*)|\b(zwrot\w*|rekompensat\w*|odszkodowani\w*|wymian\w*)\b[^.\n]{0,30}\b(gwarantowan\w*|zagwarantowan\w*|na\s+pewno|bez\s+względu\s+na\s+wszystko|za\s+wszelką\s+cenę|100\s?%)"), _I)),
    ("legal_admission_pl", re.compile(dx(r"\b((?:przyznajemy|uznajemy)\s+(?:się\s+do\s+)?(?:winy|odpowiedzialności|błąd)|to\s+(?:była|jest)\s+(?:wyłącznie\s+|całkowicie\s+)?nasza\s+wina|wygra\s+(?:pan|pani)|ma\s+(?:pan|pani)\s+(?:silną|mocną)\s+sprawę|zapłacimy\s+(?:odszkodowanie|rekompensatę))\b"), _I)),
    ("unauthorized_commitment_pl", re.compile(dx(r"\b(pominę|obejdę|zrezygnuję\s+z)\s+(?:weryfikacj|zatwierdzeni)|bez\s+(?:zatwierdzenia|weryfikacji)\s+(?:nie\s+)?(?:jest\s+)?(?:wymagan|potrzebn)"), _I)),
    ("absolute_timeline_pl", re.compile(dx(r"\b(na\s+pewno|bez\s+wątpienia|gwarantowan\w*)\s+(?:dotrze|zostanie\s+(?:dostarczon|naprawion)|dostarczymy)"), _I)),
    ("legal_admission", re.compile(r"\b(we (?:admit|accept) (?:liability|fault|responsibility)|it was (?:entirely )?our fault|you (?:will|would) win|you have a (?:strong|solid) (?:legal )?case|we will pay (?:damages|compensation) for)\b", _I)),
    ("unauthorized_commitment", re.compile(r"\b(i (?:will|can) (?:override|waive|bypass)|(?:no|without) (?:approval|verification) (?:needed|required))\b", _I)),
    ("absolute_timeline", re.compile(r"\b(will (?:definitely|certainly|surely) (?:arrive|be delivered|be fixed)|guaranteed (?:delivery|arrival))\b", _I)),
]

SAFE_REPLACEMENT = {
    "en": "I can't promise a specific outcome yet - I'll confirm what we can do once the policy checks are complete.",
    "de": "Ein bestimmtes Ergebnis kann ich noch nicht zusagen - ich bestätige Ihnen, was möglich ist, sobald die Prüfung abgeschlossen ist.",
    "fr": "Je ne peux pas encore promettre un résultat précis - je vous confirme ce qui est possible une fois les vérifications terminées.",
    "es": "Todavía no puedo prometer un resultado concreto; le confirmaré lo que es posible cuando terminen las comprobaciones.",
    "pl": "Na tym etapie nie mogę obiecać konkretnego rezultatu — potwierdzę, co możemy zrobić, gdy skończę sprawdzać zasady.",
}

AI_DISCLOSURE = {
    "en": "You're chatting with Concierge, Contoso Home's AI assistant. A human colleague is available at any time - just ask. This conversation may be recorded and analysed to improve service.",
    "de": "Sie schreiben mit Concierge, dem KI-Assistenten von Contoso Home. Auf Wunsch verbinde ich Sie jederzeit mit einem Mitarbeiter. Das Gespräch kann zur Qualitätssicherung aufgezeichnet und ausgewertet werden.",
    "fr": "Vous échangez avec Concierge, l'assistant IA de Contoso Home. Un conseiller humain est disponible à tout moment. La conversation peut être enregistrée pour améliorer le service.",
    "es": "Está hablando con Concierge, el asistente de IA de Contoso Home. Un compañero humano está disponible en cualquier momento. La conversación puede grabarse para mejorar el servicio.",
    "it": "Stai parlando con Concierge, l'assistente IA di Contoso Home. Un collega umano è disponibile in qualsiasi momento. La conversazione può essere registrata per migliorare il servizio.",
    "nl": "U chat met Concierge, de AI-assistent van Contoso Home. Een menselijke collega is altijd beschikbaar. Het gesprek kan worden opgenomen om de service te verbeteren.",
    "pl": nbsp_pl("Dzień dobry! Jestem Concierge, asystent AI Contoso Home. W każdej chwili można poprosić o połączenie z konsultantem. Rozmowa może być nagrywana i analizowana w celu poprawy jakości obsługi. Dane przetwarzamy zgodnie z RODO."),
    "pt": "Está a falar com o Concierge, o assistente de IA da Contoso Home. Um colega humano está disponível a qualquer momento. A conversa pode ser gravada para melhorar o serviço.",
    "sv": "Du chattar med Concierge, Contoso Homes AI-assistent. En mänsklig kollega finns alltid tillgänglig. Samtalet kan spelas in för att förbättra servicen.",
}
# recording consent: the question asked on a call (or shown in the widget) before recording starts; declining never blocks the service
RECORDING_CONSENT = {
    "en": "May we record this conversation for quality and training? You can say no and we will carry on without recording.",
    "de": "Dürfen wir dieses Gespräch zu Qualitäts- und Schulungszwecken aufzeichnen? Sie können ablehnen, wir helfen Ihnen dann ohne Aufzeichnung weiter.",
    "pl": nbsp_pl("Czy możemy nagrywać tę rozmowę w celu poprawy jakości obsługi i szkoleń? Brak zgody nie wpłynie na obsługę — obsłużymy Państwa bez nagrywania."),
}
GREETING = {  # the question after the disclosure (pipeline path; the realtime model is instructed to greet in the caller's language)
    "en": "How can I help you today?", "de": "Wie kann ich helfen?", "fr": "Comment puis-je vous aider ?", "es": "¿En qué puedo ayudarle?", "it": "Come posso aiutarla?",
    "nl": "Waarmee kan ik u helpen?", "pl": "W czym mogę dziś pomóc?", "pt": "Como posso ajudar?", "sv": "Hur kan jag hjälpa dig?",
}
DISCLOSURE_MARKERS = re.compile(
    r"\b(ai assistant|virtual assistant|ai agent|ki-assistent|assistant ia|asistente de ia|assistente ia|assistente de ia|ai-assistent|asystentem ai|artificial intelligence|künstliche intelligenz|ki\b)"
    + dx(r"|\b(?:asystent\w*\s+(?:ai|sztucznej)|wirtualn\w+\s+asystent\w*|sztuczn\w+\s+inteligencj\w*|bot\b|chatbot\w*)"),
    _I,
)
RECORDING_MARKERS = re.compile(r"\b(record(?:ed|ing)|aufgezeichnet|aufzeichn\w+|enregistr\w+|grabad\w+|grabaci\w+|registrat\w+|opgenomen|nagryw\w+|nagran\w+|spela in)\b", _I)


@dataclass
class InputVerdict:
    text: str  # redacted + neutralised text that is safe to store and to send to the LLM
    redaction: Redaction | None = None
    injection: bool = False
    injection_reasons: list[str] = field(default_factory=list)
    social_engineering: bool = False
    toxic: bool = False
    toxicity: dict[str, int] = field(default_factory=dict)
    profanity: bool = False
    explicit_human_request: bool = False
    card_detected: bool = False
    pii_kinds: list[str] = field(default_factory=list)
    azure_shield: bool = False

    @property
    def flags(self) -> list[str]:
        f = []
        if self.injection:
            f.append("prompt_injection")
        if self.social_engineering:
            f.append("social_engineering")
        if self.toxic:
            f.append("toxicity")
        if self.card_detected:
            f.append("card_data")
        if self.pii_kinds:
            f.append("pii:" + ",".join(sorted(set(self.pii_kinds))))
        return f


@dataclass
class OutputVerdict:
    text: str
    issues: list[str] = field(default_factory=list)
    replaced: bool = False


def _squash(text: str) -> str:
    """"i g n o r u j" / "z.a.p.o.m.n.i.j" -> "ignoruj": letters spelled out one by one (only the Polish injection rules look at this form)."""
    return _SPELLED_OUT.sub(lambda m: re.sub(r"[ .\-_]", "", m.group()), text)


_SPELLED_OUT = re.compile(r"(?<![^\W\d_])[^\W\d_](?P<sep>[ .\-_])(?:[^\W\d_](?P=sep)){2,}[^\W\d_](?![^\W\d_])")  # one separator character throughout: "i g n o r u j", not "z.a.p.o.m.n.i.j o"


def _hit(name: str, rx: re.Pattern[str], norm: str) -> str | None:
    """The text `rx` matches in (`norm`, or for the Polish rules `norm` with spelled-out letters joined); None when it does not match."""
    if rx.search(norm):
        return norm
    if name.endswith("_pl"):
        squashed = _squash(norm)
        if squashed != norm and rx.search(squashed):
            return squashed
    return None


def detect_injection(text: str) -> list[str]:
    norm = normalize(text)
    return sorted({name for name, rx in INJECTION_PATTERNS if _hit(name, rx, norm) is not None})


def neutralize_injection(text: str) -> tuple[str, list[str]]:
    norm = normalize(text)
    reasons: list[str] = []
    for name, rx in INJECTION_PATTERNS:
        if (target := _hit(name, rx, norm)) is not None:
            reasons.append(name)
            norm = rx.sub("[instruction-like text removed]", target)
    return norm, sorted(set(reasons))


def sanitize_untrusted_document(text: str) -> tuple[str, list[str]]:
    """Strip instruction-like lines from knowledge documents (retrieved content is DATA, never instructions)."""
    reasons: set[str] = set()
    kept: list[str] = []
    for line in normalize(text).splitlines():
        hit = detect_injection(line)
        if hit:
            reasons.update(hit)
            kept.append("[line removed by security filter]")
        else:
            kept.append(line)
    return "\n".join(kept), sorted(reasons)


_NEGATED_PROMISE = re.compile(
    r"\b(?:can(?:no|')t|cannot|can not|won't|will not|unable to|not able to|not in a position to|don't|do not|never|no one can|kann (?:ich )?(?:keine|nicht)|nicht zusagen|ne peux pas|je ne peux|no puedo|non posso|kan niet|nie mog\w*)\b"
    r"[^.\n]{0,50}\b(?:promis\w*|guarantee\w*|assure\w*|zusag\w*|garantier\w*|versprech\w*|promettre|garantir|prometer|garantizar|promettere|garantire|obiecywa\w*)"
    + dx(r"|\bnie\b[^.\n]{0,50}\b(?:obiecuj\w*|obiecać|gwarantuj\w*|zagwarantować|zagwarantuj\w*|zapewni\w*|zapewniam)\b"),
    _I,
)


def find_risky_promises(text: str) -> list[str]:
    """Risky commitments in an agent output. A sentence that *refuses* to promise ("I can't guarantee a refund") is not a promise."""
    norm = normalize(text)
    kept = " ".join(s for s in re.split(r"(?<=[.!?\n])\s+", norm) if not _NEGATED_PROMISE.search(s))
    return sorted({name for name, rx in RISKY_PROMISES if rx.search(kept)})


def canary_for(conv_id: str) -> str:
    return "cx-" + hashlib.sha1(f"canary:{conv_id}".encode()).hexdigest()[:10]


def toxicity_rules(text: str) -> dict[str, int]:
    sev = {"Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 0}
    if THREATS.search(text):
        sev["Violence"] = 4
    if is_profane(text):
        sev["Hate"] = max(sev["Hate"], 2)
    return sev


class Guard:
    def __init__(self, cognitive: CognitiveClient | None = None, use_azure: bool = False) -> None:
        self.cognitive = cognitive
        self.use_azure = use_azure and cognitive is not None
        self.stats = {"inputs": 0, "injections": 0, "pii_redactions": 0, "toxic": 0, "risky_promises": 0, "blocked_outputs": 0, "kb_quarantined": 0}

    bypass_injection = False  # red-team stress mode: disables neutralisation so code-level policy is tested on its own

    def inspect_input_fast(self, text: str, lang: str = "en") -> InputVerdict:
        """Deterministic rules only (PII/PCI redaction, injection neutralisation, toxicity, escalation cues) - no network."""
        self.stats["inputs"] += 1
        norm = normalize(text)
        red = redact(norm)
        verdict = InputVerdict(text=red.text, redaction=red, pii_kinds=sorted(red.kinds), card_detected=red.has("CARD") or red.has("CVV"))
        if red.findings:
            self.stats["pii_redactions"] += len(red.findings)
        cleaned, reasons = neutralize_injection(red.text)
        verdict.toxicity = toxicity_rules(red.text)
        verdict.toxic = max(verdict.toxicity.values(), default=0) >= 4
        verdict.profanity = is_profane(red.text)
        verdict.injection = bool(reasons)
        verdict.injection_reasons = reasons
        verdict.text = red.text if self.bypass_injection else cleaned
        verdict.social_engineering = bool(SOCIAL_ENGINEERING.search(norm))
        verdict.explicit_human_request = bool(EXPLICIT_HUMAN_PL.search(norm)) or (bool(EXPLICIT_HUMAN.search(norm)) and bool(
            re.search(r"\b(talk|speak|connect|transfer|want|need|get|give|sprechen|verbinden|möchte|will|brauche|parler|passez|hablar|quiero|necesito|parlare|voglio|spreken|chcę|chce|rozmawiać|rozmawiac|połączyć|prata|falar|quero|preciso|gostaria|graag)\b", norm, _I)
        ))
        if verdict.injection:
            self.stats["injections"] += 1
        if verdict.toxic:
            self.stats["toxic"] += 1
        return verdict

    async def azure_enrich(self, verdict: InputVerdict, redacted_text: str) -> InputVerdict:
        """Azure AI Content Safety (Prompt Shields + text analysis) merged into the rules verdict; safe to run concurrently with the LLM call."""
        if not self.use_azure:
            return verdict
        results = await asyncio.gather(
            self.cognitive.shield_prompt(redacted_text),  # type: ignore[union-attr]
            self.cognitive.analyze_text(redacted_text),  # type: ignore[union-attr]
            return_exceptions=True,
        )
        if isinstance(results[0], dict) and results[0].get("userPromptAttack") and not verdict.azure_shield:
            verdict.azure_shield = True
            verdict.injection = True
            verdict.injection_reasons = sorted({*verdict.injection_reasons, "azure_prompt_shields"})
            self.stats["injections"] += 1
        if isinstance(results[1], dict):
            for k, v in results[1].items():
                verdict.toxicity[k] = max(verdict.toxicity.get(k, 0), int(v))
            verdict.toxic = max(verdict.toxicity.values(), default=0) >= 4
        return verdict

    async def inspect_input(self, text: str, lang: str = "en") -> InputVerdict:
        verdict = self.inspect_input_fast(text, lang)
        return await self.azure_enrich(verdict, verdict.redaction.text if verdict.redaction else text)

    def inspect_output(self, text: str, *, lang: str = "en", canary: str = "", allow_pii: set[str] | None = None) -> OutputVerdict:
        issues: list[str] = []
        out = text
        if canary and canary in out:
            issues.append("system_prompt_leak")
            out = out.replace(canary, "")
        red = redact(out, keep=allow_pii)
        if red.findings:
            issues.append("pii_in_output:" + ",".join(sorted(red.kinds)))
            out = red.text
        risky = find_risky_promises(out)
        replaced = False
        if risky:
            issues.extend(f"risky_promise:{r}" for r in risky)
            self.stats["risky_promises"] += len(risky)
            safe = SAFE_REPLACEMENT.get(lang, SAFE_REPLACEMENT["en"])
            sentences = re.split(r"(?<=[.!?])\s+", out)
            out = " ".join(safe if find_risky_promises(s) else s for s in sentences)
            replaced = True
        if "system_prompt_leak" in issues:
            out = out.strip() or SAFE_REPLACEMENT.get(lang, SAFE_REPLACEMENT["en"])
            replaced = True
        if issues:
            self.stats["blocked_outputs"] += 1
        return OutputVerdict(text=out, issues=issues, replaced=replaced or bool(red.findings))

    @staticmethod
    def disclosure_status(messages: list[dict[str, Any]], channel: str = "web_chat") -> dict[str, bool]:
        agent_texts = [m["text"] for m in messages if m.get("role") in ("agent_ai", "agent_human", "system_notice")]
        joined = " ".join(agent_texts[:3])
        return {
            "ai_disclosure": bool(DISCLOSURE_MARKERS.search(joined)),
            "recording_notice": bool(RECORDING_MARKERS.search(joined)),
        }
