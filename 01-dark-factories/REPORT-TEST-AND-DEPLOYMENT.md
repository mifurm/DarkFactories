# SwarmAI Dark Factory ("Nightshift") — Test and Deployment Report

Reference implementation of **all 25 Release-1 features (DF-01 … DF-25)**, deployed to Azure and verified on the live URL.
All numbers below were measured in this session (clock of the build environment: 2026-11-17/18); commands to reproduce them are at the end.

| | |
|---|---|
| **Live URL** | <https://ca-nightshift.blackforest-a28408f9.swedencentral.azurecontainerapps.io> (SPA at `/`, API docs at `/docs`, health at `/healthz`, readiness at `/readyz`) |
| **Resource group** | `rg-swarmai-darkfactory` (swedencentral, subscription `1217c203-6c76-47b4-b61c-9bba62dc8e02`), azd environment `nightshift` |
| **Build on the live site** | `ca-nightshift--azd-1794963538` (shown in the footer of the SPA and in `/api/meta`) |
| **Mode** | `azure` — real Azure OpenAI (`gpt-5.4-mini` chat, `gpt-5.4` reasoning), real Cosmos DB, real Blob Storage, all over the user-assigned managed identity (no keys anywhere) |
| **Business-case model** | v1.1.0 (`business-case/model.py`, `assumptions.json`, `outputs.json`, vendored together, byte-identical — enforced by a test) |

## 1. Definition-of-done status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | All DF-01…DF-25 implemented (backend + API + UI + tests); `/api/features` lists them as implemented; Feature Map shows them | ✔ | 25/25 `implemented` (`/api/features`, smoke #4, E2E "feature map: 25/25"); 127 API operations in 123 paths; 26 UI routes (crawl 26/26 clean) |
| 2 | Brief's behavioural tests exist and pass; ≥ 80 % coverage of domain logic; ruff clean; typecheck/build passes; Playwright E2E passes | ✔ | 113 pytest tests pass, **93 % line coverage**; ruff check + format clean; mypy clean (sim + core); `tsc --noEmit` + `vite build` clean; 9 Vitest tests; Playwright 15/15 locally and on the live URL |
| 3 | Deployed in `rg-swarmai-darkfactory` (swedencentral) with the mandatory RG tags, keyless; live SPA; smoke test passes against live; `/readyz` green; real Azure OpenAI with daily budget guard | ✔ | smoke **25/25 PASS** against the live URL (§6); `/readyz` = `ready`, `mode=azure`; budget guard `$0.25 of $5` used after the full run; tags verified (§8) |
| 4 | Idempotent re-deploy proven; teardown documented | ✔ | `azd provision && azd deploy` re-run twice with SUCCESS (§5); `azd down --purge --force` documented |
| 5 | README, this report, screenshots | ✔ | `README.md`, this file, 20 screenshots in `deck/assets/screens/` (§4.5) |
| 6 | No stray processes / temp junk / secrets | ✔ | see §10 |

## 2. Real vs simulated (statement)

* **Real:** the application (FastAPI + React), the Azure deployment, Cosmos DB persistence (ledger, approvals, KPI snapshots, policy state, job summaries), Blob Storage (vision images), Azure OpenAI calls (copilot with tool calling, vision classification, shift reports, RCA narration, explanations), managed-identity authentication, the policy engine / Safety veto / kill switch (enforced in the code path of every action), the hash-chained decision ledger, rate limits, budget guard, telemetry to Application Insights.
* **Simulated (by construction, synthetic data):** the plant ("Contoso Precision Components — KAT-1", plus GDN-2 and MTY-3 for the fleet view), its assets, orders, tariffs, faults and the human response times. There are **no** real PLC/MES/ERP connections: the control API *is* the simulator. OPC UA / MQTT / Event Hubs exist as tested decoders only (no broker connected). The Teams webhook generates the Adaptive Card and posts only when a webhook URL is configured (not tested against real Teams).
* Every page carries the "SYNTHETIC DATA · SIMULATED PLANT" banner.

## 3. What was built

| Area | Content |
|---|---|
| Simulation | deterministic seeded plant (numpy `Generator` per stream), 20 assets, O(assets) per tick, time acceleration (default 1 sim-min/s), pause/step, snapshot/restore (twin forks, A/B replay), fault-injection console |
| Agents | Safety, Predictive Maintenance, Quality, Planner, Materials, Energy (+ Process Optimizer pilot, off by default) — deterministic algorithms first (robust z/EWMA, SPC rules, scheduling heuristics, policy engine); Azure OpenAI only narrates/explains, each with a deterministic fallback |
| Governance | Autonomy Dial L0–L5, YAML policy engine, Safety veto, kill switch, approval inbox with escalation/expiry (human clock), RBAC roles (server-side 403), SHA-256 hash-chained ledger with tamper detection |
| Insight | "Ask the Factory" copilot (tool calling, citations, injection-resistant), handover report, RCA, KPI engine, readiness assessment, fleet comparison |
| Value | A/B replay (swarm OFF vs ON, same seeds and fault schedule, paired differences with 95 % CIs, background job with progress) and the ROI/ACR calculator on business-case model v1.1.0 |
| Platform | feature auto-discovery (backend `features/*`, frontend `features/*/index.tsx`), Cosmos + in-memory repositories, LLM abstraction (Azure via managed identity + offline stub), usage meter + daily budget guard (fails closed), observability, deployment page (ARM inventory + smoke results) |
| Infra | Bicep + azd: RG with governance tags, user-assigned MI, ACR (Basic), Log Analytics, Application Insights, Container Apps environment + app (0.5 vCPU / 1 GiB, min = max = 1 replica), Cosmos DB serverless (local auth off, data-plane RBAC), Storage (shared key off), AI Services account with two sequential model deployments, role assignments incl. the signed-in user |

Code size: ~14.6 k lines Python (excl. vendored model), ~2.0 k lines of tests, ~4.4 k lines TypeScript/TSX, ~560 lines Bicep.

### 3.1 ROI / ACR calculator on business-case model v1.1.0 (re-vendored)

* `model.py`, `assumptions.json` and `outputs.json` were copied **together** from `business-case/` into `app/src/nightshift/features/df21_value/business_case/` (sha256 prefixes `348cd732…`, `7171f5e7…`, `235b61d8…`); earlier v1.0 copies were replaced. `model.py` has no `override_specs()` function, so `calc_specs.override_specs(assumptions)` in the app derives the control specs from `assumptions.json` (287 drivers in 26 groups — core vs expansion levers E1–E5 — plus the 60 `price.<id>` meters incl. the six new ones, 5 lever switches, list/nullable/read-only kinds).
* The UI renders every control dynamically from `GET /api/value/calculator/meta` (collapsible, searchable groups; 3-value ramps as three inputs; nullable drivers; the `shared_scale_points` curve read-only). Validation of every override is the model's own (`ValueError`/`TypeError` → HTTP 422; non-finite numbers rejected).
* **"Base · levers off" vs "Expansion levers on"** control (master toggle + five adoption switches, each with an adoption %) — "on" sets the five switches to their Upside adoption (0.5 / 0.75 / 0.5 / 1.0 / 1.0), which is the model's own expansion case on the selected scenario's other inputs. A "custom lever mix" state is reported.
* Charts/tables: tiles (NPV, ROI, payback, IRR, benefits, costs, ACR Y3, ACR run-rate, ACR per plant-year), Base-vs-levers-on comparison table (incl. 5-year NPV memo), ACR run-rate path (waterfall core → E1…E5 → levers on), **ACR by service family and by lever (stacked Year 1–3 + run-rate)**, tiers table (pilot, 1 plant, 8 plants, 25 plants, **100-plant fleet labelled illustrative** because it extrapolates shared capacity), levers table, benefits by category (zero-valued categories hidden; `data_platform` / `cyber_risk` appear only when levers are on), net/cumulative cash, NPV and year-3-ACR tornados, ACR line items (top 15 / all).
* Reference values verified in the API tests, the live smoke test (#19) and the Playwright journey (UI text):

| Case | NPV (3 y) | ROI | Payback | ACR year 3 | ACR run-rate (8 plants) | per plant-year |
|---|---|---|---|---|---|---|
| Base | $8.26M | 104 % | 22.2 mo | $0.68M | $0.91M | $114k |
| Base + expansion levers on | $4.26M | 33 % | 30.7 mo | $1.28M | $1.87M | $233k |
| Upside | — | — | — | $1.91M | $2.43M | — |

  25 plants: $2.71M core / $5.44M with levers; 100-plant fleet (illustrative): $10.6M core / $21.2M with levers. Honest reading: the levers roughly double Azure consumption but lengthen payback and lower the 3-year NPV (5-year NPV $36.6M → $38.1M), because their benefits ramp later.
* **Parity test:** `compute_all(load_assumptions())` is compared recursively with the whole `outputs.json` (Conservative / Base / Upside, every key, every list element; numbers within 0.5 %); a second test asserts the model/assumptions/outputs versions agree and that the vendored trio is byte-identical to `business-case/`.
* Performance design: plain computations take a few ms (run off the event loop in a worker thread); the tornado ("sensitivity") re-runs the model 50–370 times, so it is a separate idle-debounced request, cached per input set, single-flight and limited to 20/min/client. Calculator JSON (~100 kB) is gzip-compressed (~22 kB on the wire).

## 4. Test evidence

### 4.1 Automated tests

| Suite | Result |
|---|---|
| `pytest` (app/tests: 6 files) | **113 passed**, 0 failed (≈ 58 s) |
| Coverage (`--cov=nightshift`, vendored model, `main.py` and `core/obs.py` excluded) | **93 %** (7 380 statements, 504 missed); lowest: DF-25 deployment router 73 % (ARM calls), vision 81 %, telemetry router 83 %, inbox 84 %, process agent 86 % |
| `ruff check` / `ruff format --check` | clean (109 files) |
| `mypy` (scoped to `sim` + `core`, 17 files) | no issues (the feature packages are not yet type-annotated end to end) |
| `tsc --noEmit` + `vite build` | clean |
| Vitest (UI helpers and components) | 9 passed (`fmt`, `bits` and the calculator logic: lever modes, override handling, stacked-chart rows, number formats) |
| Playwright journeys (`scripts/e2e_journeys.py`) | **15/15 on the live URL** and 15/15 locally |
| Route crawl (`scripts/e2e_crawl.py`) | 26/26 routes render without console/page errors (live) |
| Smoke test (`scripts/smoke_test.py`) | **25/25 PASS against the live URL** (§6) |

### 4.2 Behavioural tests from the brief (`app/tests/test_behaviour.py`, all passing)

| Brief requirement | Test(s) |
|---|---|
| Bearing-wear alert lead time; breakdown avoided by planned maintenance; baseline breaks down | `test_bearing_wear_baseline_breaks_down`, `test_pdm_alerts_well_before_the_failure`, `test_planned_maintenance_avoids_the_breakdown` |
| Ledger documents the story with a valid hash chain; tampering detected | `test_ledger_documents_the_story_with_a_valid_chain`, `test_ledger_tamper_is_detected` |
| Safety veto beats the Planner | `test_safety_veto_beats_the_planner` |
| Kill switch halts every autonomous action (but not the protective stop) | `test_kill_switch_halts_every_autonomous_action` |
| Autonomy levels L0–L5 enforced; lowering the dial changes what executes | `test_autonomy_level_matrix`, `test_lowering_the_dial_changes_what_executes` |
| Forbidden setpoints rejected everywhere | `test_forbidden_setpoints_are_rejected_everywhere` |
| A/B: ≥ 10 seeds, fast, primary metrics significantly better, deterministic | `test_ab_runs_fast_and_uses_at_least_ten_seeds`, `test_ab_primary_metrics_are_significantly_better`, `test_ab_tardiness_and_total_loss_improve`, `test_ab_energy_effective_price_is_lower_and_absolute_cost_is_reported_honestly`, `test_ab_is_deterministic` |
| Planner re-plan beats FIFO after a breakdown; feasible schedule | `test_planner_replan_meets_more_due_dates_than_fifo_after_a_breakdown`, `test_planner_schedule_is_feasible_without_capacity_overlaps` |
| Energy shifting without due-date violations | `test_energy_agent_shifts_load_without_hurting_due_dates` |
| Vision agrees with known defect above threshold | `test_vision_stub_agrees_with_the_known_defect_above_threshold` (offline stub) — and 6/6 = 100 % on the live Azure model (smoke #15) |
| ROI calculator reproduces `outputs.json` | `test_roi_calculator_reproduces_outputs_json_whole_document_within_half_a_percent`, `test_vendored_business_case_files_are_one_consistent_version` |

The tests never need the network (offline stub LLM, in-memory repository). Enforcement of the governance controls is tested through the API as well as in the unit tests (operator 403s, dial changes audited in the ledger, kill switch visible in the snapshot, break-glass requires a reason and expires).

### 4.3 A/B value realization (swarm OFF vs ON; same seeds, order book, noise streams and fault schedule)

16 seeds × 8 simulated hours after a 3 h warm-up, 8 injected disruptions per seed, approvals answered after 20 sim-min. **Window "late" (default; plant clock 17:00–01:00, spans the evening tariff peak):**

| Metric | OFF | ON | Improvement | 95 % CI | p (1-sided) | Significant |
|---|---|---|---|---|---|---|
| Unplanned downtime (h) | 2.39 | 0.51 | **1.89 (−79 %)** | [1.38, 2.39] | < 0.001 | yes |
| Late orders (realised + forecast) | 7.56 | 6.06 | **1.50 (−20 %)** | [0.70, 2.30] | 0.001 | yes |
| Order tardiness (h) | 58.7 | 48.1 | 10.6 (−18 %) | [0.30, 20.8] | 0.022 | yes |
| Total loss (EUR) | 3 032 | 2 106 | 926 (−31 %) | [18, 1 834] | 0.023 | yes |
| OEE (pts) | 64.1 | 77.6 | **+13.5** | [10.8, 16.2] | < 0.001 | yes |
| Effective energy price paid (EUR/kWh) | 0.288 | 0.258 | 0.030 (−10 %) | [0.022, 0.037] | < 0.001 | yes |
| Energy cost per unit-operation (EUR) | 0.140 | 0.135 | 0.005 (−4 %) | [−0.001, 0.011] | 0.058 | no |
| **Energy cost, absolute (EUR)** | 447 | 475 | **+28 (+6 %, worse)** | [−42, −14] (better = positive) | 1.000 | no |
| Scrap (units) | 1.91 | 2.54 | −0.63 (worse) | [−3.84, 2.59] | 0.659 | no |
| Customer escapes (units) | 0.10 | 0.001 | 0.10 | [−0.06, 0.26] | 0.102 | no |
| OTIF (pts) | 87.0 | 91.2 | +4.3 | [−7.7, 16.2] | 0.229 | no |
| Good units shipped | 749 | 731 | −18 | [−105, 69] | 0.667 | no |

*Significant* = the two-sided 95 % interval excludes 0. Honest reading: downtime, late orders, tardiness, total loss, OEE and the effective energy price improve significantly; **absolute energy cost is slightly higher** (less downtime means more machine-hours running, and the energy agent moves consumption to cheaper hours rather than reducing it); scrap, escapes, OTIF and shipped units show no significant effect in this synthetic scenario. Windows "night" (01:00) and "day" (09:00) give the same picture (downtime −79 %, late orders −19 %/−18 %, OEE +13.2/+13.7 pts, total loss −31 %); the effective-price gain shrinks to −2 % (tariff spread is smaller outside the evening peak) and tardiness is borderline in the night window (CI [−0.1, 19.5]). The assumptions (sim config, fault schedule, latency) are shown in the UI (`/api/value/assumptions`) and the results are bit-identical between my laptop and the container (10 seeds: downtime −72 % CI [1.20, 2.34], late orders −16 %, OEE +12.5 pts on both).

Timing: 10 seeds × 8 h take 2.2 s on a laptop and **≈ 41 s on the 0.5 vCPU container** (target was < 30 s; it therefore runs as a background job in a **separate worker process** with progress polling, so the live simulation, SSE streams and health probes stay responsive — see §9, incident 1).

### 4.4 Playwright journeys (live URL; 1600×900)

control tower (live plant map, KPIs, SSE) · fault injection → maintenance agent reacts in the live feed · asset drill-down · ledger (valid hash chain, filter, detail) · policy dial to L2 · approvals inbox (operator 403, plant manager approves) · digital-twin what-if with KPI deltas · copilot (grounded answer, tool calls, citations — real Azure OpenAI) · A/B value realization (significant downtime + late-order improvement) · **ROI/ACR calculator** (reference values in the tiles, "matches outputs.json" badge, override → recompute → reset, 3-value ramp edit, filter, master toggle to "Expansion levers on" → $4.26M / $1.28M / $1.87M / $233k, per-lever adoption, custom mix, back to Base, tornado appears) · readiness assessment · fleet · kill switch banner · Feature Map 25/25 · extra pages (maintenance, planner, quality, deployment, observability).

### 4.5 Screenshots (`deck/assets/screens/`, 1600×900, captured from the live deployment)

`01-control-tower` · `02-agent-activity-ledger` · `03-approvals-inbox` · `04-what-if` · `05-copilot` · `06-ab-value-realization` · **`07-roi-acr-calculator`** (Base, levers off) · **`07b-roi-acr-levers-on`** · **`07c-roi-acr-by-family-and-lever`** · **`07d-roi-acr-tiers-and-levers`** · `08-readiness-assessment` · `09-fleet` · `10-feature-map` · `11-autonomy-dial-policy` · `12-kill-switch` · `13-predictive-maintenance` · `14-planner-gantt` · `15-quality-spc` · `16-deployment` · `17-observability-finops`.
The four calculator screenshots (07, 07b, 07c, 07d) were **re-captured after re-vendoring model v1.1.0** and show the levers control, ACR by family / by lever, and the 25-/100-plant tiers.

## 5. Deployment

### 5.1 Resources (14 in `rg-swarmai-darkfactory`, all tagged)

| Resource | Name | SKU / configuration |
|---|---|---|
| User-assigned managed identity | `id-nightshift-t5lxouqj6rp4m` | roles: AcrPull (ACR), Storage Blob Data Contributor (storage), Cognitive Services OpenAI User + Cognitive Services User (AI Services), Monitoring Metrics Publisher (App Insights), Reader (resource group, for the Deployment page's ARM inventory), Cosmos DB Built-in Data Contributor (data plane) |
| Log Analytics workspace | `log-nightshift-t5lxouqj6rp4m` | PerGB2018, 30-day retention, 1 GB/day cap |
| Application Insights | `appi-nightshift-t5lxouqj6rp4m` | workspace-based; Entra auth (OpenTelemetry via `azure-monitor-opentelemetry`) |
| Container Registry | `acrnst5lxouqj6rp4m` | Basic, admin user disabled, remote builds (`azd` → ACR build) |
| Container Apps environment | `cae-nightshift-t5lxouqj6rp4m` | consumption |
| Container App | `ca-nightshift` | 0.5 vCPU / 1 GiB, **min = max = 1 replica** (in-process simulation), external ingress :8000, liveness/readiness/startup probes on `/healthz` (timeout 5/5/3 s) |
| Cosmos DB account | `cosmos-nightshift-t5lxouqj6rp4m` | serverless, **local auth disabled**, Entra data-plane RBAC; db `nightshift`, 8 containers (`ledger`, `approvals`, `kpi`, `telemetry`, `state`, `jobs`, `audit`, `reports`) |
| Storage account | `stnst5lxouqj6rp4m` | Standard_LRS, **shared-key access disabled**, public blob access disabled, TLS 1.2 |
| AI Services account | `ais-nightshift-t5lxouqj6rp4m` | S0, **local auth disabled**; deployments `chat` = gpt-5.4-mini (2026-03-17, GlobalStandard, 100) and `reasoning` = gpt-5.4 (2026-03-05, GlobalStandard, 50), deployed sequentially |
| 5 auto-created system resources | alert rules / system topic / smart-detector for Log Analytics, App Insights and Storage | tagged by `scripts/ensure-tags.sh` |

### 5.2 Commands

```bash
# one-time (az login is already done; never change the account)
cd 01-dark-factories
azd up --no-prompt            # provision (Bicep, subscription-scope: RG + tags + everything) + remote ACR build + deploy
bash scripts/ensure-tags.sh   # tags the 5 platform-created alert resources (azd's postprovision hook calls it as well)

# iterate
azd deploy --no-prompt                          # code only (≈ 2.3 min, remote build)
azd provision --no-prompt && azd deploy --no-prompt   # infra + code (idempotent)

# verify
python3 scripts/smoke_test.py --base-url https://ca-nightshift.blackforest-a28408f9.swedencentral.azurecontainerapps.io
python3 scripts/load_check.py  --base-url <url> --requests 300 --concurrency 20
/Users/michalfu/Dev/SwarmAI/.venv/bin/python scripts/e2e_journeys.py --base-url <url> --screens deck/assets/screens

# teardown (removes the resource group and purges soft-deleted Cognitive Services / Cosmos names)
azd down --purge --force
```

### 5.3 Idempotent re-deployment (proof)

* `azd provision --no-prompt && azd deploy --no-prompt` on the existing environment: provision **SUCCESS in 2 min 11 s** (no resource recreated, same names), deploy **SUCCESS in 2 min 9 s** (new revision, old one deprovisioned).
* Repeated at the end of the session after changing the Container App probes in Bicep: provision SUCCESS in 2 min 16 s (probe change applied; `az containerapp show` reports timeouts 5/5/3 s), deploy SUCCESS in 2 min 18 s. Code-only `azd deploy` runs took 2 min 9 s – 2 min 18 s each (7 in this session); the smoke test is green after the last ones.
* Note: the `postprovision` hook (`scripts/ensure-tags.sh`) is not echoed by `azd provision --no-prompt` in this environment; running the script explicitly is idempotent (`0 resource(s) tagged` when all carry the tags).

## 6. Live smoke test — PASS/FAIL table (`scripts/smoke_test.py`, final revision, mode = azure)

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | healthz | PASS | uptime 96 s |
| 2 | readyz: Cosmos + Blob + Azure OpenAI over managed identity | PASS | cosmos 37 ms, storage 192 ms, openai 1 409 ms |
| 3 | meta: azure mode, Cosmos + Blob persistence | PASS | build `ca-nightshift--azd-1794963538`, write-behind written=200 |
| 4 | features: 25/25 implemented | PASS | |
| 5 | SPA + OpenAPI docs served | PASS | index, deep link and `/docs` |
| 6 | simulator: state + UNS tree | PASS | 20 assets, 105 UNS topics |
| 7 | SSE stream (control-tower feed) | PASS | hello + tick delivered |
| 8 | agents: bearing-wear fault → PdM alert → work order → ledger | PASS | alert on CNC-01 (similarity 0.99), WO-0001, ledger chain valid (220 entries) |
| 9 | autonomy dial L2 → approval inbox → RBAC → approve → Teams card | PASS | operator 403, engineer approved |
| 10 | planner / materials / energy / process / KPI endpoints | PASS | 26 slots feasible, 5 materials, OEE 78 % |
| 11 | safety: forbidden setpoint denied, intrusion → stop + veto → verified restart | PASS | restart vetoed (`zone_occupied`) |
| 12 | kill switch | PASS | engaged, visible, operator reset 403, released by plant manager |
| 13 | digital-twin what-if on a fork | PASS | net value −419.8 EUR, accept = false |
| 14 | copilot: Azure OpenAI tool calling with citations | PASS | tools `get_alerts`, `list_assets`, `query_ledger`; 8 citations |
| 15 | vision: defect images classified by the Azure model | PASS | 6/6 by `gpt-5.4-mini`, 100 % agreement |
| 16 | shift handover report narrated by Azure OpenAI | PASS | 2 867 chars |
| 17 | root-cause analysis narrated by Azure OpenAI | PASS | |
| 18 | A/B replay (≥ 10 seeds) significant downtime + late orders | PASS | 10 seeds in 41 s: downtime −72 % (CI 1.20…2.34 h), late orders −16 %, OEE +12.5 pts |
| 19 | ROI / ACR calculator reproduces the business-case model | PASS | Base NPV $8.26M, ROI 104 %, payback 22.2 mo, Y3 ACR $0.68M, run-rate $0.91M ($114k/plant-yr); levers on $1.28M / $1.87M; Upside $1.91M / $2.43M; 25 plants $2.71M → $5.44M; model v1.1.0 |
| 20 | readiness assessment + export | PASS | 11 roadmap items |
| 21 | fleet comparison (3 plants) | PASS | |
| 22 | RBAC: server-side 403s and audit trail | PASS | 3 denials audited |
| 23 | FinOps: AI usage metered, daily budget guard active | PASS | 213 calls, $0.2511 of $5 daily cap |
| 24 | persistence: KPI snapshots + ledger in Cosmos DB | PASS | 24 snapshots; write-behind written = 2 379, failed = 0, dropped = 0 |
| 25 | deployment: ARM inventory with governance tags | PASS | 14 resources, all tagged |

**25 passed, 0 failed.** The results are published to the app's *Deployment* page (`/deployment`). Replica restarts after the run: 0.

## 7. Performance (live, single replica, 0.5 vCPU)

| Measurement | Result |
|---|---|
| Load check, 300 requests, 20 concurrent, keep-alive, 10 read endpoints | 53–68 req/s, **0 errors**; client p50 **251–256 ms** (network RTT floor to swedencentral from this machine: 241–253 ms, i.e. server contribution ≈ 0–3 ms); p95 640–740 ms (= TCP/TLS handshakes of the 20 fresh connections; one run right after the E2E suite showed p95 1.97 s) |
| Server-side latency (app's own metrics, 1 542 requests, 0 errors) | typical feature p50 1.2–2.6 ms, p95 6–45 ms; DF-21 (calculator + A/B polling) p50 31 ms, p95 0.86 s |
| Calculator | `meta` 255 ms (23 kB gzip); plain compute 300 ms (RTT + ≈ 40–60 ms, 22 kB gzip); sensitivity cold 1.2 s (Base) / 5.8 s (levers on, 366 model runs), repeated input 259 ms (server cache) |
| A/B replay | 10 seeds × 8 h: 2.2 s locally, 41 s in the container (background job + progress) |
| Resource use | ≈ 30 mCores / 280 MB idle (before the worker process); the A/B child adds ≈ 100 MB while it runs |

## 8. Security and governance

* **Tags (mandatory):** RG and **all 14 resources** carry `SecurityControl=Ignore`, `SecurityExemption=StorageAccountKeyAccess`, `project=SwarmAI`, `concept=darkfactory`, `owner=michalfu`, `environment=demo` (Bicep `commonTags` passed to every module; the RG also carries azd's `azd-env-name`).

```
$ az group show -n rg-swarmai-darkfactory --query tags
{ "SecurityControl": "Ignore", "SecurityExemption": "StorageAccountKeyAccess", "azd-env-name": "nightshift",
  "concept": "darkfactory", "environment": "demo", "owner": "michalfu", "project": "SwarmAI" }

$ az resource list -g rg-swarmai-darkfactory --query "[].{n:name,t:tags.SecurityControl,e:tags.SecurityExemption}"
  14 rows, all  Ignore / StorageAccountKeyAccess   (9 workload resources + 5 platform-created alert / system resources)
```
* **Not modified by governance (checked after the last deployment):** Storage `allowSharedKeyAccess=false`, `allowBlobPublicAccess=false`, TLS 1.2; Cosmos `disableLocalAuth=true`, serverless; ACR `adminUserEnabled=false`; AI Services `disableLocalAuth=true`; public network access left enabled on Cosmos/AI Services/ACA by design (demo; private endpoints are the production target, ARCHITECTURE §19).
* **Shared-key exemption:** the `StorageAccountKeyAccess` exemption is carried on the tags as required, but **no service needs it** — Blob access uses Entra (Storage Blob Data Contributor via the managed identity) and shared-key access stays disabled.
* **Keyless:** the app authenticates to Cosmos, Blob, Azure OpenAI, ACR and Application Insights with the user-assigned managed identity (`DefaultAzureCredential`); no connection strings, keys or secrets exist in code, Bicep, azd env values or logs (scanned). The signed-in user received Cosmos data-plane RBAC for diagnostics.
* **Application controls:** server-side RBAC (roles by `X-Demo-Role` header in the demo; Entra JWT validation implemented and unit-tested with a local signing key, `AUTH_MODE=entra`), per-IP and global rate limits (read / mutate / AI / compute buckets), body-size limit, CSP and security headers, HSTS, input validation (pydantic + the model's own override validation), prompt-injection-resistant copilot (tools read-only by default; proposals go through Safety and policy), daily AI budget guard that **fails closed** to the deterministic fallbacks, SHA-256 hash-chained ledger.
* **Known gap (by design for the demo):** the public endpoint has no sign-in; roles come from a demo switcher. Production: Front Door/WAF + Entra sign-in (`enableEntraAuth` in Bicep adds Container Apps built-in auth).

## 9. Incidents and bugs found by the tests (and fixed)

1. **Container restart during the A/B replay (found by the live smoke test, #18 `KeyError: 'status'`).** The replay ran in a worker *thread*; on 0.5 vCPU it starved the event loop (GIL convoy + CPU quota), `/healthz` probes timed out for ~60 s and the liveness probe restarted the container (`restartCount = 1`, confirmed in `ContainerAppSystemLogs_CL`). Fix: the replay now runs in a separate worker process (one seed per task, thread fallback if processes are unavailable); probe timeouts/thresholds raised in Bicep (5 s / 5 failures for liveness). After the fix: 2 full smoke runs and 2 full E2E runs on the new revisions, 0 restarts, no ProbeFailed events except the normal start-up probe.
2. **Quality page crash** (`Cannot read properties of undefined (reading 'toFixed')`) when a *containment* intervention (no `offset` field) was listed — found by the E2E suite after a fault sequence; fixed with null-safe formatting.
3. **E2E assertion was vacuous** (`inner_text()` returns CSS-uppercased text, so "text changed" was always true) — now compares `textContent`; the calculator journey really verifies that a recomputation happens.
4. **Noisy logging:** the Azure SDKs logged every Cosmos request/response at INFO into Log Analytics; silenced (`azure.*` → WARNING).
5. **Calculator POSTs consumed the mutation rate limit** (120/min) — they now use their own "compute" bucket; calculator payloads are gzip-compressed (SSE excluded).
6. Earlier in the build (see ARCHITECTURE §19 and `app/tests`): bearing/thermal faults not cured by a tool change, vision false positives, telemetry `ts` default, JWT static JWKS, copilot what-if routing, approval SLAs on a human (wall-clock) time base, Cosmos write-behind daily caps.

## 10. Estimated monthly cost (idle, list prices, swedencentral)

| Item | ≈ USD / month |
|---|---|
| Container Apps, 0.5 vCPU + 1 GiB always active (1 replica; free grant 180 k vCPU-s + 360 k GiB-s per month applies) | 34 |
| Container Registry Basic | 5 |
| Cosmos DB serverless (write-behind capped by daily document limits; ≈ 1–2 M RU + a few MB) | 2–5 |
| Log Analytics + Application Insights (ingestion mostly inside the free 5 GB; app INFO logging is small after the fix) | 0–3 |
| Storage (LRS, a few MB of images) | < 1 |
| Azure OpenAI tokens (only when exercised: ≈ $0.2–0.3 for a full smoke run; budget guard $5/day; idle ≈ 0) | 0–2 |
| **Total idle** | **≈ $45 (range $40–55)** |

A heavy demo day adds well under $1 of tokens; the `$5/day` guard bounds the worst case at ≈ $150/month of AI spend. Scale-to-zero is deliberately not used because the live simulation is in-process state.

## 11. Known limitations and notes

* **Single replica** (in-process plant): scale out by partitioning plants across replicas (`PLANTS=<ids>`, ingress affinity by plant) — ARCHITECTURE §19.
* The simulation runs at **1 sim-minute per real second** by default; use 10–30× from the Control Tower for a live demo (the E2E suite uses 30×).
* **A/B on the container takes ≈ 41 s** (> 30 s target) → background job with progress.
* **Energy:** the swarm lowers the *price paid per kWh* (−10 %, significant in the evening-peak window) but not the absolute cost (+6 %) in the simulated scenario; scrap/OTIF/shipped units show no significant effect. Reported as such in the UI and the tests.
* The Process Optimizer (DF-11, P2 pilot) is **disabled by default** (enable with the agent toggle); connectors for OPC UA/MQTT/Event Hubs are decoders only; the Teams webhook is untested against real Teams.
* The 100-plant fleet ACR is an extrapolation of shared capacity (illustrative); the lever workloads themselves (vision archive, kHz waveforms, simulation pools, enterprise Fabric, ExpressRoute) are *modelled in the calculator*, not deployed.
* `mypy` covers `sim` and `core`; the feature packages use annotations but are not yet checked end to end.
* `override_specs()` is implemented in the app (`calc_specs.py`) from `assumptions.json`; if the docs agent adds one to `model.py`, the app should switch to it (same trio must be re-vendored together).

## 12. Cleanup (end of session)

Dev server on :8101 stopped; no background processes left; scratch logs (`.deploy*.log`, `.provision*.log`, `.smoke-live.log`, `.e2e-live.log`, `.redeploy.log`, `app/.dev-server.log`, `app/.pytest-full.log`, `.shots-tmp/`, local `static/` and `web/dist` copies) removed; failed-screenshot files removed; no secrets in the tree (grep for keys/connection strings/tokens is clean; `.azure/` holds only non-secret azd environment values).
