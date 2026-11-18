# Test and deployment report — SwarmAI Contact Center ("Concierge")

Reference implementation for the fictional **Contoso Home Retail**. All 24 Release-1 features (CC-01 … CC-24) are implemented (backend, API, UI, tests) and deployed to Azure.
Everything below was measured on 17–18 Nov 2026; numbers marked *(estimate)* are calculated, everything else was read back from the system.

| | |
|---|---|
| **Live URL** | https://ca-concierge-imsov4laqyzgs.delightfuldune-2bc64772.swedencentral.azurecontainerapps.io |
| API docs / health | `/docs` · `/healthz` · `/readyz` · `/api/meta` · `/api/features` · `/api/usage` |
| Resource group / region | `rg-swarmai-contactcenter` · `swedencentral` (azd environment `swarmai-cc`) |
| Final build | `20261118-013951` = `20261118-010642` (the build that the smoke test, load check and eval run below used) plus one UI fix (eval chart); the Python code is identical |
| Mode | `azure` — real Cosmos DB, Azure OpenAI (chat + Realtime), Speech, Language, Content Safety; managed identity only |

## 1. Result at a glance

| Definition-of-done item | Result |
|---|---|
| Every CC-01 … CC-24 implemented, listed by `/api/features`, shown on the Feature Map | **24 / 24** (`FEATURES.md` status board: all *Deployed ✔* with evidence) |
| Unit + API + behavioural tests | **212 passed** (≈ 24 s) |
| Browser E2E (Playwright, Chromium, incl. axe-core WCAG A/AA scan of 14 routes) | **27 passed** (≈ 35 s) |
| Line coverage of domain logic | **85 %** (10,290 statements; Azure SDK adapters, Cosmos repo, telemetry and the vendored business case are excluded — they are exercised live by the smoke test) |
| `ruff check` · `npm run build` (TypeScript type-check) | clean · clean |
| Live smoke test against the deployed app | **21 / 21 PASS** (§5), including a real refund tool call and the Realtime voice path |
| Live evaluation harness (42 scenarios, real `gpt-5.4-mini`) | **42 / 42** on the final build (resolution / accuracy / policy / safety all 1.00); run-to-run variation of the model: 40–42 / 42 (§6) |
| Chat latency (12 turns, 6 concurrent) | turn p50 / p95 **1.6 / 1.9 s**, time-to-first-token p50 / p95 **1.3 / 1.6 s** |
| Realtime voice (text input → audio + transcript) | first audio **0.34 s** (smoke) / p50 **1.1 s**, p95 1.8 s (load check, 3 calls) with `gpt-realtime-2.1-mini` |
| Idempotent re-deployment (`azd provision` + `azd deploy`) | repeated, no drift (§8) |
| Governance tags on the RG and **all 14 resources**; no setting changed by governance | verified (§3) |
| Estimated idle cost | **≈ US$28 / month** (§10) |
| PSTN telephony | **not provisioned** — simulated (§9) |

## 2. What was deployed (all keyless; one resource group)

| Resource | Name | Notes |
|---|---|---|
| Container App (API + SPA + voice relay) | `ca-concierge-imsov4laqyzgs` | 1 vCPU / 2 GiB, **min = max = 1 replica**, external HTTPS ingress, `transport: auto` (WebSocket-capable), user-assigned identity |
| Container Apps environment | `cae-cc-imsov4laqyzgs` | Consumption, logs to Log Analytics |
| Container Registry | `acrccimsov4laqyzgs` | Basic, admin user **disabled**, remote build (no local Docker) |
| Managed identity | `id-cc-imsov4laqyzgs` | AcrPull, Storage Blob Data Contributor, Cognitive Services OpenAI User / User / Speech User, Monitoring Metrics Publisher, Cosmos DB Built-in Data Contributor (data plane) |
| Cosmos DB for NoSQL | `cosmos-cc-imsov4laqyzgs` | **serverless**, Session consistency, one region, **local (key) auth disabled**, database `concierge` with **34 containers** |
| Azure AI Services (Foundry) | `ais-cc-imsov4laqyzgs` | S0, **local auth disabled**; one account serves OpenAI, Speech, Language, Content Safety |
| Model deployments (GlobalStandard) | `gpt-5.4-mini` (400), `gpt-5.4` (30), `gpt-5.4-nano` (100), `text-embedding-3-small` (50), `gpt-realtime-2.1-mini` (10), `gpt-realtime-mini` (10, fallback), `gpt-4o-mini-transcribe` (50) | capacity in K tokens/min; realtime quota in this subscription is small (≈ 1–2 concurrent calls) |
| Storage | `stccimsov4laqyzgs` | Standard_LRS, **shared-key access disabled**, no public blob access, TLS 1.2, containers `recordings`, `kb-sources`, `exports` |
| Log Analytics / Application Insights | `law-cc-…` / `appi-cc-…` | PerGB2018, 30-day retention, 1 GB/day cap; workspace-based |
| Auto-created by Azure (not in Bicep) | 3 alert rules, 1 smart-detector rule, 1 Event Grid system topic | tagged after the fact with `az tag update --operation merge` |

Human sign-in user additionally holds the same data-plane roles (+ AcrPush) for local development. Data-plane access everywhere is Entra only.

## 3. Governance tags and settings (verification requested in the tag-change instruction)

```text
$ az group show -n rg-swarmai-contactcenter --query tags
{ "SecurityControl": "Ignore", "SecurityExemption": "StorageAccountKeyAccess", "azd-env-name": "swarmai-cc",
  "concept": "contactcenter", "environment": "demo", "owner": "michalfu", "project": "SwarmAI" }

$ az resource list -g rg-swarmai-contactcenter --query "[?tags.SecurityControl!='Ignore' || tags.SecurityExemption!='StorageAccountKeyAccess'].name"
[]                                   # all 14 resources carry both governance tags (and project/concept/owner/environment)
```

* One `commonTags` object in `infra/main.bicep` is passed to every module and resource; a unit test (`test_platform`) fails if a taggable resource lacks it.
* **Nothing was modified or disabled by governance**: read-back after deployment — Storage `allowSharedKeyAccess=false`, `allowBlobPublicAccess=false`, `minimumTlsVersion=TLS1_2`; Cosmos `disableLocalAuth=true`, `EnableServerless`; AI Services `disableLocalAuth=true`; ACR `adminUserEnabled=false`; Container App ingress `allowInsecure=false`. Public network access is intentionally *Enabled* (demo; private endpoints are the production pattern).
* Why the exemption tag exists but is **not used**: the `StorageAccountKeyAccess` exemption would permit shared keys on Storage, yet nothing in the app needs them — Blob access uses Entra tokens, so the key stays disabled. No other service needed a key.

## 4. Test evidence

| Suite | Tests | Covers (brief's behavioural tests in **bold**) |
|---|---|---|
| `test_tool_policy` | 14 | **refund caps/approvals**, **idempotent retries (concurrent)**, **authentication gate**, **cross-customer access**, allow-lists in code, confirmation before state change, customer (not model) chooses replacement vs refund |
| `test_routing` | 41 | **routing matrix (≥ 30 cases)**, escalation triggers fire once, AI stops answering after handoff |
| `test_privacy_rag` | 36 | **PII/PCI golden set**, **prompt-injection quarantine (user text, KB documents, tool results)**, **RAG: cite / don't-know / fabricated answers**, groundedness (dates, times, derived numbers, empathy lines) |
| `test_analytics` | 29 | **auto-QA agreement with human scores**, Erlang-C vs exact arithmetic, forecast backtest (MAPE) and SLA in simulation, VoC clustering + planted-spike alert + no-spike control, metrics reconcile, **ROI parity ≤ 0.5 % vs `business-case/outputs.json`**, vendored-source drift check |
| `test_eval_harness` | 10 | **≥ 30 scenarios**, scoring dimensions, **gate FAILS for four deliberately broken prompts/policies**, **red-team pack (44 attacks)** incl. "gullible model" stress mode |
| `test_voice` | 6 | **fake Realtime server**: `session.update`, append/commit via server VAD, tool-call round trip, **barge-in** (cancel + truncate), STT→LLM→TTS fallback |
| `test_telephony` | 17 | provider-neutral call state machine × 3 adapters (SIP→Realtime, Teams Phone, ACS legacy), duplicate/late events, consent timeouts |
| `test_security` | 23 | JWT validation with local RSA keys, algorithm confusion, **role matrix**, Entra mode ignores the demo header, security headers, rate limits, tamper-evident audit chain |
| `test_platform` | 22 | Bicep ↔ collections, governance tags / keyless settings in IaC, repository contract, CRM connector contract, outbound consent / quiet hours by time zone, settings, feature auto-discovery |
| `test_api_surface` | 12 | every GET endpoint plus the feature journeys |
| `test_flow_damaged_sofa` | 2 | GJ-1 end to end (DE): auth → RAG → tools → confirmation → wrap-up → QA; model forgets `issue_refund` → platform requests it |
| `tests/e2e` (Playwright) | 27 | widget chat, call page, agent console with handoff, supervisor, QA, VoC, WFM, eval harness, KB admin, metrics + ROI, feature map, axe-core WCAG A/AA on 14 routes |

CI gate demonstration: `python scripts/eval_gate.py` exits 0 for the active configuration; `--broken remove_refund_cap` exits **1** (the harness blocks the promotion).

Bugs that tests found in my own code (fixed): JWKS re-fetched although injected; auditors/QA could start paid eval runs (new permissions `evals.run`, `voc.write`, `compliance.run`); a call state machine could be revived by a late event; a phone-number regex missed `(030) 123 456 78`; React effects returned a Promise (`destroy_ is not a function`); AA contrast failures.

## 5. Live smoke test — `python scripts/smoke_test.py --base-url <live> --expect-mode azure` (final deployment)

Run on the final state: build `20261118-013951`, after the last `azd provision` / `azd deploy`, budget cap $8 (the first requests after the revision restart are slower: connections are cold). An identical run before the final re-provision (build `20261118-010642`) was also 21 / 21 (first audio 345 ms, auto-QA 93/100).

| # | Check | Result | Time | Evidence |
|---|---|---|---|---|
| 1 | `GET /healthz` | PASS | 1.2 s | cold start after the new revision |
| 2 | `GET /readyz?fresh=1` (Cosmos, Storage, Azure OpenAI, AI services) | PASS | 1.8 s | `mode=azure`; cosmos 84 ms, storage 1,734 ms, openai 1,746 ms, cognitive 1,253 ms (cold connections; 64 / 335 / 557 / 27 ms warm) |
| 3 | `GET /api/meta` | PASS | 70 ms | mode azure, build `20261118-013951`, swedencentral, 24 features |
| 4 | `GET /api/features` lists CC-01…CC-24 as implemented | PASS | 70 ms | 24/24 |
| 5 | SPA, deep links, security headers | PASS | 511 ms | |
| 6 | Daily AI budget guard is active | PASS | 66 ms | `$5.87 / $8 (ok)` |
| 7 | RBAC: customer/agent denied, supervisor allowed | PASS | 460 ms | |
| 8 | Reset demo orders (repeatable journeys) | PASS | 3.8 s | |
| 9 | **GJ-1 chat (German): OTP → KB citation → confirmed refund through real tool calls** | PASS | 56.2 s | 7 turns (cold model path); `check_return_eligibility`, `get_available_slots`, `initiate_return`, **`issue_refund`** … |
| 10 | Conversation resolves; wrap-up and 100 % auto-QA with evidence | PASS | 10.8 s | resolved; auto-QA 95/100; `RESOLVED_REFUND_ISSUED` |
| 11 | RAG: cited answer; unanswerable question → don't know | PASS | 3.0 s | cited `returns-001` |
| 12 | Warm handoff: legal threat → escalations queue, context package, agent accepts, Agent Assist | PASS | 3.9 s | accepted by AG-08 |
| 13 | Red team: injection + social engineering → no forbidden tool call | PASS | 5.2 s | |
| 14 | Evaluation harness, live scenario subset | PASS | 33.4 s | 5/5; safety 1.0, policy 1.0; $0.046 |
| 15 | **Realtime voice path: text in → audio + transcript out** (via the server-side relay, Entra bearer token) | PASS | 7.9 s | `gpt-realtime-2.1-mini`, first audio **339 ms**, 44 s of audio |
| 16 | Telephony adapters: 3 simulated providers drive one state machine | PASS | 8.7 s | SIP/Realtime, Teams Phone, ACS (legacy); PSTN not provisioned |
| 17 | VoC: clustering + emerging-issue alert; no-spike control | PASS | 68.4 s | 1,981 records, 12 clusters, purity 0.92, *critical* alert "Damaged item on arrival" 7.7× (NordFreight) — the time is a real recompute (embeddings + model labels) |
| 18 | WFM: forecast backtest + Erlang-C staffing meets SLA in simulation | PASS | 0.5 s | SL 89 % ≥ 80 %; daily MAPE 5.9 %, 22.7 % better than seasonal-naive |
| 19 | ROI / ACR calculator reproduces `outputs.json` within 0.5 % | PASS | 1.3 s | NPV $27,145,851 · ROI 216 % · Y3 ACR $2,979,673 |
| 20 | CX metrics reconcile; SLOs and per-interaction metering | PASS | 1.8 s | 1,981 contacts, containment 61.4 %, metering 100 % complete, 4 SLOs |
| 21 | AI spend of the smoke run < $1 | PASS | | $0.154 |

**21 / 21 passed.** Raw output: `scripts/results/smoke-live.json`.

## 6. Live evaluation harness (CC-16) — real model, 42 scenarios

Final build: **42 / 42**, dimensions resolution 1.00 · accuracy 1.00 · policy 1.00 · safety 1.00, 84 s, $0.59, average turn 1.8 s (`scripts/results/eval-live-core.json`).
The model is not deterministic: the last seven live runs (builds 14–21) scored 39, 40, 42, 40, 41, 40 and **42** / 42 (mean 40.6 = 96.6 %). Policy and safety were 1.00 in every run since build 19; the gate threshold (≥ 0.90 pass rate, policy 1.00) is met by the final run.

**Regression gate on the real model** (screenshot `07b-eval-harness-ci-gate.png`): injecting the deliberately broken configuration *"refund cap removed + 'always promise refunds'"* and running the gate in the live app produced **`FAILED — promotion blocked`** — policy 0.98 < 1.00 and two scenarios regressed against the baseline (S01 "answer cites the knowledge base", S03 "refund cap / approval requested"), pass rate 91 %. The offline harness blocks all four broken variants in the unit tests; `scripts/eval_gate.py --broken remove_refund_cap` exits 1.

Live runs were used to find defects the offline stub can never show — each fixed in code and covered by a regression test:

| Live symptom | Root cause | Fix |
|---|---|---|
| 26 → 38 / 42 on the first runs | model forgot / altered OTP verification and confirmed steps | platform executes OTP verification and customer-confirmed plans itself, with the exact approved arguments |
| correct answers replaced by "I can't confirm that" | groundedness: Azure Content Safety false positives in English; empathy sentences; German dates `19.11.2026` parsed as the decimal 19.11; derived facts ("4-hour windows"); a number from an earlier tool result | two-key verdict (hard evidence, or Azure **and** the local check on the **same sentence**); courtesy sentences exempt; dates/times compared as dates/times; window lengths and all earlier tool results count as sources |
| refund announced, never executed | model skipped `issue_refund` after the pickup | platform requests the refund itself (`agent.refund_step_enforced` in the audit trail); customer confirmation, cap and approval rules still apply |
| model started a replacement the customer did not ask for | decision left to the model | policy in code: for damaged goods the customer's choice is required (`customer_choice_required` / `choice_mismatch`) |
| Spanish customer saw an English fallback | fallback texts existed only in EN/DE | localized for the 8 evaluated languages |
| English text classified as Polish | tiny stop-word list | detector rebuilt (100 % on the 64-phrase evaluation set) |

## 7. Load check and AI spend

`python scripts/load_check.py --base-url <live> --reads 200 --chat 12 --voice 3 --concurrency 6` (from a laptop over the internet; `scripts/results/load-live.json`):

| Measure | n | p50 | p95 | max |
|---|---|---|---|---|
| Read API (mixed GETs, 6 concurrent), 0 errors, 14 req/s | 200 | 246 ms | 1,118 ms | 1,305 ms |
| Chat turn (tool loop + guard + groundedness) | 12 | 1.63 s | 1.86 s | 2.60 s |
| **Chat time-to-first-token** (streamed) | 12 | **1.27 s** | **1.64 s** | 1.97 s |
| Voice: first audio after a typed turn (Realtime) | 3 | 1.13 s | 1.82 s | 1.82 s |
| Voice: complete turn | 3 | 8.6 s | 9.7 s | 9.7 s |

Observability SLO page (CC-22): chat TTFT target p95 ≤ 2.5 s is *burning* because turns with tool calls show the first visible token after the tool loop (p95 6.4 s across all eval/smoke traffic, 53 samples; a turn without tool calls showed 0.66 s in the single sample taken). This is reported as measured, not tuned away.

**AI spend** (in-app meter at list prices, *(estimate)* of the invoice): 18 Nov UTC measured **US$5.87** over 6,498 calls (`gpt-5.4-mini` chat $2.81, `gpt-5.4` QA scoring $1.42, Content Safety $0.83, Realtime $0.33, Language $0.31, nano $0.17) — that day contains seven live eval runs, the live CI-gate demonstration, two smoke runs, two load checks and three screenshot sessions; 17 Nov (build, spikes, first evals) ≈ $3–4 *(estimate, the meter is per UTC day)*. Total for the project ≈ **US$9–10**. Unit costs: one live eval run $0.59, a smoke run $0.16, a load check $0.11, the live CI gate ≈ $0.9.
Budget guard: `AI_DAILY_BUDGET_USD` (code and Bicep default **5**; fails closed with a UI message, verified by tests and the smoke check). The deployed value was $12 during the evaluation campaign and is **$8** in the final state so that today's demo remains usable after the verification spend; restore the default with `azd env set DAILY_AI_BUDGET_USD 5 && azd provision`.

## 8. Idempotent re-deployment and teardown

```bash
azd provision --no-prompt     # 5 runs in total (initial creation, two infrastructure changes during M0/M1, two on the final code); ≈ 11.5 min each because the 34 Cosmos containers are updated one after another
azd deploy --no-prompt        # 23 runs (one failed on a transient ACR task-queue stall and was simply repeated); remote ACR build ≈ 1.5 min + new revision ≈ 1.5 min
```

The two final `azd provision` runs prove idempotency: no resource was created, deleted or replaced; the only difference between them is the intended app setting `AI_DAILY_BUDGET_USD`. (Honest note: the first of the two did not apply the new cap because I started `azd env set` and `azd provision` in parallel and `azd` read the old value; the second, started after the value was persisted, applied it — the deployment parameter history in ARM shows both.)
Drift check: see §12.
Teardown: `azd down --purge --force` (deletes the resource group; `--purge` also purges the soft-deleted AI Services account so the name can be reused).

## 9. Real versus simulated (explicit)

| Real, in `azure` mode | Simulated / not provisioned |
|---|---|
| Azure OpenAI chat (`gpt-5.4-mini`, `gpt-5.4`, `gpt-5.4-nano`), embeddings, **Realtime voice** (browser mic → AudioWorklet → PCM16 24 kHz → WebSocket relay → Azure OpenAI Realtime, server VAD, barge-in, tools, live transcripts) | **PSTN telephony is NOT provisioned**: no phone number, carrier, SIP trunk or Azure Communication Services resource exists. The provider-neutral telephony interface with three adapters (SIP → Azure OpenAI Realtime, Teams Phone Extensibility, ACS Call Automation *legacy* — ACS retires as a standalone service on 30 Sep 2028) is exercised by a simulator in tests and in the UI |
| Azure AI Speech, Language (PII, sentiment), Content Safety (Prompt Shields, groundedness, text analysis) with Entra tokens; deterministic rules are the always-on fallback | SMS, WhatsApp and e-mail delivery (outbox panel; channel adapters are tested stubs) |
| Cosmos DB (state, memory, audit, config, analytics aggregates), Blob Storage, Application Insights | The CRM / order-management back office: a mock in Cosmos with the real tool contracts (connector layer tested against mocked HTTP) |
| Routing, policy engine, handoff, QA, VoC, WFM, evaluation — real logic (Erlang-C, forecasting, k-means, rubric scoring) | **All customer data and the 90-day / 1,981-conversation history are synthetic** (seeded generator); the NordFreight spike is planted |

## 10. Estimated idle monthly cost *(estimate, Azure Retail Prices API, Sweden Central, list prices, 30-day month)*

| Item | US$ / month |
|---|---|
| Container App: 1 vCPU + 2 GiB always on at idle rates (2.59 M s × $0.000003 per vCPU-s + 2 GiB × $0.000003) minus the monthly free grant | ≈ 22 |
| Container Registry Basic ($0.1666 / day) | ≈ 5 |
| Cosmos DB serverless (no idle compute; < 1 GB at $0.25/GB), Storage LRS, alert rules, Log Analytics / App Insights inside the free 5 GB | < 1 |
| Azure OpenAI / AI Services (pay per token; nothing at idle) | 0 |
| **Total idle** | **≈ 28** |

Usage on top is capped by the daily AI budget guard; a typical demo hour costs cents, a full live eval run $0.59.

## 11. Security notes

* **Keyless**: Cosmos, AI Services and Storage have key/local authentication disabled; the app and the signed-in developer use Entra tokens. No secret exists in the repository, the image or the Bicep (secret scan: no matches); the optional Entra-auth switch stores a client secret only as a Container Apps secret when enabled.
* Defence in depth in code: authentication level per tool, refund caps and human approval, customer confirmation, idempotency keys, per-IP and global rate limits, request-size limits, CSP / HSTS / frame / referrer headers, PII/PCI redaction before storage, logs, audit and model input, prompt-injection quarantine for user text, KB documents and tool results, tamper-evident (hash-chained) audit trail.
* RBAC with seven roles at the API (188 endpoints; 126 role-protected, 62 public by design: customer-facing flows, health, KB search). The **role switcher is a demo convenience**; with `AUTH_MODE=entra` it is inert and JWTs are validated (issuer, audience, signature, algorithm).
* Known gaps, stated plainly: telephony webhook endpoints do not verify provider signatures (production must); public network access is enabled (private endpoints for production); a single replica holds the event bus and rate limiter in process; `pip-audit` was not run; `npm audit`: **0** vulnerabilities in production dependencies, 6 *high* advisories in build-time tooling (`picomatch` via vite/tinyglobby) that is not part of the runtime image.

## 12. Post-provision verification (final state)

Order of the last steps (deliberate): all AI-consuming verification first (eval, smoke, load check, screenshots at the $12 cap) → `azd env set DAILY_AI_BUDGET_USD 8` → `azd provision` (12 min 8 s, SUCCESS) → final smoke test (§5, 21 / 21) → read-back below.

| Check after the final `azd provision` | Result |
|---|---|
| Resources in `rg-swarmai-contactcenter` | **14** (9 declared in Bicep + 5 created by Azure); **0** without `SecurityControl=Ignore` / `SecurityExemption=StorageAccountKeyAccess`; RG tags as in §3 |
| ARM parameter history (`concierge-resources` deployment) | `dailyAiBudgetUsd = "8"`; live `GET /api/usage` → `budget_usd: 8.0`, status `ok` |
| Container App | latest revision `ca-concierge-imsov4laqyzgs--0000002`, single-revision mode, **min = max = 1**, `allowInsecure=false`, `AI_DAILY_BUDGET_USD=8` |
| Settings after provisioning | Storage `allowSharedKeyAccess=false`, `allowBlobPublicAccess=false`, TLS 1.2 · Cosmos `disableLocalAuth=true`, serverless · AI Services `disableLocalAuth=true` · ACR `adminUserEnabled=false` — **unchanged by governance and by the repeated provisioning** |
| `GET /readyz` | `status: ready`, `mode: azure`, Cosmos / Storage / Azure OpenAI / cognitive checks `ok` |
| `azd provision --preview` (ARM what-if, run twice) | **0 creates, 0 deletes**, 13 "modify" entries that are what-if noise: read-only or service-defaulted properties absent from the template (`currentCapacity`, `raiPolicyName`, ACR `anonymousPullEnabled`, …). The single value difference, Cosmos `enableAutomaticFailover true → false`, is an artifact — the template does not set it and the live value stayed `true` across two provisions |
| Local dev servers / background processes | none left running (ports 8103 and 5103 free) |

Resources and the app remain deployed for review; the daily cap resets at 00:00 UTC. Today's remaining headroom is ≈ $2.

## 13. Reproduce

```bash
cd app && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt && (cd web && npm ci)
.venv/bin/ruff check src tests && .venv/bin/python -m pytest --cov=concierge && (cd web && npm run build)
.venv/bin/python -m pytest tests/e2e -o addopts=""                         # needs `playwright install chromium`
cd .. && azd up --no-prompt                                                  # provision + build + deploy
app/.venv/bin/python scripts/smoke_test.py --base-url <live> --expect-mode azure
app/.venv/bin/python scripts/load_check.py --base-url <live>
app/.venv/bin/python scripts/capture_screens.py --base-url <live>            # -> deck/assets/screens/*.png (1600x900)
```

Screenshots (21 files, live app, synthetic data): `deck/assets/screens/01-customer-widget-chat.png` … `18-compliance-guard.png`.
