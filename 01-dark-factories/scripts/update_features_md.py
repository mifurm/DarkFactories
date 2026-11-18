"""Update the Status / Evidence cells of the FEATURES.md status board (the only cells engineering may edit) from verified evidence.

Run after a green post-deploy smoke test:  python scripts/update_features_md.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# tests/ file keys: core = test_api_core, agents = test_api_agents, insight = test_api_insight, behav = test_behaviour, unit = test_unit_core, proc = test_process_copilot
EVIDENCE: dict[str, str] = {
    "DF-01": "core: test_sim_state_assets_orders_config_catalog, test_time_control_pause_step_speed, test_fault_injection_scenarios_and_unknown_kinds, test_control_api_accepts_valid_and_rejects_forbidden_actions, test_snapshot_and_restore_roundtrip; unit: test_simulation_is_deterministic_and_snapshot_restore_continues_identically, test_each_plant_profile_builds_and_runs; smoke: simulator state; e2e: fault injection",
    "DF-02": "core: test_uns_tree_latest_series_aggregates, test_ingest_validates_topics_values_and_prefix, test_uns_message_decoders; smoke: simulator state + UNS tree, SSE stream",
    "DF-03": "core: test_twin_graph_and_whatif_is_pure; proc: copilot what-if routing; smoke: digital twin what-if on a fork; e2e: what-if journey",
    "DF-04": "core: test_swarm_agents_plans_weights_blackboard, test_agent_toggle_is_enforced_and_audited; behav: test_safety_veto_beats_the_planner, test_kill_switch_halts_every_autonomous_action; smoke: bearing-wear story",
    "DF-05": "behav: test_pdm_alerts_well_before_the_failure, test_planned_maintenance_avoids_the_breakdown; agents: test_pdm_health_signatures_series_and_work_orders, test_bearing_fault_raises_an_alert_through_the_api; smoke: bearing-wear fault -> alert -> work order",
    "DF-06": "agents: test_spc_summary_and_chart, test_quality_drift_is_detected_and_compensated, test_vision_batch_queue_review_and_stats; behav: test_vision_stub_agrees_with_the_known_defect_above_threshold; unit: test_spc_limits_cpk_and_western_electric_rules; smoke: vision (Azure model)",
    "DF-07": "behav: test_planner_replan_meets_more_due_dates_than_fifo_after_a_breakdown, test_planner_schedule_is_feasible_without_capacity_overlaps; agents: test_planner_schedule_compare_explain_replan; smoke: planner endpoints",
    "DF-08": "agents: test_materials_summary_and_amr, test_supplier_delay_scenario_reaches_the_materials_agent; unit: test_material_shortage_starves_presses_in_the_baseline; smoke: materials endpoints",
    "DF-09": "behav: test_energy_agent_shifts_load_without_hurting_due_dates, test_ab_energy_effective_price_is_lower_and_absolute_cost_is_reported_honestly; agents: test_energy_summary_and_trend; smoke: energy endpoints",
    "DF-10": "behav: test_safety_veto_beats_the_planner, test_forbidden_setpoints_are_rejected_everywhere; agents: test_safety_summary_cyber_and_rule_checker, test_human_intrusion_triggers_protective_stop_and_restart; smoke: safety intrusion check",
    "DF-11": "proc: test_process_agent_tunes_the_recipe_inside_hard_bounds_with_twin_evaluation, test_process_recipe_changes_are_policy_governed; agents: test_process_agent_is_disabled_by_default_and_can_be_enabled; smoke: process endpoints (disabled pilot)",
    "DF-12": "behav: test_autonomy_level_matrix, test_lowering_the_dial_changes_what_executes, test_kill_switch_halts_every_autonomous_action; agents: test_policy_dial_rbac_and_ledger_audit, test_kill_switch_via_api_blocks_then_releases, test_break_glass_and_timebox_require_reasons_and_expire, test_policy_rules_roundtrip_and_validation; smoke: kill switch, dial L2",
    "DF-13": "agents: test_inbox_item_lifecycle_approve, test_inbox_reject_and_expiry_fail_safe; unit: test_inbox_escalates_through_the_role_chain_then_expires; insight: test_live_approval_slas_follow_the_scaled_wall_clock_not_simulated_time; smoke: dial L2 -> inbox -> approve -> Teams card; e2e: approvals journey",
    "DF-14": "behav: test_ledger_documents_the_story_with_a_valid_chain, test_ledger_tamper_is_detected; agents: test_ledger_query_verify_export_stats_and_rbac; unit: test_ledger_chain_survives_restart_via_repository_anchor; smoke: valid hash chain; e2e: ledger journey",
    "DF-15": "insight: test_readiness_measured_signals_answers_roadmap_and_export; smoke: readiness assessment + export; e2e: readiness journey",
    "DF-16": "insight: test_copilot_tools_are_read_only_by_default_and_validate_arguments, test_copilot_proposals_go_through_safety_and_policy_not_directly_to_the_plant, test_copilot_chat_stream_and_ask_offline_planner, test_prompt_injection_in_data_does_not_change_tool_policy; proc: test_model_tool_calling_loop_executes_tools_then_answers_with_citations, test_model_failure_and_budget_exhaustion_fall_back_to_the_deterministic_planner; smoke: copilot (Azure OpenAI tool calling)",
    "DF-17": "insight: test_handover_report_generation_formats_and_schedule, test_budget_guard_forces_deterministic_fallback; smoke: handover narrated by Azure OpenAI",
    "DF-18": "insight: test_rca_pareto_hypotheses_and_graph; smoke: RCA narrated by Azure OpenAI",
    "DF-19": "insight: test_kpi_windows_trend_and_snapshots; smoke: KPI endpoints, KPI snapshots persisted to Cosmos DB",
    "DF-20": "insight: test_live_plant_runs_streams_over_sse_and_persists_hourly_kpis; core: test_control_tower_endpoints; smoke: SSE stream; e2e: control tower, fault injection, asset drill-down, kill switch",
    "DF-21": "behav: test_ab_primary_metrics_are_significantly_better, test_ab_tardiness_and_total_loss_improve, test_ab_is_deterministic, test_roi_calculator_reproduces_outputs_json_whole_document_within_half_a_percent, test_vendored_business_case_files_are_one_consistent_version; insight: test_ab_job_runs_in_background_with_progress_and_publishes_latest, test_calculator_meta_is_generated_from_the_model_assumptions, test_calculator_reproduces_the_business_case_reference_values, test_calculator_overrides_lists_nulls_prices_and_validation, test_calculator_can_be_seeded_from_the_ab_measurement; core: test_calculator_posts_use_their_own_bucket_and_large_json_is_gzipped; vitest: calc/logic.test.ts; smoke: A/B replay, ROI/ACR calculator (model v1.1.0 reference values, levers on/off, Upside, 25/100-plant tiers); e2e: value journeys (A/B, calculator with lever toggle)",
    "DF-22": "insight: test_fleet_compare_and_playbook_sharing; smoke: fleet comparison; e2e: fleet journey",
    "DF-23": "insight: test_roles_matrix_me_and_audit_log, test_entra_jwt_validation_with_a_local_signing_key; agents: test_policy_dial_rbac_and_ledger_audit; smoke: RBAC 403s and audit trail",
    "DF-24": "insight: test_observability_finops_and_health; core: test_usage_endpoint_and_budget_guard; unit: test_budget_guard_fails_closed_and_rolls_over_at_midnight; smoke: FinOps meter + budget guard",
    "DF-25": "insight: test_deployment_info_resources_and_smoke_report; smoke: ARM inventory with governance tags (managed identity), results published to the Deployment page",
}


def main() -> int:
    path = ROOT / "FEATURES.md"
    lines = path.read_text().splitlines()
    changed = 0
    for i, line in enumerate(lines):
        m = re.match(r"^\| (DF-\d\d) \| ", line)
        if not m or m.group(1) not in EVIDENCE:
            continue
        cells = line.split(" | ")
        if len(cells) < 6:
            print("unexpected row format:", line[:80])
            return 1
        cells[4] = "Deployed ✔"
        cells[5] = EVIDENCE[m.group(1)].replace("|", "/") + " |"
        lines[i] = " | ".join(cells[:6])
        changed += 1
    path.write_text("\n".join(lines) + "\n")
    print(f"updated {changed} rows")
    return 0 if changed == 25 else 1


if __name__ == "__main__":
    sys.exit(main())
