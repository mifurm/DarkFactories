"""Voice-over timing in Polish: the speaking model the script estimator uses, the offline voice that follows it, silence handling of neural voices,
and the beat fitting (trim, rebalance) that keeps a Polish line inside its beat. English behaviour is pinned next to it."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from conftest import needs_ffmpeg
from spotlight.core.ai.azure import NEURAL_SILENCE_MS, AzureSpeech
from spotlight.core.ai.cache import AICache
from spotlight.core.ai.stubs import synth_pseudo_speech
from spotlight.core.blobs import MemoryBlobStore
from spotlight.core.repo import MemoryRepository
from spotlight.domain import script as sc
from spotlight.domain.timing import HEADROOM, MAX_SPEED, beat_fit, estimate_vo_seconds, fit_line
from spotlight.video import media


def _seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


# ------------------------------------------------------------------------------------------------ estimator + offline voice


def test_english_estimator_and_headroom_are_exactly_what_they_were():
    assert estimate_vo_seconds("Before the house wakes up, there is a quiet hour. Dawn Roast.", "en") == 4.0
    assert HEADROOM["en"] == MAX_SPEED
    assert beat_fit({"vo": "Wake up slowly.", "t_start": 0.0, "t_end": 3.0}, "en")["too_long"] is False
    assert estimate_vo_seconds("Wolno.", "de") == estimate_vo_seconds("Wolno.", "en")  # other languages fall back to the English model


def test_polish_estimate_counts_syllables_sentence_and_comma_pauses_and_line_padding():
    one = estimate_vo_seconds("Obudź się powoli.", "pl")
    two = estimate_vo_seconds("Obudź się powoli. Obudź się powoli.", "pl")
    assert two == pytest.approx(2 * one + 0.6 - 0.11, abs=0.02)  # second sentence: its speech + the 0.6 s sentence pause, one shared padding
    assert estimate_vo_seconds("Karmel, pomarańcza, kakao.", "pl") > estimate_vo_seconds("Karmel pomarańcza kakao.", "pl") + 0.6  # two commas
    assert estimate_vo_seconds("", "pl") == 0.0


def test_the_offline_polish_voice_is_exactly_as_long_as_the_estimate_and_english_keeps_its_own_timing():
    for text in ("Zacznij dzień wolniej.", "Dawn Roast. Średnie palenie, palone w małych partiach.", "Dawn Roast daje spokojniejszy początek poranka. Karmel, pomarańcza, kakao."):
        assert _seconds(synth_pseudo_speech(text, "neural:pl-PL-ZofiaNeural", lang="pl")) == pytest.approx(estimate_vo_seconds(text, "pl"), abs=0.02)
    en = "Before the house wakes up, there is a quiet hour. Dawn Roast."
    assert _seconds(synth_pseudo_speech(en, "openai:nova")) == _seconds(synth_pseudo_speech(en, "openai:nova", lang="en"))  # unchanged English stub


# ------------------------------------------------------------------------------------------------ fitting a line into its beat


def beat(vo: str, t0: float, t1: float) -> dict:
    return {"id": "b", "role": "proof", "vo": vo, "t_start": t0, "t_end": t1}


def test_a_polish_line_that_overruns_its_beat_loses_trailing_sentences_but_never_the_tagline_or_a_mandatory():
    b = beat("Dawn Roast leczy poranny niepokój. Karmel, pomarańcza, kakao. Obudź się powoli.", 0.0, 4.2)
    assert beat_fit(b, "pl")["too_long"]
    assert sc.trim_to_window(b, lang="pl", keep=["Obudź się powoli.", "Dawn Roast leczy poranny niepokój."])
    assert b["vo"] == "Dawn Roast leczy poranny niepokój. Obudź się powoli." and not beat_fit(b, "pl")["too_long"]
    only_protected = beat("Dawn Roast leczy poranny niepokój. Obudź się powoli.", 0.0, 2.0)
    assert sc.trim_to_window(only_protected, lang="pl", keep=["Obudź się powoli.", "Dawn Roast leczy poranny niepokój."]) is False  # nothing droppable: the issue stays visible
    assert "poranny niepokój" in only_protected["vo"]


def test_english_trimming_is_unchanged():
    b = beat("One. Two three four five six seven eight. Nine ten eleven twelve thirteen fourteen.", 0.0, 3.0)
    assert sc.trim_to_window(b) and b["vo"] == "One. Two three four five six seven eight."  # the word-count rule of the English path


def test_rebalance_gives_a_long_line_the_time_it_needs_and_keeps_the_total_length():
    beats = [
        {"id": "b1", "role": "hook", "vo": "Zacznij dzień wolniej.", "t_start": 0.0, "t_end": 3.0},
        {"id": "b2", "role": "brand", "vo": "Dawn Roast leczy poranny niepokój. Obudź się powoli.", "t_start": 3.0, "t_end": 6.0},
    ]
    assert beat_fit(beats[1], "pl")["too_long"]
    assert sc.rebalance_beats(beats, 6, "pl")
    assert beats[0]["t_start"] == 0 and beats[0]["t_end"] == beats[1]["t_start"] and beats[1]["t_end"] == 6.0
    assert not any(beat_fit(b, "pl")["too_long"] for b in beats) and beats[1]["t_end"] - beats[1]["t_start"] > 3.5
    assert sc.rebalance_beats(beats, 6, "pl") is False  # already fits: windows are left alone
    en = [dict(b, vo="x " * 60) for b in beats]
    assert sc.rebalance_beats(en, 6, "en") is False  # English is never touched


def test_speed_up_and_overflow_flags_use_the_voice_length_not_the_estimate():
    ok = fit_line(0.0, 4.2, 3.6)
    assert ok["speed"] == 1.0 and ok["overflow"] is False  # 3.6 s of speech fits the 3.85 s of room
    sped = fit_line(0.0, 4.2, 4.4)
    assert sped["speed"] == pytest.approx(4.4 / 3.85, abs=0.001) and sped["overflow"] is False
    over = fit_line(0.0, 4.2, 6.5)
    assert over["speed"] == MAX_SPEED and over["overflow"] is True


# ------------------------------------------------------------------------------------------------ neural voices: silence control


def test_neural_ssml_pins_the_silences_and_a_plain_variant_exists_for_voices_that_reject_them():
    ssml = AzureSpeech._ssml("pl-PL-ZofiaNeural", "Zacznij dzień wolniej & <spokojnie>.", 1.0, "pl")
    assert "xml:lang='pl-PL'" in ssml and "xmlns:mstts=" in ssml and "&amp;" in ssml and "&lt;spokojnie&gt;" in ssml
    for kind, ms in NEURAL_SILENCE_MS.items():
        assert f"<mstts:silence type='{kind}' value='{ms}ms'/>" in ssml
    assert "mstts:silence" not in AzureSpeech._ssml("pl-PL-ZofiaNeural", "x", 1.0, "pl", tight=False)
    assert "rate='+20%'" in AzureSpeech._ssml("pl-PL-ZofiaNeural", "x", 1.2, "pl")


def test_trim_silence_removes_padding_but_keeps_a_margin_and_never_touches_silent_input():
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(int(0.5 * media.SR)) / media.SR)).astype(np.float32)
    padded = np.concatenate([np.zeros(int(0.8 * media.SR), np.float32), tone, np.zeros(int(0.8 * media.SR), np.float32)])
    stereo = np.stack([padded, padded], axis=1)
    out = media.trim_silence(stereo)
    assert len(out) / media.SR == pytest.approx(0.5 + 0.03 + 0.08, abs=0.01)
    silent = np.zeros((1000, 2), np.float32)
    assert len(media.trim_silence(silent)) == 1000 and len(media.trim_silence(np.zeros((0, 2), np.float32))) == 0


class _Meter:
    async def record(self, **kw):  # noqa: D401, ANN003
        return None


class _Guard:
    async def authorize(self, *a, **kw):  # noqa: ANN002, ANN003
        return None


def _padded_wav() -> bytes:
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(int(0.5 * media.SR)) / media.SR)).astype(np.float32)
    pad = np.zeros(int(0.8 * media.SR), np.float32)
    mono = np.concatenate([pad, tone, pad])
    return media.encode_wav(np.stack([mono, mono], axis=1))


@needs_ffmpeg
async def test_neural_voice_output_is_trimmed_cached_and_flagged_as_wav_while_openai_voices_are_untouched():
    cache = AICache(MemoryRepository(), MemoryBlobStore())
    speech = AzureSpeech.__new__(AzureSpeech)  # no network: the service call is replaced
    speech.settings, speech.client, speech.meter, speech.guard, speech.cache, speech.fallbacks = None, None, _Meter(), _Guard(), cache, 0
    calls: list[str] = []
    mp3_like = b"\xff\xfb" + b"openai-bytes"

    async def fake_call(voice: str, text: str, speed: float, lang: str):
        calls.append(voice)
        return (_padded_wav(), "neural") if voice.startswith("neural:") else (mp3_like, "tts-hd")

    speech._call = fake_call  # type: ignore[method-assign]
    first = await speech.synthesize("Zacznij dzień wolniej.", voice="neural:pl-PL-ZofiaNeural", lang="pl")
    assert first.mime == "audio/wav" and not first.cached and _seconds(first.data) == pytest.approx(0.5 + 0.03 + 0.08, abs=0.02)
    again = await speech.synthesize("Zacznij dzień wolniej.", voice="neural:pl-PL-ZofiaNeural", lang="pl")
    assert again.cached and again.mime == "audio/wav" and again.data == first.data and calls == ["neural:pl-PL-ZofiaNeural"]
    en = await speech.synthesize("Wake up slowly.", voice="openai:nova", lang="en")
    assert en.mime == "audio/mpeg" and en.data == mp3_like  # the English default voice is passed through byte for byte
