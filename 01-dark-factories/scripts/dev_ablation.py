"""Dev helper: ablation of the swarm - each agent alone vs the baseline over the A/B fault schedule (calibration aid)."""
import sys

import numpy as np

from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.core import PlantCore
from nightshift.sim.faults import ab_fault_schedule


def run(seed, agents, swarm=True, horizon=480, warm=180, plant="KAT-1"):
    pc = PlantCore(plant, seed, swarm=swarm, agents=agents, sim_first="surrogate", headless_latency=20)
    pc.run(warm)
    snap0, t0 = pc.plant.current_snapshot(), pc.plant.t
    for t_off, kind, params in ab_fault_schedule(pc.cfg, seed, horizon, 1.0):
        pc.plant.schedule_fault(t0 + t_off, kind, **params)
    pc.run(horizon)
    k = KpiEngine.compute(pc.plant, base=snap0, cur=pc.plant.current_snapshot())
    p, i = k["plant_kpi"], k["impact_eur"]
    return dict(down_h=p["downtime_min"] / 60, tard_h=p["tardiness_h"], late=p["overdue_orders"], good=p["units_good"], kwh=p["energy_kwh"],
                ecost=p["energy_cost_eur"], scrap_eur=i["scrap"], esc=p["escapes"], loss=i["loss_total"], oee=(p["oee"] or 0) * 100)


if __name__ == "__main__":
    seeds = range(101, 101 + int(sys.argv[1] if len(sys.argv) > 1 else 8))
    configs = {"OFF": (None, False), "maint": ({"maintenance"}, True), "planner": ({"planner"}, True), "quality": ({"quality"}, True),
               "materials": ({"materials"}, True), "energy": ({"energy"}, True), "safety": ({"safety"}, True), "ALL": (None, True)}
    base = None
    for name, (ag, sw) in configs.items():
        rows = [run(s, ag, sw) for s in seeds]
        m = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
        base = base or m
        print(f"{name:10s}", " ".join(f"{k}={v:7.1f}({v - base[k]:+6.1f})" for k, v in m.items()))
