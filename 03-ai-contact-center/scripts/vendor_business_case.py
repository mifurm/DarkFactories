#!/usr/bin/env python3
"""Vendors the business-case model into the application package (CC-13 ROI / Azure-ACR calculator).

The calculator serves the *same* `model.py` and `assumptions.json` that produced `business-case/outputs.json`; a unit test asserts parity
(NPV, ROI %, payback, Year-3 ACR within 0.5 %). Run after the business case changes:  python scripts/vendor_business_case.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "business-case"
DST = ROOT / "app" / "src" / "concierge" / "features" / "metrics" / "business_case"
FILES = ("model.py", "assumptions.json", "outputs.json")


def main() -> int:
    missing = [f for f in FILES if not (SRC / f).exists()]
    if missing:
        print(f"business-case files missing: {missing}", file=sys.stderr)
        return 1
    DST.mkdir(parents=True, exist_ok=True)
    (DST / "__init__.py").write_text('"""Vendored copy of business-case/ (see PROVENANCE.json). Do not edit - re-run scripts/vendor_business_case.py."""\n', encoding="utf-8")
    prov = {"vendored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "business-case/", "files": {}}
    for name in FILES:
        shutil.copyfile(SRC / name, DST / name)
        prov["files"][name] = hashlib.sha256((SRC / name).read_bytes()).hexdigest()
    (DST / "PROVENANCE.json").write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    print(f"vendored {', '.join(FILES)} -> {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
