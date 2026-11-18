#!/usr/bin/env python3
"""Nightshift business-case model: customer ROI + Azure Consumed Revenue (ACR).

Pure standard library, deterministic, no I/O inside compute(). The live app vendors this file together with
assumptions.json and a unit test asserts it reproduces outputs.json, so the public interface below is stable:

    compute(assumptions, scenario="base", overrides=None, *, with_sensitivity=True) -> dict
    compute_all(assumptions, overrides=None, *, with_sensitivity=True) -> dict
    load_assumptions(path=None) -> dict

`assumptions` is the parsed assumptions.json. `overrides` maps an assumption id (or "price.<price id>") to a value and is
applied after the scenario has been resolved. See README.md for the list of ids the calculator exposes.

Run `python model.py` to regenerate outputs.json and outputs.md next to this file.
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from typing import Any

MODEL_VERSION = "1.1.0"
SCENARIOS = ("conservative", "base", "upside")
HOURS_PER_YEAR = 8760.0
SECONDS_PER_YEAR = 365.0 * 86400.0
SIM_MIN_YEARS = 5

BENEFIT_CATEGORIES = [
    ("downtime", "Unplanned-downtime reduction"),
    ("maintenance", "Maintenance cost optimisation"),
    ("throughput", "Throughput / OEE performance uplift"),
    ("scrap", "Scrap & rework reduction"),
    ("energy", "Energy cost reduction"),
    ("labour", "Indirect-labour productivity"),
    ("inventory", "Inventory carrying-cost reduction"),
    ("expedite", "Expedite & premium-freight avoidance"),
    ("otif", "On-time-in-full revenue protection"),
    ("capex", "Capex deferral (unlocked capacity)"),
]
AZURE_FAMILIES = [
    ("ai_foundry", "Foundry models & AI Search"),
    ("azure_ml", "Azure Machine Learning"),
    ("fabric", "Microsoft Fabric (RTI, OneLake, Power BI)"),
    ("iot_edge", "IoT Operations, Arc & Device Registry"),
    ("messaging", "Event Hubs, Event Grid, Service Bus"),
    ("digital_twins", "Azure Digital Twins"),
    ("cosmos", "Cosmos DB"),
    ("storage", "Storage / ADLS"),
    ("compute", "Container Apps compute & Container Registry"),
    ("networking", "ExpressRoute, VPN, Front Door, Private Link"),
    ("security", "Defender, Sentinel, Key Vault"),
    ("monitoring", "Azure Monitor / Log Analytics"),
]
OTHER_COST_CATEGORIES = [
    ("assessment", "Lights-Out Readiness Assessment"),
    ("edge_hardware", "Edge hardware & sensors"),
    ("integration", "Integration, onboarding & platform foundation"),
    ("change_management", "Change management & training"),
    ("agentops", "AgentOps team (humans on the loop)"),
    ("licences", "Platform & other licences"),
    ("hardware_support", "Hardware support"),
    ("contingency", "Contingency"),
]
ATTACH_CATEGORIES = {
    "ai_core": ("ai_foundry", "azure_ml"),
    "data": ("fabric", "messaging", "digital_twins", "cosmos", "storage"),
    "edge": ("iot_edge",),
    "compute": ("compute",),
    "networking": ("networking",),
    "security": ("security",),
    "monitoring": ("monitoring",),
}
NONPROD_FAMILIES = ("ai_foundry", "azure_ml", "fabric", "messaging", "digital_twins", "cosmos", "compute", "storage", "monitoring")
DR_FAMILIES = ("fabric", "messaging", "digital_twins", "compute", "storage")
CONF_KEYS = {c: "conf_" + c for c, _ in BENEFIT_CATEGORIES}

# Optional expansion levers (ids E1-E5). Each has its own Azure lines, customer-side costs and benefits; all are OFF (adoption 0) in
# Base and Conservative and ON in Upside, and can be switched with the overrides `exp_<lever>_adoption` (see README.md).
EXPANSION_LEVERS = [
    ("E1", "exp_vision", "Machine-vision fleet"),
    ("E2", "exp_hf", "High-frequency condition monitoring"),
    ("E3", "exp_sim", "Continuous sim-first what-if at scale"),
    ("E4", "exp_dp", "Enterprise data-platform modernisation"),
    ("E5", "exp_sec", "OT security & connectivity hardening"),
]
LEVER_IDS = [lid for lid, _, _ in EXPANSION_LEVERS]
LEVER_LABELS = {lid: label for lid, _, label in EXPANSION_LEVERS}
EXPANSION_BENEFIT_CATEGORIES = [
    ("data_platform", "Data-platform & IT savings (avoided historian/BI licences, analytics productivity)"),
    ("cyber_risk", "Cyber-risk reduction (expected loss avoided, insurance premium)"),
]
LEVER_NOTES = {
    "E1": "Edge inference stays customer-side, so Azure carries the image archive, retraining and low-confidence escalations: modest per plant, material across a fleet. Pays back through inspection labour and escape cost.",
    "E2": "Small for Azure: the edge extracts features and only scheduled raw snapshots travel, so storage and compute are a few thousand dollars per plant (continuous raw streaming multiplies it). Its value is earlier failure detection.",
    "E3": "Discrete-event simulation is cheap; Azure consumption becomes material only with Monte-Carlo rollouts at scale or physics-level fidelity. Its value is earning higher autonomy levels.",
    "E4": "The largest single step: Fabric capacity moves from plant level to enterprise scale. Power BI Pro and other Microsoft 365 licences are not Azure consumption.",
    "E5": "A risk and compliance lever: it adds Sentinel, Firewall Premium, a second ExpressRoute path and Defender for Servers, but does not pay for itself on expected-loss value alone. Defender for IoT OT licences are Microsoft 365, not ACR.",
}


# --------------------------------------------------------------------------------------------- loading & resolution
def load_assumptions(path: str | None = None) -> dict:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "assumptions.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _pick(spec: dict, scenario: str) -> Any:
    """Only 'scenario drivers' (entries with a `scenario` object) differ between scenarios; everything else stays at base."""
    if scenario == "base":
        return copy.deepcopy(spec["base"])
    return copy.deepcopy(spec.get("scenario", {}).get(scenario, spec["base"]))


def _check_bounds(key: str, spec: dict, value: Any) -> None:
    if key == "shared_scale_points":
        if not (isinstance(value, list) and value and all(isinstance(p, list) and len(p) == 2 for p in value)):
            raise ValueError("shared_scale_points must be a list of [plants, scale] pairs")
        return
    if value is None:
        if spec["base"] is None:
            return
        raise ValueError(f"{key}: null is not allowed")
    values = value if isinstance(value, list) else [value]
    if isinstance(spec["base"], list) and not isinstance(value, list):
        raise ValueError(f"{key}: expected a list of {len(spec['base'])} values")
    if isinstance(spec["base"], list) and len(value) != len(spec["base"]):
        raise ValueError(f"{key}: expected {len(spec['base'])} values, got {len(value)}")
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            raise ValueError(f"{key}: numeric value required")
        if "min" in spec and v < spec["min"]:
            raise ValueError(f"{key}: {v} is below the minimum {spec['min']}")
        if "max" in spec and v > spec["max"]:
            raise ValueError(f"{key}: {v} is above the maximum {spec['max']}")


def resolve(assumptions: dict, scenario: str = "base", overrides: dict | None = None) -> tuple[dict, dict]:
    """Return (A, P): resolved assumption values and unit prices (list price, before the price multiplier)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    specs = assumptions["assumptions"]
    A = {k: _pick(spec, scenario) for k, spec in specs.items()}
    P = {k: float(v["price"]) for k, v in assumptions["prices"].items()}
    for key, value in (overrides or {}).items():
        if key.startswith("price."):
            pid = key[len("price."):]
            if pid not in P:
                raise ValueError(f"unknown price id {pid!r}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{key}: non-negative number required")
            P[pid] = float(value)
            continue
        if key not in specs:
            raise ValueError(f"unknown override {key!r}")
        _check_bounds(key, specs[key], value)
        A[key] = copy.deepcopy(value)
    A["plants_total"] = int(round(A["plants_total"]))
    return A, P


# --------------------------------------------------------------------------------------------- customer benefits
def _plant_benefits(A: dict) -> tuple[dict, dict, dict]:
    """Annual steady-state benefit per plant: (gross, risk-adjusted, derived facts)."""
    revenue = A["revenue_usd"] / A["plants_total"]
    line_hours = A["lines_per_plant"] * A["scheduled_hours_per_line_year"]
    downtime_hours = line_hours * A["baseline_unplanned_downtime_pct"]
    hours_saved = downtime_hours * A["downtime_reduction_pct"]
    explicit = A["downtime_cost_per_line_hour_usd"]
    cost_per_hour = explicit if explicit is not None else (revenue / line_hours) * A["downtime_cost_pct_of_line_revenue"]
    capacity_gain = A["oee_performance_uplift_pts"] / A["baseline_oee_pct"]
    inventory_release = revenue * A["inventory_pct_revenue"] * A["inventory_reduction_pct"]
    labour_hours = A["indirect_labour_fte_per_plant"] * A["productive_hours_per_fte_year"] * A["indirect_labour_productivity_gain_pct"]
    gross = {
        "downtime": hours_saved * cost_per_hour,
        "maintenance": revenue * A["maintenance_spend_pct_revenue"] * A["maintenance_cost_reduction_pct"],
        "throughput": revenue * capacity_gain * A["contribution_margin_pct"] * A["demand_capture_pct"],
        "scrap": revenue * A["scrap_rework_cost_pct_revenue"] * A["scrap_reduction_pct"],
        "energy": revenue * A["energy_spend_pct_revenue"] * A["energy_saving_pct"],
        "labour": labour_hours * A["loaded_labour_rate_usd_per_hour"],
        "inventory": inventory_release * A["inventory_carrying_cost_pct"],
        "expedite": revenue * A["expedite_spend_pct_revenue"] * A["expedite_reduction_pct"],
        "otif": revenue * A["late_delivery_cost_pct_revenue"] * A["late_delivery_reduction_pct"],
        "capex": revenue * A["gross_ppe_pct_revenue"] * capacity_gain * (1.0 - A["demand_capture_pct"]) * A["capex_carry_cost_pct"],
    }
    adjusted = {c: gross[c] * A[CONF_KEYS[c]] for c, _ in BENEFIT_CATEGORIES}
    derived = {
        "plant_revenue_usd": revenue,
        "line_hours_per_plant_year": line_hours,
        "baseline_unplanned_downtime_hours_per_plant_year": downtime_hours,
        "downtime_hours_avoided_per_plant_year": hours_saved,
        "downtime_cost_per_line_hour_usd": cost_per_hour,
        "line_revenue_per_hour_usd": revenue / line_hours,
        "capacity_gain_share": capacity_gain,
        "labour_hours_released_per_plant_year": labour_hours,
        "working_capital_release_per_plant_usd": inventory_release,
    }
    return gross, adjusted, derived


# --------------------------------------------------------------------------------------------- Azure consumption
def _line(lines: list, lid: str, family: str, label: str, kind: str, quantity: float, unit: str, price_id: str | None,
          unit_price: float, retention_months: float | None = None) -> None:
    lines.append({
        "id": lid, "family": family, "item": label, "kind": kind, "quantity": quantity, "unit": unit,
        "price_id": price_id, "unit_price": unit_price, "annual": quantity * unit_price, "retention_months": retention_months,
    })


def _msgs_per_second(A: dict, assets: float) -> float:
    per_asset = A["tags_hot_per_asset"] / A["hot_publish_interval_s"] + A["tags_warm_per_asset"] / A["warm_publish_interval_s"]
    return assets * per_asset * A["data_volume_multiplier"]


def _plant_lines(A: dict, P: dict, s: float, *, edge_nodes: float, er_circuits: float, vpn_gateways: float, cosmos_regions: float) -> list[dict]:
    """Annual steady-state Azure consumption of ONE plant. s = assets_per_plant / reference_assets_per_plant."""
    mult = A["azure_price_multiplier"]

    def pr(key: str) -> float:
        return P[key] * mult

    L: list[dict] = []
    ref_assets = A["reference_assets_per_plant"]
    assets = s * ref_assets
    umult = A["llm_usage_multiplier"]
    cache = A["llm_prompt_cache_hit_share"]

    # --- Foundry models: tokens (usage)
    def workload(name: str) -> tuple[float, float, float]:
        calls = A[f"llm_{name}_calls_per_plant_day"] * 365.0 * s * umult
        return calls, calls * A[f"llm_{name}_in_tokens"] / 1e6, calls * A[f"llm_{name}_out_tokens"] / 1e6

    models = {
        "gpt54_mini": ("gpt-5.4-mini", [("agent", True), ("copilot", True), ("digest", True), ("vision", False)]),
        "gpt54": ("gpt-5.4", [("reasoning", True)]),
        "gpt54_nano": ("gpt-5.4-nano", [("triage", True)]),
    }
    for mkey, (mname, workloads) in models.items():
        in_cached = in_plain = out_m = 0.0
        for wname, cacheable in workloads:
            _, in_m, o_m = workload(wname)
            in_cached += in_m * cache if cacheable else 0.0
            in_plain += in_m * (1.0 - cache) if cacheable else in_m
            out_m += o_m
        _line(L, f"{mkey}_in", "ai_foundry", f"{mname} input tokens (uncached)", "usage", in_plain, "M tokens", f"{mkey}_input_per_1m", pr(f"{mkey}_input_per_1m"))
        _line(L, f"{mkey}_cached", "ai_foundry", f"{mname} input tokens (prompt-cache hits)", "usage", in_cached, "M tokens", f"{mkey}_cached_input_per_1m", pr(f"{mkey}_cached_input_per_1m"))
        _line(L, f"{mkey}_out", "ai_foundry", f"{mname} output tokens", "usage", out_m, "M tokens", f"{mkey}_output_per_1m", pr(f"{mkey}_output_per_1m"))
    _line(L, "embeddings", "ai_foundry", "text-embedding-3-small tokens", "usage", A["embedding_tokens_per_plant_day"] * 365.0 * s / 1e3, "K tokens", "embedding_3_small_per_1k", pr("embedding_3_small_per_1k"))
    copilot_calls = A["llm_copilot_calls_per_plant_day"] * 365.0 * s * umult
    _line(L, "semantic_ranker", "ai_foundry", "AI Search semantic-ranker queries", "usage", copilot_calls / 1e3, "K queries", "ai_search_semantic_ranker_per_1k", pr("ai_search_semantic_ranker_per_1k"))

    # --- Azure ML (usage)
    _line(L, "aml_train_cpu", "azure_ml", "Training compute D16s v5", "usage", A["aml_training_hours_per_plant_month"] * 12 * s, "hours", "vm_d16s_v5_hour", pr("vm_d16s_v5_hour"))
    _line(L, "aml_train_gpu", "azure_ml", "GPU training NC8as T4 v3", "usage", A["aml_gpu_hours_per_plant_month"] * 12 * s, "hours", "vm_nc8as_t4_v3_hour", pr("vm_nc8as_t4_v3_hour"))

    # --- IoT Operations, Arc, Device Registry (provisioned)
    _line(L, "iot_ops_nodes", "iot_edge", "Azure IoT Operations Standard nodes (OPC UA connector)", "provisioned", edge_nodes * HOURS_PER_YEAR, "node-hours", "iot_ops_standard_node_hour", pr("iot_ops_standard_node_hour"))
    _line(L, "device_registry_assets", "iot_edge", "Azure Device Registry assets", "provisioned", assets * HOURS_PER_YEAR, "asset-hours", "device_registry_asset_hour", pr("device_registry_asset_hour"))
    _line(L, "device_registry_devices", "iot_edge", "Azure Device Registry devices", "provisioned", A["devices_per_plant"] * s * HOURS_PER_YEAR, "device-hours", "device_registry_device_hour", pr("device_registry_device_hour"))

    # --- Event Hubs ingress, Event Grid (usage)
    msgs_s = _msgs_per_second(A, assets)
    _line(L, "eventhubs_ingress", "messaging", "Event Hubs ingress events", "usage", msgs_s * SECONDS_PER_YEAR / 1e6, "M events", "eventhubs_standard_ingress_per_1m", pr("eventhubs_standard_ingress_per_1m"))
    _line(L, "eventgrid_ops", "messaging", "Event Grid operations", "usage", A["eventgrid_million_ops_per_plant_month"] * 12 * s, "M operations", "eventgrid_operations_per_1m", pr("eventgrid_operations_per_1m"))

    # --- Digital Twins (usage, westeurope)
    minutes_year = 525600.0
    _line(L, "adt_ops", "digital_twins", "Digital Twins operations", "usage", assets * A["adt_ops_per_asset_minute"] * minutes_year / 1e3, "K operations", "adt_operations_per_1k", pr("adt_operations_per_1k"))
    _line(L, "adt_msgs", "digital_twins", "Digital Twins routed messages", "usage", assets * A["adt_messages_per_asset_minute"] * minutes_year / 1e3, "K messages", "adt_messages_per_1k", pr("adt_messages_per_1k"))
    _line(L, "adt_qu", "digital_twins", "Digital Twins query units", "usage", A["adt_queries_per_plant_minute"] * s * A["adt_query_units_per_query"] * minutes_year / 1e3, "K query units", "adt_query_units_per_1k", pr("adt_query_units_per_1k"))

    # --- Cosmos DB (provisioned)
    ru_units = A["cosmos_max_ru_per_plant"] * s * A["cosmos_autoscale_avg_fraction"] / 100.0
    _line(L, "cosmos_ru", "cosmos", f"Cosmos DB autoscale throughput x {cosmos_regions:g} region(s)", "provisioned", ru_units * HOURS_PER_YEAR * cosmos_regions, "100-RU/s-hours", "cosmos_autoscale_100ru_hour", pr("cosmos_autoscale_100ru_hour"))
    _line(L, "cosmos_storage", "cosmos", "Cosmos DB storage", "provisioned", A["cosmos_gb_per_plant"] * s * 12 * cosmos_regions, "GB-months", "cosmos_storage_gb_month", pr("cosmos_storage_gb_month"))
    _line(L, "cosmos_backup", "cosmos", "Cosmos DB continuous backup (30 days)", "provisioned", A["cosmos_gb_per_plant"] * s * 12 * cosmos_regions, "GB-months", "cosmos_continuous_backup_30d_gb_month", pr("cosmos_continuous_backup_30d_gb_month"))

    # --- Storage & OneLake (stock: grows until the retention window is full)
    raw_gb_day = msgs_s * 86400.0 * A["bytes_per_message"] / 1e9
    stored_gb_day = raw_gb_day / A["compression_ratio"]
    waveform_gb_day = assets * A["waveform_assets_share"] * A["waveform_snapshots_per_asset_day"] * A["waveform_snapshot_mb"] / 1e3
    image_gb_day = A["llm_vision_calls_per_plant_day"] * s * umult * A["image_mb"] / 1e3
    month_days = 365.0 / 12.0
    archive_gb_month = (stored_gb_day + waveform_gb_day + image_gb_day) * month_days
    arch_ret = A["archive_retention_months"]
    hot_m = min(A["storage_hot_months"], arch_ret)
    _line(L, "onelake", "fabric", "OneLake storage (curated telemetry, hot)", "stock", stored_gb_day * month_days * A["onelake_retention_months"] * 12, "GB-months", "onelake_hot_gb_month", pr("onelake_hot_gb_month"), A["onelake_retention_months"])
    _line(L, "archive_hot", "storage", "Raw archive, hot ZRS (first months)", "stock", archive_gb_month * hot_m * 12, "GB-months", "adls_hot_zrs_gb_month", pr("adls_hot_zrs_gb_month"), arch_ret)
    _line(L, "archive_cool", "storage", "Raw archive, cool ZRS (remaining retention)", "stock", archive_gb_month * max(arch_ret - hot_m, 0.0) * 12, "GB-months", "adls_cool_zrs_gb_month", pr("adls_cool_zrs_gb_month"), arch_ret)
    _line(L, "other_blob", "storage", "Models, ledger segments, backups (hot ZRS)", "provisioned", A["other_blob_gb_per_plant"] * s * 12, "GB-months", "adls_hot_zrs_gb_month", pr("adls_hot_zrs_gb_month"))
    capacity = sum(x["annual"] for x in L if x["family"] == "storage")
    _line(L, "storage_transactions", "storage", "Storage transactions (% of capacity charges)", "stock", capacity, "USD of capacity charges", None, A["storage_transactions_uplift_pct"], arch_ret)

    # --- Container Apps compute
    vcpu = A["compute_vcpu_per_plant"] * s
    _line(L, "aca_vcpu", "compute", "Container Apps dedicated vCPU (always-on agents, APIs)", "provisioned", vcpu * HOURS_PER_YEAR, "vCPU-hours", "aca_dedicated_vcpu_hour", pr("aca_dedicated_vcpu_hour"))
    _line(L, "aca_mem", "compute", "Container Apps dedicated memory", "provisioned", vcpu * A["compute_gib_per_vcpu"] * HOURS_PER_YEAR, "GiB-hours", "aca_dedicated_memory_gib_hour", pr("aca_dedicated_memory_gib_hour"))
    burst_h = A["compute_burst_vcpu_hours_per_plant_month"] * 12 * s
    _line(L, "aca_burst_cpu", "compute", "Container Apps burst vCPU (what-if forks, A/B replay)", "usage", burst_h * 3600.0, "vCPU-seconds", "aca_consumption_vcpu_second", pr("aca_consumption_vcpu_second"))
    _line(L, "aca_burst_mem", "compute", "Container Apps burst memory", "usage", burst_h * A["compute_gib_per_vcpu"] * 3600.0, "GiB-seconds", "aca_consumption_memory_gib_second", pr("aca_consumption_memory_gib_second"))

    # --- Networking
    _line(L, "er_circuit", "networking", "ExpressRoute 200 Mbps metered circuit", "provisioned", er_circuits * 12, "circuit-months", "expressroute_200mbps_metered_circuit_month", pr("expressroute_200mbps_metered_circuit_month"))
    _line(L, "vpn_gateway", "networking", "VPN gateway VpnGw1AZ (backup path)", "provisioned", vpn_gateways * HOURS_PER_YEAR, "gateway-hours", "vpn_gateway_vpngw1az_hour", pr("vpn_gateway_vpngw1az_hour"))
    _line(L, "private_endpoints", "networking", "Private endpoints", "provisioned", A["private_endpoints_per_plant"] * HOURS_PER_YEAR, "endpoint-hours", "private_endpoint_hour", pr("private_endpoint_hour"))
    _line(L, "private_link_data", "networking", "Private Link data processed", "usage", A["private_link_gb_per_plant_month"] * 12 * s, "GB", "private_link_data_processed_gb", pr("private_link_data_processed_gb"))
    _line(L, "inter_region", "networking", "Inter-region replication traffic", "usage", A["inter_region_gb_per_plant_month"] * 12 * s, "GB", "inter_region_transfer_gb", pr("inter_region_transfer_gb"))

    # --- Security
    _line(L, "defender_containers", "security", "Defender for Containers (edge cluster vCores)", "provisioned", edge_nodes * A["edge_vcores_per_node"] * HOURS_PER_YEAR, "vCore-hours", "defender_containers_vcore_hour", pr("defender_containers_vcore_hour"))
    _line(L, "defender_storage", "security", "Defender for Storage accounts", "provisioned", A["defender_storage_accounts_per_plant"] * HOURS_PER_YEAR, "account-hours", "defender_storage_account_hour", pr("defender_storage_account_hour"))
    _line(L, "defender_cosmos", "security", "Defender for Cosmos DB", "provisioned", A["cosmos_max_ru_per_plant"] * s / 100.0 * cosmos_regions * HOURS_PER_YEAR, "100-RU/s-hours", "defender_cosmos_100ru_hour", pr("defender_cosmos_100ru_hour"))
    _line(L, "sentinel", "security", "Microsoft Sentinel ingestion + analysis", "usage", A["sentinel_gb_per_plant_day"] * 365.0 * s, "GB", "sentinel_payg_gb", pr("sentinel_payg_gb"))
    _line(L, "keyvault_ops", "security", "Key Vault operations", "usage", A["keyvault_million_ops_per_plant_month"] * 12 * 100.0 * s, "10K operations", "keyvault_operations_per_10k", pr("keyvault_operations_per_10k"))

    # --- Monitoring
    la_gb = A["loganalytics_gb_per_plant_day"] * s
    _line(L, "la_ingestion", "monitoring", "Log Analytics / App Insights ingestion", "usage", la_gb * 365.0, "GB", "loganalytics_ingestion_gb", pr("loganalytics_ingestion_gb"))
    _line(L, "la_retention", "monitoring", "Log Analytics retention beyond 31 days", "usage", la_gb * max(A["loganalytics_retention_days"] - 31.0, 0.0) * 12, "GB-months", "loganalytics_retention_gb_month", pr("loganalytics_retention_gb_month"))
    return L


def _aggregate_lines(A: dict, P: dict, plants: float, s: float, shared_scale: float, *, er_gateways: float, front_door: float, ai_search_base_units: float) -> list[dict]:
    """Annual cost of the shared enterprise platform for a given number of active plants."""
    mult = A["azure_price_multiplier"]

    def pr(key: str) -> float:
        return P[key] * mult

    L: list[dict] = []
    ref_assets = A["reference_assets_per_plant"]
    search_units = ai_search_base_units + math.floor(plants / A["ai_search_plants_per_extra_unit"])
    _line(L, "ai_search", "ai_foundry", "AI Search S1 units (shared)", "shared", search_units * HOURS_PER_YEAR, "unit-hours", "ai_search_s1_unit_hour", pr("ai_search_s1_unit_hour"))
    aml_instances = max(A["aml_endpoint_min_instances"], math.ceil(plants * A["aml_endpoint_instances_per_plant"]))
    _line(L, "aml_endpoints", "azure_ml", "Managed online endpoint instances D4s v5 (shared)", "shared", aml_instances * HOURS_PER_YEAR, "instance-hours", "vm_d4s_v5_hour", pr("vm_d4s_v5_hour"))
    cu_needed = A["fabric_base_cu"] * shared_scale + plants * A["fabric_cu_per_plant"] * s
    gran = A["fabric_cu_granularity"]
    cu = math.ceil(cu_needed / gran - 1e-9) * gran
    _line(L, "fabric_capacity", "fabric", "Fabric capacity (Eventstream, Eventhouse, Activator, Power BI), 24x7", "shared", cu * HOURS_PER_YEAR, "CU-hours", "fabric_cu_hour", pr("fabric_cu_hour"))
    msgs_s = _msgs_per_second(A, s * ref_assets)
    tu = max(A["eventhubs_min_tu"], math.ceil(plants * msgs_s / 1000.0 * A["eventhubs_headroom_factor"] - 1e-9))
    _line(L, "eventhubs_tu", "messaging", "Event Hubs Standard throughput units", "shared", tu * HOURS_PER_YEAR, "TU-hours", "eventhubs_standard_tu_hour", pr("eventhubs_standard_tu_hour"))
    _line(L, "servicebus", "messaging", "Service Bus Standard base unit", "shared", HOURS_PER_YEAR, "unit-hours", "servicebus_standard_base_hour", pr("servicebus_standard_base_hour"))
    ent_vcpu = A["compute_enterprise_vcpu"] * shared_scale
    _line(L, "aca_ent_vcpu", "compute", "Shared platform dedicated vCPU", "shared", ent_vcpu * HOURS_PER_YEAR, "vCPU-hours", "aca_dedicated_vcpu_hour", pr("aca_dedicated_vcpu_hour"))
    _line(L, "aca_ent_mem", "compute", "Shared platform dedicated memory", "shared", ent_vcpu * A["compute_gib_per_vcpu"] * HOURS_PER_YEAR, "GiB-hours", "aca_dedicated_memory_gib_hour", pr("aca_dedicated_memory_gib_hour"))
    _line(L, "aca_plan", "compute", "Container Apps dedicated plan management", "shared", A["compute_dedicated_profiles"] * HOURS_PER_YEAR, "profile-hours", "aca_dedicated_plan_management_hour", pr("aca_dedicated_plan_management_hour"))
    _line(L, "acr", "compute", "Container Registry Premium replicas", "shared", A["acr_replicas"] * 365.0, "replica-days", "acr_premium_registry_day", pr("acr_premium_registry_day"))
    _line(L, "er_gateway", "networking", "ExpressRoute gateways ErGw1AZ", "shared", er_gateways * HOURS_PER_YEAR, "gateway-hours", "expressroute_gateway_ergw1az_hour", pr("expressroute_gateway_ergw1az_hour"))
    _line(L, "front_door", "networking", "Azure Front Door Premium base fee", "shared", front_door * 12, "profile-months", "front_door_premium_base_month", pr("front_door_premium_base_month"))
    _line(L, "shared_pe", "networking", "Shared private endpoints", "shared", A["private_endpoints_shared"] * shared_scale * HOURS_PER_YEAR, "endpoint-hours", "private_endpoint_hour", pr("private_endpoint_hour"))
    _line(L, "sentinel_shared", "security", "Sentinel ingestion + analysis (shared sources)", "shared", A["sentinel_gb_shared_day"] * shared_scale * 365.0, "GB", "sentinel_payg_gb", pr("sentinel_payg_gb"))
    _line(L, "defender_rm", "security", "Defender for Resource Manager", "shared", A["defender_subscriptions_shared"] * HOURS_PER_YEAR, "subscription-hours", "defender_resource_manager_hour", pr("defender_resource_manager_hour"))
    _line(L, "defender_storage_shared", "security", "Defender for Storage (shared accounts)", "shared", A["defender_storage_accounts_shared"] * HOURS_PER_YEAR, "account-hours", "defender_storage_account_hour", pr("defender_storage_account_hour"))
    la_gb = A["loganalytics_gb_shared_day"] * shared_scale
    _line(L, "la_shared", "monitoring", "Log Analytics ingestion (shared platform)", "shared", la_gb * 365.0, "GB", "loganalytics_ingestion_gb", pr("loganalytics_ingestion_gb"))
    _line(L, "la_shared_ret", "monitoring", "Log Analytics retention beyond 31 days (shared)", "shared", la_gb * max(A["loganalytics_retention_days"] - 31.0, 0.0) * 12, "GB-months", "loganalytics_retention_gb_month", pr("loganalytics_retention_gb_month"))
    return L


def _shared_scale(A: dict, plants: float) -> float:
    pts = sorted((float(p[0]), float(p[1])) for p in A["shared_scale_points"])
    if plants <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if plants <= x1:
            return y0 + (y1 - y0) * (plants - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (y1 - y0) * (plants - x1) / (x1 - x0)


def _uplift(A: dict, family: str, dr: bool) -> float:
    return (A["nonprod_environment_uplift_pct"] if family in NONPROD_FAMILIES else 0.0) + (A["dr_uplift_pct"] if (dr and family in DR_FAMILIES) else 0.0)


def _steady_state(A: dict, P: dict, plants: int, s: float, *, tier: dict | None = None) -> dict:
    """Mature, full-year Azure consumption for `plants` plants of relative size s (the run-rate)."""
    tier = tier or {}
    edge_nodes = tier.get("edge_nodes", A["edge_nodes_per_plant"])
    er = tier.get("er_circuits", A["er_circuits_per_plant"])
    vpn = tier.get("vpn_gateways", A["vpn_gateways_per_plant"])
    regions = tier.get("cosmos_regions", A["cosmos_regions"])
    dr = tier.get("dr", True)
    scale = tier.get("shared_scale", _shared_scale(A, plants))
    per_plant = _plant_lines(A, P, s, edge_nodes=edge_nodes, er_circuits=er, vpn_gateways=vpn, cosmos_regions=regions)
    agg = _aggregate_lines(A, P, plants, s, scale, er_gateways=tier.get("er_gateways", A["er_gateways_shared"]),
                           front_door=tier.get("front_door", A["front_door_shared"]), ai_search_base_units=tier.get("ai_search_base_units", A["ai_search_base_units"]))
    lines: list[dict] = []
    fam = {f: 0.0 for f, _ in AZURE_FAMILIES}
    for ln in per_plant:
        row = dict(ln)
        row["quantity"] = ln["quantity"] * plants
        row["annual"] = ln["annual"] * plants
        row["lever"] = "core"
        lines.append(row)
        fam[ln["family"]] += row["annual"]
    for ln in agg:
        row = dict(ln)
        row["lever"] = "core"
        lines.append(row)
        fam[ln["family"]] += ln["annual"]
    for f, _ in AZURE_FAMILIES:
        u = _uplift(A, f, dr)
        if u:
            extra = fam[f] * u
            lines.append({"id": f"uplift_{f}", "family": f, "item": "Dev/test and DR environments (% of family charges)", "kind": "uplift", "quantity": fam[f], "unit": "USD of family charges",
                          "price_id": None, "unit_price": u, "annual": extra, "retention_months": None, "lever": "core"})
            fam[f] += extra
    by_lever = {"core": sum(fam.values())}
    by_lever.update({lid: 0.0 for lid in LEVER_IDS})
    if tier.get("levers", True):
        for sp in _lever_specs(A, P):
            lines_l, fam_l = _lever_steady(A, sp, plants, scale)
            lines.extend(lines_l)
            for f, v in fam_l.items():
                fam[f] += v
            by_lever[sp["id"]] = sum(fam_l.values())
    return {"plants": plants, "relative_plant_size": s, "shared_scale": scale, "by_family": fam, "total": sum(fam.values()), "lines": lines, "by_lever": by_lever}


def _attach(by_family: dict) -> tuple[dict, float | None]:
    total = sum(by_family.values())
    cat = {}
    for name, fams in ATTACH_CATEGORIES.items():
        v = sum(by_family[f] for f in fams)
        cat[name] = {"annual": v, "share": (v / total) if total else 0.0}
    core = cat["ai_core"]["annual"]
    ratio = ((total - core) / core) if core > 0 else None
    return cat, ratio


# --------------------------------------------------------------------------------------------- expansion levers
def _lline(lines: list, lever: str, lid: str, family: str, label: str, kind: str, quantity: float, unit: str, price_id: str | None,
           unit_price: float, retention_months: float | None = None) -> None:
    _line(lines, lid, family, label, kind, quantity, unit, price_id, unit_price, retention_months)
    lines[-1]["lever"] = lever


def _lever_base(lid: str, A: dict) -> dict:
    prefix = next(p for i, p, _ in EXPANSION_LEVERS if i == lid)
    return {"id": lid, "label": LEVER_LABELS[lid], "prefix": prefix, "adoption": float(A[prefix + "_adoption"]), "lag": int(A[prefix + "_start_lag_months"]),
            "dr": True, "lines": [], "shared": None, "one_time": {}, "enterprise_one_time": {}, "run": {}, "enterprise_run": {},
            "hardware_usd": 0.0, "benefit_gross": {}, "confidence": {}}


def _storage_stock(L: list, lever: str, tag: str, A: dict, pr, gb_month: float, retention: float, family: str = "storage") -> None:
    """Hot then cool ZRS archive that fills up over `retention` months (same pattern as the core raw archive)."""
    hot = min(A["storage_hot_months"], retention)
    _lline(L, lever, f"{tag}_hot", family, "Archive, hot ZRS (first months)", "stock", gb_month * hot * 12, "GB-months", "adls_hot_zrs_gb_month", pr("adls_hot_zrs_gb_month"), retention)
    _lline(L, lever, f"{tag}_cool", family, "Archive, cool ZRS (remaining retention)", "stock", gb_month * max(retention - hot, 0.0) * 12, "GB-months", "adls_cool_zrs_gb_month", pr("adls_cool_zrs_gb_month"), retention)
    capacity = sum(x["annual"] for x in L if x["id"] in (f"{tag}_hot", f"{tag}_cool"))
    _lline(L, lever, f"{tag}_tx", family, "Storage transactions (% of capacity charges)", "stock", capacity, "USD of capacity charges", None, A["storage_transactions_uplift_pct"], retention)


def _log_lines(L: list, lever: str, tag: str, A: dict, pr, gb_day: float) -> None:
    _lline(L, lever, f"{tag}_la", "monitoring", "Log Analytics ingestion (pipeline telemetry)", "usage", gb_day * 365.0, "GB", "loganalytics_ingestion_gb", pr("loganalytics_ingestion_gb"))
    _lline(L, lever, f"{tag}_la_ret", "monitoring", "Log Analytics retention beyond 31 days", "usage", gb_day * max(A["loganalytics_retention_days"] - 31.0, 0.0) * 12, "GB-months", "loganalytics_retention_gb_month", pr("loganalytics_retention_gb_month"))


def _spec_vision(A: dict, P: dict, D: dict) -> dict:
    sp, k, mult = _lever_base("E1", A), "exp_vision_", A["azure_price_multiplier"]
    pr = lambda key: P[key] * mult  # noqa: E731
    L = sp["lines"]
    cams = A[k + "cameras_per_plant"]
    scored_day = cams * A[k + "fps_per_camera"] * A[k + "hours_per_day"] * 3600.0
    gb_month = scored_day * A[k + "upload_share"] * A[k + "image_mb"] / 1e3 * 365.0 / 12.0
    _storage_stock(L, "E1", "vision_archive", A, pr, gb_month, A[k + "retention_months"])
    _lline(L, "E1", "vision_train_t4", "azure_ml", "Vision retraining and back-testing, NC8as T4 v3", "usage", A[k + "models_per_plant"] * A[k + "retrains_per_model_year"] * A[k + "gpu_hours_per_retrain"], "hours", "vm_nc8as_t4_v3_hour", pr("vm_nc8as_t4_v3_hour"))
    _lline(L, "E1", "vision_finetune_a100", "azure_ml", "Vision foundation-model fine-tuning, NC24ads A100 v4", "usage", A[k + "a100_hours_per_plant_month"] * 12, "hours", "vm_nc24ads_a100_v4_hour", pr("vm_nc24ads_a100_v4_hour"))
    esc_day = scored_day * A[k + "escalation_share"] * A["llm_usage_multiplier"]
    hard = A[k + "escalation_gpt54_share"]
    mini_calls, big_calls = esc_day * (1.0 - hard) * 365.0, esc_day * hard * 365.0
    _lline(L, "E1", "vision_mini_in", "ai_foundry", "gpt-5.4-mini input tokens (vision escalations)", "usage", mini_calls * A["llm_vision_in_tokens"] / 1e6, "M tokens", "gpt54_mini_input_per_1m", pr("gpt54_mini_input_per_1m"))
    _lline(L, "E1", "vision_mini_out", "ai_foundry", "gpt-5.4-mini output tokens (vision escalations)", "usage", mini_calls * A["llm_vision_out_tokens"] / 1e6, "M tokens", "gpt54_mini_output_per_1m", pr("gpt54_mini_output_per_1m"))
    _lline(L, "E1", "vision_big_in", "ai_foundry", "gpt-5.4 input tokens (hard cases)", "usage", big_calls * A[k + "gpt54_in_tokens"] / 1e6, "M tokens", "gpt54_input_per_1m", pr("gpt54_input_per_1m"))
    _lline(L, "E1", "vision_big_out", "ai_foundry", "gpt-5.4 output tokens (hard cases)", "usage", big_calls * A[k + "gpt54_out_tokens"] / 1e6, "M tokens", "gpt54_output_per_1m", pr("gpt54_output_per_1m"))
    _log_lines(L, "E1", "vision", A, pr, A[k + "la_gb_per_plant_day"])
    hw = cams * A[k + "station_cost_usd"] + A[k + "edge_gpu_servers_per_plant"] * A[k + "edge_gpu_server_cost_usd"]
    sp["hardware_usd"] = hw
    sp["one_time"] = {"edge_hardware": hw, "integration": A[k + "integration_usd"], "change_management": A[k + "change_usd"]}
    sp["run"] = {"licences": cams * A[k + "licence_per_camera_usd_year"], "agentops": A[k + "review_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"],
                 "hardware_support": hw * A["hardware_support_pct_per_year"]}
    sp["benefit_gross"] = {"scrap": D["plant_revenue_usd"] * A[k + "quality_cost_pct_revenue"] * A[k + "quality_reduction_pct"],
                           "labour": A[k + "inspectors_per_plant"] * A["productive_hours_per_fte_year"] * A[k + "inspection_labour_reduction_pct"] * A[k + "inspector_rate_usd_hour"]}
    sp["confidence"] = {"scrap": A[k + "conf_quality"], "labour": A[k + "conf_labour"]}
    return sp


def _spec_hf(A: dict, P: dict, D: dict) -> dict:
    sp, k, mult = _lever_base("E2", A), "exp_hf_", A["azure_price_multiplier"]
    pr = lambda key: P[key] * mult  # noqa: E731
    L = sp["lines"]
    assets = A["assets_per_plant"] * A[k + "rotating_assets_share"]
    raw_bytes_day = assets * A[k + "channels_per_asset"] * A[k + "sample_rate_khz"] * 1e3 * A[k + "bytes_per_sample"] * 86400.0 * A[k + "duty_cycle"]
    stored_gb_day = raw_bytes_day / A[k + "compression_ratio"] / 1e9
    _lline(L, "E2", "hf_eventhubs", "messaging", "Event Hubs ingress events (waveform batches)", "usage", stored_gb_day * 1e9 * 365.0 / (A[k + "event_kb"] * 1e3) / 1e6, "M events", "eventhubs_standard_ingress_per_1m", pr("eventhubs_standard_ingress_per_1m"))
    _storage_stock(L, "E2", "hf_raw", A, pr, stored_gb_day * 365.0 / 12.0, A[k + "raw_retention_months"])
    feat_gb_month = assets * A[k + "feature_gb_per_asset_day"] * 365.0 / 12.0
    _lline(L, "E2", "hf_features", "fabric", "OneLake storage (extracted features)", "stock", feat_gb_month * A[k + "feature_retention_months"] * 12, "GB-months", "onelake_hot_gb_month", pr("onelake_hot_gb_month"), A[k + "feature_retention_months"])
    _lline(L, "E2", "hf_fabric", "fabric", "Fabric capacity for feature extraction and Eventhouse queries", "provisioned", A[k + "fabric_cu_per_plant"] * HOURS_PER_YEAR, "CU-hours", "fabric_cu_hour", pr("fabric_cu_hour"))
    _lline(L, "E2", "hf_train_cpu", "azure_ml", "Failure-signature training compute D16s v5", "usage", A[k + "train_hours_per_plant_month"] * 12, "hours", "vm_d16s_v5_hour", pr("vm_d16s_v5_hour"))
    _lline(L, "E2", "hf_train_gpu", "azure_ml", "Waveform model training NC8as T4 v3", "usage", A[k + "gpu_hours_per_plant_month"] * 12, "hours", "vm_nc8as_t4_v3_hour", pr("vm_nc8as_t4_v3_hour"))
    _lline(L, "E2", "hf_endpoint", "azure_ml", "Managed online endpoint instances D4s v5", "provisioned", A[k + "endpoint_instances_per_plant"] * HOURS_PER_YEAR, "instance-hours", "vm_d4s_v5_hour", pr("vm_d4s_v5_hour"))
    _log_lines(L, "E2", "hf", A, pr, A[k + "la_gb_per_plant_day"])
    hw = assets * A[k + "sensor_cost_per_asset_usd"]
    sp["hardware_usd"] = hw
    sp["one_time"] = {"edge_hardware": hw, "integration": A[k + "integration_usd"], "change_management": A[k + "change_usd"]}
    sp["run"] = {"licences": assets * A[k + "licence_per_asset_usd_year"], "agentops": A[k + "review_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"],
                 "hardware_support": hw * A["hardware_support_pct_per_year"]}
    baseline_hours = D["baseline_unplanned_downtime_hours_per_plant_year"]
    sp["benefit_gross"] = {"downtime": baseline_hours * A[k + "extra_downtime_reduction_pct"] * D["downtime_cost_per_line_hour_usd"],
                           "maintenance": D["plant_revenue_usd"] * A["maintenance_spend_pct_revenue"] * A[k + "extra_maintenance_reduction_pct"]}
    sp["confidence"] = {"downtime": A[k + "conf_downtime"], "maintenance": A[k + "conf_maintenance"]}
    return sp


def _spec_sim(A: dict, P: dict, D: dict) -> dict:
    sp, k, mult = _lever_base("E3", A), "exp_sim_", A["azure_price_multiplier"]
    pr = lambda key: P[key] * mult  # noqa: E731
    sp["dr"] = False  # stateless simulation workers are re-created on demand: no DR uplift
    L = sp["lines"]
    vcpu_s_day = A[k + "decisions_per_plant_day"] * A[k + "rollouts_per_decision"] * A[k + "vcpu_seconds_per_rollout"]
    vm_hours = vcpu_s_day * 365.0 / 3600.0 / 16.0 / A[k + "node_utilisation"]
    _lline(L, "E3", "sim_nodes", "compute", "What-if simulation pools, D16s v5 (AKS / Batch)", "usage", vm_hours, "VM-hours", "vm_d16s_v5_hour", pr("vm_d16s_v5_hour"))
    ret = A[k + "result_retention_months"]
    _lline(L, "E3", "sim_results", "storage", "Simulation results and rollout logs, hot ZRS", "stock", A[k + "result_gb_per_plant_day"] * 365.0 / 12.0 * ret * 12, "GB-months", "adls_hot_zrs_gb_month", pr("adls_hot_zrs_gb_month"), ret)
    units = A[k + "cosmos_max_ru"] * A["cosmos_autoscale_avg_fraction"] / 100.0
    _lline(L, "E3", "sim_cosmos", "cosmos", f"Cosmos DB autoscale throughput x {A['cosmos_regions']:g} region(s) (twin snapshots, scenario cache)", "provisioned", units * HOURS_PER_YEAR * A["cosmos_regions"], "100-RU/s-hours", "cosmos_autoscale_100ru_hour", pr("cosmos_autoscale_100ru_hour"))
    _log_lines(L, "E3", "sim", A, pr, A[k + "la_gb_per_plant_day"])
    sp["one_time"] = {"integration": A[k + "integration_usd"], "change_management": A[k + "change_usd"]}
    sp["run"] = {"agentops": A[k + "agentops_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"]}
    rev = D["plant_revenue_usd"]
    sp["benefit_gross"] = {"labour": A["indirect_labour_fte_per_plant"] * A["productive_hours_per_fte_year"] * A[k + "extra_labour_gain_pct"] * A["loaded_labour_rate_usd_per_hour"],
                           "energy": rev * A["energy_spend_pct_revenue"] * A[k + "extra_energy_saving_pct"],
                           "throughput": rev * (A[k + "extra_oee_pts"] / A["baseline_oee_pct"]) * A["contribution_margin_pct"] * A["demand_capture_pct"]}
    sp["confidence"] = {"labour": A[k + "conf_labour"], "energy": A[k + "conf_energy"], "throughput": A[k + "conf_throughput"]}
    return sp


def _spec_dp(A: dict, P: dict, D: dict) -> dict:
    sp, k, mult = _lever_base("E4", A), "exp_dp_", A["azure_price_multiplier"]
    pr = lambda key: P[key] * mult  # noqa: E731
    L = sp["lines"]
    msgs_s = _msgs_per_second(A, A["assets_per_plant"])
    stored_gb_day = msgs_s * 86400.0 * A["bytes_per_message"] / 1e9 / A["compression_ratio"]
    extra_ret = max(A[k + "onelake_retention_months"] - A["onelake_retention_months"], 0.0)
    _lline(L, "E4", "dp_onelake_ext", "fabric", "OneLake storage, extended retention of curated telemetry", "stock", stored_gb_day * 365.0 / 12.0 * extra_ret * 12, "GB-months", "onelake_hot_gb_month", pr("onelake_hot_gb_month"), A[k + "onelake_retention_months"])
    _lline(L, "E4", "dp_historian", "fabric", "OneLake storage, migrated historian archive", "provisioned", A[k + "historian_tb_per_plant"] * 1000.0 * 12, "GB-months", "onelake_hot_gb_month", pr("onelake_hot_gb_month"))
    _log_lines(L, "E4", "dp", A, pr, A[k + "la_gb_per_plant_day"])

    def shared(dep: float, scale: float) -> list[dict]:
        need = dep * A[k + "fabric_cu_per_plant"] + A[k + "fabric_cu_enterprise"] * scale
        gran = A["fabric_cu_granularity"]
        cu = math.ceil(need / gran - 1e-9) * gran
        out: list[dict] = []
        _lline(out, "E4", "dp_fabric", "fabric", "Fabric capacity for enterprise analytics, historian back-fill and Power BI", "shared", cu * HOURS_PER_YEAR, "CU-hours", "fabric_cu_hour", pr("fabric_cu_hour"))
        return out

    sp["shared"] = shared
    sp["one_time"] = {"integration": A[k + "migration_per_plant_usd"], "change_management": A[k + "change_per_plant_usd"]}
    sp["enterprise_one_time"] = {"integration": A[k + "programme_enterprise_usd"]}
    sp["run"] = {"agentops": A[k + "data_eng_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"]}
    sp["enterprise_run"] = {"licences": A[k + "bi_creators"] * A[k + "bi_pro_usd_month"] * 12.0}
    sp["benefit_gross"] = {"data_platform": A[k + "avoided_historian_usd_per_plant_year"] + A[k + "avoided_bi_usd_per_plant_year"]
                           + A[k + "analytics_hours_saved_per_plant_year"] * A[k + "analyst_rate_usd_hour"]}
    sp["confidence"] = {"data_platform": A[k + "conf"]}
    return sp


def _spec_sec(A: dict, P: dict, D: dict) -> dict:
    sp, k, mult = _lever_base("E5", A), "exp_sec_", A["azure_price_multiplier"]
    pr = lambda key: P[key] * mult  # noqa: E731
    L = sp["lines"]
    _lline(L, "E5", "sec_er_circuit", "networking", "ExpressRoute 1 Gbps metered circuit, diverse second path", "provisioned", A[k + "er_circuits_per_plant"] * 12, "circuit-months", "expressroute_1gbps_metered_circuit_month", pr("expressroute_1gbps_metered_circuit_month"))
    _lline(L, "E5", "sec_er_data", "networking", "ExpressRoute metered data out (Azure to plant)", "usage", A[k + "er_gb_out_per_plant_month"] * 12, "GB", "expressroute_metered_data_out_gb", pr("expressroute_metered_data_out_gb"))
    _lline(L, "E5", "sec_fw_data", "networking", "Azure Firewall Premium data processed", "usage", A[k + "fw_gb_per_plant_month"] * 12, "GB", "azure_firewall_premium_data_processed_gb", pr("azure_firewall_premium_data_processed_gb"))
    _lline(L, "E5", "sec_servers", "security", "Defender for Servers P2 (Arc-enabled OT servers)", "provisioned", A[k + "servers_per_plant"] * HOURS_PER_YEAR, "server-hours", "defender_servers_p2_node_hour", pr("defender_servers_p2_node_hour"))
    _lline(L, "E5", "sec_sentinel", "security", "Microsoft Sentinel ingestion + analysis (OT security logs)", "usage", A[k + "sentinel_gb_per_plant_day"] * 365.0, "GB", "sentinel_payg_gb", pr("sentinel_payg_gb"))
    _log_lines(L, "E5", "sec", A, pr, A[k + "la_gb_per_plant_day"])

    def shared(dep: float, scale: float) -> list[dict]:
        hubs = max(1, math.ceil(dep / A[k + "plants_per_hub"] - 1e-9))
        out: list[dict] = []
        _lline(out, "E5", "sec_firewall", "networking", "Azure Firewall Premium in the regional hub", "shared", hubs * HOURS_PER_YEAR, "deployment-hours", "azure_firewall_premium_deployment_hour", pr("azure_firewall_premium_deployment_hour"))
        return out

    sp["shared"] = shared
    hw = A[k + "sensors_per_plant"] * A[k + "sensor_cost_usd"]
    sp["hardware_usd"] = hw
    sp["one_time"] = {"edge_hardware": hw, "integration": A[k + "integration_usd"], "change_management": A[k + "change_usd"]}
    sp["run"] = {"licences": A[k + "ot_site_licence_usd_year"], "agentops": A[k + "soc_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"],
                 "hardware_support": hw * A["hardware_support_pct_per_year"]}
    sp["benefit_gross"] = {"cyber_risk": A[k + "incident_prob_per_plant_year"] * A[k + "incident_cost_usd"] * A[k + "risk_reduction_pct"]
                           + A[k + "insurance_premium_usd_per_plant"] * A[k + "premium_reduction_pct"]}
    sp["confidence"] = {"cyber_risk": A[k + "conf"]}
    return sp


def _lever_specs(A: dict, P: dict) -> list[dict]:
    """The five expansion levers resolved against the assumptions (built even when adoption is 0, so every input is always read)."""
    D = _plant_benefits(A)[2]
    specs = [_spec_vision(A, P, D), _spec_hf(A, P, D), _spec_sim(A, P, D), _spec_dp(A, P, D), _spec_sec(A, P, D)]
    for sp in specs:
        sp["benefit_adj"] = {c: sp["benefit_gross"][c] * sp["confidence"][c] for c in sp["benefit_gross"]}
        prov = {f: 0.0 for f, _ in AZURE_FAMILIES}
        usage = dict(prov)
        stock = []
        for ln in sp["lines"]:
            if ln["kind"] == "provisioned":
                prov[ln["family"]] += ln["annual"] / 12.0
            elif ln["kind"] == "usage":
                usage[ln["family"]] += ln["annual"] / 12.0
            else:
                stock.append((ln["family"], ln["annual"] / 12.0, max(float(ln["retention_months"] or 1.0), 1.0)))
        sp["prov"], sp["usage"], sp["stock"] = prov, usage, stock
    return specs


def _lever_steady(A: dict, spec: dict, plants: float, scale: float) -> tuple[list[dict], dict]:
    """Annual steady-state Azure lines of one lever for `plants` plants (expected value: plants x adoption), with dev/test and DR uplifts."""
    dep = plants * spec["adoption"]
    fam = {f: 0.0 for f, _ in AZURE_FAMILIES}
    if dep <= 0:
        return [], fam
    lines: list[dict] = []
    for ln in spec["lines"]:
        row = dict(ln)
        row["quantity"] = ln["quantity"] * dep
        row["annual"] = ln["annual"] * dep
        lines.append(row)
        fam[ln["family"]] += row["annual"]
    if spec["shared"]:
        for ln in spec["shared"](dep, scale):
            lines.append(dict(ln))
            fam[ln["family"]] += ln["annual"]
    for f, _ in AZURE_FAMILIES:
        u = _uplift(A, f, spec["dr"])
        if u and fam[f]:
            extra = fam[f] * u
            lines.append({"id": f"uplift_{spec['id']}_{f}", "family": f, "item": "Dev/test and DR environments (% of family charges)", "kind": "uplift", "quantity": fam[f],
                          "unit": "USD of family charges", "price_id": None, "unit_price": u, "annual": extra, "retention_months": None, "lever": spec["id"]})
            fam[f] += extra
    return lines, fam


# --------------------------------------------------------------------------------------------- cohorts & simulation
def _cohorts(A: dict, years: int) -> list[dict]:
    n = A["plants_total"]
    share = list(A["plants_cum_share_by_year"])
    prev = 0
    out = []
    for y in range(years):
        s = share[y] if y < len(share) else 1.0
        cum = int(math.floor(n * s + 0.5))
        cum = max(prev, min(n, cum))
        if cum > prev:
            out.append({"year": y + 1, "plants": cum - prev, "go_live_month": y * 12 + int(A["go_live_month_in_year"]) - 1, "prior_plants": prev})
        prev = cum
    return out


def _hardware_per_plant(A: dict) -> float:
    return (A["edge_servers_per_plant"] * A["edge_server_cost_usd"] + A["ot_network_security_hw_usd_per_plant"]
            + A["sensor_retrofit_share_of_assets"] * A["assets_per_plant"] * A["sensor_retrofit_cost_per_asset_usd"]
            + A["legacy_gateways_per_plant"] * A["gateway_cost_usd"])


def _simulate(A: dict, P: dict, months: int) -> dict:
    years = months // 12
    cohorts = _cohorts(A, years)
    gross, adj, derived = _plant_benefits(A)
    ramp, uramp = A["benefit_ramp"], A["usage_ramp"]
    s = A["assets_per_plant"] / A["reference_assets_per_plant"]
    per_plant = _plant_lines(A, P, s, edge_nodes=A["edge_nodes_per_plant"], er_circuits=A["er_circuits_per_plant"],
                             vpn_gateways=A["vpn_gateways_per_plant"], cosmos_regions=A["cosmos_regions"])
    prov = {f: 0.0 for f, _ in AZURE_FAMILIES}
    usage = {f: 0.0 for f, _ in AZURE_FAMILIES}
    stock = []
    for ln in per_plant:
        if ln["kind"] == "provisioned":
            prov[ln["family"]] += ln["annual"] / 12.0
        elif ln["kind"] == "usage":
            usage[ln["family"]] += ln["annual"] / 12.0
        else:
            stock.append((ln["family"], ln["annual"] / 12.0, max(float(ln["retention_months"] or 1.0), 1.0)))
    hw = _hardware_per_plant(A)
    cont = A["contingency_pct_one_time"]
    specs = _lever_specs(A, P)
    eramp, euramp = A["exp_benefit_ramp"], A["exp_usage_ramp"]
    benefit = {c: [0.0] * months for c, _ in BENEFIT_CATEGORIES}
    for sp in specs:
        if sp["adoption"] > 0:
            for cat in sp["benefit_adj"]:
                benefit.setdefault(cat, [0.0] * months)
    azure = {f: [0.0] * months for f, _ in AZURE_FAMILIES}
    other = {c: [0.0] * months for c, _ in OTHER_COST_CATEGORIES}
    lever_azure = {sp["id"]: [0.0] * months for sp in specs}
    lever_benefit = {sp["id"]: [0.0] * months for sp in specs}
    lever_cost = {sp["id"]: [0.0] * months for sp in specs}  # customer-side costs of the lever incl. contingency (Azure is in lever_azure)
    live_plants = [0] * months
    active_plants = [0] * months
    agg_cache: dict[int, list[dict]] = {}

    def add_one_time(cat: str, month: int, amount: float, lever: str | None = None) -> None:
        month = min(max(month, 0), months - 1)
        other[cat][month] += amount
        other["contingency"][month] += amount * cont
        if lever:
            lever_cost[lever][month] += amount * (1.0 + cont)

    add_one_time("assessment", 0, A["readiness_assessment_usd"])
    add_one_time("integration", 0, A["platform_foundation_integration_usd"])
    for c in cohorts:
        n, gl = c["plants"], c["go_live_month"]
        add_one_time("edge_hardware", gl - int(A["hardware_lead_months"]), n * hw)
        first_n = max(0, min(n, int(A["integration_first_plants_count"]) - c["prior_plants"]))
        add_one_time("integration", gl - int(A["integration_lead_months"]), first_n * A["integration_per_plant_first_usd"] + (n - first_n) * A["integration_per_plant_next_usd"])
        add_one_time("change_management", gl - int(A["change_lead_months"]), n * A["change_mgmt_per_plant_usd"])
    lead_hw, lead_int, lead_chg = int(A["hardware_lead_months"]), int(A["integration_lead_months"]), int(A["change_lead_months"])
    for sp in specs:
        if sp["adoption"] <= 0 or not cohorts:
            continue
        lead_of = {"edge_hardware": lead_hw, "integration": lead_int, "change_management": lead_chg}
        for c in cohorts:
            n, st = c["plants"] * sp["adoption"], c["go_live_month"] + sp["lag"]
            for cat, amount in sp["one_time"].items():
                add_one_time(cat, st - lead_of[cat], n * amount, sp["id"])
        first_start = min(c["go_live_month"] + sp["lag"] for c in cohorts)
        for cat, amount in sp["enterprise_one_time"].items():
            add_one_time(cat, first_start - lead_of[cat], amount, sp["id"])
    first_go_live = min((c["go_live_month"] for c in cohorts), default=months)
    start = int(A["shared_platform_start_month"])
    lead = int(A["provision_lead_months"])
    for m in range(months):
        live = prov_n = 0
        ben_w = use_w = 0.0
        stock_w = [0.0] * len(stock)
        for c in cohorts:
            n, gl = c["plants"], c["go_live_month"]
            if m >= gl - lead:
                prov_n += n
            if m >= gl:
                age = m - gl
                k = min(age // 12, len(ramp) - 1)
                live += n
                ben_w += n * ramp[k]
                use_w += n * uramp[min(age // 12, len(uramp) - 1)]
                for i, (_, _, ret) in enumerate(stock):
                    stock_w[i] += n * min(1.0, (age + 1) / ret)
        live_plants[m] = live
        active_plants[m] = prov_n
        for cat, _ in BENEFIT_CATEGORIES:
            benefit[cat][m] = adj[cat] / 12.0 * ben_w
        fam_m = {f: prov[f] * prov_n + usage[f] * use_w for f, _ in AZURE_FAMILIES}
        for i, (f, monthly, _) in enumerate(stock):
            fam_m[f] += monthly * stock_w[i]
        if m >= start:
            n_eff = max(1, prov_n)
            if n_eff not in agg_cache:
                agg_cache[n_eff] = _aggregate_lines(A, P, n_eff, s, _shared_scale(A, n_eff), er_gateways=A["er_gateways_shared"],
                                                    front_door=A["front_door_shared"], ai_search_base_units=A["ai_search_base_units"])
            for ln in agg_cache[n_eff]:
                fam_m[ln["family"]] += ln["annual"] / 12.0
        for f, _ in AZURE_FAMILIES:
            azure[f][m] = fam_m[f] * (1.0 + _uplift(A, f, True))
        other["hardware_support"][m] = live * hw * A["hardware_support_pct_per_year"] / 12.0
        if m >= start:
            other["agentops"][m] = (A["agentops_fte_central"] + A["agentops_fte_per_plant"] * live) * A["agentops_fte_loaded_cost_usd"] / 12.0
        lic = live * (A["platform_licence_per_plant_usd_year"] + A["other_licences_per_plant_usd_year"]) / 12.0
        if m >= first_go_live:
            lic += A["platform_licence_enterprise_usd_year"] / 12.0
        other["licences"][m] = lic
        for sp in specs:
            if sp["adoption"] <= 0:
                continue
            dep = prov_l = ben_w = use_w = 0.0
            stock_w = [0.0] * len(sp["stock"])
            for c in cohorts:
                n, st = c["plants"] * sp["adoption"], c["go_live_month"] + sp["lag"]
                if m >= st - lead:
                    prov_l += n
                if m >= st:
                    age = m - st
                    dep += n
                    ben_w += n * eramp[min(age // 12, len(eramp) - 1)]
                    use_w += n * euramp[min(age // 12, len(euramp) - 1)]
                    for i, (_, _, ret) in enumerate(sp["stock"]):
                        stock_w[i] += n * min(1.0, (age + 1) / ret)
            fam_l = {f: sp["prov"][f] * prov_l + sp["usage"][f] * use_w for f, _ in AZURE_FAMILIES}
            for i, (f, monthly, _) in enumerate(sp["stock"]):
                fam_l[f] += monthly * stock_w[i]
            if sp["shared"] and dep > 0:
                scale = _shared_scale(A, max(1, prov_n))
                for ln in sp["shared"](dep, scale):
                    fam_l[ln["family"]] += ln["annual"] / 12.0
            for f, _ in AZURE_FAMILIES:
                if fam_l[f]:
                    x = fam_l[f] * (1.0 + _uplift(A, f, sp["dr"]))
                    azure[f][m] += x
                    lever_azure[sp["id"]][m] += x
            for cat, amount in sp["benefit_adj"].items():
                b = amount / 12.0 * ben_w
                benefit[cat][m] += b
                lever_benefit[sp["id"]][m] += b
            for cat, amount in sp["run"].items():
                x = amount * dep / 12.0
                other[cat][m] += x
                lever_cost[sp["id"]][m] += x
            if dep > 0:
                for cat, amount in sp["enterprise_run"].items():
                    other[cat][m] += amount / 12.0
                    lever_cost[sp["id"]][m] += amount / 12.0
    return {"months": months, "cohorts": cohorts, "benefit": benefit, "azure": azure, "other": other, "live_plants": live_plants,
            "active_plants": active_plants, "gross_pp": gross, "adj_pp": adj, "derived": derived, "hardware_per_plant": hw,
            "specs": specs, "lever_azure": lever_azure, "lever_benefit": lever_benefit, "lever_cost": lever_cost}


# --------------------------------------------------------------------------------------------- finance helpers
def _npv(flows: list[float], rate: float) -> float:
    return sum(f / (1.0 + rate) ** ((i + 1) / 12.0) for i, f in enumerate(flows))


def _irr(flows: list[float]) -> float | None:
    if not any(f > 0 for f in flows) or not any(f < 0 for f in flows):
        return None
    lo, hi = -0.95, 50.0
    f_lo, f_hi = _npv(flows, lo), _npv(flows, hi)
    if f_lo == 0:
        return lo
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _npv(flows, mid)
        if f_mid == 0:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def _payback_months(net: list[float]) -> float | None:
    """First month from which the cumulative net cash position stays >= 0 (fractional, linear within the month)."""
    cum, running = [], 0.0
    for v in net:
        running += v
        cum.append(running)
    idx = None
    for i in range(len(cum) - 1, -1, -1):
        if cum[i] < 0:
            idx = i + 1
            break
    if idx is None:
        return 0.0 if cum else None
    if idx >= len(cum):
        return None
    prev, cur = cum[idx - 1], cum[idx]
    return idx + (-prev) / (cur - prev) if cur != prev else float(idx + 1)


def _year_sums(series: list[float], years: int) -> list[float]:
    return [sum(series[12 * y: 12 * y + 12]) for y in range(years)]


def _sig(x: Any) -> Any:
    if isinstance(x, float):
        return float(f"{x:.10g}")
    if isinstance(x, dict):
        return {k: _sig(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_sig(v) for v in x]
    return x


def _metrics(sim: dict, A: dict, years: int) -> dict:
    months = years * 12
    ben_total = [sum(series[m] for series in sim["benefit"].values()) for m in range(sim["months"])]
    cost_total = [sum(series[m] for series in sim["azure"].values()) + sum(series[m] for series in sim["other"].values()) for m in range(sim["months"])]
    net = [b - c for b, c in zip(ben_total, cost_total)]
    window = net[:months]
    total_ben, total_cost = sum(ben_total[:months]), sum(cost_total[:months])
    irr = _irr(window)
    return {
        "npv": _npv(window, A["discount_rate"]),
        "roi_pct": ((total_ben - total_cost) / total_cost * 100.0) if total_cost else None,
        "irr_pct": irr * 100.0 if irr is not None else None,
        "payback_months": _payback_months(net),
        "net_total": sum(window),
        "benefits_total": total_ben,
        "costs_total": total_cost,
        "cumulative_end": sum(window),
        "ben_series": ben_total,
        "cost_series": cost_total,
    }


# --------------------------------------------------------------------------------------------- unit economics
def _unit_economics(A: dict, P: dict, run_rate: dict, adj: dict) -> dict:
    plants = A["plants_total"]
    s = A["assets_per_plant"] / A["reference_assets_per_plant"]
    per_plant = _plant_lines(A, P, s, edge_nodes=A["edge_nodes_per_plant"], er_circuits=A["er_circuits_per_plant"],
                             vpn_gateways=A["vpn_gateways_per_plant"], cosmos_regions=A["cosmos_regions"])
    uplifted = {f: 1.0 + _uplift(A, f, True) for f, _ in AZURE_FAMILIES}
    prov_pp = sum(x["annual"] * uplifted[x["family"]] for x in per_plant if x["kind"] == "provisioned")
    use_pp = sum(x["annual"] * uplifted[x["family"]] for x in per_plant if x["kind"] == "usage")
    stock_pp = sum(x["annual"] * uplifted[x["family"]] for x in per_plant if x["kind"] == "stock")
    azure_pp_all_in = run_rate["total"] / plants
    hw = _hardware_per_plant(A)
    one_time = (hw + A["integration_per_plant_next_usd"] + A["change_mgmt_per_plant_usd"]) * (1.0 + A["contingency_pct_one_time"])
    run_other = (A["platform_licence_per_plant_usd_year"] + A["other_licences_per_plant_usd_year"] + hw * A["hardware_support_pct_per_year"]
                 + A["agentops_fte_per_plant"] * A["agentops_fte_loaded_cost_usd"])
    benefit_pp = sum(adj.values())
    levers = [sp for sp in _lever_specs(A, P) if sp["adoption"] > 0]
    cont = A["contingency_pct_one_time"]
    lever_flow_parts = []
    for sp in levers:
        a = sp["adoption"]
        lever_benefit_pp = a * sum(sp["benefit_adj"].values())
        lever_run = a * sum(sp["run"].values())
        lever_one_time = a * sum(sp["one_time"].values()) * (1.0 + cont)
        prov_m = sum(sp["prov"][f] * uplifted[f] for f, _ in AZURE_FAMILIES) * a
        use_m = sum(sp["usage"][f] * uplifted[f] for f, _ in AZURE_FAMILIES) * a
        stock_m = sum(monthly * uplifted[f] for f, monthly, _ in sp["stock"]) * a
        benefit_pp += lever_benefit_pp
        run_other += lever_run
        one_time += lever_one_time
        lever_flow_parts.append((sp["lag"], lever_benefit_pp, lever_run, lever_one_time, prov_m, use_m, stock_m))
    cum = -(one_time - sum(p[3] for p in lever_flow_parts))
    payback = None
    for m in range(60):
        k = min(m // 12, len(A["benefit_ramp"]) - 1)
        ku = min(m // 12, len(A["usage_ramp"]) - 1)
        core_benefit = sum(adj.values())
        flow = core_benefit / 12.0 * A["benefit_ramp"][k] - (prov_pp + use_pp * A["usage_ramp"][ku] + stock_pp) / 12.0 - (run_other - sum(p[2] for p in lever_flow_parts)) / 12.0
        for lag, b_pp, run_l, ot_l, prov_m, use_m, stock_m in lever_flow_parts:
            if m == lag:
                flow -= ot_l
            if m >= lag:
                age = m - lag
                ke = min(age // 12, len(A["exp_benefit_ramp"]) - 1)
                kue = min(age // 12, len(A["exp_usage_ramp"]) - 1)
                flow += b_pp / 12.0 * A["exp_benefit_ramp"][ke] - (prov_m + use_m * A["exp_usage_ramp"][kue] + stock_m) - run_l / 12.0
        new = cum + flow
        if payback is None and new >= 0:
            payback = m + (-cum / flow if flow else 1.0)
        cum = new
    return {
        "benefit_per_plant_year_risk_adjusted": benefit_pp,
        "azure_per_plant_year_incl_shared_share": azure_pp_all_in,
        "other_run_cost_per_plant_year": run_other,
        "net_per_plant_year": benefit_pp - azure_pp_all_in - run_other,
        "one_time_per_additional_plant": one_time,
        "benefit_to_run_cost_ratio": benefit_pp / (azure_pp_all_in + run_other),
        "payback_months_after_go_live_single_plant": payback,
        "memo_working_capital_release_per_plant": 0.0,
    }


# --------------------------------------------------------------------------------------------- compute
def _tier_defs(A: dict) -> list[dict]:
    n = A["plants_total"]
    ref = A["reference_assets_per_plant"]
    return [
        {"id": "pilot", "label": "Pilot (1 plant, single line)", "plants": 1, "s": A["pilot_assets"] / ref,
         "tier": {"edge_nodes": 1, "er_circuits": 0, "er_gateways": 0, "front_door": 0, "ai_search_base_units": 1, "cosmos_regions": 1, "dr": False,
                  "shared_scale": A["pilot_shared_scale"], "levers": False}},
        {"id": "plant_1", "label": "1 plant (full scope)", "plants": 1, "s": A["assets_per_plant"] / ref, "tier": {}},
        {"id": "customer", "label": f"{n} plants (reference customer)", "plants": n, "s": A["assets_per_plant"] / ref, "tier": {}},
        {"id": "enterprise_25", "label": "25-plant enterprise", "plants": 25, "s": A["assets_per_plant"] / ref, "tier": {}},
    ]


def _levers_summary(A: dict, P: dict, sim: dict, run: dict, years: int) -> list[dict]:
    """Economics of each expansion lever: per deploying plant, enterprise-fixed items, and the simulated yearly flows of this scenario."""
    plants = A["plants_total"]
    cont = A["contingency_pct_one_time"]
    out = []
    for sp in sim["specs"]:
        lid = sp["id"]
        up = {f: 1.0 + _uplift(A, f, sp["dr"]) for f, _ in AZURE_FAMILIES}
        by_family = {f: 0.0 for f, _ in AZURE_FAMILIES}
        for ln in sp["lines"]:
            by_family[ln["family"]] += ln["annual"] * up[ln["family"]]
        azure_pp = sum(by_family.values())
        run_pp = sum(sp["run"].values())
        benefit_pp = sum(sp["benefit_adj"].values())
        one_time_pp = sum(sp["one_time"].values()) * (1.0 + cont)
        net_pp = benefit_pp - azure_pp - run_pp
        shared_ref = sum(ln["annual"] * up[ln["family"]] for ln in sp["shared"](float(plants), _shared_scale(A, plants))) if sp["shared"] else 0.0
        dep = plants * sp["adoption"]
        flows = [sim["lever_benefit"][lid][m] - sim["lever_azure"][lid][m] - sim["lever_cost"][lid][m] for m in range(years * 12)]
        ben_y = _year_sums(sim["lever_benefit"][lid], years)
        az_y = _year_sums(sim["lever_azure"][lid], years)
        cost_y = _year_sums(sim["lever_cost"][lid], years)
        rr = run["by_lever"][lid]
        out.append({
            "id": lid, "label": sp["label"], "note": LEVER_NOTES[lid], "adoption": sp["adoption"], "start_lag_months": sp["lag"],
            "deploying_plants_at_full_rollout": dep,
            "per_deploying_plant": {"azure_run_cost": azure_pp, "other_run_cost": run_pp, "benefit": benefit_pp, "net": net_pp, "one_time_cost": one_time_pp,
                                    "payback_months": (one_time_pp / (net_pp / 12.0)) if net_pp > 0 else None,
                                    "benefit_to_run_cost_ratio": (benefit_pp / (azure_pp + run_pp)) if (azure_pp + run_pp) else None,
                                    "benefit_by_category": dict(sp["benefit_adj"]), "azure_by_family": by_family},
            "enterprise_fixed": {"azure_run_cost_at_reference_scale": shared_ref, "other_run_cost": sum(sp["enterprise_run"].values()),
                                 "one_time_cost": sum(sp["enterprise_one_time"].values()) * (1.0 + cont)},
            "by_year": {"benefit": ben_y, "azure": az_y, "other_cost": cost_y, "net": [b - a_ - c for b, a_, c in zip(ben_y, az_y, cost_y)]},
            "npv": _npv(flows, A["discount_rate"]),
            "run_rate": {"azure": rr, "azure_per_deploying_plant": (rr / dep) if dep > 0 else None},
        })
    return out


def _expansion(assumptions: dict, A: dict, P: dict, scenario: str, horizon: int) -> dict:
    """The expansion case: the five levers at their Upside adoption on top of this scenario, per-tier run-rates with and without the levers, the fleet tier and the path."""
    specs = assumptions["assumptions"]
    Ax, A0 = copy.deepcopy(A), copy.deepcopy(A)
    adoption = {}
    for lid, prefix, _ in EXPANSION_LEVERS:
        key = prefix + "_adoption"
        adoption[lid] = float(specs[key].get("scenario", {}).get("upside", specs[key]["high"]))
        Ax[key] = adoption[lid]
        A0[key] = 0.0
    full = _core(Ax, P, scenario, horizon)
    ref = A["reference_assets_per_plant"]
    defs = _tier_defs(A)
    fleet_plants = int(round(A["exp_fleet_plants"]))
    defs.append({"id": "fleet", "label": f"{fleet_plants}-plant enterprise fleet", "plants": fleet_plants, "s": A["assets_per_plant"] / ref, "tier": {}})
    tiers = []
    for t in defs:
        without = _steady_state(A0, P, t["plants"], t["s"], tier=t["tier"])
        with_l = _steady_state(Ax, P, t["plants"], t["s"], tier=t["tier"])
        assets = t["plants"] * t["s"] * ref
        tiers.append({
            "id": t["id"], "label": t["label"], "plants": t["plants"], "assets_per_plant": t["s"] * ref,
            "without_levers": {"total": without["total"], "per_plant": without["total"] / t["plants"], "per_asset_year": without["total"] / assets},
            "with_levers": {"total": with_l["total"], "per_plant": with_l["total"] / t["plants"], "per_asset_year": with_l["total"] / assets,
                            "by_lever": with_l["by_lever"], "by_family": with_l["by_family"]},
            "uplift_multiple": (with_l["total"] / without["total"]) if without["total"] else None,
        })
    by_id = {t["id"]: t for t in tiers}
    cust = by_id["customer"]
    path = [{"id": "core", "label": f"Core platform, {A['plants_total']} plants", "value": cust["without_levers"]["total"], "kind": "total"}]
    for lid in LEVER_IDS:
        path.append({"id": lid, "label": LEVER_LABELS[lid], "value": cust["with_levers"]["by_lever"][lid], "kind": "delta"})
    path.append({"id": "expansion", "label": f"With expansion levers, {A['plants_total']} plants", "value": cust["with_levers"]["total"], "kind": "total"})
    for tid in ("enterprise_25", "fleet"):
        path.append({"id": tid, "label": by_id[tid]["label"] + ", levers on", "value": by_id[tid]["with_levers"]["total"], "kind": "total"})
    r = full
    headline = {
        "total_benefit": r["benefits"]["total"], "total_cost": r["costs"]["total"], "net_benefit": r["roi"]["net_total"], "npv": r["roi"]["npv"], "roi_pct": r["roi"]["roi_pct"],
        "payback_months": r["roi"]["payback_months"], "irr_pct": r["roi"]["irr_pct"], "npv_5yr": r.get("memo", {}).get("five_year", {}).get("npv"),
        "steady_state_benefit_per_year": r["benefits"]["steady_state_at_all_plants_risk_adjusted"],
        "acr_by_year": r["acr"]["by_year"], "acr_year3": r["acr"]["by_year"][min(2, horizon - 1)], "acr_run_rate": r["acr"]["run_rate_year3"],
        "acr_per_plant_year": r["acr"]["per_plant_year"], "acr_per_asset_year": r["acr"]["per_asset_year"], "pull_through_ratio": r["acr"]["pull_through_ratio"],
    }
    return {
        "case": "Expansion case: the five expansion levers at their Upside adoption on top of this scenario's other assumptions (levers are OFF in Base and Conservative).",
        "adoption": adoption,
        "headline": headline,
        "levers": r["levers"],
        "benefits": {"by_category": r["benefits"]["by_category"], "category_labels": r["benefits"]["category_labels"], "total_by_year": r["benefits"]["total_by_year"],
                     "total": r["benefits"]["total"]},
        "costs": {"azure_by_family": r["costs"]["azure_by_family"], "other_by_category": r["costs"]["other_by_category"], "total_by_year": r["costs"]["total_by_year"], "total": r["costs"]["total"]},
        "roi": r["roi"],
        "acr": {"by_year": r["acr"]["by_year"], "by_family": r["acr"]["by_family"], "by_lever": r["acr"]["by_lever"], "run_rate": r["acr"]["run_rate_year3"],
                "run_rate_by_lever": r["acr"]["run_rate_by_lever"], "run_rate_by_family": r["acr"]["run_rate_by_family"], "per_plant_year": r["acr"]["per_plant_year"],
                "per_asset_year": r["acr"]["per_asset_year"], "attach": r["acr"]["attach"], "pull_through_ratio": r["acr"]["pull_through_ratio"],
                "opportunity": r["acr"]["opportunity"], "line_items": r["acr"]["line_items"]},
        "tiers": tiers,
        "path": path,
    }


def _core(A: dict, P: dict, scenario: str, horizon: int) -> dict:
    months_sim = max(SIM_MIN_YEARS, horizon) * 12
    sim = _simulate(A, P, months_sim)
    m = _metrics(sim, A, horizon)
    years = horizon
    ben_by_cat = {c: _year_sums(series, years) for c, series in sim["benefit"].items()}
    azure_by_fam = {f: _year_sums(sim["azure"][f], years) for f, _ in AZURE_FAMILIES}
    other_by_cat = {c: _year_sums(sim["other"][c], years) for c, _ in OTHER_COST_CATEGORIES}
    ben_total_year = _year_sums(m["ben_series"], years)
    cost_total_year = _year_sums(m["cost_series"], years)
    azure_total_year = [sum(azure_by_fam[f][y] for f, _ in AZURE_FAMILIES) for y in range(years)]
    net_year = [b - c for b, c in zip(ben_total_year, cost_total_year)]
    cumulative, running = [], 0.0
    for v in net_year:
        running += v
        cumulative.append(running)
    s = A["assets_per_plant"] / A["reference_assets_per_plant"]
    run = _steady_state(A, P, A["plants_total"], s)
    attach, ratio = _attach(run["by_family"])
    tiers = []
    for t in _tier_defs(A):
        ss = _steady_state(A, P, t["plants"], t["s"], tier=t["tier"])
        cat, r = _attach(ss["by_family"])
        tiers.append({"id": t["id"], "label": t["label"], "plants": t["plants"], "assets_per_plant": t["s"] * A["reference_assets_per_plant"], "total": ss["total"],
                      "per_plant": ss["total"] / t["plants"], "by_family": ss["by_family"], "pull_through_ratio": r, "shared_scale": ss["shared_scale"]})
    gross_pp, adj_pp, derived = dict(sim["gross_pp"]), dict(sim["adj_pp"]), sim["derived"]
    core_adj_pp = sim["adj_pp"]
    ben_labels = dict(BENEFIT_CATEGORIES)
    ben_conf = {c: A[CONF_KEYS[c]] for c, _ in BENEFIT_CATEGORIES}
    for sp in sim["specs"]:
        if sp["adoption"] <= 0:
            continue
        for cat, amount in sp["benefit_gross"].items():
            gross_pp[cat] = gross_pp.get(cat, 0.0) + sp["adoption"] * amount
        for cat, amount in sp["benefit_adj"].items():
            adj_pp[cat] = adj_pp.get(cat, 0.0) + sp["adoption"] * amount
            if cat not in ben_conf:
                ben_conf[cat] = sp["confidence"][cat]
    ben_labels.update({c: label for c, label in EXPANSION_BENEFIT_CATEGORIES if c in ben_by_cat})
    lever_year = {lid: _year_sums(sim["lever_azure"][lid], years) for lid in LEVER_IDS}
    by_lever_year = {"core": [azure_total_year[y] - sum(lever_year[lid][y] for lid in LEVER_IDS) for y in range(years)]}
    by_lever_year.update(lever_year)
    levers_out = _levers_summary(A, P, sim, run, years)
    cohorts = sim["cohorts"]
    live_end = []
    cum_live = 0
    for y in range(years):
        cum_live += sum(c["plants"] for c in cohorts if c["year"] == y + 1)
        live_end.append(cum_live)
    ue = _unit_economics(A, P, run, core_adj_pp)
    ue["memo_working_capital_release_per_plant"] = derived["working_capital_release_per_plant_usd"]
    plants_addressable_eu = (A["tam_eu_manufacturing_persons"] * A["tam_eu_large_enterprise_employment_share"] / A["tam_employees_per_large_plant"]) * A["tam_automation_ready_share"]
    plants_addressable_global = plants_addressable_eu * A["tam_global_to_eu_multiplier"]
    per_plant_acr = run["total"] / A["plants_total"]
    opportunity = {
        "addressable_plants_eu": plants_addressable_eu,
        "addressable_plants_global": plants_addressable_global,
        "acr_per_plant_year": per_plant_acr,
        "potential_acr_at_full_penetration": plants_addressable_global * per_plant_acr,
        "penetration_year5": A["tam_penetration_year5"],
        "acr_at_penetration_year5": plants_addressable_global * per_plant_acr * A["tam_penetration_year5"],
        "plants_at_penetration_year5": plants_addressable_global * A["tam_penetration_year5"],
        "customers_equivalent_at_penetration": plants_addressable_global * A["tam_penetration_year5"] / A["plants_total"],
        "note": "Illustrative, assumption-driven sizing (employment from Eurostat 2022; plant count, readiness share, global multiplier and penetration are assumptions). Not a forecast or a commitment.",
    }
    result = {
        "scenario": scenario,
        "model_version": MODEL_VERSION,
        "currency": "USD",
        "horizon_years": horizon,
        "plants": {"cohorts": [{"year": c["year"], "plants": c["plants"], "go_live_month": c["go_live_month"] + 1} for c in cohorts],
                   "live_by_year_end": live_end,
                   "average_live_plants_by_year": [sum(sim["live_plants"][12 * y: 12 * y + 12]) / 12.0 for y in range(years)]},
        "benefits": {
            "by_category": ben_by_cat,
            "category_labels": ben_labels,
            "total_by_year": ben_total_year,
            "total": sum(ben_total_year),
            "confidence": ben_conf,
            "steady_state_per_plant_gross": gross_pp,
            "steady_state_per_plant_risk_adjusted": adj_pp,
            "steady_state_at_all_plants_risk_adjusted": sum(adj_pp.values()) * A["plants_total"],
            "memo": {"working_capital_release_total_usd": derived["working_capital_release_per_plant_usd"] * A["plants_total"],
                     "note": "One-time cash release from lower inventory; NOT included in benefits, NPV or ROI."},
        },
        "costs": {
            "azure_by_family": azure_by_fam,
            "family_labels": dict(AZURE_FAMILIES),
            "azure_total_by_year": azure_total_year,
            "other_by_category": other_by_cat,
            "category_labels": dict(OTHER_COST_CATEGORIES),
            "total_by_year": cost_total_year,
            "total": sum(cost_total_year),
        },
        "roi": {
            "net_benefit_by_year": net_year,
            "cumulative": cumulative,
            "npv": m["npv"],
            "discount_rate": A["discount_rate"],
            "roi_pct": m["roi_pct"],
            "payback_months": m["payback_months"],
            "irr_pct": m["irr_pct"],
            "net_total": m["net_total"],
        },
        "acr": {
            "by_year": azure_total_year,
            "by_family": azure_by_fam,
            "run_rate_year3": run["total"],
            "run_rate_by_family": run["by_family"],
            "per_plant_year": per_plant_acr,
            "per_asset_year": run["total"] / (A["plants_total"] * A["assets_per_plant"]),
            "tiers": tiers,
            "pull_through_ratio": ratio,
            "attach": attach,
            "line_items": run["lines"],
            "opportunity": opportunity,
            "by_lever": by_lever_year,
            "run_rate_by_lever": run["by_lever"],
            "lever_adoption": {sp["id"]: sp["adoption"] for sp in sim["specs"]},
            "pricing_basis": "Azure Retail Prices API list price, USD, pay-as-you-go, no EA discount (x azure_price_multiplier)",
        },
        "unit_economics": ue,
        "derived": derived,
        "levers": levers_out,
    }
    if horizon < SIM_MIN_YEARS:
        five = _metrics(sim, A, SIM_MIN_YEARS)
        result["memo"] = {"five_year": {"npv": five["npv"], "roi_pct": five["roi_pct"], "irr_pct": five["irr_pct"], "net_total": five["net_total"],
                                        "benefits_total": five["benefits_total"], "costs_total": five["costs_total"]}}
    return result


def _sensitivity(assumptions: dict, scenario: str, overrides: dict, horizon: int, base_npv: float, base_acr: float) -> tuple[list, list]:
    specs = assumptions["assumptions"]
    npv_rows, acr_rows = [], []
    base_A, _ = resolve(assumptions, scenario, overrides)
    active = {p: float(base_A[p + "_adoption"]) > 0 for _, p, _ in EXPANSION_LEVERS}
    for key, spec in specs.items():
        if spec["group"] == "opportunity" or key in overrides or spec["base"] is None:
            continue
        if spec["group"].startswith("expansion"):
            if key == "exp_fleet_plants":
                continue
            prefix = next((p for _, p, _ in EXPANSION_LEVERS if key.startswith(p + "_")), None)
            if not (any(active.values()) if prefix is None else active[prefix]):
                continue
        lo, hi = spec["low"], spec["high"]
        cur = base_A[key]
        if lo == hi == cur:
            continue
        vals = {}
        for tag, v in (("low", lo), ("high", hi)):
            ov = dict(overrides)
            ov[key] = v
            A, P = resolve(assumptions, scenario, ov)
            sim = _simulate(A, P, max(SIM_MIN_YEARS, horizon) * 12)
            met = _metrics(sim, A, horizon)
            s = A["assets_per_plant"] / A["reference_assets_per_plant"]
            azure_y3 = sum(sim["azure"][f][m] for f, _ in AZURE_FAMILIES for m in range(24, 36)) if horizon >= 3 else 0.0
            vals[tag] = (met["npv"], azure_y3)
        row = {"id": key, "label": spec["label"], "group": spec["group"], "base_value": cur, "low_value": lo, "high_value": hi}
        npv_rows.append({**row, "npv_low": vals["low"][0], "npv_high": vals["high"][0], "swing": abs(vals["high"][0] - vals["low"][0])})
        acr_rows.append({**row, "acr_year3_low": vals["low"][1], "acr_year3_high": vals["high"][1], "swing": abs(vals["high"][1] - vals["low"][1])})
    npv_rows.sort(key=lambda r: (-r["swing"], r["id"]))
    acr_rows.sort(key=lambda r: (-r["swing"], r["id"]))
    return npv_rows[:15], [r for r in acr_rows if r["swing"] > 0][:12]


def compute(assumptions: dict, scenario: str = "base", overrides: dict | None = None, *, with_sensitivity: bool = True) -> dict:
    overrides = dict(overrides or {})
    A, P = resolve(assumptions, scenario, overrides)
    horizon = int(assumptions["meta"]["horizon_years"])
    result = _core(A, P, scenario, horizon)
    result["expansion"] = _expansion(assumptions, A, P, scenario, horizon)
    result["assumptions_version"] = assumptions["meta"]["assumptions_version"]
    result["price_retrieved_on"] = assumptions["meta"]["price_basis"]["retrieved_on"]
    result["inputs"] = {"resolved": {k: v for k, v in A.items()}, "overrides": overrides}
    if with_sensitivity:
        npv_rows, acr_rows = _sensitivity(assumptions, scenario, overrides, horizon, result["roi"]["npv"], result["acr"]["by_year"][min(2, horizon - 1)])
        result["sensitivity"] = npv_rows
        result["acr_sensitivity"] = acr_rows
    else:
        result["sensitivity"] = []
        result["acr_sensitivity"] = []
    return _sig(result)


def compute_all(assumptions: dict, overrides: dict | None = None, *, with_sensitivity: bool = True) -> dict:
    scenarios = {s: compute(assumptions, s, overrides, with_sensitivity=with_sensitivity) for s in SCENARIOS}
    headline = {}
    for name, r in scenarios.items():
        headline[name] = {
            "total_benefit": r["benefits"]["total"], "total_cost": r["costs"]["total"], "net_benefit": r["roi"]["net_total"], "npv": r["roi"]["npv"],
            "roi_pct": r["roi"]["roi_pct"], "payback_months": r["roi"]["payback_months"], "irr_pct": r["roi"]["irr_pct"],
            "npv_5yr": r.get("memo", {}).get("five_year", {}).get("npv"),
            "steady_state_benefit_per_year": r["benefits"]["steady_state_at_all_plants_risk_adjusted"],
            "acr_by_year": r["acr"]["by_year"], "acr_year3": r["acr"]["by_year"][min(2, len(r["acr"]["by_year"]) - 1)],
            "acr_run_rate": r["acr"]["run_rate_year3"], "acr_per_plant_year": r["acr"]["per_plant_year"], "pull_through_ratio": r["acr"]["pull_through_ratio"],
            "expansion_total_benefit": r["expansion"]["headline"]["total_benefit"], "expansion_total_cost": r["expansion"]["headline"]["total_cost"],
            "expansion_npv": r["expansion"]["headline"]["npv"], "expansion_payback_months": r["expansion"]["headline"]["payback_months"],
            "expansion_acr_by_year": r["expansion"]["headline"]["acr_by_year"], "expansion_acr_year3": r["expansion"]["headline"]["acr_year3"],
            "expansion_acr_run_rate": r["expansion"]["headline"]["acr_run_rate"],
            "fleet_plants": next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")["plants"],
            "fleet_acr_run_rate_core": next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")["without_levers"]["total"],
            "fleet_acr_run_rate_expansion": next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")["with_levers"]["total"],
        }
    return {
        "model_version": MODEL_VERSION,
        "assumptions_version": assumptions["meta"]["assumptions_version"],
        "currency": "USD",
        "price_retrieved_on": assumptions["meta"]["price_basis"]["retrieved_on"],
        "reference_customer": assumptions["meta"]["reference_customer"],
        "headline": headline,
        "scenarios": scenarios,
    }


# --------------------------------------------------------------------------------------------- reporting
def _m(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"${x / 1e6:,.{nd}f}M"


def _k(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.0f}"


def render_markdown(out: dict) -> str:
    base, cons, up = (out["scenarios"][k] for k in ("base", "conservative", "upside"))
    L: list[str] = []
    w = L.append
    w("# Nightshift business case — model outputs")
    w("")
    w(f"Generated by `model.py` v{out['model_version']} from `assumptions.json` v{out['assumptions_version']} · Azure list prices retrieved {out['price_retrieved_on']} · currency USD · "
      f"reference customer: {out['reference_customer']}.")
    w("")
    w("> Illustrative. Every benefit input is an assumption or a cited benchmark that must be validated with the customer's own data (CMMS downtime log, scrap ledger, energy bills, "
      "balance sheet). Run-time economics are not a commitment by Microsoft or any partner.")
    w("")
    w("## 1. Headline (3-year horizon)")
    w("")
    w("| Metric | Conservative | **Base** | Upside |")
    w("|---|---:|---:|---:|")
    def row(label, f):
        w(f"| {label} | {f(cons)} | **{f(base)}** | {f(up)} |")
    row("Total benefit (risk-adjusted)", lambda r: _m(r["benefits"]["total"]))
    row("Total cost (Azure + other)", lambda r: _m(r["costs"]["total"]))
    row("Net benefit", lambda r: _m(r["roi"]["net_total"]))
    row("NPV @ discount rate", lambda r: _m(r["roi"]["npv"]))
    row("ROI (net ÷ cost)", lambda r: "n/a" if r["roi"]["roi_pct"] is None else f"{r['roi']['roi_pct']:.0f}%")
    row("Payback (months from programme start)", lambda r: "> 60" if r["roi"]["payback_months"] is None else f"{r['roi']['payback_months']:.1f}")
    row("IRR", lambda r: "n/a" if r["roi"]["irr_pct"] is None else f"{r['roi']['irr_pct']:.0f}%")
    row("5-year NPV (memo)", lambda r: _m(r["memo"]["five_year"]["npv"]))
    row("Steady-state benefit, all plants (risk-adjusted, per year)", lambda r: _m(r["benefits"]["steady_state_at_all_plants_risk_adjusted"]))
    row("Azure consumption (ACR), Year 3", lambda r: _m(r["acr"]["by_year"][2], 2))
    row("Azure run-rate at full roll-out (ACR per year)", lambda r: _m(r["acr"]["run_rate_year3"], 2))
    row("Pull-through (other Azure $ per $1 of AI services)", lambda r: "n/a" if r["acr"]["pull_through_ratio"] is None else f"{r['acr']['pull_through_ratio']:.1f}x")
    row("Expansion case: Year-3 ACR (levers at Upside adoption)", lambda r: _m(r["expansion"]["headline"]["acr_year3"], 2))
    row("Expansion case: ACR run-rate at full roll-out", lambda r: _m(r["expansion"]["headline"]["acr_run_rate"], 2))
    row("Enterprise-fleet ACR run-rate, core only", lambda r: _m(next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")["without_levers"]["total"], 1))
    row("Enterprise-fleet ACR run-rate, expansion levers on", lambda r: _m(next(t for t in r["expansion"]["tiers"] if t["id"] == "fleet")["with_levers"]["total"], 1))
    w("")
    w(f"Discount rate {base['roi']['discount_rate']:.0%} (Base). Plants live at year-end: {', '.join(str(x) for x in base['plants']['live_by_year_end'])} (Base). "
      "Payback and IRR use monthly cash flows (one-time costs when incurred, benefits from each cohort's go-live month).")
    w("")
    w("## 2. Base case — benefits by category (risk-adjusted, USD M)")
    w("")
    w("| Category | Confidence | Year 1 | Year 2 | Year 3 | 3-yr total | Steady state per plant / yr |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for c, label in BENEFIT_CATEGORIES:
        v = base["benefits"]["by_category"][c]
        w(f"| {label} | {base['benefits']['confidence'][c]:.2f} | {v[0] / 1e6:.2f} | {v[1] / 1e6:.2f} | {v[2] / 1e6:.2f} | {sum(v) / 1e6:.2f} | {base['benefits']['steady_state_per_plant_risk_adjusted'][c] / 1e6:.2f} |")
    t = base["benefits"]["total_by_year"]
    w(f"| **Total** | | **{t[0] / 1e6:.2f}** | **{t[1] / 1e6:.2f}** | **{t[2] / 1e6:.2f}** | **{sum(t) / 1e6:.2f}** | **{sum(base['benefits']['steady_state_per_plant_risk_adjusted'].values()) / 1e6:.2f}** |")
    w("")
    w(f"Memo (not in NPV): one-time working-capital release at full roll-out ≈ {_m(base['benefits']['memo']['working_capital_release_total_usd'])}.")
    w("")
    w("## 3. Base case — costs (USD M)")
    w("")
    w("| Cost | Year 1 | Year 2 | Year 3 | 3-yr total |")
    w("|---|---:|---:|---:|---:|")
    for c, label in OTHER_COST_CATEGORIES:
        v = base["costs"]["other_by_category"][c]
        w(f"| {label} | {v[0] / 1e6:.2f} | {v[1] / 1e6:.2f} | {v[2] / 1e6:.2f} | {sum(v) / 1e6:.2f} |")
    v = base["costs"]["azure_total_by_year"]
    w(f"| Azure consumption (list price) | {v[0] / 1e6:.2f} | {v[1] / 1e6:.2f} | {v[2] / 1e6:.2f} | {sum(v) / 1e6:.2f} |")
    v = base["costs"]["total_by_year"]
    w(f"| **Total cost** | **{v[0] / 1e6:.2f}** | **{v[1] / 1e6:.2f}** | **{v[2] / 1e6:.2f}** | **{sum(v) / 1e6:.2f}** |")
    n = base["roi"]["net_benefit_by_year"]
    w(f"| **Net benefit** | **{n[0] / 1e6:.2f}** | **{n[1] / 1e6:.2f}** | **{n[2] / 1e6:.2f}** | **{sum(n) / 1e6:.2f}** |")
    cu = base["roi"]["cumulative"]
    w(f"| Cumulative net benefit | {cu[0] / 1e6:.2f} | {cu[1] / 1e6:.2f} | {cu[2] / 1e6:.2f} | |")
    w("")
    w("## 4. Azure Consumed Revenue (ACR) — Base")
    w("")
    w("| Service family | Year 1 | Year 2 | Year 3 | Run-rate at full roll-out |")
    w("|---|---:|---:|---:|---:|")
    for f, label in AZURE_FAMILIES:
        v = base["acr"]["by_family"][f]
        w(f"| {label} | {_k(v[0])} | {_k(v[1])} | {_k(v[2])} | {_k(base['acr']['run_rate_by_family'][f])} |")
    v = base["acr"]["by_year"]
    w(f"| **Total** | **{_k(v[0])}** | **{_k(v[1])}** | **{_k(v[2])}** | **{_k(base['acr']['run_rate_year3'])}** |")
    w("")
    w(f"Per plant-year (run-rate) {_k(base['acr']['per_plant_year'])} · per monitored asset-year {_k(base['acr']['per_asset_year'])} · pull-through "
      f"{base['acr']['pull_through_ratio']:.1f} dollars of data/edge/compute/security/monitoring/networking consumption per dollar of AI services (Foundry + Azure ML + AI Search).")
    w("")
    w("### ACR by plant tier (steady-state run-rate, Base)")
    w("")
    w("| Tier | Plants | Assets / plant | Annual ACR | ACR per plant | Pull-through |")
    w("|---|---:|---:|---:|---:|---:|")
    for tier in base["acr"]["tiers"]:
        w(f"| {tier['label']} | {tier['plants']} | {tier['assets_per_plant']:.0f} | {_k(tier['total'])} | {_k(tier['per_plant'])} | {tier['pull_through_ratio']:.1f}x |")
    w("")
    w("### Attach mix at run-rate (Base)")
    w("")
    w("| Category | Annual | Share |")
    w("|---|---:|---:|")
    for name, a in base["acr"]["attach"].items():
        w(f"| {name.replace('_', ' ')} | {_k(a['annual'])} | {a['share']:.0%} |")
    w("")
    opp = base["acr"]["opportunity"]
    w("### Illustrative opportunity sizing (assumption-driven)")
    w("")
    w(f"Addressable plants: EU ≈ {opp['addressable_plants_eu']:,.0f}, global ≈ {opp['addressable_plants_global']:,.0f} (see assumptions `tam_*`); at {_k(opp['acr_per_plant_year'])} ACR per plant-year the full-penetration "
      f"pool is {_m(opp['potential_acr_at_full_penetration'], 0)} a year; at {opp['penetration_year5']:.0%} penetration ({opp['plants_at_penetration_year5']:,.0f} plants ≈ {opp['customers_equivalent_at_penetration']:,.0f} customers like Contoso) "
      f"it is {_m(opp['acr_at_penetration_year5'], 0)} a year. {opp['note']}")
    w("")
    w("## 5. ACR audit — every line at run-rate (Base)")
    w("")
    w(f"Run-rate = {base['inputs']['resolved']['plants_total']} plants × {base['inputs']['resolved']['assets_per_plant']:.0f} assets, mature usage, full year, list prices. Quantities are annual and already multiplied by the number of plants where the meter is per plant.")
    w("")
    w("| Family | Line item | Annual quantity | Unit | Unit price (USD) | Annual cost |")
    w("|---|---|---:|---|---:|---:|")
    for f, label in AZURE_FAMILIES:
        for ln in base["acr"]["line_items"]:
            if ln["family"] == f:
                w(f"| {f} | {ln['item']} | {ln['quantity']:,.2f} | {ln['unit']} | {ln['unit_price']:g} | {_k(ln['annual'])} |")
    w("")
    w("## 6. Sensitivity (Base) — NPV tornado")
    w("")
    w("| Assumption | Low | High | NPV at low | NPV at high | Swing |")
    w("|---|---:|---:|---:|---:|---:|")
    for r in base["sensitivity"][:12]:
        w(f"| {r['label']} | {r['low_value']} | {r['high_value']} | {_m(r['npv_low'])} | {_m(r['npv_high'])} | {_m(r['swing'])} |")
    w("")
    w("## 7. Unit economics per plant (Base, steady state)")
    w("")
    ue = base["unit_economics"]
    w(f"* Risk-adjusted benefit per plant-year: **{_m(ue['benefit_per_plant_year_risk_adjusted'], 2)}**")
    w(f"* Azure per plant-year (incl. share of shared platform, dev/test and DR): **{_k(ue['azure_per_plant_year_incl_shared_share'])}**")
    w(f"* Other run cost per plant-year (licences, AgentOps, hardware support): **{_k(ue['other_run_cost_per_plant_year'])}**")
    w(f"* Net per plant-year: **{_m(ue['net_per_plant_year'], 2)}** · benefit ÷ run cost: **{ue['benefit_to_run_cost_ratio']:.1f}x**")
    w(f"* One-time cost per additional plant (hardware, integration, change, contingency): **{_k(ue['one_time_per_additional_plant'])}**")
    pb = ue["payback_months_after_go_live_single_plant"]
    w(f"* Payback of an additional plant after its go-live: **{'n/a' if pb is None else f'{pb:.1f} months'}**")
    w("")
    ex = base["expansion"]
    ehl = ex["headline"]
    w("## 8. Expansion levers E1–E5 (optional; OFF in Base and Conservative, ON in Upside)")
    w("")
    w("Each lever has its own Azure consumption (priced from the Retail Prices API), its own customer-side costs and its own risk-adjusted benefit. They are switched with the "
      "overrides `exp_vision_adoption`, `exp_hf_adoption`, `exp_sim_adoption`, `exp_dp_adoption`, `exp_sec_adoption` (share of live plants, 0 to 1). "
      "The **expansion case** below applies the Upside adoption of all five levers on top of the Base inputs "
      f"({', '.join(f'{k} {v:.0%}' for k, v in ex['adoption'].items())}).")
    w("")
    w("### 8.1 Economics per deploying plant (steady state, risk-adjusted, USD thousand per year unless stated)")
    w("")
    w("| Lever | Azure run cost | Other run cost | Benefit | Net | One-time cost | Simple payback | Enterprise-fixed items (at 8 plants) |")
    w("|---|---:|---:|---:|---:|---:|---:|---|")
    for lv in ex["levers"]:
        p, ef = lv["per_deploying_plant"], lv["enterprise_fixed"]
        pb2 = "none" if p["payback_months"] is None else f"{p['payback_months']:.0f} months"
        fixed = f"Azure {_k(ef['azure_run_cost_at_reference_scale'])}, other run {_k(ef['other_run_cost'])}, one-time {_k(ef['one_time_cost'])}" if (ef["azure_run_cost_at_reference_scale"] or ef["other_run_cost"] or ef["one_time_cost"]) else "—"
        w(f"| {lv['id']} {lv['label']} | {p['azure_run_cost'] / 1e3:,.0f} | {p['other_run_cost'] / 1e3:,.0f} | {p['benefit'] / 1e3:,.0f} | {p['net'] / 1e3:,.0f} | {p['one_time_cost'] / 1e3:,.0f} | {pb2} | {fixed} |")
    w("")
    for lv in ex["levers"]:
        w(f"* **{lv['id']} {lv['label']}** — {lv['note']}")
    w("")
    w("### 8.2 Expansion case versus Base (8 plants)")
    w("")
    w("| Metric | Base | Base + expansion levers |")
    w("|---|---:|---:|")
    w(f"| 3-year benefit | {_m(base['benefits']['total'])} | {_m(ehl['total_benefit'])} |")
    w(f"| 3-year cost | {_m(base['costs']['total'])} | {_m(ehl['total_cost'])} |")
    w(f"| NPV (3 years) | {_m(base['roi']['npv'])} | {_m(ehl['npv'])} |")
    w(f"| NPV (5 years, memo) | {_m(base['memo']['five_year']['npv'])} | {_m(ehl['npv_5yr'])} |")
    w(f"| Payback (months) | {base['roi']['payback_months']:.1f} | {ehl['payback_months']:.1f} |")
    w(f"| ACR Year 1 · 2 · 3 | {' · '.join(_k(x) for x in base['acr']['by_year'])} | {' · '.join(_k(x) for x in ehl['acr_by_year'])} |")
    w(f"| ACR run-rate at full roll-out | {_k(base['acr']['run_rate_year3'])} | {_k(ehl['acr_run_rate'])} |")
    w(f"| ACR per plant-year · per asset-year | {_k(base['acr']['per_plant_year'])} · {_k(base['acr']['per_asset_year'])} | {_k(ehl['acr_per_plant_year'])} · {_k(ehl['acr_per_asset_year'])} |")
    w(f"| Pull-through (other $ per $1 of AI services) | {base['acr']['pull_through_ratio']:.1f}x | {ehl['pull_through_ratio']:.1f}x |")
    w("")
    w("### 8.3 ACR by lever (expansion case, USD)")
    w("")
    w("| Lever | Year 1 | Year 2 | Year 3 | Run-rate at 8 plants |")
    w("|---|---:|---:|---:|---:|")
    for lid in ["core"] + LEVER_IDS:
        v = ex["acr"]["by_lever"][lid]
        label = "Core platform" if lid == "core" else f"{lid} {LEVER_LABELS[lid]}"
        w(f"| {label} | {_k(v[0])} | {_k(v[1])} | {_k(v[2])} | {_k(ex['acr']['run_rate_by_lever'][lid])} |")
    v = ex["acr"]["by_year"]
    w(f"| **Total** | **{_k(v[0])}** | **{_k(v[1])}** | **{_k(v[2])}** | **{_k(ex['acr']['run_rate'])}** |")
    w("")
    w("### 8.4 ACR by tier, with and without the levers (steady-state run-rate)")
    w("")
    w("| Tier | Plants | Core only | With levers | Multiple | Per plant-year (with) | Per asset-year (with) |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for t in ex["tiers"]:
        w(f"| {t['label']} | {t['plants']} | {_k(t['without_levers']['total'])} | {_k(t['with_levers']['total'])} | {t['uplift_multiple']:.2f}x | {_k(t['with_levers']['per_plant'])} | {_k(t['with_levers']['per_asset_year'])} |")
    w("")
    w("### 8.5 The ACR expansion path (steady-state run-rate, USD)")
    w("")
    w("| Step | Run-rate |")
    w("|---|---:|")
    for st in ex["path"]:
        sign = "+ " if st["kind"] == "delta" else ""
        w(f"| {st['label']} | {sign}{_k(st['value'])} |")
    w("")
    w("### 8.6 Lever audit — Azure lines at run-rate (expansion case, 8 plants)")
    w("")
    w("| Lever | Family | Line item | Annual quantity | Unit | Unit price (USD) | Annual cost |")
    w("|---|---|---|---:|---|---:|---:|")
    for ln in ex["acr"]["line_items"]:
        if ln.get("lever", "core") != "core":
            w(f"| {ln['lever']} | {ln['family']} | {ln['item']} | {ln['quantity']:,.2f} | {ln['unit']} | {ln['unit_price']:g} | {_k(ln['annual'])} |")
    w("")
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    assumptions = load_assumptions(os.path.join(here, "assumptions.json"))
    out = compute_all(assumptions)
    with open(os.path.join(here, "outputs.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(here, "outputs.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(out))
    base = out["scenarios"]["base"]
    print(f"wrote outputs.json / outputs.md  |  Base: NPV {_m(base['roi']['npv'])}, ROI {base['roi']['roi_pct']:.0f}%, payback {base['roi']['payback_months']}, "
          f"Year-3 ACR {_m(base['acr']['by_year'][2], 2)}, run-rate {_m(base['acr']['run_rate_year3'], 2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
