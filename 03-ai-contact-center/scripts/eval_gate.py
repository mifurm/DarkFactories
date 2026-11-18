#!/usr/bin/env python3
"""CI gate for prompt / policy / knowledge changes: runs the evaluation suite and compares it with the active baseline.

    python scripts/eval_gate.py                         # candidate == active configuration -> exit 0
    python scripts/eval_gate.py --broken remove_refund_cap   # deliberately broken candidate -> exit 1 (the gate blocks it)
    python scripts/eval_gate.py --base-url https://<app>...  # same, against a deployed instance (uses its model deployments)

Exit code 0 = gate passed, 1 = blocked. In-process mode uses the deterministic offline engine (no Azure needed); run it from the repository root
or the app/ folder with the app virtualenv."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "src"))


async def in_process(args: argparse.Namespace) -> int:
    from concierge.core.config import Settings
    from concierge.engine import evalrun
    from concierge.features.evals import BROKEN_VARIANTS, make_broken
    from concierge.services import build_services

    svc = build_services(Settings(mode="offline"))
    await svc.start()
    await svc.configs.load()
    await svc.backoffice.seed()
    await svc.kb.seed()
    try:
        baseline = await evalrun.run_suite(svc, args.suite)
        if args.broken:
            if args.broken not in BROKEN_VARIANTS:
                print(f"unknown variant {args.broken!r}; choose from {sorted(BROKEN_VARIANTS)}", file=sys.stderr)
                return 2
            candidate_cfg = await make_broken(svc, args.broken, "ci")
            report = await evalrun.run_suite(svc, args.suite, candidate_cfg)
            label = f"candidate: {candidate_cfg.name}"
        else:
            report = baseline
            label = "candidate: active configuration"
        verdict = evalrun.gate(report, baseline if args.broken else None)
        md = evalrun.render_markdown(report, verdict)
        print(f"{label}\n{md}")
        if args.markdown:
            Path(args.markdown).write_text(md)
        print("GATE:", "PASSED" if verdict["passed"] else "BLOCKED - " + "; ".join(verdict["reasons"]))
        return 0 if verdict["passed"] else 1
    finally:
        await svc.stop()


def remote(args: argparse.Namespace) -> int:
    import httpx

    h = {"X-Demo-Role": "admin"}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as c:
        body = {"suite": args.suite, **({"broken_variant": args.broken} if args.broken else {})}
        run = c.post("/api/evals/gate", json=body, headers=h)
        run.raise_for_status()
        run_id = run.json()["run_id"]
        for _ in range(300):
            r = c.get(f"/api/evals/runs/{run_id}", headers=h).json()
            if r["status"] == "done":
                break
            time.sleep(3)
        gate = r["gate"]
        print(f"run {run_id}: {r['totals']} dimensions={r['dimensions']} cost=${r['cost_usd']}")
        print("GATE:", "PASSED" if gate["passed"] else "BLOCKED - " + "; ".join(gate["reasons"]))
        return 0 if gate["passed"] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="core", choices=["core", "redteam", "all"])
    ap.add_argument("--broken", help="inject a deliberately broken configuration: remove_refund_cap | no_tools | always_escalate | no_citations")
    ap.add_argument("--base-url", help="run the gate on a deployed instance instead of in-process")
    ap.add_argument("--markdown", help="write the markdown report to this file")
    a = ap.parse_args()
    sys.exit(remote(a) if a.base_url else asyncio.run(in_process(a)))
