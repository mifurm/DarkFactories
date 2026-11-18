#!/usr/bin/env python
"""Vendor the business-case model into the app package (CS-23) and verify parity.

    python scripts/sync_business_case.py          # copy model.py / assumptions.json / outputs.json, then verify
    python scripts/sync_business_case.py --check  # verify only (exit 1 if the vendored copy is stale)

The calculator in the app and the PRD / deck must quote the SAME model, so the three files are copied verbatim from
``business-case/`` and a parity check recomputes every scenario against the published ``outputs.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "business-case"
DST = ROOT / "app" / "src" / "spotlight" / "vendor"
FILES = ("model.py", "assumptions.json", "outputs.json")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    stale = [f for f in FILES if not (DST / f).exists() or sha(SRC / f) != sha(DST / f)]
    if args.check:
        print("vendored copy is current" if not stale else f"STALE: {stale}")
        return 1 if stale else 0
    for f in FILES:
        shutil.copyfile(SRC / f, DST / f)
        print(f"copied {f} ({sha(DST / f)})")
    sys.path.insert(0, str(DST.parent.parent))
    from spotlight.vendor import model

    a = model.load_assumptions(str(DST / "assumptions.json"))
    ref = json.loads((DST / "outputs.json").read_text(encoding="utf-8"))
    bad = []
    for sc in model.SCENARIOS:
        live = model.compute(a, sc)
        for key in ("npv", "roi_pct", "payback_months", "irr_pct"):
            x, y = live["roi"][key], ref["scenarios"][sc]["roi"][key]
            if not ((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= max(0.005 * abs(y), 1e-6))):
                bad.append((sc, key, x, y))
    print("parity with outputs.json:", "OK" if not bad else f"MISMATCH {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
