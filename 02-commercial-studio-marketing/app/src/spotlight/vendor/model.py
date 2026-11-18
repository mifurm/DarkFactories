"""SwarmAI Commercial Studio ("Spotlight") — customer ROI and Azure Consumed Revenue (ACR) model.

Pure standard library, deterministic, no I/O inside ``compute``. Public interface (stable since v1.0.0):

    load_assumptions(path=None) -> dict
    compute(assumptions, scenario="base", overrides=None) -> dict
    compute_all(assumptions) -> dict            # Conservative / Base / Upside
    override_specs() -> dict                    # documented, validated override keys for UIs
    main()                                      # python model.py  -> writes outputs.json + outputs.md

v1.1.0 adds optional expansion levers E1-E4 (generative video, catalog-scale content, audience-level personalization,
marketing data platform), each with its own Azure consumption, customer benefit and cost. They are off in Conservative and
Base (Base numbers are unchanged), on in Upside, and switchable through ``overrides`` (``expansion_scale``, ``e1_scale`` ...).
Output keys were only added, never renamed (see README.md section 2).

Everything that is a number comes from ``assumptions.json`` (customer inputs, unit-consumption assumptions and the
Azure Retail Prices API snapshot). See README.md for the formulas, the override keys and how to extend the model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional

MODEL_VERSION = "1.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIOS = ("conservative", "base", "upside")
SCENARIO_LABELS = {"conservative": "Conservative", "base": "Base", "upside": "Upside"}
CLASSES = ("hero_spot", "adapted_video", "static_social", "copy_crm")
CLASS_LABELS = {
    "hero_spot": "Hero spot (master film)",
    "adapted_video": "Adapted video (format / cut-down / language / variant)",
    "static_social": "Static & social image",
    "copy_crm": "Copy & CRM asset",
}
YEARS = (0, 1, 2, 3)
HOURS = 8760.0
SECONDS = 31_536_000.0

LEVERS = ("e1", "e2", "e3", "e4")
LEVER_LABELS = {
    "e1": "E1 · Generative video (VideoProvider)",
    "e2": "E2 · Catalog-scale product content",
    "e3": "E3 · Audience-level personalization",
    "e4": "E4 · Marketing data & clean-room platform (Fabric)",
}
LEVER_BENEFIT_KEY = {
    "e1": "exp_generative_video", "e2": "exp_catalog_content", "e3": "exp_personalization", "e4": "exp_data_platform",
}
CORE_BENEFITS = (
    "production_adaptation", "agency_fees", "localization", "speed_to_market", "roas_uplift", "compliance", "rework_media_waste",
)
BENEFIT_LABELS = {
    "production_adaptation": "Production & adaptation cost",
    "agency_fees": "Agency fees",
    "localization": "Localization",
    "speed_to_market": "Cycle time / speed-to-market",
    "roas_uplift": "ROAS / CPA uplift from testing",
    "compliance": "Compliance-incident avoidance",
    "rework_media_waste": "Rework & media waste",
    "exp_generative_video": "Expansion E1 — generative video (displaced stock / 3D / VFX / pick-ups)",
    "exp_catalog_content": "Expansion E2 — catalog content (avoided photography + conversion effect)",
    "exp_personalization": "Expansion E3 — audience-level personalization (ROAS)",
    "exp_data_platform": "Expansion E4 — marketing data platform (wider measured media)",
}
COST_LABELS = {
    "platform_licence": "Platform licence & support",
    "implementation": "Implementation & integration (one-time)",
    "integration_run": "Integration run & maintenance",
    "change_management": "Change management & training",
    "rights_library": "Licensed music / stock library",
    "review_creative_legal": "Human review — creative, brand, legal",
    "review_linguist": "Human review — linguist QA",
    "review_exceptions": "Human review — Guardian exceptions",
    "expansion_integration": "Expansion levers — integration & enablement (one-time)",
    "expansion_run": "Expansion levers — run, support & data operations",
    "expansion_review": "Expansion levers — human review & sampling",
}
CORE_COSTS = tuple(list(COST_LABELS)[:8])
FAMILY_LABELS = {
    "azure_openai_text": "Azure OpenAI — text, vision & embeddings",
    "azure_openai_image": "Azure OpenAI — image & video generation",
    "speech_language": "Speech & translation",
    "content_safety": "Azure AI Content Safety",
    "ai_search": "Azure AI Search",
    "cosmos_db": "Azure Cosmos DB",
    "storage_delivery": "Blob/ADLS storage + Front Door delivery",
    "compute": "Container Apps (app tier + render jobs) & registry",
    "messaging": "Service Bus & Event Grid",
    "analytics": "Fabric analytics (performance data)",
    "monitoring_security_network": "Monitoring, security, API gateway & private networking",
    "attach_dam_archive": "Pull-through — DAM archive migration (Blob/ADLS)",
    "attach_data_platform": "Pull-through — marketing data platform (Fabric)",
    "attach_security_network": "Pull-through — security & network landing zone",
}
DIRECT_FAMILIES = tuple(list(FAMILY_LABELS)[:11])
ATTACH_FAMILIES = tuple(list(FAMILY_LABELS)[11:])
FAMILIES = DIRECT_FAMILIES + ATTACH_FAMILIES
TIERS = ("pilot", "one_brand", "global_portfolio", "agency_network", "enterprise_scale")

CLASS_TEMPLATES = (
    "mix_baseline_{c}", "mix_studio_{c}", "baseline_cost_{c}", "addressable_{c}", "review_min_{c}",
    "guardian_scale_{c}", "adapt_in_k_{c}", "adapt_out_k_{c}",
)
STATIC_KEYS = (
    "revenue_usd", "marketing_pct_revenue", "paid_media_pct_marketing", "media_scope_pct_paid", "markets",
    "baseline_assets_per_year", "annual_asset_volume", "versions_per_campaign", "active_users_full", "min_active_users",
    "variants_per_campaign", "ref_variants_per_campaign", "adoption_y1", "adoption_y2", "adoption_y3",
    "agency_fee_pct_of_production", "agency_fee_reduction_pct", "loc_share_per_market", "loc_share_cap",
    "baseline_localization_depth", "cost_per_localized_version_usd", "localization_cost_reduction_pct",
    "time_critical_campaigns_per_year", "weeks_saved", "incremental_gp_per_week_usd", "speed_realisation_pct",
    "baseline_roas", "roas_uplift_pct", "contribution_margin_pct", "volume_for_full_coverage",
    "incidents_per_year", "avg_incident_cost_usd", "incident_reduction_pct", "severe_event_prob",
    "severe_event_cost_usd", "severe_reduction_pct", "rework_pct_of_first_pass", "rework_reduction_pct",
    "media_waste_pct", "media_waste_reduction_pct",
    "confidence_production", "confidence_agency", "confidence_localization", "confidence_speed", "confidence_roas",
    "confidence_compliance", "confidence_rework",
    "platform_licence_usd_per_year", "licence_share_y1", "licence_share_y2", "licence_share_y3", "implementation_usd",
    "impl_share_y0", "integration_run_pct", "change_one_time_usd", "change_share_y0", "change_run_usd_per_year",
    "rights_library_usd_per_year", "reviewer_rate_usd_per_hour", "linguist_rate_usd_per_hour",
    "localized_review_minutes", "exception_rate", "exception_minutes", "review_minutes_scale", "discount_rate",
    "azure_consumption_scale", "ai_price_uplift_pct", "cached_input_share", "calls_per_interaction",
    "tam_target_accounts", "tam_agency_networks", "tam_share_one_brand", "tam_penetration_mid",
    "camp_brief_in_k", "camp_brief_out_k", "camp_strategy_in_k", "camp_strategy_out_k", "camp_script_in_k",
    "camp_script_out_k", "camp_story_in_k", "camp_story_out_k", "camp_guardian_stage_in_k",
    "camp_guardian_stage_out_k", "camp_guardian_stages", "camp_preflight_in_k_per_variant",
    "camp_preflight_out_k_per_variant", "camp_insights_in_k", "camp_insights_out_k", "camp_images_medium",
    "camp_images_high", "ver_guardian_checks", "ver_guardian_in_k", "ver_guardian_out_k", "guardian_loop_factor",
    "guardian_reasoning_share", "recheck_share_live", "rechecks_per_year", "loc_in_k", "loc_out_k",
    "ver_images_adapted_video", "ver_images_static", "image_attempt_factor", "img_tokens_medium_1536",
    "img_tokens_high_1536", "img_tokens_medium_1024", "img_prompt_text_tokens", "img_ref_image_tokens", "img_ref_share",
    "interactions_per_user_day", "working_days", "interaction_in_k", "interaction_out_k",
    "interactive_reasoning_share", "images_per_user_day", "cs_text_records_per_version",
    "cs_images_per_video_version", "cs_images_per_static_version", "cs_records_per_interaction",
    "tts_share_of_video_versions", "tts_chars_per_video_version", "tts_hd_share", "translator_chars_per_loc_version",
    "render_output_seconds_per_video_version", "render_vcpu_s_per_output_s", "render_master_vcpu_s",
    "render_overhead_factor", "render_gib_per_vcpu", "aca_active_share", "mb_per_video_version",
    "mb_per_static_version", "mb_per_copy_version", "storage_working_files_factor", "downloads_per_version",
    "blob_writes_per_version", "blob_reads_per_version", "afd_requests_per_version", "events_per_version",
    "cosmos_kb_per_version", "search_queries_per_interaction", "search_queries_per_version", "semantic_ranker_share",
    "fabric_hours_share", "analytics_gb_per_campaign", "attach_dam_hot_share", "attach_security_rate",
    "cohort_ramp_age1", "cohort_ramp_age2", "cohort_ramp_age3",
) + tuple(f"new_{t}_y{y}" for t in TIERS for y in (1, 2, 3))


EXPANSION_KEYS = (
    "e1_scale", "e2_scale", "e3_scale", "e4_scale", "exp_ramp_y1", "exp_ramp_y2", "exp_ramp_y3", "exp_fixed_multiplier",
    "exp_integration_share_y1",
    # E1 generative video
    "e1_hero_gen_share", "e1_hero_gen_seconds", "e1_hero_takes", "e1_hero_premium_share", "e1_adapted_gen_share",
    "e1_adapted_gen_seconds", "e1_adapted_takes", "e1_adapted_premium_share", "e1_mb_per_second", "e1_cs_frames_per_second",
    "e1_transcode_vcpu_s_per_s", "e1_displaced_share_hero", "e1_displaced_share_adapted", "e1_review_min_hero",
    "e1_review_min_adapted", "e1_integration_usd", "e1_run_pct", "confidence_e1",
    # E2 catalog-scale product content
    "e2_skus", "e2_market_presence", "e2_images_per_listing", "e2_refresh_share", "e2_attempt_factor", "e2_high_quality_share",
    "e2_desc_in_k", "e2_desc_out_k", "e2_alt_in_k", "e2_alt_out_k", "e2_guardian_scale", "e2_mb_per_image",
    "e2_renditions_per_image", "e2_pulls_per_image", "e2_search_units_per_million_images", "e2_baseline_cost_per_image_usd",
    "e2_displaced_share", "e2_online_revenue_share", "e2_conversion_uplift_pct", "e2_integration_usd", "e2_run_pct",
    "e2_review_sample_rate", "e2_review_min_per_image", "confidence_e2", "confidence_e2_conversion",
    # E3 audience-level personalization
    "e3_multiplier", "e3_mix_static", "e3_mix_copy", "e3_mix_adapted_video", "e3_consumption_factor", "e3_cosmos_max_ru_s",
    "e3_search_units", "e3_fabric_cu", "e3_roas_uplift_pct", "e3_review_sample_rate", "e3_review_min_per_version",
    "e3_integration_usd", "e3_run_pct", "confidence_e3",
    # E4 marketing data & clean-room platform
    "e4_fabric_cu", "e4_onelake_tb", "e4_purview_cu", "e4_log_gb_month", "e4_scope_increase_pct", "e4_integration_usd",
    "e4_run_pct", "e4_ops_usd_per_year", "confidence_e4",
    "tam_expansion_share", "tam_enterprise_scale_accounts",
)


def required_keys() -> List[str]:
    keys = list(STATIC_KEYS) + list(EXPANSION_KEYS)
    for tpl in CLASS_TEMPLATES:
        keys.extend(tpl.format(c=c) for c in CLASSES)
    return keys


OVERRIDE_SPECS: Dict[str, Dict[str, Any]] = {
    "annual_asset_volume": {"label": "Annual asset volume at full adoption (approved versions / year)", "unit": "versions", "min": 1000, "max": 2_000_000, "maps_to": "annual_asset_volume", "calculator": True},
    "markets": {"label": "Number of markets", "unit": "markets", "min": 1, "max": 60, "maps_to": "markets", "integer": True, "calculator": True},
    "variants_per_campaign": {"label": "Creative variants tested per campaign", "unit": "variants", "min": 1, "max": 100, "maps_to": "variants_per_campaign", "calculator": True},
    "media_spend_in_scope_usd": {"label": "Paid media in scope of Studio-optimised creative (US$ / year, full adoption)", "unit": "USD", "min": 0, "max": 5e9, "maps_to": None, "calculator": True},
    "roas_uplift_pct": {"label": "ROAS uplift from creative testing at the reference variant count", "unit": "fraction", "min": 0.0, "max": 0.5, "maps_to": "roas_uplift_pct", "calculator": True},
    "discount_rate": {"label": "Discount rate", "unit": "fraction", "min": 0.0, "max": 0.3, "maps_to": "discount_rate", "calculator": True},
    "adoption_ramp": {"label": "Adoption ramp (share of full-adoption volume in Year 1, 2, 3)", "unit": "fraction[3]", "min": 0.0, "max": 1.0, "maps_to": None, "calculator": True},
    "agency_cost_per_spot_usd": {"label": "Agency + production cost per 30 s hero spot", "unit": "USD", "min": 10_000, "max": 5_000_000, "maps_to": "baseline_cost_hero_spot", "calculator": True},
    "agency_cost_per_adapted_asset_usd": {"label": "Agency + production cost per adapted video asset", "unit": "USD", "min": 100, "max": 100_000, "maps_to": "baseline_cost_adapted_video", "calculator": True},
    "agency_cost_scale": {"label": "Multiplier on all baseline (agency + production) unit costs", "unit": "x", "min": 0.1, "max": 5.0, "maps_to": None, "calculator": True},
    "studio_review_scale": {"label": "Multiplier on Studio human-review minutes (Studio cost per asset)", "unit": "x", "min": 0.1, "max": 5.0, "maps_to": "review_minutes_scale", "calculator": True},
    "platform_licence_usd_per_year": {"label": "Studio platform licence & support (US$ / year at full scale)", "unit": "USD", "min": 0, "max": 1e8, "maps_to": "platform_licence_usd_per_year", "calculator": True},
    "azure_consumption_scale": {"label": "Multiplier on Azure unit consumption (calibrate with the live meter)", "unit": "x", "min": 0.1, "max": 10.0, "maps_to": "azure_consumption_scale", "calculator": True},
    "ai_price_uplift_pct": {"label": "Model price uplift vs Global Standard list (EU Data Zone = 0.10)", "unit": "fraction", "min": 0.0, "max": 0.5, "maps_to": "ai_price_uplift_pct", "calculator": False},
    "baseline_assets_per_year": {"label": "Creative assets produced per year today", "unit": "assets", "min": 100, "max": 1_000_000, "maps_to": "baseline_assets_per_year", "calculator": False},
    "baseline_roas": {"label": "Baseline ROAS on in-scope media", "unit": "x", "min": 0.1, "max": 20.0, "maps_to": "baseline_roas", "calculator": False},
    "contribution_margin_pct": {"label": "Contribution margin on incremental sales", "unit": "fraction", "min": 0.01, "max": 0.9, "maps_to": "contribution_margin_pct", "calculator": False},
    "active_users_full": {"label": "Active Studio users at full adoption", "unit": "users", "min": 1, "max": 100_000, "maps_to": "active_users_full", "calculator": False},
    "implementation_usd": {"label": "One-time implementation & integration", "unit": "USD", "min": 0, "max": 1e8, "maps_to": "implementation_usd", "calculator": False},
    "expansion_scale": {"label": "Expansion levers E1-E4: one switch for all four (0 = off, 1 = full scale by Year 3)", "unit": "fraction", "min": 0.0, "max": 1.0, "maps_to": None, "calculator": True},
    "e1_scale": {"label": "E1 generative video via VideoProvider: scale reached by Year 3 (0 = off, 1 = full scale)", "unit": "fraction", "min": 0.0, "max": 1.0, "maps_to": "e1_scale", "calculator": True},
    "e2_scale": {"label": "E2 catalog-scale product content: scale reached by Year 3 (0 = off, 1 = full scale)", "unit": "fraction", "min": 0.0, "max": 1.0, "maps_to": "e2_scale", "calculator": True},
    "e3_scale": {"label": "E3 audience-level personalization: scale reached by Year 3 (0 = off, 1 = full scale)", "unit": "fraction", "min": 0.0, "max": 1.0, "maps_to": "e3_scale", "calculator": True},
    "e4_scale": {"label": "E4 marketing data and clean-room platform on Fabric: scale reached by Year 3 (0 = off, 1 = full scale)", "unit": "fraction", "min": 0.0, "max": 1.0, "maps_to": "e4_scale", "calculator": True},
    "expansion_ramp": {"label": "Expansion ramp (share of Year-3 lever scale reached in Year 1, 2, 3)", "unit": "fraction[3]", "min": 0.0, "max": 1.0, "maps_to": None, "calculator": False},
    "catalog_skus": {"label": "E2 active SKUs needing product-page content", "unit": "SKUs", "min": 100, "max": 5_000_000, "maps_to": "e2_skus", "calculator": True},
    "personalization_multiplier": {"label": "E3 segment variants per approved version at full scale", "unit": "x", "min": 1, "max": 100, "maps_to": "e3_multiplier", "calculator": True},
    "video_seconds_per_hero_master": {"label": "E1 kept generated seconds per hero master that uses generated footage", "unit": "seconds", "min": 0, "max": 600, "maps_to": "e1_hero_gen_seconds", "calculator": False},
    "video_seconds_per_adapted_video": {"label": "E1 kept generated seconds per adapted video that uses generated footage", "unit": "seconds", "min": 0, "max": 120, "maps_to": "e1_adapted_gen_seconds", "calculator": False},
    "data_platform_fabric_cu": {"label": "E4 Fabric capacity units at full scale (F64 = 64)", "unit": "CU", "min": 0, "max": 2048, "maps_to": "e4_fabric_cu", "calculator": False},
    "data_platform_onelake_tb": {"label": "E4 OneLake data at full scale", "unit": "TB", "min": 0, "max": 5000, "maps_to": "e4_onelake_tb", "calculator": False},
}


RAMP_OVERRIDES = {"adoption_ramp": "adoption_y{}", "expansion_ramp": "exp_ramp_y{}"}


def override_specs() -> Dict[str, Dict[str, Any]]:
    return copy.deepcopy(OVERRIDE_SPECS)


def load_assumptions(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or os.path.join(HERE, "assumptions.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    missing = [k for k in required_keys() if k not in data["assumptions"]]
    if missing:
        raise KeyError(f"assumptions.json is missing keys: {missing[:8]}{'...' if len(missing) > 8 else ''}")
    return data


def assumptions_hash(assumptions: Dict[str, Any]) -> str:
    blob = json.dumps(assumptions, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _pick(entry: Dict[str, Any], scenario: str, blend: float = 1.0) -> float:
    base = float(entry["base"])
    low = float(entry.get("low", base))
    high = float(entry.get("high", base))
    fav = entry.get("favourable", "neutral")
    blend = float(entry.get("blend", blend))
    if scenario == "base" or fav == "neutral":
        return base
    if scenario == "conservative":
        end = low if fav == "high" else high
    else:
        end = high if fav == "high" else low
    return base + blend * (end - base)


def _norm_scenario(scenario: str) -> str:
    s = str(scenario).strip().lower()
    if s not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}'; expected one of {SCENARIOS}")
    return s


def _resolve(assumptions: Dict[str, Any], scenario: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    entries = assumptions["assumptions"]
    blend = float(assumptions["meta"].get("scenario_blend", 1.0))
    drivers = assumptions["meta"].get("scenario_drivers")
    vals = {
        k: _pick(e, scenario, blend) if (drivers is None or k in drivers or e.get("group") == "pipeline") else float(e["base"])
        for k, e in entries.items()
    }
    applied: Dict[str, Any] = {}
    media_override: Optional[float] = None
    for key, raw in (overrides or {}).items():
        if key in RAMP_OVERRIDES:
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                raise ValueError(f"{key} must be a list of three numbers (Year 1, 2, 3)")
            spec = OVERRIDE_SPECS[key]
            for i, x in enumerate(raw, start=1):
                x = _num(x, key)
                if not spec["min"] <= x <= spec["max"]:
                    raise ValueError(f"{key} values must be within [{spec['min']}, {spec['max']}]")
                vals[RAMP_OVERRIDES[key].format(i)] = x
            applied[key] = [float(x) for x in raw]
            continue
        x = _num(raw, key)
        spec = OVERRIDE_SPECS.get(key)
        if spec is not None:
            if not spec["min"] <= x <= spec["max"]:
                raise ValueError(f"override '{key}' must be within [{spec['min']}, {spec['max']}], got {x}")
            if spec.get("integer"):
                x = float(int(round(x)))
        elif key not in entries:
            raise ValueError(f"unknown override key '{key}'")
        elif x < 0:
            raise ValueError(f"override '{key}' must be >= 0")
        applied[key] = x
    if "agency_cost_scale" in applied:
        for c in CLASSES:
            vals[f"baseline_cost_{c}"] *= applied["agency_cost_scale"]
    for key, x in applied.items():
        if key in RAMP_OVERRIDES or key in ("agency_cost_scale", "expansion_scale"):
            continue
        if key == "media_spend_in_scope_usd":
            media_override = x
            continue
        spec = OVERRIDE_SPECS.get(key)
        target = spec["maps_to"] if spec and spec["maps_to"] else key
        vals[target] = x
    if "expansion_scale" in applied:
        for lv in LEVERS:
            if f"{lv}_scale" not in applied:
                vals[f"{lv}_scale"] = applied["expansion_scale"]
    derived_media = vals["revenue_usd"] * vals["marketing_pct_revenue"] * vals["paid_media_pct_marketing"] * vals["media_scope_pct_paid"]
    vals["media_spend_in_scope_usd"] = media_override if media_override is not None else derived_media
    vals["_overrides"] = applied
    return vals


def _num(x: Any, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"override '{name}' must be a number")
    if not math.isfinite(float(x)):
        raise ValueError(f"override '{name}' must be finite")
    return float(x)


# ----------------------------------------------------------------------------------------------------------------------
# Load (volumes) helpers
# ----------------------------------------------------------------------------------------------------------------------

def _loc_share(V: Dict[str, Any], markets: float) -> float:
    return min(V["loc_share_cap"], V["loc_share_per_market"] * max(0.0, markets - 1.0))


def _load(V: Dict[str, Any], volume: float, markets: float, users: float, variants: float) -> Dict[str, Any]:
    ver = {c: volume * V[f"mix_studio_{c}"] for c in CLASSES}
    camp = volume / max(V["versions_per_campaign"], 1.0)
    share = _loc_share(V, markets)
    return {
        "volume": volume, "versions": ver, "campaigns": camp, "markets": markets, "loc_share": share,
        "loc_versions": volume * share, "users": users, "variants": variants,
        "video_versions": ver["hero_spot"] + ver["adapted_video"],
        "interactions": users * V["interactions_per_user_day"] * V["working_days"],
    }


# ----------------------------------------------------------------------------------------------------------------------
# Azure bottom-up cost (units x Azure Retail Prices API list price)
# ----------------------------------------------------------------------------------------------------------------------

def _tok(V, P, model: str, in_k: float, out_k: float) -> float:
    cs = V["cached_input_share"]
    if model == "mini":
        pin, pcd, pout = P["gpt54mini_in"], P["gpt54mini_cached_in"], P["gpt54mini_out"]
    else:
        pin, pcd, pout = P["gpt54_in"], P["gpt54_cached_in"], P["gpt54_out"]
    return in_k / 1e3 * ((1.0 - cs) * pin + cs * pcd) + out_k / 1e3 * pout


def _guardian_pass(V, P, scale: float, checks: float, loop: float) -> float:
    r = V["guardian_reasoning_share"]
    one = (1.0 - r) * _tok(V, P, "mini", V["ver_guardian_in_k"] * scale, V["ver_guardian_out_k"] * scale) \
        + r * _tok(V, P, "reasoning", V["ver_guardian_in_k"] * scale, V["ver_guardian_out_k"] * scale)
    return one * checks * loop


def _image_cost(V, P, out_tokens: float) -> float:
    return (out_tokens / 1e6 * P["image15_img_out"]
            + V["img_prompt_text_tokens"] / 1e6 * P["image15_text_in"]
            + V["img_ref_share"] * V["img_ref_image_tokens"] / 1e6 * P["image15_img_in"])


def _azure_year(V, P, load: Dict[str, Any], fp: Dict[str, Any], prev_stock_gb: float, prev_campaigns: float,
                ramp: float, attach: Dict[str, float]) -> Dict[str, Any]:
    s = V["azure_consumption_scale"]
    m_ai = 1.0 + V["ai_price_uplift_pct"]
    ver, camp, users = load["versions"], load["campaigns"], load["users"]
    total_versions = load["volume"]
    interactions = load["interactions"]
    variants = load["variants"]
    video_versions = load["video_versions"]
    loc_versions = load["loc_versions"]

    # --- Azure OpenAI text, vision, embeddings
    mini_in = (V["camp_brief_in_k"] + V["camp_script_in_k"] + V["camp_story_in_k"]
               + V["camp_guardian_stage_in_k"] * V["camp_guardian_stages"] + V["camp_preflight_in_k_per_variant"] * variants)
    mini_out = (V["camp_brief_out_k"] + V["camp_script_out_k"] + V["camp_story_out_k"]
                + V["camp_guardian_stage_out_k"] * V["camp_guardian_stages"] + V["camp_preflight_out_k_per_variant"] * variants)
    reason_in = V["camp_strategy_in_k"] + V["camp_insights_in_k"]
    reason_out = V["camp_strategy_out_k"] + V["camp_insights_out_k"]
    text = camp * (_tok(V, P, "mini", mini_in, mini_out) + _tok(V, P, "reasoning", reason_in, reason_out))
    for c in CLASSES:
        text += ver[c] * _tok(V, P, "mini", V[f"adapt_in_k_{c}"], V[f"adapt_out_k_{c}"])
        text += ver[c] * _guardian_pass(V, P, V[f"guardian_scale_{c}"], V["ver_guardian_checks"], V["guardian_loop_factor"])
    text += loc_versions * _tok(V, P, "mini", V["loc_in_k"], V["loc_out_k"])
    text += total_versions * V["recheck_share_live"] * V["rechecks_per_year"] * _guardian_pass(V, P, 1.0, 1.0, 1.0)
    r_int = V["interactive_reasoning_share"]
    text += interactions * V["calls_per_interaction"] * ((1.0 - r_int) * _tok(V, P, "mini", V["interaction_in_k"], V["interaction_out_k"])
                                                         + r_int * _tok(V, P, "reasoning", V["interaction_in_k"], V["interaction_out_k"]))
    embed_tokens = total_versions * 2_000 + interactions * 300 + camp * 500_000
    text = text * m_ai + embed_tokens / 1e6 * P["embed3small"]
    text *= s

    # --- image generation
    attempts = V["image_attempt_factor"]
    n_med_1536 = camp * V["camp_images_medium"] + ver["adapted_video"] * V["ver_images_adapted_video"] * attempts
    n_high_1536 = camp * V["camp_images_high"]
    n_med_1024 = ver["static_social"] * V["ver_images_static"] * attempts + users * V["working_days"] * V["images_per_user_day"]
    image = (n_med_1536 * _image_cost(V, P, V["img_tokens_medium_1536"]) + n_high_1536 * _image_cost(V, P, V["img_tokens_high_1536"])
             + n_med_1024 * _image_cost(V, P, V["img_tokens_medium_1024"])) * m_ai * s
    n_images = n_med_1536 + n_high_1536 + n_med_1024

    # --- speech & translation
    tts_chars = video_versions * (V["tts_share_of_video_versions"] + load["loc_share"]) * V["tts_chars_per_video_version"]
    speech = tts_chars / 1e6 * (V["tts_hd_share"] * P["tts_hd"] * m_ai + (1.0 - V["tts_hd_share"]) * P["speech_neural"])
    speech += loc_versions * V["translator_chars_per_loc_version"] / 1e6 * P["translator"]
    speech *= s

    # --- content safety
    cs_text = total_versions * V["cs_text_records_per_version"] + camp * 40 + interactions * V["cs_records_per_interaction"]
    cs_img = video_versions * V["cs_images_per_video_version"] + ver["static_social"] * V["cs_images_per_static_version"] + n_images
    safety = (cs_text / 1e3 * P["cs_text"] + cs_img / 1e3 * P["cs_image"]) * s

    mult = 1.0 + fp["nonprod_multiplier"] + fp["dr_multiplier"]

    # --- AI Search
    search_fixed = fp["search_units"] * P[fp["search_price_key"]] * HOURS
    queries = interactions * V["search_queries_per_interaction"] + total_versions * V["search_queries_per_version"]
    search_var = queries / 1e3 * V["semantic_ranker_share"] * P["search_semantic"] * s

    # --- Cosmos DB
    cosmos_fixed = fp["cosmos_max_ru_s"] / 100.0 * P["cosmos_autoscale_100ru_hour"] * HOURS * fp["cosmos_avg_util"] * fp["cosmos_regions"]
    cosmos_stock_versions = (prev_campaigns * V["versions_per_campaign"]) + total_versions / 2.0
    cosmos_var = cosmos_stock_versions * V["cosmos_kb_per_version"] / 1e6 * P["cosmos_storage_gb_month"] * 12.0

    # --- Blob + Front Door delivery
    deliver_gb = (video_versions * V["mb_per_video_version"] + ver["static_social"] * V["mb_per_static_version"]
                  + ver["copy_crm"] * V["mb_per_copy_version"]) / 1024.0
    added_gb = deliver_gb * (1.0 + V["storage_working_files_factor"])
    avg_gb = prev_stock_gb + added_gb / 2.0
    storage_var = avg_gb * P["blob_hot_zrs_gb_month"] * 12.0
    storage_var += total_versions * (V["blob_writes_per_version"] / 1e4 * P["blob_write_10k"] + V["blob_reads_per_version"] / 1e4 * P["blob_read_10k"])
    afd_prefix = "afd_premium" if fp["afd"] == "premium" else "afd_standard"
    egress_gb = deliver_gb * V["downloads_per_version"]
    storage_var += egress_gb * P[f"{afd_prefix}_out_gb"] + total_versions * V["afd_requests_per_version"] / 1e4 * P[f"{afd_prefix}_requests_10k"]
    storage_var *= s
    storage_fixed = P[f"{afd_prefix}_base_month"] * 12.0

    # --- Compute (app tier + render jobs + registry)
    a = V["aca_active_share"]
    per_replica = (fp["app_vcpu"] * (a * P["aca_vcpu_second_active"] + (1 - a) * P["aca_vcpu_second_idle"])
                   + fp["app_gib"] * (a * P["aca_gib_second_active"] + (1 - a) * P["aca_gib_second_idle"])) * SECONDS
    compute_fixed = fp["app_replicas"] * per_replica + P["acr_premium_day" if fp["registry"] == "premium" else "acr_standard_day"] * 365.0
    render_vcpu_s = (video_versions * V["render_output_seconds_per_video_version"] * V["render_vcpu_s_per_output_s"]
                     + ver["hero_spot"] * V["render_master_vcpu_s"]) * V["render_overhead_factor"]
    compute_var = render_vcpu_s * (P["aca_vcpu_second_active"] + V["render_gib_per_vcpu"] * P["aca_gib_second_active"]) * s

    # --- Messaging
    events = total_versions * V["events_per_version"] + interactions * 0.5
    msg_var = (max(0.0, events - 100_000) / 1e6 * P["eventgrid_ops_1m"] + events * 2.0 / 1e6 * P["sb_ops_1m"]) * s
    if fp["servicebus"] == "premium":
        msg_fixed = fp["servicebus_units"] * P["sb_premium_mu_hour"] * HOURS
    else:
        msg_fixed = P["sb_standard_base_hour"] * HOURS

    # --- Analytics
    analytics_fixed = fp["fabric_cu"] * P["fabric_cu_hour"] * HOURS * V["fabric_hours_share"]
    analytics_var = (prev_campaigns + camp / 2.0) * V["analytics_gb_per_campaign"] * P["onelake_gb_month"] * 12.0 * s

    # --- Monitoring, security, gateway, private networking
    log_gb = max(0.0, fp["log_gb_month"] - 5.0) * 12.0
    msn_fixed = log_gb * P["loganalytics_ingest_gb"]
    msn_fixed += fp["kv_ops_per_month"] * 12.0 / 1e4 * P["keyvault_ops_10k"]
    if fp["defender_storage_accounts"] > 0:
        msn_fixed += fp["defender_storage_accounts"] * P["defender_storage_hour"] * HOURS + P["defender_arm_hour"] * HOURS
    msn_fixed += fp["apim_units"] * (P[fp["apim_price_key"]] if fp["apim_price_key"] else 0.0) * HOURS
    msn_fixed += fp["purview_cu"] * P["purview_cu_hour"] * HOURS
    msn_fixed += fp["private_endpoints"] * P["private_endpoint_hour"] * HOURS
    msn_var = added_gb * P["defender_malware_gb"] * (1.0 if fp["defender_storage_accounts"] > 0 else 0.0) * s

    fixed = {
        "ai_search": search_fixed, "cosmos_db": cosmos_fixed, "storage_delivery": storage_fixed, "compute": compute_fixed,
        "messaging": msg_fixed, "analytics": analytics_fixed, "monitoring_security_network": msn_fixed,
    }
    variable = {
        "azure_openai_text": text, "azure_openai_image": image, "speech_language": speech, "content_safety": safety,
        "ai_search": search_var, "cosmos_db": cosmos_var, "storage_delivery": storage_var, "compute": compute_var,
        "messaging": msg_var, "analytics": analytics_var, "monitoring_security_network": msn_var,
    }
    fam: Dict[str, float] = {}
    for f in DIRECT_FAMILIES:
        fam[f] = variable.get(f, 0.0) + fixed.get(f, 0.0) * mult
    fixed_with_mult = sum(fixed.values()) * mult

    dam = attach["dam_tb"] * 1000.0 * (V["attach_dam_hot_share"] * P["blob_hot_zrs_gb_month"]
                                       + (1.0 - V["attach_dam_hot_share"]) * P["blob_cool_zrs_gb_month"]) * 12.0 * ramp
    plat = attach["fabric_cu"] * P["fabric_cu_hour"] * HOURS * V["fabric_hours_share"] * ramp
    sec = V["attach_security_rate"] * fixed_with_mult
    fam["attach_dam_archive"] = dam
    fam["attach_data_platform"] = plat
    fam["attach_security_network"] = sec
    return {
        "by_family": fam, "fixed_total": fixed_with_mult, "variable_total": sum(variable.values()),
        "added_gb": added_gb, "n_images": n_images, "render_vcpu_s": render_vcpu_s,
        "variable_by_family": dict(variable), "fixed_by_family": {f: fixed.get(f, 0.0) * mult for f in DIRECT_FAMILIES},
    }


def _blend_footprints(A, V, P, load, weights: Dict[str, float], prev_stock: float, prev_campaigns: float, ramp: float) -> Dict[str, Any]:
    agg: Dict[str, Any] = {"by_family": {f: 0.0 for f in FAMILIES}, "fixed_total": 0.0, "variable_total": 0.0}
    added = 0.0
    for name, w in weights.items():
        if w <= 0:
            continue
        tier_cfg = A["tiers"][name]
        res = _azure_year(V, P, load, A["footprints"][tier_cfg["footprint"]], prev_stock, prev_campaigns, ramp, tier_cfg["attach"])
        for f in FAMILIES:
            agg["by_family"][f] += w * res["by_family"][f]
        agg["fixed_total"] += w * res["fixed_total"]
        agg["variable_total"] += w * res["variable_total"]
        added = res["added_gb"]
    agg["added_gb"] = added
    return agg


# ----------------------------------------------------------------------------------------------------------------------
# Expansion levers E1-E4 (optional; off in Conservative and Base, on in Upside; each carries its own cost AND benefit)
# ----------------------------------------------------------------------------------------------------------------------

def _afd_out(P, fp) -> float:
    return P["afd_premium_out_gb"] if fp["afd"] == "premium" else P["afd_standard_out_gb"]


def _lever_azure(lv: str, V: Dict[str, Any], P: Dict[str, float], fp: Dict[str, Any], ld: Dict[str, Any], S: float) -> Dict[str, Any]:
    """Azure consumption (list-price USD per year) of one expansion lever.

    ``S`` is the lever scale in that year (lever scale x expansion ramp, 0..1). ``ld`` is the core load of the year (volumes of
    approved versions, markets). Returns the direct-family costs, the infrastructure ("fixed") part of them, the security /
    network pull-through and the physical units behind the cost (used for unit economics and benefits)."""
    fam = {f: 0.0 for f in DIRECT_FAMILIES}
    out: Dict[str, Any] = {"fam": fam, "fixed": 0.0, "attach_security": 0.0, "units": {}}
    if S <= 0.0:
        return out
    s = V["azure_consumption_scale"]
    m_ai = 1.0 + V["ai_price_uplift_pct"]
    fixed_mult = V["exp_fixed_multiplier"]
    wf = V["storage_working_files_factor"]
    units: Dict[str, float] = out["units"]
    fixed = 0.0
    if lv == "e1":
        ver = ld["versions"]
        n_hero = ver["hero_spot"] * V["e1_hero_gen_share"] * S
        n_adp = ver["adapted_video"] * V["e1_adapted_gen_share"] * S
        kept_h, kept_a = n_hero * V["e1_hero_gen_seconds"], n_adp * V["e1_adapted_gen_seconds"]
        gen_h, gen_a = kept_h * V["e1_hero_takes"], kept_a * V["e1_adapted_takes"]
        p_std, p_prem = P["video_sora2_sec"], P["video_sora2_pro_hires_sec"]
        price_h = V["e1_hero_premium_share"] * p_prem + (1.0 - V["e1_hero_premium_share"]) * p_std
        price_a = V["e1_adapted_premium_share"] * p_prem + (1.0 - V["e1_adapted_premium_share"]) * p_std
        model = (gen_h * price_h + gen_a * price_a) * m_ai * s
        kept = kept_h + kept_a
        guardian = (n_hero + n_adp) * _guardian_pass(V, P, 1.0, V["ver_guardian_checks"], V["guardian_loop_factor"]) * m_ai * s
        safety = kept * V["e1_cs_frames_per_second"] / 1e3 * P["cs_image"] * s
        render = kept * V["e1_transcode_vcpu_s_per_s"] * (P["aca_vcpu_second_active"] + V["render_gib_per_vcpu"] * P["aca_gib_second_active"]) * s
        gb = kept * V["e1_mb_per_second"] / 1024.0
        storage = (gb * (1.0 + wf) / 2.0 * P["blob_hot_zrs_gb_month"] * 12.0 + gb * V["downloads_per_version"] * _afd_out(P, fp)) * s
        fam["azure_openai_image"] += model
        fam["azure_openai_text"] += guardian
        fam["content_safety"] += safety
        fam["compute"] += render
        fam["storage_delivery"] += storage
        units.update({"clips_hero": n_hero, "clips_adapted": n_adp, "kept_seconds": kept, "generated_seconds": gen_h + gen_a,
                      "video_model_usd": model})
    elif lv == "e2":
        listings = V["e2_skus"] * ld["markets"] * V["e2_market_presence"] * S
        kept = listings * V["e2_images_per_listing"] * V["e2_refresh_share"]
        gen = kept * V["e2_attempt_factor"]
        hq = V["e2_high_quality_share"]
        images = gen * ((1.0 - hq) * _image_cost(V, P, V["img_tokens_medium_1024"]) + hq * _image_cost(V, P, V["img_tokens_high_1536"])) * m_ai * s
        text = (listings * (_tok(V, P, "mini", V["e2_desc_in_k"], V["e2_desc_out_k"])
                            + _guardian_pass(V, P, V["e2_guardian_scale"], V["ver_guardian_checks"], V["guardian_loop_factor"]))
                + kept * _tok(V, P, "mini", V["e2_alt_in_k"], V["e2_alt_out_k"])) * m_ai
        text = (text + kept * 1000.0 / 1e6 * P["embed3small"]) * s
        safety = (gen / 1e3 * P["cs_image"] + listings * 2.0 / 1e3 * P["cs_text"]) * s
        gb = kept * V["e2_mb_per_image"] * V["e2_renditions_per_image"] / 1024.0
        storage = (gb * (1.0 + wf) / 2.0 * P["blob_hot_zrs_gb_month"] * 12.0
                   + kept * V["e2_pulls_per_image"] * V["e2_mb_per_image"] / 1024.0 * _afd_out(P, fp)) * s
        search = V["e2_search_units_per_million_images"] * kept / 1e6 * P[fp["search_price_key"]] * HOURS * fixed_mult
        fam["azure_openai_image"] += images
        fam["azure_openai_text"] += text
        fam["content_safety"] += safety
        fam["storage_delivery"] += storage
        fam["ai_search"] += search
        fixed += search
        units.update({"listings": listings, "kept_images": kept, "generated_images": gen, "image_model_usd": images})
    elif lv == "e3":
        pers = ld["volume"] * V["e3_multiplier"] * S
        Ve = dict(V)
        Ve.update({"mix_studio_hero_spot": 0.0, "mix_studio_adapted_video": V["e3_mix_adapted_video"],
                   "mix_studio_static_social": V["e3_mix_static"], "mix_studio_copy_crm": V["e3_mix_copy"],
                   "versions_per_campaign": 1e12})
        res = _azure_year(Ve, P, _load(Ve, pers, 1.0, 0.0, 0.0), fp, 0.0, 0.0, 0.0, {"dam_tb": 0.0, "fabric_cu": 0.0})
        for f, x in res["variable_by_family"].items():
            fam[f] += x * V["e3_consumption_factor"]
        cosmos = (V["e3_cosmos_max_ru_s"] * S / 100.0 * P["cosmos_autoscale_100ru_hour"] * HOURS
                  * fp["cosmos_avg_util"] * fp["cosmos_regions"] * fixed_mult)
        search = V["e3_search_units"] * S * P[fp["search_price_key"]] * HOURS * fixed_mult
        fabric = V["e3_fabric_cu"] * S * P["fabric_cu_hour"] * HOURS * V["fabric_hours_share"] * fixed_mult
        fam["cosmos_db"] += cosmos
        fam["ai_search"] += search
        fam["analytics"] += fabric
        fixed += cosmos + search + fabric
        units.update({"versions": pers})
    elif lv == "e4":
        fabric = V["e4_fabric_cu"] * S * P["fabric_cu_hour"] * HOURS * V["fabric_hours_share"] * fixed_mult
        onelake = V["e4_onelake_tb"] * 1000.0 * S * P["onelake_gb_month"] * 12.0 * s
        purview = V["e4_purview_cu"] * S * P["purview_cu_hour"] * HOURS * fixed_mult
        logs = V["e4_log_gb_month"] * S * 12.0 * P["loganalytics_ingest_gb"] * s
        fam["analytics"] += fabric + onelake
        fam["monitoring_security_network"] += purview + logs
        fixed += fabric + purview
        units.update({"capacity_units": V["e4_fabric_cu"] * S, "onelake_tb": V["e4_onelake_tb"] * S})
    else:
        raise ValueError(f"unknown lever '{lv}'")
    out["fixed"] = fixed
    out["attach_security"] = V["attach_security_rate"] * fixed
    return out


def _lever_econ(lv: str, V: Dict[str, Any], t: int, S: float, units: Dict[str, float], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Customer-side benefit and non-Azure cost of one expansion lever in year ``t`` (Year 0 carries nothing)."""
    gross: Dict[str, float] = {}
    rate = V["reviewer_rate_usd_per_hour"]
    rscale = V["review_minutes_scale"]
    review_h = 0.0
    ops = 0.0
    if S > 0.0:
        if lv == "e1":
            res_h = ctx["prod_pool"]["hero_spot"] * (1.0 - V["addressable_hero_spot"]) * (1.0 + V["agency_fee_pct_of_production"])
            res_a = ctx["prod_pool"]["adapted_video"] * (1.0 - V["addressable_adapted_video"]) * (1.0 + V["agency_fee_pct_of_production"])
            gross["displaced_external_cost"] = ctx["repl"][t] * S * (
                res_h * V["e1_hero_gen_share"] * V["e1_displaced_share_hero"]
                + res_a * V["e1_adapted_gen_share"] * V["e1_displaced_share_adapted"])
            review_h = (units["clips_hero"] * V["e1_review_min_hero"] + units["clips_adapted"] * V["e1_review_min_adapted"]) * rscale / 60.0
            conf = {"displaced_external_cost": V["confidence_e1"]}
        elif lv == "e2":
            gross["avoided_photography_retouching"] = units["kept_images"] * V["e2_baseline_cost_per_image_usd"] * V["e2_displaced_share"]
            gross["conversion_effect_flagged"] = (V["revenue_usd"] * V["e2_online_revenue_share"] * V["e2_conversion_uplift_pct"] * S
                                                  * V["contribution_margin_pct"])
            review_h = units["kept_images"] * V["e2_review_sample_rate"] * V["e2_review_min_per_image"] * rscale / 60.0
            conf = {"avoided_photography_retouching": V["confidence_e2"], "conversion_effect_flagged": V["confidence_e2_conversion"]}
        elif lv == "e3":
            gross["audience_roas_uplift"] = (V["media_spend_in_scope_usd"] * ctx["coverage"][t] * V["baseline_roas"]
                                             * V["e3_roas_uplift_pct"] * V["contribution_margin_pct"] * S)
            review_h = units["versions"] * V["e3_review_sample_rate"] * V["e3_review_min_per_version"] * rscale / 60.0
            conf = {"audience_roas_uplift": V["confidence_e3"]}
        else:
            ext = ctx["paid_media_total"] * V["e4_scope_increase_pct"] * S
            gross["wider_measured_media_roas"] = (ext * ctx["coverage"][t] * V["baseline_roas"] * V["roas_uplift_pct"] * ctx["f_var"]
                                                  * V["contribution_margin_pct"])
            gross["wider_measured_media_waste"] = ext * ctx["coverage"][t] * V["media_waste_pct"] * V["media_waste_reduction_pct"]
            ops = V["e4_ops_usd_per_year"] * S
            conf = {"wider_measured_media_roas": V["confidence_e4"], "wider_measured_media_waste": V["confidence_e4"]}
    else:
        conf = {}
    net = sum(x * conf[k] for k, x in gross.items())
    integ_total = V[f"{lv}_integration_usd"] if V[f"{lv}_scale"] > 0.0 else 0.0
    share1 = V["exp_integration_share_y1"]
    integration = integ_total * (share1 if t == 1 else (1.0 - share1) if t == 2 else 0.0)
    run = V[f"{lv}_run_pct"] * integ_total * (0.5 if t == 1 else 1.0) if t >= 1 else 0.0
    return {"gross": gross, "net": net, "gross_total": sum(gross.values()), "integration": integration, "run": run + ops,
            "review_hours": review_h, "review": review_h * rate}


def _lever_payback(flows: List[float]) -> Optional[float]:
    """Months from Year 0 until the lever's own cumulative net flow turns non-negative (0 if it never goes negative)."""
    cum, lowest = 0.0, 0.0
    for t in range(1, len(flows)):
        before = cum
        cum += flows[t]
        lowest = min(lowest, cum)
        if lowest < 0.0 and cum >= 0.0 and before < 0.0 and flows[t] > 0.0:
            return round(12.0 * (t - 1) + 12.0 * (-before / flows[t]), 2)
    if lowest >= 0.0:
        return 0.0
    return None


# ----------------------------------------------------------------------------------------------------------------------
# Core model
# ----------------------------------------------------------------------------------------------------------------------

def _core(A: Dict[str, Any], V: Dict[str, Any]) -> Dict[str, Any]:
    P = {k: float(v["price"]) for k, v in A["pricing"]["items"].items()}
    ramp = [0.0, V["adoption_y1"], V["adoption_y2"], V["adoption_y3"]]
    licence_share = [0.0, V["licence_share_y1"], V["licence_share_y2"], V["licence_share_y3"]]
    blend = A["reference_footprint_blend"]

    # volumes ------------------------------------------------------------------------------------------------------
    loads, vol_rows = [], {"versions": [], "campaigns": [], "users": [], "localized_versions": [], "video_versions": []}
    for t in YEARS:
        vol = ramp[t] * V["annual_asset_volume"]
        users = 0.0 if t == 0 else max(V["min_active_users"], ramp[t] * V["active_users_full"])
        ld = _load(V, vol, V["markets"], users, V["variants_per_campaign"])
        loads.append(ld)
        vol_rows["versions"].append(vol)
        vol_rows["campaigns"].append(ld["campaigns"])
        vol_rows["users"].append(users)
        vol_rows["localized_versions"].append(ld["loc_versions"])
        vol_rows["video_versions"].append(ld["video_versions"])

    # benefits -----------------------------------------------------------------------------------------------------
    base_assets = V["baseline_assets_per_year"]
    loc_base_share = _loc_share(V, V["markets"])
    prod_pool = {c: base_assets * V[f"mix_baseline_{c}"] * V[f"baseline_cost_{c}"] for c in CLASSES}
    fee_pool = {c: prod_pool[c] * V["agency_fee_pct_of_production"] for c in CLASSES}
    addr_prod = sum(prod_pool[c] * V[f"addressable_{c}"] for c in CLASSES)
    addr_fee = sum(fee_pool[c] * V[f"addressable_{c}"] for c in CLASSES)
    loc_pool = base_assets * loc_base_share * V["baseline_localization_depth"] * V["cost_per_localized_version_usd"]
    f_var = math.log1p(V["variants_per_campaign"]) / math.log1p(V["ref_variants_per_campaign"])
    gross = {k: [0.0] * 4 for k in CORE_BENEFITS}
    coverage = [0.0] * 4
    repl = [0.0] * 4
    for t in (1, 2, 3):
        repl[t] = ramp[t] * min(1.0, V["annual_asset_volume"] / max(base_assets, 1.0))
        coverage[t] = min(1.0, vol_rows["versions"][t] / max(V["volume_for_full_coverage"], 1.0))
        gross["production_adaptation"][t] = repl[t] * addr_prod
        gross["agency_fees"][t] = repl[t] * addr_fee * V["agency_fee_reduction_pct"]
        gross["localization"][t] = repl[t] * loc_pool * V["localization_cost_reduction_pct"]
        gross["speed_to_market"][t] = (V["time_critical_campaigns_per_year"] * V["weeks_saved"] * V["incremental_gp_per_week_usd"]
                                       * V["speed_realisation_pct"] * repl[t])
        gross["roas_uplift"][t] = (V["media_spend_in_scope_usd"] * coverage[t] * V["baseline_roas"] * V["roas_uplift_pct"] * f_var
                                   * V["contribution_margin_pct"])
        gross["compliance"][t] = ((V["incidents_per_year"] * V["avg_incident_cost_usd"] * V["incident_reduction_pct"]
                                   + V["severe_event_prob"] * V["severe_event_cost_usd"] * V["severe_reduction_pct"]) * repl[t])
        rework = repl[t] * (addr_prod + addr_fee) * V["rework_pct_of_first_pass"] * V["rework_reduction_pct"]
        waste = V["media_spend_in_scope_usd"] * coverage[t] * V["media_waste_pct"] * V["media_waste_reduction_pct"]
        gross["rework_media_waste"][t] = rework + waste
    conf = {
        "production_adaptation": V["confidence_production"], "agency_fees": V["confidence_agency"],
        "localization": V["confidence_localization"], "speed_to_market": V["confidence_speed"],
        "roas_uplift": V["confidence_roas"], "compliance": V["confidence_compliance"], "rework_media_waste": V["confidence_rework"],
    }
    ben = {k: [x * conf[k] for x in gross[k]] for k in gross}

    # Azure (ACR) --------------------------------------------------------------------------------------------------
    fam_by_year = {f: [0.0] * 4 for f in FAMILIES}
    stock_gb, cum_campaigns = 0.0, 0.0
    fixed_by_year, variable_by_year = [0.0] * 4, [0.0] * 4
    for t in (1, 2, 3):
        res = _blend_footprints(A, V, P, loads[t], blend[f"y{t}"], stock_gb, cum_campaigns, ramp[t])
        for f in FAMILIES:
            fam_by_year[f][t] = res["by_family"][f]
        fixed_by_year[t], variable_by_year[t] = res["fixed_total"], res["variable_total"]
        stock_gb += res["added_gb"]
        cum_campaigns += loads[t]["campaigns"]
    direct_core = [sum(fam_by_year[f][t] for f in DIRECT_FAMILIES) for t in YEARS]
    attach_core = [sum(fam_by_year[f][t] for f in ATTACH_FAMILIES) for t in YEARS]
    acr_core = [direct_core[t] + attach_core[t] for t in YEARS]
    variable_core_by_year, fixed_core_by_year = list(variable_by_year), list(fixed_by_year)

    # expansion levers E1-E4: Azure consumption, customer benefit and non-Azure cost (all zero while a lever's scale is 0) --
    r = V["discount_rate"]
    exp_ramp = [0.0, V["exp_ramp_y1"], V["exp_ramp_y2"], V["exp_ramp_y3"]]
    fp_ref = A["footprints"][A.get("expansion", {}).get("footprint", "global_portfolio")]
    paid_media_total = V["revenue_usd"] * V["marketing_pct_revenue"] * V["paid_media_pct_marketing"]
    ctx = {"prod_pool": prod_pool, "repl": repl, "coverage": coverage, "f_var": f_var, "paid_media_total": paid_media_total}
    exp: Dict[str, Dict[str, Any]] = {}
    for lv in LEVERS:
        e: Dict[str, Any] = {
            "scale": V[f"{lv}_scale"], "year_scale": [V[f"{lv}_scale"] * exp_ramp[t] for t in YEARS],
            "fam": {f: [0.0] * 4 for f in DIRECT_FAMILIES}, "attach_security": [0.0] * 4, "fixed": [0.0] * 4,
            "gross_by_component": {}, "gross": [0.0] * 4, "net": [0.0] * 4, "integration": [0.0] * 4, "run": [0.0] * 4,
            "review": [0.0] * 4, "review_hours": [0.0] * 4, "units": {},
        }
        for t in (1, 2, 3):
            S = e["year_scale"][t]
            az = _lever_azure(lv, V, P, fp_ref, loads[t], S)
            ec = _lever_econ(lv, V, t, S, az["units"], ctx)
            for f in DIRECT_FAMILIES:
                e["fam"][f][t] = az["fam"][f]
            e["attach_security"][t], e["fixed"][t] = az["attach_security"], az["fixed"]
            for k, x in ec["gross"].items():
                e["gross_by_component"].setdefault(k, [0.0] * 4)[t] = x
            e["gross"][t], e["net"][t] = ec["gross_total"], ec["net"]
            e["integration"][t], e["run"][t], e["review"][t], e["review_hours"][t] = ec["integration"], ec["run"], ec["review"], ec["review_hours"]
            for k, x in az["units"].items():
                e["units"].setdefault(k, [0.0] * 4)[t] = x
        e["direct"] = [sum(e["fam"][f][t] for f in DIRECT_FAMILIES) for t in YEARS]
        e["azure"] = [e["direct"][t] + e["attach_security"][t] for t in YEARS]
        e["variable"] = [e["direct"][t] - e["fixed"][t] for t in YEARS]
        e["other_cost"] = [e["integration"][t] + e["run"][t] + e["review"][t] for t in YEARS]
        e["flows"] = [e["net"][t] - e["azure"][t] - e["other_cost"][t] for t in YEARS]
        e["npv"] = sum(e["flows"][t] / (1.0 + r) ** t for t in YEARS)
        e["payback_months"] = _lever_payback(e["flows"])
        exp[lv] = e
        for t in YEARS:
            for f in DIRECT_FAMILIES:
                fam_by_year[f][t] += e["fam"][f][t]
            fam_by_year["attach_security_network"][t] += e["attach_security"][t]
            fixed_by_year[t] += e["fixed"][t]
            variable_by_year[t] += e["variable"][t]
        k = LEVER_BENEFIT_KEY[lv]
        gross[k] = list(e["gross"])
        ben[k] = list(e["net"])
        conf[k] = sum(e["net"]) / sum(e["gross"]) if sum(e["gross"]) > 0 else V[f"confidence_{lv}"]
    ben_total = [sum(ben[k][t] for k in ben) for t in YEARS]
    direct = [sum(fam_by_year[f][t] for f in DIRECT_FAMILIES) for t in YEARS]
    attach = [sum(fam_by_year[f][t] for f in ATTACH_FAMILIES) for t in YEARS]
    acr_total = [direct[t] + attach[t] for t in YEARS]

    # other costs --------------------------------------------------------------------------------------------------
    other = {k: [0.0] * 4 for k in COST_LABELS}
    review_hours = [0.0] * 4
    other["implementation"][0] = V["implementation_usd"] * V["impl_share_y0"]
    other["implementation"][1] = V["implementation_usd"] * (1.0 - V["impl_share_y0"])
    other["change_management"][0] = V["change_one_time_usd"] * V["change_share_y0"]
    other["change_management"][1] = V["change_one_time_usd"] * (1.0 - V["change_share_y0"])
    for t in (1, 2, 3):
        other["platform_licence"][t] = V["platform_licence_usd_per_year"] * licence_share[t]
        other["integration_run"][t] = V["implementation_usd"] * V["integration_run_pct"] * (0.5 if t == 1 else 1.0)
        other["change_management"][t] += V["change_run_usd_per_year"] * licence_share[t]
        other["rights_library"][t] = V["rights_library_usd_per_year"] * licence_share[t]
        ld = loads[t]
        mins = sum(ld["versions"][c] * V[f"review_min_{c}"] for c in CLASSES) * V["review_minutes_scale"]
        h_creative = mins / 60.0
        h_ling = ld["loc_versions"] * V["localized_review_minutes"] / 60.0
        h_exc = ld["volume"] * V["exception_rate"] * V["exception_minutes"] / 60.0
        other["review_creative_legal"][t] = h_creative * V["reviewer_rate_usd_per_hour"]
        other["review_linguist"][t] = h_ling * V["linguist_rate_usd_per_hour"]
        other["review_exceptions"][t] = h_exc * V["reviewer_rate_usd_per_hour"]
        review_hours[t] = h_creative + h_ling + h_exc
    other_core_total = [sum(other[k][t] for k in CORE_COSTS) for t in YEARS]
    for lv in LEVERS:
        e = exp[lv]
        for t in YEARS:
            other["expansion_integration"][t] += e["integration"][t]
            other["expansion_run"][t] += e["run"][t]
            other["expansion_review"][t] += e["review"][t]
            review_hours[t] += e["review_hours"][t]
    other_total = [sum(other[k][t] for k in other) for t in YEARS]
    cost_total = [acr_total[t] + other_total[t] for t in YEARS]
    cost_total_core = [acr_core[t] + other_core_total[t] for t in YEARS]

    # ROI ----------------------------------------------------------------------------------------------------------
    net = [ben_total[t] - cost_total[t] for t in YEARS]
    cum, run = [], 0.0
    for x in net:
        run += x
        cum.append(run)
    npv = sum(net[t] / (1.0 + r) ** t for t in YEARS)
    pv_benefit = sum(ben_total[t] / (1.0 + r) ** t for t in YEARS)
    pv_cost = sum(cost_total[t] / (1.0 + r) ** t for t in YEARS)
    tb, tc = sum(ben_total), sum(cost_total)
    return {
        "P": P, "ramp": ramp, "loads": loads, "vol_rows": vol_rows, "gross": gross, "conf": conf, "ben": ben, "ben_total": ben_total,
        "coverage": coverage, "repl": repl, "f_var": f_var, "fam_by_year": fam_by_year, "direct": direct, "attach": attach,
        "acr_total": acr_total, "other": other, "other_total": other_total, "review_hours": review_hours,
        "cost_total": cost_total, "net": net, "cum": cum, "npv": npv, "total_benefit": tb, "total_cost": tc,
        "pv_benefit": pv_benefit, "pv_cost": pv_cost,
        "roi_pct": (tb - tc) / tc * 100.0 if tc > 0 else None, "payback_months": _payback(net), "irr_pct": _irr(net),
        "pools": {"production": sum(prod_pool.values()), "fees": sum(fee_pool.values()), "localization": loc_pool,
                  "addressable_production": addr_prod, "addressable_fees": addr_fee, "by_class": prod_pool},
        "fixed_by_year": fixed_by_year, "variable_by_year": variable_by_year,
        "direct_core": direct_core, "attach_core": attach_core, "acr_core": acr_core, "cost_total_core": cost_total_core,
        "variable_core_by_year": variable_core_by_year, "fixed_core_by_year": fixed_core_by_year,
        "exp": exp, "exp_ramp": exp_ramp, "paid_media_total": paid_media_total,
    }


def _payback(net: List[float]) -> Optional[float]:
    cum = net[0]
    if cum >= 0:
        return 0.0
    for t in range(1, len(net)):
        before = cum
        cum += net[t]
        if cum >= 0 and net[t] > 0:
            return round(12.0 * (t - 1) + 12.0 * (-before / net[t]), 2)
    return None


def _irr(net: List[float]) -> Optional[float]:
    if net[0] >= 0 or sum(net[1:]) <= 0:
        return None
    def f(rate: float) -> float:
        return sum(x / (1.0 + rate) ** i for i, x in enumerate(net))
    lo, hi = -0.9, 20.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2.0 * 100.0, 4)


# ----------------------------------------------------------------------------------------------------------------------
# Sensitivity, tiers, portfolio, unit economics
# ----------------------------------------------------------------------------------------------------------------------

def _sensitivity(A: Dict[str, Any], V: Dict[str, Any], base_npv: float) -> List[Dict[str, Any]]:
    entries = A["assumptions"]
    overridden = set(V["_overrides"])
    rows = []
    for d in A["sensitivity_drivers"]:
        keys = d["keys"]
        if any(k in overridden for k in keys) or (d["id"] == "media" and "media_spend_in_scope_usd" in overridden):
            continue
        res = {}
        for end in ("low", "high"):
            vv = dict(V)
            for k in keys:
                vv[k] = float(entries[k][end])
            vv["media_spend_in_scope_usd"] = (vv["revenue_usd"] * vv["marketing_pct_revenue"] * vv["paid_media_pct_marketing"] * vv["media_scope_pct_paid"]
                                              if "media_scope_pct_paid" in keys else vv["media_spend_in_scope_usd"])
            res[end] = _core(A, vv)["npv"]
        rows.append({
            "id": d["id"], "label": d["label"], "keys": keys,
            "low": {k: float(entries[k]["low"]) for k in keys}, "high": {k: float(entries[k]["high"]) for k in keys},
            "npv_low": res["low"], "npv_high": res["high"], "swing": abs(res["high"] - res["low"]),
            "base_npv": base_npv,
        })
    rows.sort(key=lambda x: (-x["swing"], x["id"]))
    return rows


def _lever_acr(res: Dict[str, Any]) -> float:
    return sum(res["fam"].values()) + res["attach_security"]


def _lever_unit_economics(res: Dict[str, Dict[str, Any]], V: Dict[str, Any]) -> Dict[str, Any]:
    """Azure cost per generated video second, per catalog image and per personalised version (steady state, list price)."""
    out: Dict[str, Any] = {}
    e1 = res.get("e1")
    if e1 and e1["units"].get("generated_seconds", 0.0) > 0.0:
        u = e1["units"]
        total = sum(e1["fam"].values())
        out["generative_video"] = {
            "generated_seconds_per_year": u["generated_seconds"], "kept_seconds_per_year": u["kept_seconds"],
            "list_price_per_generated_second_usd": u["video_model_usd"] / u["generated_seconds"],
            "azure_cost_per_generated_second_usd": total / u["generated_seconds"],
            "generated_seconds_per_1m_usd_of_acr": 1e6 / (total / u["generated_seconds"]),
            "azure_cost_per_kept_second_usd": total / u["kept_seconds"],
            "azure_all_in_cost_per_kept_second_usd": (total + e1["attach_security"]) / u["kept_seconds"],
            "typical_adapted_insert_seconds": V["e1_adapted_gen_seconds"],
            "azure_cost_per_typical_adapted_insert_usd": total / u["kept_seconds"] * V["e1_adapted_gen_seconds"],
        }
    e2 = res.get("e2")
    if e2 and e2["units"].get("kept_images", 0.0) > 0.0:
        u = e2["units"]
        total = sum(e2["fam"].values())
        out["catalog_image"] = {
            "kept_images_per_year": u["kept_images"], "generated_images_per_year": u["generated_images"],
            "image_model_cost_per_generated_image_usd": u["image_model_usd"] / u["generated_images"],
            "azure_variable_cost_per_kept_image_usd": (total - e2["fixed"]) / u["kept_images"],
            "azure_all_in_cost_per_kept_image_usd": (total + e2["attach_security"]) / u["kept_images"],
            "avoided_baseline_cost_per_image_usd": V["e2_baseline_cost_per_image_usd"] * V["e2_displaced_share"],
        }
    e3 = res.get("e3")
    if e3 and e3["units"].get("versions", 0.0) > 0.0:
        u = e3["units"]
        total = sum(e3["fam"].values())
        out["personalized_version"] = {
            "personalized_versions_per_year": u["versions"],
            "azure_variable_cost_per_version_usd": (total - e3["fixed"]) / u["versions"],
            "azure_all_in_cost_per_version_usd": (total + e3["attach_security"]) / u["versions"],
        }
    e4 = res.get("e4")
    if e4 and e4["units"].get("capacity_units", 0.0) > 0.0:
        u = e4["units"]
        out["data_platform"] = {
            "fabric_capacity_units": u["capacity_units"], "onelake_tb": u["onelake_tb"],
            "azure_cost_per_year_usd": sum(e4["fam"].values()) + e4["attach_security"],
        }
    return out


def _tier_row(A: Dict[str, Any], V: Dict[str, Any], P: Dict[str, float], name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    ld = _load(V, cfg["annual_asset_volume"], cfg["markets"], cfg["users"], cfg["variants_per_campaign"])
    fp = A["footprints"][cfg["footprint"]]
    probe = _azure_year(V, P, ld, fp, 0.0, 0.0, 1.0, cfg["attach"])
    steady = _azure_year(V, P, ld, fp, probe["added_gb"], ld["campaigns"], 1.0, cfg["attach"])
    fam = dict(steady["by_family"])
    core_run = sum(fam[f] for f in DIRECT_FAMILIES) + sum(fam[f] for f in ATTACH_FAMILIES)
    fixed_total = steady["fixed_total"]
    lever_res: Dict[str, Dict[str, Any]] = {}
    Vt = V
    if cfg.get("levers"):
        Vt = dict(V)
        Vt.update(cfg.get("lever_params", {}))
        for lv in LEVERS:
            lever_res[lv] = _lever_azure(lv, Vt, P, fp, ld, float(cfg["levers"].get(lv, 0.0)))
            for f in DIRECT_FAMILIES:
                fam[f] += lever_res[lv]["fam"][f]
            fam["attach_security_network"] += lever_res[lv]["attach_security"]
            fixed_total += lever_res[lv]["fixed"]
    direct = sum(fam[f] for f in DIRECT_FAMILIES)
    att = sum(fam[f] for f in ATTACH_FAMILIES)
    row = {
        "tier": name, "label": cfg["label"], "description": cfg["description"],
        "versions_per_year": cfg["annual_asset_volume"], "markets": cfg["markets"], "users": cfg["users"],
        "variants_per_campaign": cfg["variants_per_campaign"], "footprint": cfg["footprint"],
        "acr_run_rate_usd": direct + att, "direct_usd": direct, "attach_usd": att,
        "by_family": {f: fam[f] for f in FAMILIES},
        "azure_cost_per_version_usd": (direct + att) / max(cfg["annual_asset_volume"], 1.0),
        "fixed_share_pct": fixed_total / max(direct, 1e-9) * 100.0,
    }
    if lever_res:
        row["expansion"] = {
            "core_run_rate_usd": core_run,
            "levers_scale": {lv: float(cfg["levers"].get(lv, 0.0)) for lv in LEVERS},
            "lever_params": dict(cfg.get("lever_params", {})),
            "by_lever_usd": {lv: _lever_acr(lever_res[lv]) for lv in LEVERS},
            "by_lever_family": {lv: {f: lever_res[lv]["fam"][f] for f in DIRECT_FAMILIES} for lv in LEVERS},
            "units": {lv: dict(lever_res[lv]["units"]) for lv in LEVERS},
            "unit_economics": _lever_unit_economics(lever_res, Vt),
        }
    return row


def _tier_results(A: Dict[str, Any], V: Dict[str, Any], P: Dict[str, float]) -> List[Dict[str, Any]]:
    return [_tier_row(A, V, P, name, A["tiers"][name]) for name in TIERS]


def _lever_summary(e: Dict[str, Any]) -> Dict[str, Any]:
    benefit, azure = sum(e["net"]), sum(e["azure"])
    by_family = {f: list(e["fam"][f]) for f in DIRECT_FAMILIES if any(e["fam"][f])}
    by_family["attach_security_network"] = list(e["attach_security"])
    return {
        "scale": e["scale"], "year_scale": e["year_scale"],
        "acr_by_year": e["azure"], "acr_year3": e["azure"][3], "acr_by_family": by_family,
        "acr_fixed_by_year": e["fixed"], "acr_variable_by_year": e["variable"],
        "benefit_gross_by_year": e["gross"], "benefit_net_by_year": e["net"], "benefit_year3": e["net"][3],
        "benefit_gross_components_by_year": e["gross_by_component"],
        "non_azure_cost_by_year": {"integration": e["integration"], "run": e["run"], "review": e["review"]},
        "review_hours_by_year": e["review_hours"],
        "net_flow_by_year": e["flows"], "npv": e["npv"], "payback_months": e["payback_months"],
        "benefit_per_azure_dollar": benefit / azure if azure > 0 else None,
        "units_by_year": e["units"],
    }


def _portfolio(A: Dict[str, Any], V: Dict[str, Any], tiers: List[Dict[str, Any]]) -> Dict[str, Any]:
    run = {t["tier"]: t["acr_run_rate_usd"] for t in tiers}
    cohort = [V["cohort_ramp_age1"], V["cohort_ramp_age2"], V["cohort_ramp_age3"]]
    new = {t: [V[f"new_{t}_y{y}"] for y in (1, 2, 3)] for t in TIERS}
    active, acr_by = {}, {}
    for t in TIERS:
        act, vals = [], []
        for y in (1, 2, 3):
            if t == "pilot":
                n, v = new[t][y - 1], new[t][y - 1] * run[t]
            else:
                n = sum(new[t][k] for k in range(y))
                v = sum(new[t][k] * cohort[y - 1 - k] * run[t] for k in range(y))
            act.append(n)
            vals.append(v)
        active[t], acr_by[t] = act, vals
    total = [0.0] + [sum(acr_by[t][y] for t in TIERS) for y in range(3)]
    return {
        "new_customers_by_tier": new, "active_customers_by_tier": active, "acr_by_tier_by_year": {t: [0.0] + v for t, v in acr_by.items()},
        "total_by_year": total, "cumulative_3yr": sum(total), "cohort_ramp": cohort,
        "note": "Illustrative sales-motion assumptions (not a forecast or a commitment): pilots last 12 months and convert into the one-brand tier counts.",
    }


def _tam(V: Dict[str, Any], tiers: List[Dict[str, Any]], expanded_run: float) -> Dict[str, Any]:
    run = {t["tier"]: t["acr_run_rate_usd"] for t in tiers}
    accounts = V["tam_target_accounts"]
    one = accounts * V["tam_share_one_brand"]
    glob = accounts - one
    ceiling = one * run["one_brand"] + glob * run["global_portfolio"] + V["tam_agency_networks"] * run["agency_network"]
    ent_n = min(V["tam_enterprise_scale_accounts"], glob)
    expanding = (glob - ent_n) * V["tam_expansion_share"]
    uplift_ref = expanded_run - run["global_portfolio"]
    uplift_ent = run["enterprise_scale"] - run["global_portfolio"]
    uplift = expanding * uplift_ref + ent_n * uplift_ent
    return {
        "target_accounts": accounts, "accounts_one_brand_tier": one, "accounts_global_portfolio_tier": glob,
        "agency_networks": V["tam_agency_networks"], "annual_acr_ceiling_usd": ceiling,
        "penetration": V["tam_penetration_mid"], "annual_acr_at_penetration_usd": ceiling * V["tam_penetration_mid"],
        "note": "Directional ceiling = target accounts x steady-state tier run-rate; assumption-driven (account counts are not sourced), not a forecast.",
        "expansion": {
            "enterprise_scale_accounts": ent_n, "uplift_per_enterprise_scale_account_usd": uplift_ent,
            "share_of_other_global_portfolio_accounts_expanding": V["tam_expansion_share"], "accounts_expanding": expanding,
            "uplift_per_expanding_account_usd": uplift_ref, "annual_acr_uplift_usd": uplift,
            "annual_acr_ceiling_with_expansion_usd": ceiling + uplift,
            "annual_acr_with_expansion_at_penetration_usd": (ceiling + uplift) * V["tam_penetration_mid"],
            "note": "Enterprise-scale accounts run at the enterprise-scale tier instead of the global-portfolio tier; a share of the remaining global-portfolio accounts adds E1-E4 at the reference customer's own scale. Assumption-driven, not a forecast.",
        },
    }


def _marginal_variable(A, V, P, cls: str) -> Dict[str, float]:
    n = 10_000.0
    ver_mix = dict(V)
    for c in CLASSES:
        ver_mix[f"mix_studio_{c}"] = 1.0 if c == cls else 0.0
    ld = _load(ver_mix, n, V["markets"], 0.0, V["variants_per_campaign"])
    fp = A["footprints"]["global_portfolio"]
    res = _azure_year(ver_mix, P, ld, fp, 0.0, 0.0, 0.0, {"dam_tb": 0.0, "fabric_cu": 0.0})
    zero = _load(ver_mix, 0.0, V["markets"], 0.0, V["variants_per_campaign"])
    base = _azure_year(ver_mix, P, zero, fp, 0.0, 0.0, 0.0, {"dam_tb": 0.0, "fabric_cu": 0.0})
    return {"azure_variable_per_version": (res["variable_total"] - base["variable_total"]) / n}


def _unit_economics(A, V, core) -> Dict[str, Any]:
    P = core["P"]
    ld = core["loads"][3]
    v3 = max(ld["volume"], 1.0)
    by_class = {}
    for c in CLASSES:
        agency = V[f"baseline_cost_{c}"] * (1.0 + V["agency_fee_pct_of_production"]) * (1.0 + V["rework_pct_of_first_pass"])
        addr = V[f"addressable_{c}"]
        azure_var = _marginal_variable(A, V, P, c)["azure_variable_per_version"]
        review = V[f"review_min_{c}"] * V["review_minutes_scale"] / 60.0 * V["reviewer_rate_usd_per_hour"]
        residual = V[f"baseline_cost_{c}"] * (1.0 - addr) * (1.0 + V["agency_fee_pct_of_production"] * (1.0 - V["agency_fee_reduction_pct"] * addr))
        all_in = residual + azure_var + review
        by_class[c] = {
            "label": CLASS_LABELS[c], "agency_cost_per_asset": agency, "residual_external_cost": residual,
            "azure_variable_cost": azure_var, "human_review_cost": review, "studio_all_in_cost_displaced_asset": all_in,
            "saving_pct": (1.0 - all_in / agency) * 100.0 if agency > 0 else None,
            "incremental_version_marginal_cost": azure_var + review,
        }
    pool = core["pools"]
    blended_agency = (pool["production"] * (1.0 + V["agency_fee_pct_of_production"]) * (1.0 + V["rework_pct_of_first_pass"]) + pool["localization"]) / max(V["baseline_assets_per_year"], 1.0)
    return {
        "year": 3, "versions": v3,
        "azure_direct_cost_per_version": core["direct_core"][3] / v3,
        "azure_total_incl_pull_through_per_version": core["acr_core"][3] / v3,
        "azure_variable_cost_per_version": core["variable_core_by_year"][3] / v3,
        "studio_all_in_cost_per_version": core["cost_total_core"][3] / v3,
        "agency_blended_cost_per_baseline_asset": blended_agency,
        "by_class": by_class,
        "note": "Azure cost per approved version = bottom-up list-price consumption divided by approved versions; agency cost = production + agency fees + rework + localisation pool divided by today's asset count. Campaign-scale studio only: expansion levers E1-E4 are reported separately (acr.expansion).",
    }


def _by_lever(core: Dict[str, Any]) -> Dict[str, List[float]]:
    out = {"core": list(core["acr_core"])}
    for lv in LEVERS:
        out[lv] = list(core["exp"][lv]["azure"])
    return out


def _full_case(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "acr_by_year": c["acr_total"], "run_rate_year3": c["acr_total"][3], "by_lever": _by_lever(c),
        "levers": {lv: _lever_summary(c["exp"][lv]) for lv in LEVERS},
        "benefit_total_by_year": c["ben_total"], "cost_total_by_year": c["cost_total"],
        "total_benefit": c["total_benefit"], "total_cost": c["total_cost"], "npv": c["npv"], "roi_pct": c["roi_pct"],
        "payback_months": c["payback_months"], "irr_pct": c["irr_pct"],
        "azure_share_of_benefit_pct": sum(c["acr_total"]) / c["total_benefit"] * 100.0 if c["total_benefit"] else None,
    }


def _path_steps(start: Dict[str, Any], end: Dict[str, Any], with_breadth: bool) -> List[Dict[str, Any]]:
    run0 = start["acr_run_rate_usd"]
    ex = end["expansion"]
    steps = [{"id": start["tier"], "label": start["label"], "kind": "total", "acr_usd": run0, "cumulative_usd": run0}]
    cum = run0
    if with_breadth:
        breadth = ex["core_run_rate_usd"] - run0
        cum += breadth
        steps.append({"id": "breadth", "kind": "delta", "acr_usd": breadth, "cumulative_usd": cum,
                      "label": f"Enterprise breadth: {end['versions_per_year']:,.0f} versions, {end['markets']:.0f} markets, {end['users']:,.0f} users"})
    for lv in LEVERS:
        x = ex["by_lever_usd"][lv]
        cum += x
        steps.append({"id": lv, "label": LEVER_LABELS[lv], "kind": "delta", "acr_usd": x, "cumulative_usd": cum})
    steps.append({"id": end["tier"], "label": end["label"], "kind": "total", "acr_usd": end["acr_run_rate_usd"], "cumulative_usd": end["acr_run_rate_usd"]})
    return steps


def _reference_expanded(A: Dict[str, Any], V: Dict[str, Any], P: Dict[str, float]) -> Dict[str, Any]:
    cfg = dict(A["tiers"]["global_portfolio"])
    cfg.update({"label": "Global portfolio + E1-E4 at full scale (reference customer, steady state)", "levers": {lv: 1.0 for lv in LEVERS}})
    return _tier_row(A, V, P, "global_portfolio_expanded", cfg)


def _expansion_block(A: Dict[str, Any], V: Dict[str, Any], core: Dict[str, Any],
                     tiers: List[Dict[str, Any]], full: Dict[str, Any], off: Dict[str, Any], ref_row: Dict[str, Any]) -> Dict[str, Any]:
    cfg = A.get("expansion", {})
    lv_cfg = cfg.get("levers", {})
    tier = {t["tier"]: t for t in tiers}
    levers = {}
    for lv in LEVERS:
        d = _lever_summary(core["exp"][lv])
        d.update({"label": LEVER_LABELS[lv], "roadmap": lv_cfg.get(lv, {}).get("roadmap"), "description": lv_cfg.get(lv, {}).get("description")})
        levers[lv] = d
    items = A["pricing"]["items"]
    price_ref = [{"key": r["key"], "role": r["role"], "product": items[r["key"]]["product"], "meter": items[r["key"]]["meter"],
                  "region": items[r["key"]]["region"], "list_price_usd_per_second": items[r["key"]]["price"], "availability": r["availability"]}
                 for r in cfg.get("video_price_reference", [])]
    fc = _full_case(full)
    fc["incremental_vs_this_scenario"] = {
        "acr_year3_usd": full["acr_total"][3] - core["acr_total"][3], "acr_3yr_usd": sum(full["acr_total"]) - sum(core["acr_total"]),
        "npv_usd": full["npv"] - core["npv"], "benefit_3yr_usd": full["total_benefit"] - core["total_benefit"],
        "cost_3yr_usd": full["total_cost"] - core["total_cost"],
    }
    lo = _full_case(off)
    lo["incremental_of_levers_in_this_scenario"] = {
        "acr_year3_usd": core["acr_total"][3] - off["acr_total"][3], "acr_3yr_usd": sum(core["acr_total"]) - sum(off["acr_total"]),
        "npv_usd": core["npv"] - off["npv"], "benefit_3yr_usd": core["total_benefit"] - off["total_benefit"],
        "cost_3yr_usd": core["total_cost"] - off["total_cost"],
    }
    return {
        "scales": {lv: V[f"{lv}_scale"] for lv in LEVERS}, "ramp_by_year": core["exp_ramp"], "levers": levers,
        "full_expansion_case": fc, "levers_off_case": lo,
        "enterprise_path": _path_steps(tier["global_portfolio"], tier["enterprise_scale"], True),
        "reference_customer_path": _path_steps(tier["global_portfolio"], ref_row, False),
        "reference_customer_expanded_tier": ref_row,
        "enterprise_run_rate_usd": tier["enterprise_scale"]["acr_run_rate_usd"],
        "enterprise_unit_economics": tier["enterprise_scale"]["expansion"]["unit_economics"],
        "video_price_reference": price_ref,
        "notes": cfg.get("notes", []),
    }


# ----------------------------------------------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------------------------------------------

def _r(x: Any) -> Any:
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, float):
        return round(x, 2) if abs(x) >= 100 else round(x, 6)
    if isinstance(x, list):
        return [_r(i) for i in x]
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    return x


def compute(assumptions: Dict[str, Any], scenario: str = "base", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    scenario = _norm_scenario(scenario)
    V = _resolve(assumptions, scenario, overrides)
    core = _core(assumptions, V)
    tiers = _tier_results(assumptions, V, core["P"])
    sens = _sensitivity(assumptions, V, core["npv"])
    full = _core(assumptions, {**V, **{f"{lv}_scale": 1.0 for lv in LEVERS}})
    off = _core(assumptions, {**V, **{f"{lv}_scale": 0.0 for lv in LEVERS}})
    ref_row = _reference_expanded(assumptions, V, core["P"])
    expansion = _expansion_block(assumptions, V, core, tiers, full, off, ref_row)
    cust = assumptions["customer"]
    families_y = core["fam_by_year"]
    exp_units = {lv: core["exp"][lv]["units"] for lv in LEVERS}
    zeros = [0.0] * 4
    resolved = {k: v for k, v in V.items() if not k.startswith("_")}
    result = {
        "scenario": scenario, "scenario_label": SCENARIO_LABELS[scenario], "currency": assumptions["meta"]["currency"],
        "horizon_years": 3, "years": list(YEARS),
        "customer": {"name": cust["name"], "description": cust["description"], "revenue_usd": V["revenue_usd"],
                     "marketing_spend_usd": V["revenue_usd"] * V["marketing_pct_revenue"],
                     "paid_media_usd": V["revenue_usd"] * V["marketing_pct_revenue"] * V["paid_media_pct_marketing"],
                     "media_spend_in_scope_usd": V["media_spend_in_scope_usd"], "markets": V["markets"],
                     "baseline_assets_per_year": V["baseline_assets_per_year"], "annual_asset_volume_full_adoption": V["annual_asset_volume"]},
        "inputs": {"resolved": resolved, "overrides": V["_overrides"], "adoption_ramp": core["ramp"][1:],
                   "coverage_by_year": core["coverage"], "replacement_share_by_year": core["repl"],
                   "variant_uplift_factor": core["f_var"], "baseline_pools_usd": core["pools"],
                   "expansion": {"lever_scale": {lv: V[f"{lv}_scale"] for lv in LEVERS}, "ramp": core["exp_ramp"][1:],
                                 "paid_media_total_usd": core["paid_media_total"]}},
        "volumes": {"approved_versions_by_year": core["vol_rows"]["versions"], "campaigns_by_year": core["vol_rows"]["campaigns"],
                    "active_users_by_year": core["vol_rows"]["users"], "localized_versions_by_year": core["vol_rows"]["localized_versions"],
                    "video_versions_by_year": core["vol_rows"]["video_versions"], "review_hours_by_year": core["review_hours"],
                    "expansion": {"generated_video_seconds_by_year": exp_units["e1"].get("generated_seconds", zeros),
                                  "kept_video_seconds_by_year": exp_units["e1"].get("kept_seconds", zeros),
                                  "catalog_images_by_year": exp_units["e2"].get("kept_images", zeros),
                                  "personalized_versions_by_year": exp_units["e3"].get("versions", zeros)}},
        "benefits": {
            "by_category": core["ben"], "total_by_year": core["ben_total"], "total": sum(core["ben_total"]),
            "detail": {k: {"label": BENEFIT_LABELS[k], "gross_by_year": core["gross"][k], "confidence": core["conf"][k], "net_by_year": core["ben"][k]} for k in BENEFIT_LABELS},
            "labels": BENEFIT_LABELS,
        },
        "costs": {
            "azure_by_family": {f: families_y[f] for f in FAMILIES}, "azure_total_by_year": core["acr_total"],
            "other_by_category": core["other"], "other_total_by_year": core["other_total"],
            "total_by_year": core["cost_total"], "total": sum(core["cost_total"]),
            "labels": {**COST_LABELS, **FAMILY_LABELS},
        },
        "roi": {
            "net_benefit_by_year": core["net"], "cumulative": core["cum"], "npv": core["npv"], "discount_rate": V["discount_rate"],
            "roi_pct": core["roi_pct"], "payback_months": core["payback_months"], "irr_pct": core["irr_pct"],
            "benefit_cost_ratio": core["total_benefit"] / core["total_cost"] if core["total_cost"] else None,
            "total_benefit": core["total_benefit"], "total_cost": core["total_cost"],
            "pv_benefit": core["pv_benefit"], "pv_cost": core["pv_cost"],
            "breakeven_benefit_haircut_pct": (1.0 - core["pv_cost"] / core["pv_benefit"]) * 100.0 if core["pv_benefit"] > 0 else None,
            "azure_share_of_cost_pct": sum(core["acr_total"]) / core["total_cost"] * 100.0 if core["total_cost"] else None,
            "azure_share_of_benefit_pct": sum(core["acr_total"]) / core["total_benefit"] * 100.0 if core["total_benefit"] else None,
        },
        "acr": {
            "by_year": core["acr_total"], "direct_by_year": core["direct"], "attach_by_year": core["attach"],
            "by_family": {f: families_y[f] for f in FAMILIES}, "by_family_total": {f: sum(families_y[f]) for f in FAMILIES},
            "family_labels": FAMILY_LABELS, "run_rate_year3": core["acr_total"][3],
            "tiers": tiers, "pull_through_ratio": core["attach"][3] / core["direct"][3] if core["direct"][3] else None,
            "fixed_platform_by_year": core["fixed_by_year"], "variable_consumption_by_year": core["variable_by_year"],
            "portfolio": _portfolio(assumptions, V, tiers), "tam": _tam(V, tiers, ref_row["acr_run_rate_usd"]),
            "by_lever": _by_lever(core),
            "by_lever_labels": {"core": "Campaign studio (Release 1 scope)", **LEVER_LABELS},
            "expansion": expansion,
            "pricing_basis": {"source": assumptions["pricing"]["meta"]["api"], "retrieved_at": assumptions["pricing"]["meta"]["retrieved_at"],
                              "billing": assumptions["pricing"]["meta"]["billing"], "region": assumptions["pricing"]["meta"]["region"],
                              "currency": assumptions["pricing"]["meta"]["currency"]},
        },
        "unit_economics": _unit_economics(assumptions, V, core),
        "sensitivity": sens,
    }
    return _r(result)


def compute_all(assumptions: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = {s: compute(assumptions, s) for s in SCENARIOS}
    summary = {}
    for s, r in scenarios.items():
        summary[s] = {"npv": r["roi"]["npv"], "roi_pct": r["roi"]["roi_pct"], "payback_months": r["roi"]["payback_months"],
                      "irr_pct": r["roi"]["irr_pct"], "total_benefit": r["benefits"]["total"], "total_cost": r["costs"]["total"],
                      "acr_by_year": r["acr"]["by_year"], "acr_run_rate_year3": r["acr"]["run_rate_year3"],
                      "portfolio_acr_by_year": r["acr"]["portfolio"]["total_by_year"],
                      "acr_by_lever_year3": {k: v[3] for k, v in r["acr"]["by_lever"].items()},
                      "full_expansion_acr_by_year": r["acr"]["expansion"]["full_expansion_case"]["acr_by_year"],
                      "full_expansion_npv": r["acr"]["expansion"]["full_expansion_case"]["npv"],
                      "enterprise_tier_acr_run_rate_usd": r["acr"]["expansion"]["enterprise_run_rate_usd"]}
    return {
        "meta": {"model_version": MODEL_VERSION, "customer": assumptions["customer"]["name"], "currency": assumptions["meta"]["currency"],
                 "assumptions_sha256": assumptions_hash(assumptions), "pricing_retrieved_at": assumptions["pricing"]["meta"]["retrieved_at"],
                 "reference_scenario": "base", "summary": summary},
        "scenarios": scenarios,
    }


# ----------------------------------------------------------------------------------------------------------------------
# Markdown report
# ----------------------------------------------------------------------------------------------------------------------

def _usd(x: Optional[float], digits: int = 0) -> str:
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e6:
        return f"{sign}${x / 1e6:,.{max(digits, 2)}f}M"
    if x >= 1e3:
        return f"{sign}${x / 1e3:,.{digits}f}k"
    return f"{sign}${x:,.{digits}f}"


def render_markdown(outputs: Dict[str, Any], assumptions: Dict[str, Any]) -> str:
    base = outputs["scenarios"]["base"]
    meta = outputs["meta"]
    L: List[str] = []
    w = L.append
    w("# Business case outputs — SwarmAI Commercial Studio (Spotlight)\n")
    w(f"Reference customer: **{meta['customer']}** · currency {meta['currency']} · 3-year horizon (Year 0 = implementation) · "
      f"pricing: Azure Retail Prices API, retrieved {meta['pricing_retrieved_at']} · model v{meta['model_version']} · assumptions sha256 `{meta['assumptions_sha256'][:12]}…`\n")
    w("> Generated by `python model.py` — do not edit by hand. Illustrative and assumption-driven: validate every driver with customer data.\n")
    w("## Scenario summary\n")
    w("| Metric | Conservative | Base | Upside |\n|---|---:|---:|---:|")
    s = meta["summary"]
    def row(label, fn):
        w(f"| {label} | " + " | ".join(fn(s[k]) for k in SCENARIOS) + " |")
    row("3-year NPV", lambda x: _usd(x["npv"]))
    row("ROI (3-year, undiscounted)", lambda x: f"{x['roi_pct']:.0f} %")
    row("Payback (months from Year 0)", lambda x: "n/a" if x["payback_months"] is None else f"{x['payback_months']:.1f}")
    row("IRR", lambda x: "n/a" if x["irr_pct"] is None else f"{x['irr_pct']:.0f} %")
    row("Total benefit (3 yr)", lambda x: _usd(x["total_benefit"]))
    row("Total cost (3 yr)", lambda x: _usd(x["total_cost"]))
    row("Azure ACR Year 1 / 2 / 3 (this customer)", lambda x: " / ".join(_usd(v) for v in x["acr_by_year"][1:]))
    row("Portfolio ACR Year 3 (illustrative pipeline)", lambda x: _usd(x["portfolio_acr_by_year"][3]))
    row("ACR Year 3 with expansion levers E1-E4 at full scale (this customer)", lambda x: _usd(x["full_expansion_acr_by_year"][3]))
    row("Enterprise-scale tier ACR run-rate (steady state)", lambda x: _usd(x["enterprise_tier_acr_run_rate_usd"]))
    w("")
    for name in ("base",):
        r = outputs["scenarios"][name]
        w(f"## {r['scenario_label']} scenario — benefits by category (US$)\n")
        w("| Category | Confidence | Y1 | Y2 | Y3 | 3-yr total |\n|---|---:|---:|---:|---:|---:|")
        for k, d in r["benefits"]["detail"].items():
            ne = d["net_by_year"]
            w(f"| {d['label']} | {d['confidence']:.0%} | {_usd(ne[1])} | {_usd(ne[2])} | {_usd(ne[3])} | {_usd(sum(ne))} |")
        tb = r["benefits"]["total_by_year"]
        w(f"| **Total benefit** | | **{_usd(tb[1])}** | **{_usd(tb[2])}** | **{_usd(tb[3])}** | **{_usd(sum(tb))}** |\n")
        w("### Costs (US$)\n")
        w("| Cost line | Y0 | Y1 | Y2 | Y3 | 3-yr total |\n|---|---:|---:|---:|---:|---:|")
        for k, v in r["costs"]["other_by_category"].items():
            w(f"| {COST_LABELS[k]} | {_usd(v[0])} | {_usd(v[1])} | {_usd(v[2])} | {_usd(v[3])} | {_usd(sum(v))} |")
        az = r["costs"]["azure_total_by_year"]
        w(f"| Azure run cost (= ACR, list price) | {_usd(az[0])} | {_usd(az[1])} | {_usd(az[2])} | {_usd(az[3])} | {_usd(sum(az))} |")
        ct = r["costs"]["total_by_year"]
        w(f"| **Total cost** | **{_usd(ct[0])}** | **{_usd(ct[1])}** | **{_usd(ct[2])}** | **{_usd(ct[3])}** | **{_usd(sum(ct))}** |\n")
        ro = r["roi"]
        w("### ROI\n")
        w("| | Y0 | Y1 | Y2 | Y3 |\n|---|---:|---:|---:|---:|")
        w("| Net benefit | " + " | ".join(_usd(x) for x in ro["net_benefit_by_year"]) + " |")
        w("| Cumulative | " + " | ".join(_usd(x) for x in ro["cumulative"]) + " |")
        w(f"\nNPV @ {ro['discount_rate']:.0%}: **{_usd(ro['npv'])}** · ROI **{ro['roi_pct']:.0f} %** · payback **{ro['payback_months']} months** · IRR **{ro['irr_pct']:.0f} %** · "
          f"Azure = {ro['azure_share_of_cost_pct']:.1f} % of cost and {ro['azure_share_of_benefit_pct']:.1f} % of benefit.\n")
        w("### Azure Consumed Revenue by service family (US$, list price, PAYG)\n")
        w("| Family | Y1 | Y2 | Y3 | 3-yr total |\n|---|---:|---:|---:|---:|")
        for f in FAMILIES:
            v = r["acr"]["by_family"][f]
            w(f"| {FAMILY_LABELS[f]} | {_usd(v[1])} | {_usd(v[2])} | {_usd(v[3])} | {_usd(sum(v))} |")
        a = r["acr"]["by_year"]
        w(f"| **Total ACR** | **{_usd(a[1])}** | **{_usd(a[2])}** | **{_usd(a[3])}** | **{_usd(sum(a))}** |")
        w(f"\nPull-through ratio (Year 3, attach ÷ direct): **{r['acr']['pull_through_ratio']:.2f}** · fixed platform share of direct Year-3 ACR: "
          f"**{r['acr']['fixed_platform_by_year'][3] / max(r['acr']['direct_by_year'][3], 1) * 100:.0f} %**\n")
        w("### ACR run-rate by customer tier (annual, steady state)\n")
        w("| Tier | Versions / yr | Users | ACR run-rate | of which attach | Azure cost / version |\n|---|---:|---:|---:|---:|---:|")
        for t in r["acr"]["tiers"]:
            w(f"| {t['label']} | {t['versions_per_year']:,.0f} | {t['users']:,.0f} | {_usd(t['acr_run_rate_usd'])} | {_usd(t['attach_usd'])} | ${t['azure_cost_per_version_usd']:,.2f} |")
        pf = r["acr"]["portfolio"]
        w("\n### Illustrative partner pipeline (not a forecast)\n")
        w("| Tier | New customers Y1/Y2/Y3 | ACR Y1 | ACR Y2 | ACR Y3 |\n|---|---|---:|---:|---:|")
        for t in TIERS:
            nn = pf["new_customers_by_tier"][t]
            ac = pf["acr_by_tier_by_year"][t]
            w(f"| {assumptions['tiers'][t]['label']} | {nn[0]:g} / {nn[1]:g} / {nn[2]:g} | {_usd(ac[1])} | {_usd(ac[2])} | {_usd(ac[3])} |")
        pt = pf["total_by_year"]
        w(f"| **Total** | | **{_usd(pt[1])}** | **{_usd(pt[2])}** | **{_usd(pt[3])}** |\n")
        tm = r["acr"]["tam"]
        w(f"Directional ceiling (not a forecast): {tm['target_accounts']:,.0f} target accounts ({tm['accounts_one_brand_tier']:,.0f} at one-brand scale, {tm['accounts_global_portfolio_tier']:,.0f} at global-portfolio scale) "
          f"+ {tm['agency_networks']:,.0f} agency networks = **{_usd(tm['annual_acr_ceiling_usd'])}** annual ACR at full penetration; at {tm['penetration']:.0%} penetration **{_usd(tm['annual_acr_at_penetration_usd'])}** a year.\n")
        te = tm["expansion"]
        w(f"With expansion levers (assumption-driven): {te['enterprise_scale_accounts']:,.0f} enterprise-scale accounts (+{_usd(te['uplift_per_enterprise_scale_account_usd'])} each) and "
          f"{te['accounts_expanding']:,.0f} global-portfolio accounts adding E1-E4 (+{_usd(te['uplift_per_expanding_account_usd'])} each) lift the ceiling to **{_usd(te['annual_acr_ceiling_with_expansion_usd'])}** "
          f"(**{_usd(te['annual_acr_with_expansion_at_penetration_usd'])}** at {tm['penetration']:.0%} penetration).\n")
        ex = r["acr"]["expansion"]
        fc = ex["full_expansion_case"]
        lab = r["acr"]["by_lever_labels"]
        w("### Expansion levers E1-E4 (optional, Release 2+; off in Conservative and Base, on in Upside)\n")
        w("Each lever carries its own Azure consumption, customer benefit and non-Azure cost. Everything below is this scenario's drivers with all four levers at **full scale**.\n")
        w("| Source of ACR (US$, list price) | Y1 | Y2 | Y3 |\n|---|---:|---:|---:|")
        for k, v in fc["by_lever"].items():
            w(f"| {lab[k]} | {_usd(v[1])} | {_usd(v[2])} | {_usd(v[3])} |")
        fa = fc["acr_by_year"]
        w(f"| **Total ACR with expansion** | **{_usd(fa[1])}** | **{_usd(fa[2])}** | **{_usd(fa[3])}** |\n")
        w("| Lever (full scale) | Benefit Y3 | Non-Azure cost Y3 | Azure ACR Y3 | Lever 3-yr NPV | Payback (months) | Benefit per Azure $ |\n|---|---:|---:|---:|---:|---:|---:|")
        for lv, d in fc["levers"].items():
            oc = sum(v[3] for v in d["non_azure_cost_by_year"].values())
            pb = "beyond 3 years" if d["payback_months"] is None else ("immediate (never negative)" if d["payback_months"] == 0.0 else f"{d['payback_months']:.1f}")
            bpa = "n/a" if d["benefit_per_azure_dollar"] is None else f"{d['benefit_per_azure_dollar']:.1f}x"
            w(f"| {LEVER_LABELS[lv]} | {_usd(d['benefit_year3'])} | {_usd(oc)} | {_usd(d['acr_year3'])} | {_usd(d['npv'])} | {pb} | {bpa} |")
        inc = fc["incremental_vs_this_scenario"]
        w(f"\nFull-expansion case: NPV **{_usd(fc['npv'])}**, ROI **{fc['roi_pct']:.0f} %**, payback **{fc['payback_months']} months**, Azure = {fc['azure_share_of_benefit_pct']:.1f} % of benefit "
          f"(vs this scenario: ACR Year 3 {_usd(inc['acr_year3_usd'])}, 3-year ACR {_usd(inc['acr_3yr_usd'])}, NPV {_usd(inc['npv_usd'])}).\n")
        lo = ex["levers_off_case"]
        w(f"Same scenario with every lever off: NPV **{_usd(lo['npv'])}**, ROI **{lo['roi_pct']:.0f} %**, payback **{lo['payback_months']} months**, IRR **{lo['irr_pct']:.0f} %**, "
          f"ACR Year 1 / 2 / 3 **{' / '.join(_usd(v) for v in lo['acr_by_year'][1:])}**; the levers switched on in this scenario change ACR Year 3 by {_usd(lo['incremental_of_levers_in_this_scenario']['acr_year3_usd'])} "
          f"and NPV by {_usd(lo['incremental_of_levers_in_this_scenario']['npv_usd'])}.\n")
        w("#### Path from campaign scale to enterprise scale (steady-state annual ACR)\n")
        w("| Step | ACR step (US$ / yr) | Running total |\n|---|---:|---:|")
        for s_ in ex["enterprise_path"]:
            mark = "**" if s_["kind"] == "total" else ""
            w(f"| {mark}{s_['label']}{mark} | {mark}{_usd(s_['acr_usd'])}{mark} | {_usd(s_['cumulative_usd'])} |")
        w("")
        eu = ex["enterprise_unit_economics"]
        w("#### Unit economics at enterprise scale (Azure list price, PAYG)\n")
        w("| Unit | Azure cost | Note |\n|---|---:|---|")
        if "generative_video" in eu:
            g = eu["generative_video"]
            w(f"| Generated video second (list price, blended tiers) | ${g['list_price_per_generated_second_usd']:,.3f} | billed per generated second, rejected takes included |")
            w(f"| Kept video second (all takes, Guardian, safety, storage) | ${g['azure_cost_per_kept_second_usd']:,.3f} | {g['kept_seconds_per_year']:,.0f} kept seconds a year |")
            w(f"| Typical {g['typical_adapted_insert_seconds']:.0f}-second generated insert | ${g['azure_cost_per_typical_adapted_insert_usd']:,.2f} | inside an adapted video |")
        if "catalog_image" in eu:
            g = eu["catalog_image"]
            w(f"| Generated catalog image candidate (model only) | ${g['image_model_cost_per_generated_image_usd']:,.3f} | gpt-image-1.5, medium / high quality mix |")
            w(f"| Kept catalog image (variable / all-in) | ${g['azure_variable_cost_per_kept_image_usd']:,.3f} / ${g['azure_all_in_cost_per_kept_image_usd']:,.3f} | vs ${g['avoided_baseline_cost_per_image_usd']:,.2f} of avoided photography and retouching cost |")
        if "personalized_version" in eu:
            g = eu["personalized_version"]
            w(f"| Personalised version (variable / all-in) | ${g['azure_variable_cost_per_version_usd']:,.3f} / ${g['azure_all_in_cost_per_version_usd']:,.3f} | {g['personalized_versions_per_year']:,.0f} versions a year |")
        if "data_platform" in eu:
            g = eu["data_platform"]
            w(f"| Marketing data platform (Fabric F{g['fabric_capacity_units']:.0f}, {g['onelake_tb']:.0f} TB OneLake) | {_usd(g['azure_cost_per_year_usd'])} a year | capacity + storage + governance |")
        w("\n#### Generative-video list prices (Azure Retail Prices API, swedencentral, per second)\n")
        w("| Meter | Price | Role | Availability |\n|---|---:|---|---|")
        for p_ in ex["video_price_reference"]:
            w(f"| {p_['product']} / {p_['meter']} | ${p_['list_price_usd_per_second']:.3f} | {p_['role']} | {p_['availability']} |")
        w("")
        for n_ in ex["notes"]:
            w(f"* {n_}")
        w("")
        ue = r["unit_economics"]
        w("### Unit economics (Year 3)\n")
        w(f"* Approved versions in Year 3: **{ue['versions']:,.0f}**; Azure direct cost per approved version **${ue['azure_direct_cost_per_version']:,.2f}** "
          f"(variable only ${ue['azure_variable_cost_per_version']:,.2f}); all-in Studio cost per version **${ue['studio_all_in_cost_per_version']:,.2f}** "
          f"vs agency blended **${ue['agency_blended_cost_per_baseline_asset']:,.0f}** per asset today.\n")
        w("| Asset class | Agency cost / asset | Residual external | Azure variable | Human review | Studio all-in | Saving |\n|---|---:|---:|---:|---:|---:|---:|")
        for c, d in ue["by_class"].items():
            w(f"| {d['label']} | ${d['agency_cost_per_asset']:,.0f} | ${d['residual_external_cost']:,.0f} | ${d['azure_variable_cost']:,.2f} | ${d['human_review_cost']:,.2f} | ${d['studio_all_in_cost_displaced_asset']:,.0f} | {d['saving_pct']:.0f} % |")
        w("\n### Sensitivity — what moves the 3-year NPV (tornado)\n")
        w("| Driver | NPV at low | NPV at high | Swing |\n|---|---:|---:|---:|")
        for d in r["sensitivity"]:
            w(f"| {d['label']} | {_usd(d['npv_low'])} | {_usd(d['npv_high'])} | {_usd(d['swing'])} |")
        w("")
    w("## Assumption register\n")
    w("`Brief` = given in the engagement brief · `Sourced` = public source cited · `Assumption` = judgement, validate with customer data.\n")
    w("| Key | Label | Unit | Low | Base | High | Flag |\n|---|---|---|---:|---:|---:|---|")
    for k, a in assumptions["assumptions"].items():
        if a.get("group") in ("azure_units",):
            continue
        w(f"| `{k}` | {a['label']} | {a['unit']} | {a['low']:g} | {a['base']:g} | {a['high']:g} | {a['flag']} |")
    w(f"\n(Azure unit-consumption assumptions — {sum(1 for a in assumptions['assumptions'].values() if a.get('group') == 'azure_units')} keys — are listed in `assumptions.json`.)\n")
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    assumptions = load_assumptions()
    outputs = compute_all(assumptions)
    with open(os.path.join(HERE, "outputs.json"), "w", encoding="utf-8") as fh:
        json.dump(outputs, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(HERE, "outputs.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(outputs, assumptions))
    b = outputs["scenarios"]["base"]
    print(f"base: NPV {_usd(b['roi']['npv'])} · ROI {b['roi']['roi_pct']:.0f}% · payback {b['roi']['payback_months']} mo · "
          f"IRR {b['roi']['irr_pct']:.0f}% · ACR Y3 {_usd(b['acr']['run_rate_year3'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
