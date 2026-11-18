# SwarmAI Dark Factory ("Nightshift") — Feature Backlog & Status Board

> **Release 1 = DF-01 … DF-25.** This file is the *contract* between product and engineering: IDs and names are frozen; descriptions,
> acceptance criteria and the Release 2+ roadmap may be sharpened by Product. Engineering edits **only** the *Status* and *Evidence*
> cells of the board below (and nothing else in this file).

Product: SwarmAI Dark Factory ("Nightshift") — lights-out manufacturing run by an Azure-native swarm of AI agents, humans *on* the loop.
Reference plant: **Contoso Precision Components — KAT-1** (3 lines, ≈20 assets). Reference customer: **Contoso Industrial Group** (fictional).
Companion documents: [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [business-case/](business-case/README.md).

## 1. Status board

**Status values** — `Planned` → `In progress` → `Implemented` (backend + API + UI surface exist) → `Tested` (≥ 1 unit test + ≥ 1 API/behavioural test pass; cite test names in *Evidence*) → `Deployed ✔` (exercised by `scripts/smoke_test.py` against the Azure deployment; cite the check name).

| ID | Feature | Epic | Priority | Status | Evidence |
|----|---------|------|----------|--------|----------|
| DF-01 | Factory simulator | A — Plant digital twin & telemetry | P0 | Deployed ✔ | core: test_sim_state_assets_orders_config_catalog, test_time_control_pause_step_speed, test_fault_injection_scenarios_and_unknown_kinds, test_control_api_accepts_valid_and_rejects_forbidden_actions, test_snapshot_and_restore_roundtrip; unit: test_simulation_is_deterministic_and_snapshot_restore_continues_identically, test_each_plant_profile_builds_and_runs; smoke: simulator state; e2e: fault injection |
| DF-02 | Telemetry ingestion & Unified Namespace | A — Plant digital twin & telemetry | P0 | Deployed ✔ | core: test_uns_tree_latest_series_aggregates, test_ingest_validates_topics_values_and_prefix, test_uns_message_decoders; smoke: simulator state + UNS tree, SSE stream |
| DF-03 | Digital twin & what-if engine | A — Plant digital twin & telemetry | P0 | Deployed ✔ | core: test_twin_graph_and_whatif_is_pure; proc: copilot what-if routing; smoke: digital twin what-if on a fork; e2e: what-if journey |
| DF-04 | Swarm runtime & Shift Supervisor | B — Agent swarm | P0 | Deployed ✔ | core: test_swarm_agents_plans_weights_blackboard, test_agent_toggle_is_enforced_and_audited; behav: test_safety_veto_beats_the_planner, test_kill_switch_halts_every_autonomous_action; smoke: bearing-wear story |
| DF-05 | Predictive Maintenance agent | B — Agent swarm | P0 | Deployed ✔ | behav: test_pdm_alerts_well_before_the_failure, test_planned_maintenance_avoids_the_breakdown; agents: test_pdm_health_signatures_series_and_work_orders, test_bearing_fault_raises_an_alert_through_the_api; smoke: bearing-wear fault -> alert -> work order |
| DF-06 | Quality Guardian agent | B — Agent swarm | P0 | Deployed ✔ | agents: test_spc_summary_and_chart, test_quality_drift_is_detected_and_compensated, test_vision_batch_queue_review_and_stats; behav: test_vision_stub_agrees_with_the_known_defect_above_threshold; unit: test_spc_limits_cpk_and_western_electric_rules; smoke: vision (Azure model) |
| DF-07 | Production Planner agent | B — Agent swarm | P0 | Deployed ✔ | behav: test_planner_replan_meets_more_due_dates_than_fifo_after_a_breakdown, test_planner_schedule_is_feasible_without_capacity_overlaps; agents: test_planner_schedule_compare_explain_replan; smoke: planner endpoints |
| DF-08 | Materials & Logistics agent | B — Agent swarm | P1 | Deployed ✔ | agents: test_materials_summary_and_amr, test_supplier_delay_scenario_reaches_the_materials_agent; unit: test_material_shortage_starves_presses_in_the_baseline; smoke: materials endpoints |
| DF-09 | Energy & Sustainability agent | B — Agent swarm | P1 | Deployed ✔ | behav: test_energy_agent_shifts_load_without_hurting_due_dates, test_ab_energy_effective_price_is_lower_and_absolute_cost_is_reported_honestly; agents: test_energy_summary_and_trend; smoke: energy endpoints |
| DF-10 | Safety & Compliance Sentinel | B — Agent swarm | P0 | Deployed ✔ | behav: test_safety_veto_beats_the_planner, test_forbidden_setpoints_are_rejected_everywhere; agents: test_safety_summary_cyber_and_rule_checker, test_human_intrusion_triggers_protective_stop_and_restart; smoke: safety intrusion check |
| DF-11 | Process Optimizer agent | B — Agent swarm | P2 | Deployed ✔ | proc: test_process_agent_tunes_the_recipe_inside_hard_bounds_with_twin_evaluation, test_process_recipe_changes_are_policy_governed; agents: test_process_agent_is_disabled_by_default_and_can_be_enabled; smoke: process endpoints (disabled pilot) |
| DF-12 | Autonomy Dial & policy-as-code | C — Autonomy governance | P0 | Deployed ✔ | behav: test_autonomy_level_matrix, test_lowering_the_dial_changes_what_executes, test_kill_switch_halts_every_autonomous_action; agents: test_policy_dial_rbac_and_ledger_audit, test_kill_switch_via_api_blocks_then_releases, test_break_glass_and_timebox_require_reasons_and_expire, test_policy_rules_roundtrip_and_validation; smoke: kill switch, dial L2 |
| DF-13 | Human-on-the-loop inbox | C — Autonomy governance | P0 | Deployed ✔ | agents: test_inbox_item_lifecycle_approve, test_inbox_reject_and_expiry_fail_safe; unit: test_inbox_escalates_through_the_role_chain_then_expires; insight: test_live_approval_slas_follow_the_scaled_wall_clock_not_simulated_time; smoke: dial L2 -> inbox -> approve -> Teams card; e2e: approvals journey |
| DF-14 | Decision Ledger | C — Autonomy governance | P0 | Deployed ✔ | behav: test_ledger_documents_the_story_with_a_valid_chain, test_ledger_tamper_is_detected; agents: test_ledger_query_verify_export_stats_and_rbac; unit: test_ledger_chain_survives_restart_via_repository_anchor; smoke: valid hash chain; e2e: ledger journey |
| DF-15 | Lights-Out Readiness Assessment | C — Autonomy governance | P1 | Deployed ✔ | insight: test_readiness_measured_signals_answers_roadmap_and_export; smoke: readiness assessment + export; e2e: readiness journey |
| DF-16 | "Ask the Factory" copilot | D — Copilot & insight | P0 | Deployed ✔ | insight: test_copilot_tools_are_read_only_by_default_and_validate_arguments, test_copilot_proposals_go_through_safety_and_policy_not_directly_to_the_plant, test_copilot_chat_stream_and_ask_offline_planner, test_prompt_injection_in_data_does_not_change_tool_policy; proc: test_model_tool_calling_loop_executes_tools_then_answers_with_citations, test_model_failure_and_budget_exhaustion_fall_back_to_the_deterministic_planner; smoke: copilot (Azure OpenAI tool calling) |
| DF-17 | Shift handover & executive digest | D — Copilot & insight | P1 | Deployed ✔ | insight: test_handover_report_generation_formats_and_schedule, test_budget_guard_forces_deterministic_fallback; smoke: handover narrated by Azure OpenAI |
| DF-18 | Root-cause analysis assistant | D — Copilot & insight | P1 | Deployed ✔ | insight: test_rca_pareto_hypotheses_and_graph; smoke: RCA narrated by Azure OpenAI |
| DF-19 | KPI engine | D — Copilot & insight | P0 | Deployed ✔ | insight: test_kpi_windows_trend_and_snapshots; smoke: KPI endpoints, KPI snapshots persisted to Cosmos DB |
| DF-20 | Control Tower UI | E — Platform & business value | P0 | Deployed ✔ | insight: test_live_plant_runs_streams_over_sse_and_persists_hourly_kpis; core: test_control_tower_endpoints; smoke: SSE stream; e2e: control tower, fault injection, asset drill-down, kill switch |
| DF-21 | Value realization & ACR/ROI calculator | E — Platform & business value | P0 | Deployed ✔ | behav: test_ab_primary_metrics_are_significantly_better, test_ab_tardiness_and_total_loss_improve, test_ab_is_deterministic, test_roi_calculator_reproduces_outputs_json_whole_document_within_half_a_percent, test_vendored_business_case_files_are_one_consistent_version; insight: test_ab_job_runs_in_background_with_progress_and_publishes_latest, test_calculator_meta_is_generated_from_the_model_assumptions, test_calculator_reproduces_the_business_case_reference_values, test_calculator_overrides_lists_nulls_prices_and_validation, test_calculator_can_be_seeded_from_the_ab_measurement; core: test_calculator_posts_use_their_own_bucket_and_large_json_is_gzipped; vitest: calc/logic.test.ts; smoke: A/B replay, ROI/ACR calculator (model v1.1.0 reference values, levers on/off, Upside, 25/100-plant tiers); e2e: value journeys (A/B, calculator with lever toggle) |
| DF-22 | Multi-plant fleet | E — Platform & business value | P1 | Deployed ✔ | insight: test_fleet_compare_and_playbook_sharing; smoke: fleet comparison; e2e: fleet journey |
| DF-23 | Identity & RBAC | E — Platform & business value | P1 | Deployed ✔ | insight: test_roles_matrix_me_and_audit_log, test_entra_jwt_validation_with_a_local_signing_key; agents: test_policy_dial_rbac_and_ledger_audit; smoke: RBAC 403s and audit trail |
| DF-24 | Observability & FinOps | E — Platform & business value | P1 | Deployed ✔ | insight: test_observability_finops_and_health; core: test_usage_endpoint_and_budget_guard; unit: test_budget_guard_fails_closed_and_rolls_over_at_midnight; smoke: FinOps meter + budget guard |
| DF-25 | IaC & deployment | E — Platform & business value | P0 | Deployed ✔ | insight: test_deployment_info_resources_and_smoke_report; smoke: ARM inventory with governance tags (managed identity), results published to the Deployment page |

**Evidence summary** (from [REPORT-TEST-AND-DEPLOYMENT.md](REPORT-TEST-AND-DEPLOYMENT.md), live deployment, build `ca-nightshift--azd-1794963538`): 25/25 features *Deployed ✔* · live smoke test **25/25 PASS** · **113 pytest tests at 93 % line coverage** (ruff and mypy clean on the scoped packages, 9 Vitest) · Playwright **15/15** on the live URL · 26/26 UI routes crawled clean · typical API latency **p50 1.2–2.6 ms, p95 6–45 ms** server-side · one replica (0.5 vCPU / 1 GiB) · ≈ US$45 a month idle · A/B replay of 10 seeds ≈ 41 s on the container (background job). **A/B simulation result in one line:** significant improvements for downtime, late orders, tardiness, total loss, OEE and the effective energy price; absolute energy cost slightly worse (+6 %); scrap, customer escapes, OTIF and units shipped not significant (PRD §10.3).

## 2. How to read this file

* **Identifiers.** `DF-nn` feature · `AC-nn.k` acceptance criterion *k* of feature *nn* (use it in test names, e.g. `test_ac_05_1_bearing_alert_lead_time`) ·
  `FR-xnn` PRD functional requirement · `NFR-nn` PRD non-functional requirement · `KPI-nn` measured outcome (catalogue in §5).
* **Normative defaults.** Numeric thresholds in acceptance criteria are *defaults*. Engineering may tune a number only with evidence recorded in
  `REPORT-TEST-AND-DEPLOYMENT.md`; the *behaviour* (the "what") is the contract. Every criterion must be testable without network access
  (offline stubs); where a criterion says *smoke* it is verified against the deployed Azure slice with real models.
* **Real vs simulated.** *Real* = production-grade software that runs in the reference implementation. *Simulated* = the physical or third-party
  world (machines, sensors, ERP/MES, Teams, grid) replaced by deterministic, tested simulators **behind the same interface** the production
  integration would use. Nothing simulated may be presented as real in the UI (footer indicator "Synthetic data / simulated environment").
* **Target vs slice.** *Target* = the production Azure design in [ARCHITECTURE.md](ARCHITECTURE.md). *Slice* = what is deployed in the demo
  (one Container App, Cosmos DB serverless, Storage, Foundry `chat` = gpt-5.4-mini and `reasoning` = gpt-5.4, App Insights/Log Analytics, ACR,
  one user-assigned managed identity; keyless). Every slice component sits behind an interface so the target service plugs in later.
* **Definition of Done (per feature).** Backend logic + REST API + UI surface + ≥ 1 unit test + ≥ 1 API/behavioural test + registry entry in
  `GET /api/features` + a row above moved to *Tested*; *Deployed ✔* only after the smoke test exercised it on Azure.

## 3. Release 1 — features

### Epic A — Plant digital twin & telemetry

#### DF-01 — Factory simulator
`Epic A · P0 · FR-A01, FR-A02, FR-A03 · KPIs: enables KPI-01…09 and KPI-21`

**Why / problem.** Autonomy cannot be trained, tested, demonstrated or *measured* on a live plant, and no customer will hand over a production line on day one.
A faithful, deterministic plant is the safe place to rehearse every scenario and the instrument that makes counterfactual A/B measurement possible.

**Description.** Seeded, deterministic discrete-time simulation of **Contoso Precision Components — KAT-1**: 3 lines (Machining, Injection Molding, Assembly & Test), ≈ 20 assets —
6 CNCs (CNC-01…06), 3 injection presses (IMM-01…03), 2 assembly cells (ASM-01…02), 2 test stations (TST-01…02), packaging (PKG-01), compressor (CMP-01), chiller (CHL-01), 3 AMRs
(AMR-01…03), raw-material warehouse (WH-01) — plus orders with due dates, priorities and routings. Asset state machine `RUN/IDLE/SETUP/DOWN/MAINT/BLOCKED/STARVED`; stochastic degradation
(health index); sensors (vibration, temperature, current, spindle load, pressure); quality (defect probability tied to tool wear and process drift); energy by state; time-of-use (ToU) tariff and grid
carbon-intensity curves. **Fault-injection library:** bearing wear, tool wear, thermal drift, jam, supplier delay, rush order, power-price spike, quality drift, human intrusion into a safety zone.
Time acceleration, pause/step, snapshot/restore, and a control API for agent actions (speed, setpoints, schedule, maintenance, AMR dispatch, load shift, safe-stop).

**Acceptance criteria**
- **AC-01.1 Determinism** — two runs with the same seed, scenario script and action script have identical `state_hash` at every 60th tick over ≥ 7 simulated days; different seeds diverge.
- **AC-01.2 Snapshot/restore** — `snapshot()` → `restore()` → continue yields the same `state_hash` as an uninterrupted run (RNG state included); snapshots serialise to JSON and round-trip through Blob/Cosmos.
- **AC-01.3 State machine** — only legal transitions occur (property test over ≥ 50 seeds × 7 days); per-asset state durations sum to elapsed time.
- **AC-01.4 Fault library** — all 9 faults are injectable via API at a chosen sim time with parameters and each produces its documented signature (e.g., bearing wear ⇒ vibration RMS and temperature trend upward, health index decays, functional failure within the configured horizon if untreated); one parametrised test covers all nine.
- **AC-01.5 Control API** — each action type is validated against asset envelopes (out-of-range ⇒ 422 with reason) and its effect is observable in state within ≤ 1 tick.
- **AC-01.6 Speed** — bare simulator ≥ 1,500 sim-minutes per wall-second on one vCPU (24 sim-hours ≤ ~1 s), so multi-seed A/B replays finish in seconds (measured rate reported in the REPORT).

**Azure — target / slice.** *Target:* in production the real plant replaces the simulator for live operation; the simulator remains the engine for what-if forks, A/B replay, training and onboarding, scaled out as batch jobs
(Container Apps jobs / AKS / Azure Batch) and calibrated from plant history with Azure ML. *Slice:* in-process Python module in the Container App; snapshots in Cosmos DB / Blob.

**Reference implementation & simulation.** Everything physical is simulated (that is the point); the simulator is real, tested software exposing the same `PlantInterface` (read telemetry, execute control action) a real PLC/SCADA/MES adapter would implement.

**Depends on.** — (foundation). **Enables.** DF-02, DF-03, DF-04…DF-11, DF-19, DF-21, DF-22.

---

#### DF-02 — Telemetry ingestion & Unified Namespace
`Epic A · P0 · FR-A04, FR-A05, FR-A06 · KPIs: KPI-12, KPI-16`

**Why / problem.** Plants speak a dozen protocols with inconsistent names. Agents need one semantic, ISA-95-shaped namespace and trustworthy, timestamped data; otherwise every integration is bespoke and every model is brittle.

**Description.** ISA-95 topic hierarchy `enterprise/site/area/line/cell/asset/metric`; pydantic-validated messages (value, unit, quality, source timestamp, sequence, source id); `TelemetrySource` adapter interface — **SimSource** (default), **HTTP ingest**, and documented
**MQTT / Event Hubs / IoT Operations** adapters; ring-buffer time-series store with downsampling and periodic persistence of aggregates; live subscription over SSE/WebSocket with MQTT-style wildcards.

**Acceptance criteria**
- **AC-02.1 Topic model** — 7-level ISA-95 topics validated; wrong depth / illegal characters ⇒ 422; wildcards `+` (one level) and `#` (rest) work for subscriptions (≥ 10 pattern tests).
- **AC-02.2 Message schema** — `{topic, value, unit, quality ∈ GOOD|UNCERTAIN|BAD, ts_source, ts_ingest, seq, source_id}`; unit/metric registry rejects mismatches (e.g., `vibration_rms` in °C); rejects are counted in `GET /api/telemetry/stats`.
- **AC-02.3 Pluggable sources** — `SimSource` and `HttpIngestSource` (`POST /api/telemetry/ingest`, ≤ 500 messages/batch, rate-limited) work; MQTT, Event Hubs and IoT Operations adapters exist as contract-tested classes (fake broker) behind the same interface, disabled by default and documented.
- **AC-02.4 Time-series** — ≥ 24 h at 1-minute resolution for all KAT-1 series (≈ 20 assets × ≥ 8 metrics) in the ring buffer; 5-min / 1-h downsampling (min/max/mean/last/count) equals a reference computation; duplicates are idempotent and late arrivals (≤ 5 min) are merged.
- **AC-02.5 Persistence** — aggregates flush periodically through the repository interface (Cosmos DB; in-memory for tests) and reload after a restart without gaps in the persisted range.
- **AC-02.6 Live stream** — `GET /api/stream/telemetry?topic=<pattern>` (SSE) delivers ≥ 1 update/s per subscription with ≤ 1 s staleness; a slow consumer is dropped without blocking producers (back-pressure test).

**Azure — target / slice.** *Target:* Azure IoT Operations on Arc-enabled Kubernetes (OPC UA connector, MQTT broker as the UNS, data flows) → Event Hubs (Kafka endpoint) → Fabric Real-Time Intelligence (Eventstream → Eventhouse), OneLake/ADLS for history. *Slice:* in-process asyncio bus and ring buffers; aggregates in Cosmos DB.

**Reference implementation & simulation.** Real: topic model, validation, buffering, downsampling, persistence, streaming. Simulated: the data source (SimSource). MQTT/Event Hubs/IoT Operations adapters are interface-level and contract-tested, not connected to live brokers.

**Expansion note (lever E4, business-case v1.1).** At enterprise scale the same namespace feeds an *enterprise data platform*: Fabric capacity, OneLake with 7–10-year retention and migrated historian archives (≈ $336 k a year of Azure at 8 plants, mostly the enterprise Fabric capacity). Modelled in `business-case/` only; nothing beyond the in-process store is deployed.

**Depends on.** DF-01. **Enables.** DF-03, DF-05, DF-06, DF-09, DF-18, DF-19.

---

#### DF-03 — Digital twin & what-if engine
`Epic A · P0 · FR-A07, FR-B02 · KPIs: KPI-12, KPI-11, KPI-13`

**Why / problem.** The riskiest moment in autonomy is the first time an action touches the plant. A twin that can *rehearse* an action on forked state and report its consequences turns "trust me" into "here is the evidence".

**Description.** Live asset graph (hierarchy, relations, state, health, KPIs); `fork()` clones simulator state into an isolated sandbox; `simulate_ahead(actions, horizon)` runs do-nothing vs. with-actions from the same snapshot and returns KPI deltas, feasibility, risk flags and a timeline; API `POST /api/twin/whatif`; used by the Shift Supervisor for **sim-first validation** of every consequential proposal.

**Acceptance criteria**
- **AC-03.1 Asset graph** — `GET /api/twin/graph` returns hierarchy and relations (`feeds`, `precedes`, `shares-utility`, `located-in-zone`) with live state/health/KPIs per node, consistent with the simulator (≥ 20 assets spot-checked).
- **AC-03.2 Fork isolation** — running or mutating a fork leaves the live twin's `state_hash` unchanged.
- **AC-03.3 Determinism** — identical inputs ⇒ identical what-if output; a no-op action list returns all-zero deltas.
- **AC-03.4 Latency** — `POST /api/twin/whatif` (≥ 1 action, horizon 15 min – 48 h) returns in ≤ 2 s p95 for a 12-h horizon on the deployed container; every result gets an id and is persisted so the ledger can link to it.
- **AC-03.5 Bounds** — ≥ 8 concurrent what-ifs complete correctly; excess requests are queued or rejected with 429; horizon and action-count limits are enforced.
- **AC-03.6 Fidelity** — if the evaluated actions are then executed live and no new disruption occurs, realised KPI deltas match the prediction within 5 % (throughput) / 10 % (tardiness).

**Azure — target / slice.** *Target:* Azure Digital Twins (DTDL) or Fabric digital twin builder for the semantic graph; what-if workers as Container Apps jobs / AKS pods scaled out per request. *Slice:* in-memory graph over the simulator; fork = snapshot restore in a worker task.

**Reference implementation & simulation.** Real: graph, fork, what-if, persistence, API. Simulated: the underlying plant dynamics (shared code with DF-01).

**Expansion note (lever E3, business-case v1.1).** Rehearsing every consequential decision with Monte-Carlo rollouts at scale (≈ 1,500 decisions × 64 rollouts per plant-day) runs on elastic, stateless simulation pools and is what earns higher autonomy levels (L4/L5). Modelled as ≈ $188 k a year of Azure at 8 plants (4 plants deploying); the slice runs a single in-process fork per decision.

**Depends on.** DF-01. **Enables.** DF-04, DF-07, DF-09, DF-11, DF-16, DF-21.

---

### Epic B — Agent swarm

#### DF-04 — Swarm runtime & Shift Supervisor
`Epic B · P0 · FR-B01, FR-B02, FR-C06 · KPIs: KPI-10, KPI-12, KPI-13, KPI-04`

**Why / problem.** Specialist agents optimise different, often opposing objectives (throughput vs energy vs maintenance vs quality vs due dates). Without an explicit coordinator the result is either chaos or a black box; with one, trade-offs become auditable.

**Description.** Agent base class (`perceive → propose`), event bus / blackboard, **Proposal** objects (action, rationale, evidence, impact estimate, risk, cost, expiry), conflict detection (shared resource/time window, mutually exclusive actions, objective trade-offs) and
**utility-based arbitration** with explicit, versioned weights (service level, cost, risk, energy/carbon, asset health). The **Shift Supervisor** pipeline: collect → de-duplicate/merge → detect conflicts → what-if each candidate bundle (DF-03) → score utility → policy check (DF-12) →
route (auto-execute / request approval / reject) → execute through the control API → write the ledger chain (DF-14) → measure the outcome. Rate limits, per-agent metrics. Deterministic by default; an LLM may *narrate* rationale/negotiation but never changes the decision.

**Acceptance criteria**
- **AC-04.1 Conflict resolution** — two proposals that need CNC-05 in the same window are resolved to exactly one executed bundle; the loser is recorded as deferred/rejected with a reason and both rationales are in the ledger.
- **AC-04.2 Determinism & explainability** — the same blackboard state yields the same decision; the per-term utility breakdown (weight × normalised delta) is persisted and returned by `GET /api/supervisor/decisions/{id}`.
- **AC-04.3 Sim-first** — every proposal whose risk class ≥ *consequential* carries a what-if result id before execution; a proposal without one is never auto-executed (test).
- **AC-04.4 Expiry & rate limits** — expired proposals are never executed; an agent exceeding its proposals-per-hour budget is throttled and a `throttled` event is emitted and counted.
- **AC-04.5 Pluggable agents** — a new agent registers via the base class with no change to supervisor code (test with a dummy agent).
- **AC-04.6 LLM optional** — with the LLM stub/unavailable all decisions and texts are still produced (deterministic templates); outcomes are identical with and without LLM narration.

**Azure — target / slice.** *Target:* agents as containerised workers on Container Apps/AKS (edge copies on IoT Operations), Microsoft Foundry Agent Service / Microsoft Agent Framework for LLM-driven reasoning, Service Bus / Event Grid for events, Cosmos DB for blackboard and agent memory. *Slice:* asyncio loops inside the single Container App; Cosmos DB for state; Foundry chat/reasoning deployments for optional narration.

**Reference implementation & simulation.** Real: runtime, arbitration, supervisor pipeline. Simulated: the plant the actions execute against.

**Depends on.** DF-01, DF-03, DF-12, DF-14. **Enables.** DF-05…DF-11, DF-13, DF-20.

---

#### DF-05 — Predictive Maintenance agent
`Epic B · P0 · FR-B03 · KPIs: KPI-01, KPI-09, KPI-12`

**Why / problem.** Unplanned downtime is the largest controllable loss in discrete manufacturing; rule-based thresholds either fire too late or cry wolf. A maintenance agent must give *lead time* and book the repair into a window that costs the least.

**Description.** Multivariate anomaly detection (robust z-score / EWMA / isolation-forest-style) over vibration, temperature, current and spindle load; health index (0–100); **RUL estimate with confidence interval**; auto-generated work orders placed into planned windows (changeovers, planned stops, low-load periods); spare-part check;
**failure-signature library** (bearing, tool wear, thermal drift, jam precursors…) with similarity matching.

**Acceptance criteria**
- **AC-05.1 Lead time** — on the seeded bearing-wear scenario (seed and scenario id documented in the test) the first alert precedes functional failure by ≥ 6 sim-hours and the RUL at first alert is within ±30 % of the true remaining life.
- **AC-05.2 False alarms** — ≤ 1 alert per 100 asset-days on a healthy 7-day run at the default sensitivity (measured over ≥ 5 seeds).
- **AC-05.3 Work order in a planned window** — a work order is placed in the next planned window before the predicted failure; when executed, the asset enters `MAINT` (not `DOWN`) and unplanned downtime is lower than the do-nothing what-if (assert).
- **AC-05.4 Signature library** — ≥ 5 failure signatures; matching returns top-k with similarity and the matched signature appears in the alert evidence.
- **AC-05.5 Spares** — if the spare is unavailable the proposal includes a request to the Materials agent (DF-08) or flags the dependency; the work order never schedules before spare ETA.
- **AC-05.6 Evidence** — every alert exposes evidence (sensors, window, score, signature, RUL CI) via `GET /api/agents/maintenance/alerts/{id}` and links into the ledger.

**Azure — target / slice.** *Target:* Azure ML (training, managed online endpoints; ONNX exported to the edge runtime), Eventhouse KQL anomaly functions and Fabric Activator triggers, work-order write-back to CMMS/ERP. *Slice:* algorithmic detectors in Python; optional LLM narration via the chat deployment.

**Reference implementation & simulation.** Real: detectors, RUL, work-order logic. Simulated: sensors/degradation; CMMS is a simulated work-order store behind a `WorkOrderPort`.

**Expansion note (lever E2, business-case v1.1).** kHz vibration and acoustic monitoring of rotating assets (edge feature extraction, scheduled raw-waveform snapshots to Event Hubs / ADLS / Fabric, Azure ML signature models) adds earlier failure detection beyond the core 20 % downtime reduction. Small for Azure (≈ $93 k a year at 8 plants, 6 deploying) unless raw waveforms are streamed continuously; the slice uses sampled summary telemetry.

**Depends on.** DF-01, DF-02, DF-04, (DF-08 optional). **Enables.** the 02:14 narrative.

---

#### DF-06 — Quality Guardian agent
`Epic B · P0 · FR-B04, FR-B05 · KPIs: KPI-03, KPI-06, KPI-13`

**Why / problem.** Scrap and escapes are discovered late, after value has been added. Quality needs statistical process control that *acts* — compensating drift inside safe bounds, containing suspect lots and escalating what it cannot judge.

**Description.** SPC (X-bar/R, Cpk, Western Electric rules), drift detection (EWMA/CUSUM), **bounded automatic setpoint compensation**, lot quarantine/containment, and **vision inspection**: Azure OpenAI multimodal on synthetic part images generated with PIL (scratches, voids, burrs) with a **human-review queue for low-confidence calls**.

**Acceptance criteria**
- **AC-06.1 SPC** — Cpk, X-bar/R limits and Western Electric rule hits equal hand-computed fixtures within 1e-6; thermal-drift or tool-wear faults raise a rule violation within ≤ 10 subgroups.
- **AC-06.2 Bounded compensation** — a compensation never exceeds the configured max offset or rate (property test over random drift); out-of-bounds requests are rejected and escalated.
- **AC-06.3 Containment** — quarantine holds exactly the lots produced since the last in-control subgroup (+ configurable look-back); release/scrap decisions go through the inbox (DF-13) and the ledger.
- **AC-06.4 Vision (smoke)** — on ≥ 60 synthetic images (ok + 3 defect classes) the real model's class agreement ≥ 85 %; unit tests use the deterministic stub.
- **AC-06.5 Human review** — predictions with confidence < 0.70 enter the review queue; the reviewer's verdict is recorded (role + timestamp) and fed back to the confusion statistics.
- **AC-06.6 Scrap/FPY effect — reported, not assumed** — the A/B (DF-21) reports scrap and customer escapes with 95 % CIs. *Revised after the evidence:* in the default 8-disruption scenario there is **no significant effect** (16 seeds: scrap 1.91 → 2.54 units, CI [−3.84, 2.59]; escapes 0.10 → 0.001, CI [−0.06, 0.26]), so the business case treats the scrap benefit as benchmark/assumption-only to be proven in shadow mode and the pilot. Drift detection and bounded compensation are verified separately (AC-06.1, AC-06.2; `test_quality_drift_is_detected_and_compensated`).

**Azure — target / slice.** *Target:* Azure ML (defect models, ONNX at the edge for inline inspection), Foundry multimodal models for long-tail/low-confidence cases, Blob/OneLake for image archive. *Slice:* Foundry chat deployment (multimodal) on synthetic images; Python SPC.

**Reference implementation & simulation.** Real: SPC maths, compensation, containment, review queue, vision call. Simulated: parts and images (PIL-generated), measurement devices.

**Evidence note (live vision).** Smoke check #15 on the live deployment: 6 of 6 synthetic defect images classified correctly by `gpt-5.4-mini` (100 % agreement); unit tests use the offline stub. A ≥ 60-image agreement estimate as described in AC-06.4 is not reported in `REPORT-TEST-AND-DEPLOYMENT.md`, so the 100 % is a smoke result, not a statistical estimate.

**Expansion note (lever E1, business-case v1.1).** A production *machine-vision fleet* (≈ 30 cameras per plant) keeps inference on customer edge GPUs; Azure carries the defect-image archive, GPU retraining (Azure ML) and the ≈ 0.8 % of frames escalated to multimodal models — ≈ $29 k a year per deploying plant, $116 k at 8 plants (4 deploying). The slice implements the escalation and human-review path on synthetic images only.

**Depends on.** DF-01, DF-02, DF-04, DF-13. 

---

#### DF-07 — Production Planner agent
`Epic B · P0 · FR-B06 · KPIs: KPI-04, KPI-02, KPI-06`

**Why / problem.** Static schedules decay the minute a machine fails or a rush order lands; planners spend their shifts re-planning in spreadsheets. Continuous, explainable re-planning protects due dates without a human in the middle of the night.

**Description.** Finite-capacity scheduling (due dates, priority, setup/changeover matrix, routings, shift calendars), continuous **re-planning on disruption** (breakdown, rush order, shortage, quality hold), schedule-quality KPIs (tardiness, makespan, utilisation) and a "why this schedule" explanation. **Baseline for A/B = FIFO/static.**

**Acceptance criteria**
- **AC-07.1 Feasibility** — an independent checker confirms no resource overlaps, routing precedence honoured, setups included, calendars respected, for every generated schedule (property test).
- **AC-07.2 Beats the baseline** — on the breakdown scenario the re-planned schedule delivers more on-time orders and lower total weighted tardiness than FIFO on the same seed (≥ 10 seeds, paired, p < 0.05).
- **AC-07.3 Latency** — re-plan for ≥ 60 open orders in ≤ 3 s p95.
- **AC-07.4 Rush orders** — a rush order is accepted only if feasible without breaking higher-priority due dates; otherwise alternatives (overtime, next slot, partial split) are proposed with their cost.
- **AC-07.5 Stability** — operations inside the freeze horizon never move; ≤ 15 % of unaffected operations change on a re-plan.
- **AC-07.6 Explanation** — `GET /api/planner/explain` lists ≥ 3 quantified drivers (slack, setup savings, bottleneck protection…).

**Azure — target / slice.** *Target:* solver microservice (OR-Tools CP-SAT) on Container Apps with orders/routings read from ERP/MES (e.g., Dynamics 365 SCM, SAP), Foundry for explanation. *Slice:* deterministic heuristic + local-search scheduler in Python; MES/ERP simulated behind `OrderPort`.

**Reference implementation & simulation.** Real: scheduler, re-planning, checker. Simulated: ERP/MES order feed.

**Evidence note.** The "Planner vs FIFO" table on the Planner page compares the two on the *current* plant state; on a quiet plant FIFO can be better on a single snapshot (the screenshot used in the deck shows 328 vs 1,386 tardiness minutes in FIFO's favour). The claim is made only for the breakdown scenario (AC-07.2, `test_planner_replan_meets_more_due_dates_than_fifo_after_a_breakdown`) and over many seeds in the A/B (late orders −20 %, tardiness −18 %), not from one frame.

**Depends on.** DF-01, DF-03, DF-04. 

---

#### DF-08 — Materials & Logistics agent
`Epic B · P1 · FR-B07 · KPIs: KPI-07, KPI-08, KPI-04`

**Why / problem.** Starved machines and expedited freight are the hidden cost of supplier variability; nobody wants to stage kits and chase suppliers at 3 a.m.

**Description.** BOM/inventory with min/max, reorder proposals, **AMR dispatch** to feed cells, supplier-delay mitigation (expedite / alternate source, with cost vs. lateness avoided), kitting.

**Acceptance criteria**
- **AC-08.1 Reorder** — crossing a min level yields a purchase proposal up to max with lead-time-aware timing; inventory is never negative; consumption equals BOM × units produced (invariant test).
- **AC-08.2 Supplier delay** — the `supplier delay` fault is detected before the planned operation start and ranked mitigations (expedite / alternate source / re-sequence) show cost and lateness avoided.
- **AC-08.3 AMR dispatch** — no task is double-assigned; starved time in the swarm-ON arm ≤ swarm-OFF over ≥ 10 seeds.
- **AC-08.4 Kitting** — kits are staged before the operation start for ≥ 95 % of released orders in the baseline scenario.
- **AC-08.5 Integration with PdM** — a spare-part request from DF-05 is answered with availability/ETA or an expedite option.

**Azure — target / slice.** *Target:* ERP/WMS integration (D365 SCM, SAP EWM), AMR fleet manager via VDA 5050/MQTT, Service Bus for PO workflows. *Slice:* Python domain logic + AMR simulation.

**Reference implementation & simulation.** Real: inventory/reorder/dispatch logic. Simulated: suppliers, ERP, AMR hardware.

**Depends on.** DF-01, DF-04, DF-07.

---

#### DF-09 — Energy & Sustainability agent
`Epic B · P1 · FR-B08 · KPIs: KPI-05`

**Why / problem.** Energy is a controllable cost and, increasingly, a reported emission; most plants run flat-out regardless of tariff or grid carbon.

**Description.** Tariff-aware (time-of-use) and carbon-aware **load shifting** of deferrable processes (compressor loading, chiller pre-cooling, curing/heat-treat, AMR charging, deferrable orders), **peak-demand shaving**, and kWh and CO2e-per-unit KPIs. **What it does and does not do:** it moves consumption to cheaper hours, so it lowers the *effective price paid per kWh* where tariffs vary; it does **not** reduce consumption, and absolute energy cost can rise when less downtime means more machine-hours.

**Acceptance criteria**
- **AC-09.1 Price paid — reported honestly** — *Revised after the evidence.* In the evening-peak A/B window the swarm-ON arm pays a lower **effective energy price** than swarm-OFF without missing a due date (≥ 10 seeds, CI above zero; 16 seeds: 0.288 → 0.258 EUR/kWh, −10 %, CI [0.022, 0.037]; about −2 % in the night and day windows). Absolute energy cost (447 → 475 EUR, **+6 %, worse**) and energy per unit-operation (−4 %, not significant) are reported as measured. `test_ab_energy_effective_price_is_lower_and_absolute_cost_is_reported_honestly`.
- **AC-09.2 Safety of deferral** — a shift is never proposed when it would violate a due date, a safety or quality constraint (negative tests).
- **AC-09.3 Peak shaving** — under the `power-price spike` fault, 15-minute maximum demand falls ≥ 5 % vs. baseline.
- **AC-09.4 Carbon** — CO2e per unit equals Σ(kWh × intensity) / units on fixtures; carbon and cost objectives are separately weighted and visible in the utility breakdown.
- **AC-09.5 Model sanity** — energy by state is monotone (SETUP/RUN ≥ IDLE ≥ DOWN) and reconciles to metered totals within 1 %.

**Azure — target / slice.** *Target:* energy meters via IoT Operations, tariff/market feeds and grid-carbon APIs (e.g., Green Software Foundation Carbon Aware SDK data providers), Fabric for time-series. *Slice:* simulator tariff and carbon curves.

**Reference implementation & simulation.** Real: optimisation and KPI logic. Simulated: meters, tariff and carbon feeds.

**Depends on.** DF-01, DF-03, DF-07, DF-19.

---

#### DF-10 — Safety & Compliance Sentinel
`Epic B · P0 · FR-B09 · KPIs: KPI-11, KPI-19`

**Why / problem.** Autonomy is only acceptable if there is an agent whose sole job is to say *no*. People, protected assets and safe operating envelopes must be protected independent of any commercial objective.

**Description.** Safety zones and **human-intrusion** handling (automatic safe-stop / slow), **forbidden-setpoint guards**, protected-asset rules (e.g., lock-out/tag-out state, no autonomous restart), **cyber-hygiene checks** (simulated posture: patch level, unsigned firmware, open ports), immutable audit hooks, and **veto over other agents**.
*Boundary:* in production, safety-rated functions stay in certified controllers/safety relays (ISO 13849 / IEC 62061 / ISO 10218 context); the Sentinel is an additional, higher-level layer that can only *reduce* risk (protective stop, veto), never relax a hardware interlock.

**Acceptance criteria**
- **AC-10.1 Intrusion response** — a `human intrusion` event in a zone triggers a safe-stop/slow of affected assets within ≤ 1 tick and a ledger entry with zone, assets and latency.
- **AC-10.2 Veto beats Planner** — a Planner/Maintenance proposal that requires running an asset in an occupied zone is vetoed with a ledger entry; the vetoed bundle is never executed (even at L5).
- **AC-10.3 Forbidden setpoints** — each rule class (absolute bound, rate-of-change, combination/interlock) rejects violating setpoints from agents *and* from the API, with reasons (one test per class).
- **AC-10.4 Protected assets** — an asset under LOTO cannot be restarted by any agent; only a human role with the permission can clear the state (RBAC test).
- **AC-10.5 Cyber hygiene** — seeded posture findings (e.g., unsigned PLC firmware) produce inbox items with severity and remediation; fixing the finding closes the item.
- **AC-10.6 Kill-switch independence** — with the global kill switch ON, agent actions halt but protective safe-stops from the Sentinel still execute.

**Azure — target / slice.** *Target:* edge-resident agent on IoT Operations beneath which certified safety PLCs/relays operate; Microsoft Defender for IoT / Defender for Cloud for OT network and posture signals; ledger anchoring in Azure Confidential Ledger / immutable Blob. *Slice:* Python sentinel with simulated zone/presence feed and simulated posture.

**Reference implementation & simulation.** Real: rules, veto, response logic. Simulated: presence sensors, PLC interlocks, posture data. No safety-rated claim is made.

**Depends on.** DF-01, DF-04, DF-12, DF-14. **Constrains.** every other agent.

---

#### DF-11 — Process Optimizer agent
`Epic B · P2 · FR-B10 · KPIs: KPI-02, KPI-03, KPI-05`

**Why / problem.** Recipes and parameters are set once and rarely revisited; small, safe adjustments to cycle time, temperature or feed can lift yield and cut energy — if exploration is bounded and reversible.

**Description.** Bounded recipe/parameter optimisation (yield vs. energy vs. cycle time) on injection-molding and machining parameters with **safe-exploration constraints** (trust region, absolute bounds, stable-state precondition, low-risk windows) and **automatic rollback on regression**; candidates are evaluated on forked twin state before any live step.

**Acceptance criteria**
- **AC-11.1 Improvement** — on a seeded process model the composite objective improves ≥ 2 % vs. the starting recipe within the iteration budget.
- **AC-11.2 Bounds** — no proposed value leaves absolute bounds or exceeds the per-step trust-region size (property test).
- **AC-11.3 Rollback** — an injected regression triggers automatic rollback within ≤ N cycles (default 5) and a ledger `rollback` entry.
- **AC-11.4 Governance** — default autonomy for `process.parameter-change` is L1 (recommend); L3+ requires an explicit policy change (test).
- **AC-11.5 Traceability** — every live parameter change records before/after values, what-if id and the observed effect.

**Azure — target / slice.** *Target:* Azure ML (Bayesian optimisation / sweep jobs) against calibrated twin replicas; Foundry for explanation. *Slice:* Python optimiser against forked twin state.

**Reference implementation & simulation.** Real: optimiser, constraints, rollback. Simulated: process response surface.

**Depends on.** DF-01, DF-03, DF-06, DF-12.

---

### Epic C — Autonomy governance

#### DF-12 — Autonomy Dial & policy-as-code
`Epic C · P0 · FR-C01, FR-C02 · KPIs: KPI-10, KPI-11, KPI-19`

**Why / problem.** "Autonomous" is not one setting. A plant will accept a swarm re-sequencing orders long before it accepts it restarting a press next to people. Trust has to be earned per *decision class*, with hard limits and an off switch that always works.

**Description.** Per-decision-class autonomy levels, composite risk scoring, approval thresholds, blast-radius and exposure limits, time-boxed auto-approval, break-glass and a **global kill switch**; rules live in YAML/JSON, are versioned and evaluated by a small, deterministic, tested policy engine.

| Level | Name | Behaviour (default semantics) |
|-------|------|-------------------------------|
| L0 | Observe | agents analyse and log only; nothing is proposed to humans or executed |
| L1 | Recommend | proposals shown to humans; humans execute manually |
| L2 | Approve-to-act | executes only after explicit human approval (default for new decision classes) |
| L3 | Act-with-veto | auto-executes after a short veto window (time-boxed auto-approval) unless a human vetoes; humans notified |
| L4 | Auto-approve within guardrails | executes immediately when risk ≤ threshold, sim-validated and inside blast-radius/exposure limits; humans informed in the digest |
| L5 | Lights-out | autonomous within the widest envelope; humans handle policy escapes (exceptions) and periodic audits |

Illustrative decision classes: `maintenance.schedule`, `planning.reschedule`, `planning.rush-order`, `materials.reorder`, `materials.expedite`, `quality.compensate`, `quality.quarantine`, `quality.release`, `energy.load-shift`, `process.parameter-change`, `safety.protective-stop` (always allowed), `safety.restart` (capped at L2), `policy.change`.
Rule classes (each with unit tests): level gate · risk threshold · blast-radius limit · cost/exposure limit · time-window · forbidden setpoint/envelope · protected asset (LOTO) · require-what-if · time-boxed auto-approval · break-glass · kill switch · action-rate limit · separation of duties.

**Acceptance criteria**
- **AC-12.1 Level × risk matrix** — for every level L0–L5 × risk band (low/medium/high) the outcome (`DENY` / `RECOMMEND` / `REQUIRE_APPROVAL` / `AUTO_AFTER_VETO` / `AUTO`) equals the documented table (≥ 18 parametrised cases).
- **AC-12.2 Rule classes** — each rule class has at least one allow and one deny unit test; evaluation returns the matched rules and human-readable reasons.
- **AC-12.3 Kill switch** — turning it on halts all agent-initiated actions within ≤ 1 tick and cancels pending auto-approvals; protective safe-stops (DF-10) remain allowed; resetting requires the Admin role and is ledgered.
- **AC-12.4 Time-boxing & break-glass** — auto-approval windows expire back to approval; break-glass requires reason, expiry (≤ 60 min default) and dual control, and is ledgered with the elevated scope.
- **AC-12.5 Policy hygiene** — invalid policy files are rejected with line-level errors; each change is versioned, diffed, attributed to an actor and written to the ledger; a dry-run mode replays the last 24 h against a candidate policy and reports what would have changed.
- **AC-12.6 Blast radius** — an action touching more assets/orders than the class limit requires approval even at L4/L5 (test).

**Azure — target / slice.** *Target:* policy repository (GitHub) with signed bundles distributed to edge and cloud (Arc GitOps / IoT Operations), Entra ID + PIM for break-glass, Key Vault for signing keys, Azure Policy for *cloud-resource* governance (distinct from decision policy). *Slice:* YAML policy files + version history in Cosmos DB; Python policy engine.

**Reference implementation & simulation.** Real: engine, risk scoring, versioning, dry-run. Simulated: none (pure logic).

**Depends on.** DF-14 (audit). **Enables.** DF-04, DF-13, DF-20.

---

#### DF-13 — Human-on-the-loop inbox
`Epic C · P0 · FR-C03, FR-C04 · KPIs: KPI-14, KPI-10`

**Why / problem.** Humans on the loop must decide only what matters, with the evidence in front of them and a clock on it. A flood of alerts recreates the problem autonomy is meant to solve.

**Description.** Approval/escalation queue: each item carries options (approve / modify / reject / defer), impact estimate from the what-if, explanation (why, evidence, alternatives, counterfactual), **SLA timers with auto-escalation** and a policy-defined default on timeout. UI plus an optional **Teams channel notifier** (Adaptive Card JSON via a Workflows/incoming webhook configured by env).

**Acceptance criteria**
- **AC-13.1 Lifecycle** — items move `pending → approved | rejected | modified | expired | escalated`; invalid transitions are refused; approving executes the proposal **exactly once** (idempotency test with duplicate clicks/requests).
- **AC-13.2 SLA & escalation** — after the SLA (follows the sim clock so accelerated demos behave realistically) the item escalates along the configured chain (shift lead → plant manager → on-call) and the policy default applies on final expiry (safe default = no action or the safe alternative).
- **AC-13.3 Context** — every item shows what-if KPI deltas, utility breakdown, evidence links and the do-nothing counterfactual.
- **AC-13.4 Teams card** — the Adaptive Card JSON validates against the Adaptive Cards schema (v1.4+) and is POSTed to a mock webhook in tests; with the env var unset the notifier is a logged no-op; the card deep-links to the inbox item.
- **AC-13.5 Audit** — every human action is ledgered with identity and role (DF-23); a user cannot approve their own break-glass request.
- **AC-13.6 Noise control** — duplicate/superseded items are merged or auto-closed with a reason (test).

**Azure — target / slice.** *Target:* Microsoft Teams (Adaptive Cards, actionable messages via bot or Power Automate/Workflows), Service Bus for durable queues, Logic Apps for escalations (SMS/voice via a communications service), Entra ID for identity. *Slice:* inbox in the app (Cosmos DB) + optional Teams webhook notifier.

**Reference implementation & simulation.** Real: queue, SLA engine, UI, card generation. Simulated: Teams delivery unless a webhook is configured.

**Depends on.** DF-04, DF-12, DF-14, DF-23 (roles).

---

#### DF-14 — Decision Ledger
`Epic C · P0 · FR-C05, FR-C06 · KPIs: KPI-13, KPI-19`

**Why / problem.** Operations, auditors and regulators will ask "who decided what, on what evidence, and what would have happened otherwise?". For autonomous operations that record must be complete, linkable and tamper-evident.

**Description.** Append-only, **hash-chained** (SHA-256 over canonical JSON + previous hash), queryable (asset / agent / time / outcome / decision class / correlation id), JSONL export and `verify-chain` API. Entry types: observation, proposal, simulation, decision, action, outcome, veto, approval, override, policy-change, kill-switch, break-glass. Stores **rationale, evidence references and counterfactual impact** and links the chain *observation → proposal → decision → action → outcome* by correlation id.

**Acceptance criteria**
- **AC-14.1 Integrity** — `GET /api/ledger/verify-chain` returns `{valid, entries_checked, head_hash, first_invalid_seq}`; a chain of ≥ 1,000 entries verifies.
- **AC-14.2 Tamper detection** — mutating, deleting or re-ordering any stored entry makes verification fail and report the exact sequence number (three tests).
- **AC-14.3 Append-only** — the API exposes no update/delete; concurrent appends (≥ 20 parallel writers) still form a single linear chain.
- **AC-14.4 Query & export** — filter by asset/agent/class/time/outcome/correlation id; JSONL export re-verifies with the stand-alone `scripts/verify_ledger.py` (no network).
- **AC-14.5 Completeness** — in the 02:14 scenario every autonomous action has the full chain (observation → proposal → simulation → decision → action → outcome) under one correlation id, including the counterfactual (expected vs. do-nothing).
- **AC-14.6 Anchoring** — a periodic *anchor* (head hash + count + timestamp) is written to Blob; verification can check the anchor.

**Azure — target / slice.** *Target:* Cosmos DB (ledger index, change-feed projections), **Azure Blob immutable storage (WORM)** for JSONL segments and anchors, optional **Azure Confidential Ledger** for head attestation, Fabric/ADLS for long-term analytics. *Slice:* hash-chain in Cosmos DB (partitioned by day), JSONL export + anchors in Blob.

**Reference implementation & simulation.** Real: chain, verification, queries, export. Nothing simulated. (Tamper-evidence, not tamper-proof: the anchor/WORM tier in the target closes the gap against a privileged insider.)

**Depends on.** — (foundation). **Enables.** DF-04, DF-10, DF-12, DF-13, DF-16, DF-17, DF-21.

---

#### DF-15 — Lights-Out Readiness Assessment
`Epic C · P1 · FR-C07 · KPIs: KPI-15, KPI-16`

**Why / problem.** Customers do not know where they are on the path to lights-out, and a pilot that starts in the wrong plant fails. A fast, evidence-based assessment is both the diagnostic and the **land motion** for the commercial model.

**Description.** Questionnaire plus **auto-measured signals from the running simulation** (data coverage, data quality, MTBF/MTTR, scrap, automation share, OEE variance, safety-zone coverage…); scores six dimensions — **data, connectivity, automation, safety, process stability, skills** — as a radar (0–100 each, maturity level 1–5); gap analysis; **recommended roadmap** (initiatives with effort, impact, prerequisites, mapped to Nightshift features / Azure services); recommended **autonomy ceiling per decision class**; exportable.

**Acceptance criteria**
- **AC-15.1 Scoring** — deterministic, documented formula; fixtures for low / medium / high maturity plants produce the expected scores.
- **AC-15.2 Measured vs. reported** — ≥ 8 signals are pulled from the running simulator and shown with provenance (`measured` vs `self-reported`); measured values override conflicting self-reports and flag the discrepancy.
- **AC-15.3 Gap analysis** — ≥ 5 prioritised gaps with recommended actions, effort (weeks) and the feature/Azure service that closes each.
- **AC-15.4 Ceilings** — the recommended autonomy ceiling per decision class follows readiness (e.g., Safety < 60 caps physical-action classes at L2) and can be applied to the policy as a draft.
- **AC-15.5 Export** — JSON and Markdown export; re-running after closing gaps shows the score delta.

**Azure — target / slice.** *Target:* assessment web app on Container Apps, plant signals from Eventhouse/OneLake, fleet-wide readiness in Power BI. *Slice:* in-app module using simulator signals.

**Reference implementation & simulation.** Real: scoring, roadmap, export. Simulated: plant signals.

**Depends on.** DF-01, DF-19. **Enables.** the Lights-Out Readiness land motion.

---

### Epic D — Copilot & insight

#### DF-16 — "Ask the Factory" copilot
`Epic D · P0 · FR-D01, FR-D02 · KPIs: KPI-20, KPI-06, KPI-14`

**Why / problem.** The plant manager at 06:00 does not want a dashboard hunt; she wants to ask "why did the Supervisor move the CNC-04 jobs?" and get an answer she can verify.

**Description.** Azure OpenAI tool-calling over KPIs, assets, ledger, twin and what-if; **streaming**; answers carry **citations** to ledger entries and assets (`[ledger:#1234]`, `[asset:CNC-04]`); read-only by default; a "propose action" tool creates a *proposal* that flows through the approval/policy path — the copilot can never execute directly. Tool allow-list, output validation, treats tool data as untrusted, budget-capped.

**Acceptance criteria**
- **AC-16.1 Grounded & cited** — "Why did the Supervisor move jobs to CNC-05?" returns an answer with ≥ 1 citation that resolves to a real ledger entry (API test with the stub; smoke test with the real model).
- **AC-16.2 Tools** — at least `get_kpis`, `get_asset`, `query_ledger`, `run_whatif`, `list_open_proposals`, `propose_action`; tool calls and results are visible to the user (collapsible) and logged.
- **AC-16.3 No direct execution** — `propose_action` creates an inbox item/proposal; no tool path mutates plant state (negative test enumerating the tool registry).
- **AC-16.4 Honesty** — when tools return nothing, the copilot says it does not know instead of inventing numbers (test with empty data).
- **AC-16.5 Prompt-injection resistance** — instructions hidden in an asset name, ledger rationale or work-order text are not obeyed: no tool outside the allow-list is called and no state is mutated (adversarial test).
- **AC-16.6 Latency & budget** — first streamed token ≤ 3 s p95 on the deployed slice (`gpt-5.4-mini`, `reasoning_effort` low/minimal); the daily AI budget cap fails closed with a clear UI message.

**Azure — target / slice.** *Target:* Microsoft Foundry Agent Service with MCP tools over plant APIs, Azure AI Search for SOP/manual/failure-mode grounding, Foundry guardrails (prompt shields, content filters), Entra-scoped on-behalf-of access. *Slice:* Azure OpenAI Responses/Chat tool-calling via the Foundry account (managed identity); offline deterministic stub for tests.

**Reference implementation & simulation.** Real: tool layer, citation resolver, streaming, guardrails. Simulated: none (the data it reads is the simulated plant's).

**Depends on.** DF-03, DF-14, DF-19, DF-13.

---

#### DF-17 — Shift handover & executive digest
`Epic D · P1 · FR-D03 · KPIs: KPI-06, KPI-13, KPI-14`

**Why / problem.** Shift handover is where information is lost; executives want one page, not a console. The 06:00 report — "1 failure avoided, 0 missed due dates, €X saved" — is the artefact that makes the night shift visible and credible.

**Description.** On-demand and scheduled (at shift boundaries) generation from **structured KPI and ledger input** (LLM narration with a deterministic template fallback); sections: headline, KPIs vs. target, decisions (auto vs. approved vs. vetoed), avoided losses with method and confidence, open items, risks for the next shift; HTML/Markdown export.

**Acceptance criteria**
- **AC-17.1 No invented numbers** — an automated check proves every number in the digest appears in (or is derived from) the structured input; failing digests fall back to the template.
- **AC-17.2 Fallback** — with the LLM unavailable the template digest is produced with the same numbers.
- **AC-17.3 Savings logic** — "€X saved" equals the sum of ledger counterfactual impacts for the shift, with the method and a confidence label shown (fixture test).
- **AC-17.4 Scheduling** — digests are generated at each shift boundary (06:00 / 14:00 / 22:00 sim time) and stored; the latest is retrievable via API.
- **AC-17.5 Export** — Markdown and HTML export; pending approvals and escalations are listed.

**Azure — target / slice.** *Target:* Foundry for narration; delivery via Teams/Outlook (Logic Apps) and Power BI paginated reports for the executive view. *Slice:* chat deployment + templates; in-app scheduler.

**Reference implementation & simulation.** Real: generation, validation, scheduling. Simulated: none.

**Depends on.** DF-14, DF-19, DF-13.

---

#### DF-18 — Root-cause analysis assistant
`Epic D · P1 · FR-D04 · KPIs: KPI-01, KPI-09, KPI-06, KPI-12`

**Why / problem.** When something goes wrong, teams lose hours correlating alarms across systems; the first hypothesis is often wrong and the loss repeats.

**Description.** Event correlation using a **temporal causal graph** (events: alarms, state changes, faults, quality excursions, schedule changes; edges from topology + precedence + lag-window evidence), **loss Pareto** (by category/asset/reason), **ranked hypotheses** with evidence; an LLM may only *narrate* the result.

**Acceptance criteria**
- **AC-18.1 Correct ranking** — for seeded faults with known cause (e.g., compressor pressure drop → downstream CNC alarms) the true root cause ranks #1 in ≥ 80 % and top-3 in ≥ 95 % of ≥ 20 seeded cases.
- **AC-18.2 Reconciliation** — Pareto totals reconcile exactly with total loss time in the KPI engine.
- **AC-18.3 Evidence** — each hypothesis lists the supporting events (timestamps, lag) and a confidence; weak-evidence hypotheses are labelled.
- **AC-18.4 Offline** — fully functional without an LLM (deterministic narration).
- **AC-18.5 Actionability** — a hypothesis can be turned into a proposal (e.g., inspect compressor) via the inbox path.

**Azure — target / slice.** *Target:* Eventhouse (KQL time-series and graph functions) and Azure ML for learned causal models; Foundry for narration. *Slice:* Python temporal graph and Pareto over the ledger/event store.

**Reference implementation & simulation.** Real: graph, scoring, Pareto. Simulated: the event stream.

**Depends on.** DF-01, DF-02, DF-14, DF-19.

---

#### DF-19 — KPI engine
`Epic D · P0 · FR-D05 · KPIs: measures KPI-01…09`

**Why / problem.** Every claim in this product — from the 06:00 report to the ROI model — rests on KPIs that mean the same thing everywhere. Definitions must be explicit and tested.

**Description.** OEE (A×P×Q), throughput, FPY, scrap, MTBF/MTTR, OTIF, energy and CO2e per unit, **$ impact**; per asset / line / plant, for windows (shift / day / week / custom), with trends and persisted snapshots; loss tree (availability, performance, quality losses) for RCA and A/B.

**Acceptance criteria**
- **AC-19.1 Formulae** — OEE = Availability × Performance × Quality on hand-computed fixtures; planned production time and ideal cycle time are explicit inputs.
- **AC-19.2 Windows & roll-ups** — shift/day/week aggregations and asset→line→plant roll-ups are exact (weighted, not averaged averages).
- **AC-19.3 Persistence** — snapshots are stored through the repository interface and reloaded after restart; trends reproduce.
- **AC-19.4 $ impact** — documented attribution (downtime hours × cost/hour, scrap × unit cost, energy × tariff, late orders × penalty) consistent with ledger counterfactuals.
- **AC-19.5 Performance** — `GET /api/kpis?scope=plant` ≤ 200 ms p95 at KAT-1 scale; loss tree sums to total time.

**Azure — target / slice.** *Target:* Eventhouse KQL materialised views + Power BI semantic model (Direct Lake on OneLake). *Slice:* Python KPI engine; snapshots in Cosmos DB.

**Reference implementation & simulation.** Real: all maths. Simulated: the source data.

**Depends on.** DF-01, DF-02. **Enables.** DF-09, DF-15, DF-17, DF-18, DF-20, DF-21, DF-22.

---

### Epic E — Platform & business value

#### DF-20 — Control Tower UI
`Epic E · P0 · FR-E01, FR-E08 · KPIs: KPI-14, KPI-10, KPI-15`

**Why / problem.** Humans-on-the-loop need situational awareness in seconds and levers they trust. The control tower is also where executives *see* the swarm work.

**Description.** Dark "control-room" web UI (React + Vite + TypeScript): live **plant map (SVG)** with machine cards, KPI tiles, **agent activity stream**, **scenario/fault console** (inject faults, time controls), **Autonomy Dial**, approvals inbox, ledger explorer, twin what-if panel, copilot panel; **Feature Map** page (`/features`) rendered from `GET /api/features`; permanent "Synthetic data / simulated environment" indicator; responsive and accessible.

**Acceptance criteria**
- **AC-20.1 One-screen story** — every panel above is reachable within ≤ 2 clicks from the main view; the 02:14 narrative is runnable end-to-end by a scripted Playwright test (inject bearing wear → alert → what-if → policy auto-approval at L4 → ledger entry → 06:00 shift report) and yields the screenshots for the deck.
- **AC-20.2 Live** — state, activity stream and KPI tiles update without reload; staleness ≤ 2 s at 1× speed.
- **AC-20.3 Accessibility** — keyboard-operable inbox and dial, visible focus, WCAG 2.2 AA contrast; axe-core scan reports 0 critical/serious violations on the main views; `prefers-reduced-motion` respected.
- **AC-20.4 Responsive** — usable from 1024 px to 1920 px wide.
- **AC-20.5 Feature Map** — `/features` lists all 25 Release-1 features (ID, name, status, link to its screen) from the registry; clicking opens the feature's UI route.
- **AC-20.6 Honest simulation** — the synthetic-data indicator is visible on every view and tied to `/api/meta`.
- **AC-20.7 Bundled** — no runtime third-party/CDN fetches (CSP-checked).

**Azure — target / slice.** *Target:* Container Apps (or Static Web Apps) behind Azure Front Door + WAF with Entra ID sign-in; Power BI embedded for fleet analytics. *Slice:* SPA served by FastAPI from the single Container App.

**Reference implementation & simulation.** Real: UI and its APIs. Simulated: plant behind it.

**Depends on.** every API feature. 

---

#### DF-21 — Value realization & ACR/ROI calculator
`Epic E · P0 · FR-E02, FR-E03 · KPIs: KPI-21, KPI-22`

**Why / problem.** Executives buy outcomes, not architectures. This feature turns the swarm's behaviour into **measured, repeatable evidence** and converts it into the CFO's language (NPV, payback) and Microsoft's (Azure consumption).

**Description.** (a) **A/B replay:** N seeds × {swarm OFF, swarm ON} over the same scenario horizon (same order book, noise streams and fault schedule; baseline = FIFO pull, run-to-failure maintenance, periodic manual QC, min/max reorder); paired deltas with **confidence intervals for twelve metrics** — downtime, late orders, tardiness, total loss, OEE, effective energy price, absolute energy cost, energy per unit-operation, scrap, customer escapes, OTIF and good units shipped — *all reported, including those that are worse or not significant*. (b) **Business-case calculator** (plants, revenue, downtime cost/hour, labour rates, discount rate, adoption ramp …) using the **vendored** `business-case/model.py` + `assumptions.json` → customer ROI, payback, NPV, IRR, sensitivity (tornado) and **Azure ACR by service family, year and plant tier**. A *measured-to-assumed bridge* can pre-fill calculator inputs from the A/B result, clearly flagged "measured in simulation — validate on customer data".

**Acceptance criteria**
- **AC-21.1 Measured uplift (simulation evidence, reported without selection)** — with ≥ 10 seeds the A/B reports **every** metric with a 95 % CI, paired by seed. *Revised after the evidence:* on the synthetic plant the swarm-ON arm is significantly better for unplanned downtime, late orders, order tardiness, total loss, OEE and the effective energy price (16 seeds: −79 %, −20 %, −18 %, −31 %, +13.5 pts, −10 %). Absolute energy cost (+6 %, worse), energy per unit-operation, scrap, customer escapes, OTIF and good units shipped are reported as measured — not significant, or worse. The run is reproducible (same seeds ⇒ same numbers, bit-identical on laptop and container) and is labelled "simulation evidence on synthetic assumptions", never a customer guarantee.
- **AC-21.2 Parity** — for Conservative / Base / Upside the calculator reproduces `business-case/outputs.json` within 0.5 % (unit test on the vendored model).
- **AC-21.3 Overrides** — documented override keys (plants, revenue, downtime cost/hour, labour rates, discount rate, adoption ramp…) change results deterministically; out-of-range or malformed inputs are rejected with a clear message.
- **AC-21.4 ACR view** — ACR table by service family × year, by plant tier (pilot / 1 plant / 8 plants / 25-plant enterprise) and the pull-through ratio match `outputs.json`.
- **AC-21.5 Export** — results export as JSON/CSV/Markdown including inputs and the assumptions version.
- **AC-21.6 Responsiveness** — an A/B run of the default size completes within the HTTP timeout or runs as a job with progress (never blocks the event loop; bounded concurrency). *Achieved:* 10 seeds × 8 h take 2.2 s on a laptop but **≈ 41 s on the 0.5 vCPU container**, so the replay runs as a background job in a **separate worker process** with progress polling (a thread-based first version starved the health probes and restarted the container — fixed, REPORT §9).
- **AC-21.7 Expansion levers (model v1.1)** — the five lever switches (`exp_vision_adoption`, `exp_hf_adoption`, `exp_sim_adoption`, `exp_dp_adoption`, `exp_sec_adoption`) are accepted as overrides; with all five at 0 the Base and Conservative results equal their v1.0 values; the ACR view shows ACR by lever (core, E1–E5) and the expansion tiers including the 100-plant enterprise fleet, matching `acr.by_lever` and `expansion.tiers` in `outputs.json`.

**Azure — target / slice.** *Target:* A/B replays as batch jobs (Container Apps jobs / AKS / Azure Batch) over historian replays in Fabric; calculators embedded in Power BI/web; Azure Retail Prices API refresh pipeline for unit prices. *Slice:* the A/B runner as a background job in a separate worker process with progress polling (10 seeds ≈ 41 s on the 0.5 vCPU container) and the vendored model (the `model.py`/`assumptions.json`/`outputs.json` trio is byte-identical to `business-case/`, enforced by a test).

**Reference implementation & simulation.** Real: A/B statistics, calculator, model. Simulated: plant dynamics; benefit assumptions flagged *Assumption* until validated on customer data.

**Evidence note (what the simulation supports).** The A/B supports mechanisms for three benefit categories only — unplanned downtime, OEE/throughput and late-delivery cost (44 % of the Base risk-adjusted benefit). Scrap, maintenance, energy, indirect labour, inventory, expedite and capex deferral are **benchmark/assumption-only** (56 %); energy is a tariff-aware price effect, not lower consumption. Classification and stress tests: PRD §10.3 and §11.1. *Known gap:* the calculator does not yet label each benefit category with its evidence class (shown in the PRD and the deck); candidate for R1.5.

**Expansion note (model v1.1).** The shared model now includes five optional *expansion levers* (E1 machine vision, E2 kHz condition monitoring, E3 continuous sim-first what-if, E4 enterprise data platform, E5 OT security and connectivity) with their own Azure meters, costs and benefits. They are off in Base and Conservative and on in Upside; Base ACR is $0.68 M in Year 3 ($0.91 M run-rate at 8 plants), the expansion case $1.28 M ($1.87 M), a 100-plant fleet $21.2 M. The lever economics are assumptions to validate; the calculator exposes the switches so a customer can turn on only the levers it needs.

**Depends on.** DF-01, DF-04, DF-19. 

---

#### DF-22 — Multi-plant fleet
`Epic E · P1 · FR-E04 · KPIs: KPI-02, KPI-09, KPI-15`

**Why / problem.** Value compounds across plants: a failure signature learned in Plant 1 should protect Plant 8 on day 1; executives need one view and fair benchmarks.

**Description.** ≥ 3 simulated plants with different profiles (e.g., KAT-1 precision machining + molding; a high-mix heavy-machining plant; a high-volume assembly/test plant), fleet KPIs, **benchmarking** normalised by plant type, **cross-plant playbook sharing** (failure signatures, policy templates), per-plant overrides inside fleet guardrails.

**Acceptance criteria**
- **AC-22.1 Independence** — ≥ 3 plants run concurrently with independent seeded state and per-plant policy.
- **AC-22.2 Fleet roll-ups** — fleet KPIs equal exact weighted roll-ups of the plant KPIs.
- **AC-22.3 Learning transfer** — a bearing-wear signature learned at plant A is published to the fleet; plant B's PdM detects the same fault earlier than without it (seeded comparison, lead time improvement reported).
- **AC-22.4 Benchmarking** — OEE/downtime/energy benchmarks are normalised by plant type and show rank and gap-to-best.
- **AC-22.5 Guardrails** — a plant-level policy override can tighten but never loosen a fleet cap (test).

**Azure — target / slice.** *Target:* hub-and-spoke landing zones per region, per-plant Arc-enabled edge, Fabric workspaces per plant + enterprise, Event Hubs per region, fleet policy via GitOps. *Slice:* 3 simulated plants in one process, namespaced storage.

**Reference implementation & simulation.** Real: fleet logic, sharing, benchmarking. Simulated: plants.

**Depends on.** DF-01, DF-05, DF-12, DF-19.

---

#### DF-23 — Identity & RBAC
`Epic E · P1 · FR-E05 · KPIs: KPI-19`

**Why / problem.** Who may change autonomy, approve a restart, reset the kill switch or read the ledger is as important as what the agents do. OT/Cyber leads have veto power on any purchase.

**Description.** Roles **Operator, Engineer, Plant Manager, Auditor, Admin** enforced in the API (Entra-ready JWT validation + demo role switcher); audit of privileged actions in the ledger.

**Acceptance criteria**
- **AC-23.1 Permission matrix** — role × representative endpoint tests (allowed/denied) match the documented matrix (Operator: acknowledge/approve low-risk; Engineer: what-if, maintenance/planning approvals; Plant Manager: all approvals, dial within bounds; Auditor: read-only incl. ledger verify/export; Admin: policy publish, kill-switch reset, role mapping).
- **AC-23.2 JWT validation** — with locally generated keys: expired, wrong audience, wrong issuer, bad signature and missing role claim are all rejected; OIDC discovery/JWKS caching is unit-tested with a fake issuer.
- **AC-23.3 Demo mode** — the demo role switcher works only when `AUTH_MODE=demo`; with `AUTH_MODE=entra` it is rejected.
- **AC-23.4 Privileged-action audit** — policy change, dial change, kill switch, break-glass, approvals and ledger export always create ledger entries with actor and role.
- **AC-23.5 Separation of duties** — break-glass and policy publication require two distinct identities (test).

**Azure — target / slice.** *Target:* Microsoft Entra ID (app roles, groups, Conditional Access, PIM), Entra Agent ID for agent identities, managed identities for service-to-service. *Slice:* JWT validation module + demo role switcher; one user-assigned managed identity for Azure resources.

**Reference implementation & simulation.** Real: authorisation and validation. Simulated: the identity provider in demo mode.

**Expansion note (lever E5, business-case v1.1).** At fleet scale identity sits inside a hardened OT connectivity and security layer — a diverse ExpressRoute path per plant, Azure Firewall Premium regional hubs, Defender for Servers on Arc-enabled OT servers and Sentinel OT-log ingestion (≈ $224 k a year at 8 plants). A risk and compliance lever, not a payback lever; delivered by roadmap item DF-31. Defender for IoT OT licences are Microsoft 365 licences, not Azure consumption.

**Depends on.** DF-14. 

---

#### DF-24 — Observability & FinOps
`Epic E · P1 · FR-E06 · KPIs: KPI-17, KPI-18`

**Why / problem.** An autonomous system that cannot be observed, and whose AI cost cannot be bounded, will not survive its first review.

**Description.** OpenTelemetry → Application Insights (+ Log Analytics), structured JSON logs with request/correlation ids, per-agent latency and decision counters, an **LLM token/$ meter** with budget status, health endpoints (`/healthz`, `/readyz`, `/api/meta`, `/api/usage`), saved KQL queries/workbook definition.

**Acceptance criteria**
- **AC-24.1 Health** — `/healthz` needs no dependencies; `/readyz` returns per-dependency JSON (Cosmos, Storage, Azure OpenAI) and HTTP 503 when a required dependency is down (fault-injected test).
- **AC-24.2 Usage meter** — `GET /api/usage` reports tokens by deployment, $ estimate (from a price table with source/date) and budget status; the daily cap fails closed with a clear message.
- **AC-24.3 Correlation** — a decision's logs and spans share one correlation id across agent → supervisor → what-if → policy → action; PII is redacted in logs (test).
- **AC-24.4 Metrics** — per-agent proposal count, cycle latency and supervisor outcome counters are exported; the smoke test confirms they arrive in Application Insights (query evidence in the REPORT).
- **AC-24.5 Unit economics** — the UI/API shows Azure + AI cost per plant-day estimate derived from the usage meter.

**Azure — target / slice.** *Target:* Azure Monitor (App Insights, Log Analytics, Managed Grafana), Container insights, Cost Management + FinOps tooling with per-plant tags. *Slice:* `azure-monitor-opentelemetry` → App Insights; in-app usage meter.

**Reference implementation & simulation.** Real. Nothing simulated.

**Expansion note (model v1.1).** The FinOps meters are what will measure the expansion levers' consumption in a customer tenant — image and waveform archive growth, simulation node-hours, Fabric capacity, ExpressRoute and firewall hubs — against the model's per-lever run-rate (`acr.by_lever`) using the per-plant cost-allocation tags.

**Depends on.** — (cross-cutting).

---

#### DF-25 — IaC & deployment
`Epic E · P0 · FR-E07, FR-E08 · KPIs: KPI-17, KPI-18, KPI-15`

**Why / problem.** "Works on my laptop" is not a reference implementation. Repeatable, keyless, secure-by-default infrastructure is how this scales to a customer landing zone.

**Description.** Bicep modules + `azure.yaml` (azd) creating the resource group with the required governance tags, Container Apps environment/app, Cosmos DB serverless with Entra RBAC, Storage (Entra only, no shared key), Foundry (AIServices) account with sequentially created model deployments, ACR (remote build), Log Analytics/App Insights, one user-assigned managed identity and role assignments; optional Entra authentication switch; smoke tests; teardown.
*Demo governance note:* the demo subscription is a managed sandbox that carries exemption tags (`SecurityControl=Ignore`, `SecurityExemption=StorageAccountKeyAccess`, `project=SwarmAI`, `concept=dark-factory`, `owner=michalfu`, `environment=demo`); production landing zones use private endpoints and policy-compliant patterns instead (see ARCHITECTURE.md).

**Acceptance criteria**
- **AC-25.1 Build** — `az bicep build` succeeds for all modules; `az deployment sub what-if` is clean on the second run (idempotent).
- **AC-25.2 From scratch** — `azd provision && azd deploy` (or `azd up --no-prompt`) yields a healthy `/readyz` with all dependencies green.
- **AC-25.3 Smoke** — `scripts/smoke_test.py --base-url <url>` exercises every Release-1 feature on Azure, prints a PASS/FAIL table and exits non-zero on failure; AI spend per run < US$1.
- **AC-25.4 Keyless** — a grep gate finds no keys, connection strings or SAS tokens in code, IaC, env vars or outputs; Cosmos and AIServices have local auth disabled; Storage has shared-key access off.
- **AC-25.5 Teardown & rebuild** — documented teardown (`azd down --purge --force` or RG delete) works and a re-provision restores service.
- **AC-25.6 Guardrails** — per-IP/global rate limits, request-size limits and the daily AI budget are configured via env/Bicep parameters; ACA `minReplicas` ≥ 1 for the simulation, `maxReplicas` ≤ 3.

**Azure — target / slice.** *Target:* Azure Landing Zone (hub-and-spoke), GitHub Actions/Azure DevOps with OIDC federation, Azure Policy, Defender for Cloud, private endpoints. *Slice:* azd + Bicep, remote build in ACR.

**Reference implementation & simulation.** Real: deployment to the demo subscription.

**Depends on.** all.

---

## 4. Release 2+ roadmap (not part of the Release-1 contract)

Sequencing logic: **R1.5 "Pilot-ready"** closes the gap between the reference slice and a first customer pilot on real equipment; **R2 "Scale"** makes many plants and many policies manageable;
**R3 "Lights-out at scale"** adds network-level optimisation and regulatory evidence automation. *Roadmap items describe SwarmAI's product intent; they are not commitments by Microsoft or any partner, and depend on the Azure services named being available in the customer's region.*

| ID | Item | Release | Epic | Value / description | Azure services (target) | Builds on |
|----|------|---------|------|---------------------|-------------------------|-----------|
| DF-26 | Edge connector pack & local inference | R1.5 | A | OPC UA / MQTT connectors, store-and-forward, local ONNX inference and edge-resident Sentinel on real equipment | Azure IoT Operations, Arc-enabled Kubernetes, Azure ML (ONNX) | DF-02, DF-05, DF-10 |
| DF-27 | Fabric Real-Time Intelligence & OneLake integration | R1.5 | A/D | Eventstream → Eventhouse → Activator rules, OneLake history, Power BI semantic model | Fabric RTI, OneLake, Power BI, Event Hubs | DF-02, DF-19 |
| DF-28 | MES / ERP / CMMS write-back connectors | R1.5 | B/E | Work orders, schedules and reorders written to SAP, Siemens Opcenter, Rockwell, AVEVA, Dynamics 365 SCM through certified connectors | Logic Apps / API Management, Service Bus | DF-05, DF-07, DF-08 |
| DF-29 | Actionable Teams approvals | R1.5 | C | Bot-based Adaptive Card actions (approve/modify/reject in Teams), mobile push, escalation by call/SMS | Teams, Bot Service / Workflows, Logic Apps | DF-13 |
| DF-30 | Enterprise identity & agent identities | R1.5 | E | Entra app roles, Conditional Access, PIM-backed break-glass, Entra Agent ID for agents | Microsoft Entra ID, PIM | DF-23 |
| DF-31 | Private-networking landing zone & OT security integration | R1.5 | E | Private Link, ExpressRoute/VPN, NSP, Defender for IoT sensors, Sentinel analytics for agent activity | Private Link, Defender for IoT / Cloud, Microsoft Sentinel | DF-25 |
| DF-32 | Signed policy bundles & degraded-mode autonomy | R1.5 | C | Policy distribution to edge with signature check; autonomy ceiling drops automatically when the policy cache is stale or cloud is unreachable | Arc GitOps, Key Vault | DF-12 |
| DF-33 | Twin calibration from plant history | R2 | A | System-identification fits degradation, cycle-time and energy models to historian data; calibration report per plant | Azure ML, Fabric/OneLake | DF-01, DF-03 |
| DF-34 | Agent evaluation & LLMOps harness | R2 | B/E | Scenario library, offline replay, regression gates in CI, red-team packs, model-version A/B | Foundry evaluations, GitHub Actions | DF-04, DF-21 |
| DF-35 | Twin model exchange (ISA-95 / OPC UA companion specs) | R2 | A | Import/export of asset models to Fabric digital twin builder / Azure Digital Twins (DTDL) | Azure Digital Twins, Fabric | DF-03 |
| DF-36 | Supplier collaboration agent | R2 | B | ASN/EDI ingestion, supplier risk scoring, automated expedite negotiation within policy | Logic Apps, Foundry | DF-08 |
| DF-37 | Workforce & skills agent | R2 | B | Shift rosters, skills matrix, remote-operator workload balancing; **no individual performance monitoring** by design | Foundry, Teams | DF-13 |
| DF-38 | Robot & AMR fleet orchestration | R2 | B | VDA 5050 / ROS 2 bridges and robot-cell twins | IoT Operations, Container Apps | DF-08 |
| DF-39 | Fleet policy management at scale | R2 | C/E | Inheritance (enterprise → region → plant), drift detection, policy rollout rings | Arc GitOps, Azure Policy (cloud side) | DF-12, DF-22 |
| DF-40 | Federated playbook exchange | R2 | E | Privacy-preserving sharing of failure signatures and recipes across plants/customers | Azure ML, Confidential computing | DF-22 |
| DF-41 | Cross-plant network optimisation | R3 | B | Allocate orders across plants by capacity, energy, carbon and logistics | Foundry, solver on Container Apps | DF-07, DF-22 |
| DF-42 | Continuous resilience drills | R3 | A/E | Automated fault-injection "game days" in the twin that test policies and people | Container Apps jobs | DF-01, DF-34 |
| DF-43 | Sustainability reporting pack | R3 | D | Hourly Scope 2 matching and emission data for CSRD/ESRS reporting | Fabric, Power BI | DF-09 |
| DF-44 | Regulatory evidence pack | R3 | C/E | Auto-generated EU AI Act technical documentation inputs, ISO/IEC 42001 and IEC 62443 control mappings from ledger and policy history | Fabric, Purview | DF-14, DF-12 |
| DF-45 | Policy verification & safety-case generator | R3 | C | Model-check policy sets against hazard-analysis assumptions; produce a reviewable safety-case skeleton (does not replace certified safety engineering) | Azure ML / Container Apps | DF-10, DF-12 |
| DF-46 | Agent-assisted line commissioning | R3 | B | Recipe transfer and set-up checklists for new lines/products | Foundry | DF-11, DF-33 |

**Where the business-case expansion levers (E1–E5, model v1.1) land.** E1 machine-vision fleet → DF-06, DF-26 (edge inference) · E2 high-frequency condition monitoring → DF-05, DF-26, DF-27 · E3 continuous sim-first what-if at scale → DF-03, DF-33, DF-42 · E4 enterprise data-platform modernisation → DF-02, DF-19, DF-27 · E5 OT security and connectivity hardening → DF-23, DF-31. These are modelled in `business-case/` for ROI and ACR; they do not add or change any Release-1 feature.

## 5. KPI catalogue (used in the "KPIs moved" lines and the traceability matrix)

Targets, baselines and the measurement plan are in [PRD.md](PRD.md) §"Success metrics"; business-case values are in [business-case/outputs.md](business-case/outputs.md).

| ID | KPI | Definition (short) | Better | Measured by |
|----|-----|--------------------|--------|-------------|
| KPI-01 | Unplanned downtime | Hours of unplanned DOWN per asset-year, and % of scheduled production time | ↓ | DF-19 |
| KPI-02 | OEE | Availability × Performance × Quality | ↑ | DF-19 |
| KPI-03 | Scrap, rework & FPY | Scrapped/reworked units ÷ units started; first-pass yield | ↓ / ↑ | DF-19 |
| KPI-04 | On-time-in-full & tardiness | % orders shipped complete by due date; mean/weighted tardiness | ↑ / ↓ | DF-19 |
| KPI-05 | Energy cost & CO2e per unit | Energy $ and kg CO2e per good unit | ↓ | DF-19, DF-09 |
| KPI-06 | Indirect-labour effort | Planning, supervision, QA and reporting hours per 1,000 units | ↓ | PRD measurement plan |
| KPI-07 | Inventory & working capital | WIP + FG days of inventory; stock-outs | ↓ | DF-19, DF-08 |
| KPI-08 | Expedite & premium freight | Spend on expedited supply/shipping | ↓ | DF-08 |
| KPI-09 | Maintenance effectiveness | Planned-work ratio, MTBF, MTTR, maintenance cost | ↑ / ↓ | DF-19 |
| KPI-10 | Autonomy ratio | % of decisions executed inside policy without human touch; override rate | ↑ / ↓ | DF-12, DF-14 |
| KPI-11 | Safety | Agent-attributable safety incidents (target 0); safe-stop latency; veto compliance (100 %) | 0 / ↓ / 100 % | DF-10 |
| KPI-12 | Decision latency | Detect → action p95; what-if turnaround | ↓ | DF-04, DF-24 |
| KPI-13 | Explainability & integrity | % decisions with rationale + counterfactual; ledger verification success | 100 % | DF-14 |
| KPI-14 | Human-on-the-loop responsiveness | Approval-SLA attainment; time-to-decision p50/p95 | ↑ / ↓ | DF-13 |
| KPI-15 | Time-to-value | Weeks from assessment to first autonomous shift; days to onboard a plant | ↓ | DF-15, DF-25 |
| KPI-16 | Readiness score | Lights-Out Readiness (0–100) and gap closure rate | ↑ | DF-15 |
| KPI-17 | Platform reliability | Availability, error rate, platform MTTR | ↑ / ↓ | DF-24 |
| KPI-18 | Unit economics | Azure + AI cost per plant-day and per decision | ↓ | DF-24 |
| KPI-19 | Security & compliance posture | RBAC coverage, privileged-action audit coverage, policy conformance | 100 % | DF-23, DF-12 |
| KPI-20 | Copilot quality | Grounded-answer rate, citation validity, time-to-first-token | ↑ / ↓ | DF-16 |
| KPI-21 | Value proof | A/B uplift with 95 % CI excluding 0; calculator/outputs parity | ✔ | DF-21 |
| KPI-22 | Azure consumption | ACR run-rate per plant (core and with expansion levers); ACR by lever; pull-through ratio | ↑ | DF-21 |

## 6. Traceability matrix (feature → PRD requirement → KPI)

### 6.1 PRD functional-requirement index

| FR | Requirement (short form — full text in PRD §"Functional requirements") | Features |
|----|-----------------------------------------------------------------------|----------|
| FR-A01 | Seeded, deterministic plant simulation (state machine, degradation, sensors, quality, energy, tariff/carbon) | DF-01 |
| FR-A02 | Fault-injection library (9 faults) and scripted scenarios | DF-01 |
| FR-A03 | Time control, snapshot/restore, validated control API | DF-01 |
| FR-A04 | ISA-95 Unified Namespace with validated message schema | DF-02 |
| FR-A05 | Pluggable telemetry sources (sim, HTTP; MQTT / Event Hubs / IoT Operations adapters) | DF-02 |
| FR-A06 | Time-series retention, downsampling, persistence, live streaming | DF-02 |
| FR-A07 | Live asset graph; fork-and-simulate-ahead what-if | DF-03 |
| FR-B01 | Perceive→propose agent runtime with evidence-bearing proposals | DF-04 |
| FR-B02 | Conflict detection, explainable utility arbitration, sim-first validation | DF-04, DF-03 |
| FR-B03 | Failure prediction with RUL; maintenance in planned windows | DF-05 |
| FR-B04 | SPC, drift detection, bounded compensation, lot containment | DF-06 |
| FR-B05 | Vision inspection with human review of low-confidence calls | DF-06 |
| FR-B06 | Finite-capacity planning and continuous re-planning, explained | DF-07 |
| FR-B07 | Inventory, reorder, AMR dispatch, supplier-delay mitigation, kitting | DF-08 |
| FR-B08 | Energy/carbon-aware load shifting and peak shaving | DF-09 |
| FR-B09 | Safety zones, intrusion response, forbidden setpoints, veto, cyber hygiene | DF-10 |
| FR-B10 | Bounded process optimisation with rollback | DF-11 |
| FR-C01 | Autonomy levels L0–L5 per decision class | DF-12 |
| FR-C02 | Deterministic policy-as-code (risk, thresholds, blast radius, time-boxing, break-glass, kill switch) | DF-12 |
| FR-C03 | Approval/escalation queue with SLA timers | DF-13 |
| FR-C04 | Teams notification of approvals | DF-13 |
| FR-C05 | Tamper-evident, queryable, exportable decision ledger | DF-14 |
| FR-C06 | Rationale, evidence and counterfactual with every decision | DF-14, DF-04 |
| FR-C07 | Lights-Out Readiness Assessment and roadmap | DF-15 |
| FR-D01 | Grounded, cited, streaming copilot | DF-16 |
| FR-D02 | Copilot acts only through the approval/policy path | DF-16 |
| FR-D03 | Shift handover and executive digest with verified numbers | DF-17 |
| FR-D04 | Root-cause analysis with ranked, evidenced hypotheses | DF-18 |
| FR-D05 | Consistent manufacturing KPI engine incl. $ impact | DF-19 |
| FR-E01 | Control tower UI (situational awareness + levers) | DF-20 |
| FR-E02 | Counterfactual A/B replay with confidence intervals | DF-21 |
| FR-E03 | ROI/NPV/payback and ACR calculator from the shared model | DF-21 |
| FR-E04 | Multi-plant fleet, benchmarking, playbook sharing | DF-22 |
| FR-E05 | RBAC, Entra-ready authentication, privileged-action audit | DF-23 |
| FR-E06 | Observability and FinOps (traces, metrics, health, AI cost meter, budget cap) | DF-24 |
| FR-E07 | Deployable, testable, removable infrastructure as code | DF-25 |
| FR-E08 | Feature registry / Feature Map; transparent synthetic-data indication | DF-20, DF-25 |

### 6.2 Feature → requirement → KPI

| Feature | PRD requirement(s) | Primary KPIs | Persona(s) served |
|---------|--------------------|--------------|-------------------|
| DF-01 Factory simulator | FR-A01, FR-A02, FR-A03 | enables KPI-01…09, KPI-21 | Process Engineer, all (demo) |
| DF-02 Telemetry & UNS | FR-A04, FR-A05, FR-A06 | KPI-12, KPI-16 | OT/Cyber lead, Process Engineer |
| DF-03 Twin & what-if | FR-A07, FR-B02 | KPI-12, KPI-11, KPI-13 | Plant Manager, Process Engineer |
| DF-04 Swarm runtime & Supervisor | FR-B01, FR-B02, FR-C06 | KPI-10, KPI-12, KPI-13, KPI-04 | Plant Manager, COO |
| DF-05 Predictive Maintenance | FR-B03 | KPI-01, KPI-09, KPI-12 | Maintenance Lead |
| DF-06 Quality Guardian | FR-B04, FR-B05 | KPI-03, KPI-06 | Quality Manager |
| DF-07 Production Planner | FR-B06 | KPI-04, KPI-02, KPI-06 | Supply-chain Planner, Plant Manager |
| DF-08 Materials & Logistics | FR-B07 | KPI-07, KPI-08, KPI-04 | Supply-chain Planner |
| DF-09 Energy & Sustainability | FR-B08 | KPI-05 | Plant Manager, CFO |
| DF-10 Safety Sentinel | FR-B09 | KPI-11, KPI-19 | OT/Cyber lead, Plant Manager |
| DF-11 Process Optimizer | FR-B10 | KPI-02, KPI-03, KPI-05 | Process Engineer |
| DF-12 Autonomy Dial & policy | FR-C01, FR-C02 | KPI-10, KPI-11, KPI-19 | COO, OT/Cyber lead |
| DF-13 Human-on-the-loop inbox | FR-C03, FR-C04 | KPI-14, KPI-10 | Remote Operator, Plant Manager |
| DF-14 Decision Ledger | FR-C05, FR-C06 | KPI-13, KPI-19 | Auditor, OT/Cyber lead, CFO |
| DF-15 Lights-Out Readiness | FR-C07 | KPI-15, KPI-16 | COO, Plant Manager |
| DF-16 "Ask the Factory" | FR-D01, FR-D02 | KPI-20, KPI-06, KPI-14 | Plant Manager, Remote Operator |
| DF-17 Shift handover & digest | FR-D03 | KPI-06, KPI-13, KPI-14 | Plant Manager, COO |
| DF-18 Root-cause assistant | FR-D04 | KPI-01, KPI-09, KPI-06, KPI-12 | Maintenance Lead, Process Engineer |
| DF-19 KPI engine | FR-D05 | KPI-01…KPI-09 (measurement) | all |
| DF-20 Control Tower UI | FR-E01, FR-E08 | KPI-14, KPI-10, KPI-15 | Plant Manager, Remote Operator |
| DF-21 Value realization & ACR/ROI | FR-E02, FR-E03 | KPI-21, KPI-22 | CFO, COO, Microsoft/partner |
| DF-22 Multi-plant fleet | FR-E04 | KPI-02, KPI-09, KPI-15 | COO |
| DF-23 Identity & RBAC | FR-E05 | KPI-19 | OT/Cyber lead, Auditor |
| DF-24 Observability & FinOps | FR-E06 | KPI-17, KPI-18 | CIO, Platform owner |
| DF-25 IaC & deployment | FR-E07, FR-E08 | KPI-17, KPI-18, KPI-15 | CIO, Platform owner |

### 6.3 Business-case expansion levers → features → KPIs (model v1.1; no new Release-1 features)

| Lever | Lands in feature(s) | PRD | KPIs moved | Benefit category in the model |
|-------|---------------------|-----|------------|-------------------------------|
| E1 Machine-vision fleet | DF-06 (R1.5: DF-26) | §11.5 | KPI-03, KPI-06, KPI-22 | scrap and escape cost; inspection labour |
| E2 High-frequency condition monitoring | DF-05 (R1.5: DF-26, DF-27) | §11.5 | KPI-01, KPI-09, KPI-22 | extra downtime reduction; maintenance spend |
| E3 Continuous sim-first what-if at scale | DF-03 (R2: DF-33, R3: DF-42) | §11.5 | KPI-10, KPI-12, KPI-22 | labour, energy, throughput (higher autonomy earned) |
| E4 Enterprise data-platform modernisation | DF-02, DF-19 (R1.5: DF-27) | §11.5 | KPI-18, KPI-22 | avoided historian/BI licences, analytics productivity |
| E5 OT security and connectivity hardening | DF-23 (R1.5: DF-31) | §11.5 | KPI-19, KPI-22 | expected cyber-loss and insurance premium |

