#!/usr/bin/env python
"""Calibrate the speaking-rate model of a language against REAL Azure neural voices (reproduces ``app/evidence/pl-tts-calibration.json``).

    python scripts/calibrate_tts.py --lang pl [--voice neural:pl-PL-ZofiaNeural] [--lines my_lines.txt] [--out calibration-pl.json]

Needs ``AZURE_OPENAI_ENDPOINT`` and ``AI_ENDPOINT`` (the Azure AI Services account; keyless — your ``az login`` identity needs the Cognitive Services roles).
It runs on hybrid backends — real Azure AI Speech, in-memory repository and blobs — and never touches the deployed Cosmos DB / Blob storage.

Every line goes through the production text path (``spoken_text`` + the brand pronunciations of the language's kit); the length of the trimmed audio is measured and
a least-squares fit gives ``speech = syllables / rate + pause_per_sentence_stop * stops + pause_per_comma * commas``; the mean silence left around the trimmed audio is
the suggested ``LINE_PAD``. Copy the constants into ``app/src/spotlight/domain/timing.py`` (SYLLABLE_RATE, SENTENCE_PAUSE, COMMA_PAUSE, LINE_PAD) and keep
HEADROOM below MAX_SPEED / (1 + worst under-estimate). The report also scores the constants that are currently shipped. 24 lines cost ≈ US$0.02.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "src"))

from spotlight.config import Settings
from spotlight.domain.polish import spoken_text
from spotlight.domain.text import syllables, words
from spotlight.domain.timing import estimate_vo_seconds
from spotlight.seed.data import KIT
from spotlight.services import build_services
from spotlight.video import media

DEFAULT_VOICES = {"pl": "neural:pl-PL-ZofiaNeural"}
DEFAULT_LINES = {
    "pl": [
        "Zacznij dzień wolniej.", "Dawn Roast. Średnie palenie, palone w małych partiach.", "Karmel, pomarańcza, kakao. Bez pośpiechu.", "Obudź się powoli.",
        "Najpierw jedna cicha filiżanka.", "Jest godzina, która należy tylko do ciebie.", "Nalewaj powoli. Reszta może poczekać.", "Znajdź Dawn Roast w pobliżu.",
        "Dziesięć cichych minut, zanim zacznie się dzień.", "Próbujemy każdą partię, bo pierwsza filiżanka znaczy najwięcej.", "Zanim dom się obudzi, jest cicha godzina.",
        "Dawn Roast daje spokojniejszy początek poranka. Karmel, pomarańcza, kakao.", "Wolny start, dobrze zrobiony.", "Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży.",
        "Kiedy ostatnio twój poranek zaczął się powoli?", "Wolniejszy początek dnia.", "Pierwsza filiżanka należy tylko do ciebie.", "Poranek nie musi zaczynać się od hałasu.",
        "Zaparz kawę, usiądź przy oknie i nie spiesz się nigdzie.", "Northwind Coffee Roasters. Palone w małych partiach, z troską o każdy szczegół.",
        "Spróbuj Dawn Roast już dziś. Znajdziesz go w sklepach w całej Polsce.", "Cisza, para nad kubkiem i światło, które dopiero się budzi.",
        "Nie każdy poranek musi być pospieszny. Ten może być twój.", "Karmel, skórka pomarańczy i kakao w każdej filiżance.",
    ],
}
SILENCE_FLOOR = 10 ** (-42 / 20)


async def measure(lines: list[str], lang: str, voice: str) -> list[dict[str, Any]]:
    aoai, ai = os.environ.get("AZURE_OPENAI_ENDPOINT", ""), os.environ.get("AI_ENDPOINT", "")
    if not (aoai and ai):
        sys.exit("set AZURE_OPENAI_ENDPOINT and AI_ENDPOINT (the Azure AI Services account; keyless, your az login is used)")
    settings = Settings(
        spotlight_mode="azure", ai_backend="azure", repo_backend="memory", blob_backend="memory", cosmos_endpoint="", blob_account_url="",
        azure_openai_endpoint=aoai, ai_endpoint=ai, daily_ai_budget_usd=0.5,
    )
    pron = KIT.get("i18n", {}).get(lang, {}).get("voice", {}).get("pronunciations", {})
    svc = await build_services(settings)
    rows: list[dict[str, Any]] = []
    try:
        for text in lines:
            spoken = spoken_text(text, lang, pron)
            res = await svc.speech.synthesize(spoken, voice=voice, lang=lang, speed=1.0)
            natural = media.audio_duration(res.data)
            level = np.abs(media.decode_audio(res.data)).max(axis=1)
            loud = np.nonzero(level > SILENCE_FLOOR)[0]
            lead, trail = float(loud[0]) / media.SR, float(len(level) - 1 - loud[-1]) / media.SR
            rows.append({
                "text": text, "spoken": spoken, "nat": round(natural, 3), "lead": round(lead, 3), "trail": round(trail, 3), "speech": round(natural - lead - trail, 3),
                "est": estimate_vo_seconds(spoken, lang), "syll": sum(syllables(w, lang) for w in words(spoken)),
                "stops": sum(1 for i, ch in enumerate(spoken[:-1]) if ch in ".!?…" and spoken[i + 1] == " "),
                "commas": sum(spoken[:-1].count(c) for c in ",;:"), "cost": res.cost_usd,
            })
            r = rows[-1]
            print(f"speech {r['speech']:5.2f}s (lead {lead:4.2f} trail {trail:4.2f})  shipped model {r['est']:5.2f}s  syll {r['syll']:3d} stops {r['stops']} commas {r['commas']}  {spoken}")
    finally:
        await svc.close()
    return rows


def report(rows: list[dict[str, Any]]) -> None:
    x = np.array([[r["syll"], r["stops"], r["commas"]] for r in rows], dtype=float)
    y = np.array([r["speech"] for r in rows])
    (per_syll, stop_pause, comma_pause), *_ = np.linalg.lstsq(x, y, rcond=None)
    pad = float(np.mean([r["lead"] + r["trail"] for r in rows]))
    print(f"\nfit: speech = {per_syll:.4f} * syllables + {stop_pause:.3f} * sentence_stops + {comma_pause:.3f} * commas")
    print(f"=> SYLLABLE_RATE {1 / per_syll:.2f} syll/s, SENTENCE_PAUSE {stop_pause:.2f} s, COMMA_PAUSE {comma_pause:.2f} s, LINE_PAD {pad:.2f} s")
    rel = np.array([(r["est"] - r["nat"]) / r["nat"] for r in rows])
    print(f"shipped model vs measured length: RMSE {math.sqrt(float(np.mean(rel ** 2))) * 100:.1f} %, bias {float(np.mean(rel)) * 100:+.1f} %, worst under-estimate {float(-rel.min()) * 100:.1f} %")
    print(f"TTS cost US$ {sum(r['cost'] for r in rows):.5f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", default="pl")
    ap.add_argument("--voice", help="neural:<voice name> (default: the language's default voice)")
    ap.add_argument("--lines", type=Path, help="text file, one line per row (default: the shipped Polish set)")
    ap.add_argument("--out", type=Path, help="write the measurements as JSON")
    args = ap.parse_args()
    voice = args.voice or DEFAULT_VOICES.get(args.lang)
    lines = [ln.strip() for ln in args.lines.read_text(encoding="utf-8").splitlines() if ln.strip()] if args.lines else DEFAULT_LINES.get(args.lang)
    if not voice or not lines:
        sys.exit(f"no default voice / lines for {args.lang!r}: pass --voice neural:<name> and --lines <file>")
    rows = asyncio.run(measure(lines, args.lang, voice))
    report(rows)
    if args.out:
        args.out.write_text(json.dumps({"voice": voice, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("written", args.out)


if __name__ == "__main__":
    main()
