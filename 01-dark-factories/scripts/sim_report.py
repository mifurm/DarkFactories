"""Dev helper: run the simulator headless and print a KPI summary (no agents) - used to calibrate/inspect the plant model.

    PYTHONPATH=app/src app/.venv/bin/python scripts/sim_report.py --plant KAT-1 --hours 24 --seed 7
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

from nightshift.sim.config import build_plant_config
from nightshift.sim.plant import Plant


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant", default="KAT-1")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fault", action="append", default=[], help="kind:target@minute, e.g. bearing_wear:CNC-04@30")
    args = ap.parse_args()
    cfg = build_plant_config(args.plant)
    p = Plant(cfg, seed=args.seed)
    for f in args.fault:
        head, _, at = f.partition("@")
        kind, _, target = head.partition(":")
        key = {"supplier_delay": "material", "human_intrusion": "zone", "rush_order": "sku"}.get(kind, "asset")
        p.schedule_fault(int(at or 0), kind, **({key: target} if target else {}))
    t0 = time.perf_counter()
    p.run(int(args.hours * 60))
    dt = time.perf_counter() - t0
    print(f"{cfg.plant_id}: {args.hours} h simulated in {dt:.2f}s ({dt / (args.hours * 60) * 1000:.2f} ms/tick)")
    acc = p.acc
    print("good units/h:", round(acc["units_good"] / args.hours, 1), "| orders done:", int(acc["orders_completed"]),
          "on-time:", int(acc["orders_on_time"]), "| open:", len(p.open_orders()))
    print("energy kWh:", round(acc["energy_kwh"]), "cost EUR:", round(acc["energy_cost"]), "| peak kW:", round(acc["peak_kw"]))
    print("scrap units:", round(acc["scrap_units"], 1), "escapes:", round(acc["escapes"], 1), "| unplanned downtime min:", round(acc["downtime_unplanned_min"]))
    by_type: dict[str, Counter] = {}
    for spec in cfg.assets:
        by_type.setdefault(spec.type, Counter()).update(p.assets[spec.id].mins)
    for ty, c in by_type.items():
        tot = sum(c.values()) or 1
        print(f"  {ty:6s}", " ".join(f"{k}:{v / tot * 100:4.0f}%" for k, v in c.items() if v))


if __name__ == "__main__":
    main()
