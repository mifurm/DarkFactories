"""Digital twin & what-if engine (DF-03): live asset graph, fork() and simulate_ahead(actions, horizon) with KPI deltas.

The twin shares the plant's dynamics model but is *state-estimated*: hidden faults the agents have not detected are not copied into the
fork; assets the Predictive Maintenance agent flags get its health / decay-rate estimate instead of the (unknowable) true state.
Baseline and action forks use common random numbers, so the deltas are low-noise.
"""

from __future__ import annotations

from typing import Any

from nightshift.features.df19_kpi.engine import KpiEngine
from nightshift.plant.models import Action
from nightshift.sim.config import PRODUCTION_TYPES
from nightshift.sim.plant import ActionRejected, Plant

HIDDEN_FLAGS = ("bearing", "heat", "wear_accel", "thermal_target", "thermal_ramp")


class Twin:
    def __init__(self, plant: Plant) -> None:
        self.plant = plant
        self.runs = 0

    # ------------------------------------------------------------------ forks
    def fork(self) -> Plant:
        return self.plant.fork()

    def fork_estimated(self, estimates: dict[str, dict[str, float]] | None = None) -> Plant:
        f = self.plant.fork()
        est = estimates or {}
        f.pending_faults = []
        f.chaos_per_day = 0.0
        for aid, a in f.assets.items():
            for k in HIDDEN_FLAGS:
                a.flags.pop(k, None)
            e = est.get(aid)
            if e is not None:
                a.health = float(e["health"])
                if e.get("rate", 0.0) > 0:
                    a.flags["bearing"] = {"rate": float(e["rate"]), "noise": 0.05}
            else:
                a.health = max(a.health, 0.85)
        return f

    # ------------------------------------------------------------------ what-if
    def simulate_ahead(
        self, actions: list[Action], horizon_min: int = 240, estimates: dict[str, dict[str, float]] | None = None
    ) -> dict[str, Any]:
        self.runs += 1
        horizon_min = max(15, min(int(horizon_min), 720))
        base = self.fork_estimated(estimates)
        act = self.fork_estimated(estimates)
        snap0 = base.current_snapshot()
        rejected: list[str] = []
        for a in actions:
            try:
                act.apply(a.to_sim(), actor="twin")
            except ActionRejected as exc:
                rejected.append(f"{a.kind}: {exc}")
        if rejected:
            return {
                "accept": False,
                "horizon_min": horizon_min,
                "explanation": "Plant rejected the plan in the twin: " + "; ".join(rejected),
                "delta": {"net_value_eur": 0.0},
                "counterfactual": {},
                "rejected": rejected,
            }
        base.run(horizon_min)
        act.run(horizon_min)
        kb = KpiEngine.compute(base, base=snap0, cur=base.current_snapshot())
        ka = KpiEngine.compute(act, base=snap0, cur=act.current_snapshot())
        pb, pa = kb["plant_kpi"], ka["plant_kpi"]
        ib, ia = kb["impact_eur"], ka["impact_eur"]
        loss_saved = (ib["loss_total"] + ib["tardiness_open"]) - (ia["loss_total"] + ia["tardiness_open"])
        energy_saved = ib["energy"] - ia["energy"]
        margin = act.A["products"]
        avg_margin = sum(p["margin_eur"] * p["weight"] for p in margin.values()) / max(
            1e-9, sum(p["weight"] for p in margin.values())
        )
        revenue_gain = (pa["units_good"] - pb["units_good"]) * avg_margin
        net = loss_saved + energy_saved + revenue_gain
        fails_b = [
            {"asset": e["asset"], "t": e["t"], "cause": e.get("cause")} for e in base.events if e["kind"] == "failure"
        ]
        fails_a = [
            {"asset": e["asset"], "t": e["t"], "cause": e.get("cause")} for e in act.events if e["kind"] == "failure"
        ]
        avoided_min = pb["downtime_min"] - pa["downtime_min"]
        worse_p1 = (pa["tardiness_h"] - pb["tardiness_h"]) * 60 > 45
        accept = net > 0 and not worse_p1
        delta = {
            "net_value_eur": round(net, 1),
            "downtime_min": round(pa["downtime_min"] - pb["downtime_min"], 1),
            "tardiness_h": round(pa["tardiness_h"] - pb["tardiness_h"], 2),
            "late_orders": pa["overdue_orders"] - pb["overdue_orders"],
            "scrap_units": round(pa["scrap_units"] - pb["scrap_units"], 1),
            "energy_kwh": round(pa["energy_kwh"] - pb["energy_kwh"], 1),
            "energy_cost_eur": round(pa["energy_cost_eur"] - pb["energy_cost_eur"], 2),
            "units_good": round(pa["units_good"] - pb["units_good"], 1),
            "oee": None if pa["oee"] is None or pb["oee"] is None else round(pa["oee"] - pb["oee"], 4),
        }
        parts = []
        if fails_b and len(fails_a) < len(fails_b):
            first = fails_b[0]
            parts.append(
                f"without the plan {first['asset']} fails ({first['cause']}) ~{first['t'] - self.plant.t} min from now; with it the failure is avoided"
            )
        if abs(avoided_min) >= 1:
            parts.append(f"unplanned downtime {delta['downtime_min']:+.0f} min")
        if abs(delta["tardiness_h"]) >= 0.05:
            parts.append(f"tardiness {delta['tardiness_h']:+.1f} h")
        if abs(delta["energy_cost_eur"]) >= 1:
            parts.append(f"energy cost {delta['energy_cost_eur']:+.0f} EUR")
        if abs(delta["scrap_units"]) >= 0.5:
            parts.append(f"scrap {delta['scrap_units']:+.0f} units")
        expl = (
            f"Twin forked at t={self.plant.t}, {horizon_min} min ahead, common random numbers: "
            + ("; ".join(parts) if parts else "no material KPI change")
            + f". Net value {net:+,.0f} EUR -> {'accept' if accept else 'reject'}."
        )
        return {
            "accept": accept,
            "horizon_min": horizon_min,
            "explanation": expl,
            "delta": delta,
            "baseline": {
                k: pb[k]
                for k in (
                    "oee",
                    "downtime_min",
                    "tardiness_h",
                    "overdue_orders",
                    "scrap_units",
                    "energy_kwh",
                    "units_good",
                )
            },
            "with_actions": {
                k: pa[k]
                for k in (
                    "oee",
                    "downtime_min",
                    "tardiness_h",
                    "overdue_orders",
                    "scrap_units",
                    "energy_kwh",
                    "units_good",
                )
            },
            "counterfactual": {
                "baseline_failures": fails_b[:5],
                "action_failures": fails_a[:5],
                "avoided_downtime_min": round(avoided_min, 1),
                "avoided_loss_eur": round(loss_saved, 0),
                "failure_avoided": len(fails_a) < len(fails_b),
            },
            "mode": "full",
            "t": self.plant.t,
        }

    def evaluate_recipe(self, asset: str, recipe: dict[str, float], horizon_min: int = 180) -> dict[str, float]:
        price = self.plant.price_now or self.plant.tariff_at(self.plant.t)
        f = self.fork_estimated()
        for k, v in recipe.items():
            f.apply({"kind": "set_setpoint", "asset": asset, "name": k, "value": v})
        g0 = (f.assets[asset].good, f.assets[asset].scrap, f.assets[asset].kwh)
        f.run(horizon_min)
        a = f.assets[asset]
        good, scrap, kwh = a.good - g0[0], a.scrap - g0[1], a.kwh - g0[2]
        return {"good": good, "scrap": scrap, "kwh": kwh, "j": good * 15.0 - scrap * 25.0 - kwh * price}

    # ------------------------------------------------------------------ live graph
    def graph(self) -> dict[str, Any]:
        p = self.plant
        nodes: list[dict[str, Any]] = [{"id": p.cfg.plant_id, "type": "plant", "label": p.cfg.name}]
        edges: list[dict[str, str]] = []
        areas: set[str] = set()
        lines: set[tuple[str, str]] = set()
        for s in p.cfg.assets:
            if s.area not in areas:
                areas.add(s.area)
                nodes.append({"id": f"area:{s.area}", "type": "area", "label": s.area})
                edges.append({"from": p.cfg.plant_id, "to": f"area:{s.area}", "kind": "contains"})
            if (s.area, s.line) not in lines:
                lines.add((s.area, s.line))
                nodes.append({"id": f"line:{s.line}", "type": "line", "label": s.line})
                edges.append({"from": f"area:{s.area}", "to": f"line:{s.line}", "kind": "contains"})
            a = p.assets[s.id]
            nodes.append(
                {
                    "id": s.id,
                    "type": s.type,
                    "label": s.name,
                    "area": s.area,
                    "line": s.line,
                    "cell": s.cell,
                    "zone": s.zone,
                    "state": a.state,
                    "power_kw": round(a.power_kw, 1),
                    "queue": len(a.queue),
                }
            )
            edges.append({"from": f"line:{s.line}", "to": s.id, "kind": "contains"})
            if s.type in PRODUCTION_TYPES and s.params.get("util") in p._utils:
                edges.append({"from": p._utils[s.params["util"]], "to": s.id, "kind": "supplies"})
        stages = list(p.cfg.pools)
        order = ["MACH", "MOLD", "ASM", "TEST", "PACK"]
        stages.sort(key=order.index)
        for sa, sb in zip(stages, stages[1:], strict=False):
            if sa in ("MACH", "MOLD") and sb in ("MACH", "MOLD"):
                continue
            for x in p.cfg.pools[sa]:
                for y in p.cfg.pools[sb]:
                    edges.append({"from": x, "to": y, "kind": "flows_to"})
        # MACH -> MOLD only for the overmoulded actuator route; both feed ASM
        return {"plant": p.cfg.plant_id, "nodes": nodes, "edges": edges, "t": p.t}
