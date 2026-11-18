# SwarmAI Contact Center ("Concierge") — Feature Backlog & Status Board

> **Owner:** Product & solution architecture · **Engineering edits only the `Status` and `Evidence` cells of the status board.**
> **Contract:** Release 1 = CC-01 … CC-24. IDs and names below are frozen; descriptions, acceptance criteria and scope notes may be sharpened, never dropped.
> Companion documents: [`PRD.md`](PRD.md) (requirements `FR-*` / `NFR-*`, KPI plan) · [`ARCHITECTURE.md`](ARCHITECTURE.md) (target Azure architecture) · [`business-case/`](business-case/README.md) (ROI & ACR model).

## 0. How to read this document

* **Status values:** `Planned` → `In progress` → `Implemented` (code + unit tests merged locally) → `Tested` (unit + API/behavioural tests green, UI surface present) → `Deployed ✔` (the post-deploy smoke test exercised the feature **on Azure**).
* **Evidence** = test names / smoke-test check names / screenshot file / URL path. A feature is never `Deployed ✔` on the strength of unit tests alone.
* **Priority:** `P0` = must work in the live demo and be in the executive story; `P1` = required for Release 1 completeness, may be shallower; `P2` = Release 1 but thin slice acceptable (still real, tested software).
* **Target vs deployed slice:** every feature describes the *target* Azure service(s) for an enterprise deployment and the *deployed slice* in this repository (one Container App, Cosmos DB serverless, Foundry/AIServices account, App Insights, ACR, managed identity). Nothing in the slice uses keys or connection strings (managed identity + RBAC only).
* **What is simulated** is stated explicitly per feature. The demo has **no PSTN/telephony provisioned**; web voice (browser microphone → WebSocket relay → Azure OpenAI Realtime) is the live voice channel. The telephony path is implemented behind a `TelephonyAdapter` interface and exercised by a simulator in tests.
* All data are **synthetic** (fictional retailer *Contoso Home*; seeded RNG). All amounts in demo flows are illustrative (EUR); the business case is in USD.
* **Platform note (Microsoft Learn, Sep 2026):** Azure Communication Services is being retired as a standalone offering on 30 Sep 2028 (SMS, Email, Chat, Direct Routing, Job Router retired; Call Automation only for Teams-aligned scenarios), and tenants without an ACS resource created before 23 Oct 2026 cannot acquire ACS phone numbers or SMS. The telephony/messaging layer is therefore **pluggable** (`TelephonyAdapter`, `ChannelAdapter`, `Router`); `ARCHITECTURE.md` (ADR-02) names the production options. Feature IDs, names and acceptance criteria are unaffected.

### Epics

| Epic | Name | Features |
|---|---|---|
| A | Conversational AI agents | CC-01 … CC-05 |
| B | Routing & human collaboration | CC-06 … CC-09 |
| C | Quality, compliance, insight | CC-10 … CC-13 |
| D | Operations & LLMOps | CC-14 … CC-18 |
| E | Platform | CC-19 … CC-24 |

### KPI catalogue (used in every feature section and in the traceability matrix)

| KPI | Name | Definition (how it is measured) | Better |
|---|---|---|---|
| KPI-01 | Verified AI resolution rate | % of AI-first contacts closed by the AI **with a verified outcome** (state change confirmed in the system of record, or answer confirmed by the customer) and **no re-contact on the same intent within 7 days**. Only verified resolutions are monetised in the business case. | ↑ |
| KPI-02 | AI containment rate | % of AI-first contacts completed without a human. Reported next to KPI-01 so the "false containment" gap (containment − verified resolution) is visible. | ↑ (gap ↓) |
| KPI-03 | Average handle time (AHT), human-handled | Talk/chat handling time + after-call work (ACW) per human-handled contact, by queue/channel. | ↓ |
| KPI-04 | After-call work (ACW) time | Seconds of wrap-up per human-handled contact (manual vs auto wrap-up with agent edits). | ↓ |
| KPI-05 | First-contact resolution (FCR) | % of contacts with no repeat contact on the same intent within 7 days (all channels, AI and human). | ↑ |
| KPI-06 | CSAT (surveyed and predicted) | Post-contact survey score where available; predicted CSAT (model-based, calibrated to surveys) for 100 % of contacts. | ↑ |
| KPI-07 | Cost per contact / cost per resolved contact | Fully-loaded human cost + metered Azure/AI cost, per contact and per *verified-resolved* contact, AI vs human, per queue and interval. | ↓ |
| KPI-08 | QA coverage & calibration agreement | % of conversations scored (target 100 %) and agreement between auto-QA and human QA calibration (± 1 band / Cohen's κ). | ↑ |
| KPI-09 | Escalation quality | % of handoffs delivered with a complete context package, customer re-explanation rate, time-to-first-human-response, post-handoff CSAT. | ↑ |
| KPI-10 | Voice turn latency | p50/p95 time from end of customer speech to first agent audio (target p95 < 800 ms on the production path); text time-to-first-token. | ↓ |
| KPI-11 | Service level & abandonment | % answered within threshold (e.g., 80/20), abandon rate, speed-of-answer, per queue/interval. | ↑ (abandon ↓) |
| KPI-12 | Compliance & safety adherence | Disclosure/consent capture rate (target 100 %), PII/PCI leakage incidents (target 0), policy-violating tool calls (target 0), red-team must-pass rate (target 100 %). | ↑ / 0 |
| KPI-13 | Groundedness & answer accuracy | % of answers grounded in cited sources; fabricated-answer detection rate on seeded tests; "don't know → escalate" precision. | ↑ |
| KPI-14 | Agent experience & attrition | Agent attrition %, agent eNPS, occupancy, share of time on complex vs repetitive work. | attrition ↓ |
| KPI-15 | Forecast accuracy & schedule fit | Interval/daily MAPE, SLA attainment of the recommended schedule in simulation, over-/under-staffing minutes. | MAPE ↓ |
| KPI-16 | Release quality (LLMOps) | Eval-gate pass rate, change-failure rate, mean time to rollback, canary regressions caught pre-promotion. | ↑ / ↓ |
| KPI-17 | Insight latency | Time from emerging issue (e.g., "damaged on delivery", carrier X) to alert; repeat-contact rate. | ↓ |
| KPI-18 | Platform reliability & cost telemetry | Availability SLO attainment, latency SLO burn, % of interactions with complete token/audio-minute metering. | ↑ |
| KPI-19 | Language coverage & accessibility | Languages evaluated in production quality, WCAG 2.1 AA conformance of the UI (automated + manual checks). | ↑ |

## 1. Status board

| ID | Feature | Epic | Priority | Status | Evidence |
|---|---|---|---|---|---|
| CC-01 | Omnichannel chat agent | A — Conversational AI agents | P0 | Deployed ✔ | `features/chat`, `engine/orchestrator.py`; tests: `test_flow_damaged_sofa`, `test_api_surface`, E2E widget; live: smoke GJ-1 (DE, real refund), eval 42 scenarios |
| CC-02 | Real-time voice agent | A — Conversational AI agents | P0 | Deployed ✔ | `features/voice` (Realtime relay, STT→LLM→TTS fallback, 3 telephony adapters + simulator); tests: `test_voice` (fake Realtime server), `test_telephony`, E2E call page; live: smoke Realtime text turn → audio + transcript. PSTN not provisioned |
| CC-03 | Knowledge-grounded answers / RAG | A — Conversational AI agents | P0 | Deployed ✔ | `engine/rag.py`, `features/knowledge`; tests: `test_privacy_rag` (retrieval, don't-know, fabricated-answer and date/time grounding sets); live: smoke cited answer + don't-know |
| CC-04 | Transactional tools / skills | A — Conversational AI agents | P0 | Deployed ✔ | `engine/tools.py`, `features/tools` (allow-lists, caps, approvals, idempotency, audit); tests: `test_tool_policy`; live: smoke refund via real tool calls |
| CC-05 | Identity verification, consent & disclosure | A — Conversational AI agents | P0 | Deployed ✔ | `features/identity`, `engine/tools.py`; tests: `test_tool_policy` (auth gate), `test_flow_damaged_sofa` (OTP, consent, disclosure), `test_security`; live: smoke OTP → Verified L1 |
| CC-06 | Intent/sentiment/urgency understanding & smart routing | B — Routing & human collaboration | P0 | Deployed ✔ | `engine/routing.py`, `engine/understanding.py`, `features/routing`; tests: `test_routing` (≥30-case matrix, escalation triggers fire once); live: smoke legal threat → escalations queue |
| CC-07 | Warm handoff with context package | B — Routing & human collaboration | P0 | Deployed ✔ | `engine/handoff.py`, `features/handoff`; tests: `test_routing`, `test_api_surface`, E2E agent console; live: smoke package complete, accepted by a human agent |
| CC-08 | Agent Assist copilot | B — Routing & human collaboration | P0 | Deployed ✔ | `features/assist`; tests: `test_api_surface`, E2E agent console; live: smoke handoff + Agent Assist suggestions (screenshot 02) |
| CC-09 | Auto wrap-up | B — Routing & human collaboration | P0 | Deployed ✔ | `engine/wrapup.py`, `features/wrapup`; tests: `test_flow_damaged_sofa` (disposition RESOLVED_REFUND_ISSUED, summary); live: smoke wrap-up produced |
| CC-10 | 100 % Auto-QA | C — Quality, compliance, insight | P0 | Deployed ✔ | `engine/qa.py`, `features/qa`; tests: `test_analytics` (rubric, evidence, agreement with human scores), E2E; live: smoke auto-QA ≥ 90/100 with evidence |
| CC-11 | Compliance & risk guard | C — Quality, compliance, insight | P0 | Deployed ✔ | `engine/guard.py`, `features/compliance`; tests: `test_privacy_rag` (PII/PCI golden set, injection), `test_eval_harness` (44-attack red-team pack); live: smoke red-team probes execute no forbidden tool |
| CC-12 | Voice-of-customer analytics | C — Quality, compliance, insight | P1 | Deployed ✔ | `engine/voc.py`, `features/voc`; tests: `test_analytics` (cluster purity, planted NordFreight spike alerts, no-spike control); live: smoke 1,981 records, 12 clusters, critical alert |
| CC-13 | CX metrics & ROI view | C — Quality, compliance, insight | P0 | Deployed ✔ | `features/metrics`, `engine/metrics.py`, vendored `business-case/model.py`; tests: `test_analytics` (metrics reconcile, ROI parity ≤ 0.5 % vs `outputs.json`); live: smoke NPV $27.1M, ROI 216 %, Y3 ACR $2.98M |
| CC-14 | Workforce forecasting & staffing | D — Operations & LLMOps | P1 | Deployed ✔ | `engine/wfm.py`, `features/wfm`; tests: `test_analytics` (Erlang-C vs exact arithmetic, forecast backtest MAPE, staffing meets SLA in simulation); live: smoke SL 89 %, daily MAPE 5.9 % |
| CC-15 | Supervisor console | D — Operations & LLMOps | P0 | Deployed ✔ | `features/supervisor`; tests: `test_api_surface`, `test_security` (role matrix), E2E supervisor console; live: screenshot 03 (queues, SLA clocks, heat map, interventions) |
| CC-16 | Evaluation & simulation harness | D — Operations & LLMOps | P0 | Deployed ✔ | `engine/evalrun.py`, `engine/redteam.py`, `features/evals`; tests: `test_eval_harness` (42 scenarios + 44 attacks; gate fails for 4 broken variants); live: core suite 40–42/42 on the real model (see report) |
| CC-17 | Prompt/policy/knowledge management & staged rollout | D — Operations & LLMOps | P1 | Deployed ✔ | `features/rollout`, `features/knowledge`; tests: `test_eval_harness` (gate blocks promotion), `test_api_surface`, E2E; live: screenshots 09, 17 |
| CC-18 | Proactive & outbound engagement | D — Operations & LLMOps | P2 | Deployed ✔ | `engine/outbound.py`, `features/outbound`; tests: `test_platform` (consent, opt-out, time-zone quiet hours, caps, kill switch), `test_api_surface`; simulated delivery (no SMS/WhatsApp/e-mail provider) |
| CC-19 | Multilingual & accessibility | E — Platform | P1 | Deployed ✔ | `features/multilingual`, `core/langid.py`, `engine/translate.py`; tests: `test_platform`, `test_api_surface` (i18n round trip), E2E axe-core WCAG A/AA scan of 14 routes; live: German journey in smoke; **Polish (`pl`, Phase 1):** `core/i18n.py` (locale contract), `core/catalog_{en,pl}.py`, `engine/lexicon_pl.py`, `core/redaction.py` (PESEL / NIP / REGON / dowód / NRB), `engine/kb_seed_pl.py` (50 articles), `engine/eval_pl.py` (31 scenarios), `features/voice` (pl Realtime + pl-PL TTS); tests: `test_pl_*` (443); real model (hybrid): Polish pack 29/31 = 93.5 %, 0 safety failures, smoke `PL-1…PL-10` 10/10; **live (Azure, build 20261118-131258): smoke `--lang all` 31/31 incl. `PL-1…PL-10`, Polish eval subset 10/10** |
| CC-20 | Customer 360 & CRM integration layer | E — Platform | P1 | Deployed ✔ | `engine/crm.py`, `engine/crm_contract.py`, `features/crm`; tests: `test_platform` (connector contract tests against mocked HTTP), `test_security` (PII masking by role) |
| CC-21 | Security, identity, RBAC | E — Platform | P1 | Deployed ✔ | `core/rbac.py`, `core/security.py`, `features/security`; tests: `test_security` (JWT with local RSA keys, algorithm confusion, role matrix, rate limits, tamper-evident audit chain); live: smoke RBAC + security headers |
| CC-22 | Observability & FinOps | E — Platform | P1 | Deployed ✔ | `features/observability`, `core/ai/usage.py`, `core/tracing.py`, `core/telemetry.py`; tests: `test_api_surface`, `test_platform`; live: smoke SLOs + 100 % metered interactions + daily AI budget guard; App Insights + Log Analytics deployed |
| CC-23 | IaC & deployment | E — Platform | P0 | Deployed ✔ | `infra/*.bicep`, `azure.yaml`, `Dockerfile`; tests: `test_platform` (Bicep ↔ collections, governance tags, keyless settings); live: `azd provision` + `azd deploy` repeated idempotently, RG and resource tags verified |
| CC-24 | Agent Studio UI | E — Platform | P0 | Deployed ✔ | `features/studio`, `app/web/src` (auto-discovered `meta.ts` per feature, Feature Map `/features`); tests: `test_platform` (feature discovery), E2E 27 journeys; `/api/features` lists 24/24 implemented; **Polish UI (Phase 1):** language switcher EN | PL, `app/web/src/i18n` (dictionary completeness, plural and format unit tests), Polish E2E journeys and 1600×900 screenshots in `deck/assets/screens-pl/` (counts in `app/PHASE1-fe-DONE.md`); the API stays language independent (`/api/features` is English, translated by feature ID); **live: Polish Playwright journeys against the deployed app (see REPORT §14.6)** |

*Rules for the registry:* `GET /api/features` must return exactly these 24 IDs and names (plus `epic`, `priority`, `status`, `ui_route`, `api_prefix`); the SPA Feature Map (`/features`) renders it. This board and the registry must not drift.

## 2. Golden journeys (cross-feature acceptance tests)

These end-to-end journeys are the *demo narrative* made testable. Each must run in the Playwright E2E suite (offline stub models) and, where marked ☁, in the post-deploy smoke test against Azure.

| ID | Journey | Must demonstrate | Features |
|---|---|---|---|
| GJ-1 ☁ | **Damaged sofa, in German, resolved by AI in ≤ 3 minutes** — customer clicks "Call us" (or chats) and reports in German that a sofa arrived damaged | language detected → AI disclosure + recording consent captured → OTP verification → order looked up → returns/damage policy retrieved **and cited** → replacement or refund offered (refund cap enforced) → pickup slot booked → confirmation sent → auto wrap-up (summary + disposition) → auto-QA score with evidence; **no human involved**; cost-per-resolved-contact visible | CC-01/02, 03, 04, 05, 06, 09, 10, 11, 13, 19, 22 |
| GJ-2 ☁ | **Angry customer mentions legal action → warm handoff** | sentiment + legal-threat risk flag → escalation trigger fires → routed to the specialist queue → human console shows summary, steps tried, sentiment trajectory, suggested resolution, policy citations **before** the human speaks → Agent Assist suggests next-best-actions with citations and compliance reminders → human closes → auto wrap-up | CC-06, 07, 08, 09, 15, 10 |
| GJ-3 | **Supervisor in control** | live queues, active AI + human conversations, sentiment heat, SLA-risk alert, take-over / whisper / approve above-cap refund request | CC-15, 04, 06 |
| GJ-4 | **Quality at 100 % and emerging issue** | both journeys auto-scored with evidence; VoC flags a spike in "damaged on delivery" for one carrier; QA analyst calibrates a score | CC-10, 12 |
| GJ-5 | **WFM what-if** | forecast per queue, Erlang-C staffing, capacity plan changes when the containment slider moves | CC-14, 13 |
| GJ-6 | **Safe change** | a deliberately broken prompt is rejected by the eval gate; a good change goes canary → promote; rollback works | CC-16, 17 |
| GJ-7 | **Attack and leak resistance** | prompt-injection in user text and in a KB document does not trigger a forbidden tool call; a card number is never present in transcript, logs or LLM context | CC-11, 05, 04, 03 |
| GJ-8 ☁ | **ROI view** | calculator reproduces `business-case/outputs.json` (Base) within 0.5 %; cost per resolved contact AI vs human shown from live metering | CC-13, 22 |

## 3. Feature specifications

### Epic A — Conversational AI agents

#### CC-01 · Omnichannel chat agent `P0`
**PRD:** FR-A01, FR-A02 · **KPIs:** KPI-01, KPI-02, KPI-06, KPI-07, KPI-11

**Why / problem.** Customers repeat themselves across channels and wait for a human for requests a well-grounded agent can finish. The chat agent is the lowest-latency, lowest-cost place to resolve Tier-1 contacts and the foundation every other channel reuses.

**Description.** A web chat widget plus REST/WebSocket (SSE) API in front of the Resolution agent. Streaming responses, multi-turn session memory, multilingual replies, typing/“agent is working” states, tool-use progress. A `ChannelAdapter` interface normalises inbound/outbound messages so the same agent core serves web chat, a generic webhook channel and (as tested stubs) SMS, WhatsApp and email.

**Acceptance criteria**
* A visitor opens the widget, sends a message and sees a **token-streamed** reply; first token ≤ 2 s p95 on the deployed slice under normal load (measured and shown in CC-22).
* Session memory: a ≥ 10-turn conversation correctly resolves references to earlier turns ("that order", "the second option"); the session survives a server restart (state persisted).
* The agent replies in the customer's language (German, English, French, Spanish, Italian, Dutch, Polish, Portuguese evaluated) without being told the language.
* `ChannelAdapter` contract tests run against **web chat, generic webhook and the SMS / WhatsApp / email stubs** (inbound normalisation, outbound rendering, delivery receipt, idempotent message IDs).
* OpenAPI documents the session/message/stream endpoints; a request-size limit and rate limit protect them; a rejected request returns a clear, localised error.

**Azure services.** *Target:* channel plane behind `ChannelAdapter` — Azure Web PubSub or Container Apps WebSockets for web chat; messaging (SMS, WhatsApp, e-mail) via Dynamics 365 Contact Center channels or partner CPaaS (Azure Communication Services Chat/SMS/Email/WhatsApp are being retired on 30 Sep 2028 and suit only tenants already on ACS); Azure OpenAI/Foundry chat models, Cosmos DB, Front Door. *Deployed slice:* FastAPI WebSocket/SSE on Container Apps, Azure OpenAI `chat` deployment (gpt-5.4-mini), Cosmos DB serverless session store.

**Reference scope & simulated.** Real: web chat, webhook channel, memory, streaming, multilingual. Simulated: SMS/WhatsApp/email delivery (adapters are tested stubs behind the same interface; no carrier accounts).

**Dependencies.** CC-03, CC-04, CC-05, CC-06, CC-11 (guard), CC-22 (metering), CC-24 (widget).

---

#### CC-02 · Real-time voice agent `P0`
**PRD:** FR-A03, FR-A04 · **KPIs:** KPI-01, KPI-02, KPI-10, KPI-11, KPI-07

**Why / problem.** Voice is still the most expensive and most-abandoned channel. A voice agent only matters if it feels natural: sub-second turn-taking, barge-in, and the ability to *act* (not just talk) mid-call.

**Description.** Browser voice: the widget's "Call us" captures microphone audio (24 kHz PCM16) and streams it over a WebSocket to a relay that holds a session with the Azure OpenAI Realtime API (`gpt-realtime-2.1-mini`, fallback `gpt-realtime-mini`): server-side VAD, barge-in (cancel + truncate on interruption), **tool-calling inside the realtime session** (same tool registry as CC-04), live transcript, per-turn latency metrics. A fallback **STT → LLM → TTS** pipeline (Azure AI Speech / transcribe + chat + TTS) takes over if the realtime path is unavailable or a language/voice is not supported. A **`TelephonyAdapter`** interface implements the **Azure Communication Services Call Automation** contract (incoming-call event, answer, media streaming, play/recognize, transfer, hang-up) and is exercised by a simulator.

**Acceptance criteria**
* Relay protocol tests against a **fake realtime server** cover `session.update`, audio append/commit, audio-delta streaming back to the browser, tool-call round trip (function call → result → continuation), and **barge-in cancel** (response cancelled and audio playback truncated within one turn).
* Live smoke test proves the Azure path **without a human**: text input → realtime session → audio + transcript output, with a tool call, on the deployed slice.
* Voice turn latency (end of user speech → first audio delta) is measured server-side per turn; p50/p95 are exposed in CC-22 and displayed in the UI. Production target p95 < 800 ms; the demo reports what it actually achieves.
* Fallback: when the realtime session is forced to fail in a test, the conversation continues through STT → LLM → TTS with a visible "fallback" marker and the transcript stays continuous.
* `TelephonyAdapter` state machine is driven by simulated ACS events (`IncomingCall`, `CallConnected`, `PlayCompleted`, `RecognizeCompleted`, `CallDisconnected`) and produces the expected actions (answer, start media streaming, hand audio to the voice session, transfer to human, hang up).
* Live transcript streams to the UI during the call and is stored with the conversation (PII-redacted per CC-11).

**Azure services.** *Target (telephony is pluggable behind `TelephonyAdapter`):* (a) SIP trunk or SBC → the **Azure OpenAI Realtime SIP endpoint** (Sweden Central supported; webhook `realtime.call.incoming`, accept / refer / hang-up APIs, WebSocket side-channel for tools); (b) Teams Phone Extensibility with Call Automation for Microsoft-telephony tenants; (c) Dynamics 365 Contact Center voice; (d) partner CPaaS media streams → relay; (e) Azure Communication Services Call Automation for tenants that already run on ACS (the service is being retired as a standalone offering on 30 Sep 2028). Azure OpenAI Realtime (or Foundry Voice Live API), Azure AI Speech (fallback STT/TTS, custom neural voice), Container Apps/AKS media relays, Front Door. *Deployed slice:* Container App WebSocket relay → Azure OpenAI Realtime (`realtime` deployment) with AIServices Speech fallback.

**Reference scope & simulated.** Real: browser voice over Azure OpenAI Realtime, barge-in, tools, metrics, fallback. **Simulated: PSTN/SIP telephony — no phone numbers are provisioned in the demo**; the Call Automation-style adapter (the event model above) is real code behind the provider-neutral `TelephonyAdapter`, tested with a simulator; any other provider (for example the Realtime SIP webhook events) plugs into the same interface. *Stretch (not required for Release 1):* a second simulated provider profile driven by `realtime.call.incoming` webhooks passes the same state-machine tests. PSTN provisioning is documented in `ARCHITECTURE.md` only.

**Dependencies.** CC-04, CC-05, CC-06, CC-11, CC-19, CC-22.

---

#### CC-03 · Knowledge-grounded answers / RAG `P0`
**PRD:** FR-A05, FR-A06 · **KPIs:** KPI-13, KPI-01, KPI-12

**Why / problem.** Inconsistent answers and hallucinated policy are the fastest way to lose customer trust. Every factual statement about policy, product or process must be traceable to a published source — or the agent must say it does not know and escalate.

**Description.** Knowledge-base ingestion (markdown, PDF, text, HTML — FAQs, policies, product and troubleshooting guides), heading-aware chunking, embeddings (`text-embedding-3-small`), hybrid retrieval (vector + keyword) with **citations** to KB chunk IDs, a "don't know → escalate" threshold, and a **groundedness check** (Azure AI Content Safety groundedness detection or an LLM judge) before an answer is delivered. KB admin with documents, **versions and publish** (draft → published, rollback). The in-process vector index is persisted to Cosmos DB (Azure AI Search is the scale-out path behind the same `Retriever` interface).

**Acceptance criteria**
* Ingesting the seeded KB (≥ 40 documents across returns, damage, delivery, warranty, billing, installation, product care) produces chunks with embeddings; ingestion is idempotent (re-ingest does not duplicate).
* Answers to in-scope questions include **≥ 1 citation** that resolves to the exact chunk text shown in the UI; an eval set of ≥ 20 questions reaches the target citation-accuracy threshold.
* Out-of-scope or unanswerable questions yield a "don't know" answer and an escalation offer — never a fabricated policy (seeded unanswerable set passes).
* The groundedness check **flags a seeded fabricated answer** (and blocks or rewrites it) and passes grounded answers.
* KB admin: create/upload document → draft version → publish → agents use the published version only; rolling back restores the previous version; every change is audit-logged.
* Content from KB documents is treated as **untrusted data** (a seeded KB doc containing an injected instruction does not alter agent behaviour — see CC-11).

**Azure services.** *Target:* Azure AI Search (hybrid + semantic ranker, integrated vectorization), Azure OpenAI embeddings, Content Safety groundedness detection, Blob/ADLS for sources, Document Intelligence for PDFs. *Deployed slice:* in-process index persisted in Cosmos DB, `embed` deployment (text-embedding-3-small), LLM-judge groundedness (Content Safety groundedness where available on the AIServices account).

**Reference scope & simulated.** Real: ingestion, retrieval, citations, groundedness, versioning. Simulated: none (the KB content is synthetic Contoso Home policy text).

**Dependencies.** CC-11 (injection defence), CC-17 (KB versions in rollout), CC-22.

---

#### CC-04 · Transactional tools / skills `P0`
**PRD:** FR-A07 · **KPIs:** KPI-01, KPI-05, KPI-07, KPI-12

**Why / problem.** "Deflection" that ends in "please call us" is not resolution. The agent must be able to *do* things — safely: look up, change, refund, book — with limits a CFO and a compliance officer would sign.

**Description.** Function-calling against a **mock back-office service** (CRM/OMS/billing) with the following tools: look up customer and order, track shipment, initiate return, issue refund (autonomous cap; **approval required above cap**), reschedule delivery/pickup, update address, goodwill credit (cap), warranty claim, create/update ticket, escalate to human. A policy engine enforces: authentication level, per-agent **tool allow-lists**, monetary caps and frequency limits, eligibility windows, explicit **confirmation** before any state-changing call, **idempotency keys**, and an append-only **audit trail** (who/what/why/arguments hash/result).

**Acceptance criteria**
* **Refund above the cap** is not executed: the agent requests approval / escalates, a supervisor can approve or deny in CC-15, and the outcome is audited.
* **Idempotent retries:** repeating the same tool call (same idempotency key) after a timeout never double-refunds or double-books.
* An **unauthenticated** session cannot read account data or run state-changing tools; **cross-customer access** attempts (another customer's order ID) are rejected and audited.
* Every state-changing tool call is preceded by a read-back confirmation turn (text or voice) and recorded with the confirmation reference.
* The agent can only call tools on its allow-list (e.g., the Knowledge agent has no write tools); a prompt-injection attempt to call a forbidden tool is blocked and logged.
* A tool failure/timeout produces a graceful message and (after N failures) triggers escalation (CC-06) with the failed step in the handoff package.

**Azure services.** *Target:* Azure API Management in front of OMS/CRM APIs, Dynamics 365 / Dataverse, Azure Functions or Container Apps tool services, Key Vault, Foundry Agent Service tools / MCP servers (Release 2). *Deployed slice:* mock back-office module in the same Container App behind the connector interface (CC-20), Cosmos DB for orders/customers/audit.

**Reference scope & simulated.** Real: tool registry, policy engine, idempotency, audit. Simulated: the back-office itself (synthetic orders, customers, carriers).

**Dependencies.** CC-05, CC-11, CC-20, CC-21.

---

#### CC-05 · Identity verification, consent & disclosure `P0`
**PRD:** FR-A08, FR-A09 · **KPIs:** KPI-12, KPI-01, KPI-06

**Why / problem.** Account actions need identity assurance; AI use needs disclosure; recording needs consent; card data must never reach an LLM. These are table stakes for regulated, brand-sensitive operations.

**Description.** A verification flow (OTP and knowledge-based fallback, step-up for risky actions), **AI disclosure** at the start of every conversation, **recording consent** capture (text version, timestamp, channel) with a decline path, **PII minimisation** (only the fields needed are placed in LLM context; identifiers masked), and a **secure payment hand-off** (DTMF capture or hosted payment link — simulated) so that card data never enters transcripts, logs or model context.

**Acceptance criteria**
* AI disclosure is spoken/shown first in 100 % of conversations (asserted per channel) and recorded as an event; recording consent is captured with timestamp + consent-text version; **declining consent** either continues without recording or routes to a human (configurable) and is honoured downstream (no recording stored).
* OTP flow: code delivered via the simulated outbox (visible in a demo "outbox" panel), expiry and attempt limits enforced; wrong code ×3 locks the flow and offers a human; KBA fallback works; verification level (L0 anonymous / L1 OTP / L2 step-up) gates tools (CC-04).
* Step-up: a refund or address change requires L1+ (and L2 above a configurable value).
* **Payment hand-off:** when a payment is needed the agent calls a `request_payment` tool that returns a hosted-link/DTMF session; a golden test proves **no PAN/CVV** appears in transcript, logs, tool arguments or LLM context even if the customer speaks or types a card number (redaction + hand-off).
* PII minimisation: a unit test asserts which fields reach the model prompt (allow-list) for a sample conversation.

**Azure services.** *Target:* Microsoft Entra External ID (customer identity, e-mail one-time passcode), SMS OTP via partner CPaaS (Azure Communication Services SMS is being retired on 30 Sep 2028), PCI-certified payment service / IVR (DTMF capture through the telephony provider + PSP hosted page), Key Vault, Purview. *Deployed slice:* in-app OTP/KBA service with simulated outbox, consent store in Cosmos DB, payment hand-off simulation.

**Reference scope & simulated.** Real: flows, state, gating, redaction. Simulated: OTP delivery channel and the payment service provider (no real PSP, no real PANs).

**Dependencies.** CC-11 (redaction), CC-04, CC-20, CC-21.

---

### Epic B — Routing & human collaboration

#### CC-06 · Intent/sentiment/urgency understanding & smart routing `P0`
**PRD:** FR-B01, FR-B02 · **KPIs:** KPI-09, KPI-11, KPI-05, KPI-06

**Why / problem.** Routing on a menu choice ignores what the customer actually needs and how they feel. The wrong queue costs a transfer; ignoring a legal threat or a vulnerable customer costs far more.

**Description.** The Greeter/Router agent extracts **intent and entities**, **sentiment/emotion and urgency**, and **risk flags** (legal threat, vulnerable customer, fraud suspicion, safety issue, regulatory complaint, churn risk) on every turn. A deterministic **skills-based routing engine** modelled on Azure Communication Services **Job Router** semantics (jobs, workers with labels/skills and capacity, queues, classification policy, distribution policy, exception policy) assigns escalations by skills, priority, SLA, VIP and vulnerable status. **Escalation triggers** (sentiment threshold, conversation loops, explicit "I want a person", policy block, tool failure, risk flag) are explicit, configurable rules.

**Acceptance criteria**
* A **routing matrix test** (queues × skills × priority × VIP × vulnerable × legal-risk × language) behaves exactly per the written spec (table-driven, deterministic; ≥ 30 cases).
* Seeded transcripts fire each escalation trigger exactly once and with the right reason code (sentiment, loop, explicit request, policy, tool failure, legal threat, vulnerable).
* Intent/entity extraction on the labelled seed set reaches the target macro-F1; sentiment trajectory is stored per turn and visible in the console.
* SLA/priority handling: VIP and vulnerable customers are routed ahead of standard contacts; an exception policy raises priority when the SLA is at risk.
* Routing decisions are explainable: each decision stores the inputs (labels, scores) and the matching rule.

**Azure services.** *Target:* routing engine with Job Router semantics (queues, classification and distribution policies, exception policies) — Dynamics 365 Contact Center routing (Microsoft's stated alternative to Azure Communication Services Job Router, which is being retired on 30 Sep 2028), a partner routing engine, or the in-process router; Azure AI Language (sentiment, CLU/NER) and/or Azure OpenAI classifiers, Event Grid. *Deployed slice:* in-process router implementing Job Router semantics behind a `Router` interface; LLM (gpt-5.4-nano/mini) classification with deterministic rules for risk flags; Language service via the AIServices account.

**Reference scope & simulated.** Real: classification, scoring, routing engine, triggers. Simulated: the human-agent population (seeded agents with skills/capacity/presence).

**Dependencies.** CC-01/02 (input), CC-07 (handoff), CC-15, CC-11.

---

#### CC-07 · Warm handoff with context package `P0`
**PRD:** FR-B03 · **KPIs:** KPI-09, KPI-03, KPI-06

**Why / problem.** The most hated moment in a contact center is "please repeat your problem". A handoff is only *warm* if the human knows everything the AI knew before they say hello.

**Description.** When the AI escalates, the Escalation/Handoff agent builds a **context package** — customer and verification level, summary, intent and entities, **steps tried** (tools called and results), **sentiment trajectory**, risk flags, **suggested resolution**, **policy citations**, language and preferences, SLA timer, full transcript link — and delivers it to the human-agent console in real time (before the agent accepts the contact, then live-updating). The customer is told what is happening ("I'm bringing in a colleague who can see our conversation").

**Acceptance criteria**
* On escalation the package is delivered to the assigned agent's console in ≤ 2 s (measured) and renders every required section; a completeness score (0–100 %) is computed and ≥ 90 % on the seeded escalation set.
* The agent console shows the package **before** the human's first message; the customer is not asked for information already in the package (asserted by a seeded test: no re-asking of verified identity, order ID, issue).
* The package is **PII-minimised** (masked identifiers by default, reveal on demand with audit).
* Handoff works from **chat and voice** (voice: AI stays on the line until the human joins; whisper summary simulated in UI).
* If no human is available the customer is offered a callback/ticket with the package attached (no loss of context).

**Azure services.** *Target:* routing-engine offer/accept, call transfer through the telephony adapter (SIP REFER or provider transfer), Teams or CCaaS agent desktop, Event Grid, SignalR/Web PubSub for live updates, Cosmos DB. *Deployed slice:* WebSocket push to the in-app agent console; package stored in Cosmos DB.

**Reference scope & simulated.** Real: package generation and delivery. Simulated: voice transfer to a physical human (the console is the human surface; voice "join" is simulated).

**Dependencies.** CC-06, CC-08, CC-09, CC-15, CC-20.

---

#### CC-08 · Agent Assist copilot `P0`
**PRD:** FR-B04, FR-B05 · **KPIs:** KPI-03, KPI-05, KPI-14, KPI-12

**Why / problem.** New agents take months to ramp; experienced agents drown in knowledge and compliance prompts. Assist raises quality and shortens handling time without removing the human from decisions that need judgement.

**Description.** A real-time copilot in the human-agent console: live transcript, **next-best-action** (ranked, with rationale and **policy citations**), **suggested replies** (editable, one-click insert), **compliance reminders** (required disclosures per intent/market), knowledge search, **form auto-fill** (ticket, refund, address change), and **tone coaching** (e.g., "customer is frustrated — acknowledge first"). The console also supports **chat takeover** of an AI conversation with full history.

**Acceptance criteria**
* Suggestions appear within ≤ 2 s of each customer turn (p95, deployed slice) and **every factual suggestion carries a citation** that opens the policy/KB chunk.
* Compliance reminders fire for seeded scenarios (e.g., refund → required statement; recording consent missing → prompt) and clear when the agent complies; adherence is logged for QA.
* Form auto-fill populates ≥ 80 % of fields correctly on the seeded set and the agent can edit before submit; every accepted/edited/rejected suggestion is logged (acceptance rate KPI).
* Chat takeover: a human takes over a live AI chat; the AI stops responding, the history is intact, and the customer sees a clear handover message.
* The copilot never executes a state-changing tool on its own; the human triggers it (with the same policy engine and audit as CC-04).

**Azure services.** *Target:* Azure OpenAI (chat/reasoning), Azure AI Search, Azure AI Speech real-time STT/diarization for voice, Azure AI Language, Dynamics 365 / Teams embedded agent desktop. *Deployed slice:* LLM calls from the Container App, KB retriever (CC-03), in-app agent console.

**Reference scope & simulated.** Real: suggestions, citations, reminders, takeover. Simulated: live phone audio for human calls (voice assist is driven by web-voice transcripts and scripted human-agent sessions).

**Dependencies.** CC-03, CC-04, CC-07, CC-11, CC-24.

---

#### CC-09 · Auto wrap-up `P0`
**PRD:** FR-B06 · **KPIs:** KPI-04, KPI-03, KPI-14

**Why / problem.** After-call work is dead time: agents re-type what the system already knows. For AI-resolved contacts it is pure cost.

**Description.** At the end of every conversation (AI or human) the system produces a **summary**, **disposition codes** (from the tenant taxonomy), **CRM notes** (written through the connector), **follow-up tasks**, and **QA flags**; humans can edit before submit. The product **measures after-call-work reduction** (manual vs auto, edit distance, time on the wrap-up screen).

**Acceptance criteria**
* ≥ 95 % of ended conversations have a wrap-up record within 10 s of end (AI-resolved: fully automatic; human: pre-filled for one-click confirm).
* On the labelled set, disposition-code accuracy ≥ the target threshold and summaries contain the required facts (intent, outcome, amounts, next steps) — checked by assertions on seeded conversations.
* CRM note and follow-up task are written through the connector (CC-20) and visible in Customer 360; re-running wrap-up is idempotent.
* ACW dashboard shows baseline vs auto-wrap-up seconds, edit rate and estimated hours saved (feeds CC-13).
* QA flags (e.g., possible compliance miss, unresolved promise) are raised to CC-10 with evidence.

**Azure services.** *Target:* Azure OpenAI (summarisation), Azure AI Language (conversation summarisation, PII), Dynamics 365 Customer Service / Dataverse, Event Grid. *Deployed slice:* LLM summarisation in the app, mock CRM notes/tasks via the connector interface.

**Reference scope & simulated.** Real: generation, taxonomy, metrics. Simulated: the downstream CRM (mock).

**Dependencies.** CC-04, CC-10, CC-13, CC-20.

---

### Epic C — Quality, compliance, insight

#### CC-10 · 100 % Auto-QA `P0`
**PRD:** FR-C01, FR-C02 · **KPIs:** KPI-08, KPI-06, KPI-12, KPI-14

**Why / problem.** Manual QA reviews 1–3 % of contacts, is slow, and is inconsistent between reviewers. Problems are found weeks later, from a tiny sample. AI agents also need QA — they are the highest-volume "employees".

**Description.** Every conversation — human and AI — is scored against a **rubric** (greeting/identification, empathy, accuracy, policy adherence, resolution, compliance, clarity/tone) with **evidence snippets** (turn references and quotes) and **auto-fail** rules for compliance breaches. A **human calibration workflow** lets QA analysts re-score a sample and see agreement metrics; **coaching suggestions** are generated per agent (for the AI agent: prompt/knowledge fixes feeding CC-17); QA dashboards show distributions, trends and outliers.

**Acceptance criteria**
* 100 % of completed conversations receive a QA record (coverage KPI shown); scoring completes within a configurable SLA (default ≤ 5 min after conversation end).
* On a **labelled transcript set**, auto-QA agreement with the reference scores is above the target (e.g., ≥ 85 % within ± 1 band; κ reported); evidence snippets **exist in the transcript** for every non-perfect dimension (asserted).
* Calibration workflow: analyst opens a scored conversation, overrides dimension scores, the system records the delta, updates agreement metrics and can flag drift.
* Compliance auto-fail: a seeded conversation lacking the AI disclosure or containing a risky promise is auto-failed with evidence.
* Coaching: per-agent (human and AI) top-3 suggestions are generated from recurring low-scoring dimensions.

**Azure services.** *Target:* Azure OpenAI (reasoning model, structured outputs), Azure AI Language, Fabric Real-Time Intelligence + OneLake + Power BI for QA analytics, Event Hubs. *Deployed slice:* LLM scoring in the app, results in Cosmos DB, dashboards in the SPA.

**Reference scope & simulated.** Real: scoring, evidence, calibration, dashboards. Simulated: none (calibration labels are synthetic).

**Dependencies.** CC-09, CC-11, CC-13, CC-17 (feedback to prompts).

---

#### CC-11 · Compliance & risk guard `P0`
**PRD:** FR-C03, FR-C04 · **KPIs:** KPI-12, KPI-13

**Why / problem.** A conversational agent with tools is an attack surface: prompt injection, data leakage, toxic outputs, and over-promising ("guaranteed refund") are brand and regulatory risks that must be controlled *by design* and proven by tests.

**Description.** A guard layer on every input and output: **PII redaction** (rules with checksum validation for card/IBAN + Azure AI Language PII), **prompt-injection/jailbreak defences** (Azure AI Content Safety **Prompt Shields** for user prompts and documents, plus input/output validation), **toxicity filters**, **required-disclosure checks**, **risky-promise detection**, **retention policies** (TTL/purge by data class, legal hold), a tamper-evident **audit log**, and a **red-team regression pack** run in CI.

**Acceptance criteria**
* **PII/PCI golden tests:** card numbers, IBANs, e-mail addresses and phone numbers are redacted in transcripts, logs and LLM context; checksum-valid PANs are always caught (including spoken digits and split formats in the test set).
* **Prompt-injection pack** (seeded attacks in user text *and* inside KB documents / tool results) never triggers a forbidden tool call or policy bypass (must-pass = 100 %).
* Risky-promise and missing-disclosure detectors flag seeded violations with evidence and block or rewrite the output; false-positive rate on benign set is reported.
* Toxic/harassing customer input is handled safely (de-escalation or human routing) and abusive agent output is blocked.
* Retention job purges expired records per policy and is audited; the audit log is append-only and hash-chained (tamper test fails when a record is altered).

**Azure services.** *Target:* Azure AI Content Safety (Prompt Shields, text moderation, groundedness), Azure AI Language PII, Microsoft Purview, Defender for Cloud, Key Vault, Cosmos DB TTL/Storage lifecycle policies. *Deployed slice:* rules + Language PII + Content Safety via the AIServices account, TTL policies in Cosmos DB, audit collection.

**Reference scope & simulated.** Real: guard layer and tests. Simulated: none.

**Dependencies.** Cross-cutting: CC-01…CC-05, CC-08, CC-10, CC-16 (red-team pack), CC-21.

---

#### CC-12 · Voice-of-customer analytics `P1`
**PRD:** FR-C05, FR-C06 · **KPIs:** KPI-17, KPI-05, KPI-06

**Why / problem.** Contact centers sit on the richest customer-insight dataset in the company but only see it through disposition codes. Contact *drivers* (why customers call) are the cheapest way to reduce volume at the root.

**Description.** **Topic/intent discovery** by embedding clustering of conversation summaries, **sentiment/emotion trends**, a **contact-driver Pareto**, **repeat-contact and churn-risk signals**, and **emerging-issue alerts** from anomaly detection on topic volumes (e.g., "damaged on delivery" spiking for one carrier). Dashboards for CX leads and operations.

**Acceptance criteria**
* Clustering of the seeded corpus yields topics that match the planted drivers (e.g., ≥ 80 % purity); each topic has an LLM-generated label, volume, sentiment and example conversations.
* The **planted spike** ("damaged on delivery" for one carrier over a week) is detected by the anomaly detector and surfaced as an alert with the carrier attribution and a link to evidence conversations; a no-spike control produces no alert.
* Repeat-contact (same customer + intent within 7 days) and churn-risk indicators are computed and shown per topic.
* Pareto view ranks contact drivers by volume and by cost (handling minutes × cost per minute).
* All dashboards load from stored aggregates in ≤ 2 s on the seeded dataset.

**Azure services.** *Target:* Event Hubs → Fabric Real-Time Intelligence (Eventhouse/KQL anomaly detection), OneLake, Power BI, Azure OpenAI embeddings, Azure AI Language key phrases. *Deployed slice:* in-process clustering and anomaly detection over Cosmos DB aggregates; SPA dashboards.

**Reference scope & simulated.** Real: clustering, anomaly detection, dashboards. Simulated: historical volume (seeded 90-day synthetic history).

**Dependencies.** CC-09, CC-10, CC-13.

---

#### CC-13 · CX metrics & ROI view `P0`
**PRD:** FR-C07, FR-C08 · **KPIs:** KPI-01, KPI-02, KPI-03, KPI-05, KPI-06, KPI-07, KPI-11

**Why / problem.** The buyer (COO/CFO) must see the effect on cost-to-serve and customer outcomes in the same screen — and be able to challenge the numbers.

**Description.** Operational metrics — containment, **verified resolution**, AHT, FCR, predicted CSAT, **cost per contact and per resolved contact**, deflection, SLA, abandon — with **AI-vs-human comparison**, per queue and interval. A **ROI & Azure-ACR calculator** that **vendors `business-case/model.py` and `assumptions.json`** and lets the user change the key drivers (agents, contacts, voice/digital mix, cost per contact, containment, AHT reduction, attrition, QA coverage, discount rate, ramp) with Conservative/Base/Upside scenarios and a tornado.

**Acceptance criteria**
* Metrics are computed from stored interaction records (not hard-coded) and reconcile: containment ≥ verified resolution; counts add up across queue/interval roll-ups (asserted).
* AI-vs-human view shows cost per contact **and per resolved contact** with the Azure metering from CC-22 included in the AI cost.
* The calculator reproduces `business-case/outputs.json` (Base) **within 0.5 %** for NPV, ROI %, payback months and Year-3 ACR (unit test + smoke check).
* Changing an input (e.g., containment 30 % → 20 %) updates NPV, payback, ACR and the tornado without a page reload; scenario toggle switches Conservative/Base/Upside.
* A visible footnote states the model basis (list prices, retrieval date, "illustrative — validate with customer data").

**Azure services.** *Target:* Fabric/Power BI semantic model over OneLake, Event Hubs, Azure Monitor. *Deployed slice:* metrics from Cosmos DB, vendored `model.py` served by the app, SPA charts.

**Reference scope & simulated.** Real: metric computation, calculator. Simulated: baseline human-contact history (seeded).

**Dependencies.** CC-09, CC-10, CC-22; `business-case/`.

---

### Epic D — Operations & LLMOps

#### CC-14 · Workforce forecasting & staffing `P1`
**PRD:** FR-D01, FR-D02 · **KPIs:** KPI-15, KPI-11, KPI-07

**Why / problem.** Retail demand is peaky (promotions, delivery failures, seasonality). Under-staffing wrecks service level; over-staffing burns cost. AI containment changes the shape of human demand and makes static staffing rules obsolete.

**Description.** Interval **volume forecast** per queue (seasonal-naive baseline, Holt-Winters/exponential smoothing with daily and weekly seasonality), **Erlang-C staffing** (service-level target, shrinkage, occupancy cap), an **AI-vs-human capacity plan** with **containment what-ifs**, and a **schedule recommendation** (shift templates covering the requirement). **Backtests report MAPE.**

**Acceptance criteria**
* **Erlang-C** implementation numerically matches published reference values (table-driven test, agents required for given volume/AHT/service level; tolerance ≤ 1 agent / 0.1 % on probabilities).
* Forecast **MAPE** on the seeded seasonal series is below the target threshold and better than the seasonal-naive baseline; backtest report is shown per queue.
* Moving the **containment slider** (0–60 %) changes the human requirement per interval and total FTE; the output also shows AI capacity (concurrent AI sessions, voice minutes) so Azure capacity planning is visible.
* The recommended schedule meets the SLA target in a **discrete-event simulation** of the forecast demand (asserted).
* Forecast and plan are exportable (CSV) and feed CC-13.

**Azure services.** *Target:* Fabric (notebooks/Eventhouse), Azure Machine Learning or Fabric Data Science for forecasting models, Power BI, WFM/CCaaS APIs. *Deployed slice:* pure-Python forecasting/Erlang-C modules, seeded history in Cosmos DB, SPA planner.

**Reference scope & simulated.** Real: algorithms and planner. Simulated: historical demand (seeded).

**Dependencies.** CC-13, CC-15.

---

#### CC-15 · Supervisor console `P0`
**PRD:** FR-D03 · **KPIs:** KPI-11, KPI-09, KPI-06

**Why / problem.** Supervisors manage by exception. With AI handling most contacts they need one live view of **AI + human** work, risk and SLA — and levers to intervene.

**Description.** Live **queues** (waiting, longest wait, SLA clock, abandons), **active conversations** (AI and human) with state and sentiment, a **sentiment heat map**, **SLA-risk alerts**, an **AI containment panel**, and interventions: **take over** (AI → human), **whisper** (private note to the agent), **coach** (silent monitor/barge — simulated for voice), **approve/deny** above-cap actions.

**Acceptance criteria**
* The console updates live (WebSocket/SSE) as conversations start, escalate and end in the demo; queue counts and SLA clocks match the router state (asserted).
* An SLA-risk alert fires when a queue's projected wait exceeds threshold and clears when resolved.
* **Take over** moves an active AI conversation to the supervisor/agent with history intact; **whisper** is visible to the agent only and is audited.
* **Approve/deny** of an above-cap refund request (from CC-04) executes or blocks the action and records the decision.
* Role enforcement: only Supervisor/Admin roles can access the console and interventions (CC-21).

**Azure services.** *Target:* Fabric Real-Time Dashboards/Power BI streaming, SignalR/Web PubSub, Job Router state, Teams for expert collaboration. *Deployed slice:* SSE/WebSocket feed from the app, in-app UI.

**Reference scope & simulated.** Real: live views, interventions on chat; voice monitor/barge is simulated in the UI.

**Dependencies.** CC-06, CC-07, CC-04, CC-21, CC-24.

---

#### CC-16 · Evaluation & simulation harness `P0`
**PRD:** FR-D04 · **KPIs:** KPI-16, KPI-13, KPI-12

**Why / problem.** You cannot ship prompt, knowledge or tool changes to a customer-facing agent on vibes. LLM systems need CI-style regression gates, adversarial testing and realistic simulated customers.

**Description.** A library of **synthetic customer personas and scenarios** (scripted + LLM-driven: angry, confused, multilingual, impatient, vulnerable, fraudster, prompt-injector), an **automated runner** that conducts full conversations against a chosen agent configuration, **scoring** (resolution correctness, factual accuracy, policy compliance, safety, tone, efficiency), a **regression suite and CI gate** with thresholds for prompt/KB/tool changes, a **red-team pack**, and **comparison reports** (baseline vs candidate). The *Simulator* agent plays the customers.

**Acceptance criteria**
* The harness runs **≥ 30 scripted scenarios end-to-end** (offline deterministic stub *and* optionally live models), producing a scored JSON + HTML/markdown report.
* The **CI gate fails** (non-zero exit) when a **deliberately broken prompt** is injected (e.g., removes the refund cap rule) — tested in CI and shown in the UI.
* Red-team pack (≥ 40 cases covering injection, data exfiltration, policy bypass, toxicity, jailbreak) must-pass cases = 100 %.
* Comparison report shows deltas per metric between two agent configs and flags regressions beyond tolerance.
* Harness is callable from the UI (run, view report) and from CLI (`scripts/` entry point) with the same code path.

**Azure services.** *Target:* Azure AI Foundry evaluations (built-in evaluators, red-teaming agent), Azure DevOps/GitHub Actions gates, Azure OpenAI as simulated customers. *Deployed slice:* in-app harness (stub + Azure OpenAI), results stored in Cosmos DB.

**Reference scope & simulated.** Real: harness, scoring, gates. Simulated: customers (by design).

**Dependencies.** CC-01…CC-04, CC-11, CC-17.

---

#### CC-17 · Prompt/policy/knowledge management & staged rollout `P1`
**PRD:** FR-D05 · **KPIs:** KPI-16, KPI-01

**Why / problem.** Prompts, policies and knowledge are production code. Without versioning, canaries and one-click rollback, every change is a risk and nobody can say why resolution changed last Tuesday.

**Description.** **Versioned agent configurations** (prompts, tools, policies, model deployments, KB version), a change workflow (draft → eval gate → canary % → promote), **A/B comparison** on live metrics, **one-click rollback**, and a full **audit trail** (who changed what, when, diff, eval result).

**Acceptance criteria**
* A config version is immutable once published; a diff view shows prompt/tool/policy changes between versions.
* Promotion requires a **passing eval run** (CC-16) for the candidate version — promotion is blocked otherwise (tested).
* **Canary %** routes the configured share of new conversations (deterministic hash) to the candidate; metrics are split by version (resolution, escalation rate, cost per resolved contact, QA score).
* **Rollback** restores the previous version for new conversations within seconds; in-flight conversations finish on their version; the action is audited.
* All changes appear in the audit trail with actor, timestamp, diff and linked eval report.

**Azure services.** *Target:* Azure App Configuration (feature flags/targeting), Foundry prompt/agent versioning, Azure DevOps/GitHub environments, Azure Monitor. *Deployed slice:* config store in Cosmos DB with in-app rollout logic.

**Reference scope & simulated.** Real: versioning, gating, canary, rollback. Simulated: none.

**Dependencies.** CC-16, CC-03, CC-13, CC-21.

---

#### CC-18 · Proactive & outbound engagement `P2`
**PRD:** FR-D06 · **KPIs:** KPI-06, KPI-07, KPI-12

**Why / problem.** The cheapest contact is the one you prevent: telling a customer *before* they call that a delivery is late. Outbound is also where compliance risk is highest (consent, quiet hours, opt-out).

**Description.** **Event-triggered outreach** (shipment delay, payment due, appointment reminder), **callback scheduling**, **consent and opt-out** enforcement per channel, **quiet-hours** and frequency caps by recipient time zone/jurisdiction, and **campaign controls** (pause, caps, audit). Outbound messages are generated by the same agent with the same guard layer.

**Acceptance criteria**
* A simulated "shipment delayed" event triggers an outreach to every affected customer **with valid consent**, none without; opted-out customers are never contacted (tested).
* **Quiet hours** (per recipient time zone) defer sends; frequency caps stop over-contact; deferrals are logged.
* A customer can reply to the outreach and continue in the same conversation (context preserved) or request a **callback** that is scheduled and visible to WFM/supervisor.
* Campaign controls (pause/resume, cap, kill-switch) take effect within seconds; every outreach decision is audited with the consent evidence used.
* Outbound voice is **not placed on any PSTN** in the demo; it is simulated (web/voice session or log) behind the same interface.

**Azure services.** *Target:* outbound channels through Dynamics 365 Contact Center or partner CPaaS (SMS, WhatsApp, e-mail, outbound voice; the Azure Communication Services equivalents are being retired on 30 Sep 2028), Event Grid, Azure Functions/Logic Apps for triggers, Azure OpenAI. *Deployed slice:* in-app event trigger + simulated channel outbox.

**Reference scope & simulated.** Real: triggers, consent logic, scheduling. Simulated: actual message/call delivery.

**Dependencies.** CC-01, CC-05, CC-11, CC-14, CC-20.

---

### Epic E — Platform

#### CC-19 · Multilingual & accessibility `P1`
**PRD:** FR-E01, FR-E02 · **KPIs:** KPI-19, KPI-01, KPI-06

**Why / problem.** Eight markets mean eight (or more) languages, each too small to staff well 24/7. Accessibility is both a legal requirement and a market-size issue.

**Description.** Per-utterance **language detection**, **40+ languages** in chat and voice (quality-evaluated on the eight Contoso markets: EN, DE, FR, ES, IT, NL, PL, PT; others best-effort), **real-time translation** for human agents (customer language ↔ agent language, side-by-side), **captions and transcripts** for voice, and an **accessible UI** targeting **WCAG 2.1 AA** (keyboard, contrast, ARIA, focus, reduced motion).

**Acceptance criteria**
* Language detection ≥ the target accuracy on the multilingual seed set; the agent answers in the detected language and switches when the customer switches.
* Human console shows the customer message in its original language **and** the agent's language; the agent's reply is translated back (round-trip test on seeded phrases).
* Voice and chat both produce **live captions/transcripts**; transcripts are downloadable.
* Automated accessibility checks (axe-core or equivalent) report **no critical/serious violations** on the main screens; keyboard-only completion of the chat journey is verified in a Playwright test.
* The evaluated-language list and per-language eval scores are shown in the UI (honest coverage statement).

**Azure services.** *Target:* Azure OpenAI multilingual models, Azure AI Speech (STT/TTS locales, language identification), Azure AI Translator, Azure AI Language. *Deployed slice:* multilingual LLM/realtime model + Speech via AIServices.

**Reference scope & simulated.** Real: detection, translation, captions, a11y checks. Honest limit: voice quality per language varies; only evaluated languages are claimed. **Polish (`pl`) is evaluated end to end** (Phase 1): a 31-scenario Polish pack on the real model (29/31 = 93.5 %, policy and safety 1.00), Polish PII / PESEL checksums, Polish knowledge base, Polish Auto-QA with verified quotes, Polish Realtime voice (disclosure verified by the relay) and a Polish UI; the EUR ⇄ PLN rate used for the policy caps is a fixed demo constant (1 EUR = 4.30 PLN).

**Dependencies.** CC-01, CC-02, CC-08, CC-24.

---

#### CC-20 · Customer 360 & CRM integration layer `P1`
**PRD:** FR-E03 · **KPIs:** KPI-01, KPI-05, KPI-07

**Why / problem.** AI agents are only as good as the systems they can read and write. Enterprises will not rip out CRM/OMS; the integration layer is what makes the swarm deployable next to existing systems.

**Description.** A **connector abstraction** (`CustomerRecordConnector`/`OrderConnector`/`CaseConnector`) with a mock CRM/OMS implementation, **adapters** for **Dynamics 365 / Dataverse** (Web API/OData) and a **generic REST/OData connector** (config-driven field mapping), tested against mocked HTTP, and a **customer timeline** (orders, contacts, cases, sentiment, AI and human interactions).

**Acceptance criteria**
* All back-office tools (CC-04) and wrap-up writes (CC-09) go through the connector interface — swapping the connector implementation needs no tool changes (contract test suite runs against mock, Dataverse and generic REST adapters).
* The Dynamics 365/Dataverse adapter correctly builds OData queries/payloads (account/contact/incident/case notes) and handles paging, auth header, 4xx/5xx and throttling (429 retry-after) — verified with recorded/mocked HTTP.
* The generic connector maps arbitrary JSON fields via configuration and passes the same contract tests.
* Customer 360 shows a merged, time-ordered timeline for a customer, with PII masking by role (CC-21).
* Connector failures degrade gracefully (tool failure path → escalation).

**Azure services.** *Target:* Dynamics 365 Customer Service/Contact Center + Dataverse, Azure API Management, Azure Logic Apps/Functions, Salesforce/ServiceNow connectors (Release 2), Fabric/OneLake for 360 analytics. *Deployed slice:* mock CRM/OMS in Cosmos DB behind the connector interface; adapters unit-tested against mocked HTTP.

**Reference scope & simulated.** Real: abstraction, adapters, timeline. Simulated: the external CRMs (mock HTTP only; no tenant connection).

**Dependencies.** CC-04, CC-09, CC-21.

---

#### CC-21 · Security, identity, RBAC `P1`
**PRD:** FR-E04 · **KPIs:** KPI-12, KPI-18

**Why / problem.** Transcripts and customer records are sensitive; supervisors, QA analysts and auditors need different access. Enterprise buyers will ask for roles, audit and Entra integration before anything else.

**Description.** Roles — **Customer, Agent, Supervisor, QA, WFM, Admin, Auditor** — enforced at the API; **Entra-ready JWT validation** (issuer, audience, signature via JWKS, expiry, role claims) with a **demo role switcher** for the sandbox; **data-retention** policies and an **access audit** of who viewed which transcript/record.

**Acceptance criteria**
* Role/permission matrix tests assert allowed/forbidden calls for every role across the main API groups (default deny).
* JWT validation rejects tokens with wrong issuer/audience, bad signature, expired, or missing role claims, and accepts a correctly formed Entra-style token (tested with locally generated keys/JWKS).
* The demo role switcher is clearly labelled "demo authentication" and disabled by a configuration flag for real deployments; enabling Container Apps built-in Entra auth is documented.
* Access to a transcript/record by Agent/Supervisor/QA/Auditor is written to the access-audit log; the Auditor role can query it (read-only).
* Retention settings per data class are enforced (see CC-11 job) and visible in settings.

**Azure services.** *Target:* Microsoft Entra ID (workforce) and Entra External ID (customers), Conditional Access, Managed identities, Key Vault, Purview, Defender for Cloud. *Deployed slice:* managed identity + RBAC to Azure resources; in-app role model with Entra-ready JWT validation; demo role switcher.

**Reference scope & simulated.** Real: authorisation, JWT validation, audit. Simulated: user directory (demo users).

**Dependencies.** Cross-cutting.

---

#### CC-22 · Observability & FinOps `P1`
**PRD:** FR-E05 · **KPIs:** KPI-18, KPI-10, KPI-07

**Why / problem.** AI cost is variable and invisible unless metered per interaction. Operations needs latency SLOs for a product where 500 ms is the difference between natural and broken.

**Description.** **OpenTelemetry → Application Insights** (traces, metrics, structured logs), per-interaction **metering** of tokens, audio minutes and tool calls with a **$ estimate** and **cost per resolved contact**, latency SLOs (**time-to-first-token**, **voice turn latency**), SLO burn display, health endpoints (`/healthz`, `/readyz`), request IDs, PII-redacted logs.

**Acceptance criteria**
* Every interaction records tokens (in/out/cached), audio seconds, tool calls and an estimated cost using the unit prices from `business-case/assumptions.json`; metering completeness is reported (target 100 %).
* `GET /api/usage` returns the usage meter and **daily budget status**; the daily AI budget cap **fails closed** with a clear UI message (tested).
* SLO panel shows p50/p95 for TTFT and voice turn latency with threshold lines and burn; traces for a voice turn can be followed from the relay to the model.
* `/healthz` is dependency-free; `/readyz` reports Cosmos, Storage and Azure OpenAI status per dependency.
* Logs contain no PII/PCI (golden test over captured logs).

**Azure services.** *Target:* Azure Monitor, Application Insights, Log Analytics, Azure Managed Grafana/Workbooks, Azure Cost Management + budgets, Defender for Cloud. *Deployed slice:* `azure-monitor-opentelemetry` → App Insights + Log Analytics (1 GB/day cap), in-app usage meter and budget cap.

**Reference scope & simulated.** Real: telemetry and metering (cost uses list prices). Simulated: none.

**Dependencies.** All features emit metrics; CC-13 consumes them.

---

#### CC-23 · IaC & deployment `P0`
**PRD:** FR-E06 · **KPIs:** KPI-18, KPI-16

**Why / problem.** A concept that cannot be redeployed from scratch is a prototype, not a product. IaC also encodes the security baseline.

**Description.** **Bicep modules + `azd`** (`azd provision && azd deploy`), **remote image build in ACR** (no Docker daemon), idempotent re-runs, **smoke tests** against the deployed URL, and a documented **teardown**. Governance conventions of the demo subscription (resource-group tagging) are applied; keyless by default (managed identity + RBAC; `disableLocalAuth`, no shared-key access, TLS 1.2+).

**Acceptance criteria**
* `azd up --no-prompt` (or provision + deploy) from a clean environment yields a working URL; re-running is idempotent; outputs contain **URLs only** (no secrets).
* `scripts/smoke_test.py --base-url <url>` runs end-to-end checks against the deployed app (real Azure OpenAI, Cosmos DB, Blob) and prints a PASS/FAIL table; exits non-zero on failure; AI spend per run < US$1.
* IaC scan finds no keys/connection strings in code, env vars or outputs; resources are keyless and tagged per the demo-subscription convention.
* Teardown (`azd down --purge --force` or resource-group delete) removes all resources; documented in the README/report.
* The Container App reaches `minReplicas`/`maxReplicas` limits and the cost guardrails (daily AI budget, Log Analytics cap) are parameterised.

**Azure services.** *Target:* Bicep/azd/GitHub Actions or Azure DevOps with environments, Azure Deployment Stacks, Azure Policy. *Deployed slice:* Bicep + azd, ACR cloud build, Container Apps.

**Reference scope & simulated.** Real. (Demo-only: governance-exemption tags and public network access are a sandbox convention; the production target uses private endpoints and policy-compliant networking — see `ARCHITECTURE.md`.)

**Dependencies.** All.

---

#### CC-24 · Agent Studio UI `P0`
**PRD:** FR-E07 · **KPIs:** KPI-14, KPI-19, KPI-06

**Why / problem.** Every persona in a contact center needs a purpose-built surface; a polished, coherent UI is what makes the platform credible to an executive audience and usable by an agent under pressure.

**Description.** A single SPA containing: **customer widget** (chat + "Call us"), **human-agent console**, **supervisor console**, **QA workbench**, **KB admin**, **evaluation harness UI**, **analytics** (CX metrics, VoC), **WFM planner**, **settings** (config management, roles, retention), **ROI/ACR calculator**, and the **Feature Map** (`/features`). Polished enterprise look, responsive, accessible, with a visible "synthetic data / simulated environment" indicator.

**Acceptance criteria**
* Every Release-1 feature (CC-01…CC-24) has a reachable UI route or an explicit surface, listed on the **Feature Map** from `GET /api/features` with status and link.
* The golden journeys GJ-1 and GJ-2 can be driven entirely from the UI in the Playwright E2E test; screenshots (1600×900) of each main view are produced for the deck (`deck/assets/screens/NN-<view>.png`).
* Layouts are usable from 360 px to 1920 px width; keyboard navigation and visible focus work; automated accessibility checks pass (see CC-19).
* The footer/header shows the synthetic-data indicator and the build/mode (`azure|offline`) from `GET /api/meta`.
* `npm run build` (typecheck) passes; a few UI component tests run in CI.

**Azure services.** *Target:* Static/SPA served from Container Apps or Static Web Apps behind Front Door (+ WAF), Entra login. *Deployed slice:* SPA served by the FastAPI container.

**Reference scope & simulated.** Real UI. Simulated environment indicator shown honestly.

**Dependencies.** All feature APIs.

---

## 4. Release 2+ roadmap (indicative — not a commitment, and not a statement of Microsoft product roadmap)

Release 1 proves every capability end-to-end on the demo slice. Release 2+ closes the gap to a production deployment on a customer's own telephony, systems and landing zone, then differentiates. Sequencing depends on pilot learnings and on the GA status of the Azure services involved.

| ID | Release | Theme | Capability | Extends | Why it matters |
|---|---|---|---|---|---|
| R2-01 | 2 | Telephony | Production PSTN & SIP: SIP trunk / SBC to the **Azure OpenAI Realtime SIP endpoint**, or **Teams Phone Extensibility** / Teams Direct Routing, or Dynamics 365 Contact Center voice; interop with existing CCaaS/PBX (Genesys, NICE, Cisco, Avaya), compliance recording / SIPREC fork, number-porting runbook | CC-02 | The single biggest step from demo to live voice traffic (ACS direct routing is retiring on 30 Sep 2028 — see ADR-02) |
| R2-02 | 2 | Voice | Evaluate the Foundry **Voice Live** API option (integrated VAD, noise suppression, echo cancellation) and **custom neural brand voice** | CC-02, CC-19 | Latency, audio quality and brand consistency |
| R2-03 | 2 | Agents | Orchestration on **Foundry Agent Service** with **MCP tool servers** for back-office systems and a governed tool catalogue | CC-04 | Standard tool plumbing; easier partner extension |
| R2-04 | 2 | Channels | GA messaging: WhatsApp Business, Apple Messages for Business, RCS/SMS with templates and opt-in; **email AI agent** (draft-then-approve, then auto-send for low-risk intents) | CC-01, CC-18 | Meet customers where they are; email is a large, slow channel |
| R2-05 | 2 | Integration | Salesforce, ServiceNow, Zendesk connectors; **Dynamics 365 Contact Center** bidirectional (conversations, presence, cases) | CC-20 | Deploy next to the customer's system of record |
| R2-06 | 2 | Multimodal | Customer **photo/video evidence** for damage and warranty claims (vision), proof-of-delivery and invoice extraction (Document Intelligence) | CC-03, CC-04 | Completes the "damaged sofa" journey without a human |
| R2-07 | 2 | Analytics | Production analytics path: Event Hubs → **Fabric Real-Time Intelligence** → OneLake → Power BI semantic model | CC-12, CC-13 | Enterprise reporting and ad-hoc analysis at 100 % coverage |
| R2-08 | 2 | Security | Landing-zone hardening: Private Link everywhere, Front Door + WAF, APIM, Entra External ID, customer-managed keys, Purview classification | CC-21, CC-23 | Passes enterprise security review |
| R2-09 | 2 | Resilience | **Multi-region active/active voice**, automated failover, chaos drills, DR runbooks | CC-02, CC-22 | Contact centers cannot go dark |
| R2-10 | 2 | Knowledge | **Knowledge operations:** gap detection from unanswered questions and escalations → drafted KB articles with approval; freshness SLAs | CC-03, CC-12 | Resolution rate is limited by knowledge quality |
| R2-11 | 2 | Cost/LLMOps | Eval-driven optimisation: prompt/policy change proposals, **model router** (nano/mini/full), semantic caching | CC-16, CC-17, CC-22 | Cost per resolved contact falls over time |
| R3-01 | 3 | Fraud & identity | Consent-based **voice biometrics**, synthetic-voice/deepfake and fraud signals, risk-based step-up | CC-05 | Raises assurance while reducing friction |
| R3-02 | 3 | CX | **Predictive CSAT** and proactive recovery; retention offers within guardrails | CC-06, CC-13 | Turns contacts into retention |
| R3-03 | 3 | WFM | **Full WFM**: schedule optimisation with preferences and multi-skill pooling, intraday management, adherence, AI headcount planning | CC-14 | Closes the loop from forecast to roster |
| R3-04 | 3 | Collaboration | **Expert swarming via Teams** (pull a back-office SME into a live case), agent-to-agent handoffs | CC-07, CC-15 | Complex cases get resolved in one touch |
| R3-05 | 3 | Outbound | Outbound voice at scale (progressive dialing) with a **jurisdiction rules engine** (consent, quiet hours, caller-ID authentication) | CC-18 | Opens proactive voice safely |
| R3-06 | 3 | Compliance | Vertical packs (financial services, healthcare, public sector) and an **EU AI Act documentation toolkit** | CC-11, CC-21 | Regulated-industry reach |
| R3-07 | 3 | Personalisation | Consented long-term memory and preference centre | CC-20 | Better, shorter conversations |
| R3-08 | 3 | Ecosystem | Partner/ISV **skill marketplace** and SDK for tool packs and industry templates | CC-04, CC-17 | Scales delivery through partners |
| R3-09 | 3 | People | Coaching plans and learning paths from QA signals; agent-wellbeing signals (privacy-preserving) | CC-08, CC-10 | Attrition is a core cost driver |
| R3-10 | 3 | Efficiency | Small/fine-tuned models for classification, QA and PII; edge options | CC-06, CC-10, CC-11 | Lower unit cost, lower latency |
| R3-11 | 3 | Experience | Video/co-browse, visual IVR | CC-01 | Complex product support |
| R3-12 | 3 | Insight | Journey analytics and "deflect-before-contact" analysis across web/app/contact center | CC-12 | Reduces contact demand at the source |

## 5. Requirement and KPI traceability

### 5.1 Functional requirement catalogue (full statements in `PRD.md` §8)

| FR | Requirement (short) | Feature(s) | Priority |
|---|---|---|---|
| FR-A01 | Streaming, multi-turn, multilingual chat with persistent session memory | CC-01 | P0 |
| FR-A02 | Channel-adapter abstraction (web chat, webhook; SMS/WhatsApp/email stubs) | CC-01 | P0 |
| FR-A03 | Real-time speech-to-speech voice with server VAD, barge-in, live transcript and in-session tool calls | CC-02 | P0 |
| FR-A04 | Voice resilience: STT→LLM→TTS fallback; telephony adapter contract (ACS Call Automation) | CC-02 | P0 |
| FR-A05 | KB ingestion, hybrid retrieval with citations, KB versions and publish | CC-03 | P0 |
| FR-A06 | Groundedness verification and "don't know → escalate" | CC-03 | P0 |
| FR-A07 | Policy-guarded transactional tools (confirmation, idempotency, caps, audit, allow-lists) | CC-04 | P0 |
| FR-A08 | Identity verification (OTP/KBA) and step-up | CC-05 | P0 |
| FR-A09 | AI disclosure, recording consent, PII minimisation, PCI-safe payment hand-off | CC-05 | P0 |
| FR-B01 | Intent, entity, sentiment/emotion, urgency and risk-flag extraction | CC-06 | P0 |
| FR-B02 | Skills/priority/SLA routing (Job Router semantics) and explicit escalation triggers | CC-06 | P0 |
| FR-B03 | Warm handoff with real-time context package | CC-07 | P0 |
| FR-B04 | Agent Assist: live transcript, next-best-action, cited suggestions, compliance reminders | CC-08 | P0 |
| FR-B05 | Human-agent console: takeover, knowledge search, form auto-fill, tone coaching | CC-08, CC-24 | P0 |
| FR-B06 | Auto wrap-up: summary, disposition, CRM notes, follow-ups, QA flags, ACW measurement | CC-09 | P0 |
| FR-C01 | Rubric-based scoring of 100 % of conversations with evidence | CC-10 | P0 |
| FR-C02 | QA calibration, coaching suggestions and dashboards | CC-10 | P0 |
| FR-C03 | PII redaction, prompt-injection/jailbreak and toxicity defences | CC-11 | P0 |
| FR-C04 | Disclosure and risky-promise detection, retention, audit log, red-team pack | CC-11 | P0 |
| FR-C05 | VoC topic discovery, sentiment trends, driver Pareto, repeat/churn signals | CC-12 | P1 |
| FR-C06 | Emerging-issue alerts from anomaly detection | CC-12 | P1 |
| FR-C07 | CX metrics with AI-vs-human comparison, cost per (resolved) contact | CC-13 | P0 |
| FR-C08 | ROI & ACR calculator reproducing the business-case model | CC-13 | P0 |
| FR-D01 | Interval volume forecasting with backtests (MAPE) | CC-14 | P1 |
| FR-D02 | Erlang-C staffing, AI-vs-human capacity plan, containment what-ifs, schedule recommendation | CC-14 | P1 |
| FR-D03 | Supervisor live console with interventions | CC-15 | P0 |
| FR-D04 | Evaluation & simulation harness with CI gate and red-team pack | CC-16 | P0 |
| FR-D05 | Versioned configs, canary/A-B, rollback, audit | CC-17 | P1 |
| FR-D06 | Proactive and outbound engagement with consent, quiet hours, callbacks | CC-18 | P2 |
| FR-E01 | Multilingual detection/generation (40+ languages) and agent-side translation | CC-19 | P1 |
| FR-E02 | Accessibility (WCAG 2.1 AA targets) and captions/transcripts | CC-19, CC-24 | P1 |
| FR-E03 | CRM/OMS connector layer, Dynamics 365 and REST/OData adapters, customer 360 | CC-20 | P1 |
| FR-E04 | Roles, JWT validation (Entra-ready), retention and access audit | CC-21 | P1 |
| FR-E05 | Observability, per-interaction metering, cost per resolved contact, SLOs | CC-22 | P1 |
| FR-E06 | IaC, remote build, smoke tests, teardown | CC-23 | P0 |
| FR-E07 | Agent Studio UI for all personas | CC-24 | P0 |

Non-functional requirements (`NFR-01 … NFR-12`; targets in `PRD.md` §9): NFR-01 voice latency · NFR-02 text/assist latency · NFR-03 concurrency & elasticity · NFR-04 availability & resilience · NFR-05 accessibility · NFR-06 security · NFR-07 privacy & data residency · NFR-08 safety & responsible AI · NFR-09 observability & auditability · NFR-10 cost efficiency · NFR-11 maintainability & testability · NFR-12 interoperability.

### 5.2 Traceability matrix (feature → requirement → KPI)

| Feature | Functional requirements | Non-functional | KPIs moved |
|---|---|---|---|
| CC-01 Omnichannel chat agent | FR-A01, FR-A02 | NFR-02, NFR-03, NFR-12 | KPI-01, 02, 06, 07, 11 |
| CC-02 Real-time voice agent | FR-A03, FR-A04 | NFR-01, NFR-03, NFR-04, NFR-12 | KPI-01, 02, 07, 10, 11 |
| CC-03 Knowledge-grounded answers / RAG | FR-A05, FR-A06 | NFR-02, NFR-08 | KPI-01, 12, 13 |
| CC-04 Transactional tools / skills | FR-A07 | NFR-06, NFR-08, NFR-09 | KPI-01, 05, 07, 12 |
| CC-05 Identity verification, consent & disclosure | FR-A08, FR-A09 | NFR-06, NFR-07, NFR-08 | KPI-01, 06, 12 |
| CC-06 Intent/sentiment/urgency understanding & smart routing | FR-B01, FR-B02 | NFR-02, NFR-09, NFR-12 | KPI-05, 06, 09, 11 |
| CC-07 Warm handoff with context package | FR-B03 | NFR-02, NFR-07 | KPI-03, 06, 09 |
| CC-08 Agent Assist copilot | FR-B04, FR-B05 | NFR-02, NFR-08 | KPI-03, 05, 12, 14 |
| CC-09 Auto wrap-up | FR-B06 | NFR-09, NFR-12 | KPI-03, 04, 14 |
| CC-10 100 % Auto-QA | FR-C01, FR-C02 | NFR-03, NFR-08, NFR-09 | KPI-06, 08, 12, 14 |
| CC-11 Compliance & risk guard | FR-C03, FR-C04 | NFR-06, NFR-07, NFR-08 | KPI-12, 13 |
| CC-12 Voice-of-customer analytics | FR-C05, FR-C06 | NFR-03, NFR-07 | KPI-05, 06, 17 |
| CC-13 CX metrics & ROI view | FR-C07, FR-C08 | NFR-09, NFR-10 | KPI-01, 02, 03, 05, 06, 07, 11 |
| CC-14 Workforce forecasting & staffing | FR-D01, FR-D02 | NFR-03 | KPI-07, 11, 15 |
| CC-15 Supervisor console | FR-D03 | NFR-02, NFR-06 | KPI-06, 09, 11 |
| CC-16 Evaluation & simulation harness | FR-D04 | NFR-08, NFR-11 | KPI-12, 13, 16 |
| CC-17 Prompt/policy/knowledge management & staged rollout | FR-D05 | NFR-08, NFR-11 | KPI-01, 16 |
| CC-18 Proactive & outbound engagement | FR-D06 | NFR-07, NFR-08 | KPI-06, 07, 12 |
| CC-19 Multilingual & accessibility | FR-E01, FR-E02 | NFR-05, NFR-12 | KPI-01, 06, 19 |
| CC-20 Customer 360 & CRM integration layer | FR-E03 | NFR-06, NFR-12 | KPI-01, 05, 07 |
| CC-21 Security, identity, RBAC | FR-E04 | NFR-06, NFR-07, NFR-09 | KPI-12, 18 |
| CC-22 Observability & FinOps | FR-E05 | NFR-04, NFR-09, NFR-10 | KPI-07, 10, 18 |
| CC-23 IaC & deployment | FR-E06 | NFR-04, NFR-06, NFR-11 | KPI-16, 18 |
| CC-24 Agent Studio UI | FR-E02, FR-E07 | NFR-02, NFR-05, NFR-11 | KPI-06, 14, 19 |

### 5.3 Coverage check

* Every FR appears in at least one feature row; every Release-1 feature appears in at least one FR row; every KPI (01–19) is moved by at least one feature.
* **Change control:** reducing the scope of a Release-1 feature is not allowed silently — record the reason and the evidence in the `Evidence` cell and in the engineering report; never delete a row or rename a feature.

