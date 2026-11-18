# Phase 1 — Spotlight BACKEND: DONE (cs-be-pl2)

Polish (pl) localization of the Commercial Studio backend, content and AI behaviour is implemented and verified **locally** — offline stubs and the **real Azure AI models on hybrid backends**
(real Azure OpenAI / Content Safety / AI Speech / images, in-memory repository + local blobs; the live Cosmos DB / Blob storage were never touched). The deployed-instance checks were run afterwards by the orchestrator: see `REPORT-TEST-AND-DEPLOYMENT.md` §12 (smoke 44/44 on the deployed app).
English behaviour is unchanged (parity proof below). Budget caps unchanged (daily US$5, per campaign US$2).

## Numbers

| Gate | Result |
|---|---|
| `pytest tests` | **384 passed** = 97 pre-Polish baseline (unchanged) + 287 Polish, 0 failed, ≈ 67 s |
| Coverage | 90 % total (9,496 statements): domain 94 %, i18n 91 %, video 92 %, core 87 %, features 86 % |
| `ruff check src tests ../scripts e2e` / `mypy` | clean / no issues in 42 files |
| `smoke_test.py --lang both` (offline server) | **44/44** (30 English + 14 Polish); `--lang en` 30/30 |
| `smoke_test.py --lang pl` (real models, hybrid) | **17/17** (3 infra + 14 Polish), AI spend **US$0.140**, 2 min 47 s |
| Real-model probe (Guardian LLM rewrite PL, PL→DE, EN→PL) | verified, US$0.059 |
| Cumulative real-model spend of this work | ≈ **US$0.87** (4 Polish smokes ≈ 0.55, 3 probes ≈ 0.23, TTS calibration ≈ 0.08) — budget US$3 |
| Polish 15 s spot | ffprobe h264/aac 1280×720, 14.90 s, −16.0 LUFS (offline and real); frame check: ąćęłńóśźż glyphs + „Wygenerowano przez AI” |
| English parity vs `HEAD` | 83 API responses + 15 LLM prompts compared: 0 unexplained differences, 14/15 prompts byte-identical (the 15th is the intended EN→PL prompt); English captions identical on 1,500 random lines |

Live (deployed) Polish smoke and the FE's live Polish journeys: **done on 18 Nov 2026** (smoke 44/44; see `REPORT-TEST-AND-DEPLOYMENT.md` §12.2 and §12.8). Evidence: `app/evidence/pl-*` (summary in `pl-tests.txt`, live run in `pl-smoke-live.txt`), report: `REPORT-TEST-AND-DEPLOYMENT.md` §12.

## What changed (additive; English paths identical)

* **New:** `src/spotlight/i18n/` (locale middleware + context, catalogs `messages_en|pl` ≈ 600 keys each with parity test, CLDR plurals, pl-PL formats, LLM output-language directive, localized validation errors),
  `domain/pl_morph.py` (stem + ending classes, per-form replacements), `domain/polish.py` (numbers/units/dates as words for the voice, typography, brand respelling), `domain/kit.py`,
  `seed/pl_claims.py` (15 `clm-pl-*` rules), `core/ai/safety_rules.py` (Polish Content-Safety word lists + prompt-injection pre-check), 8 `tests/test_pl_*.py`, `scripts/smoke_test.py` Polish steps,
  `scripts/calibrate_tts.py` (reproducible speaking-model calibration against a real neural voice).
* **Contract:** locale middleware (`?lang` → `X-UI-Lang` → `Accept-Language` → `en`), `/api/meta` `languages` / `default_language` / `language`, `Content-Language`, `campaign.language`, localized `message`/`hint` with stable `error.code`.
* **Read-time rendering** (stored as code + params): Guardian findings, timing/voice warnings, audit `message`, jobs (title/message/error, SSE), approvals `stage_label`/`state_label`, notifications/webhooks, team, scorecard tips, insights, cost/ROI/ops notes,
  format-version notes, provenance summary, rights/claims labels. Signed manifest and audit hash chain untouched.
* **Content (seed `2026.11.2`, upsert only, deterministic ids):** Polish Brand Book + kit (tagline „Obudź się powoli.”), 15 claim rules, rights notes/labels, sample campaign `dawn-roast-premiera-pl` („Dawn Roast — premiera w Polsce”, market PL).
* **AI behaviour:** Polish-first pipeline (brief → strategy → 6/15/30 s scripts → storyboard (Polish text, English image prompts) → `pl-PL` VO → captions/end card/badge → formats), Guardian in Polish (inflection-aware, diacritic-insensitive, negative controls),
  auto-revise to compliant Polish, bidirectional localization with glossary / do-not-translate / back-translation QA (Polish stems), scorecard/variants/insights/planner in Polish.
* **Real-model driven fixes:** neural-voice padding removed with SSML `mstts:silence` + trim; speaking model calibrated on 24 real `pl-PL-ZofiaNeural` lines (5.4 syll/s, 0.6 s sentence pause, 0.35 s comma, RMSE 10 %; reproducible with `scripts/calibrate_tts.py`); trim/rebalance never drops the tagline or a mandatory;
  `WORK_DIR` created on demand; digits-not-words directive; captions: sentence- and comma-aware, balanced, no one-word cue.

## Coverage matrix (spec §4 traps and §6 bullets → file → proof)

| § | Item | Implemented in | Proven by |
|---|---|---|---|
| 4.1 | ł/Ł folding | `domain/text.py` `fold`, `util.slugify` | `test_pl_i18n` (fold, slugs) |
| 4.2 | Inflection | `domain/pl_morph.py`, `seed/pl_claims.py` | `test_pl_guardian` (34 positives, agreement of replacements) |
| 4.3 | No-diacritics input | every pattern runs on `fold()` | `test_pl_guardian` (each positive/negative also without diacritics), `detect_lang` golden set |
| 4.4 | Plurals / numbers / money | `i18n/plural.py`, `i18n/fmt.py`, `domain/polish.py` | `test_pl_i18n`, `test_pl_voice_timing` |
| 4.5 | Dates / times | `i18n/fmt.py` (Europe/Warsaw), `polish.py` | `test_pl_i18n` |
| 4.6, 4.7 | Addresses, PII | n/a for Spotlight (Concierge scope); Polish Content-Safety + injection pre-check instead | `test_pl_guardian`, `test_pl_i18n`, smoke PL-4 |
| 4.8 | Language detection | `domain/text.py` `detect_lang` | `test_pl_i18n` (≥ 49 samples) |
| 4.9 | Typography in video, timing | `domain/polish.py`, `video/overlays.py`, `video/spec.py`, `domain/timing.py` | `test_pl_pipeline` (extracted frame), `test_pl_voice_timing`, smoke PL-10/11 |
| 4.10 | Legal wording | `messages_pl` `disclosure.*`, `seed/pl_claims.py` | `test_pl_guardian`, `test_pl_platform` (provenance), smoke PL-13 |
| 6 | Locale middleware, `/api/meta`, `campaign.language`, localized errors | `i18n/`, `app_factory`, `errors` | `test_pl_i18n`, `test_pl_error_catalog`, smoke PL-1 |
| 6 | Polish Brand Book/voice/do-don't/personas/products/glossary, rights labels, sample campaign | `seed/data.py`, `seed/__init__.py`, `domain/kit.py` | `test_pl_seed`, smoke PL-2 |
| 6 | Claims pack, Guardian positives + negative controls, auto-revise | `seed/pl_claims.py`, `domain/guardian.py`, `pl_morph.py` | `test_pl_guardian`, smoke PL-3/7/8 |
| 6 | Brief / strategy / scripts / storyboard / VO / captions / end card / badge | `cs04…cs09`, `domain/*`, `video/*` | `test_pl_pipeline`, smoke PL-5…11 |
| 6 | Localization both directions, provenance summary | `cs10`, `domain/localize.py`, `cs14` | `test_pl_pipeline`, `test_pl_platform`, smoke PL-12/13 |
| 6 | Scorecard / variants / insights / planner | `cs16…cs19`, `domain/perfsim.py` | `test_pl_insights`, smoke PL-14 |
| 6 | 15 s Polish spot meets the delivery spec | `video/*`, `core/ai/azure.py` | `test_pl_pipeline`, smoke PL-11 (offline and real) |

## How to run every test

```bash
cd app
.venv/bin/python -m pytest tests -q -p no:cacheprovider            # 384 passed (97 baseline + 287 Polish); add --cov for coverage
.venv/bin/python -m pytest tests/test_pl_guardian.py tests/test_pl_i18n.py tests/test_pl_pipeline.py tests/test_pl_platform.py \
  tests/test_pl_voice_timing.py tests/test_pl_insights.py tests/test_pl_seed.py tests/test_pl_error_catalog.py -q   # Polish only
.venv/bin/ruff check src tests ../scripts e2e && .venv/bin/python -m mypy
SPOTLIGHT_MODE=offline .venv/bin/uvicorn spotlight.main:app --port 8102 &                                           # offline server
python ../scripts/smoke_test.py --base-url http://127.0.0.1:8102 --lang both                                        # 44/44 ( --lang en | pl )
# real Azure AI, never the live data (hybrid): in-memory repository + local blobs
SPOTLIGHT_MODE=azure AI_BACKEND=azure REPO_BACKEND=memory BLOB_BACKEND=localdir DATA_DIR=./.hybrid COSMOS_ENDPOINT= BLOB_ACCOUNT_URL= \
  AZURE_OPENAI_ENDPOINT=https://<ais>.openai.azure.com/ AI_ENDPOINT=https://<ais>.cognitiveservices.azure.com/ .venv/bin/uvicorn spotlight.main:app --port 8102 &
python ../scripts/smoke_test.py --base-url http://127.0.0.1:8102 --lang pl --expect-mode azure --evidence-dir evidence   # 17/17, ≈ US$0.14
AZURE_OPENAI_ENDPOINT=https://<ais>.openai.azure.com/ AI_ENDPOINT=https://<ais>.cognitiveservices.azure.com/ \
  .venv/bin/python ../scripts/calibrate_tts.py --lang pl [--out calibration-pl.json]                                   # speaking-model calibration, ≈ US$0.02
# after the code-only redeploy (live, ≈ US$0.31 for both narratives):
python ../scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io --expect-mode azure --lang both --evidence-dir evidence
```

## Facts for the product-docs agents

* Languages: `en`, `pl`; UI language (per request) and content language (`campaign.language`, defaults to the UI language, editable) are independent. LLM calls carry an explicit output-language directive; offline stubs also write Polish.
* Polish sample campaign `dawn-roast-premiera-pl` next to the English one; 15 Polish claim rules; Polish Brand Book; seed version `2026.11.2` re-runs once on deployed data (upsert, never wipe).
* Guardian PL: 34 positive and 30 negative-control golden sentences (each also without diacritics); EU 1924/2006 health claims apply to the PL market; the caffeine disclaimer „Zawiera kofeinę. Niezalecane dla dzieci i kobiet w ciąży.” is enforced.
* Real-model timings (swedencentral): brief ≈ 5 s, strategy ≈ 13 s, script ≈ 8 s, storyboard ≈ 96 s (4 images, low quality), VO ≈ 1.3 s, render 6–16 s, PL→EN with English render ≈ 20 s; ≈ US$0.14 per Polish smoke run.
* Terminology shared with the front end: *claim / claimy*, *Specjalista kreatywny*, *Dział prawny / Compliance*, *Strażnik marki* (Guardian), *wersja skrócona* (cut-down).

## Known gaps and limits (honest list)

* **Live run (done):** the Polish smoke on the deployed instance (44/44) and the FE's live journeys / live screenshots are in `REPORT-TEST-AND-DEPLOYMENT.md` §12.2 and §12.8. The Cosmos / Blob adapters were not exercised locally; on the first live start the Polish Brand Book chunks, 15 claim rules, rights labels and the sample campaign were upserted once (the live run also exposed two latent defects, §12.4).
* The speaking-rate model is calibrated for `pl-PL-ZofiaNeural` only; another voice needs its own constants in `domain/timing.py`.
* Back-translation QA is lexical (word stems + trigrams): good paraphrases are flagged `needs_review` for a human; real-model wording and timings vary run to run, so smoke asserts structure, not exact words.
* Polish legal wording (EU 1924/2006, AI disclosure) is demo content, not legal advice. Image prompts stay English by design; `/api/features` summaries stay English by contract (the UI translates by feature id); machine fields of the provenance manifest stay English.
* Offline Content Safety is a word-list heuristic (azure mode uses the real service plus the local Polish injection pre-check, because Prompt Shields' documented languages do not include Polish).
* English copy „Seven seeded violations — …” lists eight items (pre-existing, left untouched; the Polish text says „Osiem”). No eval harness exists in Spotlight (the Guardian golden sets are the equivalent).

## Files outside my ownership touched

* `app/e2e/journeys_pl.py`, `app/e2e/pl_checks.py` (FE-owned, FE already finished): **`ruff check --fix` only** — one unused import, five unused `noqa` comments, and `set("""…""".split())` → set literals so that the documented
  `ruff check src tests ../scripts e2e` is clean. The module constants are byte-for-byte the same data (hash checked before/after); nothing else changed. Nothing else outside `app/src`, `app/tests`, `scripts`, docs and `app/evidence`.
