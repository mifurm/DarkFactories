"""Typed view over sim/assumptions.yaml and plant construction."""

from __future__ import annotations

import copy
import functools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ASSUMPTIONS_PATH = Path(__file__).with_name("assumptions.yaml")
STATES = ("RUN", "IDLE", "SETUP", "DOWN", "MAINT", "BLOCKED", "STARVED")
PRODUCTION_TYPES = ("CNC", "PRESS", "ASM", "TEST", "PACK")
STAGE_OF = {"CNC": "MACH", "PRESS": "MOLD", "ASM": "ASM", "TEST": "TEST", "PACK": "PACK"}
TYPE_LABEL = {
    "CNC": "CNC machining centre",
    "PRESS": "Injection moulding press",
    "ASM": "Assembly cell",
    "TEST": "Test station",
    "PACK": "Packaging cell",
    "COMP": "Air compressor",
    "CHILL": "Chiller",
    "AMR": "Autonomous mobile robot",
    "WH": "Raw-material warehouse",
}
AREA_OF = {
    "CNC": ("machining", "mach-line-1"),
    "PRESS": ("molding", "mold-line-1"),
    "ASM": ("assembly-test", "asm-line-1"),
    "TEST": ("assembly-test", "asm-line-1"),
    "PACK": ("assembly-test", "asm-line-1"),
    "COMP": ("utilities", "air"),
    "CHILL": ("utilities", "cooling"),
    "AMR": ("logistics", "amr-fleet"),
    "WH": ("logistics", "warehouse"),
}
LINE_LABEL = {
    "machining": "Machining",
    "molding": "Injection Molding",
    "assembly-test": "Assembly & Test",
    "utilities": "Utilities",
    "logistics": "Logistics",
}


@functools.lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with ASSUMPTIONS_PATH.open() as f:
        return yaml.safe_load(f)


def load_assumptions() -> dict[str, Any]:
    """Fresh deep copy of the assumptions document (the file the UI displays)."""
    return copy.deepcopy(_raw())


def hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def parse_window(w: str) -> tuple[int, int]:
    a, b = w.split("-")
    return hhmm(a), hhmm(b)


@dataclass(frozen=True)
class AssetSpec:
    id: str
    type: str
    stage: str | None
    name: str
    area: str
    line: str
    cell: str
    zone: str
    index: int
    params: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_production(self) -> bool:
        return self.type in PRODUCTION_TYPES

    @property
    def sensors(self) -> list[str]:
        return list(self.params.get("sensors", []))


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    family: str
    route: tuple[str, ...]
    margin_eur: float
    weight: float
    qty: tuple[int, ...]
    cycle: dict[str, float]
    bom: dict[str, float]


@dataclass
class PlantConfig:
    plant_id: str
    name: str
    site: str
    location: str
    profile: str
    assets: tuple[AssetSpec, ...]
    products: dict[str, Product]
    assumptions: dict[str, Any]
    order_rate_per_h: float
    mix: dict[str, float]
    energy_price_factor: float
    carbon_factor: float
    failure_factor: float

    def __post_init__(self) -> None:
        self._by_id = {a.id: a for a in self.assets}
        pools: dict[str, list[str]] = {}
        for a in self.assets:
            if a.stage:
                pools.setdefault(a.stage, []).append(a.id)
        self.pools: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in pools.items()}

    def asset(self, asset_id: str) -> AssetSpec:
        return self._by_id[asset_id]

    def zones(self) -> dict[str, list[str]]:
        z: dict[str, list[str]] = {}
        for a in self.assets:
            z.setdefault(a.zone, []).append(a.id)
        return z

    @property
    def starting_clock(self) -> str:
        return self.assumptions["time"]["start"]


def _zone_for(t: str, i: int, n: int) -> str:
    if t == "CNC":
        return "Z-MACH-A" if i < math.ceil(n * 0.6) else "Z-MACH-B"
    return {
        "PRESS": "Z-MOLD",
        "ASM": "Z-ASM",
        "TEST": "Z-ASM",
        "PACK": "Z-ASM",
        "COMP": "Z-UTIL",
        "CHILL": "Z-UTIL",
        "AMR": "Z-LOG",
        "WH": "Z-LOG",
    }[t]


def build_plant_config(plant_id: str = "KAT-1", assumptions: dict[str, Any] | None = None) -> PlantConfig:
    a = assumptions if assumptions is not None else load_assumptions()
    p = a["plants"][plant_id]
    assets: list[AssetSpec] = []
    for t, n in p["counts"].items():
        tp = a["asset_types"][t]
        for i in range(n):
            area, line = AREA_OF[t]
            aid = f"{t}-{i + 1:02d}"
            assets.append(
                AssetSpec(
                    id=aid,
                    type=t,
                    stage=tp.get("stage"),
                    name=f"{TYPE_LABEL[t]} {i + 1:02d}",
                    area=area,
                    line=line,
                    cell=f"cell-{i + 1:02d}",
                    zone=_zone_for(t, i, n),
                    index=i,
                    params=tp,
                )
            )
    order = {t: k for k, t in enumerate(AREA_OF)}
    assets.sort(key=lambda x: (order[x.type], x.index))
    products = {
        sku: Product(
            sku,
            d["name"],
            d["family"],
            tuple(d["route"]),
            float(d["margin_eur"]),
            float(d["weight"]),
            tuple(d["qty"]),
            dict(d["cycle_min"]),
            dict(d["bom"]),
        )
        for sku, d in a["products"].items()
    }
    return PlantConfig(
        plant_id=plant_id,
        name=p["name"],
        site=p["site"],
        location=p["location"],
        profile=p["profile"],
        assets=tuple(assets),
        products=products,
        assumptions=a,
        order_rate_per_h=float(p["order_rate_per_h"]),
        mix=dict(p["mix"]),
        energy_price_factor=float(p["energy_price_factor"]),
        carbon_factor=float(p["carbon_factor"]),
        failure_factor=float(p["failure_factor"]),
    )
