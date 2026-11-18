# SwarmAI Dark Factory — "Nightshift" (reference implementation)

Lights-out manufacturing run by an Azure-native **swarm of AI agents**, with humans *on* the loop. This folder contains the working,
tested, Azure-deployed reference implementation of every Release-1 feature (**DF-01 … DF-25**) plus the product documents.

| | |
|---|---|
| **Live demo** | <https://ca-nightshift.blackforest-a28408f9.swedencentral.azurecontainerapps.io> (Azure Container Apps, swedencentral) |
| **API docs** | `<live url>/docs` (OpenAPI), health `/healthz`, readiness `/readyz` (real Cosmos DB + Blob + Azure OpenAI round trips) |
| **Status** | 25/25 features implemented, deployed and exercised by the post-deploy smoke test — see [REPORT-TEST-AND-DEPLOYMENT.md](REPORT-TEST-AND-DEPLOYMENT.md) |
| **Documents** | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [FEATURES.md](FEATURES.md) (status board with test evidence) · [business-case/](business-case/README.md) · [deck/](deck/README.md) |

> **Everything you see is synthetic.** The plant (*Contoso Precision Components – KAT-1*, plus GDN-2 and MTY-3), its machines, sensors, orders, tariffs
> and faults come from a seeded simulator. No real factory, PLC or personal data is connected. Real: the software, the Azure services, the
> agents' algorithms, the policy engine, the hash-chained ledger and the Azure OpenAI calls. Simulated: the physics of the plant
> (a calibrated stochastic model, assumptions in `app/src/nightshift/sim/assumptions.yaml`) and the OT/IT connectors (see [Real vs simulated](#real-vs-simulated)).

## What it does

A seeded, deterministic plant simulator runs in the background of the server. Seven specialist agents (Safety, Predictive Maintenance, Quality,
Planner, Materials, Energy, Process-optimiser pilot) observe it through a UNS-style telemetry model, propose actions, and a **Shift Supervisor**
arbitrates conflicts, lets Safety veto, rehearses every plan on a **fork of the digital twin** ("sim-first") and hands it to a **policy engine**
(the *Autonomy Dial* L0–L5, kill switch, break-glass). What the policy does not auto-execute lands in the **approvals inbox** (SLA, escalation,
Teams Adaptive Card). Every proposal, decision, action, veto and outcome goes into a **SHA-256 hash-chained decision ledger**. Azure OpenAI narrates
and explains (shift reports, "Ask the Factory" copilot with tool calling, root-cause narration, vision inspection) — each with a deterministic
fallback, so the product keeps working if the model is unreachable or the daily AI budget is spent.

**Evidence of value:** the *Value realization* page replays the same plant (same seeds, same fault schedule) with the swarm OFF vs ON and reports paired
differences with 95 % confidence intervals, and an ROI / Azure-consumed-revenue calculator (the business-case model **v1.1.0**, vendored byte-for-byte) that
can be seeded with that measurement. The calculator renders all ~350 overridable inputs (287 drivers + 60 Azure unit prices) from the model's own assumption
file, switches the five expansion levers (E1–E5) on and off with a master toggle, and shows ACR by service family *and* by lever (Year 1–3 + run-rate), the
25-plant and (illustrative) 100-plant fleet tiers, and the Base-vs-levers-on comparison.

## Quick start (local, no Azure needed)

```bash
cd app
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
(cd web && npm ci && npm run build) && mkdir -p src/nightshift/static && cp -R web/dist/* src/nightshift/static/
NIGHTSHIFT_MODE=offline PYTHONPATH=src .venv/bin/python -m uvicorn nightshift.main:app --port 8101   # http://127.0.0.1:8101
# UI hot reload instead:  (cd web && npm run dev)   -> http://127.0.0.1:5101 (proxies /api to 8101)
```

Offline mode uses an in-memory repository and a deterministic LLM stub; every feature works. To use real Azure services locally (after `az login`, with the
data-plane roles Bicep grants the deploying user) set `NIGHTSHIFT_MODE=azure` plus `COSMOS_ENDPOINT`, `STORAGE_ACCOUNT_URL`, `AZURE_OPENAI_ENDPOINT`
(values: `azd env get-values`). No keys or connection strings exist anywhere — only Entra tokens (managed identity / `az login`).

### Five-minute demo script (live site or local)

1. **Control Tower** (`/`): plant map, KPIs, live agent feed over SSE. Speed up the clock (top right, e.g. *30 sim-min/s*).
2. **Fault console** → *Bearing wear* on CNC-04 → *Inject*. Watch Maintenance detect the drift, Materials stage a spare, the Supervisor rehearse the plan
   on the twin, the policy auto-approve it, and the asset go into a planned stop — with no breakdown.
3. **Policy** (`/policy`): set *maintenance.schedule* to **L2**, inject again → the plan waits in **Inbox**; try approving as *Operator* (403), then as *Plant Manager*.
4. **Ledger** (`/ledger`): every step, the counterfactual, the chain head — *verify* shows the hash chain is intact.
5. **Twin** (`/twin`): ask "what if" for any action sequence; **Copilot** (`/copilot`): "Which assets look unhealthy and what is being done about them?"
6. **Value** (`/value`): the A/B replay (16 seeds) with confidence intervals, then the **ROI / ACR calculator** seeded from it. Or hit the **kill switch** on the tower.

## Repository layout

```
app/                    the product (single deployable container)
  src/nightshift/       FastAPI app; feature-sliced: features/dfNN_<name>/{router.py,<logic>.py,__init__.py (FEATURE spec)} auto-discovered
    core/               config, registry (auto-discovery), repo (Cosmos | memory), llm (Azure | stub), usage meter + budget guard, http middleware, obs
    sim/                the plant simulator (deterministic, per-asset RNG streams, faults, snapshot/restore) + assumptions.yaml
    plant/              PlantCore (sim + agents + supervisor + policy + ledger + inbox), PlantRuntime (live loop, SSE), Fleet
    features/           25 feature packages (DF-01 … DF-25)
  web/                  React + Vite + TypeScript SPA; src/features/<name>/index.tsx auto-discovered with import.meta.glob
  tests/                pytest: unit + API + behavioural (the brief's behavioural tests live in test_behaviour.py)
  Dockerfile            multi-stage (node → python:3.13-slim, non-root)
infra/                  Bicep (subscription scope): RG with governance tags, monitoring, identity, data (Cosmos, Storage), AIServices + models, ACA
azure.yaml              azd project (remote ACR build)
scripts/                smoke_test.py (post-deploy, real Azure), load_check.py, e2e_journeys.py (Playwright), e2e_crawl.py, dev helpers
deck/assets/screens/    1600×900 screenshots captured by e2e_journeys.py against the live deployment
```

## Feature → where it lives

| ID | Feature | UI route | API prefix | ID | Feature | UI route | API prefix |
|---|---|---|---|---|---|---|---|
| DF-01 | Factory simulator | `/simulator` | `/api/sim` | DF-14 | Decision ledger | `/ledger` | `/api/ledger` |
| DF-02 | Telemetry & UNS | `/telemetry` | `/api/telemetry` | DF-15 | Readiness assessment | `/readiness` | `/api/readiness` |
| DF-03 | Digital twin & what-if | `/twin` | `/api/twin` | DF-16 | "Ask the Factory" copilot | `/copilot` | `/api/copilot` |
| DF-04 | Swarm runtime & supervisor | `/swarm` | `/api/swarm` | DF-17 | Shift handover report | `/handover` | `/api/handover` |
| DF-05 | Predictive maintenance | `/maintenance` | `/api/maintenance` | DF-18 | Root-cause analysis | `/rca` | `/api/rca` |
| DF-06 | Quality & vision | `/quality` | `/api/quality` | DF-19 | KPIs & business impact | `/kpis` | `/api/kpi` |
| DF-07 | Production planner | `/planner` | `/api/planner` | DF-20 | Control tower | `/` | `/api/tower`, `/api/stream/plant` |
| DF-08 | Materials & logistics | `/materials` | `/api/materials` | DF-21 | Value realization (A/B + ROI/ACR) | `/value` | `/api/value` |
| DF-09 | Energy & sustainability | `/energy` | `/api/energy` | DF-22 | Fleet | `/fleet` | `/api/fleet` |
| DF-10 | Safety & cybersecurity | `/safety` | `/api/safety` | DF-23 | RBAC / Entra-ready auth | `/access` | `/api/access` |
| DF-11 | Process optimiser (pilot) | `/process` | `/api/process` | DF-24 | Observability & FinOps | `/observability` | `/api/observability` |
| DF-12 | Autonomy dial & policy | `/policy` | `/api/policy` | DF-25 | IaC & deployment | `/deployment` | `/api/deployment` |
| DF-13 | Approvals inbox | `/inbox` | `/api/inbox` | | Feature map (auto-generated) | `/features` | `/api/features` |

Adding a feature = adding a folder under `features/` (backend) and one under `web/src/features/` (UI); both are auto-discovered.

## Run the tests

```bash
cd app
.venv/bin/python -m pytest tests --cov                     # 106 tests; coverage config in pyproject.toml (domain logic ≥ 80 %)
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
(cd web && npm run build && npm test)                      # tsc typecheck + vite build + vitest
# end-to-end in a real browser (Playwright; any Python with `playwright install chromium` done)
python scripts/e2e_journeys.py --base-url http://127.0.0.1:8101 --screens deck/assets/screens
# post-deploy checks against a RUNNING instance (real Azure OpenAI / Cosmos / Blob when mode=azure)
python scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io          # --offline to skip Azure-only checks
python scripts/load_check.py --base-url https://<app>.azurecontainerapps.io --requests 200 --concurrency 20
```

The behavioural tests from the brief (`app/tests/test_behaviour.py`): bearing-wear alert lead time and breakdown avoided with a valid hash chain, ledger tamper
detection, Safety veto beats the Planner, kill switch halts every autonomous action (but not the protective stop), L0–L5 matrices, forbidden setpoints
rejected everywhere, A/B over 16 seeds with confidence intervals excluding 0, planner re-plan beats FIFO after a breakdown with a feasible schedule, energy
shifting without due-date violations, vision stub agreement, ROI/ACR calculator reproducing the **whole** `business-case/outputs.json` (Conservative/Base/Upside)
within 0.5 % plus a check that the vendored trio is byte-identical to `business-case/`.

## Deploy to Azure (and tear down)

Prerequisites: `az login` (never switch accounts implicitly), `azd`, subscription `1217c203-6c76-47b4-b61c-9bba62dc8e02`.

```bash
azd env new nightshift && azd env set AZURE_SUBSCRIPTION_ID 1217c203-6c76-47b4-b61c-9bba62dc8e02
azd env set AZURE_LOCATION swedencentral && azd env set AZURE_PRINCIPAL_ID "$(az ad signed-in-user show --query id -o tsv)"
azd up --no-prompt            # provision (Bicep) + remote ACR build + deploy; idempotent — re-run any time
azd provision --no-prompt && azd deploy --no-prompt   # the same, in two steps
azd down --purge --force      # teardown (or: az group delete -n rg-swarmai-darkfactory --yes)
```

Resources (all tagged `SecurityControl=Ignore`, `SecurityExemption=StorageAccountKeyAccess`, `project=SwarmAI`, `concept=darkfactory`, `owner=michalfu`,
`environment=demo` via one `commonTags` object): resource group, user-assigned managed identity, Log Analytics (1 GB/day cap) + workspace-based Application Insights,
ACR (Basic), Storage (shared-key **disabled**, Entra only), Cosmos DB serverless (local auth **disabled**, data-plane RBAC), Azure AI Services account with `chat`
(gpt-5.4-mini) and `reasoning` (gpt-5.4) GlobalStandard deployments (local auth **disabled**), Container Apps environment + app (1 vCPU / 2 GiB, **1 replica**).
Optional Bicep switch `enableEntraAuth` puts Container Apps built-in Entra authentication in front of the app.

**Why one replica:** the live simulation is in-process state. To scale out, partition plants across replicas (one `PLANTS=KAT-1` per revision, SSE sticky by plant)
— see ARCHITECTURE.md. Estimated idle cost and the cost model are in the REPORT.

## Configuration (environment)

`NIGHTSHIFT_MODE` (`azure`|`offline`), `AZURE_CLIENT_ID`, `COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `STORAGE_ACCOUNT_URL`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT`,
`AZURE_OPENAI_REASONING_DEPLOYMENT`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `AI_DAILY_BUDGET_USD` (default 5; fails closed → deterministic fallbacks), `SIM_SPEED`
(simulated minutes per real second, default 1), `SIM_AUTOSTART`, `APPROVAL_CLOCK_FACTOR` (live approval SLAs run N× faster than wall-clock so escalation/expiry are visible in a
demo; 0 = simulated time), `NIGHTSHIFT_SEED`, `PLANTS`, `TEAMS_WEBHOOK_URL` (optional; HTTPS, allow-listed hosts), `DEMO_ROLE_SWITCH`, `DEFAULT_ROLE`, `ENTRA_TENANT_ID` + `ENTRA_AUDIENCE`
(enable JWT validation), `RATE_LIMIT_*`, `MAX_BODY_BYTES`, `LLM_NARRATION`.

## Security notes

Managed identity + RBAC only (no keys, connection strings or secrets in code, env or IaC outputs); Cosmos and AI Services local auth disabled; Storage shared-key access disabled;
TLS 1.2+; non-root container; strict CSP and security headers; per-IP and global rate limits (tighter for AI endpoints), body-size limit, daily AI budget guard;
server-side RBAC (5 roles, audited, Entra JWT validation implemented and tested with a local signing key); all agent actions pass through the safety veto, forbidden-setpoint
guards and the policy engine in code (tests prove it); copilot tools are read-only except a *proposal* that goes through the same pipeline; model output is treated as data
(rendered as text, never as HTML); webhook URLs are allow-listed. The governance tags allow shared-key Storage access if a service ever needs it — this deployment does not.

## Real vs simulated

| Real | Simulated (behind the same interfaces a production integration would use) |
|---|---|
| FastAPI app, agents' algorithms (EWMA/isolation-forest drift + RUL, SPC with Western-Electric rules, finite-capacity scheduling, ToU load shifting, policy engine), twin forking, hash-chained ledger, approvals, RBAC/JWT, rate limits, budget guard | The plant physics, sensors, orders, tariffs/carbon curves, faults and the human response times |
| Azure Container Apps, Cosmos DB, Blob, Azure AI Services (gpt-5.4-mini / gpt-5.4), App Insights, ACR, managed identity, Bicep/azd | OPC UA / MQTT / Event Hubs brokers (decoders implemented and tested; no broker connected), PLC/MES/ERP writes (the control API is the simulator), Teams webhook (Adaptive Card generated; posted only when a webhook is configured) |
| Vision inspection by the Azure model on generated part images | The images are synthetic discs with injected defects; the cyber-posture checklist is simulated |

Honest limits of the value evidence: the A/B replay measures a *synthetic* plant under an *assumed* fault load (8 disruptions per 8 h); it is an illustration of mechanism and
variance, not a forecast. Absolute energy cost is reported alongside effective price and cost per unit — the swarm keeps the plant busier, so absolute cost can rise.
