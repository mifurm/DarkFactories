# PHASE 1 — Concierge backend (Polish localization): DONE

Owner: cc-be-pl2 (resumed run). Scope: `app/src/**`, `app/tests/**` (not `tests/e2e`), `scripts/**`, seeds, `README.md`, `REPORT-TEST-AND-DEPLOYMENT.md`, `FEATURES.md`, `ARCHITECTURE.md`, `app/evidence/**`.
Files outside this scope touched: **none** (`tests/test_voice.py` is a backend test; its fake realtime server got an optional `greetings` parameter, default behaviour unchanged).
Not done by design: no deployment, no `az login`, nothing pointed at the live Cosmos DB / Blob.

## What changed

* **Locale contract** (`core/i18n.py`, `core/errors.py`, `main.py`): `?lang=` → `X-UI-Lang` → `Accept-Language` → `en`; `Content-Language` / `Vary`; SSE and WebSocket `?lang=`; `/api/meta` → `languages`, `default_language`, `language`, `language_names`;
  error bodies keep `detail` / `error` and add `code`, localized `message` / `hint` (+ `errors[]` for 422); message catalogs `core/catalog_en.py` = `core/catalog_pl.py` (382 keys, parity tested). An **omitted** `language` in the chat / voice / text-turn / KB-ask / output-check bodies follows the request locale (explicit wins).
* **Understanding and safety**: `engine/lexicon_pl.py`, `core/textutil.py` (`fold`, ł/Ł), `core/langid.py` (pl vs cs / sk / ru), `core/redaction.py` (PESEL, NIP, REGON-9/14, dowód, NRB with checksums, Polish phones, spoken digits), guard (social engineering, risky promises).
* **Money**: `core/money.py` (PLN, `1 599,00 zł`, amounts in words, fixed demo rate **1 EUR = 4.30 PLN**, CLDR plural helpers); Polish-market back office (CU-1009 … CU-1013, CH-1003xx; InPost / DPD Polska / DHL); caps are applied to the EUR equivalent (2 150,00 zł = EUR 500 is still autonomous, 2 150,01 zł needs approval), idempotent.
* **Conversation**: disclosure + recording notice, OTP SMS, confirmations, wrap-up / disposition / CRM note, e-mail, handoff package and escalation reasons, Agent Assist (`engine/plan_text.py`, `engine/localize.py`, `engine/wrapup.py`, `engine/handoff.py`, `features/*`). Customer-facing text follows `conversation.language`; operator text follows the UI locale; persisted records keep `code` + `params` and are rendered at read time.
* **Knowledge and quality**: 50 Polish KB articles (`engine/kb_seed_pl.py`, ids `<id>-pl`), cross-language retrieval, Polish-aware groundedness (`engine/cognitive.py`), Auto-QA with verified Polish quotes, Polish red-team pack (`engine/redteam_pl.py`, 28 attacks), Polish eval pack (`engine/eval_pl.py`, **31 scenarios**: 22 scripted, 3 persona, 6 red-team; suites `pl`, `pl-gate`, `pl-smoke`, `pl-redteam`), KB eval set `POST /api/kb/evalset/run?lang=pl`.
* **Voice**: Realtime session configured for Polish (instructions + language lock + voice guide, `input_audio_transcription.language`), strict word-for-word Polish opening, **disclosure verified and repeated once if the model skipped it (all languages, audit `voice.disclosure_enforced`)**, STT → LLM → TTS fallback with `pl-PL-ZofiaNeural`, Polish caller prompt for +48 numbers in the telephony simulator.
* **Analytics / outbound** (`engine/synth_pl.py`, `engine/history_seed.py`, `engine/voc.py`, `features/{voc,wfm,supervisor,outbound}`): idempotent Polish slice on top of already seeded data (`PL_SLICE_VERSION = "pl1"`, `VOC_VERSION = "v3"`, `HISTORY_VERSION` still `h4`, no wipe), WFM queues `general-pl` / `delivery-pl` in `Europe/Warsaw` with Polish holidays, Polish outbound templates, `POST /api/outbound/replies` (`STOP`, `REZYGNUJĘ`, `WYPISZ MNIE`), quiet hours 21:00–08:00 Warsaw time.
* **Additive API fields** the web already uses: supervisor `heat_map[].label`, handoff `queue_name`, WFM `timezone` / `market`, VoC `clusters[].label_en` / `summary_pl`, CRM 360 `orders[].currency`, handoff `pending_approvals[].currency`, outbound decision `reason_code` / `reason_params`; `GET /api/wfm/forecast` `mape_interval` is `null` (never NaN) for the two small Polish queues.
* **Scripts**: `scripts/dev_hybrid.py` (real Azure AI + in-memory data), `scripts/smoke_test.py` (`--lang en|pl|all`, `--expect-mode hybrid`, steps `PL-1` … `PL-10`), `scripts/eval_gate.py` already knows the Polish suites.

## Tests — how to run everything

```bash
cd 03-ai-contact-center/app
.venv/bin/ruff check src tests                                       # All checks passed
.venv/bin/python -m pytest --ignore=tests/e2e                         # 655 passed (212 English baseline + 443 Polish)
.venv/bin/python ../scripts/eval_gate.py --suite pl-gate              # exit 0 (offline engine, 31/31)
.venv/bin/python ../scripts/eval_gate.py --suite pl-gate --broken no_citations   # exit 1 (also remove_refund_cap, no_tools, always_escalate)
.venv/bin/python ../scripts/dev_hybrid.py --check                     # real AI probes, a few cents
.venv/bin/python ../scripts/dev_hybrid.py &                           # real AI, in-memory data, http://127.0.0.1:8103
.venv/bin/python ../scripts/smoke_test.py --base-url http://127.0.0.1:8103 --expect-mode hybrid --lang all    # 31/31, ≈ US$0.5
```

| Module | Tests | Covers |
|---|---|---|
| `test_pl_understanding.py` | 147 | golden utterances with / without diacritics, intents, risks, sentiment, langid (≥ 30), routing matrix |
| `test_pl_pii_money.py` | 81 | every Polish identifier valid + invalid checksum inside sentences, phones, cards, redaction never leaks, PLN / FX / words / plurals / dates / DST, locale resolution |
| `test_pl_conversation.py` | 29 | PLN back office + upgrade of seeded data, consent, OTP, confirmations, cap boundaries, idempotency, approvals, golden journey, wrap-up, handoff, Agent Assist, slot note, disclosure markers |
| `test_pl_knowledge_quality.py` | 119 | KB parity, retrieval, citations, don't-know, groundedness (real-model outputs as fixtures), risky promises, QA evidence, red team, eval pack + gate that FAILS for broken prompts |
| `test_pl_voice_outbound.py` | 39 | Realtime configured for Polish (fake realtime server), disclosure enforcement, pl-PL pipeline, opt-out, quiet hours |
| `test_pl_contract.py` | 28 | locale order, SSE / WS `?lang=`, error contract, catalog parity, English output unchanged, English seed digests identical, seed idempotence incl. upgrade of seeded data, VoC / WFM / supervisor / CRM localization |

## Real-model verification (hybrid harness; AI spend ≈ US$2.9 of the US$3 cap)

* Polish pack on `gpt-5.4-mini`: **29 / 31 = 93.5 %** in two runs (resolution 0.97–0.98, accuracy 0.95–0.98, **policy 1.00, safety 1.00**); subsets after the fixes 6 / 6 and 10 / 10 (three times). Reports: `app/evidence/eval-pl-hybrid.json`, `eval-pl-hybrid-report.md`.
* Hybrid smoke `--lang all`: **31 / 31** (English US$0.17 + Polish US$0.32): `app/evidence/smoke-hybrid-all.md`.
* Azure Language: `pl` detected 1.00; PII categories incl. `PLNationalID`; Speech `pl-PL-ZofiaNeural` TTS → STT round trip correct.
* Defects found only by the real models and fixed at the root cause (table in `REPORT-TEST-AND-DEPLOYMENT.md` §14.3): groundedness false positives on slot lists and agent-offer sentences; English "Outcome:" in Polish wrap-ups; realtime greeting without disclosure / informal / English filler; informal fallbacks; one escalation instead of a pickup booking (slot-id note, **not re-measured on the real model — budget used up**).

## For the orchestrator (deployment)

* Code-only redeploy. `SEED_ON_START=1` performs the idempotent upgrades on the live data (Polish KB articles, Polish-market back office, Polish history / WFM slice, VoC aggregate `v3`). Wait for `/readyz` = `ready` (the seed finishes ≈ 1–2 min after start; the VoC recompute adds ≈ 70 s on the first VoC call).
* Live cap: raise `AI_DAILY_BUDGET_USD` before the live run (the smoke test needs ≈ US$0.5 for English + Polish; `--lang pl` ≈ US$0.3), as in spec §8; report the value you leave.
* Live smoke: `app/.venv/bin/python scripts/smoke_test.py --base-url <live> --expect-mode azure --lang all --json report.json` — run on 18 Nov 2026: **31 / 31** (`app/evidence/smoke-live-all-pl.txt`; `REPORT-TEST-AND-DEPLOYMENT.md` §14.4).
* English behaviour is unchanged (digest-tested seed data, unchanged English output of every localized endpoint, English smoke steps unchanged). One shared, English-visible change: the Realtime relay now repeats the AI disclosure once when the *real model* skipped it (the offline demo script is untouched), and the Portuguese disclosure is now recognised by `DISCLOSURE_MARKERS`.

## Known gaps / limits

* The EUR ⇄ PLN rate is a fixed demo constant. Static descriptive API texts (identity levels, metric definitions, SLO notes, tool descriptions) stay English in the API — the web dictionary translates them.
* The real model varies (≈ 6 % of the Polish scenarios per run, different ones each time); the last two fixes were verified by unit tests only. Polish realtime wording is only as good as `gpt-realtime-2.1-mini` ("Pan/Pani" is sometimes read literally); the relay enforces disclosure and language, not wording.
* Azure Content Safety groundedness is English-tuned: the verdict needs the Azure flag **and** the Polish-aware local check to agree on the same sentence unless a number / absolute claim is unsupported.
* Offline (hashed-embedding) retrieval misses one of 26 Polish questions (25 / 26 citation accuracy); real-embedding cross-language retrieval is exercised by `PL-5` and the eval pack, not measured as a separate recall figure.
* `ruff check src tests` (it also covers the FE-owned `tests/e2e`) reports "All checks passed" on the final tree.

## Addendum (12:45) — LLM-written Polish operator notes carry no internal codes
FE finding from the live Polish E2E: the LLM hand-off note sometimes ended with the trigger code ("… kroków prawnych (legal_threat)"). Fixed for **Polish only** (English prompts and output unchanged): the Polish hand-off prompt carries the localized trigger reason,
noun phrases for the steps tried and readable speaker labels (`engine/plain_text.py`); both Polish system prompts (hand-off, wrap-up) forbid internal codes; the model's summary / suggested resolution pass through `plain_text.plain()` (parenthesised code removed, known code → Polish phrase, unknown snake_case removed;
order numbers, ids, e-mail addresses, URLs untouched). Tests: `tests/test_pl_plain_text.py` (12). The English twin of the problem is left as is on purpose. On the current shared tree (other agents edited it after this note) `ruff check src tests` is clean and `pytest --ignore=tests/e2e` = 1138 passed.
