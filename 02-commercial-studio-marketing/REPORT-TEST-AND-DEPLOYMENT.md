# Report — test, deployment & verification evidence

**Product:** SwarmAI Commercial Studio ("Spotlight") — Release 1 (CS-01 … CS-24) · **Verified:** 17–18 Nov 2026 ·
**Live app:** <https://ca-studio-web.yellowgrass-9740f562.swedencentral.azurecontainerapps.io> · **Resource group:** `rg-swarmai-studio` (swedencentral)

Raw evidence files are in [`app/evidence/`](app/evidence): `smoke-live.txt`, `load-live.txt`, `e2e-live.txt`, `quality-gates.txt`,
`azure-rg-tags.json`, `azure-resource-tags.txt`, `azure-security-settings.txt`, `ai-spend.txt`. Screenshots (1600×900) are in
[`deck/assets/screens/`](deck/assets/screens).

## 1. Definition-of-done checklist

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | All 24 features: backend + API + UI + unit tests + API/behavioural tests; `/api/features` lists them as implemented; Feature Map shows them | ✅ | `/api/features` → 24/24 `implemented` (smoke #2); `app/tests/*` (97 tests); Playwright "feature map" journey; `screens/25-feature-map.png`; FEATURES.md status board |
| 2 | Brief's behavioural tests exist and pass; ≥ 80 % line coverage on domain logic; ruff clean; typecheck/build passes; Playwright E2E passes | ✅ | 97 passed · coverage 88 % total, domain modules 88–100 % (§3) · `ruff` clean · `mypy` clean · `tsc -b` + `vite build` pass · E2E 18/18 on the live app (§4) |
| 3 | Deployed to Azure, mandatory RG tags, keyless; smoke test passes incl. real brief → rendered MP4; `/readyz` green; `mode=azure`; daily AI budget guard active | ✅ | smoke **30/30** (§5), `/readyz` all six dependencies `ok`, `mode=azure`, daily cap $5 (§2, §6) |
| 4 | Idempotent re-deploy proven; teardown documented | ✅ | `azd provision` → *"There are no changes to provision"*; `scripts/deploy.sh` re-run; `scripts/teardown.sh` (§7) |
| 5 | README, this report, screenshots | ✅ | [README.md](README.md), this file, 26 PNGs |
| 6 | No stray processes / temp junk / secrets | ✅ | §10 |

## 2. What is deployed (all keyless, all tagged)

| Resource | Name | Configuration (verified with `az`, `app/evidence/azure-security-settings.txt`) |
|---|---|---|
| Resource group | `rg-swarmai-studio` | swedencentral; tags below |
| Managed identity | `id-studio-app` | user-assigned; used for **every** data-plane call |
| Container Registry | `acrstudiovh4ojwexsajyg` | Basic, admin user **off**, remote ACR build (no local Docker) |
| Log Analytics | `log-studio-vh4ojwexsajyg` | 1 GB/day ingestion cap, 30 d retention |
| Application Insights | `appi-studio-vh4ojwexsajyg` | workspace-based, **`DisableLocalAuth=true`** (Entra-only ingestion); OpenTelemetry from the app |
| Container Apps environment + app | `cae-studio-vh4ojw` / `ca-studio-web` | 1 vCPU / 2 GiB, min 1 – max 2 replicas, external HTTPS only (`allowInsecure=false`), **0 secrets**, revision `ca-studio-web--azd-1794965663` |
| Cosmos DB for NoSQL | `cosmos-studio-vh4ojwexsajyg` | **serverless**, db `studio`, 22 containers (`/pk`), **`disableLocalAuth=true`**, data-plane RBAC only |
| Storage | `stvh4ojwexsajyg` | Standard_LRS, container `assets` private, **`allowSharedKeyAccess=false`**, `allowBlobPublicAccess=false`, TLS 1.2 |
| Azure AI Services | `ais-studio-vh4ojwexsajyg` | S0, **`disableLocalAuth=true`**; deployments: `gpt-5.4-mini` (GlobalStandard 100), `gpt-5.4` (50), `text-embedding-3-small` (50), `tts-hd` (Standard 2), `gpt-image-1.5` (3), `gpt-image-1-mini` (3); Content Safety + AI Speech neural voices via the same account |
| Platform-created extras | 2 scheduled-query alerts, 1 metric alert, 1 smart-detector rule, 1 Event Grid system topic | created by Azure Monitor / Storage on their own; tagged by `scripts/deploy.sh` |

**Governance tags (user instruction):** the RG is created with the tags at deployment time and **every taggable resource** carries them via one Bicep
`commonTags` object (a unit test, `test_bicep_applies_the_governance_tags_…`, guards this). Verification, as required:

```
$ az group show -n rg-swarmai-studio --query tags
{ "SecurityControl": "Ignore", "SecurityExemption": "StorageAccountKeyAccess", "azd-env-name": "studio",
  "concept": "studio", "environment": "demo", "owner": "michalfu", "project": "SwarmAI" }

$ az resource list -g rg-swarmai-studio --query "[].{n:name,t:tags.SecurityControl,e:tags.SecurityExemption}"   # all 14 resources
Name                                                                      SecurityControl  SecurityExemption
id-studio-app / log-studio-… / acrstudio… / stvh4ojwexsajyg / cosmos-studio-… / ais-studio-… / appi-studio-… /
cae-studio-vh4ojw / ca-studio-web / log-studio-…-DailyCapLimitReachedAlert / stvh4ojwexsajyg-AvailabilityAlert /
Failure Anomalies - appi-studio-… / appi-studio-…-ApplicationInsightsThrottlingLimitReachedAlert / stvh4ojwexsajyg-e049fd23-…
                                                                          Ignore           StorageAccountKeyAccess   (all 14 rows identical)
```

Full table in `app/evidence/azure-resource-tags.txt`. **No resource was modified or disabled by governance**: public access and auth settings are exactly as intended
(table above; e.g. Cosmos/AI Services/App Insights keys disabled, Storage shared-key off). The `SecurityExemption=StorageAccountKeyAccess` tag *permits* shared-key access on
Storage, but **nothing here needs it**: the Blob SDK uses Entra (`Storage Blob Data Contributor` for the managed identity and the signed-in user), so key access stays **off**
— the exemption is documented, not used. (An earlier mid-provision RG was re-tagged with `az tag update --operation merge`, then Bicep was changed so re-deploys keep the tags.)

## 3. Tests, coverage and static analysis

| Gate | Result |
|---|---|
| `pytest` (offline stubs + real ffmpeg) | **97 passed**, 0 failed, ≈ 45 s — `test_compositor` 10 · `test_domain` 22 · `test_features_api` 17 · `test_guardian` 19 · `test_pipeline_api` 7 · `test_platform` 22 |
| Line coverage | **88 % total** (7,919 statements). Domain logic: every module 88–100 % (aggregate ≈ 93 %: bandit 98, brief 99, colors 96, formats 96, perfsim 95, planner 97, rights 93, text 93, script 91, scorecard 91, guardian 90, spot_builder 88); core 86 %; feature routers 85 %. Real-Azure adapters (`core/ai/azure.py`, `core/repo/cosmos.py`, `AzureBlobStore`), the telemetry bootstrap and the vendored business-case model are excluded and covered by the live smoke test / `business-case/test_model.py` instead |
| `ruff check` (E,F,W,I,B,UP,S,ASYNC,C4,SIM,RUF) | clean (src, tests, scripts, e2e) |
| `mypy` (core + domain, 38 files) | no issues |
| Web: `tsc -b` (strict) + `vite build` | pass (bundle 965 kB / 282 kB gzip) |
| `pip-audit` | no known vulnerabilities (dev dependency `pytest` bumped to 9.0.3 to clear PYSEC-2026-1845; it is not part of the runtime image) |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Playwright E2E (Chromium, 1600×900) | **18/18 journeys** on the live app (§4) |

### Brief §5 behavioural tests → where they live

| Required behaviour | Test(s) |
|---|---|
| Guardian blocks seeded violations (prohibited claim, missing disclaimer, forbidden word, palette, unlicensed music, expired consent, content-safety hit), passes compliant assets, auto-revise converges | `test_guardian.py` (19 tests incl. `…auto_revise_converges_on_all_seeded_violations_at_once`, `…content_safety_hit_blocks…`), `test_features_api.py::test_cs12_guardian_playground_…` (all expected rules found, verdict *block* → converged), E2E "guardian playground", smoke #9–10 |
| Stage gating: no approval with open Guardian failures; role permissions; audit chain verifies | `test_pipeline_api.py::test_guardian_blocks_script_then_auto_revise_converges_and_approval_is_gated` (+ `gate_order` 409), `::test_role_permissions_are_enforced`, `test_platform.py::test_audit_chain_is_append_only_and_detects_edits_deletions_and_reordering`, `::test_role_permission_matrix_…`; smoke #15–16 |
| Compositor: `ffprobe` codec/resolution/duration ±0.5 s/audio, loudness ±1.5 LU, formats & cutdowns with correct aspect ratios, captions/SRT monotonic | `test_compositor.py` (H.264/AAC, 1280×720, 14.9 s, −16.0 LUFS; −23 LUFS broadcast; 16:9/9:16/1:1/4:5 exact sizes; SRT timing; subprocess isolation), `test_domain.py::test_reframe_and_cutdown_…`; smoke #13 (live: 14.9 s, −16.1 LUFS) and #17 (6.0 s cutdown, 720×1280, 720×720) |
| Provenance verifies and fails after tampering | `test_pipeline_api.py` (tamper of file **and** manifest detected), smoke #14, E2E "provenance verification + tamper test" |
| Bandit converges to the best variant in ≥ 90 % of seeded simulations, beats uniform in cumulative reward, significance test correct | `test_domain.py`: converges to the best arm in ≥ 90 % of 40 seeded simulations (asserted), beats uniform in ≥ 28/30 seeds with mean uplift > 8 %, z-test vs textbook value (z = 2.188, p = 0.0287), type-I error ≈ 5 % and power > 95 % on synthetic data, auto-pause only clear losers |
| Budget guard refuses after the cap with a clear error; metering matches counted calls | `test_platform.py::test_budget_guard_refuses_after_the_cap_…` (HTTP 402, `daily_budget_exceeded`, "fails closed"; `meter.by_kind.image.calls == image.calls`), campaign cap + premium gate, once-per-threshold alerts, readable small amounts; smoke #29 (live 402) |
| Localization keeps glossary / do-not-translate terms; back-translation similarity threshold | `test_domain.py` (DNT masking, faulty translator repaired, similarity threshold), `test_features_api.py::test_cs10_localization_…` (DE/PL keep *Dawn Roast*, approved tagline translations), smoke #19 (live DE/FR/PL; low-similarity lines flagged *review*) |
| ROI calculator reproduces `business-case/outputs.json` within 0.5 % | `test_platform.py::test_roi_calculator_reproduces_…` (the **entire** `compute()` output of Conservative/Base/Upside compared recursively, plus all-levers-on), `::test_roi_headline_numbers_and_the_expansion_levers_…`, API parity endpoint; smoke #27 |
| Smoke test on Azure (real brief → … → MP4 → Guardian pass/fail → provenance) | `scripts/smoke_test.py`, §5 |

## 4. Playwright journeys (live) — `app/e2e/journeys.py`, `app/evidence/e2e-live.txt`

18/18 pass on the deployed app (a first local run had caught one missing test-id, fixed before the live runs): dashboard · brief wizard (≤ 3 clarifying questions) · brand brain (cited retrieval) · claims + rights · creative workspace
(storyboard keyframes, **video player with duration > 5 s**, ffprobe panel, audio, formats tree, localization, scorecard) · provenance verification + **tamper test** · Guardian playground
(**BLOCK** report with all seeded rules found, then auto-revise → not blocked) · approvals inbox + "chain verified" · variants/bandit (stacked allocation chart, paused losers) · performance insights ·
media planner · asset library (search, detail dialog) · cost meter · **ROI/ACR calculator** (Base reference values, 5 tiers, Enterprise breakdown, Upside, *Expansion on*) · team · ops · feature map · Swagger.
Any console error or HTTP 5xx during a journey fails the run. The variants journey creates a 12-variant experiment on a scratch campaign and runs it to *completed*, then resets and re-runs the seeded showcase
experiment (deterministic) and asserts leader, significance column, paused losers and the stacked allocation chart before capturing it; the scratch campaign is deleted by the script afterwards.
**Every capture is gated by a settle check**: the journey fails if the page still shows a skeleton, spinner, "Loading…" text, an undecoded image, an unloaded video/audio player or a lingering toast
(added after a review found the first variants capture taken while the new experiment's details were still loading — the page itself never stays on a skeleton). Screenshots (all **1600×900**): `01-dashboard`, `02-brief-wizard`, `03-brand-brain`, `04-claims-library`, `05-rights-registry`,
`06-creative-workspace-storyboard`, `07-creative-workspace-video`, `08-voice-and-music`, `09-formats-and-cutdowns`, `10-localization`, `11-preflight-scorecard`, `12-provenance-tamper-test`,
`13-guardian-report-blocked`, `14-guardian-auto-revise`, `15-approvals-inbox`, `16-approvals-and-audit-chain`, `17-variants-bandit-experiment`, `18-performance-insights`, `19-media-planner`,
`20-asset-library`, `21-cost-meter`, `22-roi-acr-calculator`, `22b-roi-expansion-on`, `23-team-and-integrations`, `24-ops-observability`, `25-feature-map`.

## 5. Smoke test against the deployed app (`scripts/smoke_test.py --base-url <live> --expect-mode azure --langs de,fr,pl`)

**30 / 30 PASS** — real Azure OpenAI (`gpt-5.4-mini`, `gpt-image-1.5` low quality, `tts-hd`, embeddings), Content Safety, Cosmos DB, Blob Storage. AI spend of the run (list-price estimate): **$0.174** (runs vary between US$0.157 and US$0.178, i.e. ≈ US$0.16–0.17 per run).

| # | Check | Result | Time | Evidence |
|---|---|---|---|---|
| 1 | healthz + readyz (Cosmos, Blob, Azure OpenAI, Content Safety, Speech, ffmpeg) | PASS | 2.9s | mode=azure deps=repository:501ms,blob_storage:359ms,openai_chat:1655ms,content_safety:557ms,speech:488ms,ffmpeg:204ms |
| 2 | feature registry (24/24) + SPA + Feature Map route | PASS | 1.4s | 24/24 implemented; SPA served |
| 3 | meta + usage: daily AI budget guard active | PASS | 1.3s | daily cap $5.0; models=['gpt-5.4-mini', 'gpt-5.4', 'text-embedding-3-small']… |
| 4 | CS-01 Brand Brain retrieval with citations (embeddings) | PASS | 1.2s | 5 cited passages (top: 'Voice and tone', score 0.5309) |
| 5 | CS-02 claims library: prohibited blocked / compliant passes | PASS | 1.6s | prohibited claim -> block; compliant line -> pass |
| 6 | CS-03 rights registry: unlicensed / expired blocked, library cleared | PASS | 2.1s | unlicensed music + expired consent blocked; library track cleared |
| 7 | CS-04 briefing agent: <=3 questions, normalized brief, early Guardian flags | PASS | 5.1s | 3 clarifying questions: ['key_message', 'cta', 'duration_targets']; Guardian flags ['claims.prohibited', 'rights.unlicensed'] |
| 8 | CS-05 strategy agent: 3+ territories grounded with citations | PASS | 13.6s | 3 territories (e.g. 'The first quiet minute'), 5 citations, guardian=warn |
| 9 | CS-06 script agent writes 15 s script; Guardian blocks the mandatory claim + music cue | PASS | 6.2s | 4 beats, 30 words; Guardian BLOCKS (blocks=2, score=56) |
| 10 | CS-12 Guardian auto-revise converges (claim rewritten, music swapped to licensed track) | PASS | 2.1s | converged in 2 iteration(s); fixes=['replace_text', 'swap_music']; verdict=pass; music -> Slow Ember (library) |
| 11 | CS-07 storyboard: shot list + >=3 gpt-image keyframes (low quality) | PASS | 89.9s | 4/4 keyframes (gpt-image-1.5, low), first image 336 KB; guardian=pass |
| 12 | CS-09 voice-over timed to script beats (tts-hd) + SRT | PASS | 6.9s | 4 lines, 9.9s of VO, voice=openai:nova, cost $0.00366 |
| 13 | CS-08 compositor: 15 s H.264/AAC MP4 retrievable via API (ffprobe, loudness, range) | PASS | 30.5s | 14.9s MP4 1387 KB, -16.1 LUFS, render 23.71s; ffprobe: h264/aac 1280x720 14.90s; guardian=pass |
| 14 | CS-14 provenance manifest verifies; tampering is detected; pack export | PASS | 4.2s | manifest verifies (5 checks, key f916194aefd10562); tampered asset+manifest rejected; pack 1368 KB |
| 15 | CS-13 approvals: stage gates, roles enforced, Guardian-gated approval | PASS | 27.1s | 5/5 gates approved by role; Guardian-gated=True; non-approver refused (403) |
| 16 | CS-13 immutable audit log verifies (hash chain) | PASS | 0.7s | hash-chain verified: 25 entries, head 44547d866a38… |
| 17 | CS-11 format factory: 9:16, 1:1 and 6 s bumper from the master | PASS | 63.7s | version tree: master + 3 derived {'16:9 · 6s cutdown': (1280, 720, 6.0), '1:1': (720, 720, 14.9), '9:16': (720, 1280, 14.9)} |
| 18 | CS-11/13 derived versions approved (Guardian-gated) | PASS | 1.9s | approved 3 derived versions; refused 0 |
| 19 | CS-10 localization de,fr,pl: glossary kept, back-translation QA, localized VO + render | PASS | 98.8s | pl: minsim=0.337, review=1, guardian=pass; fr: minsim=0.25, review=1, guardian=pass; de: minsim=0.799, review=0, guardian=pass |
| 20 | CS-16 pre-flight scorecard (labelled predictive/simulated) | PASS | 3.4s | predicted 85/100 (heuristic 91, panel avg 7); suggestions=0 |
| 21 | CS-17 12-variant experiment: Thompson sampling converges to the best arm in 24 simulated hours | PASS | 3.1s | leader v03 within 0.3% of the simulator's best (v02); 8 losers auto-paused; +17.1% clicks vs uniform; top share 51% |
| 22 | CS-18 performance: connector sync + CSV ingest + insights written to Brand Brain | PASS | 6.1s | 98 rows; CTR 1.552% CVR 4.50% CPA $12.90 ROAS 1.12; 7 insight(s) -> Brand Brain (56 learnings) |
| 23 | CS-19 planner: media-mix with diminishing returns + ranges (illustrative) | PASS | 0.9s | 6 channels; ROAS p10/p50/p90 0.81/0.99/1.19; +16.9% vs uniform split |
| 24 | CS-21 asset library: semantic search, upload, versions, range streaming | PASS | 3.8s | semantic search -> 2 hits; upload + version v2 |
| 25 | CS-22 webhooks: Teams-compatible delivery + SSRF guard; roles enforced | PASS | 2.7s | Teams MessageCard delivered to internal sink; SSRF target (metadata IP) rejected |
| 26 | CS-22 campaign pack export (mp4/png/csv/provenance zip) | PASS | 7.3s | pack 10966 KB with 40 files (videos, keyframes, captions, provenance, csv) |
| 27 | CS-23 ROI & ACR calculator reproduces outputs.json; overrides recompute | PASS | 5.8s | model v1.1.0 parity OK (±0.5%); Base NPV $6,979,862, ROI 139.98%, payback 14.97 mo, ACR Y1/Y2/Y3 $64,541/$304,893/$464,798; Upside Y3 $972,886; Enterprise tier $2.63M/yr; expansion on → Y3 ≈ $940k |
| 28 | CS-15 cost meter: $ per approved asset vs agency baseline | PASS | 0.8s | campaign spend $0.168, 4 approved assets → $0.0421/asset vs agency $1,850 |
| 29 | CS-15 budget guard fails closed with a clear message (per-campaign cap) | PASS | 1.9s | generation refused with 402 `campaign_budget_exceeded`: "Campaign AI cap reached: $0.00 of $0.0001 spent on this campaign…" |
| 30 | CS-24 observability: status, per-route metrics, AI usage meter | PASS | 3.0s | telemetry=App Insights; 69 routes metered; AI calls {'safety': 90, 'embedding': 25, 'llm': 13, 'image': 4, 'tts': 24, 'render': 7} |

The rendered commercial is retrievable from the live API (e.g. `GET /api/library/assets/{id}/content`, `Range` supported) and plays in the UI (`screens/07-creative-workspace-video.png`).
Note on #19: with real LLM transcreation the English back-translation legitimately differs from the source; lines below the 0.5 similarity threshold are **flagged for human review** instead of silently passing — that is the QA gate working.
The smoke test removes the campaigns of earlier smoke/E2E runs first (`--keep-previous` to disable), so the demo environment keeps exactly one showcase campaign (7 rendered versions: master, 9:16, 1:1, 6 s cut, DE, FR, PL).

## 6. Light load check (`scripts/load_test.py`, 400 requests, concurrency 20, one 1-vCPU replica)

| Endpoint | n | p50 ms | p95 ms | p99 ms | errors |
|---|---|---|---|---|---|
| GET /healthz | 50 | 302 | 550 | 724 | 0 |
| GET /api/features | 50 | 295 | 785 | 916 | 0 |
| GET /api/studio/overview (dashboard) | 50 | 1106 | 2039 | 2181 | 0 |
| GET /api/library/assets | 50 | 651 | 1318 | 1439 | 0 |
| GET /api/claims | 50 | 399 | 841 | 963 | 0 |
| GET /api/budget | 50 | 811 | 1472 | 1784 | 0 |
| GET /api/brand | 50 | 568 | 1128 | 1290 | 0 |
| POST /api/roi/compute | 50 | 528 | 789 | 1044 | 0 |
| **all** | 400 | **554** | **1414** | 2000 | **0** (29 req/s) |

Latencies include the client's WAN round trip (≈ 40–60 ms) and TLS; they are for reads that fan out to Cosmos DB serverless. The first run (p50 577 ms / **p95 3,450 ms**, dashboard p50 3.3 s) led to an
optimisation (field projections in Cosmos queries, concurrent per-campaign lookups, `limit=1` gate lookups) that cut the dashboard p50 to ≈ 1.1 s and the overall p95 to ≈ 1.1–1.4 s. Long jobs
(image generation ≈ 90 s for 4 keyframes, render ≈ 24 s per 15 s spot on 1 vCPU, localization ≈ 33 s per language) run in the background job runner with live SSE progress, so the web process stays responsive.

## 7. Idempotent redeploy and teardown

```bash
export AZURE_SUBSCRIPTION_ID=<subscription-id>
scripts/deploy.sh            # azd provision → tag platform-created resources → azd deploy web  (full run measured: 5 m 03 s)
scripts/deploy.sh --app-only # code-only redeploy (measured: 3 m 43 s)
scripts/teardown.sh          # azd down --force --purge
```

Proof of idempotency (second full run, nothing changed in `infra/`): `azd provision` printed *"Comparing deployment state — (-) Skipped: Didn't find new changes. SUCCESS: There are no changes to provision"*, then
`azd deploy web` built remotely in ACR and rolled a new revision (4 m 25 s) with `/healthz` and `/readyz` green afterwards. The initial provisioning (≈ 5 min) created everything from Bicep
(`infra/main.bicep` + 8 modules; subscription-scope deployment creates the tagged RG). Teardown removes the RG including Cosmos data, blobs, ACR and the soft-deleted AI Services account (`--purge`).
After the review, three UI-only follow-ups (variants page layout, voice-over player metadata) were rolled out with `scripts/deploy.sh --app-only` (3 m 13 s – 3 m 14 s each); the live revision is `ca-studio-web--azd-1794965663`
(re-checked: 0 secrets, HTTPS only, 14/14 resources and the RG carry both governance tags) and the final E2E run (18/18) was executed against it.

## 8. AI spend and estimated idle cost

**AI spend incurred** (metered by the app at list-price estimates; every call to Azure OpenAI / Content Safety / Speech goes through the meter; `app/evidence/ai-spend.txt`): **$0.80 in total** for the verification
campaign of the delivery (5 full 30-check smoke runs — 2 from a local server against the real Azure resources, 3 against the live app —, 3 E2E runs and all manual checks): Content Safety $0.33 (419 calls), images $0.26 (20 × `gpt-image-1.5` low quality), LLM $0.12 (64 calls), TTS $0.08 (102), render compute $0.014, embeddings $0.0002.
Afterwards the reviewer's own live smoke run (US$0.157) and three follow-up E2E runs (US$0.028 together) raised the cumulative ledger to **$0.99** (`app/evidence/ai-spend.txt` lists both snapshots).
A full end-to-end smoke run costs ≈ **US$0.16–0.17**. The daily guard is **$5** (per-campaign cap $2, hard maximum $50) and fails closed.

**Estimated idle monthly cost** (list prices, no discounts; validate in the Azure Pricing Calculator): Container Apps 1 vCPU/2 GiB always-on at idle rates ≈ **$22–24**, Container Registry Basic ≈ **$5**, Cosmos DB serverless
(≈ 0.1 GB, no traffic) ≈ $0.1, Storage LRS ≈ $0.02, Log Analytics/App Insights within the free allowance ≈ $0–2, Azure OpenAI/Content Safety/Speech deployments have no standing charge → **≈ $30 / month idle**.
Setting `appMinReplicas` to 0 (scale to zero, ≈ 15 s cold start) brings idle cost to ≈ **$5 / month** (ACR only).

## 9. Security notes

* **Keyless by design.** One user-assigned managed identity reaches Cosmos (`sqlRoleAssignments`), Blob (`Storage Blob Data Contributor`), Azure OpenAI/Content Safety/Speech (`Cognitive Services OpenAI User` + `Cognitive Services User`) and App Insights (`Monitoring Metrics Publisher`). Local/key auth is **disabled** on Cosmos, AI Services and App Insights; Storage shared-key is **off** (the exemption tag is *not* exercised); ACR admin is off; the container app has **0 secrets**; the repo contains no keys.
  The Application Insights *connection string* is an app setting by necessity (it identifies the resource; ingestion needs an Entra token), the provenance signing key (Ed25519) is generated on first use and stored in the **private** blob `keys/` — a software key, documented limitation (production: Key Vault/HSM + certificate chain).
* **Network:** public ingress with HTTPS only, no public blobs (media is streamed through the API with range support, `nosniff`, CSP `frame-ancestors`, `X-Frame-Options`), request-size limit (12 MB), upload type allow-list (SVG rejected, images validated), per-IP and global rate limits that are tighter on spend routes. Private endpoints / WAF / Front Door are documented target-state options, not deployed.
* **Prompt injection & data handling:** all uploaded text is wrapped as untrusted data and screened with Content Safety Prompt Shields (attacks are quarantined, not indexed); webhooks are SSRF-guarded (https + allow-list + public-IP-only resolution, unit-tested against metadata/loopback/credential/port/suffix tricks); logs are PII-redacted.
* **Identity of users:** the demo role switcher (`X-Studio-Role`) is **self-declared** — anyone with the URL can act as any role, bounded by the $5/day fail-closed AI cap. For shared use enable the Bicep switch `enableEntraAuth` (+ `entraClientId`); app roles then arrive via `X-MS-CLIENT-PRINCIPAL`.
* **Supply chain:** `pip-audit` and `npm audit` clean; container runs as non-root (uid 10001) from `python:3.13-slim`; `npm ci --ignore-scripts`.
* **Responsible AI:** burned-in AI-disclosure badge where required, signed provenance with tamper-evident verification, Guardian-gated approvals, Legal-only waivers with audit trail, predictive scorecards labelled *simulated*.

## 10. Real vs simulated — and what is not done

| Real | Simulated / illustrative |
|---|---|
| Azure OpenAI chat/structured output, `gpt-image-1.5`, `tts-hd`, embeddings; Content Safety; AI Speech; Cosmos DB; Blob; managed identity/RBAC; App Insights; ffmpeg rendering (H.264/AAC, −16 LUFS, captions, music, end card); hash-chained audit; Ed25519 provenance; approvals/roles | Brand, claims, rights, talent, campaigns (fictional Northwind Coffee Roasters); ad platforms and connectors; synthetic audience panel (scores labelled *predicted/simulated*); bandit "ground truth"; media-planner curves; performance history; ROI/ACR figures (illustrative business case from `business-case/`) |

Not done / limits (honest list): generative video models are not used (**Sora-2 is deprecated** in swedencentral) — a `VideoProvider` interface is in place and the compositor animates keyframes; CJK/Arabic caption fonts are not shipped (Latin, Cyrillic, Greek are); rate limits are per replica; no CI pipeline, WAF or private networking;
the provenance format is C2PA-*style*, not a certified Content Credential; the load check is light (single replica, 400 requests — autoscale beyond concurrency 40 not exercised); expansion levers E1–E4 are modelled in the calculator, not built.

### Issues found and fixed during verification
First real-Azure smoke run: 25/30 → fixed a connection-reuse flake in the smoke client, a transient cold-start `readyz` degrade (retry + failing-dependency detail), and per-campaign cap attribution in async dependencies (then 30/30).
`contains_phrase` matched inside words (`awake` ⊃ `wake`) → whole-phrase match; PII redaction order (IPs were masked as phones); a budget alert is now also emitted when a call is *refused* at the cap; the claim checker now accepts the disclaimer inside the text itself; provenance "coverage" counts delivered spots;
dashboard/budget/brand endpoints were parallelised (p95 3.45 s → ≈ 1.1–1.4 s); `deploy.sh` tag loop now handles resource names containing spaces; business-case model re-vendored to the final **v1.1.0** (all three files, byte-identical, recursive 0.5 % parity test).

## 11. Reproduce

```bash
cd app && python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]" && (cd web && npm ci && npm run build)
.venv/bin/pytest --cov && .venv/bin/ruff check src tests ../scripts e2e && .venv/bin/mypy           # 97 passed · 88 %
export AZURE_SUBSCRIPTION_ID=<id> && ../scripts/deploy.sh                                              # provision + deploy
python ../scripts/smoke_test.py --base-url <url> --expect-mode azure --langs de,fr,pl                  # 30/30
python ../scripts/load_test.py  --base-url <url>
/path/to/playwright-venv/bin/python e2e/journeys.py --base-url <url> --screens ../deck/assets/screens   # 18/18 + PNGs
python ../scripts/sync_business_case.py                                                                # re-vendor model v1.1.0 + parity
```
