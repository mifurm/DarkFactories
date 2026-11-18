# SwarmAI Commercial Studio — "Spotlight"

**Brief → brand-safe, localized, measurable commercials.** Spotlight is an AI crew (Strategist, Copywriter, Art Director,
Director, Sound Designer, Localizer, **Brand Guardian**, Media Analyst) that turns a marketing brief into a **rendered MP4
commercial** (keyframes from `gpt-image`, motion, voice-over, burned-in captions + SRT, music bed, logo, AI-disclosure badge,
brand end card, loudness-normalised) plus cutdowns, aspect-ratio reframes and localized versions — with **governance as the
differentiator**: claims library, rights registry, hash-chained approvals/audit, signed provenance manifests, a deterministic
Brand Guardian that blocks violations before approval, and cost guardrails that fail closed.

All 24 Release-1 features (**CS-01 … CS-24**) are implemented end to end (backend + API + UI + tests) and deployed to Azure.
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
 │  routers: CS-01 … CS-24   ·   deps: roles (X-Studio-Role) · rate limits · budget guard       │
 │  core: repo (Cosmos│memory) · blobs (Azure│localdir│memory) · job runner (persisted, SSE)    │
 │        AI clients (Azure OpenAI chat/image/TTS/embeddings · Content Safety · AI Speech)       │
 │        meter + BudgetGuard · audit hash-chain · provenance (Ed25519) · vector index          │
 │  domain: guardian · claims · rights · colors · disclosure · script · localize · bandit · …    │
 │  video: compositor (Pillow/numpy frames → ffmpeg) behind a VideoProvider interface            │
 └───────────┬───────────────┬───────────────┬───────────────┬───────────────────────────────┘
        Cosmos DB        Blob Storage     Azure OpenAI     Content Safety / AI Speech     App Insights
       (serverless,      (private, RBAC)  gpt-5.4(-mini),  (text, image, protected         (OpenTelemetry,
        data-plane RBAC)                  gpt-image-1.5,   material, Prompt Shields,        Entra-authenticated)
                                          tts-hd, embed    neural voices)
 Identity: one user-assigned managed identity for every call — no keys, no connection strings, no secrets.
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
| CS-08 | Spot compositor (ffmpeg MP4, captions, music, end card, −16/−23 LUFS) | Video tab | `/api/campaigns/{id}/spot/*` |
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
.venv/bin/pytest --cov                                  # 97 tests, ~45 s, offline stubs + real ffmpeg (88 % line coverage)
.venv/bin/ruff check src tests ../scripts e2e && .venv/bin/mypy
(cd web && npm run build)                               # tsc -b (strict) + vite build
# browser journeys (+ 1600×900 deck screenshots) against any running instance:
/path/to/playwright-venv/bin/python e2e/journeys.py --base-url http://127.0.0.1:8102 --screens ../deck/assets/screens
# end-to-end smoke of a DEPLOYED instance (real Azure OpenAI / Cosmos / Blob; ≈ US$0.16–0.17 per run):
python ../scripts/smoke_test.py --base-url https://<app>.azurecontainerapps.io --expect-mode azure --langs de,fr,pl
python ../scripts/load_test.py  --base-url https://<app>.azurecontainerapps.io          # p50/p95 on read endpoints
```

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
`DAILY_AI_BUDGET_USD` (default 5), `CAMPAIGN_AI_BUDGET_USD` (default 2), `APPLICATIONINSIGHTS_CONNECTION_STRING`.
See `app/src/spotlight/config.py`.

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
| ffmpeg rendering, loudness normalisation, ffprobe verification, captions/SRT, procedural CC0-style music | Video *generation* models (Sora-2 is deprecated in this region): a `VideoProvider` interface is in place; the compositor animates keyframes |
| Hash-chained audit log, Ed25519 provenance signatures, approvals & role enforcement | Provenance format is "C2PA-style" (hash-based, signed) — not a certified C2PA Content Credential; signing key is app-managed (production: Key Vault/HSM) |
| Metered AI spend (list-price estimates) | ROI/ACR figures: illustrative business case with labelled assumptions (see `business-case/`) |

## Known limitations

CJK / Arabic captions need extra fonts (not shipped; Latin, Cyrillic, Greek are). Generative video, catalog-scale content, audience
personalization and the clean-room data platform are **expansion levers** modelled in the ROI calculator (E1–E4; Base = off), not Release-1 code. The vendored business-case model is re-synced with `scripts/sync_business_case.py` (copies `model.py`, `assumptions.json`, `outputs.json` together and verifies parity).
Rate limits are per replica (in-process). The demo identity is self-declared. See ARCHITECTURE.md → *Implemented vs target*.
