"""A/B replay (DF-21): the same seeds and the same fault schedule with the swarm OFF vs ON; paired deltas with confidence intervals."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from nightshift.features.df04_swarm.core import WorldView
from nightshift.features.df07_planner.scheduler import build_schedule
from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.features.df21_value.stats import paired_summary
from nightshift.plant.core import PlantCore
from nightshift.sim.config import build_plant_config
from nightshift.sim.faults import ab_fault_schedule

# metric -> (label, unit, lower_is_better)
METRICS: dict[str, tuple[str, str, bool]] = {
    "downtime_h": ("Unplanned downtime", "h", True),
    "tardiness_h": ("Order tardiness (realised + forecast backlog due < 24 h)", "h", True),
    "late_orders": ("Late orders (realised + forecast)", "orders", True),
    "scrap_units": ("Scrap", "units", True),
    "escapes": ("Customer escapes", "units", True),
    "energy_cost_eur": ("Energy cost (absolute, not normalised)", "EUR", True),
    "energy_cost_per_op": ("Energy cost per unit-operation processed", "EUR", True),
    "energy_price_eur_kwh": ("Effective energy price paid (cost / kWh)", "EUR/kWh", True),
    "loss_eur": ("Total loss (downtime, scrap, escapes, tardiness, maintenance)", "EUR", True),
    "oee": ("OEE", "pts", False),
    "otif": ("OTIF", "pts", False),
    "units_good": ("Good units shipped", "units", False),
}


WINDOW_START = {"night": "22:00", "day": "06:00", "late": "14:00"}


@dataclass
class ABConfig:
    seeds: list[int] = field(default_factory=lambda: list(range(101, 117)))
    horizon_h: float = 8.0
    warmup_min: int = 180
    intensity: float = 1.0
    plant: str = "KAT-1"
    latency_min: int = 20
    window: str = "late"  # plant clock at the start of the replay window: night 01:00, day 09:00, late 17:00 (after the 3 h warm-up)


def run_arm(
    cfg: ABConfig,
    seed: int,
    swarm: bool,
    agents: set[str] | None = None,
    faults: list[tuple[int, str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """One replay arm. ``agents`` restricts the swarm (ablation); ``faults`` overrides the seeded fault schedule (offsets in minutes)."""
    pcfg = copy.deepcopy(build_plant_config(cfg.plant))
    pcfg.assumptions["time"]["start"] = f"2026-11-17T{WINDOW_START[cfg.window]}"
    pc = PlantCore(pcfg, seed, swarm=swarm, agents=agents, sim_first="surrogate", headless_latency=cfg.latency_min)
    pc.run(cfg.warmup_min)
    plant = pc.plant
    snap0 = plant.current_snapshot()
    t0 = plant.t
    horizon = int(cfg.horizon_h * 60)
    schedule = faults if faults is not None else ab_fault_schedule(pc.cfg, seed, horizon, cfg.intensity)
    for t_off, kind, params in schedule:
        plant.schedule_fault(t0 + t_off, kind, **params)
    pc.run(horizon)
    k = KpiEngine.compute(plant, base=snap0, cur=plant.current_snapshot())
    pk, imp = k["plant_kpi"], k["impact_eur"]
    late_completed = plant.acc["orders_completed"] - snap0["orders_completed"] - pk["orders_on_time"]
    proj = build_schedule(
        WorldView(plant), "cr"
    )  # same yardstick for both arms: forecast of the backlog from the end state
    due_soon = [o for o in plant.open_orders() if o.due <= plant.t + 24 * 60]
    proj_tard = sum(max(0.0, proj.order_end.get(o.id, plant.t) - o.due) for o in due_soon) / 60.0
    proj_late = sum(1 for o in due_soon if proj.order_end.get(o.id, plant.t) > o.due)
    return {
        "downtime_h": pk["downtime_min"] / 60.0,
        "tardiness_h": pk["tardiness_h"] + proj_tard,
        "late_orders": float(late_completed + proj_late),
        "realized_tardiness_h": pk["tardiness_h"],
        "scrap_units": pk["scrap_units"],
        "escapes": pk["escapes"],
        "energy_cost_eur": pk["energy_cost_eur"],
        "energy_cost_per_unit": pk["energy_cost_eur"] / pk["units_good"] if pk["units_good"] > 0 else 0.0,
        "loss_eur": imp["loss_total"] + imp["tardiness_open"],
        "oee": pk["oee"] or 0.0,
        "otif": pk["otif"] if pk["otif"] is not None else 1.0,
        "units_good": pk["units_good"],
        "energy_kwh": pk["energy_kwh"],
        "kwh_per_unit": pk["kwh_per_unit"] or 0.0,
        "co2_per_unit_kg": pk["co2_per_unit_kg"] or 0.0,
        "failures": pk["failures"],
        "energy_cost_per_op": pk["energy_cost_eur"] / max(1.0, plant.acc["units_total"] - snap0["units_total"]),
        "energy_price_eur_kwh": pk["energy_cost_eur"] / max(1.0, pk["energy_kwh"]),
        "loss_breakdown": {kk: round(vv, 1) for kk, vv in imp.items()},
        "ledger_entries": len(pc.ledger) if swarm else 0,
        "auto_actions": pc.supervisor.stats["executed"] if swarm else 0,
        "approvals": pc.supervisor.stats["approvals"] if swarm else 0,
    }


def run_seed(cfg: ABConfig, seed: int) -> dict[str, Any]:
    """Both arms of one seed. Module-level so the API can run it in a worker process (see router.run_job)."""
    return {"seed": seed, "off": run_arm(cfg, seed, swarm=False), "on": run_arm(cfg, seed, swarm=True)}


def run_ab(cfg: ABConfig, progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    t_start = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for seed in cfg.seeds:
        rows.append(run_seed(cfg, seed))
        if progress:
            progress(len(rows), len(cfg.seeds))
    return summarize(cfg, rows, time.perf_counter() - t_start)


def summarize(cfg: ABConfig, rows: list[dict[str, Any]], elapsed_s: float) -> dict[str, Any]:
    """Paired differences with 95 % confidence intervals over the per-seed rows."""
    metrics: dict[str, Any] = {}
    for key, (label, unit, lower_better) in METRICS.items():
        diffs = [(r["off"][key] - r["on"][key]) if lower_better else (r["on"][key] - r["off"][key]) for r in rows]
        scale = 100.0 if unit == "pts" else 1.0
        s = paired_summary([d * scale for d in diffs])
        off_mean = sum(r["off"][key] for r in rows) / len(rows) * scale
        on_mean = sum(r["on"][key] for r in rows) / len(rows) * scale
        metrics[key] = {
            "label": label,
            "unit": unit,
            "lower_is_better": lower_better,
            "off_mean": off_mean,
            "on_mean": on_mean,
            "improvement": s["mean"],
            "improvement_pct": (s["mean"] / off_mean * 100.0) if abs(off_mean) > 1e-9 and unit != "pts" else None,
            "ci_low": s["ci_low"],
            "ci_high": s["ci_high"],
            "p_one_sided": s["p_one_sided"],
            "significant": s["significant"],
            "n": s["n"],
            "per_seed": [d * scale for d in diffs],
        }
    return {
        "config": asdict(cfg),
        "seeds": cfg.seeds,
        "metrics": metrics,
        "rows": rows,
        "elapsed_s": round(elapsed_s, 2),
        "method": (
            "Paired replay: identical seeds, order book, noise streams and fault schedule in both arms; the OFF arm is a FIFO pull MES with hard-wired "
            "safety interlocks and run-to-failure maintenance, the ON arm adds the agent swarm under the default policy (approvals answered after "
            f"{cfg.latency_min} sim-min). Improvement = paired difference, 95 % t-interval, one-sided p for H0: improvement <= 0."
        ),
        "caveat": "Synthetic plant and assumed fault frequencies: validate with customer data before using these numbers outside the demo.",
    }
