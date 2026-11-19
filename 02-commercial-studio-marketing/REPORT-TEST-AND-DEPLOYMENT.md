# Report — test, deployment & verification evidence

**Product:** SwarmAI Commercial Studio ("Spotlight") — CS-01 … CS-25 · **Verified:** 17–19 Nov 2026 ·
**Live app:** <https://ca-studio-web.yellowgrass-9740f562.swedencentral.azurecontainerapps.io> · **Resource group:** `rg-swarmai-studio` (swedencentral)

Raw evidence files are in [`app/evidence/`](app/evidence): `smoke-live.txt`, `load-live.txt`, `e2e-live.txt`, `quality-gates.txt`,
`azure-rg-tags.json`, `azure-resource-tags.txt`, `azure-security-settings.txt`, `ai-spend.txt`. Screenshots (1600×900) are in
[`deck/assets/screens/`](deck/assets/screens).

> §1–§11 document the **English release as deployed** (97 tests, 30/30 live smoke …) — a dated snapshot. The **Polish localization** was added afterwards, **deployed to Azure on 18 Nov 2026 and verified live (44/44 smoke)**; it is reported in **§12** (evidence in `app/evidence/pl-*`). **Cinematic motion (CS-25)** — real AI-generated video clips on a serverless GPU instead of camera moves on stills — came last, **deployed and verified live on 18–19 Nov 2026**; it is reported in **§13** (evidence in `app/evidence/motion-*`). Where a statement in §1–§11 is superseded (generative video), it says so.

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
| Container Registry | `acrstudiovh4ojwexsajyg` | Basic at this release (**Standard since CS-25**, §13.2: the GPU worker image is 7.6 GB), admin user **off**, remote ACR build (no local Docker) |
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
A full end-to-end smoke run costs ≈ **US$0.16–0.17**. The daily guard is **$5** (per-campaign cap $2, hard maximum $50) and fails closed (*since CS-25: $15 and $5*, because one Cinematic spot meters ≈ $0.5 of GPU; §13.2).

**Estimated idle monthly cost** (list prices, no discounts; validate in the Azure Pricing Calculator): Container Apps 1 vCPU/2 GiB always-on at idle rates ≈ **$22–24**, Container Registry Basic ≈ **$5**, Cosmos DB serverless
(≈ 0.1 GB, no traffic) ≈ $0.1, Storage LRS ≈ $0.02, Log Analytics/App Insights within the free allowance ≈ $0–2, Azure OpenAI/Content Safety/Speech deployments have no standing charge → **≈ $30 / month idle**.
Setting `appMinReplicas` to 0 (scale to zero, ≈ 15 s cold start) brings idle cost to ≈ **$5 / month** (ACR only). *Update (CS-25, 19 Nov 2026):* the registry is now Standard (≈ $20 a month instead of ≈ $5), so the figures become ≈ **$45 / month** idle and ≈ **$20** with scale-to-zero; the GPU worker adds nothing while it sleeps (§13.3).

## 9. Security notes

* **Keyless by design.** One user-assigned managed identity reaches Cosmos (`sqlRoleAssignments`), Blob (`Storage Blob Data Contributor`), Azure OpenAI/Content Safety/Speech (`Cognitive Services OpenAI User` + `Cognitive Services User`) and App Insights (`Monitoring Metrics Publisher`). Local/key auth is **disabled** on Cosmos, AI Services and App Insights; Storage shared-key is **off** (the exemption tag is *not* exercised); ACR admin is off; the container app has **0 secrets**; the repo contains no keys.
  The Application Insights *connection string* is an app setting by necessity (it identifies the resource; ingestion needs an Entra token), the provenance signing key (Ed25519) is generated on first use and stored in the **private** blob `keys/` — a software key, documented limitation (production: Key Vault/HSM + certificate chain).
* **Network:** public ingress with HTTPS only, no public blobs (media is streamed through the API with range support, `nosniff`, CSP `frame-ancestors`, `X-Frame-Options`), request-size limit (12 MB), upload type allow-list (SVG rejected, images validated), per-IP and global rate limits that are tighter on spend routes. Private endpoints / WAF / Front Door are documented target-state options, not deployed.
* **Prompt injection & data handling:** all uploaded text is wrapped as untrusted data and screened with Content Safety Prompt Shields (attacks are quarantined, not indexed); webhooks are SSRF-guarded (https + allow-list + public-IP-only resolution, unit-tested against metadata/loopback/credential/port/suffix tricks); logs are PII-redacted.
* **Identity of users:** the demo role switcher (`X-Studio-Role`) is **self-declared** — anyone with the URL can act as any role, bounded by the $5/day fail-closed AI cap ($15 since CS-25). For shared use enable the Bicep switch `enableEntraAuth` (+ `entraClientId`); app roles then arrive via `X-MS-CLIENT-PRINCIPAL`.
* **Supply chain:** `pip-audit` and `npm audit` clean; container runs as non-root (uid 10001) from `python:3.13-slim`; `npm ci --ignore-scripts`.
* **Responsible AI:** burned-in AI-disclosure badge where required, signed provenance with tamper-evident verification, Guardian-gated approvals, Legal-only waivers with audit trail, predictive scorecards labelled *simulated*.

## 10. Real vs simulated — and what is not done

| Real | Simulated / illustrative |
|---|---|
| Azure OpenAI chat/structured output, `gpt-image-1.5`, `tts-hd`, embeddings; Content Safety; AI Speech; Cosmos DB; Blob; managed identity/RBAC; App Insights; ffmpeg rendering (H.264/AAC, −16 LUFS, captions, music, end card); hash-chained audit; Ed25519 provenance; approvals/roles; **(CS-25) Wan 2.2 image-to-video on a serverless A100 behind a queue** | Brand, claims, rights, talent, campaigns (fictional Northwind Coffee Roasters); ad platforms and connectors; synthetic audience panel (scores labelled *predicted/simulated*); bandit "ground truth"; media-planner curves; performance history; ROI/ACR figures (illustrative business case from `business-case/`) |

Not done / limits (honest list): at the time of this release generative video was not used (Sora 2 was deprecated in swedencentral and the compositor animated keyframes) — **superseded by CS-25 (§13)**, which generates real video clips with an open model on a serverless GPU; CJK/Arabic caption fonts are not shipped (Latin, Cyrillic, Greek are); rate limits are per replica; no CI pipeline, WAF or private networking;
the provenance format is C2PA-*style*, not a certified Content Credential; the load check is light (single replica, 400 requests — autoscale beyond concurrency 40 not exercised); expansion levers E1–E4 are modelled in the calculator, not built (the hosted-model, Sora-priced E1 in particular; CS-25 is the self-hosted path, priced per GPU second).

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

## 12. Polish localization (pl)

**Status.** **Deployed to Azure and verified live** (code-only redeploy by `az acr build` + `az containerapp update`; no infrastructure change; the idempotent seed `2026.11.3` upserted the Polish content into the live Cosmos DB without touching existing data). The first live run was on revision `ca-studio-web--0000003`; after the fix of §12.8 the app was redeployed from the committed tree — image tag `git-3b33cbe`, revision `ca-studio-web--0000005` — and the smoke test was **44/44** again (AI spend US$0.32).
Before the deployment the work was verified locally in two ways: *offline stubs* (every code path, deterministic) and the **real Azure AI models** on *hybrid backends* — real Azure OpenAI, Content Safety, AI Speech and image generation,
but an in-memory repository and local-directory blobs, so nothing touched the live Cosmos DB / Blob storage while the English app was being served from it. The live daily AI cap was raised for the verification and restored to **$5** (per-campaign cap $2).

### 12.1 What is Polish now

| Area | What changed | Proven by |
|---|---|---|
| Contract | `?lang` → `X-UI-Lang` → `Accept-Language` → `en` locale middleware (context variable, inherited by background jobs); `/api/meta` → `languages`, `default_language`, `language`; `Content-Language` on every response; `campaign.language` (defaults to the request locale, always returned); errors keep `error.code` and localize `message`/`hint` (125 raise sites, AST-checked) | `test_pl_i18n.py`, `test_pl_error_catalog.py`, smoke PL-1 |
| Read-time rendering | deterministic text is stored as **code + params** and rendered in the reader's language: Guardian findings, script timing issues, voice warnings, audit one-liners, job titles/progress/errors (also the SSE stream), approval stages, notifications / webhook cards, team roster, scorecard tips, insight sentences, cost/ROI/ops notes, format-version notes, provenance summary; hash chain and signed manifest untouched (machine fields stay English) | `test_pl_guardian.py`, `test_pl_platform.py`, smoke PL-13/PL-14 |
| Content (seed v2026.11.2, idempotent) | second Brand Book + kit with `lang: pl` (tagline *„Obudź się powoli.”*, voice & tone, do/don't, personas, products, glossary, logo notes), 15 `clm-pl-*` claim rules, Rights registry notes/channel/territory labels, sample campaign **„Dawn Roast — premiera w Polsce”** (`dawn-roast-premiera-pl`, market PL, language pl). Deterministic ids, upsert only, English seeds and counts untouched; re-seeding on an already-deployed store keeps user work | `test_pl_seed.py` |
| Guardian in Polish | inflection-aware, diacritic-insensitive patterns (ł/Ł included) for prohibited / needs-substantiation / approved claims, forbidden words with replacements that agree in gender and case, caffeine disclaimer, EU 1924/2006 health claims (PL market only), greenwashing, superlatives, finance / pharma / alcohol packs, missing AI-disclosure label, rights; **34 positives × (with / without diacritics) and 30 negative controls** (look-alike stems such as *zabierz*, compliant copy) → no false positives; auto-revise converges to compliant Polish with Polish rewrites | `test_pl_guardian.py` (165), smoke PL-3/PL-7/PL-8 |
| Content Safety / Prompt Shields | Polish word lists for the offline stub, and a local Polish + English prompt-injection pre-check in the Azure adapter (the documented languages of Prompt Shields do not include Polish) | `test_pl_guardian.py`, `test_pl_i18n.py`, smoke PL-4 (real service) |
| Polish-first pipeline | brief (Polish free text → Polish questions → normalized brief) → strategy territories (grounded in the Polish Brand Book) → 6 / 15 / 30 s scripts (beats, VO, supers, CTA) → storyboard (Polish descriptions, **English image prompts by design**) → `pl-PL` neural VO → SRT + burned-in captions → end card / legal supers / „Wygenerowano przez AI” → format factory; every LLM call carries an explicit output-language directive and the offline stubs write Polish too | `test_pl_pipeline.py`, smoke PL-5 … PL-11 |
| Timing and typography | per-language speaking model (`domain/timing.py`) calibrated on real audio, the *„line too long for its beat”* check, trimming / beat rebalancing that never drops the tagline or a verbatim mandatory; numbers / units / dates spelled as inflected words for the voice; NBSP after single-letter words, between number and unit and inside brand names; captions break at sentence ends, then at commas, never leave a one-word cue; long words shrink to fit | `test_pl_voice_timing.py`, `test_pl_pipeline.py` (extracted frame), smoke PL-10/PL-11 |
| Localization both ways | PL → EN / DE / FR … and EN → PL: glossary + do-not-translate masked and verified, legal lines translated, back-translation QA in the source language (Polish compared by word stems), localized supers, voice and render | `test_pl_pipeline.py`, `test_pl_i18n.py`, smoke PL-12 |
| Scorecard / variants / insights / planner | Polish audience-panel personas and suggestions, Polish hook copy and labels, insight statements rendered per viewer from structured evidence, pl-PL numbers and dates | `test_pl_insights.py`, smoke PL-14 |

### 12.2 Results

| Gate | Offline stubs | Real Azure models (hybrid) | Live (deployed) |
|---|---|---|---|
| `pytest` (`app/tests`) | **1,206 passed + 8 strict `xfail`** (97 English baseline unchanged + 1,109 Polish / regression: the build's 287 plus the independent linguistic QA — an 825-case adversarial Guardian corpus in `test_pl_guardian_adversarial.py`, 165 Guardian goldens, regression tests for the two live findings of §12.4), 0 failed, ≈ 65 s. The 8 xfails are documented residual gaps (`KNOWN_GAPS`) that fail loudly if they ever start passing | — | n/a (local suite) |
| Line coverage | **90 %** total on the final tree (9,911 statements, 957 missed) | — | n/a |
| `ruff check src tests ../scripts e2e` / `mypy` | clean / no issues in 42 files | — | n/a |
| `smoke_test.py --lang both` | **44/44** (30 English + 14 Polish), English-only `--lang en` 30/30 | — | **44/44** on the deployed app (`app/evidence/pl-smoke-live.txt`), AI spend **US$0.34** for both languages |
| `smoke_test.py --lang pl` | 14/14 Polish steps | **17/17** (3 infra + 14 Polish), AI spend **US$0.140** | PL-1 … PL-14 all PASS: Polish content on Cosmos, Guardian block + auto-revise, pl-PL VO, MP4, PL→EN localization, provenance, read-time localization |
| Polish 15 s spot vs delivery spec | ffprobe h264/aac 1280×720, 14.90 s, −16.0 LUFS | same: 14.90 s, −16.0 LUFS (−15.8 … −16.0 over the runs) | **14.9 s h264/aac 1280×720, −16 LUFS** (PL-11) |
| Extracted frames: diacritics + „Wygenerowano przez AI” | glyph check of caption, badge and end card passes | passes (`app/evidence/pl-frames/*.png`) | **verified on a frame of the live render** (`app/evidence/pl-frames-live/`: „Wolniejszy początek dnia,”, „Obudź się powoli.”, „Znajdź Dawn Roast…”) |
| Guardian rewrite / PL→DE / EN→PL on the real models | — | verified (`pl-realmodel-guardian-localization.txt`, US$0.059) | PL-3, PL-7, PL-8, PL-12 on the live services |
| Front end: typecheck, vitest, build, Playwright Polish journeys + screenshots | Polish journeys **36/36** (33 page states), English journeys **18/18**; vitest 65 passed; `pl_audit`: 0 missing keys, 0 console errors, 0 overflow at 1600×900 and 1280×720 (`app/PHASE1-fe-DONE.md`) | — | Polish journeys on the deployed app: see §12.8 |
| Eval pass rate | not applicable to Spotlight (the equivalent is the Guardian golden set: 34 Polish positives, 30 negative controls, each also without diacritics — `test_pl_guardian.py`) | — | — |

**English regression.** Every pre-existing test passes unchanged and the English smoke is 30/30. A parity run recorded 83 API responses and 15 LLM prompts of the English narrative on the previous release (`git archive` of `HEAD`) and on the working tree:
**0 unexplained differences** in deterministic English content (explained: additive Polish seeds, Guardian `rules_version`/`subject_hash` hashes of the extended rule set, simulator numbers seeded from the random campaign-id suffix, the intended EN → Polish localization prompt);
14 of 15 English LLM prompts are byte-identical, and English captions are identical on 1,500 random lines (`app/evidence/pl-english-parity.txt`).

### 12.3 Real-model findings (what only the real services could show)

* **Neural voices pad every line.** Raw `pl-PL-ZofiaNeural` audio carries ≈ 0.16 s of leading and ≈ 0.82 s of trailing silence and pauses ≈ 0.8–1.2 s between sentences, so a 4-beat script overran its windows. Fix: exact SSML `mstts:silence` values
  (leading 30 ms, trailing 60 ms, sentence boundary 260 ms, comma 130 ms) plus trimming to a WAV (lead ≈ 0.03 s, trail ≈ 0.08 s); the synthesis cache key is versioned.
* **The first speaking-rate model was 35–60 % too optimistic.** Recalibrated on 24 real lines (`app/evidence/pl-tts-calibration.json`, reproducible with `scripts/calibrate_tts.py`): 5.4 syllables/s, 0.6 s per sentence stop, 0.35 s per comma, +0.11 s per line;
  against the measured audio the shipped model has RMSE 10 %, bias ≈ 0 and a worst under-estimate of 22 %, absorbed by the 1.05 headroom and the ≤ 1.3 × speed-up limit. The offline Polish voice uses the same model. The calibration covers `pl-PL-ZofiaNeural` only.
* **Stage timings** of the final real run (swedencentral): brief 5.4 s · strategy 13.2 s · script 8.3 s · auto-revise 0.8 s · storyboard 95.8 s (4 × `gpt-image-1.5` low quality) · voice-over 1.3 s · render 6–16 s · PL → EN localization incl. English render 20.4 s.
* **Spend of that run: US$0.140** — images 4 × $0.013 = $0.052, Content Safety 57 calls $0.046, LLM 8 calls $0.035, TTS 8 calls $0.007, embeddings and render compute < $0.001. Cumulative AI spend of this whole verification (four Polish smoke runs ≈ $0.55,
  three real-model probes ≈ $0.23, TTS calibration ≈ $0.08) ≈ **US$0.87**, under the US$3 budget; images were generated at low quality and only once per run.
* **Output quality (gpt-5.4-mini / gpt-5.4):** idiomatic Polish questions, territories (*„Cicha pierwsza filiżanka”*, *„Małe partie, duży spokój”*) and scripts, citations from the Polish Brand Book, PL → EN lines such as *„Dawn Roast — a slower start, done right.”*;
  lines that are paraphrased rather than translated get a low back-translation score and are flagged `needs_review` for a human (by design).

### 12.4 Issues found and fixed during verification

* Real services: neural-voice padding and speaking model (above); a missing `WORK_DIR` turned the first render into HTTP 500 (now created on demand); the LLM wrote number words where digits were asked (the directive now says digits; the voice layer spells them).
* Polish typography: `overlays.wrap()` split on NBSP (single-letter words were not glued); captions ended mid-sentence and left one-word cues (*„… palone w małych | partiach.”*) → sentence-aware, comma-preferring, balanced split (English split untouched, checked against `HEAD`).
* Guardian: the bare toast *„Zdrowie!”* was a health claim; trimming used the English words-per-second; the mandatory claim may sit in the supers instead of the voice-over (script and smoke handle both).
* English drift caught by the parity run: brief normalization (trailing-period stripping, splitting on *„ i ”* / *„ oraz ”*) is now gated to non-English; the English-source localization prompt was restored byte-for-byte.
* Terminology aligned with the front end: *claim / claimy* (the EU regulation keeps *„oświadczenia zdrowotne”*), *Specjalista kreatywny*, *Dział prawny / Compliance*.
* Back-translation QA compares Polish word stems, so inflection (*„początek”* / *„początku”*) no longer lowers the score.
* **Found only on the deployed app (both are latent defects of the English release that the Polish verification exposed; fixed with regression tests):**
  * *Audit hash chain broke on Cosmos DB.* After a run whose images came from the AI cache, an audit entry carried `cost_usd: 0.0`; Cosmos DB returns `0.0` as `0`, so the hash recomputed on read no longer matched and `CS-13 audit log verifies` failed (`broken_at` 9, "entry content hash mismatch"). The in-memory repository keeps the float, so no unit test could see it.
    Fix: `entry_hash` hashes integral floats as ints (only the audit hash; `canonical_json` is untouched because signed provenance manifests depend on its exact output). `test_audit_cosmos_numbers` replays entries through a repository that mimics Cosmos and still detects edits to numbers and booleans.
  * *Library semantic search returned nothing.* Deleting an asset or a campaign (the smoke test cleans up after itself) left its vectors in the `library` namespace, and the search took the top-k vectors *before* dropping those whose asset no longer exists, so a few stale vectors pushed every live asset out. Fix: delete the vectors together with the asset / campaign, over-fetch in the search and drop (and heal) stale vectors. `test_library_vectors` (3).
  * The smoke test now retries a step once on a transport error ("connection reset by peer" between the laptop and Azure) instead of failing a whole run on a network blip.

### 12.5 Known limits

* The Polish Playwright journeys on the deployed app are reported in §12.8; the English live evidence (§4–§6) is the release baseline and still stands (the English smoke is 30/30 on the final build).
* The speaking model is calibrated for one voice (`pl-PL-ZofiaNeural`); another voice needs its own constants in `domain/timing.py`.
* Polish legal wording (EU 1924/2006, AI disclosure) is factual **demo content, not legal advice**. Image prompts stay English by design (image models); `/api/features` summaries stay English by contract (the UI translates by feature id).
* Back-translation QA is lexical, not semantic: good paraphrases are flagged for review rather than passed. Content Safety severity offline is a word-list heuristic (the real service is used in azure mode).
* CJK / Arabic captions still need fonts that are not shipped (Latin Extended-A, which covers Polish, is in the bundled DejaVu fonts).
* The English copy *„Seven seeded violations — …”* lists eight items (pre-existing; left untouched to keep English identical — the Polish text says *„Osiem”*).

### 12.6 Evidence files (`app/evidence/`)

`pl-tests.txt` (test / lint / coverage summary) · `pl-smoke-offline.txt` (44/44) · `smoke-en-offline-after-pl.txt` (30/30) · `pl-smoke-hybrid-realmodel.txt` (17/17, real models) · `pl-realmodel-guardian-localization.txt` ·
`pl-tts-calibration.json` (24 real `pl-PL` lines) · `pl-english-parity.txt` · `pl-frames/smoke-pl-caption-frame.png`, `smoke-pl-endcard-frame.png`, `smoke-pl-captions.srt`. Live (deployed app): `pl-smoke-live.txt` (44/44) and `pl-frames-live/` (frames and SRT of the live Polish render).

### 12.7 Reproduce

```bash
cd app
.venv/bin/pytest --cov                                              # 1,206 passed, 8 xfailed · 90 %
.venv/bin/ruff check src tests ../scripts && .venv/bin/mypy         # clean
SPOTLIGHT_MODE=offline .venv/bin/uvicorn spotlight.main:app --port 8102 &
python ../scripts/smoke_test.py --base-url http://127.0.0.1:8102 --lang both         # 44/44 offline
# real Azure AI without touching the live data (hybrid): in-memory repository + local blobs
SPOTLIGHT_MODE=azure AI_BACKEND=azure REPO_BACKEND=memory BLOB_BACKEND=localdir DATA_DIR=./.hybrid COSMOS_ENDPOINT= BLOB_ACCOUNT_URL= \
  AZURE_OPENAI_ENDPOINT=https://<ais>.openai.azure.com/ AI_ENDPOINT=https://<ais>.cognitiveservices.azure.com/ .venv/bin/uvicorn spotlight.main:app --port 8102 &
python ../scripts/smoke_test.py --base-url http://127.0.0.1:8102 --lang pl --expect-mode azure --evidence-dir evidence    # 17/17, ≈ US$0.14
# after the code-only redeploy (live):
python ../scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io --expect-mode azure --lang both --evidence-dir evidence
```

### 12.8 Polish Playwright journeys on the deployed app

`BASE_URL=https://ca-studio-web… .venv/bin/python e2e/journeys_pl.py` (full run with live AI) against the deployed app: **35 of 36 journeys passed** and 33 page states were checked; the one failure was a scanner finding, not a missing translation — the approvals inbox listed the English strategy concept *„The First Quiet Minute”* of the English smoke campaign,
i.e. user / AI-authored content in its own language. The artifact title and the reviewers' comments are now rendered as content (`data-user-content`), the build was redeployed (revision `ca-studio-web--0000004`) and the journey passed on the live app. The same suite without the live-AI steps passes **22 / 22** on the deployed app at 1280×720
(5 journeys that need a produced campaign are skipped there), and **36 / 36** (33 page states) on the offline server; the English journeys pass **18 / 18**. The harness's English-leftover scan also learned to skip technical text that is not UI wording (licence names, model ids such as `neural:pl-PL-ZofiaNeural`, price-tier names, Recharts' own aria-labels).
The 29 Polish screenshots in `deck/assets/screens-pl/` (1600×900) were captured on the deployed app („AZURE · NA ŻYWO”); `deck/assets/screens/` (English) is untouched.

What running against the real services showed that the offline stubs hide: identifiers that only azure mode sends (provider / model / voice ids, job kinds, price tiers) are covered by a unit test that parses the backend sources (`backend-enums.test.ts`); a produced campaign includes ≈ 90 s of keyframe generation (4 images), so the journeys take one timeout knob and assert model-written text by pattern.

## 13. Cinematic motion (CS-25) — AI-generated video on a serverless GPU

**Why.** Reviewers found that the rendered spots *looked like static pictures joined together*: the compositor only moved a virtual camera over one AI keyframe per shot (Ken-Burns), so the hand and the mug never changed. CS-25 makes the shots real video: the approved keyframe becomes the **opening frame of a generated clip** with subject and camera motion, and the same compositor then edits the clips (dissolves, supers, captions, logo, AI badge, voice-over, music, −16 LUFS, end card). Preview (camera moves on stills) stays as the free mode and as the per-shot fallback.

**Status.** **Deployed to Azure and verified live (18–19 Nov 2026).** App: commit `da99d6bf`, image `swarmai-studio/web-studio:git-da99d6b`, revision `ca-studio-web--0000009`. The live smoke run and the English journeys below ran on the preceding revision `0000008` (commit `b6fb366c`); the only difference is the Polish strategy-prompt headings of §13.6, re-verified live. GPU worker: image `swarmai-studio/motion-worker:live1`, app `ca-studio-motion` (unchanged since its first live verification). Design: ARCHITECTURE §7.2, ADR-16/17; contract: `contracts/`; worker: `motion-worker/`.

### 13.1 Why the model is self-hosted

* **Sora 2 is retired.** Across 65 regions the only first-party video model in the catalogue was `sora-2` (swedencentral, eastus2), lifecycle *Deprecated*; creating a deployment is refused (`ServiceModelDeprecated`, "deprecated since 11/02/2026"; the retirement table lists 15 Oct 2026).
* **Partner video models were not enabled.** The fal models in Foundry (Kling v3 Pro, LTX 2.5, MiniMax H3; US$0.08–0.22 per second) run **outside Microsoft's facilities** and Microsoft's DPA does not apply to them.
* So the Studio runs the open **Wan 2.2 TI2V-5B** (Apache-2.0, no territory restrictions; revision pinned) on a **Container Apps serverless A100** in its own environment: data never leaves the tenant. The quota is exactly **one A100 per environment**, so shots render one after another.

### 13.2 What is deployed (added to `rg-swarmai-studio`; every resource tagged)

| Resource | Configuration (verified with `az`, `app/evidence/motion-azure-resources.txt`) |
|---|---|
| Workload profile `gpu-a100` | `Consumption-GPU-NC24-A100` in the existing environment `cae-studio-vh4ojw` |
| `ca-studio-motion` (worker) | 8 vCPU / 64 GiB on `gpu-a100`, **min 0 / max 1, no ingress**, image 7.6 GB, termination grace 600 s; KEDA `azure-queue` scaler with **identity auth** (queue length 1, polling 15 s, cooldown 420 s) |
| `id-studio-motion` | second user-assigned identity. Roles: AcrPull; **Storage Queue Data Contributor on the queue `motion-jobs` only; Storage Blob Data Contributor on the containers `motion-in`, `motion-out`, `motion-models` only** — no role covers `assets`, where the provenance signing key lives (an earlier account-wide scope was found in review and removed; the live smoke run and the role test of §13.6 ran on the narrowed roles) |
| `id-studio-app` | gains Storage Queue Data Contributor **on the queue only** (its Blob role is unchanged) |
| Storage `stvh4ojwexsajyg` | queue `motion-jobs`; containers `motion-in`, `motion-out`, `motion-models` (weights mirror); lifecycle rule `motion-transport-ttl` deletes transport blobs after 3 days; shared-key access still **off** |
| Container Registry | **Standard** (the CUDA worker image is 7.6 GB; Basic is capped at 10 GiB); admin user off |
| Studio app settings | `MOTION_*` (queue, containers, model, price per GPU second); **daily AI cap US$15, per-campaign cap US$5** (were 5 / 2: a cinematic spot meters ≈ US$0.5) |
| Governance tags | RG and **16 of 16 resources** carry `SecurityControl=Ignore` and `SecurityExemption=StorageAccountKeyAccess`; 0 untagged; Bicep `what-if` shows no drift in storage, queue or role assignments |

### 13.3 Measured on the deployed A100 (swedencentral, 18–19 Nov 2026)

| Quantity | Result |
|---|---|
| GPU price | US$0.00108 per second (A100 0.000688 + 8 vCPU + 64 GiB; Azure Retail Prices API, 18 Nov 2026) |
| Throughput | ≈ 0.75–0.82 s of GPU per frame at 1024×576, 20 steps (73 frames 55 s; 109 frames 88 s; 1280×704 92 s). Live spot: 93 frames 72.3 s, 117 frames 94.2 s and 94.8 s |
| Unit cost | ≈ **US$0.02 per generated second**, **US$0.08–0.10 per shot**; the three-shot Dawn Roast spot = 261.3 GPU s = **US$0.28** |
| Cold start | **≈ 3.7–4 min**: image pull (7.6 GB) and node ≈ 2 min, weights from the tenant's Blob mirror 59–64 s, model load 9–12 s; KEDA wakes the worker 16 s after the first message. Enqueue → job start in the role test: 231 s |
| Cost of a wake-up | the app meters an **estimated cold start of US$0.26**; the worker then idles 7 min before it scales to zero (≈ **US$0.45**, *not* in the app's meter). A wake-up with nothing else queued therefore costs ≈ US$0.7 in total |
| Re-render, localization, cut-down | **US$0**: finished clips are cached and reused (Polish localization of a cinematic master: 3 of 3 clips reused, 44 s, +US$0.001) |
| Scale-to-zero | `ScaledToZero` between uses; idle cost of the GPU layer = 0 (ACR Standard +≈ US$15 a month over Basic) |
| What did not help | ACR Premium with artifact streaming did not shorten the cold start (≈ 2 min to worker start either way); reverted to Standard |

### 13.4 Verification

| Gate | Result |
|---|---|
| Worker `motion-worker/tests` (CPU only: fake pipeline + local transport) | **356 passed**, 98 % line + branch coverage |
| Backend `pytest` (offline stubs, real ffmpeg, real OpenCV) | **1,432 passed + 8 strict xfail**, 0 failed; **92 %** coverage (11,578 statements, 928 missed); `ruff check src tests ../scripts e2e` clean; `mypy` no issues in 56 files; `pip-audit` no known vulnerabilities (OpenCV included), `npm audit --omit=dev` 0 |
| Web | `tsc -b` + `vite build` clean; vitest **224 passed** (1 skipped), including the Polish completeness tests |
| Image build (`az acr build`) | `import cv2` runs at build time (`opencv 4.14.0`, manylinux wheel for Python 3.13): a broken wheel fails the build, not the first render |
| Deployment | revision `0000008` Healthy; `/healthz` ok; `/readyz?deep=true` **ready** (repository, Blob, Azure OpenAI, Content Safety, Speech, ffmpeg), `mode=azure`; `/api/motion/status` shows the worker `cold` (scaled to zero) before the run |
| **Live smoke** `SMOKE_CINEMATIC=1 scripts/smoke_test.py --expect-mode azure --lang both --langs de,fr,pl` | **45/45** on revision `0000008` (`app/evidence/motion-smoke-live.txt`); AI spend US$0.8467 for the whole run: motion 0.541, Content Safety 0.124, images 0.104, LLM 0.061, TTS 0.011, render 0.006. After the Polish strategy fix, the Polish narrative (`--lang pl`) ran again on the final revision `0000009`: **17/17**, US$0.13 (`motion-smoke-live-pl-final.txt`) |
| CS-25 step of the smoke test | **3 of 3 shots AI motion, 0 cached, 0 fallback**, 261.3 GPU s = US$0.282 + US$0.259 estimated cold start; **14.9 s MP4, h264/aac 1280×720 @ 25 fps, −16.2 LUFS**, Guardian pass; the manifest names the model, revision, licence, and per shot the seed, prompt digest, GPU seconds and attempts; the step took 536 s including the cold start |
| Playwright, English, on the live app | **18/18** journeys (`app/evidence/motion-e2e-live-en.txt`); the video tab shows *CINEMATIC · AI MOTION 3/3 SHOTS*, the model and licence line, GPU time and cost, and a motion badge per shot |
| Playwright, Polish, on the live app | **35/36** on revision `0000008` (full run with the real pipeline, 34 page states, `motion-e2e-live-pl.txt`), including the Polish render journey that captures the Cinematic panel in Polish (*Tryb renderu · Podgląd / Filmowy*, per-shot estimate in USD). The one failure was not CS-25: the model copied an English prompt heading into a strategy source label (§13.6). Fixed in `da99d6bf`, deployed as revision `0000009`; the brief and strategy journeys then passed **2/2** and four further live strategy runs showed no English heading (`motion-pl-strategy-fix.txt`) |
| Polish UI of the cinematic spot | *FILMOWY · RUCH AI: 3/3 UJĘĆ*, *Model ruchu … licencja Apache-2.0 … w Twoim środowisku Azure*, *DUŻO RUCHU / SUBTELNY RUCH*; no console errors, no English text left in the motion panel |

### 13.5 Is it really film? The motion-quality gate

The first check of the smoke test — frames 0.6 s apart differ — **cannot tell a film from a slideshow**: a Ken-Burns zoom changes every pixel too. So every generated clip is now **measured** (`app/src/spotlight/motion/quality.py`, `scripts/measure_motion.py`): dense optical flow between frames 0.42 s apart, minus the best global affine fit of the flow — what a camera move on a still cannot explain. Calibrated on raw clips (`app/evidence/motion-measurements.txt`): Ken-Burns control **0.10–0.31**, generated clips **0.42–4.9**. Levels: *low* < 0.32 ≤ *subtle* < 1.0 ≤ *rich*.

* A *low* clip gets **one retry** (seed + 1, a prompt that insists on visible motion) when the budget allows; the better of the two is kept; the discarded attempt's GPU time is still metered. The score, level, attempts and retries are stored on the clip asset, in `render.motion`, in the signed manifest and in the UI.
* Live result: the three clips score **1.78 (rich), 0.97 (subtle), 2.13 (rich)** — measured on the server and independently re-measured from the downloaded clips (same values) — against **0.24 / 0.15 / 0.21** for a camera move on the same first frames: **6.5–10×** the slideshow control. No retry was needed; the smoke test asserts a median ≥ 0.5.
* The retry path was **not** triggered live (every clip cleared 0.32); it is covered by `test_motion_quality.py` and `test_motion_orchestrator.py` with a fake worker.

### 13.6 Issues found and fixed during verification

* **Only the real code path showed (the fake pipeline hides them):** the worker's entry point never called `main()`; a structured-log field called `name` collided with `logging`'s own parameter (now positional-only); the Azure SDK's error codes are `str`-mixin enums whose `str()` is not the wire value, so codes such as `PopReceiptMismatch` were not matched until they were compared on their wire value; diffusers 0.40 returns a float numpy array by default, so the worker passes `output_type` explicitly.
* **Least privilege:** the worker first received Blob and Queue roles on the whole storage account, which would have let it read the provenance signing key; the roles were narrowed to the queue and three containers, the old assignments deleted, and a live job (queue receive, weights mirror read, blob write, KEDA wake-up from zero) succeeded on the narrowed roles.
* **Tests:** two timing races in test code — the fake worker advertised `ready` and claimed a job from two different clock readings, and the weights-download test asserted the order in which threads *entered* the transport — were fixed deterministically (event-driven worker; first-wave rendezvous) and proven stable under CPU load (load average 28).
* **UI:** job progress did not reconnect after a dropped SSE stream (now recovered); raw clips (library assets) were counted as unprovenanced deliverables in the provenance view and the pack export (excluded).
* **Polish:** the full Polish journeys flagged *„[Learnings from past performance]”* in a Polish strategy: the prompt of a Polish campaign carried English section headings and the model copied one into the free-text `source` of an insight. The prompt now has Polish headings (English prompt byte-identical, unit-tested; `da99d6bf`); verified live on revision `0000009`. A model-written label can still echo an English label of the user message in rare cases (one *„Brief objective”* in a dozen labels).
* **Deployment mechanics:** one A100 of quota means a new worker revision cannot get a GPU while the previous replica runs, so `scripts/deploy_motion.sh` waits for idle (and counts only replicas that still hold the GPU: scaled-down replicas stay listed as `NotRunning`). The latest revision must never be chosen by alphabetical sort.

### 13.7 Known limits

* **One A100 of quota per environment**: shots render in turn (a three-shot spot ≈ 4.5 min of GPU after a ≈ 4 min cold start); more concurrency needs a quota increase or a second environment.
* **Clips are ≤ 5 s and silent** (the Studio mixes voice-over and music); a 5-billion-parameter open model can still draw an imperfect hand or object. The gate measures *movement*, not beauty: Content Safety checks first / middle / last frame, a shot can fall back to Preview, and a human still approves.
* The silent warm-up after the keyframe step wakes the GPU even if the user never renders; the idle tail (≈ US$0.45 per wake-up) is not in the app's meter.
* The daily cap is **US$15** and the campaign cap US$5 for this verification; restore with `PUT /api/budget/caps {"daily_cap_usd": 5}` and `CAMPAIGN_AI_BUDGET_USD=2`.
* Business-case lever **E1** is still priced on hosted per-second (Sora) meters in `business-case/`; CS-25 is the self-hosted path at ≈ US$0.02 per second and the model was deliberately **not** re-based.
* Partner models (fal: Kling, LTX, MiniMax) would give higher fidelity but are hosted outside Microsoft's facilities; they are not enabled.

### 13.8 Evidence files (`app/evidence/`) and how to reproduce

`motion-azure-resources.txt` (resources, roles, scale rule, tags; `scripts/capture_motion_evidence.sh`) · `motion-smoke-live.txt` (45/45) · `motion-smoke-live-pl-final.txt` (Polish narrative 17/17 on the final revision) · `motion-e2e-live-en.txt` (18/18) · `motion-e2e-live-pl.txt` (35/36) · `motion-pl-strategy-fix.txt` (the one failure, its fix and live re-check) · `motion-render-report-live.json` (`render.motion` of the live spot, per-shot scores) · `motion-measurements.txt` (calibration and live scores).

```bash
cd motion-worker && python -m pytest                                  # 356 passed · 98 %
cd app && .venv/bin/pytest --cov && .venv/bin/ruff check src tests ../scripts e2e && .venv/bin/mypy       # 1,432 passed + 8 xfail · 92 %
(cd web && npm run build && npx vitest run)                           # 224 passed
az acr build --registry <acr> --image swarmai-studio/web-studio:git-<sha> --file Dockerfile app && az containerapp update -g rg-swarmai-studio -n ca-studio-web --image <acr>.azurecr.io/swarmai-studio/web-studio:git-<sha>
AZURE_SUBSCRIPTION_ID=<id> scripts/deploy_motion.sh                   # GPU worker image; waits until the queue is idle
SMOKE_CINEMATIC=1 python scripts/smoke_test.py --base-url <url> --expect-mode azure --lang both --langs de,fr,pl --timeout 900   # 45/45, ≈ US$0.85
python scripts/measure_motion.py clip.mp4 [more.mp4 …]                # non-rigid motion vs. a Ken-Burns control
AZURE_SUBSCRIPTION_ID=<id> scripts/capture_motion_evidence.sh         # read-only evidence of the Azure resources
```
