"""Render worker: run in a subprocess so CPU-heavy compositing never blocks the web process.

    python -m spotlight.video.worker <job_dir>

<job_dir>/job.json = {"spec": {...}, "assets": {asset_id: relpath}, "vo": {vo_id: relpath}, "timeout": 420}
Progress is reported as ``PROGRESS <0..1> <message>`` lines; the final line is ``RESULT <json>``.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from .renderer import render
from .spec import RenderSpec


def main(job_dir: str) -> int:
    root = Path(job_dir)
    job = json.loads((root / "job.json").read_text())
    spec = RenderSpec.model_validate(job["spec"])
    images = {k: (root / v).read_bytes() for k, v in job["assets"].items()}
    vo = {k: (root / v).read_bytes() for k, v in job["vo"].items()}

    def progress(p: float, msg: str) -> None:
        print(f"PROGRESS {p:.4f} {msg}", flush=True)

    try:
        result = render(spec, images, vo, root / "out", progress, float(job.get("timeout", 420)))
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    print("RESULT " + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
