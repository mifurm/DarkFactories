#!/usr/bin/env python3
"""Hybrid development server: REAL Azure OpenAI / Speech / Language / Content Safety with IN-MEMORY data.

The deployed (English) demo is served from the live Cosmos DB and Blob storage. This script never touches them: it builds the services with
`build_services(settings, repo=InMemoryRepository(), blobs=MemoryBlobStore())`, so only the AI calls are real (Entra token of the `az login` user,
read-only use of the credential, no keys). It is how the Polish eval pack, red-team pack, chat / refund tool flow and voice path are exercised on the
real models before a deployment, and how `smoke_test.py` is run locally.

    .venv/bin/python scripts/dev_hybrid.py --check                # credentials + one tiny probe per AI service (a few hundredths of a cent), exit 0 = ready
    .venv/bin/python scripts/dev_hybrid.py                        # serve http://127.0.0.1:8103 (UI + API; Ctrl-C to stop)
    python scripts/smoke_test.py --base-url http://127.0.0.1:8103 --lang pl
    python scripts/eval_gate.py --base-url http://127.0.0.1:8103 --suite pl-smoke

The daily AI budget guard of the app (`UsageMeter`, fails closed) is the hard spend cap of the process: `--budget` (default US$2.50)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "src"))

AI_KEYS = ("AZURE_OPENAI_ENDPOINT", "AI_SERVICES_ENDPOINT", "AZURE_AI_SERVICES_NAME")  # nothing else is ever read: no Cosmos / Storage endpoint enters this process
LIVE_DATA_ENV = ("COSMOS_ENDPOINT", "COSMOS_DATABASE", "STORAGE_ACCOUNT_URL")


def azd_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_file in sorted((ROOT / ".azure").glob("*/.env")):
        for line in env_file.read_text().splitlines():
            m = re.match(r'^([A-Z0-9_]+)="?([^"]*)"?$', line.strip())
            if m and m.group(1) in AI_KEYS:
                values.setdefault(m.group(1), m.group(2))
    return values


def ai_endpoints() -> tuple[str, str]:
    """Azure OpenAI and AI Services endpoints: environment first, then the azd environment of the deployed app (only these keys are read)."""
    found = azd_values()
    openai_ep = (os.environ.get("AZURE_OPENAI_ENDPOINT") or found.get("AZURE_OPENAI_ENDPOINT", "")).rstrip("/")
    services = os.environ.get("AI_SERVICES_ENDPOINT") or found.get("AI_SERVICES_ENDPOINT", "")
    if not services and found.get("AZURE_AI_SERVICES_NAME"):
        services = f"https://{found['AZURE_AI_SERVICES_NAME']}.cognitiveservices.azure.com"
    if not openai_ep or not services:
        sys.exit("AZURE_OPENAI_ENDPOINT / AI_SERVICES_ENDPOINT are not set and no azd environment was found (.azure/*/.env)")
    return openai_ep, services.rstrip("/")


def build_hybrid(budget_usd: float):
    from concierge.core.blobstore import MemoryBlobStore
    from concierge.core.config import Settings
    from concierge.core.repo import InMemoryRepository
    from concierge.services import build_services

    for name in LIVE_DATA_ENV:
        os.environ.pop(name, None)  # defence in depth: the live data endpoints are not even visible to this process
    openai_ep, services_ep = ai_endpoints()
    web_dist = ROOT / "app" / "web" / "dist"
    settings = Settings(
        mode="azure", openai_endpoint=openai_ep, ai_services_endpoint=services_ep, cosmos_endpoint="", storage_account_url="", daily_budget_usd=budget_usd,
        build_id="hybrid-local", region="local-hybrid", static_dir=str(web_dist) if web_dist.is_dir() else "", seed_on_start=True,
    )  # fmt: skip
    svc = build_services(settings, repo=InMemoryRepository(), blobs=MemoryBlobStore())
    assert type(svc.repo).__name__ == "InMemoryRepository" and type(svc.blobs).__name__ == "MemoryBlobStore", "the hybrid server must never use live storage"
    assert not settings.cosmos_endpoint and not settings.storage_account_url
    return settings, svc


async def check(budget_usd: float) -> int:
    """One tiny probe per AI service, including the Polish-specific ones; prints what answered (never a token or a key)."""
    from concierge.core.azure_auth import get_token

    _, svc = build_hybrid(budget_usd)
    await svc.start()
    failures = 0

    async def probe(name: str, coro) -> None:
        nonlocal failures
        t0 = time.perf_counter()
        try:
            out = await coro
            print(f"  ok    {name:<34} {1000 * (time.perf_counter() - t0):6.0f} ms  {out}")
        except Exception as exc:  # a diagnostic tool reports every failure kind
            failures += 1
            print(f"  FAIL  {name:<34} {type(exc).__name__}: {str(exc)[:160]}")

    async def token() -> str:
        return "Entra token acquired (az login user)" if await get_token(svc.settings.client_id) else "no token"

    async def language_pl() -> str:
        lang, conf = await svc.cognitive.detect_language("Dzień dobry, chciałbym zwrócić uszkodzoną kanapę.")
        return f"detect_language -> {lang} ({conf:.2f})"

    async def pii_pl() -> str:
        ents = await svc.cognitive.pii_entities("Nazywam się Anna Kowalska, mój PESEL to 44051401359, e-mail anna@example.pl", "pl")
        return "pii categories: " + ", ".join(sorted({e.category for e in ents})) if ents else "pii: no entities"

    async def chat() -> str:
        res = await svc.llm.chat([{"role": "user", "content": "Odpowiedz jednym słowem po polsku: jaki kolor ma trawa?"}], role="chat", max_tokens=300, feature="check")
        return f"{svc.llm.model_for('chat')} -> {res.text.strip()[:40]!r}"

    async def embed() -> str:
        vecs = await svc.llm.embed(["zwrot kanapy", "return of a sofa"], feature="check")
        return f"{svc.llm.model_for('embed')} dims={len(vecs[0])}"

    async def tts_stt() -> str:
        audio, mime = await svc.speech.synthesize("Dzień dobry, tu Concierge. Zwrot wynosi 1 599 złotych.", language="pl")
        heard = await svc.speech.transcribe(audio, mime=mime, language="pl")
        return f"pl-PL TTS {len(audio) // 1024} KiB {mime}; STT heard: {heard.text.strip()[:70]!r}"

    await probe("Entra credential", token())
    await probe("Azure OpenAI chat (Polish)", chat())
    await probe("Azure OpenAI embeddings", embed())
    await probe("Azure Language: language detection", language_pl())
    await probe("Azure Language: PII (pl)", pii_pl())
    await probe("Speech: pl-PL TTS -> STT round trip", tts_stt())
    snap = svc.meter.snapshot()
    print(f"spent ${snap['spent_usd']:.4f} of the ${snap['budget_usd']:.2f} budget guard; repository={type(svc.repo).__name__}, blobs={type(svc.blobs).__name__}")
    await svc.stop()
    return 1 if failures else 0


def serve(port: int, budget_usd: float) -> None:
    import uvicorn

    from concierge.main import create_app

    settings, svc = build_hybrid(budget_usd)
    app = create_app(settings, services=svc)
    host = settings.openai_endpoint.split("//")[-1].split(".")[0]
    print(f"HYBRID server on http://127.0.0.1:{port} - real AI ({host}), in-memory repository and blobs (never the live Cosmos DB / Blob), AI budget guard US${budget_usd:.2f}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8103)
    ap.add_argument("--budget", type=float, default=2.5, help="hard AI spend cap of this process in US$ (the app's budget guard fails closed)")
    ap.add_argument("--check", action="store_true", help="probe credentials and every AI service once, then exit")
    ns = ap.parse_args()
    if ns.check:
        sys.exit(asyncio.run(check(ns.budget)))
    serve(ns.port, ns.budget)
