# Business case model - SwarmAI Contact Center ("Concierge")

Single source of truth for **every ROI and Azure Consumed Revenue (ACR) number** in the PRD, the architecture and the deck.
Pure Python standard library, deterministic, no network at run time. The live app's ROI & ACR calculator (CC-13) **vendors `model.py` and `assumptions.json`**; its unit test asserts that it reproduces `outputs.json` for the reference scenario.

| File | Purpose |
|---|---|
| `assumptions.json` | Every assumption (value, unit, low / base / high, rationale, source, `flag`, `validate`) and every Azure unit price (with the Retail Prices API row it came from) |
| `model.py` | `compute(assumptions, scenario="base", overrides=None)`, `compute_all(assumptions)`, and a `__main__` that writes `outputs.json` / `outputs.md` |
| `outputs.json` | Machine-readable results for the three scenarios (+ headline numbers + stress tests) - **what the PRD, deck and app quote** |
| `outputs.md` | Human-readable report: scenario table, benefits, costs, ACR by service family, ACR by seat tier, line-item audit trail, unit economics, tornado, assumptions |
| `pricing_snapshot.json` | The exact Azure Retail Prices API rows behind every priced line (retrieved 2026-11-17) |
| `refresh_prices.py` | Re-queries the API, rewrites the snapshot, reports price drift (`--check` verifies offline) |
| `test_model.py` | 43 unit tests (`python -m unittest test_model -v`) |

## 1. Quick start

```bash
python model.py                       # rewrite outputs.json + outputs.md (prints the headline)
python model.py --check               # exit 1 if outputs are stale
python -m unittest test_model -v      # 43 tests
python refresh_prices.py              # (network) refresh pricing_snapshot.json and report drift
```

```python
import json, model
a = model.load_assumptions("assumptions.json")
r = model.compute(a, "base", {"containment": 0.25, "seats": 2000, "discount_rate": 0.12})
r["roi"]["npv"], r["roi"]["payback_months"], r["acr"]["run_rate_year3"]
```

## 2. Interface (stable)

`compute(...)` returns a JSON-serialisable dict. Time series have **4 entries: index 0 = Year 0 (build + pilot, one-time costs), 1-3 = production years**.

| Key | Contents |
|---|---|
| `scenario`, `currency`, `horizon_years`, `model_version`, `price_basis` | metadata |
| `inputs` | `assumptions` (resolved values after scenario + overrides), `overrides`, `derived` (cost per contact, cost per handling minute, ...), `ramps` |
| `volumes` | per year: contacts, AI-first contacts, AI-resolved contacts, AI voice minutes, assisted contacts, QA-scored contacts, ... |
| `benefits` | `by_category` (risk-adjusted), `gross_by_category`, `confidence_factors`, `total_by_year`, `total`, FTE-equivalents released |
| `costs` | `azure_by_family`, `other_by_category`, `total_by_year`, `total` (Azure + implementation + AI operations + licences + communications billed elsewhere) |
| `roi` | `net_benefit_by_year`, `cumulative`, `npv`, `discount_rate`, `roi_pct`, `payback_months` (from project start), `payback_months_from_go_live`, `irr_pct`, `benefit_cost_ratio` |
| `acr` | `by_year`, `by_family`, `by_group`, `run_rate_year3`, `three_year_total`, `tiers[]` (pilot 50 / 500 / 1,500 / 10,000 seats), `pull_through_ratio`, `line_items_year3[]` (audit trail), `opportunity_sizing` |
| `unit_economics` | cost per contact and per resolved contact, AI vs human; Azure cost per voice AI minute, per digital AI contact, per assisted human contact |
| `sensitivity[]` | tornado on NPV, sorted by swing: `assumption`, `low_value`, `high_value`, `npv_at_low`, `npv_at_high`, `swing` |

`compute_all(assumptions)` returns `{"conservative": ..., "base": ..., "upside": ...}`.

**`outputs.json` layout**

```
{ "meta": {...}, "headline": {"conservative": {...}, "base": {...}, "upside": {...}},
  "stress": {"stacked_downside": {...}, "stacked_upside": {...}},
  "scenarios": {"conservative": <compute()>, "base": <compute()>, "upside": <compute()>} }
```

Parity test for the app: `compute(a, "base")` must match `outputs.json["scenarios"]["base"]` within 0.5 % for `roi.npv`, `roi.roi_pct`, `roi.payback_months`, `acr.run_rate_year3` (the Python reference matches exactly; floats in the file are rounded to 4 decimals).

## 3. Scenarios

* **base** - base values.
* **conservative / upside** - uncertain *outcome* and *cost* assumptions (AI containment, AHT reduction, adoption and maturity ramps, confidence factors, implementation and AI-operations costs, ...) move **60 %** of the way (`meta.scenario_blend`) from base to their unfavourable / favourable bound. Customer facts (agents, contacts, cost per agent, attrition), Azure **usage drivers** and **prices** stay at base - they are stress-tested in the tornado and with `azure_usage_multiplier`, so the ACR range reflects adoption, not guesses about token counts.
* **stacked_downside / stacked_upside** (in `outputs.json -> stress`) - *every* uncertain driver at its bound at once (100 %). A stress test, not a forecast.

Each assumption's `kind` says how it behaves: `outcome` and `cost` move with scenarios; `customer_input`, `usage`, `finance`, `market` do not. `favourable` says which end helps the customer's NPV.

## 4. Overrides the live calculator can change

`overrides` maps assumption keys (or aliases) to replacement values; unknown keys raise `KeyError`, list values must have the same length. **Any key in `assumptions.json` is valid.** The ones the calculator exposes:

| Override key (alias) | Meaning | Base | Notes |
|---|---|---:|---|
| `agents` (`seats`) | contact-center agents | 1,500 | drives cost base, QA team, attrition, tier sizing |
| `contacts_per_year` (`contacts`) | contacts per year | 18,000,000 | drives volumes and Azure consumption |
| `voice_share_of_contacts` (`voice_share`, `digital_share`) | voice vs digital mix | 0.50 | `digital_share = 1 - voice_share` |
| `cost_per_contact_usd` | blended human cost per contact | derived $5.58 | replaces the derived value; back-solves cost per agent |
| `loaded_cost_per_agent_usd` | fully-loaded annual cost per agent | 67,000 | |
| `ai_containment_pct` (`containment`) | verified AI resolution of AI-first contacts at maturity | 0.30 | headline driver |
| `aht_reduction_pct` (`aht_reduction`) | AHT reduction on human-handled contacts | 0.12 | |
| `attrition_rate` (`attrition`) | agent attrition | 0.40 | |
| `qa_coverage_target` (`qa_coverage`) | share of contacts auto-QA'd | 1.00 | lowering it reduces both cost and benefit |
| `discount_rate` | NPV discount rate | 0.10 | |
| `adoption_ramp` (`adoption`, `ramp`) | share of contacts AI-first, [Y1, Y2, Y3] | [0.25, 0.60, 0.85] | also `maturity_ramp`, `assist_ramp`, `qa_ramp`, `ramp_other`, `attrition_ramp` |
| `azure_usage_multiplier` | stress factor on every Azure line | 1.0 | e.g. 1.5 = +50 % |
| `openai_deployment_type` | `"datazone"` (EU, default) or `"global"` price list | datazone | Global is about 9 % cheaper |
| `rt_full_model_share` | share of voice minutes on gpt-realtime-2.1 (rest on -mini) | 0.30 | |
| `comms_azure_billed_share` | share of communications spend billed through Azure (counts as ACR) | 0.0 | see section 7 |

## 5. How the numbers are built

**Baseline.** `cost per contact = agents x loaded cost per agent / contacts` ($5.58 for the reference customer; Gartner's 2019 poll reported $8.01 per live contact, so the baseline is conservative). Channel costs follow handle time (voice 6.5 min, digital 3.84 effective minutes). Only `variable_cost_share` (80 %) of loaded cost is cashable.

**Benefits** (year *t*, ramps from `assumptions.json`, each category multiplied by a **confidence factor**):

| Category | Formula (gross, before confidence) |
|---|---|
| AI containment | contacts x adoption x containment x maturity x cost per contact x Tier-1 AHT factor x variable share |
| AHT reduction | (baseline cost pool - containment savings) x assist coverage x AHT reduction x variable share |
| Auto-QA & quality | QA analysts x cost x effort reduction x coverage x ramp + repeat-contact reduction x cost per contact |
| Attrition / hiring | (agents x attrition reduction x ramp + FTE released x attrition rate) x replacement cost |
| Abandonment, CSAT, retention | recovered abandoned voice contacts x margin + customers x churn reduction x margin per customer |
| Peak resilience | overflow contacts x AI absorption x adoption x maturity x (overflow cost - in-house cost) |
| Compliance risk | incidents x cost per incident x reduction |
| Multilingual | small-language contacts x cost per contact x fragmentation overhead share x pooling recovery x variable share |

Only **verified resolutions** count as containment (resolve, not deflect). Excluded, deliberately: cross-sell/upsell revenue, outbound/proactive deflection (CC-18), wage inflation, tool consolidation, Microsoft licence discounts.

**Costs.** Year 0: implementation (fixed + per seat), change management, contingency, pilot Azure. Years 1-3: Azure consumption (bottom-up, below), AI operations team, third-party licences/SBC, support, and **communications billed outside Azure** (priced at ACS list rates as a proxy).

**ACR (bottom-up, per customer per year).** Each Azure family is `units x list price`; units come from volumes x usage drivers (token counts per minute and per turn, text records per contact, queries per contact, RU per contact, ...). Fixed platform items are sized from peak load: concurrent voice sessions -> vCPU; peak queries/s -> search replicas; RU/s -> Cosmos autoscale; seats in scope -> Fabric capacity ladder; discrete SKUs (Front Door, APIM, Event Hubs, Purview, regions) step up by seat tier (`assumptions.json -> tiers`). Realtime audio uses Microsoft's own estimate of about 10 input and 20 output audio tokens per second (Learn: Voice Live API token estimation) with cached re-reads of the growing context on every response. A non-production uplift (20 %) applies to fixed items. `outputs.md` lists every Year-3 line (quantity x unit price x factor).

**Unit economics.** Azure cost per voice AI minute, per digital AI contact, per assisted contact, per QA-scored contact, per AI-resolved contact; all-in AI cost per resolved contact (adds AI operations, licences, support, communications and amortised one-time costs) versus human cost per resolved contact.

**Payback** is measured from project start (build + pilot = `implementation_months`) with benefits ramping inside each year and costs spread evenly (conservative); `payback_months_from_go_live` is also returned. **IRR** uses Year 0 as the investment. **ROI %** = (benefits - costs) / costs over Years 0-3, undiscounted.

## 6. Sources and flags

* **Azure unit prices** - Azure Retail Prices API (public, list price, USD, pay-as-you-go), swedencentral meters, retrieved **2026-11-17**; Azure OpenAI at **Data Zone (EU) Standard** rates (Global Standard is about 9 % cheaper). Query pattern: `$filter=serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and productName eq 'Azure OpenAI Media'`. Each price has a `ref` and its row is stored in `pricing_snapshot.json`; `test_model.py` fails if they differ. Fabric CU-hour is $0.19 in swedencentral ($0.22 in westeurope).
* **Not in the Retail API**: ACS SMS rates for EU destinations (taken from Microsoft Learn, alphanumeric sender, equal-weight mean of 8 markets = $0.0708) and the Private Link endpoint hour ($0.01, published list price) - both flagged as assumptions in `assumptions.json`.
* **Benchmarks used as cross-checks** (not as inputs): Gartner 2019 poll ($8.01 live vs $0.10 self-service per contact); Gartner 2022 (about 17 M agents worldwide; integration $1,000-$2,000 per agent); Gartner 2025 (80 % autonomous resolution of common issues by 2029 with 30 % lower operating cost); Brynjolfsson, Li and Raymond, QJE 2025 (+15 % issues resolved per hour with a GenAI assistant); ContactBabel 2024 (US attrition mean 31 %, median 24 %). Full citations are in `PRD.md` section Sources.
* **Flags**: `customer_input` (replace with the customer's own figure), `sourced`, `assumption`. Entries with `validate: true` must be confirmed with customer data before the case supports a commitment.

## 7. Communications and Azure Communication Services (ACS)

Microsoft Learn's retirement guide (announced 23 Sep 2026) states that **ACS is retired as a standalone offering on 30 Sep 2028**: ACS Direct Routing, Direct Offer numbers, SMS, Email, Chat, Advanced Messaging (WhatsApp) and Job Router are retired; Call Automation, audio streaming and recording remain only for Teams-aligned scenarios (Teams Phone Extensibility), and customers without an ACS resource created before 23 Oct 2026 cannot acquire ACS phone numbers or SMS. Concierge therefore keeps telephony and messaging **pluggable** (SIP trunk to the Azure OpenAI Realtime SIP endpoint, Teams Phone Extensibility, Dynamics 365 Contact Center, partner CPaaS). The communications cost is a real customer cost and is **included in the ROI** (priced at ACS list rates as a proxy), but by default **0 %** of it is counted as Azure ACR (`comms_azure_billed_share = 0`). Set it to `1.0` to model a tenant that already runs on ACS; total cost and NPV do not change, only the ACR classification.

## 8. Extending the model

1. **New benefit category** - add a key to `BENEFITS`, a `gross[...]` formula and a `confidence_*` assumption in `_core`; add its assumptions (with `kind: outcome`) to `assumptions.json`.
2. **New Azure line** - add an `add(family, purpose, name, qty, unit, price, ...)` call in `_azure`, a unit price (with `ref` if it exists in the Retail API) and usage assumptions; run `python refresh_prices.py`, `python model.py`, `python -m unittest test_model -v`.
3. **New seat tier or SKU step** - edit `assumptions.json -> tiers`.
4. **Re-price** - `python refresh_prices.py` reports drift; update the values it lists, rerun the model and tests, and commit `outputs.*` together with the snapshot.
5. **Customer-specific case** - replace every `customer_input` and `validate: true` value, keep the keys, and regenerate.

## 9. Limitations (read before quoting)

* Illustrative and assumption-driven; list prices only (no EA/MCA discount, no reservations or commitment tiers); Azure usage drivers are engineering estimates until replaced by pilot metering (CC-22).
* Benefits are cashable only if capacity released is converted into attrition-based reductions, hiring freezes, redeployment or avoided overflow - that is what the confidence factors and `variable_cost_share` represent.
* The model excludes taxes, FX, Teams Phone and Dynamics 365 licences, carrier PSTN minutes the customer already pays, and Meta (WhatsApp) conversation fees.
