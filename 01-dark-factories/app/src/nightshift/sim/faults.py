"""Fault-injection catalog, narrative scenarios and the seeded fault schedules used by the A/B replay."""

from __future__ import annotations

from typing import Any

import numpy as np

from nightshift.sim.config import PlantConfig

FAULT_LABELS: dict[str, dict[str, Any]] = {
    "bearing_wear": {
        "label": "Bearing wear",
        "target": "asset",
        "types": ["CNC", "PRESS", "COMP", "CHILL"],
        "hint": "Vibration and bearing temperature drift upward; failure in ttf_h hours if nobody acts.",
        "params": ["ttf_h"],
    },
    "tool_wear": {
        "label": "Tool wear",
        "target": "asset",
        "types": ["CNC", "PRESS", "ASM"],
        "hint": "Tool/mould wears accel x faster: process mean shifts, defects rise.",
        "params": ["accel"],
    },
    "thermal_drift": {
        "label": "Thermal drift",
        "target": "asset",
        "types": ["CNC", "PRESS"],
        "hint": "Temperature rises and the process mean drifts (dimension / part weight).",
        "params": ["magnitude_sigma", "ramp_h"],
    },
    "quality_drift": {
        "label": "Quality drift (material lot)",
        "target": "asset",
        "types": ["CNC", "PRESS"],
        "hint": "Process mean shifts without any thermal signature (e.g. a bad material lot).",
        "params": ["magnitude_sigma", "duration_h"],
    },
    "jam": {
        "label": "Jam",
        "target": "asset",
        "types": ["CNC", "PRESS", "ASM", "TEST", "PACK", "AMR"],
        "hint": "Asset stops (DOWN); a remote clear is possible when the jam is recoverable.",
        "params": ["duration_min"],
    },
    "supplier_delay": {
        "label": "Supplier delay",
        "target": "material",
        "types": [],
        "hint": "Open purchase orders slip by delay_h hours.",
        "params": ["delay_h"],
    },
    "rush_order": {
        "label": "Rush order",
        "target": "sku",
        "types": [],
        "hint": "A priority-1 order with a tight due date lands in the order book.",
        "params": ["qty", "due_in_h"],
    },
    "power_price_spike": {
        "label": "Power-price spike",
        "target": "plant",
        "types": [],
        "hint": "Spot price multiplier for the next hours.",
        "params": ["multiplier", "duration_h"],
    },
    "human_intrusion": {
        "label": "Human intrusion",
        "target": "zone",
        "types": [],
        "hint": "A person enters a safety zone: machines in the zone must stop.",
        "params": ["duration_min"],
    },
}


def fault_catalog(cfg: PlantConfig) -> list[dict[str, Any]]:
    out = []
    for kind, meta in FAULT_LABELS.items():
        d = cfg.assumptions["faults"][kind]
        targets: list[str] = []
        if meta["target"] == "asset":
            targets = [a.id for a in cfg.assets if a.type in meta["types"]]
        elif meta["target"] == "material":
            targets = list(cfg.assumptions["materials"])
        elif meta["target"] == "zone":
            targets = list(cfg.zones())
        elif meta["target"] == "sku":
            targets = list(cfg.products)
        out.append(
            {
                "kind": kind,
                "label": meta["label"],
                "hint": meta["hint"],
                "target_kind": meta["target"],
                "targets": targets,
                "params": {p: d[p] for p in meta["params"] if p in d},
            }
        )
    return out


def _first(cfg: PlantConfig, types: tuple[str, ...], n: int = 0) -> str:
    ids = [a.id for a in cfg.assets if a.type in types]
    return ids[min(n, len(ids) - 1)]


def scenario_steps(name: str, cfg: PlantConfig) -> list[tuple[int, str, dict[str, Any]]]:
    """(minutes from now, fault kind, params) - the live fault console can fire a whole story with one click."""
    cnc4 = "CNC-04" if "CNC-04" in cfg.pools.get("MACH", ()) else _first(cfg, ("CNC",), 3)
    press = _first(cfg, ("PRESS",), 1)
    zone = "Z-MACH-B" if "Z-MACH-B" in cfg.zones() else next(iter(cfg.zones()))
    table: dict[str, list[tuple[int, str, dict[str, Any]]]] = {
        "night-shift-bearing": [(2, "bearing_wear", {"asset": cnc4, "ttf_h": 5.0})],
        "rush-order": [(2, "rush_order", {"sku": "SHF-200", "qty": 90, "due_in_h": 8.0, "priority": 1})],
        "supplier-delay": [(2, "supplier_delay", {"material": "RESIN-PA", "delay_h": 12.0})],
        "price-spike": [(2, "power_price_spike", {"multiplier": 3.0, "duration_h": 3.0})],
        "tool-wear": [(2, "tool_wear", {"asset": _first(cfg, ("CNC",), 1), "accel": 25.0})],
        "thermal-drift": [(2, "thermal_drift", {"asset": press})],
        "intrusion": [(2, "human_intrusion", {"zone": zone, "duration_min": 12})],
        "perfect-storm": [
            (2, "bearing_wear", {"asset": cnc4, "ttf_h": 5.0}),
            (10, "supplier_delay", {"material": "RESIN-PA", "delay_h": 10.0}),
            (20, "tool_wear", {"asset": _first(cfg, ("CNC",), 1), "accel": 25.0}),
            (35, "rush_order", {"sku": "HSG-100", "qty": 80, "due_in_h": 7.0, "priority": 1}),
            (50, "power_price_spike", {"multiplier": 2.8, "duration_h": 2.5}),
            (70, "human_intrusion", {"zone": zone, "duration_min": 12}),
        ],
    }
    if name not in table:
        raise KeyError(name)
    return table[name]


SCENARIO_INFO = {
    "night-shift-bearing": "02:14 - bearing temperature on CNC-04 drifts. Watch Maintenance, Planner, Materials, Energy and Safety negotiate a plan.",
    "rush-order": "A priority-1 shaft order with an 8 h due date arrives - the Planner re-sequences the shop floor.",
    "supplier-delay": "The polyamide resin delivery slips 12 h - Materials expedites or switches source before presses starve.",
    "price-spike": "Spot power triples for 3 h - the Energy agent shifts compressor and chiller load.",
    "tool-wear": "A CNC tool wears 25x faster - SPC detects the shift, compensates and contains the lot.",
    "thermal-drift": "A press drifts thermally - Quality compensates and Maintenance is alerted.",
    "intrusion": "A person enters a safety zone - Safety stops the cell and restarts it after verification.",
    "perfect-storm": "Six simultaneous disruptions: the stress test for arbitration, policy and the approval inbox.",
}


def ab_fault_schedule(
    cfg: PlantConfig, seed: int, horizon_min: int, intensity: float = 1.0
) -> list[tuple[int, str, dict[str, Any]]]:
    """Seeded disruption set for a replay arm. Both arms receive the identical list (same seed => same schedule)."""
    g = np.random.default_rng(seed * 7919 + 17)
    cn = [a.id for a in cfg.assets if a.type == "CNC"]
    pr = [a.id for a in cfg.assets if a.type == "PRESS"]
    wearable = cn + pr
    prod = [a.id for a in cfg.assets if a.type in ("CNC", "PRESS", "ASM", "TEST", "PACK")]
    zones = list(cfg.zones())

    def at(lo: float, hi: float) -> int:
        return int(g.uniform(lo, min(hi, 0.95) * horizon_min if hi <= 1 else min(hi, horizon_min - 20)))

    items: list[tuple[int, str, dict[str, Any]]] = [
        (at(10, 60), "bearing_wear", {"asset": str(g.choice(wearable)), "ttf_h": float(g.uniform(4.5, 7.0))}),
        (at(30, 120), "tool_wear", {"asset": str(g.choice(cn or wearable)), "accel": float(g.uniform(40, 60))}),
        (at(60, 200), "thermal_drift" if g.random() < 0.5 else "quality_drift", {"asset": str(g.choice(wearable))}),
        (at(30, 150), "supplier_delay", {"material": "RESIN-PA", "delay_h": float(g.uniform(8, 14))}),
        (
            at(90, 240),
            "rush_order",
            {
                "sku": str(g.choice(list(cfg.products))),
                "qty": int(g.choice([60, 80, 100])),
                "due_in_h": float(g.uniform(6, 8)),
                "priority": 1,
            },
        ),
        (at(60, 240), "power_price_spike", {"multiplier": float(g.uniform(2.6, 3.2)), "duration_h": 2.5}),
        (at(100, 400), "human_intrusion", {"zone": str(g.choice(zones)), "duration_min": int(g.integers(10, 16))}),
        (at(60, 380), "jam", {"asset": str(g.choice(prod)), "duration_min": 90}),
    ]
    if intensity < 1.0:
        keep = max(1, round(len(items) * intensity))
        idx = sorted(g.choice(len(items), size=keep, replace=False).tolist())
        items = [items[i] for i in idx]
    return sorted(items, key=lambda x: x[0])
