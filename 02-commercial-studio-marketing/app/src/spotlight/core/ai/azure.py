"""Azure implementations of the AI interfaces — Entra ID (managed identity / az login) only, no keys."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import httpx
from openai import AsyncOpenAI
from PIL import Image

from ...config import Settings
from ...errors import ProviderUnavailable
from ...util import stable_hash
from . import pricing, safety_rules
from .base import ImageResult, SafetyResult, SpeechResult, T, VoiceInfo, current_ctx
from .voices import catalog, default_voice, fallback_voice, locale_for

SCOPE = "https://cognitiveservices.azure.com/.default"

# Azure neural voices pad every utterance (~0.8 s of trailing silence, ~1 s between sentences in Polish), which eats the beat windows of a 15 s spot.
# Absolute silences (SSML ``mstts:silence``, ``*-exact`` types) pin them to ad-friendly values. Calibrated on pl-PL-ZofiaNeural, see REPORT §Polish.
NEURAL_SILENCE_MS = {"Leading-exact": 30, "Tailing-exact": 60, "Sentenceboundary-exact": 260, "Comma-exact": 130, "Semicolon-exact": 180}
NEURAL_SSML_VERSION = "silence2"  # part of the neural cache key: audio cached before the silence tags / trimming is never reused


def _tight_wav(mp3: bytes) -> bytes:
    """Neural voice output without its padding: decoded, leading / trailing silence trimmed, as a WAV (the mixer decodes every line to PCM anyway)."""
    from ...video import media

    return media.encode_wav(media.trim_silence(media.decode_audio(mp3)))


def make_credential(client_id: str | None = None) -> Any:
    from azure.identity.aio import DefaultAzureCredential

    return DefaultAzureCredential(managed_identity_client_id=client_id or None)


def _openai_client(settings: Settings, credential: Any) -> AsyncOpenAI:
    from azure.identity.aio import get_bearer_token_provider

    return AsyncOpenAI(
        base_url=f"{settings.azure_openai_endpoint.rstrip('/')}/openai/v1/",
        api_key=get_bearer_token_provider(credential, SCOPE),
        timeout=httpx.Timeout(180.0, connect=15.0),
        max_retries=3,
    )


class AzureLLM:
    mode = "azure"

    def __init__(self, settings: Settings, credential: Any, meter: Any, guard: Any, cache: Any, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self.client = client or _openai_client(settings, credential)
        self.meter, self.guard, self.cache = meter, guard, cache

    async def _chat(self, *, task: str, system: str, user: str, schema: type[T] | None, role: str, max_tokens: int, effort: str, fresh: bool) -> tuple[Any, str]:
        model = self.settings.models.get(role, self.settings.model_chat)
        key = stable_hash(["llm", model, task, system, user, schema.__name__ if schema else "text", effort])
        if not fresh:
            hit = await self.cache.get_json(key)
            if hit is not None:
                await self.meter.record(kind="llm", model=model, units={"task": task, "cache": "hit"}, cost_usd=0.0, cached=True)
                return (schema.model_validate(hit["value"]) if schema else hit["value"]), model
        p_tok = pricing.estimate_tokens(system + user)
        await self.guard.authorize(pricing.llm_cost(model, p_tok, int(max_tokens * 0.5)), kind="llm", model=model)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tokens = max_tokens
        for attempt in (1, 2):
            if schema is not None:
                resp = await self.client.chat.completions.parse(
                    model=model, messages=messages, response_format=schema, max_completion_tokens=tokens, reasoning_effort=effort  # type: ignore[arg-type]
                )
            else:
                resp = await self.client.chat.completions.create(model=model, messages=messages, max_completion_tokens=tokens, reasoning_effort=effort)  # type: ignore[call-overload]
            choice = resp.choices[0]
            usage = resp.usage
            cost = pricing.llm_cost(
                model,
                usage.prompt_tokens if usage else p_tok,
                usage.completion_tokens if usage else 0,
                getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0,
            )
            await self.meter.record(
                kind="llm",
                model=model,
                units={"prompt_tokens": getattr(usage, "prompt_tokens", 0), "completion_tokens": getattr(usage, "completion_tokens", 0), "task": task},
                cost_usd=cost,
            )
            if schema is not None:
                parsed = choice.message.parsed
                if parsed is not None:
                    await self.cache.put_json(key, {"value": parsed.model_dump(mode="json")})
                    return parsed, model
            else:
                text = choice.message.content or ""
                if text.strip():
                    await self.cache.put_json(key, {"value": text})
                    return text, model
            if choice.finish_reason == "length" and attempt == 1:
                tokens = min(tokens * 2, 16000)
                continue
            raise ProviderUnavailable(
                f"LLM task {task!r} returned no usable output ({choice.finish_reason}; refusal={getattr(choice.message, 'refusal', None)})",
                code="llm_empty",
                params={"task": task, "finish": choice.finish_reason, "refusal": getattr(choice.message, "refusal", None)},
            )
        raise ProviderUnavailable(f"LLM task {task!r} failed", code="llm_failed", params={"task": task})

    async def complete(self, *, task: str, system: str, user: str, schema: type[T], role: str = "chat", max_tokens: int = 2500, effort: str = "minimal", context: dict[str, Any] | None = None, fresh: bool = False) -> T:
        out, _ = await self._chat(task=task, system=system, user=user, schema=schema, role=role, max_tokens=max_tokens, effort=effort, fresh=fresh)
        return out

    async def complete_text(self, *, task: str, system: str, user: str, role: str = "chat", max_tokens: int = 1200, effort: str = "minimal", context: dict[str, Any] | None = None, fresh: bool = False) -> str:
        out, _ = await self._chat(task=task, system=system, user=user, schema=None, role=role, max_tokens=max_tokens, effort=effort, fresh=fresh)
        return str(out)

    async def ping(self) -> dict[str, Any]:
        r = await self.client.chat.completions.create(
            model=self.settings.model_chat, messages=[{"role": "user", "content": "ok"}], max_completion_tokens=50, reasoning_effort="minimal"
        )
        return {"ok": True, "backend": "azure-openai", "deployment": self.settings.model_chat, "finish": r.choices[0].finish_reason}


class AzureImage:
    mode = "azure"

    def __init__(self, settings: Settings, credential: Any, meter: Any, guard: Any, cache: Any, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self.client = client or _openai_client(settings, credential)
        self.meter, self.guard, self.cache = meter, guard, cache

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1536x1024",
        quality: str = "low",
        model_role: str = "image",
        references: list[bytes] | None = None,
        seed: int | None = None,
        palette: list[str] | None = None,
        fresh: bool = False,
    ) -> ImageResult:
        model = self.settings.models.get(model_role, self.settings.model_image)
        digest = stable_hash(["img", model, size, quality, prompt, [stable_hash(r.hex()[:4000]) for r in (references or [])]])
        if not fresh:
            hit = await self.cache.get_bytes(digest)
            if hit:
                await self.meter.record(kind="image", model=model, units={"images": 1, "cache": "hit"}, cost_usd=0.0, cached=True)
                return ImageResult(hit[0], hit[1].get("mime", "image/jpeg"), model, size, quality, digest[:16], True, 0.0, "azure-openai")
        est = pricing.image_cost(model, quality, size)
        await self.guard.authorize(est, kind="image", model=model, premium=quality in pricing.PREMIUM_IMAGE_QUALITIES)
        data: bytes | None = None
        if references:
            try:
                files = [(f"ref{i}.png", r, "image/png") for i, r in enumerate(references[:4])]
                resp = await self.client.images.edit(model=model, image=files, prompt=prompt, size=size, quality=quality, n=1)  # type: ignore[call-overload]
                data = base64.b64decode(resp.data[0].b64_json or "")
            except Exception:
                data = None  # fall back to plain generation (style carried by the prompt)
        if not data:
            resp = await self.client.images.generate(model=model, prompt=prompt, size=size, quality=quality, n=1, output_format="jpeg", output_compression=88)  # type: ignore[call-overload]
            b64 = resp.data[0].b64_json
            if not b64:
                raise ProviderUnavailable("image model returned no image (content filter?)", code="image_empty")
            data = base64.b64decode(b64)
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        await self.meter.record(kind="image", model=model, units={"images": 1, "quality": quality, "size": size}, cost_usd=est)
        await self.cache.put_bytes(digest, data, {"mime": mime, "model": model}, mime)
        return ImageResult(data, mime, model, size, quality, digest[:16], False, est, "azure-openai")


class AzureEmbeddings:
    mode = "azure"
    dim = 1536

    def __init__(self, settings: Settings, credential: Any, meter: Any, guard: Any, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self.client = client or _openai_client(settings, credential)
        self.meter, self.guard = meter, guard

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = [t[:8000] or " " for t in texts[i : i + 64]]
            toks = sum(pricing.estimate_tokens(t) for t in batch)
            await self.guard.authorize(pricing.embed_cost(self.settings.model_embed, toks), kind="embedding")
            r = await self.client.embeddings.create(model=self.settings.model_embed, input=batch)
            out += [d.embedding for d in r.data]
            used = getattr(r.usage, "total_tokens", toks)
            await self.meter.record(kind="embedding", model=self.settings.model_embed, units={"tokens": used}, cost_usd=pricing.embed_cost(self.settings.model_embed, used))
        return out


class AzureSpeech:
    mode = "azure"

    def __init__(self, settings: Settings, credential: Any, meter: Any, guard: Any, cache: Any, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self.credential = credential
        self.client = client or _openai_client(settings, credential)
        self.meter, self.guard, self.cache = meter, guard, cache
        self._http = httpx.AsyncClient(timeout=60)
        self.fallbacks = 0

    def voices(self) -> list[VoiceInfo]:
        return catalog()

    async def _token(self) -> str:
        return (await self.credential.get_token(SCOPE)).token

    async def _openai_tts(self, name: str, text: str, speed: float) -> bytes:
        r = await self.client.audio.speech.create(model=self.settings.model_tts, voice=name, input=text, response_format="mp3", speed=max(0.5, min(speed, 1.6)))
        return r.content

    @staticmethod
    def _ssml(name: str, text: str, speed: float, lang: str, tight: bool = True) -> str:
        rate = f"{round((speed - 1.0) * 100):+d}%"
        loc = name.rsplit("-", 1)[0] if "-" in name else locale_for(lang)
        silence = "".join(f"<mstts:silence type='{kind}' value='{ms}ms'/>" for kind, ms in NEURAL_SILENCE_MS.items()) if tight else ""
        return f"<speak version='1.0' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='{loc}'><voice name='{name}'>{silence}<prosody rate='{rate}'>{xml_escape(text)}</prosody></voice></speak>"

    async def _neural_tts(self, name: str, text: str, speed: float, lang: str) -> bytes:
        url = f"{self.settings.ai_endpoint.rstrip('/')}/tts/cognitiveservices/v1"
        headers = {"Authorization": f"Bearer {await self._token()}", "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3", "User-Agent": "spotlight-studio"}
        r = await self._http.post(url, content=self._ssml(name, text, speed, lang).encode("utf-8"), headers=headers)
        if r.status_code == 400:  # a voice that does not accept the silence tags still speaks, with its natural padding
            r = await self._http.post(url, content=self._ssml(name, text, speed, lang, tight=False).encode("utf-8"), headers=headers)
        if r.status_code != 200:
            raise ProviderUnavailable(f"Azure AI Speech returned {r.status_code}: {r.text[:200]}", code="speech_failed", params={"status": r.status_code, "detail": r.text[:200]})
        return r.content

    async def _call(self, voice: str, text: str, speed: float, lang: str) -> tuple[bytes, str]:
        provider, name = voice.split(":", 1) if ":" in voice else ("openai", voice)
        if provider == "neural":
            return await self._neural_tts(name, text, speed, lang), "neural"
        return await self._openai_tts(name, text, speed), "tts-hd"

    async def synthesize(self, text: str, *, voice: str = "openai:nova", lang: str = "en", speed: float = 1.0, fresh: bool = False) -> SpeechResult:
        if not text.strip():
            raise ProviderUnavailable("empty text for speech synthesis", code="speech_empty")
        key = stable_hash(["tts", voice, lang, round(speed, 2), text, *([NEURAL_SSML_VERSION] if voice.startswith("neural:") else [])])
        if not fresh:
            hit = await self.cache.get_bytes(key)
            if hit:
                await self.meter.record(kind="tts", model=hit[1].get("kind", "tts-hd"), units={"chars": len(text), "cache": "hit"}, cost_usd=0.0, cached=True)
                return SpeechResult(hit[0], hit[1].get("mime", "audio/mpeg"), voice, lang, len(text), hit[1].get("kind", "tts-hd"), True, 0.0, "azure")
        kind = "neural" if voice.startswith("neural:") else "tts-hd"
        await self.guard.authorize(pricing.tts_cost(kind, len(text)), kind="tts", model=kind)
        used_voice = voice
        try:
            data, kind = await self._call(voice, text, speed, lang)
        except Exception:
            self.fallbacks += 1
            used_voice = fallback_voice(voice, lang)
            data, kind = await self._call(used_voice, text, speed, lang)
        mime = "audio/mpeg"
        if kind == "neural":  # the service still pads short utterances: cut the padding so the line occupies only its speech
            data, mime = await asyncio.to_thread(_tight_wav, data), "audio/wav"
        cost = pricing.tts_cost(kind, len(text))
        await self.meter.record(kind="tts", model=kind, units={"chars": len(text), "voice": used_voice}, cost_usd=cost)
        await self.cache.put_bytes(key, data, {"kind": kind, "voice": used_voice, "mime": mime}, mime)
        return SpeechResult(data, mime, used_voice, lang, len(text), kind, False, cost, "azure")

    async def ping(self) -> dict[str, Any]:
        r = await self._http.get(f"{self.settings.ai_endpoint.rstrip('/')}/tts/cognitiveservices/voices/list", headers={"Authorization": f"Bearer {await self._token()}"})
        return {"ok": r.status_code == 200, "backend": "azure-speech", "voices": len(r.json()) if r.status_code == 200 else 0, "default_voice": default_voice("en")}


class AzureSafety:
    """Azure AI Content Safety through the AIServices account (text, image, protected material, Prompt Shields)."""

    mode = "azure"

    def __init__(self, settings: Settings, credential: Any, meter: Any, guard: Any) -> None:
        self.settings = settings
        self.credential = credential
        self.meter, self.guard = meter, guard
        self._http = httpx.AsyncClient(timeout=30)

    async def _post(self, path: str, body: dict[str, Any], version: str = "2024-09-01", kind: str = "text") -> dict[str, Any]:
        await self.guard.authorize(pricing.safety_cost(kind), kind="safety")
        url = f"{self.settings.ai_endpoint.rstrip('/')}/contentsafety/{path}?api-version={version}"
        for attempt in range(3):
            tok = (await self.credential.get_token(SCOPE)).token
            r = await self._http.post(url, json=body, headers={"Authorization": f"Bearer {tok}"})
            if r.status_code == 429 and attempt < 2:
                await asyncio.sleep(float(r.headers.get("retry-after", "1")))
                continue
            break
        if r.status_code != 200:
            raise ProviderUnavailable(f"Content Safety {path} returned {r.status_code}: {r.text[:200]}", code="safety_failed", params={"path": path, "status": r.status_code, "detail": r.text[:200]})
        await self.meter.record(kind="safety", model=f"content-safety-{kind}", units={"records": 1, "api": path}, cost_usd=pricing.safety_cost(kind))
        return r.json()

    async def analyze_text(self, text: str) -> SafetyResult:
        body = {"text": text[:9500], "categories": ["Hate", "SelfHarm", "Sexual", "Violence"], "outputType": "FourSeverityLevels"}
        data = await self._post("text:analyze", body)
        return SafetyResult({c["category"]: int(c["severity"]) for c in data.get("categoriesAnalysis", [])}, raw=data)

    async def analyze_image(self, data: bytes) -> SafetyResult:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1024, 1024))
        if min(img.size) < 64:
            img = img.resize((max(64, img.width), max(64, img.height)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        body = {"image": {"content": base64.b64encode(buf.getvalue()).decode()}, "categories": ["Hate", "SelfHarm", "Sexual", "Violence"], "outputType": "FourSeverityLevels"}
        res = await self._post("image:analyze", body, kind="image")
        return SafetyResult({c["category"]: int(c["severity"]) for c in res.get("categoriesAnalysis", [])}, raw=res)

    async def protected_material(self, text: str) -> bool:
        if len(text) < 110:  # API minimum length
            return False
        data = await self._post("text:detectProtectedMaterial", {"text": text[:9500]}, version="2024-09-15-preview")
        return bool(data.get("protectedMaterialAnalysis", {}).get("detected"))

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> bool:
        # Prompt Shields' documented languages exclude Polish: a deterministic local pre-check (EN + PL patterns) runs first, as defence in depth.
        if safety_rules.local_attack(" ".join([user_prompt, *(documents or [])[:5]])):
            return True
        body = {"userPrompt": user_prompt[:9500], "documents": [d[:9500] for d in (documents or [])[:5]]}
        data = await self._post("text:shieldPrompt", body)
        if data.get("userPromptAnalysis", {}).get("attackDetected"):
            return True
        return any(d.get("attackDetected") for d in data.get("documentsAnalysis", []))

    async def ping(self) -> dict[str, Any]:
        res = await self.analyze_text("ping")
        return {"ok": True, "backend": "azure-content-safety", "categories": list(res.categories)}


def dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


__all__ = ["AzureEmbeddings", "AzureImage", "AzureLLM", "AzureSafety", "AzureSpeech", "current_ctx", "make_credential"]
