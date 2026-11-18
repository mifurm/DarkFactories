# SwarmAI Contact Center — "Concierge"

An **AI-first contact center** reference implementation for the fictional omnichannel retailer **Contoso Home Retail** (delivery &
installation). Every contact starts with an AI agent swarm that can actually *resolve* — grounded in a knowledge base and able to act
through policy-guarded tools — while humans become the escalation and expertise layer. 100 % of interactions are auto-scored, voice-of-
customer and workforce analytics run on the same data, and an evaluation harness gates every prompt or policy change.

All **24 Release-1 features (CC-01 … CC-24)** are implemented end to end (backend logic, API, UI, tests) and deployed to Azure.
**Live deployment** (Sweden Central, synthetic data, daily AI budget cap): https://ca-concierge-imsov4laqyzgs.delightfuldune-2bc64772.swedencentral.azurecontainerapps.io —
start at *Overview & demo guide*, or open `/widget` (chat), `/call` (voice), `/agent`, `/supervisor`, `/evals`, `/metrics`, `/features`.
Business context and design live next to the code: [`PRD.md`](PRD.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`FEATURES.md`](FEATURES.md)
(status board with evidence) · [`business-case/`](business-case/) · [`deck/`](deck/) · test and deployment evidence in
[`REPORT-TEST-AND-DEPLOYMENT.md`](REPORT-TEST-AND-DEPLOYMENT.md).

> **Real vs simulated.** Real in `azure` mode: Azure OpenAI chat + **Realtime voice** (browser mic → WebSocket relay → `gpt-realtime-2.1-mini`),
> embeddings, Azure AI Speech / Language / Content Safety, Cosmos DB, Blob Storage, App Insights — all via managed identity (no keys).
> **Simulated:** PSTN telephony (**no number, carrier or ACS resource is provisioned**; SIP→Realtime, Teams Phone and ACS Call Automation
> *adapters* are exercised by a simulator), SMS / WhatsApp / e-mail delivery, the CRM/OMS back office (mock + connectors tested against
> mocked HTTP) and all customer data (synthetic).

## What is in the box

| Area | Features | UI route |
|---|---|---|
| Conversational agents | CC-01 chat (REST/SSE/WebSocket, 5 channel adapters) · CC-02 voice (Realtime relay, barge-in, tools, STT→LLM→TTS fallback, telephony adapters) · CC-03 RAG with citations, groundedness, don't-know · CC-04 policy-guarded tools · CC-05 identity (OTP/KBA), consent, disclosure, payment hand-off | `/widget`, `/call`, `/kb`, `/tools`, `/identity` |
| Routing & humans | CC-06 routing + escalation triggers · CC-07 warm handoff with context package · CC-08 Agent Assist · CC-09 auto wrap-up | `/routing`, `/agent` |
| Quality & insight | CC-10 100 % auto-QA · CC-11 compliance & risk guard · CC-12 VoC clustering + emerging-issue alerts · CC-13 CX metrics + **ROI / Azure-ACR calculator** | `/qa`, `/compliance`, `/voc`, `/metrics` |
| Operations & LLMOps | CC-14 forecasting + Erlang-C staffing · CC-15 supervisor console · CC-16 **evaluation harness** (42 scenarios + 44-attack red-team pack, regression gate) · CC-17 rollout manager · CC-18 proactive outreach | `/wfm`, `/supervisor`, `/evals`, `/rollout`, `/outbound` |
| Platform | CC-19 multilingual (47 languages, 8 evaluated) · CC-20 Customer 360 + CRM connectors · CC-21 RBAC · CC-22 observability & FinOps · CC-23 IaC · CC-24 Agent Studio shell + Feature Map | `/i18n`, `/customers`, `/security`, `/observability`, `/deployment`, `/features` |

`GET /api/features` lists every feature as implemented; the SPA **Feature Map** (`/features`) renders it. Both are auto-discovered from
`app/src/concierge/features/*` and `app/web/src/features/*/meta.ts` — adding a feature is adding a folder.

## Architecture in one picture

```
 browser (React/Vite/TS)  ── HTTPS / WebSocket ──►  Azure Container Apps (1 app: FastAPI + SPA + voice relay)
   widget · call · consoles                              │  managed identity (no keys anywhere)
                                                         ├─► Azure OpenAI (AI Services account): gpt-5.4-mini / gpt-5.4 / nano, embeddings,
                                                         │      gpt-realtime-2.1-mini (+ gpt-realtime-mini fallback), transcribe
                                                         ├─► Azure AI Speech · Language · Content Safety (same account, Entra tokens)
                                                         ├─► Cosmos DB for NoSQL (serverless, Entra-only, 34 containers)
                                                         ├─► Blob Storage (Entra-only) · Application Insights / Log Analytics
                                                         └─► ACR (remote build)         Bicep + azd, tags on the RG and every resource
```

* **Agent swarm** — Greeter → Authentication → Knowledge / Resolution → Escalation, one streaming tool-calling loop. The model can only
  *request* tools; allow-lists, authentication levels, refund caps, customer confirmation, idempotency keys and approvals are enforced
  **in code** (`engine/tools.py`). Confirmed plans execute in code with exactly the approved arguments.
* **Guardrails** — PII/PCI redaction before anything is stored, logged or sent to a model; prompt-injection quarantine for user text, KB
  documents and tool results; groundedness check (two-key: hard numeric/absolute evidence, or Azure + deterministic agreement).
* **Voice** — browser mic → AudioWorklet → PCM16 24 kHz → `/ws/voice/{id}` relay → Azure OpenAI Realtime (Entra bearer token), server VAD,
  barge-in, tool calls, live transcripts both ways, turn-latency metrics. `POST /api/voice/text-turn` proves the path without a human.
* **Telephony** — one provider-neutral `TelephonyAdapter` + call state machine with three adapters: SIP→Azure OpenAI Realtime (default
  production path), Teams Phone Extensibility (strategic), ACS Call Automation (legacy; ACS retires as a standalone offering on 30 Sep
  2028). Simulated only; see `ARCHITECTURE.md` §7 and ADR-02.
* **Analytics** — seeded synthetic history (1,981 conversations / 90 days / 8 markets with a planted NordFreight "damaged on delivery"
  spike; 5 queues × 90 days of 30-minute volumes). Forecasting, Erlang-C, k-means VoC and QA scoring are real, tested maths (numpy only).
* **ROI / ACR calculator** — serves the very `model.py` + `assumptions.json` of `business-case/` (vendored, hash-checked, parity-tested
  against `outputs.json` within 0.5 %).

## Run it locally (no Azure needed — deterministic offline mode)

```bash
cd app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
(cd web && npm ci && npm run build)                       # SPA -> web/dist
CONCIERGE_MODE=offline STATIC_DIR=web/dist PYTHONPATH=src \
  .venv/bin/python -m uvicorn concierge.main:create_app --factory --port 8103     # http://127.0.0.1:8103
# hot-reload UI: cd web && npm run dev   (Vite on 5103, proxies /api and /ws to 8103)
```

Offline mode uses an in-memory repository and a deterministic stub "brain", so every journey (including the damaged-sofa story) works with
no network. With `COSMOS_ENDPOINT` + `AZURE_OPENAI_ENDPOINT` set (and `az login` locally) the same code runs in `azure` mode.

**Real models without touching the live data — the hybrid server.** `scripts/dev_hybrid.py` runs the app with the **real** Azure OpenAI / Speech /
Language / Content Safety (Entra token of your `az login` user, no keys) but an **in-memory repository and blob store**, so the deployed demo's
Cosmos DB and Blob data are never read or written; the app's daily AI budget guard is the hard spend cap of the process (`--budget`, default US$2.50):

```bash
cd app && .venv/bin/python ../scripts/dev_hybrid.py --check                   # one tiny probe per AI service (chat, embeddings, Language incl. Polish PII, pl-PL TTS -> STT)
.venv/bin/python ../scripts/dev_hybrid.py &                                    # http://127.0.0.1:8103  (UI + API, real AI, in-memory data)
.venv/bin/python ../scripts/smoke_test.py --base-url http://127.0.0.1:8103 --expect-mode hybrid        # English + Polish steps
.venv/bin/python ../scripts/eval_gate.py --base-url http://127.0.0.1:8103 --suite pl                   # the Polish pack on the real model
```

## Languages (English by default, Polish `pl`)

* **Switching.** The header language switcher (EN | PL) is remembered per browser. The SPA sends `X-UI-Lang` and `Accept-Language` on every call and `?lang=` on
  SSE / WebSocket URLs. The server resolves the **locale** as `?lang=` → `X-UI-Lang` → `Accept-Language` (q-values) → `en` and answers with `Content-Language`;
  `GET /api/meta` lists `languages` (`["en","pl"]`) and `default_language`. English output is byte-identical to before; everything is additive.
* **Two different languages.** The *UI locale* decides the language of operator-facing text (summaries, queue names, QA notes, error `message` / `hint`, reports).
  The *conversation language* (`conversation.language`, set by the widget / voice-page selector, otherwise the request locale) decides what the customer reads and hears:
  disclosure and recording notice, OTP SMS, confirmations, e-mails, outbound messages, voice. Stable machine fields (`code`, `id`, `key`, `status`, enums, tool-result keys)
  never change; persisted records store `code` + `params` (+ the original text) and are rendered at read time.
* **What is Polish.** 50 Polish KB articles (`<id>-pl`, the same business rules; cross-language retrieval both ways), Polish understanding (intent, sentiment, risk flags; with and
  without diacritics, ł/Ł-aware folding), PII for PESEL / NIP / REGON / dowód osobisty / NRB with checksums plus Polish phone formats and spoken digits, Polish Auto-QA with
  real quotes as evidence, compliance guard (risky promises such as „gwarantujemy zwrot 100 %”), 31-scenario evaluation pack (incl. persona-simulated and red-team), Polish voice
  (Realtime `input_audio_transcription.language = "pl"`, pl-PL neural voice in the STT → LLM → TTS fallback), Polish analytics slice (VoC, WFM queues in `Europe/Warsaw` with Polish
  holidays, supervisor), outbound templates with `STOP` / `REZYGNUJĘ` opt-out and quiet hours 21:00–08:00 Warsaw time.
* **Money.** Polish-market orders are in **PLN** (`1 599,00 zł`); the policy caps are defined in EUR and applied to the **EUR equivalent at a fixed demo rate of 1 EUR = 4.30 PLN**
  (`core/money.py`): refund cap EUR 500 = 2 150,00 zł, step-up EUR 400 = 1 720,00 zł, goodwill EUR 50 = 215,00 zł. Not a live FX rate; English orders stay in EUR.
* **Add another language** (the Polish work is the template; every step has a test in `tests/test_pl_*.py` to copy):
  1. `core/i18n.py`: add the code to `SUPPORTED`, `LANGUAGE_NAMES`, `NATIVE_NAMES`; create `core/catalog_<xx>.py` with **every key** of `catalog_en.py` and register it in `CATALOGS`
     (`test_pl_contract` fails on any missing key or placeholder mismatch).
  2. Understanding and safety: `engine/lexicon_<xx>.py` (intents, risks, sentiment), `core/langid.py` profile, `core/redaction.py` national identifiers / phones, `core/textutil.fold`.
  3. Content: `engine/kb_seed_<xx>.py` (articles `<id>-<xx>`), `engine/eval_<xx>.py` + `engine/redteam_<xx>.py`, `engine/synth_<xx>.py` for the analytics slice (bump the slice version in `history_seed.py`).
  4. Voice and text: `VOICES` in `core/ai/azure_cognitive.py`, `LANGUAGE_GUIDES` / `VOICE_GUIDES` / `VOICE_OPENING` in `engine/prompts.py`, `AI_DISCLOSURE` / `GREETING` / `SAFE_REPLACEMENT` in
     `engine/guard.py`, currency in `core/money.py` if it is not EUR/PLN. The web part is described in `app/web/src/i18n/README.md`.

## Tests

```bash
cd app
.venv/bin/ruff check src tests                      # lint
.venv/bin/python -m pytest --cov=concierge          # unit + API + behavioural tests, coverage report
(cd web && npm run build)                           # TypeScript type-check + production build
.venv/bin/python -m pytest tests/e2e -o addopts=""  # Playwright E2E in Chromium (+ axe-core WCAG A/AA scan); starts its own server on 8103
                                                    # E2E_SHOTS_DIR=../deck/assets/screens also saves screenshots
python ../scripts/eval_gate.py                      # CI gate: exit 0 for the active config
python ../scripts/eval_gate.py --broken remove_refund_cap   # exit 1: the gate blocks a deliberately broken prompt/policy
python ../scripts/eval_gate.py --suite pl-gate              # the Polish pack (PLN orders, Polish customers): exit 0
python ../scripts/eval_gate.py --suite pl-gate --broken no_citations   # exit 1: the gate also blocks a broken prompt on the Polish pack
```

The brief's behavioural tests map to: `test_tool_policy` (caps, approvals, idempotency, auth gate, cross-customer), `test_routing`
(≥ 30-case matrix, escalation triggers), `test_privacy_rag` (RAG, groundedness, PII/PCI golden, injection), `test_analytics` (auto-QA
agreement, Erlang-C vs exact arithmetic, forecast MAPE, SLA in simulation, ROI parity), `test_voice` (fake realtime *server*: session.update,
append/commit, deltas, tool round trip, barge-in cancel), `test_telephony` (three adapters × state machine), `test_eval_harness` (≥ 30
scenarios, gate fails on broken prompts, red-team pack), `test_security`, `test_platform`, `test_api_surface`.

The Polish localization adds eight modules (926 tests; the whole backend suite is 1,138): `test_pl_understanding` (371: golden and adversarial utterances with and without diacritics, langid,
routing matrix), `test_pl_guard` (173: injection / social-engineering / human-handoff / profanity patterns with look-alike negatives), `test_pl_pii_money` (143: PESEL / NIP / REGON / dowód / NRB
checksums inside sentences, phones, PLN formats, plural forms, dates, locale resolution), `test_pl_conversation` (PLN back office, caps on the EUR equivalent, idempotency, consent, OTP,
confirmations, wrap-up, handoff, golden journey), `test_pl_knowledge_quality` (KB parity and cross-language retrieval, groundedness, risky promises, Auto-QA, red-team pack, Polish eval pack and its gate),
`test_pl_voice_outbound` (Realtime configured for Polish on the fake realtime server, pl-PL pipeline, opt-out, quiet hours), `test_pl_plain_text` (no internal codes in LLM-written notes) and
`test_pl_contract` (the FE ⇄ BE contract: locale order, SSE / WebSocket `?lang=`, error codes, catalog parity, English output unchanged, seed idempotence incl. the upgrade of already-seeded data);
`test_voice_no_markers` guards voice calls against reading citation markers aloud (found on the live app).

## Deploy to Azure

Prerequisites: Azure CLI + `azd` (≥ 1.36), a subscription where you can create a resource group, quota for the models in
`infra/resources.bicep` (Sweden Central), and `az login`. **No Docker needed** (ACR remote build).

```bash
azd env new swarmai-cc && azd env set AZURE_LOCATION swedencentral
azd env set DAILY_AI_BUDGET_USD 5                       # AI budget guard (fails closed)
azd provision --no-prompt                               # RG + all resources (≈ 12 min: model deployments are created sequentially)
azd deploy --no-prompt                                  # remote build in ACR + new Container Apps revision (≈ 2–3 min)
# azd up = both. Re-running either is idempotent.
```

Everything is created in `rg-swarmai-contactcenter` with the governance tags `SecurityControl=Ignore`,
`SecurityExemption=StorageAccountKeyAccess`, `project=SwarmAI`, `concept=contactcenter`, `owner=michalfu`, `environment=demo` on the resource
group **and every taggable resource** (one `commonTags` object in `infra/main.bicep`). Cosmos DB, the AI Services account and Storage have
local/key authentication disabled; the Container App uses a user-assigned managed identity with least-privilege data-plane roles (the
signed-in user gets the same roles for local development). The storage shared-key *exemption* tag exists for the sandbox policy but is not used.

Teardown: `azd down --purge --force` (removes the resource group and purges the soft-deleted AI Services account).

## Verify a deployment

```bash
python scripts/smoke_test.py --base-url https://<app>.<region>.azurecontainerapps.io      # PASS/FAIL table (English + Polish PL-* steps), < 1 USD of AI spend in total
python scripts/smoke_test.py --base-url https://<app>... --lang pl                        # only the Polish PL-* steps (--lang en = the English / German checks as before)
python scripts/load_check.py --base-url https://<app>...                                  # p50/p95 latency, chat TTFT, voice first audio
python scripts/capture_screens.py --base-url https://<app>...                             # 1600x900 product-tour screenshots -> deck/assets/screens
```

The smoke test covers health/readiness (real Cosmos + Azure OpenAI), SPA and security headers, RBAC, the damaged-sofa journey with a **real
refund tool call**, auto-QA, RAG (cite + don't-know), warm handoff, red-team probes, a live eval subset, the **Realtime voice path with text
input**, the three telephony simulations, VoC alert, WFM plan, ROI parity and the AI budget guard. The Polish steps (`PL-1` … `PL-10`) repeat the
important ones in Polish: locale contract, Polish content on the data store, a damaged-sofa chat with a confirmed **refund in PLN** through real tool calls, wrap-up and
QA evidence, Polish RAG with citation and "nie wiem", the legal-threat warm handoff, Polish prompt-injection / social-engineering probes, a Polish evaluation
subset (≥ 90 %) and the Polish Realtime voice path.

## Configuration (environment)

| Variable | Meaning | Default |
|---|---|---|
| `CONCIERGE_MODE` | `azure` \| `offline` \| `auto` (azure when Cosmos + OpenAI endpoints are set) | `auto` |
| `COSMOS_ENDPOINT`, `COSMOS_DATABASE` | Cosmos DB account (Entra auth) | — / `concierge` |
| `AZURE_OPENAI_ENDPOINT`, `AI_SERVICES_ENDPOINT` | AI Services account (OpenAI + Speech/Language/Content Safety) | — |
| `AOAI_DEPLOYMENT_{CHAT,REASONING,NANO,REALTIME,REALTIME_FALLBACK,EMBED,TRANSCRIBE}` | deployment names | see `core/config.py` |
| `AI_DAILY_BUDGET_USD` | daily AI spend cap (metered, fails closed with a UI message) | `5` |
| `AUTH_MODE`, `ENTRA_TENANT_ID`, `ENTRA_AUDIENCE` | `demo` (role switcher, clearly labelled) or `entra` (JWT validation; the switcher is inert) | `demo` |
| `SEED_ON_START` | idempotent seed of back office, KB, history | `1` |

## Repository layout

```
app/src/concierge/{core,engine,features}   backend: infrastructure, domain engines, one package per feature (router + seed + startup)
app/web/src/{lib,features}                 React/Vite/TS shell, UI kit, one folder per feature (meta.ts is auto-discovered)
app/tests (+ e2e)                          pytest suites and Playwright journeys        scripts/   smoke, load, gate, screenshots, diagnostics
infra/                                     Bicep (subscription scope) + azd              business-case/  model.py, assumptions, outputs (docs)
```

## Known limitations

Single replica (in-process event bus / rate limits; scale-out path in `ARCHITECTURE.md` §12/§14); retrieval is an in-process hybrid index
persisted in Cosmos DB (Azure AI Search is the target); Realtime quota in the sandbox allows ~1–2 concurrent calls; PSTN, SMS/WhatsApp/e-mail
providers and a real CRM are intentionally out of scope; the demo role switcher is for demonstration only (use `AUTH_MODE=entra` for real access control).
Polish: the FX rate between EUR and PLN is a fixed demo constant, not a market rate; static descriptive API texts (identity levels, metric definitions, SLO notes,
tool descriptions) stay English in the API and are translated by the web dictionary; Polish voice quality depends on `gpt-realtime-2.1-mini` (the relay verifies the spoken AI
disclosure and repeats it once if the model skipped it; formal register and Polish filler phrases are enforced through the call instructions, not guaranteed by the model).
