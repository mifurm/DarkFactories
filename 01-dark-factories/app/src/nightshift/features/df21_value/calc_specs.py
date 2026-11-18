"""Describes every override the vendored business-case model accepts, derived from assumptions.json (no hard-coded driver list).

The calculator UI renders its controls from this description, so a new model version only needs new JSON, not new UI code.
Core drivers and the expansion levers (E1-E5) are separate groups; Azure unit prices are listed as ``price.<id>`` overrides.
"""

from __future__ import annotations

from typing import Any

SCENARIOS = ("conservative", "base", "upside")

GROUP_LABELS: dict[str, str] = {
    "customer": "Customer & scope",
    "timing": "Timing",
    "benefit_baseline": "Benefit baselines",
    "benefit_lever": "Benefit levers (what the swarm changes)",
    "ramp": "Adoption ramps",
    "confidence": "Confidence factors (risk adjustment)",
    "customer_cost": "Customer-side costs",
    "opportunity": "Opportunity sizing (illustrative)",
    "acr": "ACR - general sizing",
    "acr_ai": "ACR - Foundry models & AI Search",
    "acr_ml": "ACR - Azure Machine Learning",
    "acr_data": "ACR - Fabric, OneLake, Power BI",
    "acr_edge": "ACR - IoT Operations & Arc",
    "acr_messaging": "ACR - Event Hubs, Event Grid, Service Bus",
    "acr_twins": "ACR - Azure Digital Twins",
    "acr_cosmos": "ACR - Cosmos DB",
    "acr_compute": "ACR - Container Apps compute",
    "acr_network": "ACR - Networking",
    "acr_security": "ACR - Defender, Sentinel, Key Vault",
    "acr_monitoring": "ACR - Azure Monitor",
    "expansion": "Expansion levers - shared (ramps, fleet size)",
    "expansion_vision": "E1 Machine-vision fleet",
    "expansion_hf": "E2 High-frequency condition monitoring",
    "expansion_sim": "E3 Continuous sim-first what-if at scale",
    "expansion_dp": "E4 Enterprise data-platform modernisation",
    "expansion_sec": "E5 OT security & connectivity hardening",
    "prices": "Azure unit prices (USD list price, Retail Prices API)",
}

# lever id -> (override key that switches it, group id)
LEVER_SWITCHES: dict[str, tuple[str, str]] = {
    "E1": ("exp_vision_adoption", "expansion_vision"),
    "E2": ("exp_hf_adoption", "expansion_hf"),
    "E3": ("exp_sim_adoption", "expansion_sim"),
    "E4": ("exp_dp_adoption", "expansion_dp"),
    "E5": ("exp_sec_adoption", "expansion_sec"),
}
LEVER_NAMES = {
    "E1": "Machine-vision fleet",
    "E2": "High-frequency condition monitoring",
    "E3": "Continuous sim-first what-if",
    "E4": "Enterprise data platform",
    "E5": "OT security & connectivity",
}


def _kind(spec: dict[str, Any]) -> str:
    base = spec["base"]
    if base is None:
        return "nullable"
    if isinstance(base, list):
        return "pairs" if base and isinstance(base[0], list) else "list"
    return "number"


def _scenario_values(spec: dict[str, Any]) -> dict[str, Any]:
    sc = spec.get("scenario", {})
    return {s: sc.get(s, spec["base"]) for s in SCENARIOS}


def _driver(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    kind = _kind(spec)
    d: dict[str, Any] = {
        "id": key,
        "label": spec.get("label", key),
        "group": spec.get("group", "other"),
        "unit": spec.get("unit", ""),
        "kind": kind,
        "base": spec["base"],
        "low": spec.get("low"),
        "high": spec.get("high"),
        "min": spec.get("min"),
        "max": spec.get("max"),
        "flag": spec.get("flag", ""),
        "source": spec.get("source", ""),
        "scenario": _scenario_values(spec),
        "scenario_driver": bool(spec.get("scenario")),
        "editable": kind != "pairs",  # [plants, scale] curves are shown, not edited
    }
    if kind == "list":
        d["length"] = len(spec["base"])
    return d


def group_label(group: str) -> str:
    return GROUP_LABELS.get(group, group.replace("_", " ").capitalize())


def override_specs(assumptions: dict[str, Any]) -> dict[str, Any]:
    """Groups of overridable drivers (core first, then expansion levers, then unit prices) plus the five lever switches."""
    specs: dict[str, dict[str, Any]] = assumptions["assumptions"]
    order: list[str] = []
    by_group: dict[str, list[dict[str, Any]]] = {}
    for key, spec in specs.items():
        d = _driver(key, spec)
        if d["group"] not in by_group:
            order.append(d["group"])
            by_group[d["group"]] = []
        by_group[d["group"]].append(d)
    groups: list[dict[str, Any]] = []
    for kind in ("core", "expansion"):
        for g in order:
            is_exp = g.startswith("expansion")
            if (kind == "expansion") != is_exp:
                continue
            groups.append({"id": g, "label": group_label(g), "kind": kind, "drivers": by_group[g]})
    prices = [
        {
            "id": f"price.{pid}",
            "label": f"{p.get('sku') or pid}",
            "group": "prices",
            "unit": p.get("unit", ""),
            "kind": "number",
            "base": p["price"],
            "min": 0,
            "max": None,
            "low": None,
            "high": None,
            "flag": "sourced",
            "source": f"Azure Retail Prices API, {p.get('region', '')} (effective {p.get('effective', '')})",
            "scenario": {s: p["price"] for s in SCENARIOS},
            "scenario_driver": False,
            "editable": True,
            "detail": pid,
        }
        for pid, p in assumptions["prices"].items()
    ]
    groups.append({"id": "prices", "label": group_label("prices"), "kind": "prices", "drivers": prices})
    switches = []
    for lever, (key, group) in LEVER_SWITCHES.items():
        sc = _scenario_values(specs[key])
        switches.append(
            {
                "lever": lever,
                "key": key,
                "group": group,
                "label": LEVER_NAMES[lever],
                "off": 0.0,
                "on": float(
                    sc["upside"]
                ),  # "levers on" = the model's expansion case: every lever at its Upside adoption
                "scenario": sc,
                "min": specs[key].get("min", 0),
                "max": specs[key].get("max", 1),
            }
        )
    return {
        "groups": groups,
        "switches": switches,
        "counts": {"drivers": len(specs), "prices": len(prices)},
    }
