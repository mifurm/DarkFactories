# SwarmAI Commercial Studio — "Spotlight"

**Brief → brand-safe, localized, measurable commercials.** Spotlight is an AI crew (Strategist, Copywriter, Art Director,
Director, Sound Designer, Localizer, **Brand Guardian**, Media Analyst) that turns a marketing brief into a **rendered MP4
commercial** (keyframes from `gpt-image` brought to life as **AI-generated video clips with real subject and camera motion** —
*Cinematic*, on a serverless A100 GPU inside your own Azure tenant — or camera moves on the stills in *Preview*; voice-over,
burned-in captions + SRT, music bed, logo, AI-disclosure badge, brand end card, loudness-normalised) plus cutdowns, aspect-ratio
reframes and localized versions — with **governance as the
differentiator**: claims library, rights registry, hash-chained approvals/audit, signed provenance manifests, a deterministic
Brand Guardian that blocks violations before approval, and cost guardrails that fail closed.

All 25 Release-1 features (**CS-01 … CS-25**) are implemented end to end (backend + API + UI + tests) and deployed to Azure.
Everything runs on a **fictional sample brand** (Northwind Coffee Roasters, campaign *Dawn Roast*); see "Real vs simulated".

| | |
|---|---|
| Live app | `https://ca-studio-web.yellowgrass-9740f562.swedencentral.azurecontainerapps.io` (Azure Container Apps, swedencentral) |
| Evidence | [REPORT-TEST-AND-DEPLOYMENT.md](REPORT-TEST-AND-DEPLOYMENT.md) (tests, coverage, smoke results, p50/p95, spend, security) |
| Docs | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [FEATURES.md](FEATURES.md) · [business-case/](business-case/README.md) · [deck/](deck) |
| API | `/docs` (Swagger UI, bundled locally) · `/openapi.json` |

## Try it (2 minutes)

1. Open the live URL → **Dashboard** → *Dawn Roast — Launch* → **Open workspace** (or **New brief → Load sample**).
2. **Brief** → the Briefing agent asks ≤ 3 clarifying questions and flags the client's risky mandatory line
   (*"Dawn Roast cures morning anxiety."*) and an unlicensed music reference (*"Sunrise Anthem"*) **before** any spend.
3. **Strategy → Script → Storyboard → Voice & audio → Video**: each stage is a job with live progress; the Brand Guardian
   **blocks** the script (prohibited claim, missing caffeine disclaimer, unlicensed track) — press **Auto-revise** and watch it
   rewrite the claim and swap in a licensed library track.
4. **Video** plays the rendered 15 s MP4 (ffprobe-verified H.264/AAC, −16 LUFS). **Formats & cutdowns** adds 9:16 / 1:1 / 4:5 and a 6 s
   cutdown; **Localization** adds German/French/Polish with glossary + back-translation QA; **Provenance** verifies the signed
   manifest and runs a **tamper test**.
5. **Approvals** (roles per gate; approval is refused while the Guardian has open failures) → **audit chain verified**.
6. **Variants & bandit**, **Insights**, **Media planner**, **Cost meter**, **ROI & ACR** (the same model as the PRD/deck: ROI, NPV, payback, Azure ACR by service and by expansion lever, five customer tiers, *Expansion off/on* switch), **Feature map**.

## Architecture in one picture

```
 React 19 + Vite + TS (Tailwind 4, TanStack Query, Recharts)          feature slices auto-discovered (import.meta.glob)
              │  /api/*  (JSON, SSE job progress)
 ┌────────────▼──────────────────────────────────────────────────────────────────────────────┐
 │ FastAPI (Python 3.13) — app factory auto-discovers features/csNN_*/  →  /api/features        │
 │  routers: CS-01 … CS-25   ·   deps: roles (X-Studio-Role) · rate limits · budget guard       │
 │  core: repo (Cosmos│memory) · blobs (Azure│localdir│memory) · job runner (persisted, SSE)    │
 │        AI clients (Azure OpenAI chat/image/TTS/embeddings · Content Safety · AI Speech)       │
 │        meter + BudgetGuard · audit hash-chain · provenance (Ed25519) · vector index          │
 │  domain: guardian · claims · rights · colors · disclosure · script · localize · bandit · …    │
 │  video: compositor (Pillow/numpy frames → ffmpeg) behind a VideoProvider interface            │
 │  motion: MotionClient (queue + blob contract v1) · planner · clip cache · offline animator    │
 └───────────┬───────────────┬───────────────┬───────────────┬───────────────────────────────┘
        Cosmos DB        Blob Storage     Azure OpenAI     Content Safety / AI Speech     App Insights
       (serverless,      (private, RBAC)  gpt-5.4(-mini),  (text, image, protected         (OpenTelemetry,
        data-plane RBAC)  + Queue motion-  gpt-image-1.5,   material, Prompt Shields,        Entra-authenticated)
                          jobs (CS-25)     tts-hd, embed    neural voices)
                               │
                               └─► ca-studio-motion: Wan 2.2 image→video on a serverless A100 (scale-to-zero, no ingress, own identity)
 Identity: user-assigned managed identities (app + GPU worker) for every call — no keys, no connection strings, no secrets.
```

* **Offline mode** (`SPOTLIGHT_MODE=offline`, the default when no Azure endpoints are configured) runs the *same code paths*
  with deterministic stubs (procedural images, synthesized speech, in-memory repo) — used by the unit/API tests and for
  development without Azure. Offline spend is *simulated* at the same list prices so the budget guard behaves identically.
* **Adding a feature** = drop a `features/csNN_name/__init__.py` exporting `FEATURE = Feature(...)` (+ a `web/src/features/csNN-*/index.tsx`
  exporting `feature`); both the API and the SPA discover it. `/api/features` and the **Feature Map** page list what is live.

## Feature map

| ID | Feature | UI | API |
|---|---|---|---|
| CS-01 | Brand kit & Brand Brain (versioned kit, embeddings, cited retrieval, learnings) | `/brand` | `/api/brand/*` |
| CS-02 | Claims & compliance library (approved / prohibited / needs-substantiation, packs) | `/claims` | `/api/claims/*` |
| CS-03 | Rights & consent registry (music, talent, stock; windows, territories, AI consent) | `/rights` | `/api/rights/*` |
| CS-04 | Brief intake & Briefing agent (≤ 3 questions, completeness, injection-safe) | `/campaigns/new`, Brief tab | `/api/campaigns/{id}/brief/*` |
| CS-05 | Strategy agent (3+ territories grounded with citations) | Strategy tab | `/api/campaigns/{id}/strategy/*` |
| CS-06 | Script & copy agent (6/15/30 s beats, mandatories verbatim) | Script tab | `/api/campaigns/{id}/script/*` |
| CS-07 | Storyboard & art direction (style bible, `gpt-image` keyframes, hero quality gated) | Storyboard tab | `/api/campaigns/{id}/storyboard/*` |
| CS-08 | Spot compositor (ffmpeg MP4, captions, music, end card, −16/−23 LUFS; Preview = camera moves on stills) | Video tab | `/api/campaigns/{id}/spot/*` |
| CS-09 | Voice & audio (tts-hd / neural voices, beat-timed VO, SRT, licensed procedural music) | Voice & audio tab | `/api/campaigns/{id}/audio/*` |
| CS-10 | Localization (8 languages, glossary/DNT, back-translation QA, local-market Guardian) | Localization tab | `/api/campaigns/{id}/localization/*` |
| CS-11 | Format factory (16:9 / 9:16 / 1:1 / 4:5, 6/15/30 s cutdowns, version tree) | Formats tab | `/api/campaigns/{id}/formats/*` |
| CS-12 | Brand Guardian (8 checks, scored report, fixes, auto-revise, waivers) | `/guardian`, Guardian tab | `/api/guardian/*`, `/api/campaigns/{id}/guardian/*` |
| CS-13 | Approvals & audit trail (gates, roles, SLAs, hash-chained log) | `/approvals`, Approvals tab | `/api/approvals/*`, `/api/campaigns/{id}/audit` |
| CS-14 | AI disclosure & provenance (signed manifest, tamper-evident, labels, pack) | Provenance tab | `/api/provenance/*` |
| CS-15 | Budget & cost guardrails (metering, caps that fail closed, premium approval) | `/cost` | `/api/budget/*` |
| CS-16 | Pre-flight scorecard (synthetic panel + heuristics, labelled simulated) | Scorecard tab | `/api/campaigns/{id}/scorecard` |
| CS-17 | Variant engine (matrix, Thompson sampling, z-test, auto-pause) | `/experiments` | `/api/experiments/*` |
| CS-18 | Performance ingestion & insights (CSV, simulated connectors, insights → Brand Brain) | `/performance` | `/api/performance/*` |
| CS-19 | Campaign planner (diminishing-returns media mix, p10–p90 ranges) | `/planner` | `/api/planner/*` |
| CS-20 | Creative studio UI (dashboard, workspace, stage stepper) | `/`, `/campaigns/:id/:tab` | `/api/studio/*` |
| CS-21 | Asset library / DAM (private blobs, semantic search, versions, rights links) | `/library` | `/api/library/*` |
| CS-22 | Collaboration & integrations (roles, Teams/Slack webhooks, campaign pack) | `/team` | `/api/team/*`, `/api/campaigns/{id}/export` |
| CS-23 | ROI & ACR calculator (vendored business-case model v1.1.0: scenarios, expansion levers E1–E4, 5 tiers, live comparison) | `/roi` | `/api/roi/*` |
| CS-24 | Observability, security & IaC (health, metrics, OpenTelemetry, Bicep) | `/ops` | `/healthz`, `/readyz`, `/api/ops/*`, `/api/meta`, `/api/usage` |
| CS-25 | **Cinematic motion** — generative video: each keyframe becomes an AI clip (Wan 2.2 on a serverless A100), estimate + budget check, GPU warm-up, per-shot fallback | Video tab (render quality), Storyboard tab (motion prompt) | `/api/motion/*`, `/api/campaigns/{id}/spot/estimate`, `…/spot/render {quality}` |

## Cinematic motion — from slideshow to film

*Preview* is the compositor animating stills (Ken-Burns / pan / parallax): fast, free, and still a slideshow. *Cinematic* turns every
approved keyframe — the **opening frame** of the shot — into a **generated video clip** with real subject and camera motion
(a hand lifts the mug, steam curls, light moves, the camera pushes in), then the same compositor edits the clips: dissolves, supers,
captions, logo, AI badge, voice-over + music, EBU R128, end card.

```
Studio ─ keyframe + motion prompt ─► Storage Queue ──(KEDA, identity auth)──► ca-studio-motion  (Wan 2.2 TI2V-5B, serverless A100, min 0 / max 1, no ingress)
   ▲                                  Blob motion-in/out/models                      │ clip.mp4 + status + result
   └──────────── clip asset (library) ◄──────────────────────────────────────────────┘ → compositor → spot (Guardian frame checks, signed manifest)
```

| | |
|---|---|
| Model | **Wan 2.2 TI2V-5B**, Apache-2.0 (no territory restrictions), pinned revision; weights mirrored into the tenant's Blob. Azure OpenAI Sora 2 is **retired** (2 Nov 2026) and no other first-party video model exists, so the model runs in *your* environment: data never leaves the tenant |
| Compute | Container Apps **serverless A100** (`gpu-a100` profile of the Studio environment), 8 vCPU / 64 GiB, scale-to-zero, per-second billing: **US$0.00108 / s** (A100 0.000688 + vCPU + memory, swedencentral retail) |
| Measured | 1024×576, 20 steps: **≈ 0.75 s of GPU per frame** (3 s clip = 55 s, 4.9 s clip = 95 s). Cold start **≈ 3.7 min** (node + image ≈ 2 min, weights from the Blob mirror ≈ 1 min, model load 11 s); KEDA starts the worker 16 s after the first message |
| Cost | ≈ **US$0.08–0.10 per shot**, **≈ US$0.35–0.45 per four-shot spot** (+ ≈ US$0.26 when the worker has to cold-start); a cached shot — re-render, localization, cut-down — is **US$0** and calls no GPU |
| Limits | **One A100 per environment** (quota) → shots render one after another; ≤ 5 s per clip; clips are silent (Studio mixes VO + music); a generative model can still draw an imperfect hand → Content Safety frame checks, per-shot fallback to the still, human approval gate |
| Governance | Worker identity = queue + blob only (no Cosmos, no OpenAI); estimate and budget check before spending; actual GPU seconds metered as kind `motion`; manifest records model, revision, licence, host, per-shot seed + prompt digest; AI badge burned in |

```bash
# local, no GPU, no Azure: the Studio's offline mode animates keyframes procedurally (MOTION_MODE=stub is the offline default)
SPOTLIGHT_MODE=offline .venv/bin/uvicorn spotlight.main:app --port 8102
# the real worker contract on your laptop (fake pipeline + local-dir transport, CPU only)
cd motion-worker && MOTION_PIPELINE=fake MOTION_TRANSPORT=local MOTION_LOCAL_DIR=/tmp/motion python -m motion_worker
# deploy / update the GPU worker (ACR build + revision switch while the queue is idle — the environment holds ONE A100)
scripts/deploy_motion.sh [tag]
```
Settings (env, set by Bicep): `MOTION_MODE` (`auto|azure|local|stub|off`), `MOTION_QUEUE_URL`, `MOTION_QUEUE_NAME`, `MOTION_BLOB_ACCOUNT_URL`,
`MOTION_IN_CONTAINER`, `MOTION_OUT_CONTAINER`, `MOTION_STEPS` (20), `MOTION_GUIDANCE` (4.0), `MOTION_HIGH` (1280×704), `MOTION_PRICE_PER_GPU_SECOND`
(0.00108), `MOTION_TIMEOUT_S`, `MOTION_COLD_START_S`. Contract and schemas: [contracts/](contracts/README.md) · worker: [motion-worker/](motion-worker/README.md) ·
design: [ARCHITECTURE.md §7.2](ARCHITECTURE.md), ADR-16/17.

## Run it locally

```bash
cd app
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"        # needs ffmpeg on PATH for rendering (brew install ffmpeg)
(cd web && npm ci && npm run build)                                    # builds the SPA into web/dist (served by FastAPI)

# offline mode: deterministic stubs, in-memory data, no Azure needed
SPOTLIGHT_MODE=offline .venv/bin/uvicorn spotlight.main:app --port 8102        # → http://127.0.0.1:8102
# or the Vite dev server with hot reload (proxy → 8102)
(cd web && npm run dev)                                                # → http://127.0.0.1:5102

# against real Azure resources (az login first; your user needs the data-plane roles Bicep grants)
SPOTLIGHT_MODE=azure COSMOS_ENDPOINT=… BLOB_ACCOUNT_URL=… AZURE_OPENAI_ENDPOINT=… AI_ENDPOINT=… \
  .venv/bin/uvicorn spotlight.main:app --port 8102
```

### Tests

```bash
cd app
.venv/bin/pytest --cov                                  # 1,206 passed + 8 strict xfail (97 English baseline + Polish / regression), ~1–2 min, offline stubs + real ffmpeg
.venv/bin/pytest tests/test_pl_*.py -q                  # the Polish suites only (Guardian, i18n contract, pipeline, platform, seed, timing)
.venv/bin/ruff check src tests ../scripts e2e && .venv/bin/mypy
(cd web && npm run build)                               # tsc -b (strict) + vite build
# browser journeys (+ 1600×900 deck screenshots) against any running instance:
/path/to/playwright-venv/bin/python e2e/journeys.py --base-url http://127.0.0.1:8102 --screens ../deck/assets/screens
# end-to-end smoke of a DEPLOYED instance (real Azure OpenAI / Cosmos / Blob; ≈ US$0.16–0.17 per English run, ≈ US$0.14 for the Polish steps):
python ../scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io --expect-mode azure --langs de,fr,pl      # English narrative + Polish PL-* steps
python ../scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io --lang pl [--evidence-dir ../evidence]  # Polish steps only (+ saves the extracted frames)
python ../scripts/load_test.py  --base-url https://<app>.azurecontainerapps.io          # p50/p95 on read endpoints
```

## Languages

The Studio speaks **English and Polish**. Two things are independent:

* **UI / message language** — what the person at the keyboard reads (labels, errors, Guardian explanations, audit lines, job progress, notifications). Resolved per request:
  `?lang=pl` → `X-UI-Lang` header → `Accept-Language` → `en`. `/api/meta` lists `languages`, `default_language` and the resolved `language`; every response carries `Content-Language`.
  The web app's language switcher sets `X-UI-Lang`.
* **Content language** — the language a campaign is *made in*: `campaign.language` (always returned; defaults to the request language when the campaign is created). It decides the
  output language of every LLM call (explicit language directive; offline stubs write Polish too), the Guardian rule set (Polish claims pack, forbidden words, disclaimers), the voice-over
  voice (`pl-PL` neural voices), caption/end-card typography and the AI-disclosure badge ("Wygenerowano przez AI").

How it works: deterministic text is stored as a **stable code + params** and rendered when it is read, in the reader's language — Guardian findings, script timing issues, voice warnings,
audit one-liners, job titles/progress/errors, approval stages, webhook cards, scorecard tips, insight sentences, provenance summaries (the signed manifest's machine fields stay English).
Error responses keep `error.code` stable and localize `message`/`hint`. Content (briefs, scripts, claims, Brand Book, glossary) is produced and stored *in* its language with a `lang` tag.
Polish specifics: inflection-aware, diacritic-insensitive claim patterns (`zdrowa`/`zdrowy`/`zdrowie`, ł→l, "najlepsza kawa na świecie" without Polish letters), replacements that agree in
gender/case, numbers/units/dates read as inflected words for the voice (`spoken_text`), NBSP after single-letter words and caption cues that break at sentence ends / commas (never a one-word cue), a speaking-rate model calibrated on real `pl-PL-ZofiaNeural`
audio (line-too-long check, trimming, beat rebalancing), bidirectional localization with glossary / do-not-translate enforcement and a back-translation check that compares Polish word stems.

**Add a language** (e.g. `de`):

1. `app/src/spotlight/i18n/messages_de.py` — copy `messages_en.py` (same keys, same `{placeholders}`, plural dicts with the CLDR forms of the language); register it in `i18n/catalog.py` (`CATALOGS`) and
   `i18n/locale.py` (`SUPPORTED`, `LANGUAGE_NAMES`). `tests/test_pl_i18n.py::test_catalog_parity_…` fails until keys/placeholders/plural forms match.
2. Content: a Brand Book + kit overlay (`seed/data.py`, `KIT["i18n"]["de"]`), a claims pack (`seed/<lang>_claims.py`, patterns on `fold()`-ed text, one rule per English `concept`), forbidden words + replacements.
3. Language code: `domain/text.py::detect_lang`/`syllables`, `domain/timing.py` speaking model (measure real synthesis with `scripts/calibrate_tts.py --lang de --voice neural:<voice> --lines lines.txt`, ≈ US$0.02),
   `i18n/directive.py`
   (LLM output-language directive), `core/ai/voices.py` (default voice per language), `core/ai/stubs.py` (offline copy), `domain/localize.py` (phrasebook, market notes, glossary translations).
4. Typography: fonts must contain the alphabet (DejaVu ships Latin/Cyrillic/Greek); NBSP rules in `domain/polish.py`-style module if the language needs them.
5. Tests: golden positives **and** negative controls for the claims pack, catalog parity, one end-to-end pipeline run (offline), smoke steps.

Known limits: CJK/Arabic need fonts that are not shipped; the English UI strings of the web app live in `app/web/src/i18n` (owned by the front end); legal wording is demo content, not legal advice.


## Deploy to Azure (idempotent)

```bash
export AZURE_SUBSCRIPTION_ID=<subscription-id>          # az login && azd auth login first
scripts/deploy.sh                # azd provision (Bicep) → tag platform-created resources → remote ACR build → azd deploy web
scripts/deploy.sh --app-only     # code-only redeploy (~3.5 min)
scripts/teardown.sh              # azd down --force --purge
```

`azd provision` creates (resource group `rg-swarmai-studio`, `swedencentral`): user-assigned managed identity · Log Analytics
(1 GB/day cap) · Application Insights (Entra-only ingestion) · Container Registry (remote build, no local Docker) · Container
Apps environment + app (1 vCPU / 2 GiB, 1–2 replicas, HTTPS, system-managed scale rules) · Cosmos DB serverless (22 containers,
data-plane RBAC only, local auth disabled) · Storage (private container, shared-key access **off**) · Azure AI Services
(`gpt-5.4-mini`, `gpt-5.4`, `text-embedding-3-small`, `tts-hd`, `gpt-image-1.5`, `gpt-image-1-mini`; local auth disabled) and
the role assignments (MI + signed-in user). The resource group and **every** taggable resource carry the governance tags
`SecurityControl=Ignore`, `SecurityExemption=StorageAccountKeyAccess`, `project=SwarmAI`, `concept=studio`, `owner=michalfu`,
`environment=demo` (one `commonTags` object in `infra/main.bicep`). Details, verification output and the (unused) key-access
exemption rationale are in the report.

Configuration (all via environment variables, set by Bicep; **no secrets**): `SPOTLIGHT_MODE`, `AZURE_CLIENT_ID`,
`COSMOS_ENDPOINT`, `BLOB_ACCOUNT_URL`, `AZURE_OPENAI_ENDPOINT`, `AI_ENDPOINT`, `MODEL_*` deployment names,
`DAILY_AI_BUDGET_USD` (default 15 — Cinematic spots cost ≈ US$0.4–0.6 of GPU time; it was 5), `CAMPAIGN_AI_BUDGET_USD` (default 5; was 2), `MOTION_*` (see *Cinematic motion*), `APPLICATIONINSIGHTS_CONNECTION_STRING`.
See `app/src/spotlight/config.py`. The GPU layer adds: the `gpu-a100` workload profile (Studio environment), `ca-studio-motion`, a second managed identity `id-studio-motion`, Storage Queue `motion-jobs`, blob containers `motion-in` / `motion-out` / `motion-models` (3-day lifecycle on the transport blobs) and Container Registry **Standard** (the worker image is 7 GiB). Deploy the worker with `scripts/deploy_motion.sh`; revert the budget raise with `PUT /api/budget/caps {"daily_cap_usd": 5}` and `CAMPAIGN_AI_BUDGET_USD=2` if you do not use Cinematic.

## Security, governance & responsible AI

* **Keyless.** Managed identity → Cosmos / Blob / Azure OpenAI / Content Safety / Speech / App Insights. No account keys, SAS tokens or secrets in code, images, Bicep outputs or app settings.
* **Private data plane by API.** Blobs are never public; media is streamed through the API (`/api/library/assets/{id}/content`, range requests) with `nosniff`, CSP, `X-Frame-Options`, request-size and per-IP/global rate limits; webhooks are SSRF-guarded (https + allow-list + public-IP only).
* **Prompt-injection hygiene.** Uploaded briefs/guidelines are untrusted data: wrapped in delimiters, screened with Azure AI Content Safety *Prompt Shields*, quarantined on attack.
* **Guardian before approval.** Deterministic rules first (claims, forbidden words, palette ΔE, logo size/clear space, rights windows/territories/AI consent, disclosure, accessibility); Content Safety on every text/image; the LLM only assists (tone, rewrites). Approvals are *refused* with open blocking findings; waivers need Legal/Admin + justification and are audit-logged.
* **Provenance & disclosure.** Every rendered spot gets an Ed25519-signed, hash-based manifest (asset + ingredient hashes, models, prompt digests, approvals, rights, audit anchor) and a sidecar JSON; EU/UK/US + platform label requirements are computed; burned-in "AI-generated" badge where required. Verification fails on any byte flipped in the file or manifest.
* **Cost safety.** Every call is metered and priced; daily + per-campaign caps **fail closed** (HTTP 402 with a clear message); hero-quality images need an explicit premium approval; prompt-hash caching avoids repeat spend.
* **Roles.** Admin, Brand Manager, Creative Director, Creative, Legal, Agency guest — enforced server-side. In the demo they are self-declared (`X-Studio-Role`); production uses Entra ID app roles (Container Apps built-in auth is an optional Bicep switch).

## Real vs simulated

| Real (in Azure mode) | Simulated / illustrative |
|---|---|
| Azure OpenAI chat + structured output, image generation, TTS, embeddings; Content Safety; AI Speech voices | Brand, claims library, rights registry entries, talent, people, campaigns — all fictional |
| Cosmos DB, Blob Storage, managed identity, RBAC, App Insights telemetry | Ad platforms (Google/Meta/TikTok/LinkedIn connectors), audience panel, bandit "ground truth", media-planner curves, performance history |
| ffmpeg rendering, loudness normalisation, ffprobe verification, captions/SRT, procedural CC0-style music | **Live-action footage** (shots are generated, not filmed); Cinematic clips are generated by an open model, so imperfect hands/objects can occur — hence the frame checks, fallback and human approval |
| **Generative video: Wan 2.2 on a real serverless A100**, queue + blob contract, KEDA scale-from-zero, metered GPU seconds (CS-25) | Offline mode: the clips come from a procedural animator, not a model (labelled "offline motion simulator") |
| Hash-chained audit log, Ed25519 provenance signatures, approvals & role enforcement | Provenance format is "C2PA-style" (hash-based, signed) — not a certified C2PA Content Credential; signing key is app-managed (production: Key Vault/HSM) |
| Metered AI spend (list-price estimates) | ROI/ACR figures: illustrative business case with labelled assumptions (see `business-case/`) |

## Known limitations

CJK / Arabic captions need extra fonts (not shipped; Latin, Cyrillic, Greek are). Catalog-scale content, audience
personalization and the clean-room data platform are **expansion levers** modelled in the ROI calculator (E1–E4; Base = off), not Release-1 code (E1, generative video for *hero footage*, is priced on hosted per-second meters; the in-product Cinematic motion of CS-25 is a different, self-hosted path). The vendored business-case model is re-synced with `scripts/sync_business_case.py` (copies `model.py`, `assumptions.json`, `outputs.json` together and verifies parity).
**Cinematic motion limits:** one A100 per environment (shots render sequentially), ≈ 3.7 min cold start (hidden by the warm-up and a 7-minute cooldown), clips ≤ 5 s and silent, no guarantee of perfect hands or product details — a flagged or failed shot falls back to the still. The partner video models in Foundry (fal: Kling, LTX, MiniMax) are **not enabled**: they run outside Microsoft's facilities and the Microsoft DPA does not apply.
Rate limits are per replica (in-process). The demo identity is self-declared. See ARCHITECTURE.md → *Implemented vs target*.
Polish (pl): **deployed and verified live** (smoke 44/44 on the deployed app incl. 14 Polish steps; 1,206 backend tests, hybrid run on the real models — see REPORT → *Polish localization*). Neural voices are
the default for Polish; the speaking-rate model was calibrated for `pl-PL-ZofiaNeural` only (another voice may need its own constants). Polish legal wording (EU 1924/2006 health claims, AI disclosure) is factual demo content, not legal advice.
