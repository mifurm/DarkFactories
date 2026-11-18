"""Voice catalog shared by the Azure and stub speech clients (Azure OpenAI tts-hd voices + Azure AI Speech neural voices)."""

from __future__ import annotations

from .base import VoiceInfo

OPENAI_VOICES = [
    VoiceInfo("openai:nova", "Nova — warm, friendly", "openai", "*", "female", "warm"),
    VoiceInfo("openai:shimmer", "Shimmer — bright, upbeat", "openai", "*", "female", "bright"),
    VoiceInfo("openai:alloy", "Alloy — neutral, clear", "openai", "*", "neutral", "neutral"),
    VoiceInfo("openai:fable", "Fable — expressive storyteller", "openai", "*", "male", "storyteller"),
    VoiceInfo("openai:echo", "Echo — calm, composed", "openai", "*", "male", "calm"),
    VoiceInfo("openai:onyx", "Onyx — deep, authoritative", "openai", "*", "male", "deep"),
]

NEURAL = {
    "en": [("en-US-JennyNeural", "Jenny", "female"), ("en-US-GuyNeural", "Guy", "male"), ("en-GB-SoniaNeural", "Sonia (UK)", "female"), ("en-GB-RyanNeural", "Ryan (UK)", "male")],
    "de": [("de-DE-KatjaNeural", "Katja", "female"), ("de-DE-ConradNeural", "Conrad", "male")],
    "fr": [("fr-FR-DeniseNeural", "Denise", "female"), ("fr-FR-HenriNeural", "Henri", "male")],
    "es": [("es-ES-ElviraNeural", "Elvira", "female"), ("es-ES-AlvaroNeural", "Álvaro", "male")],
    "it": [("it-IT-ElsaNeural", "Elsa", "female"), ("it-IT-DiegoNeural", "Diego", "male")],
    "pl": [("pl-PL-ZofiaNeural", "Zofia", "female"), ("pl-PL-MarekNeural", "Marek", "male")],
    "pt": [("pt-PT-RaquelNeural", "Raquel", "female"), ("pt-PT-DuarteNeural", "Duarte", "male")],
    "nl": [("nl-NL-ColetteNeural", "Colette", "female"), ("nl-NL-MaartenNeural", "Maarten", "male")],
}
LOCALES = {"en": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "pl": "pl-PL", "pt": "pt-PT", "nl": "nl-NL"}
STYLE_PL = {
    "warm, friendly": "ciepły, przyjazny", "bright, upbeat": "jasny, pogodny", "neutral, clear": "neutralny, wyraźny",
    "expressive storyteller": "wyrazisty gawędziarz", "calm, composed": "spokojny, opanowany", "deep, authoritative": "głęboki, autorytatywny",
}


def display_name(voice: VoiceInfo, locale: str = "en") -> str:
    """The label shown in the voice picker. English keeps the catalog name; Polish translates the style words ("Nova — ciepły, przyjazny")
    and the neural-voice suffix ("Zofia (PL, głos neuronowy)")."""
    if locale != "pl":
        return voice.name
    if voice.provider == "openai":
        head, sep, style = voice.name.partition(" — ")
        return f"{head} — {STYLE_PL.get(style, style)}" if sep else voice.name
    return f"{voice.name.removesuffix(f' ({voice.lang.upper()} neural)')} ({voice.lang.upper()}, głos neuronowy)"


def catalog() -> list[VoiceInfo]:
    out = list(OPENAI_VOICES)
    for lang, items in NEURAL.items():
        out += [VoiceInfo(f"neural:{vid}", f"{name} ({lang.upper()} neural)", "neural", lang, g) for vid, name, g in items]
    return out


def default_voice(lang: str, gender: str = "female") -> str:
    """English: tts-hd Nova; other languages: a native Azure AI Speech neural voice (better accent)."""
    if lang == "en":
        return "openai:nova" if gender != "male" else "openai:onyx"
    items = NEURAL.get(lang) or NEURAL["en"]
    for vid, _, g in items:
        if g == gender:
            return f"neural:{vid}"
    return f"neural:{items[0][0]}"


def fallback_voice(voice: str, lang: str) -> str:
    """The other provider's equivalent voice, used when one speech provider is unavailable."""
    if voice.startswith("neural:"):
        return "openai:nova"
    return default_voice(lang) if lang != "en" else f"neural:{NEURAL['en'][0][0]}"


def locale_for(lang: str) -> str:
    return LOCALES.get(lang, "en-US")
