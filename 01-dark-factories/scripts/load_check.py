#!/usr/bin/env python3
"""Light load check: N read requests at a given concurrency against a running instance; prints p50/p95/p99 and error counts.

    python scripts/load_check.py --base-url https://<app>.azurecontainerapps.io --requests 200 --concurrency 20
"""

from __future__ import annotations

import argparse
import json
import http.client
import statistics
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

PATHS = [
    "/healthz",
    "/api/tower/snapshot",
    "/api/kpi?window_hours=8",
    "/api/ledger?limit=20",
    "/api/swarm/agents",
    "/api/planner/schedule",
    "/api/maintenance/health",
    "/api/energy/summary",
    "/api/fleet/compare",
    "/api/features",
]


_local = threading.local()


def _conn(base: str) -> http.client.HTTPConnection:
    c = getattr(_local, "c", None)
    if c is None:
        u = urllib.parse.urlparse(base)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        c = _local.c = cls(u.netloc, timeout=30)
    return c


def one(base: str, path: str) -> tuple[str, float, int]:
    """One GET over a persistent (keep-alive) connection per worker thread, so TLS/TCP set-up is not counted in every sample."""
    t0 = time.perf_counter()
    code = 0
    for attempt in range(2):
        try:
            c = _conn(base)
            c.request("GET", path, headers={"Accept": "application/json"})
            r = c.getresponse()
            r.read()
            code = r.status
            break
        except Exception:  # noqa: BLE001
            _local.c = None
            if attempt == 1:
                code = 0
    return path, (time.perf_counter() - t0) * 1000, code


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    jobs = [PATHS[i % len(PATHS)] for i in range(a.requests)]
    rtt = [one(base, "/healthz")[1] for _ in range(8)][2:]  # sequential keep-alive round trips = network RTT + trivial handler
    for p in PATHS[:3]:  # warm-up
        one(base, p)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        res = list(ex.map(lambda p: one(base, p), jobs))
    wall = time.perf_counter() - t0
    lat = [ms for _, ms, c in res if c == 200]
    errors = sum(1 for _, _, c in res if c != 200)
    out = {
        "requests": a.requests,
        "concurrency": a.concurrency,
        "wall_s": round(wall, 2),
        "rps": round(a.requests / wall, 1),
        "ok": len(lat),
        "errors": errors,
        "p50_ms": round(statistics.median(lat), 1) if lat else None,
        "p95_ms": round(pct(lat, 95), 1) if lat else None,
        "p99_ms": round(pct(lat, 99), 1) if lat else None,
        "max_ms": round(max(lat), 1) if lat else None,
        "baseline_healthz_rtt_ms": round(statistics.median(rtt), 1),
        "per_path": {},
    }
    for p in PATHS:
        xs = [ms for path, ms, c in res if path == p and c == 200]
        if xs:
            out["per_path"][p] = {"n": len(xs), "p50_ms": round(statistics.median(xs), 1), "p95_ms": round(pct(xs, 95), 1)}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"{a.requests} requests @ {a.concurrency} concurrent against {base}: {out['rps']} req/s, {errors} errors")
        print(f"sequential /healthz round trip (network RTT floor): {out['baseline_healthz_rtt_ms']} ms")
        print(f"latency  p50 {out['p50_ms']} ms   p95 {out['p95_ms']} ms   p99 {out['p99_ms']} ms   max {out['max_ms']} ms")
        for p, v in out["per_path"].items():
            print(f"  {p:<28} n={v['n']:<3} p50 {v['p50_ms']:>7} ms  p95 {v['p95_ms']:>7} ms")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
