"""Deterministic offline stubs for every AI interface (tests / CI / local-without-Azure).

They are real, tested software: same interfaces, same metering + budget-guard path as the Azure clients
(prices are simulated with the same price table), deterministic outputs seeded from the inputs.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import math
import re
import wave
from collections.abc import Callable
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ...domain.text import detect_lang
from ...errors import ProviderUnavailable
from ...util import stable_hash
from . import pricing, safety_rules
from .base import ImageResult, SafetyResult, SpeechResult, T, VoiceInfo

# --------------------------------------------------------------------------------------- LLM

STUB_TASKS: dict[str, Callable[[dict[str, Any]], Any]] = {}


def stub_task(name: str) -> Callable[[Callable[[dict[str, Any]], Any]], Callable[[dict[str, Any]], Any]]:
    """Register the deterministic offline generator for an LLM task (kept next to the real prompt)."""

    def deco(fn: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
        STUB_TASKS[name] = fn
        return fn

    return deco


class StubLLM:
    mode = "stub"

    def __init__(self, meter: Any = None, guard: Any = None) -> None:
        self.meter = meter
        self.guard = guard
        self.calls: list[str] = []

    async def _run(self, task: str, system: str, user: str, context: dict[str, Any] | None, role: str) -> Any:
        handler = STUB_TASKS.get(task)
        if handler is None:
            raise ProviderUnavailable(f"no offline stub registered for LLM task {task!r}", code="stub_missing", params={"task": task})
        model = "gpt-5.4" if role == "reasoning" else "gpt-5.4-mini"
        p_tok = pricing.estimate_tokens(system + user)
        if self.guard:
            await self.guard.authorize(pricing.llm_cost(model, p_tok, 400), kind="llm", model=model)
        out = handler(context or {})
        self.calls.append(task)
        if self.meter:
            c_tok = pricing.estimate_tokens(str(out))
            await self.meter.record(
                kind="llm",
                model=model,
                units={"prompt_tokens": p_tok, "completion_tokens": c_tok, "task": task, "stub": True},
                cost_usd=pricing.llm_cost(model, p_tok, c_tok),
            )
        return out

    async def complete(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        role: str = "chat",
        max_tokens: int = 2500,
        effort: str = "minimal",
        context: dict[str, Any] | None = None,
        fresh: bool = False,
    ) -> T:
        out = await self._run(task, system, user, context, role)
        if isinstance(out, schema):
            return out
        return schema.model_validate(out)

    async def complete_text(
        self,
        *,
        task: str,
        system: str,
        user: str,
        role: str = "chat",
        max_tokens: int = 1200,
        effort: str = "minimal",
        context: dict[str, Any] | None = None,
        fresh: bool = False,
    ) -> str:
        return str(await self._run(task, system, user, context, role))

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "stub"}


# --------------------------------------------------------------------------------------- image

DEFAULT_PALETTE = ["#2B1A12", "#F2A03D", "#F6EBDD", "#B5452B", "#5C7A5E"]


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _mix(a: np.ndarray, b: np.ndarray, t: np.ndarray | float) -> np.ndarray:
    return a * (1 - t) + b * t


def render_stub_scene(prompt: str, size: tuple[int, int], palette: list[str] | None, seed: int) -> Image.Image:
    """Procedural 'dawn' illustration: gradient sky, sun glow, layered hills, coffee cup, steam."""
    w, h = size
    pal = [np.array(hex_to_rgb(c), dtype=np.float64) for c in (palette or DEFAULT_PALETTE)]
    while len(pal) < 5:
        pal.append(pal[-1])
    dark, amber, cream, red, sage = pal[:5]
    rng = np.random.default_rng(seed)
    ys = np.linspace(0, 1, h)[:, None, None]
    xs = np.linspace(0, 1, w)[None, :, None]
    sky = np.where(ys < 0.55, _mix(_mix(dark, red, 0.35), amber, np.clip(ys / 0.55, 0, 1) ** 1.4), _mix(amber, cream, np.clip((ys - 0.55) / 0.45, 0, 1)))
    sx, sy = rng.uniform(0.25, 0.75), rng.uniform(0.38, 0.52)
    dist = np.sqrt(((xs - sx) * (w / h)) ** 2 + (ys - sy) ** 2)
    glow = np.exp(-(dist / 0.28) ** 2)[..., :1] * 0.75
    img = _mix(sky, cream, glow)
    disc = (dist < 0.075)[..., :1]
    img = np.where(disc, _mix(img, cream, 0.92), img)
    for i in range(3):
        base = 0.62 + 0.1 * i
        amp = 0.035 + 0.015 * i
        ph = rng.uniform(0, 6.28)
        fr = rng.uniform(2.0, 4.5)
        line = base + amp * np.sin(fr * 6.28 * xs[..., 0] + ph) + 0.015 * np.sin(fr * 17 * xs[..., 0] + ph * 2)
        mask = (ys[..., 0] > line)[..., None]
        col = _mix(dark, sage, 0.18 + 0.2 * (2 - i))
        img = np.where(mask, _mix(img, col, 0.93 - 0.08 * i), img)
    grain = rng.normal(0, 3.0, (h, w, 1))
    arr = np.clip(img + grain, 0, 255).astype(np.uint8)
    base_img = Image.fromarray(arr, "RGB")

    # coffee cup + steam (supersampled overlay)
    s = 2
    layer = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = int((0.3 + 0.4 * ((seed >> 3) % 100) / 100) * w * s)
    cy = int(0.78 * h * s)
    cw = int(0.17 * h * s)
    cup = (*tuple(int(v) for v in cream), 255)
    shade = (*tuple(int(v) for v in _mix(cream, red, 0.45)), 255)
    d.polygon([(cx - cw, cy - cw), (cx + cw, cy - cw), (cx + int(cw * 0.78), cy + int(cw * 0.9)), (cx - int(cw * 0.78), cy + int(cw * 0.9))], fill=cup)
    d.polygon([(cx - int(cw * 0.1), cy - cw), (cx + cw, cy - cw), (cx + int(cw * 0.78), cy + int(cw * 0.9)), (cx + int(cw * 0.15), cy + int(cw * 0.9))], fill=shade)
    d.ellipse([cx + int(cw * 0.78), cy - int(cw * 0.6), cx + int(cw * 1.55), cy + int(cw * 0.3)], outline=cup, width=max(3, cw // 6))
    d.ellipse([cx - cw, cy - cw - int(cw * 0.18), cx + cw, cy - cw + int(cw * 0.18)], fill=(*tuple(int(v) for v in dark), 255))
    for k in range(3):
        pts = [(cx - int(cw * 0.5) + k * int(cw * 0.5) + int(14 * s * math.sin(t / 3.0 + k)), cy - cw - int(cw * 0.2) - t * s * 4) for t in range(0, 40)]
        d.line(pts, fill=(*tuple(int(v) for v in cream), 110), width=max(3, cw // 9))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.2 * s)).resize((w, h), Image.Resampling.LANCZOS)
    base_img.paste(layer, (0, 0), layer)
    return base_img


class StubImage:
    mode = "stub"

    def __init__(self, meter: Any = None, guard: Any = None) -> None:
        self.meter = meter
        self.guard = guard
        self.calls = 0

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
        model = "gpt-image-1.5" if model_role == "image" else "gpt-image-1-mini"
        est = pricing.image_cost(model, quality, size)
        if self.guard:
            await self.guard.authorize(est, kind="image", model=model, premium=quality in pricing.PREMIUM_IMAGE_QUALITIES)
        w, h = (int(v) for v in size.split("x"))
        sd = seed if seed is not None else int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        img = render_stub_scene(prompt, (w // 2, h // 2) if max(w, h) > 1024 else (w, h), palette, sd)
        if img.size != (w, h):
            img = img.resize((w, h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        self.calls += 1
        if self.meter:
            await self.meter.record(kind="image", model=model, units={"images": 1, "quality": quality, "size": size, "stub": True}, cost_usd=est)
        return ImageResult(buf.getvalue(), "image/jpeg", model, size, quality, stable_hash(prompt)[:16], False, est, "stub")


# --------------------------------------------------------------------------------------- speech

def speech_duration_estimate(text: str, speed: float = 1.0) -> float:
    words = re.findall(r"\w+", text)
    pause = 0.2 * len(re.findall(r"[,;:]", text)) + 0.35 * len(re.findall(r"[.!?…]", text))
    return round((sum(0.13 + 0.052 * len(w) for w in words) + 0.07 * len(words) + pause) / max(speed, 0.5), 3)


def synth_pseudo_speech(text: str, voice: str, speed: float = 1.0, sr: int = 24000, lang: str = "en") -> bytes:
    """Speech-like synthetic audio: per-word voiced bursts with formant emphasis (NOT intelligible).

    English keeps its letter-length timing; other languages are syllable-timed with the same model the script estimator uses
    (``domain.timing``: rate, sentence / comma pauses, line padding), like real neural voices: Polish words are long but not proportionally slow to say."""
    from ...domain.text import syllables
    from ...domain.timing import COMMA_PAUSE, LINE_PAD, SENTENCE_PAUSE, SYLLABLE_RATE

    def model(table: dict[str, float]) -> float:
        return table.get(lang, table["en"])

    base = 105 + (int(hashlib.sha1(voice.encode()).hexdigest()[:4], 16) % 110)
    chunks: list[np.ndarray] = []
    words = re.findall(r"\w+[.,;:!?…]*", text)
    if lang != "en":
        chunks.append(np.zeros(int(sr * model(LINE_PAD) * 0.27 / max(speed, 0.5)), dtype=np.float32))  # lead share of the padding
    for i, wd in enumerate(words):
        core = re.sub(r"[^\w]", "", wd)
        dur = ((0.13 + 0.052 * len(core)) if lang == "en" else max(1, syllables(core, lang)) / model(SYLLABLE_RATE)) / max(speed, 0.5)
        n = int(sr * dur)
        t = np.arange(n) / sr
        f0 = base * (1 + 0.08 * math.sin(i * 1.7)) * (1 + 0.04 * np.sin(2 * math.pi * 5 * t))
        phase = 2 * math.pi * np.cumsum(f0) / sr
        sig = sum((1.0 / k) * np.sin(k * phase) * (1.6 if k in (3, 5) else 1.0) for k in range(1, 8))
        env = np.hanning(n) ** 0.6
        chunks.append((sig * env * 0.18).astype(np.float32))
        last = i == len(words) - 1
        if lang == "en":
            gap = 0.07 + (0.35 if wd[-1:] in ".!?…" else 0.2 if wd[-1:] in ",;:" else 0.0)
        elif last:
            gap = model(LINE_PAD) * 0.73  # trail share of the padding
        else:
            gap = model(SENTENCE_PAUSE) if wd[-1:] in ".!?…" else model(COMMA_PAUSE) if wd[-1:] in ",;:" else 0.0
        chunks.append(np.zeros(int(sr * gap / max(speed, 0.5)), dtype=np.float32))
    audio = np.concatenate(chunks) if chunks else np.zeros(int(sr * 0.2), dtype=np.float32)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class StubSpeech:
    mode = "stub"

    def __init__(self, meter: Any = None, guard: Any = None) -> None:
        self.meter = meter
        self.guard = guard
        self.calls = 0

    def voices(self) -> list[VoiceInfo]:
        from .voices import catalog

        return catalog()

    async def synthesize(self, text: str, *, voice: str = "openai:nova", lang: str = "en", speed: float = 1.0, fresh: bool = False) -> SpeechResult:
        kind = "neural" if voice.startswith("neural:") else "tts-hd"
        est = pricing.tts_cost(kind, len(text))
        if self.guard:
            await self.guard.authorize(est, kind="tts", model=kind)
        data = synth_pseudo_speech(text, voice, speed, lang=lang)
        self.calls += 1
        if self.meter:
            await self.meter.record(kind="tts", model=kind, units={"chars": len(text), "voice": voice, "stub": True}, cost_usd=est)
        return SpeechResult(data, "audio/wav", voice, lang, len(text), kind, False, est, "stub")

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "stub"}


# --------------------------------------------------------------------------------------- embeddings

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be", "it", "this", "that", "at", "by", "as", "we", "our", "you", "your"}
_STOP_PL = {"i", "w", "z", "o", "u", "a", "na", "do", "po", "od", "za", "nie", "to", "jest", "sie", "dla", "ale", "lub", "oraz", "jak", "ze", "co", "tak", "czy", "ten", "ta", "te", "tego", "tej", "ich", "ci", "ty", "ma", "sa", "byl"}
_PL_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


class StubEmbeddings:
    mode = "stub"
    dim = 384

    def __init__(self, meter: Any = None, guard: Any = None) -> None:
        self.meter = meter
        self.guard = guard

    @staticmethod
    def _vec(text: str, dim: int) -> list[float]:
        polish = detect_lang(text) == "pl"  # Polish text: fold diacritics (a typed-without-diacritics query still matches) + Polish stop-words
        low = text.translate(_PL_FOLD).lower() if polish else text.lower()
        toks = [t for t in re.findall(r"[a-z0-9äöüßéèêàçñąćęłńóśźż]+", low) if t not in _STOP and not (polish and t in _STOP_PL)]
        feats = toks + [a + "_" + b for a, b in itertools.pairwise(toks)]
        v = np.zeros(dim, dtype=np.float64)
        for f in feats:
            h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
            v[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
            # a second, stem-like feature so "roasted"/"roast" overlap a little
            stem = f[:5]
            h2 = int(hashlib.md5(("s:" + stem).encode()).hexdigest()[:8], 16)
            v[h2 % dim] += 0.5 if (h2 >> 31) & 1 else -0.5
        n = float(np.linalg.norm(v))
        return (v / n).tolist() if n else v.tolist()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        toks = sum(pricing.estimate_tokens(t) for t in texts)
        if self.guard:
            await self.guard.authorize(pricing.embed_cost("text-embedding-3-small", toks), kind="embedding")
        if self.meter:
            await self.meter.record(kind="embedding", model="text-embedding-3-small", units={"tokens": toks, "stub": True}, cost_usd=pricing.embed_cost("text-embedding-3-small", toks))
        return [self._vec(t, self.dim) for t in texts]


# --------------------------------------------------------------------------------------- safety

# word lists (English + Polish) live in safety_rules.py, shared with the Azure adapter's local Prompt-Shields pre-check


class StubSafety:
    mode = "stub"

    def __init__(self, meter: Any = None, guard: Any = None, flagged_image_hashes: set[str] | None = None) -> None:
        self.meter = meter
        self.guard = guard
        self.flagged_image_hashes = flagged_image_hashes or set()

    async def _tick(self, kind: str) -> None:
        est = pricing.safety_cost(kind)
        if self.guard:
            await self.guard.authorize(est, kind="safety")
        if self.meter:
            await self.meter.record(kind="safety", model=f"content-safety-{kind}", units={"records": 1, "stub": True}, cost_usd=est)

    async def analyze_text(self, text: str) -> SafetyResult:
        await self._tick("text")
        return SafetyResult(safety_rules.severity(text), provider="stub")

    async def analyze_image(self, data: bytes) -> SafetyResult:
        await self._tick("image")
        flagged = hashlib.sha256(data).hexdigest() in self.flagged_image_hashes
        return SafetyResult({"Hate": 0, "SelfHarm": 0, "Sexual": 0, "Violence": 6 if flagged else 0}, provider="stub")

    async def protected_material(self, text: str) -> bool:
        await self._tick("text")
        return safety_rules.protected(text)

    async def shield_prompt(self, user_prompt: str, documents: list[str] | None = None) -> bool:
        await self._tick("text")
        return safety_rules.local_attack(" ".join([user_prompt, *(documents or [])]))

    async def ping(self) -> dict[str, Any]:
        return {"ok": True, "backend": "stub"}
