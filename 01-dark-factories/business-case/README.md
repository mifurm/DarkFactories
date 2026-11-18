# Nightshift business case — ROI for the customer + Azure Consumed Revenue (ACR)

One deterministic, auditable model answers two questions for the reference customer **Contoso Industrial Group** (fictional; US$2.0 B revenue, 8 plants, ~3,200 monitored assets, three shifts):

1. **Customer ROI** — what do 3 years of SwarmAI Dark Factory (Nightshift) cost and return? (benefits by category with ramp and confidence factors, all costs incl. Azure, NPV, ROI %, payback, IRR, sensitivity)
2. **Azure Consumed Revenue** — what does the customer consume on Azure, bottom-up per service family, per year, per plant tier, and how much non-AI consumption does AI pull through?

Everything quoted in `PRD.md`, `ARCHITECTURE.md` and the executive deck comes from `outputs.json` (produced by `model.py` from `assumptions.json`).
**Illustrative — validate every benefit input with the customer's own data before committing to a number.**

| File | Purpose |
|---|---|
| `assumptions.json` | every input: value (low/base/high), unit, scenario values, source or "assumption" flag, rationale (287 assumptions, 118 of them for the expansion levers) + the Azure unit prices (60 meters) |
| `model.py` | pure standard-library model: `compute()`, `compute_all()`, `load_assumptions()`; `python model.py` writes `outputs.json` and `outputs.md` |
| `outputs.json` / `outputs.md` | results for the Conservative / Base / Upside scenarios (JSON for machines, Markdown with a line-by-line ACR audit for humans) |
| `test_model.py` | 37 unit tests (`python -m unittest -v test_model`) incl. "outputs.json is current", price-snapshot parity, Base golden values, internal consistency, override validation, expansion levers |
| `prices/` | `queries.json` (the exact Retail Prices API queries), `prices-snapshot.json` (result, retrieved 2026-11-17), `fetch_prices.py` (stdlib helper to search / refresh) |

```bash
cd business-case
python model.py                      # regenerate outputs.json + outputs.md
python -m unittest -v test_model     # 37 tests, ~2 s
```

## 1. How the customer ROI works

**Timeline.** 36 months (`horizon_years` = 3; a 5-year memo is always computed). Cohorts go live at `go_live_month_in_year` (default month 7) of each onboarding year so that **2 / 5 / 8 plants** are live at the end of years 1 / 2 / 3 (`plants_cum_share_by_year` = 0.25 / 0.625 / 1.0, from the brief).
A plant earns `benefit_ramp` of its steady-state benefit in each 12-month period after its own go-live (default 35 % → 75 % → 95 %: autonomy is earned decision class by decision class).

**Benefit categories** (annual steady state per plant, then × risk-adjustment confidence factor × ramp; plant revenue = `revenue_usd` / `plants_total`):

| Category | Formula (per plant per year) | Evidence anchor | Evidence class (§1a) |
|---|---|---|---|
| Unplanned downtime | lines × 6,000 h × baseline downtime % × reduction % × cost per line-hour | Siemens 2024: large plant loses 326 h/yr (= 5.4 % of 6,000 h); McKinsey 2017: PdM cuts downtime 30–50 % (we assume 20 %) | **simulation-supported** (A/B −79 % against a run-to-failure baseline) |
| Maintenance cost | revenue × maintenance spend % × reduction % | assumption | benchmark/assumption-only (not measured by the A/B) |
| Throughput / OEE | revenue × (OEE pts ÷ baseline OEE) × contribution margin × share of capacity sold | OEE.com: typical OEE ≈ 60 % | **simulation-supported** in direction (A/B OEE +13.5 pts, mostly availability); the +1.5-pt performance component and the share sold are assumptions |
| Scrap & rework | revenue × scrap cost % × reduction % | assumption | benchmark/assumption-only — **A/B: no significant effect** |
| Energy | revenue × energy spend % × saving % — read as **tariff-aware load shifting that lowers the effective price paid per kWh where tariffs vary**, not lower consumption | assumption | benchmark/assumption-only — A/B: effective price −10 % (evening-peak window), absolute cost +6 % |
| Indirect labour | indirect FTE × productive hours × productivity gain × loaded rate | assumption | benchmark/assumption-only |
| Inventory | revenue × inventory % × reduction % × carrying-cost rate (cash release is a memo, **not** in NPV) | assumption | benchmark/assumption-only |
| Expedite & freight | revenue × expedite spend % × reduction % | assumption | benchmark/assumption-only |
| OTIF protection | revenue × late-delivery cost % × reduction % | assumption | **simulation-supported** (late orders −20 %, tardiness −18 %; OTIF points not significant) |
| Capex deferral | revenue × gross PPE % × unsold capacity gain × carrying cost % | assumption | benchmark/assumption-only (derived from the capacity gain) |

### 1a. What the simulation does and does not support (evidence classes)

The product's A/B replay (16 seeds, swarm OFF vs ON, same seeds/order book/noise/fault schedule; baseline = FIFO pull, run-to-failure maintenance, periodic manual QC, min/max reorder) is **simulation evidence on synthetic assumptions — not a customer guarantee**. Full table: PRD §10.3; evidence in `REPORT-TEST-AND-DEPLOYMENT.md` §4.3.

* **Significant improvements (6 of 12 metrics):** unplanned downtime −79 %, late orders −20 %, order tardiness −18 %, total loss −31 %, OEE +13.5 points, effective energy price paid −10 % (evening-peak window; about −2 % in the night and day windows).
* **Absolute energy cost is slightly worse (+6 %)**: less downtime means more machine-hours, and the energy agent shifts load to cheaper hours rather than cutting kWh. The energy benefit in the model is therefore a *price* effect that exists only where tariffs vary.
* **No significant effect** on scrap, customer escapes, OTIF points and good units shipped in the simulated scenario.

Consequently the ten benefit categories split into **simulation-supported** (downtime, OEE/throughput, OTIF/late-delivery) = **44 %** of the Base risk-adjusted benefit, and **benchmark/assumption-only** (maintenance, scrap, energy, labour, inventory, expedite, capex deferral) = **56 %**; the expansion levers E1–E5 are modelled, not simulated (assumption-only). The model's numbers are unchanged by this classification. The confidence factors (0.40–0.90) express how measurable a benefit is on customer data; the pilot replaces them with measured realisation. Reproducible stress tests (Base, `compute(a, "base", overrides=...)`):

| Override set | 3-year NPV | Payback | 5-year NPV |
|---|---:|---:|---:|
| none (published Base) | $8.26 M | 22.2 mo | $36.6 M |
| `scrap_reduction_pct` = 0 and `energy_saving_pct` = 0 | $4.66 M | 25.2 mo | $26.1 M |
| only simulation-supported benefits: `scrap_reduction_pct`, `energy_saving_pct`, `maintenance_cost_reduction_pct`, `indirect_labour_productivity_gain_pct`, `inventory_reduction_pct`, `expedite_reduction_pct`, `capex_carry_cost_pct` all = 0 | −$1.34 M | 38.3 mo | $8.56 M |

The cost of an unplanned line-hour is **derived** (`downtime_cost_pct_of_line_revenue` × line revenue per hour ≈ US$4.2 k) unless you override `downtime_cost_per_line_hour_usd` (Siemens: US$36 k/h FMCG … US$2.3 M/h automotive for the largest plants, so the default is deliberately conservative for US$250 M plants).

**Costs.** Azure run cost (from the ACR engine, list price) + edge hardware & sensors + integration (platform foundation once, then per plant with a learning curve) + change management + AgentOps team (central + per live plant) + SwarmAI platform subscription + other licences (Defender for IoT OT sites, Power BI, connectors) + hardware support + contingency + the paid Lights-Out Readiness Assessment. One-time costs are placed when incurred (hardware 3 months, integration 2 months, training 1 month before go-live).

**Metrics.** Monthly cash flows. NPV discounts each month at `(1+r)^(-(m+1)/12)`; ROI % = (benefits − costs) ÷ costs over the horizon; payback = first month from which the cumulative net cash position stays ≥ 0 (linear interpolation; looks up to 60 months); IRR = annualised rate that zeroes the monthly NPV (null if the flows never change sign). **Sensitivity** = one-at-a-time swing of NPV between each assumption's `low` and `high` (others at the scenario value).

**Scenarios.** Base uses `base` everywhere. Conservative and Upside change only the 53 *scenario drivers* (entries with a `scenario` object: value levers, ramp, go-live month, cost items, Azure usage drivers, and the expansion-lever adoption, start lag and ramp); everything else is identical, so the scenarios stay explainable rather than compounding 100 worst cases. **The five expansion levers (§4a) are OFF in Base and Conservative and ON in Upside.**

## 2. How the ACR engine works

Bottom-up: **units × Azure Retail Prices API list price** (USD, pay-as-you-go, no EA/CSP discount, no reservations; swedencentral unless the meter is global/zone-based; Azure Digital Twins is priced in westeurope because it is not offered in swedencentral). Prices were retrieved on **2026-11-17**; `prices/queries.json` holds the filters and `test_model.py` fails if `assumptions.json` and `prices/prices-snapshot.json` disagree.

* **12 service families:** Foundry models & AI Search · Azure ML · Fabric (RTI, OneLake, Power BI) · IoT Operations/Arc/Device Registry · Event Hubs/Event Grid/Service Bus · Digital Twins · Cosmos DB · Storage/ADLS · Container Apps compute & ACR · networking (ExpressRoute, VPN, Front Door, Private Link) · security (Defender, Sentinel, Key Vault) · monitoring (Log Analytics).
* **Four kinds of line:** *provisioned* (billed in full from 2 months before go-live: IoT Ops nodes, always-on vCPU, Cosmos RU/s, circuits), *usage* (scaled by `usage_ramp`: tokens, ingestion, queries, logs), *stock* (storage that fills over its retention window), *shared* (the enterprise platform, scaled sub-linearly with plants via `shared_scale_points`).
* **Uplifts:** dev/test environments (`nonprod_environment_uplift_pct`) and warm-standby DR (`dr_uplift_pct`) on the families where they apply (see `NONPROD_FAMILIES`, `DR_FAMILIES` in `model.py`).
* **Per-plant sizing** is stated for the 400-asset reference plant and scales linearly with `assets_per_plant`. Telemetry volume is derived (tags × publish rates × bytes), tokens from calls × token counts per workload, so every quantity can be audited in `outputs.md` §5.
* **Outputs:** `acr.by_year`, `acr.by_family`, `run_rate_year3` (full-year steady state at full roll-out), `tiers` (pilot / 1 plant / 8 plants / 25-plant enterprise), `pull_through_ratio` = (all other families) ÷ (Foundry + AI Search + Azure ML), `attach` mix (AI core, data, edge, compute, networking, security, monitoring), `line_items`, an illustrative `opportunity` sizing and `acr_sensitivity`.

Excluded from ACR on purpose: carrier last-mile charges, Defender for IoT OT site licences and Entra/Teams/Power BI Pro (Microsoft 365 billing), customer hardware, partner services.

## 3. Output schema (stable)

`compute(assumptions, scenario="base", overrides=None, *, with_sensitivity=True)` returns:

```
scenario, currency, horizon_years, model_version, assumptions_version, price_retrieved_on
inputs {resolved{id: value}, overrides}
plants {cohorts[], live_by_year_end[], average_live_plants_by_year[]}
benefits {by_category{cat: [y1,y2,y3]}, total_by_year[], total, confidence{}, steady_state_per_plant_gross{}, steady_state_per_plant_risk_adjusted{}, steady_state_at_all_plants_risk_adjusted, memo{working_capital_release_total_usd}}
costs {azure_by_family{fam: [..]}, azure_total_by_year[], other_by_category{cat: [..]}, total_by_year[], total}
roi {net_benefit_by_year[], cumulative[], npv, discount_rate, roi_pct, payback_months, irr_pct, net_total}
acr {by_year[], by_family{}, run_rate_year3, run_rate_by_family{}, per_plant_year, per_asset_year, tiers[], pull_through_ratio, attach{}, line_items[], opportunity{},
     by_lever{core, E1..E5: [y1,y2,y3]}, run_rate_by_lever{core, E1..E5}, lever_adoption{E1..E5}}          # last three: new in v1.1.0
unit_economics{}, derived{}, memo{five_year{npv, roi_pct, irr_pct, ...}}, sensitivity[], acr_sensitivity[]
levers[]        # new in v1.1.0: per lever E1..E5 — adoption, start lag, per_deploying_plant{azure_run_cost, other_run_cost, benefit, net, one_time_cost, payback_months, ...},
                #   enterprise_fixed{}, by_year{benefit, azure, other_cost, net}, npv, run_rate{azure, azure_per_deploying_plant}
expansion{}     # new in v1.1.0: the expansion case = all five levers at their Upside adoption on top of THIS scenario's inputs:
                #   case, adoption{}, headline{npv, npv_5yr, payback_months, acr_by_year, acr_year3, acr_run_rate, ...}, levers[], benefits{}, costs{}, roi{},
                #   acr{by_year, by_family, by_lever, run_rate, run_rate_by_lever, run_rate_by_family, per_plant_year, per_asset_year, line_items[], ...},
                #   tiers[{id: pilot|plant_1|customer|enterprise_25|fleet, without_levers{total, per_plant, per_asset_year}, with_levers{..., by_lever, by_family}, uplift_multiple}],
                #   path[{id, label, value, kind: total|delta}]   # core -> +E1..E5 -> expansion -> 25 plants -> fleet
```

Compatibility: **every v1.0.0 key keeps its name, shape and — for Base and Conservative — its value** (a unit test pins the Base golden values). New data lives in new keys. Two additive details to know: each `acr.line_items[]` row has an extra `lever` field (`"core"` or `"E1"`…`"E5"`), and when levers are switched on `benefits.by_category`, `benefits.category_labels` and `benefits.confidence` gain `data_platform` and `cyber_risk` (E4, E5) — iterate over the dicts and read labels from `category_labels` instead of hard-coding the ten core categories. Lever customer costs are booked in the existing `costs.other_by_category` buckets and lever Azure consumption in the existing twelve families, so ROI totals stay consistent.

`compute_all(assumptions)` returns `{model_version, assumptions_version, currency, price_retrieved_on, reference_customer, headline{scenario: {...}}, scenarios{conservative, base, upside}}`; `headline` gained `expansion_*` and `fleet_*` keys.

## 4. Overrides the live calculator can change

`overrides` is a dict `{assumption_id: value}` applied after the scenario is resolved (unknown ids, wrong types and values outside `min`/`max` raise `ValueError`). Use `with_sensitivity=False` for slider-speed recalculation (~2 ms). Bounds below are the validity limits stored in `assumptions.json`.

| Key | Meaning | Base | Allowed |
|---|---|---:|---|
| `plants_total` | plants in scope (roll-out follows `plants_cum_share_by_year`) | 8 | 1 – 200 |
| `plants_cum_share_by_year` | cumulative share live at each year-end (adoption pace) | [0.25, 0.625, 1.0] | 3 values 0 – 1 |
| `revenue_usd` | enterprise revenue (per plant = ÷ plants) | 2.0e9 | 1e7 – 2e11 |
| `assets_per_plant` | monitored assets per plant (drives Azure usage and hardware) | 400 | 10 – 5,000 |
| `downtime_cost_per_line_hour_usd` | cost of an unplanned production-line hour (null = derived from revenue) | null (≈ 4,167) | 100 – 5,000,000 |
| `baseline_unplanned_downtime_pct` / `downtime_reduction_pct` | downtime baseline and what the swarm removes | 5.4 % / 20 % | 0 – 50 % / 0 – 90 % |
| `loaded_labour_rate_usd_per_hour` | loaded labour rate for indirect-labour savings | 52 | 5 – 300 |
| `indirect_labour_fte_per_plant` / `indirect_labour_productivity_gain_pct` | indirect FTE pool and gain | 55 / 10 % | 0 – 2,000 / 0 – 60 % |
| `energy_spend_pct_revenue` / `energy_saving_pct` | energy baseline and saving | 2.5 % / 5 % | 0 – 30 % / 0 – 50 % |
| `scrap_rework_cost_pct_revenue` / `scrap_reduction_pct` | scrap & rework baseline and reduction | 2 % / 12 % | 0 – 30 % / 0 – 90 % |
| `discount_rate` | WACC | 10 % | 0 – 50 % |
| `benefit_ramp` | benefit realisation in years 1, 2, 3+ after each go-live (**adoption ramp**) | [0.35, 0.75, 0.95] | 3 values 0 – 1.2 |
| `go_live_month_in_year` | month of each cohort's go-live | 7 | 1 – 12 |
| `platform_licence_per_plant_usd_year` / `platform_licence_enterprise_usd_year` | SwarmAI subscription | 160k / 300k | 0 – 5M / 0 – 10M |
| `azure_price_multiplier` | 1.0 = list price; 0.85 = 15 % discount (affects customer cost **and** ACR) | 1.0 | 0.3 – 1.5 |
| `llm_usage_multiplier`, `data_volume_multiplier` | agent/copilot call volume; telemetry richness | 1.0 | 0 – 20 / 0 – 50 |
| `price.<price_id>` | override one Azure meter, e.g. `price.fabric_cu_hour` | list | ≥ 0 |

Every other id in `assumptions.json` can be overridden the same way (e.g. `contingency_pct_one_time`, `edge_server_cost_usd`, `fabric_cu_per_plant`, `compute_vcpu_per_plant`). The live app **vendors `model.py` + `assumptions.json` + `outputs.json` together** (v1.1.0, byte-identical to this folder — enforced by a test); its whole-document parity test reproduces `outputs.json` (Base, Conservative, Upside, every key) within 0.5 % and passes — the interface above is frozen, so the app never needs a different model. `override_specs()` for the calculator controls is derived in the app from `assumptions.json`.

## 4a. Expansion levers E1–E5 (new in v1.1.0)

A real dark-factory programme adds more than the core platform once autonomy is proven. Five optional **expansion levers** model what it adds on Azure **and** what it costs and returns for the customer, so ACR is never shown without the ROI that justifies it. All five are **OFF in Base and Conservative** (adoption 0 — Base numbers are unchanged) and **ON in Upside** (adoption 50 % / 75 % / 50 % / 100 % / 100 %, shorter start lags and faster ramps). The `expansion` output block always shows the **expansion case** (Upside adoption of the levers on top of the scenario's other inputs), so "Base vs Base + expansion" needs no extra run.

| Lever | What it adds on Azure (unit prices: Retail Prices API) | Customer-side cost (existing cost buckets) | Benefit (risk-adjusted) | Honest size |
|---|---|---|---|---|
| **E1 Machine-vision fleet** | cameras × frames/s × upload share → ADLS hot/cool archive; AML T4/A100 retraining; low-confidence frames to gpt-5.4-mini / gpt-5.4; Log Analytics | camera stations and edge GPU servers (edge hardware), integration, vision licences, review FTE | scrap/escape cost (scrap), inspection labour (labour) | ≈ $29k Azure per plant-year — edge inference is customer-side, so Azure carries archive, retraining and exceptions |
| **E2 High-frequency condition monitoring** | kHz channels × duty cycle → Event Hubs, ADLS raw waveforms, OneLake features, Fabric CU, AML training/endpoint | sensors and DAQ, integration, per-asset licences | extra downtime reduction (downtime), planned instead of emergency work (maintenance) | ≈ $15k per plant-year — **small**; continuous raw streaming (`exp_hf_duty_cycle` = 1) multiplies it |
| **E3 Continuous sim-first what-if at scale** | decisions/day × rollouts × vCPU-seconds → D16s v5 simulation pools (AKS/Batch), results storage, Cosmos DB scenario cache | twin calibration, AgentOps FTE | higher autonomy levels: labour, energy, throughput | ≈ $47k per plant-year; discrete-event simulation is cheap, Monte-Carlo at scale is not |
| **E4 Enterprise data-platform modernisation** | Fabric capacity per migrated plant + enterprise capacity (`exp_dp_fabric_cu_enterprise`, scaled with the shared-platform factor), 7–10-year OneLake retention, migrated historian archive | migration programme and per-plant migration, BI creators (Power BI Pro: Microsoft 365, **not ACR**), data-engineering FTE | avoided historian and BI licences, analytics productivity (new category `data_platform`) | the largest single step: ≈ $0.3M enterprise Fabric at 8 plants plus ≈ $5k per plant |
| **E5 OT security & connectivity hardening** | second diverse ExpressRoute circuit (1 Gbps metered) and metered data out, Azure Firewall Premium per hub, Defender for Servers P2 on OT servers, Sentinel OT ingestion, Log Analytics | OT network sensors, Defender for IoT site licence (**Microsoft 365, not ACR**, assumption — no Azure meter exists), zones-and-conduits integration, SOC FTE | expected cyber-incident loss avoided and insurance premium (new category `cyber_risk`) | ≈ $26k per plant-year; a **risk and compliance** lever that roughly breaks even — said so in the outputs |

**Override keys** (all validated: unknown ids, non-numeric values, values outside `min`/`max` and wrongly sized lists raise `ValueError`):

| Key | Meaning | Base → Upside | Allowed |
|---|---|---|---|
| `exp_vision_adoption`, `exp_hf_adoption`, `exp_sim_adoption`, `exp_dp_adoption`, `exp_sec_adoption` | **the switches**: share of live plants (equivalently, share of the reference footprint in every plant) that deploy E1 … E5 | 0 → 0.5 / 0.75 / 0.5 / 1.0 / 1.0 | 0 – 1 |
| `exp_vision_start_lag_months`, `exp_hf_…`, `exp_sim_…`, `exp_dp_…`, `exp_sec_…` | months after a plant's go-live before the lever starts (cost and benefit ramps run from there) | 6 / 3 / 9 / 3 / 0 → 3 / 0 / 6 / 0 / 0 | 0 – 36 |
| `exp_benefit_ramp`, `exp_usage_ramp` | lever benefit and usage by year since the lever started (3 values) | [0.4, 0.8, 1.0] / [0.6, 0.9, 1.0] | 3 values 0 – 1 |
| `exp_vision_cameras_per_plant`, `exp_vision_fps_per_camera`, `exp_vision_upload_share`, `exp_vision_image_mb`, `exp_vision_retention_months`, `exp_vision_escalation_share` | E1 volume drivers | 30, 0.5, 3 %, 1.5 MB, 36, 0.8 % | see `min`/`max` |
| `exp_hf_rotating_assets_share`, `exp_hf_channels_per_asset`, `exp_hf_sample_rate_khz`, `exp_hf_duty_cycle`, `exp_hf_raw_retention_months`, `exp_hf_fabric_cu_per_plant` | E2 volume drivers | 20 %, 3, 25.6, 5 %, 24, 3 | see `min`/`max` |
| `exp_sim_decisions_per_plant_day`, `exp_sim_rollouts_per_decision`, `exp_sim_vcpu_seconds_per_rollout`, `exp_sim_node_utilisation` | E3 sizing drivers | 1,500, 64, 45, 60 % | see `min`/`max` |
| `exp_dp_fabric_cu_per_plant`, `exp_dp_fabric_cu_enterprise`, `exp_dp_onelake_retention_months`, `exp_dp_historian_tb_per_plant`, `exp_dp_bi_creators` | E4 sizing drivers | 8, 64, 96, 5, 300 | see `min`/`max` |
| `exp_sec_er_circuits_per_plant`, `exp_sec_sentinel_gb_per_plant_day`, `exp_sec_servers_per_plant`, `exp_sec_plants_per_hub`, `exp_sec_ot_site_licence_usd_year` | E5 sizing drivers | 1, 6, 30, 25, 24k | see `min`/`max` |
| `exp_*_quality_*`, `exp_*_conf*`, `exp_*_integration_usd`, … | benefits, confidence factors and customer costs of each lever (every id has a label, unit, low/base/high, flag and rationale in `assumptions.json`) | — | see `min`/`max` |
| `exp_fleet_plants` | plants in the illustrative enterprise-fleet tier of the `expansion` block | 100 | 2 – 2,000 |
| `price.vm_nc24ads_a100_v4_hour`, `price.expressroute_1gbps_metered_circuit_month`, `price.expressroute_metered_data_out_gb`, `price.azure_firewall_premium_deployment_hour`, `price.azure_firewall_premium_data_processed_gb`, `price.defender_servers_p2_node_hour` | the six new Azure meters (queries in `prices/queries.json`, retrieved 2026-11-17) | list | ≥ 0 |

**Calculator recipes.** Everything on: `{"exp_vision_adoption": 1, "exp_hf_adoption": 1, "exp_sim_adoption": 1, "exp_dp_adoption": 1, "exp_sec_adoption": 1}`. Only the vision fleet: `{"exp_vision_adoption": 1}`. 100-plant fleet: `{"plants_total": 100, "revenue_usd": 25e9, **all adoption keys}` or read `expansion.tiers[id="fleet"]` (steady-state run-rate, plants set by `exp_fleet_plants`).

**How the levers enter the model.** Lever Azure lines are `quantity × unit price` per deploying plant, flagged `provisioned` / `usage` / `stock` / `shared` like the core lines, get the same dev/test and DR uplifts (E3's stateless simulation pools: dev/test only) and start `provision_lead_months` before the lever's start month. One-time lever costs (hardware, integration, change) fall `hardware_lead_months` / `integration_lead_months` / `change_lead_months` before the start, with the 10 % contingency; run costs scale with deploying plants. Benefits use the lever's own confidence factors and `exp_benefit_ramp`. `levers[].by_year` and `levers[].npv` show each lever's own flows; the 3-year NPV of a lever is usually negative (investment first, payback in 6–14 months once running), the 5-year memo shows the return. Excluded from ACR on purpose: Defender for IoT OT licences, Power BI Pro and other Microsoft 365 licences, carrier charges.

## 5. How to extend

* **New benefit lever:** add the category to `BENEFIT_CATEGORIES`, its formula in `_plant_benefits`, a `conf_<id>` confidence factor and its inputs to `assumptions.json`; the test that every assumption is read will tell you if something is orphaned.
* **New Azure service:** add the price query to `prices/queries.json`, run `fetch_prices.py snapshot`, copy the price into `assumptions.json`, add a `_line(...)` in `_plant_lines` (per plant) or `_aggregate_lines` (shared) with the right `kind` and family.
* **Refresh prices:** `python prices/fetch_prices.py snapshot --queries prices/queries.json --out prices/prices-snapshot.json --date <YYYY-MM-DD>`, copy changed prices, bump `meta.price_basis.retrieved_on`, run `python model.py` and the tests.
* **Customer calibration:** replace the baselines (downtime hours, maintenance budget, scrap ledger, energy bill, inventory, expedite spend) with the customer's actuals — the tornado shows which ones matter most (benefit ramp, downtime cost per hour, downtime reduction, roll-out pace, go-live timing).

## 6. Known limits (read before quoting)

* Benefit baselines are assumptions flagged `assumption`; only the downtime baseline, OEE baseline and Eurostat employment are tied to published sources. Ranges are wide on purpose.
* The A/B replay in the product measures *simulated* uplift on synthetic assumptions and does not replace a pilot on the customer's historian data. It supports the downtime, OEE/throughput and late-delivery categories (§1a), shows **no significant effect on scrap**, and for energy shows a lower *price paid per kWh* but a **higher absolute cost** (+6 %) — so the scrap and energy categories are benchmark/assumption-only and the energy benefit exists only where tariffs vary.
* ACR is list price: real consumption is lower with enterprise agreements and reservations (use `azure_price_multiplier`), higher with provisioned model throughput or heavier telemetry (see `llm_usage_multiplier`, `data_volume_multiplier`, `fabric_cu_per_plant`).
* SwarmAI licence prices are pricing hints, not a price list. Microsoft has made no commitment to any roadmap item referenced in the product documents.
* The expansion levers (§4a) are the least-evidenced part of the model: sizing, costs and benefits are assumptions (flagged, with ranges) to be replaced by pilot data; E1–E4 are calibrated to pay back within about 6–14 months once running and E5 to roughly break even, but within a 3-year window the levers lower NPV (investment first) and add to ACR. Per-lever Azure consumption is small for E2 and E3 at plant level; the multi-million run-rate comes from fleet scale (`expansion.tiers`, fleet) and from E4's enterprise Fabric capacity. Reservations, savings plans, spot VMs and archive-tier storage would lower the modelled ACR and are not assumed.
