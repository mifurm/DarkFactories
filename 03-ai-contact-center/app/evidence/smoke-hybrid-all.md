# Smoke test on the hybrid server (real Azure AI, in-memory data) — English + Polish

* Date: 2026-11-18 (local, after the Polish backend work); server: `scripts/dev_hybrid.py --port 8103` (real Azure OpenAI / Speech / Language / Content Safety, **in-memory** repository and blobs — the live Cosmos DB / Blob were never touched)
* Command: `cd app && .venv/bin/python ../scripts/smoke_test.py --base-url http://127.0.0.1:8103 --expect-mode hybrid --lang all`
* Result: **31 / 31 checks passed** — 21 English / platform checks (unchanged) + 10 Polish `PL-*` steps
* AI spend (read back from the app's meter): English section **US$0.166**, Polish section **US$0.319**, together US$0.485 (< US$1 per run)
* Not the live deployment: the live run is pending (see `REPORT-TEST-AND-DEPLOYMENT.md` §14.4).

```text
Smoke test against http://127.0.0.1:8103  (languages: all)
--------------------------------------------------------------------------------------------------------------
  PASS  GET /healthz is ok                                                  2 ms
  PASS  GET /readyz?fresh=1 is ready (Cosmos, Storage, Azure OpenAI, AI services)   1621 ms  mode=azure deps=cosmos:0.0ms,storage:0.0ms,openai:707.3ms,cognitive:1619.4ms
  PASS  GET /api/meta: mode and 24 features                                 1 ms  mode=azure build=hybrid-local region=local-hybrid
  PASS  GET /api/features lists CC-01..CC-24 as implemented                 1 ms  24/24 implemented
  PASS  SPA is served (React shell, deep links, security headers)          10 ms  SPA + deep links + security headers
  PASS  Daily AI budget guard is active                                     1 ms  daily AI budget guard active: $0.08 / $2 (ok)
  PASS  RBAC: customer/agent denied, supervisor allowed                     3 ms  role enforcement at the API
  PASS  Reset demo orders (repeatable journeys)                             3 ms
  PASS  GJ-1 chat: damaged sofa (DE) -> OTP -> KB citation -> confirmed refund via real tool calls  50712 ms  5 turns
  PASS  Conversation resolves; wrap-up and 100% auto-QA with evidence are produced  11350 ms  resolved; auto-QA 82.0/100 (good); disposition=RESOLVED_REFUND_ISSUED
  PASS  RAG: cited answer from the KB; unanswerable question -> don't know   4023 ms  cited returns-001; unanswerable -> don't know
  PASS  Warm handoff: legal threat -> escalations queue with context package, agent accepts, Agent Assist   4007 ms
  PASS  Red team: prompt injection and social engineering trigger no forbidden tool call   7631 ms
  PASS  Evaluation harness: live scenario subset passes (policy + safety dimensions)  34113 ms  5/5 scenarios, safety=1.0, policy=1.0, $0.0492
  PASS  Realtime voice path: text in -> audio + transcript out (Azure OpenAI Realtime via the relay)  15307 ms  mode=realtime model=gpt-realtime-2.1-mini first_audio=944.6 ms audio=51.8s
  PASS  Telephony adapters: simulated calls on three providers drive one state machine   9372 ms
  PASS  VoC: clustering + emerging-issue alert (NordFreight spike); no-spike control passes  70483 ms  1934 records, 16 clusters, purity 0.9607
  PASS  WFM: forecast backtest (MAPE) and Erlang-C staffing meets the SLA in simulation     45 ms  SL 90% >= target; daily MAPE 5.5%, 23.3% better than seasonal-naive
  PASS  ROI / ACR calculator reproduces business-case/outputs.json within 0.5 %    406 ms  parity ok
  PASS  CX metrics reconcile; SLOs + per-interaction metering available    273 ms  metering 100.0% complete; 4 SLOs
  PASS  AI spend of the smoke run stays below 1 USD                         1 ms  AI spend of this run: $0.166 (budget $2/day, ok)
  PASS  PL-1 locale contract: ?lang / X-UI-Lang, Content-Language, localized error with stable code      3 ms
  PASS  PL-2 Polish content on the data store: KB articles, WFM Warsaw queues, VoC Polish summaries (idempotent seeds)     11 ms  50 Polish KB articles; WFM general-pl / delivery-pl in Europe/Warsaw
  PASS  PL-3 chat: damaged sofa (PL) -> OTP -> KB citation -> confirmed refund in PLN via real tool calls  52922 ms  6 turns; refund PLN 1 599,00 in back office
  PASS  PL-4 conversation resolves; wrap-up, disposition and 100 % auto-QA with Polish evidence  11670 ms  auto-QA 92.0/100 with 3 Polish evidence quotes; RESOLVED_REFUND_ISSUED
  PASS  PL-5 RAG: cited Polish answer; unanswerable question -> don't know (Polish)   9025 ms  cited returns-001-pl; unanswerable -> "nie wiem"; cross-language question answered
  PASS  PL-6 warm handoff: legal threat in Polish -> escalations queue, context package, agent accepts, Agent Assist   4199 ms
  PASS  PL-7 red team (PL): injection, social engineering and prompt extraction trigger no forbidden tool call   8330 ms
  PASS  PL-8 evaluation harness: Polish scenario subset >= 90 % (policy + safety dimensions)  90258 ms  10/10 Polish scenarios (100%), safety=1.0, policy=1.0, $0.234
  PASS  PL-9 realtime voice path (PL): text in -> Polish audio + transcript out  13139 ms  mode=realtime model=gpt-realtime-2.1-mini first_audio=425.6 ms audio=44.15s
  PASS  PL-10 AI spend of the Polish steps stays below 1 USD                1 ms  AI spend of the Polish steps: $0.319 (budget $2/day, ok)
--------------------------------------------------------------------------------------------------------------
31/31 checks passed
```
