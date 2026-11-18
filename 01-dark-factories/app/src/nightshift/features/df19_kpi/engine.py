"""KPI engine (DF-19): OEE (A x P x Q), throughput, FPY, scrap, MTBF/MTTR, OTIF, energy and CO2 per unit, EUR impact.

Computed from the simulator's accumulators; windows are differences between hourly accumulator snapshots.
"""

from __future__ import annotations

from typing import Any

from nightshift.sim.config import PRODUCTION_TYPES, STAGE_OF
from nightshift.sim.plant import Plant

PRODUCTION_STAGES = ("MACH", "MOLD", "ASM", "TEST", "PACK")


def _d(cur: dict[str, Any], base: dict[str, Any], key: str) -> float:
    return float(cur.get(key, 0.0)) - float(base.get(key, 0.0))


def _asset_kpi(c: dict[str, float], b: dict[str, float]) -> dict[str, Any]:
    m = {
        k: c.get(k, 0.0) - b.get(k, 0.0)
        for k in (
            "RUN",
            "IDLE",
            "SETUP",
            "DOWN",
            "MAINT",
            "BLOCKED",
            "STARVED",
            "units",
            "good",
            "scrap",
            "ideal",
            "kwh",
            "failures",
            "down_unplanned",
        )
    }
    ppt = m["RUN"] + m["SETUP"] + m["DOWN"] + m["BLOCKED"] + m["STARVED"]
    a = m["RUN"] / ppt if ppt > 0 else None
    p = min(1.0, m["ideal"] / m["RUN"]) if m["RUN"] > 0 else None
    q = (m["units"] - m["scrap"]) / m["units"] if m["units"] > 0 else None
    oee = a * p * q if a is not None and p is not None and q is not None else None
    return {
        "availability": a,
        "performance": p,
        "quality": q,
        "oee": oee,
        "ppt_min": ppt,
        "run_min": m["RUN"],
        "down_min": m["DOWN"],
        "setup_min": m["SETUP"],
        "starved_min": m["STARVED"],
        "blocked_min": m["BLOCKED"],
        "idle_min": m["IDLE"],
        "maint_min": m["MAINT"],
        "units": m["units"],
        "good": m["good"],
        "scrap": m["scrap"],
        "kwh": m["kwh"],
        "failures": m["failures"],
    }


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ppt = sum(r["ppt_min"] for r in rows)
    run = sum(r["run_min"] for r in rows)
    ideal_num = sum((r["performance"] or 0) * r["run_min"] for r in rows)
    units = sum(r["units"] for r in rows)
    scrap = sum(r["scrap"] for r in rows)
    a = run / ppt if ppt > 0 else None
    p = ideal_num / run if run > 0 else None
    q = (units - scrap) / units if units > 0 else None
    return {
        "availability": a,
        "performance": p,
        "quality": q,
        "oee": a * p * q if a is not None and p is not None and q is not None else None,
        "failures": sum(r["failures"] for r in rows),
        "down_min": sum(r["down_min"] for r in rows),
        "run_min": run,
        "units": units,
        "scrap": scrap,
        "kwh": sum(r["kwh"] for r in rows),
    }


class KpiEngine:
    @staticmethod
    def base_snapshot(plant: Plant, window_min: int | None) -> dict[str, Any]:
        if window_min is None:
            return {"_t": 0, "_assets": {}}
        target = plant.t - window_min
        best: dict[str, Any] = {"_t": 0, "_assets": {}}
        for t, snap in plant.history:
            if t <= target:
                best = {**snap, "_t": t}
            else:
                break
        return best

    @classmethod
    def compute(
        cls,
        plant: Plant,
        window_min: int | None = None,
        base: dict[str, Any] | None = None,
        cur: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cur = cur or plant.current_snapshot()
        base = base or cls.base_snapshot(plant, window_min)
        t0, t1 = int(base.get("_t", 0)), int(cur.get("_t", plant.t))
        hours = max((t1 - t0) / 60.0, 1e-9)
        cfg = plant.cfg
        assets: dict[str, dict[str, Any]] = {}
        for spec in cfg.assets:
            c = cur["_assets"].get(spec.id, {})
            b = base.get("_assets", {}).get(spec.id, {})
            if spec.type in PRODUCTION_TYPES:
                assets[spec.id] = _asset_kpi(c, b)
            else:
                dn = c.get("down_unplanned", 0.0) - b.get("down_unplanned", 0.0)
                kwh = c.get("kwh", 0.0) - b.get("kwh", 0.0)
                assets[spec.id] = {
                    "availability": 1.0 - dn / max(1.0, t1 - t0),
                    "oee": None,
                    "down_min": dn,
                    "kwh": kwh,
                    "failures": c.get("failures", 0) - b.get("failures", 0),
                    "performance": None,
                    "quality": None,
                }
        prod = [a for sid, a in assets.items() if cfg.asset(sid).type in PRODUCTION_TYPES]
        plant_k = _agg(prod)
        lines: dict[str, dict[str, Any]] = {}
        for area in sorted({s.area for s in cfg.assets if s.type in PRODUCTION_TYPES}):
            lines[area] = _agg([assets[s.id] for s in cfg.assets if s.area == area and s.type in PRODUCTION_TYPES])
        # stage yields -> rolled throughput yield
        fpy = 1.0
        started = 0.0
        for stage in PRODUCTION_STAGES:
            ids = [s.id for s in cfg.assets if s.stage == stage]
            if not ids:
                continue
            u = sum(assets[i]["units"] for i in ids)
            sc = sum(assets[i]["scrap"] for i in ids)
            if u > 0:
                fpy *= 1.0 - sc / u
            if stage in ("MACH", "MOLD"):
                started += u
        good = _d(cur, base, "units_good")
        scrap = _d(cur, base, "scrap_units")
        completed = _d(cur, base, "orders_completed")
        on_time = _d(cur, base, "orders_on_time")
        energy = _d(cur, base, "energy_kwh")
        co2 = _d(cur, base, "co2_kg")
        failures = plant_k["failures"]
        run_h = plant_k["run_min"] / 60.0
        c = plant.A["costs"]
        overdue_eur = 0.0
        overdue_min = 0.0
        for o in plant.open_orders():
            if plant.t > o.due:
                overdue_min += plant.t - o.due
                overdue_eur += (plant.t - o.due) / 60.0 * c["tardiness_eur_per_hour"][o.priority]
        impact = {
            "downtime": _d(cur, base, "downtime_loss_eur"),
            "scrap": _d(cur, base, "scrap_cost"),
            "escapes": _d(cur, base, "escape_cost"),
            "energy": _d(cur, base, "energy_cost"),
            "tardiness": _d(cur, base, "tardiness_eur"),
            "maintenance": _d(cur, base, "maintenance_cost"),
            "expedite": _d(cur, base, "expedite_cost"),
        }
        impact["loss_total"] = sum(v for k, v in impact.items() if k != "energy")
        return {
            "plant": plant.cfg.plant_id,
            "from_t": t0,
            "to_t": t1,
            "window_h": round(hours, 2),
            "plant_kpi": {
                "oee": plant_k["oee"],
                "availability": plant_k["availability"],
                "performance": plant_k["performance"],
                "quality": plant_k["quality"],
                "throughput_uph": good / hours,
                "units_good": good,
                "fpy": fpy,
                "scrap_units": scrap,
                "scrap_pct": scrap / started if started > 0 else 0.0,
                "mtbf_h": run_h / failures if failures else None,
                "mttr_min": plant_k["down_min"] / failures if failures else None,
                "failures": failures,
                "downtime_min": _d(cur, base, "downtime_unplanned_min"),
                "otif": on_time / completed if completed else None,
                "orders_completed": completed,
                "orders_on_time": on_time,
                "tardiness_h": (_d(cur, base, "tardiness_min") + overdue_min) / 60.0,
                "overdue_orders": sum(1 for o in plant.open_orders() if plant.t > o.due),
                "energy_kwh": energy,
                "kwh_per_unit": energy / good if good > 0 else None,
                "co2_kg": co2,
                "co2_per_unit_kg": co2 / good if good > 0 else None,
                "energy_cost_eur": _d(cur, base, "energy_cost"),
                "peak_kw": cur.get("peak_kw", 0.0),
                "escapes": _d(cur, base, "escapes"),
                "safety_stop_min": _d(cur, base, "safety_stop_min"),
                "revenue_eur": _d(cur, base, "revenue"),
            },
            "impact_eur": {**{k: round(v, 2) for k, v in impact.items()}, "tardiness_open": round(overdue_eur, 2)},
            "lines": lines,
            "assets": assets,
        }

    @classmethod
    def trend(cls, plant: Plant, points: int = 24) -> list[dict[str, Any]]:
        snaps = [(t, s) for t, s in plant.history][-(points + 1) :]
        snaps.append((plant.t, plant.current_snapshot()))
        out = []
        for (t0, s0), (t1, s1) in zip(snaps, snaps[1:], strict=False):
            if t1 <= t0:
                continue
            k = cls.compute(plant, base={**s0, "_t": t0}, cur={**s1, "_t": t1})["plant_kpi"]
            out.append(
                {
                    "t": t1,
                    "oee": k["oee"],
                    "availability": k["availability"],
                    "throughput_uph": k["throughput_uph"],
                    "scrap_units": k["scrap_units"],
                    "energy_kwh": k["energy_kwh"],
                    "downtime_min": k["downtime_min"],
                    "energy_cost_eur": k["energy_cost_eur"],
                }
            )
        return out


__all__ = ["KpiEngine", "STAGE_OF"]
