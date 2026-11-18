"""Azure AI Language, Content Safety (Prompt Shields, text analysis, groundedness) and Speech over REST with Entra bearer
tokens (managed identity). Verified against the AIServices custom-domain endpoint (see scripts/diagnose_cognitive.py)."""

from __future__ import annotations

import io
import json
import time
import wave
from typing import Any

import httpx

from ..azure_auth import get_token
from ..config import Settings
from .base import PiiEntity, TranscriptResult
from .usage import PRICES, UsageMeter

VOICES = {
    "en": ("en-US", "en-US-AvaMultilingualNeural"), "de": ("de-DE", "de-DE-KatjaNeural"), "fr": ("fr-FR", "fr-FR-DeniseNeural"),
    "es": ("es-ES", "es-ES-ElviraNeural"), "it": ("it-IT", "it-IT-ElsaNeural"), "nl": ("nl-NL", "nl-NL-ColetteNeural"),
    "pl": ("pl-PL", "pl-PL-ZofiaNeural"), "sv": ("sv-SE", "sv-SE-SofieNeural"), "pt": ("pt-PT", "pt-PT-RaquelNeural"),
    "da": ("da-DK", "da-DK-ChristelNeural"), "fi": ("fi-FI", "fi-FI-NooraNeural"), "cs": ("cs-CZ", "cs-CZ-VlastaNeural"),
    "tr": ("tr-TR", "tr-TR-EmelNeural"), "ro": ("ro-RO", "ro-RO-AlinaNeural"), "ja": ("ja-JP", "ja-JP-NanamiNeural"),
    "zh": ("zh-CN", "zh-CN-XiaoxiaoNeural"), "ar": ("ar-SA", "ar-SA-ZariyahNeural"), "ru": ("ru-RU", "ru-RU-SvetlanaNeural"),
}  # fmt: skip


class AzureCognitive:
    """Language + Content Safety."""

    name = "azure"

    def __init__(self, settings: Settings, meter: UsageMeter) -> None:
        self.s = settings
        self.meter = meter
        self.endpoint = settings.ai_services_endpoint
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0))

    async def _post(self, path: str, body: dict[str, Any], feature: str, cost: float) -> dict[str, Any]:
        self.meter.check_budget()
        token = await get_token(self.s.client_id)
        t0 = time.perf_counter()
        resp = await self._http.post(f"{self.endpoint}{path}", headers={"Authorization": f"Bearer {token}"}, json=body)
        resp.raise_for_status()
        self.meter.record(model=feature, feature=feature, latency_ms=(time.perf_counter() - t0) * 1000, extra_cost_usd=cost)
        return resp.json()

    async def detect_language(self, text: str) -> tuple[str, float]:
        body = {"kind": "LanguageDetection", "analysisInput": {"documents": [{"id": "1", "text": text[:1000]}]}}
        data = await self._post("/language/:analyze-text?api-version=2023-04-01", body, "language", PRICES["other"]["language_per_1k_text_records"] / 1000)
        det = data["results"]["documents"][0]["detectedLanguage"]
        return det["iso6391Name"], float(det.get("confidenceScore", 0))

    async def pii_entities(self, text: str, language: str = "en") -> list[PiiEntity]:
        body = {
            "kind": "PiiEntityRecognition",
            "parameters": {"modelVersion": "latest"},
            "analysisInput": {"documents": [{"id": "1", "language": language, "text": text[:5000]}]},
        }
        data = await self._post("/language/:analyze-text?api-version=2023-04-01", body, "language", PRICES["other"]["language_per_1k_text_records"] / 1000)
        ents = data["results"]["documents"][0].get("entities", [])
        return [PiiEntity(e["category"], e["text"], e["offset"], e["length"], e.get("confidenceScore", 1.0)) for e in ents]

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> dict[str, Any]:
        body = {"userPrompt": user_prompt[:9000], "documents": [d[:9000] for d in (documents or [])]}
        data = await self._post("/contentsafety/text:shieldPrompt?api-version=2024-09-01", body, "content_safety", PRICES["other"]["content_safety_per_1k_text_records"] / 1000)
        return {
            "userPromptAttack": bool(data.get("userPromptAnalysis", {}).get("attackDetected")),
            "documentsAttack": [bool(d.get("attackDetected")) for d in data.get("documentsAnalysis", [])],
        }

    async def analyze_text(self, text: str) -> dict[str, int]:
        data = await self._post("/contentsafety/text:analyze?api-version=2024-09-01", {"text": text[:9000], "outputType": "FourSeverityLevels"}, "content_safety", PRICES["other"]["content_safety_per_1k_text_records"] / 1000)
        return {c["category"]: int(c["severity"]) for c in data.get("categoriesAnalysis", [])}

    async def groundedness(self, query: str, answer: str, sources: list[str], language: str = "en") -> dict[str, Any]:
        body = {
            "domain": "Generic",
            "task": "QnA",
            "qna": {"query": query[:300]},
            "text": answer[:7000],
            "groundingSources": [s[:50000] for s in sources][:20],
            "reasoning": False,
        }
        data = await self._post("/contentsafety/text:detectGroundedness?api-version=2024-09-15-preview", body, "content_safety", PRICES["other"]["content_safety_per_1k_text_records"] / 1000)
        return {
            "ungroundedDetected": bool(data.get("ungroundedDetected")),
            "ungroundedPercentage": float(data.get("ungroundedPercentage", 0)),
            "ungroundedDetails": [{"text": d.get("text", "")} for d in data.get("ungroundedDetails", [])],
            "provider": "azure-content-safety",
        }

    async def ping(self) -> dict[str, Any]:
        lang, conf = await self.detect_language("Hello, this is a readiness probe.")
        return {"ok": True, "language_probe": lang, "confidence": conf}

    async def close(self) -> None:
        await self._http.aclose()


class AzureSpeech:
    """Azure AI Speech: fast transcription (STT) and neural TTS through the AIServices custom-domain endpoint."""

    name = "azure-speech"

    def __init__(self, settings: Settings, meter: UsageMeter) -> None:
        self.s = settings
        self.meter = meter
        self.endpoint = settings.ai_services_endpoint
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=8.0))

    async def transcribe(self, audio: bytes, *, mime: str = "audio/wav", language: str | None = None) -> TranscriptResult:
        self.meter.check_budget()
        token = await get_token(self.s.client_id)
        locales = [VOICES.get(language or "", ("",))[0]] if language and language in VOICES else [v[0] for v in list(VOICES.values())[:8]]
        definition = json.dumps({"locales": locales})
        ext = {"audio/wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3"}.get(mime, "wav")
        t0 = time.perf_counter()
        resp = await self._http.post(
            f"{self.endpoint}/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
            headers={"Authorization": f"Bearer {token}"},
            files={"audio": (f"audio.{ext}", audio, mime), "definition": (None, definition, "application/json")},
        )
        resp.raise_for_status()
        data = resp.json()
        dur = data.get("durationMilliseconds", 0) / 1000.0
        text = " ".join(p.get("text", "") for p in data.get("combinedPhrases", [])).strip()
        locale = (data.get("phrases") or [{}])[0].get("locale", "")
        self.meter.record(model="speech-stt", feature="speech", latency_ms=(time.perf_counter() - t0) * 1000, audio_seconds=dur, extra_cost_usd=dur / 3600 * PRICES["other"]["speech_stt_fast_per_hour"])
        return TranscriptResult(text=text, language=locale.split("-")[0] if locale else (language or ""), duration_s=dur)

    async def synthesize(self, text: str, *, language: str = "en", voice: str | None = None) -> tuple[bytes, str]:
        self.meter.check_budget()
        token = await get_token(self.s.client_id)
        locale, default_voice = VOICES.get(language, VOICES["en"])
        name = voice or default_voice
        safe = text[:1500].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ssml = f'<speak version="1.0" xml:lang="{locale}"><voice xml:lang="{locale}" name="{name}">{safe}</voice></speak>'
        t0 = time.perf_counter()
        resp = await self._http.post(
            f"{self.endpoint}/tts/cognitiveservices/v1",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "concierge"},
            content=ssml.encode("utf-8"),
        )
        resp.raise_for_status()
        self.meter.record(model="speech-tts", feature="speech", latency_ms=(time.perf_counter() - t0) * 1000, extra_cost_usd=len(text) / 1_000_000 * PRICES["other"]["speech_tts_neural_per_1m_chars"])
        return resp.content, "audio/wav"

    async def close(self) -> None:
        await self._http.aclose()


def wav_from_pcm16(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
