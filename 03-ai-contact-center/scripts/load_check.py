#!/usr/bin/env python3
"""Light load check of a deployed instance: read-API latency under concurrency, chat turn latency and time-to-first-token (streamed), voice
first-audio latency. Reports p50 / p95 / max and the AI spend of the run.

    python scripts/load_check.py --base-url https://<app>.azurecontainerapps.io [--chat 12] [--voice 3] [--concurrency 6] [--json load.json]

Defaults keep the spend around 0.1 USD. Needs: pip install httpx"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

CUSTOMER = {"X-Demo-Role": "customer"}
ADMIN = {"X-Demo-Role": "admin"}
QUESTIONS = ["What is the return window?", "How much does installing a washing machine cost?", "How do I schedule a return pickup?", "What is the warranty on a mattress?", "How are refunds paid?", "What are the delivery windows?"]


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def summary(xs: list[float]) -> dict[str, Any]:
    return {"n": len(xs), "p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "max": round(max(xs), 1) if xs else None, "mean": round(statistics.mean(xs), 1) if xs else None}


def read_api(base: str, n: int, concurrency: int) -> dict[str, Any]:
    paths = ["/api/meta", "/api/features", "/api/usage", "/api/metrics", "/api/voc/summary", "/api/wfm/queues", "/api/routing/queues", "/healthz"]
    lat: list[float] = []
    errors = 0

    def one(i: int) -> None:
        nonlocal errors
        with httpx.Client(base_url=base, timeout=60) as c:
            t0 = time.perf_counter()
            r = c.get(paths[i % len(paths)], headers=ADMIN)
            lat.append((time.perf_counter() - t0) * 1000)
            errors += r.status_code >= 500

    t0 = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as ex:
        list(ex.map(one, range(n)))
    wall = time.perf_counter() - t0
    return {**summary(lat), "errors": errors, "rps": round(n / wall, 1), "concurrency": concurrency}


def chat_turn(base: str, i: int) -> tuple[float, float | None, bool]:
    with httpx.Client(base_url=base, timeout=120) as c:
        sid = c.post("/api/chat/sessions", json={"language": "en", "recording_consent": "granted"}, headers=CUSTOMER).json()["session"]["id"]
        t0 = time.perf_counter()
        ttft = None
        ok = False
        with c.stream("POST", f"/api/chat/sessions/{sid}/stream", json={"text": QUESTIONS[i % len(QUESTIONS)]}, headers=CUSTOMER) as r:
            for line in r.iter_lines():
                if ttft is None and '"token"' in line:
                    ttft = (time.perf_counter() - t0) * 1000
                if '"turn_done"' in line:
                    ok = True
        return (time.perf_counter() - t0) * 1000, ttft, ok


def chat(base: str, n: int, concurrency: int) -> dict[str, Any]:
    with ThreadPoolExecutor(concurrency) as ex:
        rows = list(ex.map(lambda i: chat_turn(base, i), range(n)))
    return {"turn_ms": summary([r[0] for r in rows]), "ttft_ms": summary([r[1] for r in rows if r[1]]), "completed": sum(r[2] for r in rows), "sessions": n, "concurrency": concurrency}


def voice(base: str, n: int) -> dict[str, Any]:
    first, total, modes = [], [], []
    with httpx.Client(base_url=base, timeout=180) as c:
        for i in range(n):
            r = c.post("/api/voice/text-turn", json={"text": QUESTIONS[i % len(QUESTIONS)], "language": "en", "mode": "auto", "wait_s": 45}).json()
            if r.get("first_audio_ms"):
                first.append(r["first_audio_ms"])
            total.append(r.get("total_ms", 0))
            modes.append(r.get("mode"))
    return {"first_audio_ms": summary(first), "total_ms": summary(total), "modes": sorted(set(map(str, modes))), "turns": n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--reads", type=int, default=200)
    ap.add_argument("--chat", type=int, default=12)
    ap.add_argument("--voice", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--json")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    c = httpx.Client(base_url=base, timeout=60)
    spent0 = c.get("/api/usage").json()["spent_usd"]
    out: dict[str, Any] = {"base_url": base, "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "meta": {k: c.get("/api/meta").json().get(k) for k in ("build_id", "mode", "region")}}
    print(f"Load check against {base}")
    out["read_api_ms"] = read_api(base, a.reads, a.concurrency)
    print("  read API      ", out["read_api_ms"])
    if a.chat:
        out["chat"] = chat(base, a.chat, a.concurrency)
        print("  chat turns    ", out["chat"])
    if a.voice:
        out["voice"] = voice(base, a.voice)
        print("  voice (text)  ", out["voice"])
    out["ai_spend_usd"] = round(c.get("/api/usage").json()["spent_usd"] - spent0, 3)
    print(f"  AI spend of this run: ${out['ai_spend_usd']}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=2)
    errors = out["read_api_ms"]["errors"] + (a.chat - out.get("chat", {}).get("completed", a.chat))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
