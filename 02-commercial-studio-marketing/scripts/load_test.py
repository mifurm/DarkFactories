#!/usr/bin/env python
"""Light load check against a deployed Spotlight instance: p50/p95/p99 latency per endpoint, error rate, throughput.

    python scripts/load_test.py --base-url https://<app>.azurecontainerapps.io [--requests 300] [--concurrency 20]

Read-only / CPU-only endpoints (no Azure OpenAI spend). The in-process rate limiter protects spend/mutation routes only,
so these GETs measure the real service path: ingress -> FastAPI -> Cosmos DB (serverless) -> JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/healthz", None),
    ("GET", "/api/features", None),
    ("GET", "/api/studio/overview", None),
    ("GET", "/api/library/assets?limit=24", None),
    ("GET", "/api/claims", None),
    ("GET", "/api/budget", None),
    ("GET", "/api/brand", None),
    ("POST", "/api/roi/compute", {"scenario": "base"}),
]


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


async def worker(client: httpx.AsyncClient, queue: asyncio.Queue, out: dict[str, list[tuple[float, int]]]) -> None:
    while True:
        try:
            method, path, body = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        t0 = time.perf_counter()
        try:
            r = await client.request(method, path, json=body, headers={"X-Studio-Role": "creative", "X-Studio-User": "load-test"})
            status = r.status_code
        except Exception:
            status = 599
        out[f"{method} {path.split('?')[0]}"].append(((time.perf_counter() - t0) * 1000, status))


async def run(base: str, total: int, concurrency: int) -> int:
    out: dict[str, list[tuple[float, int]]] = {f"{m} {p.split('?')[0]}": [] for m, p, _ in ENDPOINTS}
    queue: asyncio.Queue = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(ENDPOINTS[i % len(ENDPOINTS)])
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base, timeout=60, limits=limits) as client:
        await client.get("/healthz")  # warm the connection / replica
        t0 = time.perf_counter()
        await asyncio.gather(*[worker(client, queue, out) for _ in range(concurrency)])
        wall = time.perf_counter() - t0
    print(f"\nLoad check: {total} requests, concurrency {concurrency}, wall {wall:.1f}s, {total / wall:.1f} req/s\n")
    print("| Endpoint | n | p50 ms | p95 ms | p99 ms | max ms | errors |\n|---|---|---|---|---|---|---|")
    all_lat: list[float] = []
    errors = 0
    for name, rows in out.items():
        lat = [r[0] for r in rows]
        err = sum(1 for r in rows if r[1] >= 400)
        errors += err
        all_lat += lat
        print(f"| {name} | {len(lat)} | {statistics.median(lat):.0f} | {pct(lat, 95):.0f} | {pct(lat, 99):.0f} | {max(lat):.0f} | {err} |")
    print(f"| **all** | {len(all_lat)} | {statistics.median(all_lat):.0f} | {pct(all_lat, 95):.0f} | {pct(all_lat, 99):.0f} | {max(all_lat):.0f} | {errors} |")
    print(f"\nLOAD_P50_MS={statistics.median(all_lat):.0f} LOAD_P95_MS={pct(all_lat, 95):.0f} ERRORS={errors}")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()
    return asyncio.run(run(args.base_url.rstrip("/"), args.requests, args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
