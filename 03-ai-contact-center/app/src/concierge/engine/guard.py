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
from ..core.redaction import Redaction, redact

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)


def normalize(text: str) -> str:
    """NFKC fold + strip zero-width characters so obfuscated attacks are matched."""
    return unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)


_I = re.IGNORECASE
INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the|system)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|polic(?:y|ies)|guidelines?|restrictions?)\b", _I)),
    ("override_instructions_de", re.compile(r"\b(ignorier\w*|vergiss\w*|missachte\w*|umgehe\w*)\b[^.\n]{0,40}\b(anweisung\w*|regel\w*|instruktion\w*|richtlinie\w*|vorgabe\w*)\b", _I)),
    ("override_instructions_fr_es_it", re.compile(r"\b(ignore\w*|oublie\w*|ignora\w*|olvida\w*|dimentica\w*)\b[^.\n]{0,40}\b(instructions?|instrucciones|istruzioni|consignes|règles|reglas|regole)\b", _I)),
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
EXPLICIT_HUMAN = re.compile(
    r"\b(human|real person|live agent|agent|representative|operator|someone else|manager|supervisor|mitarbeiter\w*|mensch\w*|berater\w*|"
    r"echte[nr]? person|jemand(?:en)? (?:anders|echten)|vorgesetzte\w*|conseiller|humain|personne r[ée]elle|agente|persona real|operatore|persona vera|"
    r"una persona|persona humana|asesor\w*|persona\b|medewerker\w*|echte persoon|iemand|konsultant\w*|pracownik\w*|cz[łl]owiek\w*|przedstawiciel\w*|"
    r"pessoa|atendente|colega|funcion[aá]rio|humano|umano|collega)\b",
    _I,
)

PROFANITY = re.compile(
    r"\b(fuck\w*|shit\w*|bastard|asshole|idiot\w*|stupid|useless|moron\w*|scheiß\w*|scheiss\w*|arschloch|idiot|dumm\w*|"
    r"verdammt|merde|connard|putain|mierda|cabr[oó]n|cazzo|stronzo)\b",
    _I,
)
THREATS = re.compile(r"\b(i will (?:hurt|kill|destroy|find you)|ich werde (?:dich|sie) (?:fertigmachen|töten)|bomb|threat)\b", _I)

RISKY_PROMISES: list[tuple[str, re.Pattern[str]]] = [
    ("guaranteed_refund", re.compile(r"\b(guarantee[ds]?|guaranteed|promise|assure|definitely|certainly will|100\s?%)\b[^.\n]{0,40}\b(refund|credit|compensation|replacement|reimburse\w*)\b|\b(refund|credit|compensation|replacement)\b[^.\n]{0,30}\b(is |are )?(guaranteed|100\s?%|for sure|no matter what)\b", _I)),
    ("guaranteed_refund_de", re.compile(r"\b(garantier\w*|auf jeden fall|definitiv|versprech\w*|sicher)\b[^.\n]{0,40}\b(erstattung|rückerstattung|gutschrift|entschädigung|ersatz)\b", _I)),
    ("legal_admission", re.compile(r"\b(we (?:admit|accept) (?:liability|fault|responsibility)|it was (?:entirely )?our fault|you (?:will|would) win|you have a (?:strong|solid) (?:legal )?case|we will pay (?:damages|compensation) for)\b", _I)),
    ("unauthorized_commitment", re.compile(r"\b(i (?:will|can) (?:override|waive|bypass)|(?:no|without) (?:approval|verification) (?:needed|required))\b", _I)),
    ("absolute_timeline", re.compile(r"\b(will (?:definitely|certainly|surely) (?:arrive|be delivered|be fixed)|guaranteed (?:delivery|arrival))\b", _I)),
]

SAFE_REPLACEMENT = {
    "en": "I can't promise a specific outcome yet - I'll confirm what we can do once the policy checks are complete.",
    "de": "Ein bestimmtes Ergebnis kann ich noch nicht zusagen - ich bestätige Ihnen, was möglich ist, sobald die Prüfung abgeschlossen ist.",
    "fr": "Je ne peux pas encore promettre un résultat précis - je vous confirme ce qui est possible une fois les vérifications terminées.",
    "es": "Todavía no puedo prometer un resultado concreto; le confirmaré lo que es posible cuando terminen las comprobaciones.",
}

AI_DISCLOSURE = {
    "en": "You're chatting with Concierge, Contoso Home's AI assistant. A human colleague is available at any time - just ask. This conversation may be recorded and analysed to improve service.",
    "de": "Sie schreiben mit Concierge, dem KI-Assistenten von Contoso Home. Auf Wunsch verbinde ich Sie jederzeit mit einem Mitarbeiter. Das Gespräch kann zur Qualitätssicherung aufgezeichnet und ausgewertet werden.",
    "fr": "Vous échangez avec Concierge, l'assistant IA de Contoso Home. Un conseiller humain est disponible à tout moment. La conversation peut être enregistrée pour améliorer le service.",
    "es": "Está hablando con Concierge, el asistente de IA de Contoso Home. Un compañero humano está disponible en cualquier momento. La conversación puede grabarse para mejorar el servicio.",
    "it": "Stai parlando con Concierge, l'assistente IA di Contoso Home. Un collega umano è disponibile in qualsiasi momento. La conversazione può essere registrata per migliorare il servizio.",
    "nl": "U chat met Concierge, de AI-assistent van Contoso Home. Een menselijke collega is altijd beschikbaar. Het gesprek kan worden opgenomen om de service te verbeteren.",
    "pl": "Rozmawiasz z Concierge, asystentem AI Contoso Home. Pracownik jest dostępny w każdej chwili. Rozmowa może być nagrywana w celu poprawy jakości obsługi.",
    "pt": "Está a falar com o Concierge, o assistente de IA da Contoso Home. Um colega humano está disponível a qualquer momento. A conversa pode ser gravada para melhorar o serviço.",
    "sv": "Du chattar med Concierge, Contoso Homes AI-assistent. En mänsklig kollega finns alltid tillgänglig. Samtalet kan spelas in för att förbättra servicen.",
}
DISCLOSURE_MARKERS = re.compile(r"\b(ai assistant|virtual assistant|ai agent|ki-assistent|assistant ia|asistente de ia|assistente ia|ai-assistent|asystentem ai|artificial intelligence|künstliche intelligenz|ki\b)", _I)
RECORDING_MARKERS = re.compile(r"\b(record(?:ed|ing)|aufgezeichnet|aufzeichn\w+|enregistr\w+|grabad\w+|grabaci\w+|registrat\w+|opgenomen|nagryw\w+|spela in)\b", _I)


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


def detect_injection(text: str) -> list[str]:
    norm = normalize(text)
    return sorted({name for name, rx in INJECTION_PATTERNS if rx.search(norm)})


def neutralize_injection(text: str) -> tuple[str, list[str]]:
    norm = normalize(text)
    reasons: list[str] = []
    for name, rx in INJECTION_PATTERNS:
        if rx.search(norm):
            reasons.append(name)
            norm = rx.sub("[instruction-like text removed]", norm)
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
    r"[^.\n]{0,50}\b(?:promis\w*|guarantee\w*|assure\w*|zusag\w*|garantier\w*|versprech\w*|promettre|garantir|prometer|garantizar|promettere|garantire|obiecywa\w*)",
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
    if PROFANITY.search(text):
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
        verdict.profanity = bool(PROFANITY.search(red.text))
        verdict.injection = bool(reasons)
        verdict.injection_reasons = reasons
        verdict.text = red.text if self.bypass_injection else cleaned
        verdict.social_engineering = bool(SOCIAL_ENGINEERING.search(norm))
        verdict.explicit_human_request = bool(EXPLICIT_HUMAN.search(norm)) and bool(
            re.search(r"\b(talk|speak|connect|transfer|want|need|get|give|sprechen|verbinden|möchte|will|brauche|parler|passez|hablar|quiero|necesito|parlare|voglio|spreken|chcę|chce|rozmawiać|rozmawiac|połączyć|prata|falar|quero|preciso|gostaria|graag)\b", norm, _I)
        )
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
