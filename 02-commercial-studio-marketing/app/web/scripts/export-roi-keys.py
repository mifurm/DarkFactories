#!/usr/bin/env python3
"""Exports every ROI-model key the calculator UI renders (with its English source label) to src/i18n/roi-keys.json.

The Polish dictionary (src/i18n/pl/roi.ts) is keyed by these model keys; i18n.test.ts compares the two so a new lever, benefit, cost, service
family, sensitivity driver or override key can never reach the UI without a Polish label.

    npm run export:roi-keys            # rewrite src/i18n/roi-keys.json from the vendored model
    npm run export:roi-keys -- --check # exit 1 when the committed file is stale (no write)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from spotlight.vendor import model

OUT = Path(__file__).resolve().parent.parent / "src" / "i18n" / "roi-keys.json"


def build() -> dict[str, object]:
    a = model.load_assumptions()
    specs = model.override_specs()
    return {
        "_generated": "by scripts/export-roi-keys.py from spotlight.vendor.model — do not edit; run `npm run export:roi-keys`",
        "model_version": model.MODEL_VERSION,
        "roiScenario": dict(model.SCENARIO_LABELS),
        "roiLever": {"core": "Campaign studio (Release 1 scope)", **model.LEVER_LABELS},
        "roiTier": {k: v["label"] for k, v in a["tiers"].items()},
        "roiTierDesc": {k: v["description"] for k, v in a["tiers"].items()},
        "roiBenefit": dict(model.BENEFIT_LABELS),
        "roiCost": dict(model.COST_LABELS),
        "roiFamily": dict(model.FAMILY_LABELS),
        "roiSens": {d["id"]: d["label"] for d in a["sensitivity_drivers"]},
        "roiSpec": {k: s["label"] for k, s in specs.items()},
        "roiUnit": {u: u for u in sorted({s["unit"] for s in specs.values()})},
    }


def main(argv: list[str]) -> int:
    text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is stale — run `npm run export:roi-keys`", file=sys.stderr)
            return 1
        print("roi-keys.json is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parents[3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
