# Business case — customer ROI and Azure Consumed Revenue (ACR)

Everything the PRD, the deck and the live ROI/ACR calculator quote comes from **one pure-Python model** and **one assumptions file**.
Nothing here is a forecast or a Microsoft commitment: the case is illustrative and assumption-driven — *validate every driver with customer data*.

| File | Role |
|------|------|
| `assumptions.json` | 272 assumptions (value, unit, low / base / high, favourable direction, rationale, source, flag) — 75 of them for the expansion levers — 59 Azure Retail Prices API meters (list price, with selector and retrieval date), footprint and tier definitions, sensitivity drivers, expansion-lever configuration, public sources |
| `model.py` | **Pure standard library**, deterministic: `compute()`, `compute_all()`, `override_specs()`, `load_assumptions()`; `python model.py` regenerates the outputs (model v1.1.0) |
| `outputs.json` | Machine-readable results for Conservative / Base / Upside — **what the PRD and the deck quote** |
| `outputs.md` | Human-readable report generated from `outputs.json` (tables for every number, assumption register) |
| `test_model.py` | 41 unit tests (`python -m unittest test_model -v`): identities, scenario order, overrides, validation, price snapshot, expansion levers, parity of `outputs.json` |
| `refresh_prices.py` | Verifies (or `--write`s) the price snapshot against the live Azure Retail Prices API |

Reference customer: **Contoso Consumer Brands** (fictional) — US$8 B revenue, marketing ≈ 8 % of revenue (Gartner 2026 average 7.8 %), 12 markets, ≈ 5,000 creative assets a year today, target 50,000 approved versions with personalisation, 6–10 week cycle time.

## 1. How it works

**Timeline.** Year 0 = implementation (one-time spend, no benefit); Years 1–3 = operation. Annual cash flows, end-of-year discounting (Year 0 undiscounted). Outputs: 3-year NPV, ROI % = (Σbenefit − Σcost) / Σcost, payback in months from Year 0 (linear within a year), IRR, break-even benefit haircut (how far every benefit could fall before NPV = 0).

**Adoption ramp** `adoption_y1..y3` (base 15 % / 50 % / 85 %) = share of full-adoption volume in each year. Approved versions in year *t* = ramp × `annual_asset_volume` (50,000).

**Benefits** (seven categories, each × a confidence factor, each credited only for work the customer would otherwise have bought):

| Category | Formula (per year *t*, gross before confidence) |
|---|---|
| Production & adaptation | `replacement_t × Σ_class baseline_units × unit_cost × addressable_share` |
| Agency fees | `replacement_t × Σ_class (production pool × fee%) × addressable × fee_reduction` |
| Localization | `replacement_t × baseline_assets × loc_share × depth × cost_per_localized_version × reduction` |
| Cycle time / speed | `time_critical_campaigns × weeks_saved × weekly_gross_profit × realisation × replacement_t` |
| ROAS / CPA uplift | `media_in_scope × coverage_t × baseline_ROAS × uplift × ln(1+variants)/ln(1+12) × contribution_margin` |
| Compliance-incident avoidance | `(incidents × cost × reduction + P(severe) × cost × reduction) × replacement_t` |
| Rework & media waste | `replacement_t × (addressable production + fees) × rework% × reduction + media × coverage_t × waste% × reduction` |

`replacement_t = ramp_t × min(1, annual_volume / baseline_assets)`; `coverage_t = min(1, volume_t / volume_for_full_coverage)`; `loc_share = min(cap, 3.6 % × (markets − 1))`. **Versions beyond today's volume earn no avoided-agency-cost credit** — they pay back only through uplift — while *every* Studio version is charged its Azure and review cost.

**Costs** = Azure run cost (identical to the ACR of the same scenario, list price) + platform licence & support + implementation & integration (Y0/Y1) + integration run + change management & training + licensed music/stock + human review (minutes per version × loaded rate, linguist QA, Guardian exceptions). No credit is taken for avoided internal review hours.

**ACR, bottom-up** — for each service family, *units × Azure Retail Prices API list price* (PAYG, USD, swedencentral; global meters for Front Door / Translator / Private Link; no EA/MACC discount, no reservations):

| Family | Units driven by |
|---|---|
| Azure OpenAI text / vision / embeddings | tokens per campaign (briefing, strategy, script, storyboard, Guardian stages, pre-flight, insights), per version (adaptation, Guardian checks × auto-revise loop, localisation, continuous re-checks), interactive co-creation (users × actions/day × calls/action), cached-input share |
| Azure OpenAI image generation | images per campaign / per version × attempts × output-image tokens × output-token price (+ prompt and reference-image input) |
| Speech & translation | tts-hd + Azure AI Speech neural characters, Translator characters |
| Content Safety | text records and images (generated + sampled frames) |
| AI Search | search units × hours (SKU per footprint) + semantic-ranker queries |
| Cosmos DB | autoscale RU/s × utilisation × regions + storage |
| Blob/ADLS + Front Door | GB stored (deliverables × working-file factor, accumulating), operations, delivered GB, requests, Front Door base fee |
| Container Apps + registry | app replicas (active/idle) + render vCPU-seconds (ffmpeg compositor) |
| Service Bus + Event Grid | base/messaging units + events per version |
| Fabric analytics | capacity units × hours × utilisation + OneLake |
| Monitoring / security / API gateway / networking | Log Analytics GB, Key Vault, Defender, Purview, APIM, private endpoints |
| **Pull-through (attach)** | DAM archive migration (TB), marketing data-platform capacity (CU), security & network landing zone (ratio of direct fixed cost) |

Fixed platform cost depends on the **footprint** (pilot / one-brand / global-portfolio / agency-network), with non-production and DR multipliers; the reference customer blends footprints by year (`reference_footprint_blend`). `pull_through_ratio` = Year-3 attach ÷ direct.

**Scenarios.** Only the key value drivers listed in `meta.scenario_drivers` (adoption, baseline cost per asset, addressable share, ROAS uplift, media in scope, licence, implementation, change cost) and the partner-pipeline counts move, **half-way (`scenario_blend` = 0.5) from Base towards their unfavourable (Conservative) or favourable (Upside) bound**. All other assumptions stay at Base and are flexed one at a time, over their full low/high range, in the **tornado** (`sensitivity[]`). Stacking every bound would be a worst/best case, not a scenario. The four expansion-lever scales are on/off decisions rather than calibrated drivers: they carry an entry-level `blend` of 1.0, so Conservative and Base = 0 (Release-1 scope) and Upside = 1 (§1a).

**Tiers** (`acr.tiers`) = steady-state annual ACR for a *pilot*, *one brand*, *global portfolio* (the reference customer at 100 % adoption), an *agency network* (multi-tenant) and an **enterprise-scale** customer (catalog + generative video + personalization, see §1a). **Portfolio** (`acr.portfolio`) = illustrative partner pipeline (new customers per tier per year × customer-age ramp 50/80/100 %; pilots last 12 months) and `acr.tam` = directional ceiling (target accounts × tier run-rate, plus an expansion ceiling). **Unit economics** (`unit_economics`) = Azure cost per approved version (direct, variable only, incl. pull-through), all-in Studio cost per version and agency cost per asset by class — campaign-scale studio only; the expansion units (per generated video second, per catalog image, per personalised version) are in `acr.expansion`.

### 1a. Expansion levers E1–E4 (optional, Release 2+) — why and how

The core model is the **Release-1 campaign studio**. Four optional levers show where much larger Azure consumption comes from, each with **its own Azure consumption, customer benefit and non-Azure cost**, so the ROI stays coherent. They are *off* (`e*_scale = 0`) in Conservative and Base — Base numbers are exactly the Release-1 numbers — and *on at full scale* in Upside. `e*_scale` ∈ [0, 1] is the share of the lever's full-scale volume reached by the end of Year 3; the ramp `exp_ramp_y1..y3` (10 % / 45 % / 100 %) spreads it over the years. Roadmap: E1 = R2-01, E2 = R2-21, E3 = R2-02, E4 = R2-08 / R2-22 (`FEATURES.md`).

| Lever | Azure consumption (list price × units) | Customer benefit (× confidence) | Non-Azure cost |
|---|---|---|---|
| **E1 Generative video** behind `VideoProvider` | hero masters / adapted videos using generated footage × kept seconds × **takes** × `$ per generated second` (Sora 2 standard $0.10 and Pro high-res $0.50 from the Retail API; blend by premium share), + Guardian text, Content Safety on sampled frames (1 fps), conform / transcode compute, storage | share of the **residual** (not already displaced) hero / adapted external cost that generated footage replaces: stock, 3D / VFX, animatics, pick-ups | integration, run %, extra creative / legal / likeness review minutes |
| **E2 Catalog-scale product content** | SKUs × markets × market presence × images per listing × refresh share × attempts → `gpt-image-1.5` image tokens; localized descriptions and alt-text (`gpt-5.4-mini`), Guardian per listing, Content Safety, Blob renditions + Front Door pulls, AI Search units per million images | kept images × blended cost per image today × displaced share; **plus a separately flagged conversion / return-rate effect** (online revenue share × relative uplift × margin, 25 % confidence) | PIM / e-commerce integration, run %, sampled review |
| **E3 Audience-level personalization** | segment variants (5–20× per approved version) priced with the **same unit-consumption assumptions as the core pipeline** (× `e3_consumption_factor`), plus extra Cosmos RU/s, AI Search units and Fabric capacity | incremental ROAS uplift (2 %) on in-scope media × coverage × margin — on top of the creative-testing uplift in the core | integration (audience / consent data), run %, sampled review |
| **E4 Marketing data & clean-room platform** (Fabric) | Fabric capacity (CU × hours share × dev/test+DR multiplier), OneLake TB, Purview, Log Analytics | extra share of paid media brought into measured optimisation × the core ROAS-uplift and media-waste mechanism | integration (CRM / CDP, identity, clean room), run %, data-engineering operations |

Common rules: lever fixed infrastructure carries `exp_fixed_multiplier` (dev/test + DR, 1.25); the security / network pull-through rate applies to lever fixed cost; integration is charged only for levers whose scale is above zero (`exp_integration_share_y1` in Year 1, the rest in Year 2); every benefit line has its own confidence factor.

**Where it shows in the outputs** (all new keys; no existing key changes meaning):

* `benefits.by_category` gains `exp_generative_video`, `exp_catalog_content`, `exp_personalization`, `exp_data_platform`; `costs.other_by_category` gains `expansion_integration`, `expansion_run`, `expansion_review`. All are zero-filled while a lever is off, so the schema never varies. The levers' Azure consumption is folded into the existing 14 families (`azure_openai_image` is now labelled "image & video generation") and therefore into `costs.azure_total_by_year`, `acr.by_year` and the ROI.
* `acr.by_lever` = `{core, e1, e2, e3, e4}` → ACR by year (the stack for "path to multi-million"); `acr.by_lever_labels`.
* `acr.expansion` = `levers` (this scenario: scale, ACR by year and family, benefit by year and component, non-Azure cost, net flow, lever NPV and payback, benefit per Azure dollar, units), **`full_expansion_case`** (the same scenario with all four levers at full scale: ACR by year and by lever, NPV, ROI, payback, `incremental_vs_this_scenario`), **`levers_off_case`** (the same scenario with every lever off — Upside's v1.0.0 numbers — plus `incremental_of_levers_in_this_scenario`), `enterprise_path` and `reference_customer_path` (waterfall steps), `reference_customer_expanded_tier`, `enterprise_unit_economics`, `video_price_reference`, `notes`.
* `acr.tiers[]` gains the fifth tier `enterprise_scale` (with `expansion.by_lever_usd`, `units`, `unit_economics`); `volumes.expansion`, `inputs.expansion`, `sensitivity[]` gains the `expansion` row; `meta.summary.<scenario>` gains `acr_by_lever_year3`, `full_expansion_acr_by_year`, `full_expansion_npv`, `enterprise_tier_acr_run_rate_usd`.

**Honest reading.** Generative video and catalog imagery are cheap per unit at list price (**cents per image, dollars per kept video second** — video is billed per generated second, rejected takes included), so E1 and E2 add little Azure consumption at this customer's volumes even though their customer benefit is large (E2 has the best ROI and the smallest Azure bill). The consumption that makes ACR material comes from the **data platform (E4)**, **segment-scale personalization (E3)** and from **customer breadth and users** — the enterprise-scale tier, where a larger group runs 3× the versions, 20 markets and 1,000 users on a bigger platform. At the reference customer's own volumes the levers roughly double ACR; at enterprise scale the run-rate is about five times the campaign-scale baseline. Three of the four levers are close to NPV break-even within three years at the reference customer's volumes: they add ACR and absolute NPV in Upside but dilute ROI % and payback, because their integration and run costs are front-loaded.

## 2. Interface (stable — the live app vendors `model.py` + `assumptions.json`)

```python
import json, model
A = model.load_assumptions()                     # or json.load(open("assumptions.json"))
r = model.compute(A, "base", overrides={"markets": 8, "adoption_ramp": [0.1, 0.4, 0.7]})
all3 = model.compute_all(A)                      # {"meta": {...}, "scenarios": {"conservative": ..., "base": ..., "upside": ...}}
```

`compute()` returns (all money in USD; every `*_by_year` list is indexed by `years = [0, 1, 2, 3]`):
`scenario`, `scenario_label`, `currency`, `horizon_years`, `years`, `customer`, `inputs{resolved, overrides, adoption_ramp, …}`, `volumes`,
`benefits{by_category, total_by_year, total, detail{gross, confidence, net}}`, `costs{azure_by_family, other_by_category, total_by_year, total, …}`,
`roi{net_benefit_by_year, cumulative, npv, discount_rate, roi_pct, payback_months, irr_pct, breakeven_benefit_haircut_pct, …}`,
`acr{by_year, by_family, run_rate_year3, tiers, pull_through_ratio, portfolio, tam, by_lever, expansion, …}`, `unit_economics`, `sensitivity[]` (tornado: `id, label, npv_low, npv_high, swing`).

**Interface stability (v1.1.0).** `load_assumptions`, `compute(assumptions, scenario="base", overrides=None)`, `compute_all(assumptions)` and `override_specs()` keep their signatures; every v1.0.0 output key is still present with the same meaning and, while the expansion levers are off (Conservative, Base), the same values — only keys, list entries (a fifth tier, extra benefit / cost categories, one more tornado row) and dict entries were *added*. Re-vendor `model.py` + `assumptions.json` together (the loader fails loudly on missing keys).

**Parity contract for the app (CS-23).** `model.compute(A, "base")` must equal `outputs.json → scenarios.base` (the shipped test asserts exact equality; the app test may allow 0.5 %). `outputs.json → meta.assumptions_sha256` identifies the assumption set used.

### Override keys (validated; unknown keys or out-of-range values raise `ValueError` → HTTP 422)

| Key | Meaning | Range | Maps to |
|-----|---------|-------|---------|
| `annual_asset_volume` | Approved versions / year at full adoption | 1,000 – 2,000,000 | `annual_asset_volume` |
| `markets` | Number of markets (integer) | 1 – 60 | `markets` |
| `variants_per_campaign` | Creative variants tested per campaign | 1 – 100 | `variants_per_campaign` |
| `media_spend_in_scope_usd` | Paid media carrying Studio-optimised creative (full adoption) | 0 – 5e9 | derived default = revenue × marketing % × paid-media % × scope % |
| `roas_uplift_pct` | ROAS uplift at 12 variants and full coverage | 0 – 0.5 | `roas_uplift_pct` |
| `discount_rate` | Discount rate | 0 – 0.3 | `discount_rate` |
| `adoption_ramp` | `[y1, y2, y3]` share of full-adoption volume | each 0 – 1 | `adoption_y1..y3` |
| `agency_cost_per_spot_usd` | Agency + production cost per 30 s hero spot | 10k – 5M | `baseline_cost_hero_spot` |
| `agency_cost_per_adapted_asset_usd` | … per adapted video asset | 100 – 100k | `baseline_cost_adapted_video` |
| `agency_cost_scale` | Multiplier on all four baseline unit costs | 0.1 – 5 | all `baseline_cost_*` |
| `studio_review_scale` | Multiplier on Studio human-review minutes (Studio cost per asset) | 0.1 – 5 | `review_minutes_scale` |
| `platform_licence_usd_per_year` | Licence & support at full scale | 0 – 1e8 | same |
| `azure_consumption_scale` | Calibrate unit consumption with the live meter | 0.1 – 10 | same |
| `ai_price_uplift_pct` | Model price basis (0 = Global, 0.10 = EU Data Zone) | 0 – 0.5 | same |
| `baseline_assets_per_year`, `baseline_roas`, `contribution_margin_pct`, `active_users_full`, `implementation_usd` | advanced | see `override_specs()` | same |
| `expansion_scale` | **Master switch** for the four expansion levers (0 = off, 1 = full scale by Year 3); an explicit per-lever key wins | 0 – 1 | `e1_scale … e4_scale` |
| `e1_scale` | E1 generative video through `VideoProvider` | 0 – 1 | `e1_scale` |
| `e2_scale` | E2 catalog-scale product content | 0 – 1 | `e2_scale` |
| `e3_scale` | E3 audience-level personalization | 0 – 1 | `e3_scale` |
| `e4_scale` | E4 marketing data & clean-room platform on Fabric | 0 – 1 | `e4_scale` |
| `expansion_ramp` | `[y1, y2, y3]` share of the Year-3 lever scale reached in each year (default 0.10 / 0.45 / 1.0) | each 0 – 1 | `exp_ramp_y1..y3` |
| `catalog_skus` | E2 active SKUs needing product-page content | 100 – 5,000,000 | `e2_skus` |
| `personalization_multiplier` | E3 segment variants per approved version at full scale | 1 – 100 | `e3_multiplier` |
| `video_seconds_per_hero_master`, `video_seconds_per_adapted_video` | E1 kept generated seconds per hero master / adapted video that uses the lever | 0 – 600 / 0 – 120 | `e1_hero_gen_seconds`, `e1_adapted_gen_seconds` |
| `data_platform_fabric_cu`, `data_platform_onelake_tb` | E4 Fabric capacity units and OneLake TB at full scale | 0 – 2,048 / 0 – 5,000 | `e4_fabric_cu`, `e4_onelake_tb` |
| *any assumption key* | e.g. `review_min_adapted_video`, `exception_rate`, `e2_images_per_listing`, `e1_hero_takes`, `e4_scope_increase_pct` | ≥ 0 | itself |

`override_specs()` returns this table as data (label, unit, min, max, `calculator` flag for the UI).

## 3. Price snapshot (audit trail)

Prices are **list prices from the Azure Retail Prices API** (`https://prices.azure.com/api/retail/prices`), pay-as-you-go, USD, retrieved **2026-11-17** for `swedencentral` (global meters where the service is global). Each item in `assumptions.json → pricing.items` records `service`, `product`, `meter`, `region`, `tier_min` (tierMinimumUnits), the raw `api_price` + `api_unit`, a `factor` to the model's unit and the normalised `price`. Query pattern:

```bash
curl -sG "https://prices.azure.com/api/retail/prices" --data-urlencode "\$filter=armRegionName eq 'swedencentral' and serviceName eq 'Foundry Models' and meterName eq '5.4 mini Inp Gl 1M Tokens' and priceType eq 'Consumption'"
python refresh_prices.py          # re-checks all 59 items against the live API (exit 1 if anything moved)
python refresh_prices.py --write  # updates the snapshot + retrieved_at, then run: python model.py
```

Basis: models at **Global Standard** list price plus `ai_price_uplift_pct` (Data Zone Standard is listed 10 % higher, Regional about 21 %); text-embedding-3-small uses the only meter listed in the region (Data Zone). **Generative video (E1 only):** Azure OpenAI *Sora 2* meters (`Sora 2 glbl Second` $0.10 standard, `Sora 2 pro high res glbl Second` $0.50 premium; `Sora 2 pro glbl Second` $0.30 as a reference) are priced per generated second — *assumption: availability varies by region; sora-2 is a preview model on Microsoft Learn and is deprecated in swedencentral as of Nov 2026*, so the `VideoProvider` plug-in can target another region or a partner video model; the Foundry catalog lists partner models ("Azure Fal" meters, effective 2026-11-01) at about $0.03–$0.30 per second, kept as a price reference only (ACR eligibility to be confirmed). Excluded on purpose: EA/MACC discounts, reservations/savings plans, Provisioned Throughput (not rational at this volume), generative video in Conservative and Base (levers off), egress to ad platforms, customer-side Azure estate beyond the explicit pull-through lines.

## 4. How to extend

* **New or changed assumption** — edit `assumptions.json` (keep `low ≤ base ≤ high`, a rationale and a source/flag); `python model.py && python -m unittest test_model`. A new key used by the code must be added to `STATIC_KEYS`/`CLASS_TEMPLATES` in `model.py` (the loader fails loudly on missing keys).
* **New Azure service family** — add its meters to `pricing.items`, a block in `_azure_year()` (fixed vs variable) and the family to `FAMILY_LABELS` / `DIRECT_FAMILIES`; add any fixed-footprint parameters to `footprints`.
* **New benefit category** — add a gross formula and a `confidence_*` assumption in `_core()`, a label in `BENEFIT_LABELS`.
* **New tier / footprint** — add to `footprints` and `tiers`, and to `TIERS` in `model.py` (a tier with a `levers` block and `lever_params` also gets the expansion breakdown).
* **New expansion lever** — add its `*_scale`, volume, cost and `confidence_*` assumptions to `assumptions.json` (and `EXPANSION_KEYS` / `scenario_drivers`), a branch in `_lever_azure()` (consumption by family, fixed vs variable, units) and `_lever_econ()` (benefit and non-Azure cost), a label in `LEVER_LABELS` / `LEVER_BENEFIT_KEY` / `BENEFIT_LABELS`, and an `OVERRIDE_SPECS` entry.
* **Live override** — add the key to `OVERRIDE_SPECS` (with range and `maps_to`) so the calculator can expose it.
* **Calibrate with measured data** — replace the unit-consumption assumptions (tokens, images, vCPU-seconds, users × actions) with the averages from the reference implementation's meter (CS-15, `/api/usage`) or scale all of them with `azure_consumption_scale`; replace baseline unit costs with Contoso purchase-order data in the first week of the pilot.

## 5. Reading the result responsibly

* Azure is a small share of customer cost (≈ 13 % of 3-year cost, ≈ 5 % of benefit) — the ROI is driven by *adoption, baseline cost per asset, addressable share and the confidence you can place on uplift*, which is why those head the tornado.
* ACR per customer is modest at campaign scale (global-portfolio tier ≈ US$0.5 M a year, about 40 % fixed platform; the rest scales with users and versions, interactive co-creation being the largest variable line). The expansion levers roughly double it for the same customer and an enterprise-scale customer runs at about five times the campaign-scale baseline (§1a); the commercial opportunity also comes from breadth (accounts × tiers), pull-through and agency networks, not from per-asset intensity — unit prices are cents per image and dollars per kept video second.
* Pre-flight scores, bandit results and performance data in the product are simulations; the business case treats uplift as a hypothesis to be proven by a holdout test in the pilot (KPI-05).

```bash
python model.py                         # writes outputs.json and outputs.md
python -m unittest test_model -v        # 41 tests
python refresh_prices.py                # price snapshot vs live API
```
