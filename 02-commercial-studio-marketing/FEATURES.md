# SwarmAI Commercial Studio ("Spotlight") — Feature Backlog

> **Contract.** The 24 Release-1 features below (**CS-01 … CS-24**) are the product contract between Product, Engineering and the customer.
> IDs and names are frozen; descriptions and acceptance criteria may be sharpened, never dropped.
> **Engineering edits only the `Status` and `Evidence` cells of the status board** (evidence = test names, commit-free pointers such as
> `tests/test_guardian.py::test_blocks_prohibited_claim`, smoke-test step names, screenshot names). Everything else is owned by Product.
>
> Companion documents: [PRD.md](PRD.md) (requirements `FR-*`, `NFR-*`, KPIs `KPI-*`) · [ARCHITECTURE.md](ARCHITECTURE.md) · [business-case/](business-case/README.md).

> **Delivery status (verified 17–18 November 2026).** All 24 features are **Deployed ✔** on Azure (`rg-swarmai-studio`, `swedencentral`; live at <https://ca-studio-web.yellowgrass-9740f562.swedencentral.azurecontainerapps.io>, synthetic data, self-declared demo roles).
> Evidence: **97 automated tests** (88 % line coverage; domain modules 88–100 %), **18/18** Playwright journeys on the live app, **30/30** live smoke checks with real Azure OpenAI, Content Safety, Cosmos DB and Blob, light-load **p50 554 ms / p95 1.4 s** with 0 errors, ≈ **US$0.17** of AI spend per full smoke run and ≈ **US$30 a month** idle run cost — see [REPORT-TEST-AND-DEPLOYMENT.md](REPORT-TEST-AND-DEPLOYMENT.md) and `app/evidence/`.
> Not in the slice: generative video (lever E1) and the other expansion levers E2–E4 are *modelled* in the ROI & ACR calculator (CS-23), not built — they are Release 2+ below.

## Status board

Status values: **Planned** → **In progress** → **Implemented** (code + unit tests) → **Tested** (unit + API/behavioural tests green, evidence listed) → **Deployed ✔** (the post-deploy smoke test exercised it against Azure).

| ID | Feature | Epic | Priority | Status | Evidence |
|----|---------|------|----------|--------|----------|
| CS-01 | Brand Kit & Brand Brain | A — Brand Brain & governance data | P0 | **Deployed ✔** | tests/test_features_api.py::test_cs01_brand_brain_retrieval_cites_sources_ingests_documents_and_versions_the_kit · test_domain.py::test_document_ingestion_extracts_text_from_md_docx_pdf_and_rejects_other_types · smoke: *CS-01 Brand Brain retrieval with citations* · screens/03-brand-brain.png |
| CS-02 | Claims & Compliance Library | A — Brand Brain & governance data | P0 | **Deployed ✔** | test_features_api.py::test_cs02_claims_library_filters_checks_and_is_editable_by_legal_only · test_guardian.py (claims/disclaimer/EU-market tests) · smoke: *CS-02 claims library* · screens/04-claims-library.png |
| CS-03 | Rights & Consent Registry | A — Brand Brain & governance data | P0 | **Deployed ✔** | test_features_api.py::test_cs03_rights_registry_blocks_out_of_rights_use_alerts_on_expiry_and_revokes · test_guardian.py (unlicensed, expired consent, territory/channel/AI-consent) · smoke: *CS-03 rights registry* · screens/05-rights-registry.png |
| CS-04 | Brief intake & Briefing agent | B — Creative pipeline | P0 | **Deployed ✔** | test_pipeline_api.py::test_briefing_agent_asks_three_clarifying_questions_and_normalizes_the_brief, ::test_prompt_injection_in_a_brief_is_rejected · test_domain.py::test_brief_parsing_normalisation_and_completeness_drive_the_clarifying_questions · smoke: *CS-04 briefing agent* · screens/02-brief-wizard.png |
| CS-05 | Strategy agent | B — Creative pipeline | P0 | **Deployed ✔** | test_pipeline_api.py::build_to_script (3–5 territories with rationale/risks, Brand-Brain citations) · smoke: *CS-05 strategy agent* |
| CS-06 | Script & Copy agent | B — Creative pipeline | P0 | **Deployed ✔** | test_pipeline_api.py::test_script_agent_writes_6_15_30_with_beats_and_inserts_mandatories_verbatim · test_domain.py::test_script_beats_are_contiguous_mandatories_inserted_verbatim_and_beats_trimmed_to_speakable_windows · smoke: *CS-06 script agent* |
| CS-07 | Storyboard & Art Direction agent | B — Creative pipeline | P0 | **Deployed ✔** | test_pipeline_api.py::test_full_pipeline_to_rendered_mp4_… (shot list, ≥3 keyframes, Guardian on images) · smoke: *CS-07 storyboard: ≥3 gpt-image keyframes* · screens/06-creative-workspace-storyboard.png |
| CS-08 | Spot compositor / Video | B — Creative pipeline | P0 | **Deployed ✔** | test_compositor.py (ffprobe H.264/AAC, duration ±0.5 s, loudness ±1.5 LU, 4 aspect ratios, −23 LUFS, subprocess isolation) · smoke: *CS-08 compositor: 15 s MP4 via API* · screens/07-creative-workspace-video.png |
| CS-09 | Voice & audio agent | B — Creative pipeline | P0 | **Deployed ✔** | test_compositor.py::test_captions_and_srt_timing_are_monotonic_and_inside_the_spot · test_domain.py::test_voice_over_timing_speeds_up_within_limits_and_flags_overflow · smoke: *CS-09 voice-over timed to script beats* · screens/08-voice-and-music.png |
| CS-10 | Localization agent | B — Creative pipeline | P1 | **Deployed ✔** | test_features_api.py::test_cs10_localization_keeps_glossary_terms_… · test_domain.py (DNT masking, faulty-translator repair, back-translation threshold) · smoke: *CS-10 localization de,fr,pl* · screens/10-localization.png |
| CS-11 | Format factory & versioning | B — Creative pipeline | P0 | **Deployed ✔** | test_features_api.py::test_cs11_format_factory_produces_reframes_and_cutdowns_… · test_domain.py::test_reframe_and_cutdown_keep_the_hook_the_end_card_and_valid_vo_timing · smoke: *CS-11 format factory* · screens/09-formats-and-cutdowns.png |
| CS-12 | Brand Guardian | C — Governance & safety | P0 | **Deployed ✔** | tests/test_guardian.py (19 tests: seeded claim/disclaimer/forbidden-word/palette/music/consent/content-safety violations, compliant pass, auto-revise convergence, waivers) · test_features_api.py::test_cs12_guardian_playground_… · smoke: *CS-12 Guardian auto-revise converges* · screens/13-guardian-report-blocked.png, 14-guardian-auto-revise.png |
| CS-13 | Approval workflow & audit trail | C — Governance & safety | P0 | **Deployed ✔** | test_pipeline_api.py::test_guardian_blocks_script_then_auto_revise_converges_and_approval_is_gated, ::test_role_permissions_are_enforced · test_platform.py::test_audit_chain_is_append_only_and_detects_edits_deletions_and_reordering · smoke: *CS-13 approvals*, *CS-13 immutable audit log* · screens/15-approvals-inbox.png, 16-approvals-and-audit-chain.png |
| CS-14 | AI disclosure & provenance | C — Governance & safety | P0 | **Deployed ✔** | test_pipeline_api.py (manifest verifies; tamper of file and manifest detected; sidecar; pack) · test_domain.py::test_disclosure_labels_follow_jurisdiction_and_platform · smoke: *CS-14 provenance manifest verifies; tampering is detected* · screens/12-provenance-tamper-test.png |
| CS-15 | Budget & cost guardrails | C — Governance & safety | P0 | **Deployed ✔** | test_platform.py (budget guard refuses after cap with a clear error; metering == counted calls; campaign cap; premium gate; alerts) · test_features_api.py::test_cs15_budget_overview_… · smoke: *CS-15 cost meter*, *CS-15 budget guard fails closed* · screens/21-cost-meter.png |
| CS-16 | Pre-flight creative scorecard | D — Performance & optimization | P1 | **Deployed ✔** | test_features_api.py::test_cs16_preflight_scorecard_is_labelled_predictive_… · test_domain.py::test_scorecard_components_… · smoke: *CS-16 pre-flight scorecard* · screens/11-preflight-scorecard.png |
| CS-17 | Variant engine & experimentation | D — Performance & optimization | P0 | **Deployed ✔** | test_domain.py (Thompson converges ≥ 90 % of 40 seeded sims; beats uniform; z-test vs textbook value, type-I ≈ 5 %, power > 95 %; auto-pause) · test_features_api.py::test_cs17_experiment_matrix_… · smoke: *CS-17 12-variant experiment* · screens/17-variants-bandit-experiment.png |
| CS-18 | Performance ingestion & insights | D — Performance & optimization | P0 | **Deployed ✔** | test_domain.py (CSV validation, derived metrics, planted-winner insights) · test_features_api.py::test_cs18_performance_csv_connectors_metrics_and_insights_… · smoke: *CS-18 performance* · screens/18-performance-insights.png |
| CS-19 | Campaign planner & media-mix hints | D — Performance & optimization | P2 | **Deployed ✔** | test_domain.py::test_planner_spends_the_whole_budget_equalises_marginal_returns_… · test_features_api.py::test_cs19_planner_… · smoke: *CS-19 planner* · screens/19-media-planner.png |
| CS-20 | Studio UI | E — Platform | P0 | **Deployed ✔** | test_features_api.py::test_cs20_studio_overview_and_activity_feed · Playwright journeys: dashboard, creative workspace (7 tabs), feature map (app/e2e/journeys.py) · screens/01-dashboard.png |
| CS-21 | Asset library / DAM | E — Platform | P1 | **Deployed ✔** | test_features_api.py::test_cs21_asset_library_upload_search_versions_tags_rights_and_range_streaming · smoke: *CS-21 asset library* · screens/20-asset-library.png |
| CS-22 | Collaboration, roles & integrations | E — Platform | P1 | **Deployed ✔** | test_features_api.py::test_cs22_roles_webhooks_ssrf_guard_… , ::test_cs22_campaign_pack_export_… · test_platform.py (SSRF validator, rate limiter, role matrix) · smoke: *CS-22 webhooks*, *CS-22 campaign pack export* · screens/23-team-and-integrations.png |
| CS-23 | ROI & ACR calculator | E — Platform | P0 | **Deployed ✔** | test_platform.py::test_roi_calculator_reproduces_the_published_business_case_within_half_a_percent · test_features_api.py::test_cs23_roi_calculator_endpoints_… · smoke: *CS-23 ROI & ACR parity* · screens/22-roi-acr-calculator.png |
| CS-24 | Observability, security & IaC | E — Platform | P0 | **Deployed ✔** | test_features_api.py::test_cs24_observability_endpoints_… · test_platform.py (Bicep ↔ collections, governance tags on every resource) · smoke: *healthz + readyz*, *CS-24 observability*; live /readyz green · screens/24-ops-observability.png, 25-feature-map.png |

**Priorities.** P0 = the product is not credible without it (MVP gate). P1 = needed for a GA customer deployment. P2 = valuable, may ship as "illustrative" in GA.
All 24 are in scope of the Release-1 reference implementation regardless of priority.

**Conventions used in every section below**
* *Target* = the enterprise Azure design in [ARCHITECTURE.md](ARCHITECTURE.md). *Deployed slice* = what runs in `rg-swarmai-studio` (one Container App with FastAPI + SPA + ffmpeg + background job runner; Cosmos DB serverless; Blob; one Foundry/AIServices account with deployments `chat`=gpt-5.4-mini, `reasoning`=gpt-5.4, `image`=gpt-image-1.5 or -mini, `embed`=text-embedding-3-small, `tts`=tts-hd; Content Safety and AI Speech neural voices through the same account; App Insights + Log Analytics; ACR Basic; user-assigned managed identity; 0 secrets).
* Every AI call goes through an interface (`LLMClient`, `ImageClient`, `SpeechClient`, `EmbeddingClient`, `SafetyClient`, `VideoProvider`, `AdPlatformConnector`) with an Azure implementation and a deterministic offline stub. Acceptance criteria are written so they can be asserted against the stub in CI **and** against Azure in the smoke test.
* Acceptance criteria are numbered `CS-NN-ACk` so tests and the Evidence column can cite them. "Synthetic" = seeded fictional data (Northwind Coffee Roasters inside the Contoso Consumer Brands portfolio); nothing real is pretended.
* `FR-*` = requirement id in PRD §7, `KPI-*` = metric id in PRD §10 (also listed in the [traceability matrix](#traceability-matrix)).

---

## Epic A — Brand Brain & governance data

### CS-01 — Brand Kit & Brand Brain (P0)

**Why / problem.** Brand consistency is lost wherever guidelines live in PDFs and each agency or tool re-interprets them; ungrounded generative agents drift off-brand and invent product facts. Consistency has to be *by construction*, not by review.

**Description.** A governed knowledge base per brand. Brand owners ingest brand guidelines (md / pdf / txt / docx text), tone of voice, palette (hex + role), typography, logo rules (clear space, minimum size), product catalogue and personas. The Brand Brain chunks the content structure-aware, embeds it (`text-embedding-3-small`) and retrieves with **citations** (document, section, version). A **brand-voice profile** (do / don't, vocabulary, formality, sentence rhythm, example lines) is derived and editable. Every publish creates an immutable **version**; agents pin the version they used (recorded in provenance, CS-14). Performance *learnings* (CS-18) are stored as typed entries with confidence and provenance.

**Acceptance criteria**
* **CS-01-AC1** Ingesting the seeded Northwind brand book (md, txt, docx-text and pdf-text samples) yields chunks + embeddings; on the seeded Q/A set (≥ 20 questions) the correct source chunk is in the top-3 results for ≥ 90 % of questions, each result carrying a citation (document, section, version).
* **CS-01-AC2** Editing any Brand Kit element creates version *n+1*; version *n* stays retrievable; diff view lists changed elements; an agent run records the exact Brand Kit version it used.
* **CS-01-AC3** Structured identity rules (palette hex + role, logo clear-space ratio, minimum logo size, forbidden words) are machine-readable and consumed by the Guardian (CS-12): changing a forbidden word changes the Guardian verdict on the next check.
* **CS-01-AC4** Every agent output that used retrieval stores the citation IDs; the UI shows "Grounded in …" with click-through to the source passage.
* **CS-01-AC5** Uploaded text that contains instruction-like strings ("ignore previous instructions …") is treated as data: a test proves the agent output does not follow it.
* **CS-01-AC6** The index survives a restart (persisted in Cosmos/Blob) and works fully offline with the stub embedder.

**Azure services.** *Target:* Azure AI Search (hybrid vector + keyword, semantic ranker), Azure OpenAI embeddings via Microsoft Foundry, Azure AI Document Intelligence (PDF/Office layout), Cosmos DB (versions, entries), Blob/ADLS Gen2 (source documents), Microsoft Purview (classification, lineage). *Deployed slice:* `embed` (text-embedding-3-small) on the Foundry account, in-process numpy cosine index persisted in Cosmos/Blob, text extraction for md/txt/docx/pdf-text.

**Reference scope / simulated.** Real embeddings + real retrieval; AI Search, Document Intelligence and Purview are *not* deployed (documented scale-out path behind the `BrandIndex` interface).

**Dependencies.** None (foundation). Consumed by CS-04 … CS-12, CS-16, CS-18.

**KPIs moved.** KPI-13, KPI-07, KPI-17.

### CS-02 — Claims & Compliance Library (P0)

**Why / problem.** Unsubstantiated or non-compliant claims are the most common legal exposure in regulated categories, and the rules differ per market. Legal review at the end of the chain finds problems when they are expensive to fix.

**Description.** A structured library of claims per **market × product category** (food, beverage, alcohol, finance, pharma/health, cosmetics, environmental claims …) with status `approved`, `prohibited`, `needs_substantiation`; **required disclaimers / legal supers** (text, minimum size and duration, language); **substantiation** links with expiry; owner and review date; CSV/JSON import; versioning. Claim matching combines exact/regex rules, embedding similarity for paraphrases and an LLM judge for borderline cases. The Script agent is given the allowed claims and the prohibited list (*claim-aware generation*); the Guardian (CS-12) enforces them.

**Acceptance criteria**
* **CS-02-AC1** CRUD + CSV import with validation (market, category, status, disclaimer, substantiation URL/expiry); every change is versioned and audited. The seed contains ≥ 30 claims across ≥ 4 categories and ≥ 5 markets (US, UK, DE, FR, PL).
* **CS-02-AC2** A check call for (text, market, category) returns every matched claim with verdict, matched span, rule id and the disclaimers that must accompany it. "Cures morning anxiety" is `prohibited` in every market; a paraphrase ("heals your morning worries") is flagged through semantic matching.
* **CS-02-AC3** Market scoping is honoured: a claim `approved` in the US and `needs_substantiation` in DE yields different verdicts for the same text.
* **CS-02-AC4** When substantiation expires the claim flips to `needs_substantiation` automatically and an expiry alert is emitted (alerts feed + webhook).
* **CS-02-AC5** Generated copy never contains a prohibited phrase (asserted over a seeded prompt set with the offline stub) and carries the required disclaimer whenever a conditional claim is used.

**Azure services.** *Target:* Cosmos DB, Azure AI Search (semantic claim matching), Azure OpenAI (judge), Purview business glossary, Power Automate/Dynamics 365 for legal workflow. *Deployed slice:* Cosmos DB + `embed` + `chat` judge.

**Reference scope / simulated.** The claims content is synthetic and illustrative — it is **not legal advice** and is labelled as such in the UI.

**Dependencies.** CS-01 (taxonomy); consumed by CS-06, CS-10, CS-11, CS-12.

**KPIs moved.** KPI-06, KPI-07, KPI-08.

### CS-03 — Rights & Consent Registry (P0)

**Why / problem.** Using talent likeness or voice, licensed music or stock outside the licensed territory, channel or window is expensive, and generative tools make synthetic likeness and voice a new consent problem.

**Description.** Registry of rights items: talent likeness, talent voice, licensed music, stock image/footage, fonts and locations. Each item carries rights-holder, licence/contract reference, **territories**, **media/channels**, **windows**, exclusivity, restrictions (e.g. "no synthetic voice", "no alcohol adjacency") and an explicit **AI-use consent flag** for likeness and voice. A rights check takes an asset's declared uses (music cue ids, talent ids, stock ids) × target markets × channels × publish date and returns pass/block with reasons and remediation (licensed alternative). Expiry alerts fire N days ahead; expired items flip to `expired`.

**Acceptance criteria**
* **CS-03-AC1** CRUD with validation for the five item types. The seed contains ≥ 6 music tracks (some licensed only for certain territories, one expired, one unlicensed), ≥ 3 talents (one with expired consent, one with "no synthetic voice"), and stock items.
* **CS-03-AC2** The rights check blocks and explains: unlicensed music cue, talent used outside granted territory, use after window end, channel not covered, synthetic voice without AI-voice consent — each with a reason code and a remediation hint.
* **CS-03-AC3** Items expiring within the configured horizon appear in the alerts feed and webhook; items past end date automatically become `expired`.
* **CS-03-AC4** Music selection in CS-09 only offers tracks licensed for the asset's markets, channels and window.
* **CS-03-AC5** Publish / campaign-pack export (CS-22) refuses assets with open rights violations; an override requires the Legal role and a reason, and is audited.

**Azure services.** *Target:* Cosmos DB, Azure Functions (expiry timers), Event Grid, Service Bus, Purview, integrations with rights-management / contract systems. *Deployed slice:* Cosmos DB, an in-app scheduler for expiry.

**Reference scope / simulated.** Synthetic talents and tracks; licensed music is simulated by locally generated royalty-free beds referenced by registry entries; no real contracts or persons.

**Dependencies.** CS-13 (audit); consumed by CS-09, CS-12, CS-14, CS-22.

**KPIs moved.** KPI-11, KPI-06, KPI-10.

---

## Epic B — Creative pipeline (the crew)

### CS-04 — Brief intake & Briefing agent (P0)

**Why / problem.** Poor briefs are the largest single source of creative rework; agencies burn rounds clarifying what was meant.

**Description.** A structured **brief wizard** (objective, audience, KPIs, channels, markets, budget, timeline, mandatories, tone, product, category) *and* free-text / document paste. The Briefing agent extracts fields, scores **completeness** against a checklist, asks at most **three prioritised clarifying questions**, flags category and market risks (e.g. caffeinated beverage → health-claim caution; market without claims coverage) and emits a **normalised brief** (JSON schema + readable document), versioned and locked at the *brief* gate (CS-13).

**Acceptance criteria**
* **CS-04-AC1** Pasting the Dawn Roast free-text brief yields a normalised brief with every required field filled or explicitly flagged as missing, plus a completeness score 0–100.
* **CS-04-AC2** The agent asks ≤ 3 clarifying questions, each tied to a missing or ambiguous field and none redundant with supplied information; answering updates the brief and raises completeness.
* **CS-04-AC3** Schema validation rejects invalid budget, dates and unknown markets; category/market risk flags are displayed and link to claims-library coverage gaps.
* **CS-04-AC4** The brief is versioned; approval at the brief gate locks it and downstream agents receive the locked version id.

**Azure services.** *Target:* Foundry GPT (structured outputs), Document Intelligence for uploaded briefs, Teams intake bot, Logic Apps. *Deployed slice:* `chat` (gpt-5.4-mini) structured output + deterministic validators.

**Reference scope / simulated.** Fully real in the slice (text in, JSON out); no Teams intake bot.

**Dependencies.** CS-01, CS-02 (risk flags), CS-13 (gate).

**KPIs moved.** KPI-02, KPI-07, KPI-08.

### CS-05 — Strategy agent (P0)

**Why / problem.** Strategy quality varies across brands and agencies, and learnings from past campaigns rarely reach the next brief.

**Description.** From the locked brief, the Brand Brain and accumulated *learnings* (CS-18), the agent produces an insight summary, 2–4 audience segments (needs, media habits), a positioning statement and **3–5 big-idea territories** (name, one-liner, rationale, proof points, tone, **risk notes** for claims, rights and cultural sensitivity) with a recommendation and trade-offs. Every statement cites Brand Brain sources or learnings. The team selects or merges a territory, which locks at the *concept* gate.

**Acceptance criteria**
* **CS-05-AC1** For the Dawn Roast brief the agent returns 3 territories with all required fields and ≥ 1 citation each.
* **CS-05-AC2** A territory that implies a health benefit is flagged with a claim-risk note cross-checked against CS-02.
* **CS-05-AC3** When CS-18 insights exist (seeded: "sunrise ritual hook outperforms for 25–34"), the strategy cites them (asserted in a seeded test).
* **CS-05-AC4** Territory selection is persisted and locked at the concept gate; "regenerate with feedback" creates a new version without losing the old one.

**Azure services.** *Target:* Foundry GPT reasoning models, Azure AI Search, Fabric (audience data), Dynamics 365 Customer Insights. *Deployed slice:* `reasoning` (gpt-5.4) with `chat` fallback; retrieval from the in-process Brand Brain.

**Reference scope / simulated.** Real LLM reasoning over synthetic brand/learning data; no CDP/audience integration (segments come from personas in the Brand Kit).

**Dependencies.** CS-01, CS-04, CS-18 (optional learnings).

**KPIs moved.** KPI-02, KPI-13, KPI-05.

### CS-06 — Script & Copy agent (P0)

**Why / problem.** Scripts must fit a duration, a brand voice, a claim set and a channel at the same time — hard to do manually at volume.

**Description.** Scripts for **6 / 15 / 30 / 60 s** with time-coded beats, VO, on-screen supers and CTA, built around the selected territory and a *hook in the first 3 seconds*; **channel-specific copy** (headlines, captions, emails, push, retail-media) within platform character limits; **tone variants** (e.g. warm / witty / premium); **claim-aware** (approved claims offered, prohibited ones forbidden, required disclaimers inserted); a **word budget per duration** (speech-rate model) so the VO fits.

**Acceptance criteria**
* **CS-06-AC1** The 15 s script's beat durations sum to 15 s ± 0.5 s and the VO word count fits the speech-rate window (e.g. 2.0–3.0 words/s) — asserted numerically.
* **CS-06-AC2** 6 / 15 / 30 / 60 s versions are produced from one territory with a consistent through-line (shared key message and CTA).
* **CS-06-AC3** Output contains no prohibited claim (checked with CS-02) and includes the required disclaimer when a conditional claim is used.
* **CS-06-AC4** ≥ 3 tone variants are produced, measurably different from each other while staying within the brand-voice profile threshold.
* **CS-06-AC5** Channel copy respects per-channel character limits.
* **CS-06-AC6** Guardian feedback triggers a *targeted* revision (only failing lines change; the diff is shown).

**Azure services.** *Target:* Foundry GPT (chat + reasoning), Azure AI Language (readability/PII), Azure AI Search for claim and voice grounding. *Deployed slice:* `chat` / `reasoning` with structured outputs.

**Reference scope / simulated.** Fully real.

**Dependencies.** CS-01, CS-02, CS-05; produces input for CS-07, CS-09, CS-10, CS-12.

**KPIs moved.** KPI-02, KPI-06, KPI-07.

### CS-07 — Storyboard & Art Direction agent (P0)

**Why / problem.** Visual consistency across shots, formats and markets is the hardest thing for generative image models; without it, output looks like stock.

**Description.** From the script the agent writes a **shot list** (shot number, duration, framing, camera move, subject, location, lighting, mood, VO/super sync, safe-area notes) and generates **storyboard key-frames** with `gpt-image-*`. Consistency comes from a **style bible** injected into every prompt (palette conditioning, style references, seed-prompt template, a character/product description block, optional reference images). Single-frame regeneration, version history, and *premium* (high-resolution / high-quality) generation gated by CS-15.

**Acceptance criteria**
* **CS-07-AC1** For the 15 s script the agent produces a shot list with ≥ 5 shots whose durations sum to the script duration; every shot has a frame prompt.
* **CS-07-AC2** ≥ 3 storyboard frames are generated and stored (Blob) with a prompt digest; every frame prompt contains the style bible (palette + character/product block) — asserted by test.
* **CS-07-AC3** Palette conditioning is measurable: the dominant-colour distance of generated frames to the brand palette is reported and below the configured threshold for the stub/seeded frames; on Azure the report is recorded as evidence, not a hard gate.
* **CS-07-AC4** Regenerating one frame leaves the other frames untouched and creates a new version of that frame.
* **CS-07-AC5** Prompts and outputs pass through CS-12 content-safety checks; generation obeys CS-15 caps and premium gating.

**Azure services.** *Target:* Foundry image models (`gpt-image-1.5` / `gpt-image-2`), Azure OpenAI vision for QA, Blob/ADLS, Content Safety. *Deployed slice:* `image` deployment (gpt-image-1.5 or -mini, low quality/small size), Blob.

**Reference scope / simulated.** Real generated frames on Azure; the offline stub renders deterministic palette-based placeholder frames. Frames are illustrative key-art, not final photography.

**Dependencies.** CS-01, CS-06, CS-12, CS-15.

**KPIs moved.** KPI-02, KPI-13, KPI-01.

### CS-08 — Spot compositor / Video (P0)

**Why / problem.** Azure OpenAI's Sora video model is deprecated in the target region and no video model is a safe long-term dependency. The product must work today and upgrade later.

**Description.** A **`VideoProvider`** interface (`render(timeline_spec) → artifact`) with capability negotiation (max duration, aspect ratios, audio support). The default provider is an **ffmpeg spot compositor**: key-frames + **motion** (zoompan / pan / parallax), transitions, **voice-over + music bed with ducking**, **captions** (burned-in + SRT/VTT), logo + **brand end-card**, **EBU R128** loudness normalisation, MP4 H.264/AAC. A documented, stubbed `external-video-model` provider shows the contract for any generative video model. The *timeline spec* (JSON) is the single source of truth, so renders are reproducible and cacheable by spec hash.

**Acceptance criteria**
* **CS-08-AC1** A 15 s spot renders to MP4 verified with `ffprobe`: H.264 video, AAC audio present, resolution as configured, duration 15 ± 0.5 s.
* **CS-08-AC2** Integrated loudness is within ± 1.5 LU of the selected target (default −23 LUFS EBU R128; online profile −16 LUFS).
* **CS-08-AC3** Burned-in captions and an `.srt` sidecar are produced; cue timestamps are monotonic and non-overlapping.
* **CS-08-AC4** The brand end-card/logo is present for ≥ 1.5 s at the end (frame-sample check).
* **CS-08-AC5** Provider selection is configuration-only; the external provider stub returns a clear "not configured" capability error that documents the contract.
* **CS-08-AC6** Rendering runs as a background job with progress events (SSE) and is idempotent per spec hash.

**Azure services.** *Target:* Container Apps jobs or Azure Batch render workers (scale-out), Blob/ADLS, Azure Front Door/CDN for delivery, external generative-video provider behind `VideoProvider` when licensed and available. *Deployed slice:* ffmpeg inside the Container App with a background job runner; output to Blob.

**Where expansion lever E1 lands.** The `VideoProvider` / premium-generation path is where the optional **generative-video lever E1** (roadmap R2-01) plugs in — no change to this feature or its acceptance criteria. A generative provider is billed **per generated second, rejected takes included** (Azure OpenAI Sora 2 meters at US$0.10 standard and US$0.50 Pro high-res; partner video models from the Foundry catalog at about US$0.03–0.30), so it sits behind the CS-15 premium-generation approval and budget caps, and its availability is region-dependent (sora-2 is deprecated in swedencentral). The business case models E1 per generated second in `business-case/` (see PRD §11).

**Reference scope / simulated.** The motion is Ken-Burns/parallax over generated key-frames — **not generative video**; labelled as such in the UI. The pipeline, timeline spec, loudness, captions and provider abstraction are real.

**Dependencies.** CS-07, CS-09; consumed by CS-11, CS-14.

**KPIs moved.** KPI-01, KPI-02, KPI-03.

### CS-09 — Voice & audio agent (P0)

**Why / problem.** Voice-over, timing, subtitles and music licensing are slow, expensive and a rights risk (synthetic voices, unlicensed music).

**Description.** Generates **VO** with `tts-hd` or Azure AI Speech neural voices in multiple voices and languages from an **approved voice list**; fits the VO to the beat plan (speed/pause control, measured duration); produces **SRT** from the script; normalises loudness; selects a **music bed from the Rights Registry** (only tracks cleared for market, channel and window) and ducks it under the VO. Requests to clone a person or imitate a celebrity are refused and logged.

**Acceptance criteria**
* **CS-09-AC1** VO for the 15 s script is generated; its duration is within ± 8 % of the beat plan or automatically time-fitted.
* **CS-09-AC2** SRT cues align with the VO; monotonic; ≤ 2 lines and ≤ 42 characters per line.
* **CS-09-AC3** The music selector never offers an unlicensed or out-of-territory track (test with the seeded unlicensed track).
* **CS-09-AC4** The mix meets the loudness target of the selected profile (± 1.5 LU).
* **CS-09-AC5** Only approved voices are selectable; a voice-cloning / celebrity-imitation request is refused with a logged reason.
* **CS-09-AC6** VO is produced in ≥ 3 languages with the correct voice locale.

**Azure services.** *Target:* Azure AI Speech (neural TTS, batch synthesis; Custom Neural Voice only under Microsoft's limited-access and consent-verification process), Azure OpenAI TTS / transcription for alignment QA, Blob. *Deployed slice:* `tts` (tts-hd) via Foundry for English plus Azure AI Speech neural voices through the same AI Services account for other languages (automatic fallback between the two), ffmpeg for mixing and loudness.

**Reference scope / simulated.** Real synthetic speech; music beds are locally generated royalty-free audio standing in for licensed tracks; no voice cloning is offered.

**Dependencies.** CS-03, CS-06; consumed by CS-08, CS-10.

**KPIs moved.** KPI-01, KPI-02, KPI-11.

### CS-10 — Localization agent (P1)

**Why / problem.** Literal translation fails in advertising (idioms, humour, claim rules differ by market), and localising a campaign into a dozen markets takes weeks and agency fees.

**Description.** **Transcreation** (not literal translation) of scripts, captions and supers into **≥ 8 languages** (EN, DE, FR, ES, IT, PL, PT, NL; JA/ZH/AR optional when fonts are available). Enforces a **glossary and do-not-translate list** (brand and product names, taglines), re-runs claim rules for the target market, performs a **back-translation check** (similarity threshold, drift flagged for a human linguist), fits text to length (supers, VO window) and produces **localised VO + captions + end-card**.

**Acceptance criteria**
* **CS-10-AC1** Dawn Roast scripts are transcreated into DE, FR and PL (and into all 8 languages in the batch test) with VO text, supers and captions.
* **CS-10-AC2** Glossary/do-not-translate terms ("Dawn Roast", "Northwind") are preserved in 100 % of outputs on the seeded glossary test.
* **CS-10-AC3** Back-translation similarity ≥ threshold, or the output is flagged "needs human linguist".
* **CS-10-AC4** Localised VO fits the master timeline within ± 10 % (text is auto-shortened when over).
* **CS-10-AC5** Claim rules are re-evaluated per target market (a claim approved in the US but needing substantiation in DE is flagged in the DE variant).
* **CS-10-AC6** Super/caption rendering shows no missing glyphs for diacritics in the 8 languages (render test).

**Azure services.** *Target:* Azure OpenAI for transcreation, Azure AI Translator (glossaries / custom translator) for deterministic terminology, Azure AI Speech multilingual voices, linguist-in-the-loop through an LSP API. *Deployed slice:* `chat` for transcreation and back-translation, `embed` for similarity, Azure AI Speech neural voices (e.g. `pl-PL-ZofiaNeural`) for the localized voice-over; Translator is not deployed.

**Reference scope / simulated.** Real LLM transcreation; no human linguist (the flag is raised and queued); fonts bundled for Latin-script languages.

**Dependencies.** CS-02, CS-06, CS-09, CS-11.

**KPIs moved.** KPI-09, KPI-02, KPI-06.

### CS-11 — Format factory & versioning (P0)

**Why / problem.** One hero spot becomes dozens of deliverables (aspect ratios, lengths, languages); done by hand this is the bulk of the production bill and a source of errors.

**Description.** Auto-reformats a master into **16:9, 9:16, 1:1, 4:5** and **cutdowns (6 / 15 / 30 s)** with *safe-area-aware reframing* (platform UI zones), template overlays (logo, end-card, legal supers from CS-02) and **6 s bumpers**. A **version tree** records lineage (master → format → language → variant); regenerating a parent marks descendants *stale*.

**Acceptance criteria**
* **CS-11-AC1** From a 15 s 16:9 master the factory outputs 9:16 (1080×1920), 1:1 (1080×1080) and 4:5 (1080×1350) files verified by `ffprobe`.
* **CS-11-AC2** A 6 s bumper is produced (6 ± 0.5 s) preserving the hook and the end-card.
* **CS-11-AC3** In 9:16 output the logo and supers sit inside the platform safe zones (overlay-metadata bounds test).
* **CS-11-AC4** The version tree stores lineage with spec hashes and renders in the UI; changing the master marks derived versions stale.
* **CS-11-AC5** Market-specific legal supers are applied automatically with minimum size/duration.
* **CS-11-AC6** A batch of N formats × M languages completes as one job with per-output status.

**Azure services.** *Target:* Container Apps jobs / Azure Batch workers, Service Bus (fan-out), Blob/ADLS, Front Door/CDN. *Deployed slice:* ffmpeg in the Container App's job runner.

**Reference scope / simulated.** Real reframing and cutdowns of the composited spot; smart-crop is geometry-based (subject-centred keyframes), not a vision-model tracker.

**Dependencies.** CS-08, CS-02, CS-10.

**KPIs moved.** KPI-01, KPI-03, KPI-09.

---

## Epic C — Governance & safety

### CS-12 — Brand Guardian (P0)

**Why / problem.** Manual brand and legal review does not scale to 10× the assets, and generative systems introduce new failure modes (hallucinated claims, protected material, unsafe imagery, prompt injection).

**Description.** An automated multi-check on **every script, asset and stage**: brand voice (profile similarity + judge), **visual identity** (palette distance, logo clear-space/size, forbidden words), **claims library** (CS-02), regulated-category rules, **rights registry** (CS-03), and **Azure AI Content Safety** (text + image, protected material, Prompt Shields where untrusted content is involved). Output: a **scored report** (per dimension, hard-fail vs warning) with evidence (text span / bounding box / rule id), **fix suggestions** and an **auto-revise loop** (bounded iterations, escalate on non-convergence). Failures **block approval**; overrides need the Legal role plus a reason.

**Acceptance criteria**
* **CS-12-AC1** The seeded violation set is blocked, each with a hard-fail, rule id and evidence: prohibited claim ("cures morning anxiety"), missing disclaimer, forbidden word, palette violation, unlicensed music, expired talent consent, content-safety hit.
* **CS-12-AC2** ≥ 10 seeded compliant assets produce zero false blocks.
* **CS-12-AC3** Auto-revise converges (all hard-fails cleared) in ≤ 3 iterations for ≥ 90 % of seeded failing scripts; otherwise the item is escalated to a human with the history.
* **CS-12-AC4** The approval endpoint returns **409** while any hard-fail is open.
* **CS-12-AC5** The report is stored with the asset version and shows evidence and suggested fixes per finding.
* **CS-12-AC6** Instruction-like text embedded in an asset cannot change the verdict (prompt-injection test).

**Azure services.** *Target:* Azure AI Content Safety (text, image, protected material, Prompt Shields, groundedness detection, custom categories), Foundry evaluators/guardrails, AI Search for semantic rule matching. *Deployed slice:* Content Safety via the Foundry AIServices account (text + image analysis, protected-material and shield-prompt where the API is available in the region), plus deterministic rule engines for palette/logo/forbidden-word/rights/claims.

**Reference scope / simulated.** All checks are real; the *content-safety hit* in the seeded set uses text/image that the service flags at a low threshold configured for the demo; palette and logo checks run on rendered pixels.

**Dependencies.** CS-01, CS-02, CS-03; gates CS-13.

**KPIs moved.** KPI-06, KPI-07, KPI-13, KPI-11.

### CS-13 — Approval workflow & audit trail (P0)

**Why / problem.** Humans must stay accountable. Approvals scattered across email and chat leave no defensible record, and nothing stops an unapproved asset from shipping.

**Description.** Configurable **stage gates**: brief → concept → script → storyboard → final. Roles (Brand Manager, Creative Director, Legal, Agency-guest, Admin), comments with version references, decisions (approve / request changes / reject) with reasons, **SLAs** with reminders and escalation, delegated approval and optional separation of duties (author ≠ approver). Every action is appended to an **immutable, hash-chained audit log**; a verification endpoint recomputes the chain.

**Acceptance criteria**
* **CS-13-AC1** A gate cannot be approved while Guardian hard-fails are open (409) or without the required role (403).
* **CS-13-AC2** The role–gate permission matrix is enforced (table-driven test across roles × gates).
* **CS-13-AC3** The audit chain verifies end-to-end; mutating any stored entry makes verification fail and report the first broken index.
* **CS-13-AC4** Items past their SLA are flagged and a notification (webhook) is emitted.
* **CS-13-AC5** The approvals inbox lists pending items per role with version links; comments and decisions are stored against the version.
* **CS-13-AC6** With separation of duties enabled, the author of a version cannot approve it.

**Azure services.** *Target:* Entra ID (groups/app roles, B2B guests), Cosmos DB (change-feed driven audit with immutable export to Blob immutable storage), Service Bus/Logic Apps (SLA timers), Teams Adaptive Cards for approvals. *Deployed slice:* Cosmos DB, in-app scheduler, role switcher header for the demo.

**Reference scope / simulated.** Roles are selected through a demo role switcher (no Entra sign-in in the public demo); hash chain and gating logic are real.

**Dependencies.** CS-12; consumed by CS-03, CS-04 … CS-11, CS-14, CS-22.

**KPIs moved.** KPI-06, KPI-08, KPI-02, KPI-20.

### CS-14 — AI disclosure & provenance (P0)

**Why / problem.** AI-generated and synthetically altered content increasingly requires disclosure and machine-readable marking (EU AI Act Article 50, platform policies) and brands need to prove what was made, by what, and who approved it.

**Description.** A **C2PA-style provenance manifest** for every final asset: asset hash, generator, actions (created / edited / composed), **models and tools used** (deployment names), **prompt digests** (hashes, not raw prompts), inputs (Brand Kit version, rights ids), **approvals**, ingredients (parent manifests for derived formats/languages) and a signature; a **sidecar JSON**; **jurisdiction/platform disclosure label** recommendations applied as caption/overlay/metadata per policy; a **provenance pack** export and a **verification endpoint**.

**Acceptance criteria**
* **CS-14-AC1** Every final asset has a manifest containing the required fields and a downloadable sidecar.
* **CS-14-AC2** Verification returns *valid* for an untouched asset and *invalid (hash mismatch)* after a one-byte change; a broken signature is detected separately.
* **CS-14-AC3** Disclosure labels are recommended per target market/platform and, when the policy says so, applied to the rendered asset (caption or overlay) and recorded in the manifest.
* **CS-14-AC4** The provenance pack contains manifest, audit extract, rights evidence and Guardian report for each asset and verifies as a whole.
* **CS-14-AC5** Derived assets (formats, languages) reference the parent manifest as ingredients; the chain is verifiable.
* **CS-14-AC6** Manifests record the Brand Kit version, model deployments, prompt digests and gate approvals.

**Azure services.** *Target:* C2PA SDK signing in render workers with keys in Azure Key Vault / Managed HSM and an X.509 chain from a C2PA-conformant CA; Content Credentials that Azure OpenAI attaches to generated images; immutable Blob storage / Confidential Ledger for audit anchoring; Purview lineage. *Deployed slice:* manifest (`spotlight-c2pa-lite/1`) + sidecar + Ed25519 software signature with an app-generated key stored in a private blob (a documented limitation), audit-chain anchor; verification endpoint with a tamper test. Not a CA-issued C2PA Content Credential.

**Reference scope / simulated.** The manifest follows the C2PA *concepts* but is **not** a C2PA-trusted credential (no CA-issued certificate); the UI states this. Disclosure-label rules are illustrative and configurable.

**Dependencies.** CS-08, CS-11, CS-13, CS-03, CS-01.

**KPIs moved.** KPI-10, KPI-06, KPI-20.

### CS-15 — Budget & cost guardrails (P0)

**Why / problem.** Generative production has variable cost; without metering and caps a runaway loop becomes a surprise bill, and without cost per approved asset the ROI story cannot be audited.

**Description.** A **usage meter** for tokens (by model, input/output), images (size/quality), TTS characters, embeddings and render seconds → **US$ estimate** from a versioned price table aligned with the business-case assumptions; **per-campaign and per-day caps**; alerts at 50/80/100 %; **approval required for premium generation** (high-resolution images, reasoning model for batch jobs); the headline KPI **cost per approved asset** shown against the agency baseline.

**Acceptance criteria**
* **CS-15-AC1** Metering equals counted calls: N mocked calls produce N meter events with the expected US$ (unit test).
* **CS-15-AC2** After a cap is reached further generation is refused with a clear error code and UI message; the demo daily cap defaults to ≤ US$5 and fails closed.
* **CS-15-AC3** Premium generation requires an approver and is logged.
* **CS-15-AC4** Cost per approved asset = campaign AI cost ÷ approved assets, shown with the agency baseline overlay.
* **CS-15-AC5** Alerts fire at the configured thresholds (feed + webhook); usage exports to CSV.

**Azure services.** *Target:* Azure API Management (token-limit and metering policies in front of model endpoints), Foundry usage metrics, Azure Monitor, Cost Management tags/budgets, Event Grid for alerts. *Deployed slice:* in-app meter and caps persisted in Cosmos; `/api/usage`.

**Reference scope / simulated.** Real metering of real calls; price table is a snapshot of Azure retail list prices (US$, PAYG).

**Expansion levers (Release 2+).** The same meter extends to the optional levers — generated video **seconds** (billed per generated second, rejected takes included), catalog images, personalised versions and Fabric capacity — so cost per approved asset, caps and approvals apply per lever (see PRD §11, *Expansion levers*).

**Dependencies.** All generating features; feeds CS-20, CS-23.

**KPIs moved.** KPI-01, KPI-16.

---

## Epic D — Performance & optimization

### CS-16 — Pre-flight creative scorecard (P1)

**Why / problem.** Media money should not be the first test of a creative; teams need a cheap, early read to prune weak variants.

**Description.** A **synthetic audience panel** (persona-prompted LLMs per segment) plus deterministic **heuristics** — hook within the first 3 s, brand presence, message clarity, CTA, accessibility (captions, contrast, legibility), compliance — produces a **predicted score**, sub-scores and **improvement suggestions** for each variant. Always labelled **predictive / simulated**; calibrated against observed performance (rank correlation reported, KPI-18).

**Acceptance criteria**
* **CS-16-AC1** Scoring a set of variants returns a ranking with 0–100 sub-scores (hook, brand, clarity, CTA, accessibility, compliance) and suggestions; the 12 Dawn Roast variants are ranked.
* **CS-16-AC2** Every payload and screen carries the "predicted / simulated — not a measurement" label.
* **CS-16-AC3** Heuristics are deterministic: a spot with the logo in the first 3 s and captions scores higher on brand presence and accessibility than one without (unit test).
* **CS-16-AC4** The panel reports mean and dispersion over ≥ 5 personas.
* **CS-16-AC5** After performance ingestion the Spearman correlation between predicted and observed ranks is computed and shown.

**Azure services.** *Target:* Foundry GPT (persona panel), Azure OpenAI vision for frame analysis, Azure AI Video Indexer / Content Understanding for video features, Fabric for calibration data. *Deployed slice:* `chat` persona panel + frame/metadata heuristics.

**Reference scope / simulated.** The panel is synthetic by definition — **simulated, not market research**. Calibration uses the performance simulator.

**Dependencies.** CS-06, CS-08, CS-18 (calibration).

**KPIs moved.** KPI-18, KPI-12, KPI-05.

### CS-17 — Variant engine & experimentation (P0)

**Why / problem.** Creative is the largest controllable driver of campaign effectiveness, but testing is limited by production cost; once variants are cheap, allocation becomes the bottleneck and static A/B splits waste spend on losers.

**Description.** A **variant matrix** (hook × CTA × visual × segment, with caps), **Thompson-sampling** allocation of budget (Beta-Bernoulli for rate metrics; exploration floor), **statistical significance** (two-proportion test and Bayesian probability-to-be-best) and **auto-pause of losers**. Operates against the **performance simulator** with seeded ground-truth rates; every allocation decision is logged with its reason.

**Acceptance criteria**
* **CS-17-AC1** A 12-variant matrix is built from hooks × CTAs × visuals (segments optional) with a configurable cap.
* **CS-17-AC2** Over ≥ 50 seeded simulations the bandit identifies the best variant in ≥ 90 % and its cumulative reward exceeds uniform allocation (paired comparison).
* **CS-17-AC3** The significance test is correct on synthetic data (type-I error ≈ α under the null; adequate power under the alternative).
* **CS-17-AC4** Variants with probability-to-be-best below the threshold after the minimum sample are auto-paused (zero spend) and can be re-enabled.
* **CS-17-AC5** Daily allocations sum exactly to the budget and respect floors/ceilings.
* **CS-17-AC6** Every allocation and pause decision is stored with its inputs and reason.

**Azure services.** *Target:* Azure Functions / Container Apps jobs for the allocation loop, Fabric (Eventhouse/Lakehouse) for impressions data, ad-platform APIs, Azure Machine Learning for contextual bandits (R2). *Deployed slice:* in-app bandit + seeded simulator.

**Reference scope / simulated.** The performance environment is a **simulator** (documented parameters); the algorithm and decision log are real and testable.

**Dependencies.** CS-11, CS-16, CS-18.

**KPIs moved.** KPI-04, KPI-05, KPI-12.

### CS-18 — Performance ingestion & insights (P0)

**Why / problem.** Performance data lives in ad platforms and spreadsheets and rarely changes the next brief; the loop must close.

**Description.** **CSV upload** (mapping profiles for common ad-platform exports) and a **simulated ad-platform connector** behind an `AdPlatformConnector` interface (Google / Meta / TikTok / LinkedIn adapters are R2) ingest impressions, clicks, CTR, VTR, CVR, CPA, ROAS and spend per variant/day. **Insight generation** mines variant attributes (hook, visual, CTA, segment, length, format, language) for effects with sizes and confidence, and **writes insights back to the Brand Brain** where the Strategy agent and the next brief pick them up.

**Acceptance criteria**
* **CS-18-AC1** CSV upload validates schema and types, reports invalid rows, and de-duplicates by (platform, date, ad id).
* **CS-18-AC2** Derived metrics (CTR, VTR, CVR, CPA, ROAS) match a golden dataset exactly.
* **CS-18-AC3** The simulated connector produces seeded daily data through the same interface a real connector would implement.
* **CS-18-AC4** On the seeded data the insight generator returns ≥ 3 insights, each with effect size, confidence interval and supporting rows.
* **CS-18-AC5** Insights appear as typed entries in the Brand Brain, are retrievable by CS-01 and cited by CS-05.
* **CS-18-AC6** Re-ingesting the same file does not double-count.

**Azure services.** *Target:* Microsoft Fabric (Lakehouse/Eventhouse/Real-Time Intelligence), Azure Data Factory/Functions connectors, Power BI semantic model, Dynamics 365 Customer Insights, Purview. *Deployed slice:* Cosmos DB + in-app analytics, CSV + simulator.

**Reference scope / simulated.** No live ad-platform credentials or APIs; the interface is the production contract.

**Dependencies.** CS-17, CS-01.

**KPIs moved.** KPI-17, KPI-05, KPI-12.

### CS-19 — Campaign planner & media-mix hints (P2)

**Why / problem.** Teams need a defensible first view of how to split a budget across channels before the first impression is bought.

**Description.** Recommends a **channel/budget split** with **expected reach and ROAS ranges** from a diminishing-returns (saturation-curve) model; priors are flagged as priors and refitted from ingested data when available; constraints (min/max per channel) and scenario compare; **explicitly labelled illustrative**.

**Acceptance criteria**
* **CS-19-AC1** Allocations sum to the budget and respect min/max constraints.
* **CS-19-AC2** At the optimum the marginal returns across unconstrained channels are equal within tolerance.
* **CS-19-AC3** Expected reach is monotonic in budget with diminishing returns (unit test); P10–P90 ranges are displayed with the "illustrative" label.
* **CS-19-AC4** Curves are refitted from CS-18 data when present; otherwise the UI shows "prior".

**Azure services.** *Target:* Azure Machine Learning / Fabric notebooks for MMM, Power BI. *Deployed slice:* closed-form model in the app.

**Reference scope / simulated.** Illustrative curves, not a calibrated marketing-mix model.

**Dependencies.** CS-04, CS-18.

**KPIs moved.** KPI-05, KPI-12.

---

## Epic E — Platform

### CS-20 — Studio UI (P0)

**Why / problem.** Adoption depends on one coherent, accessible workspace for marketers, creatives and legal — not a dozen tools.

**Description.** Campaign dashboard, brief wizard, Brand Brain console, **creative workspace** (strategy / script / storyboard / video / audio / localization / variants tabs), Guardian report, approvals inbox, asset library, experiments, performance, cost meter, ROI calculator and a **Feature Map** (`/features`). Polished editorial look, responsive, accessible (WCAG 2.2 AA target), a persistent "synthetic data / simulated environment" indicator, no third-party runtime fetches.

**Acceptance criteria**
* **CS-20-AC1** `/features` lists all 24 features from `/api/features` with id, name, status and a link to each feature's screen.
* **CS-20-AC2** The Dawn Roast journey (brief → … → insights) is completable in the UI end-to-end (Playwright).
* **CS-20-AC3** Core pages have no horizontal scroll at 1280, 1024 and 390 px widths.
* **CS-20-AC4** Automated accessibility checks report zero critical/serious violations on the key pages; the approval flow is keyboard-operable.
* **CS-20-AC5** The synthetic-data indicator is visible on every page.
* **CS-20-AC6** The production build type-checks and makes zero external network requests at runtime.

**Azure services.** *Target:* Azure Front Door + WAF → Container Apps / Static Web Apps, Entra ID sign-in, Azure Communication Services (R2 notifications). *Deployed slice:* React + Vite + TypeScript SPA served by the FastAPI container.

**Reference scope / simulated.** Real UI over real APIs.

**Dependencies.** All features (surfaces them).

**KPIs moved.** KPI-14, KPI-08, KPI-15.

### CS-21 — Asset library / DAM (P1)

**Why / problem.** Assets are scattered; reuse is low and rights context gets lost.

**Description.** Blob-backed library (Entra-only access) with metadata (type, campaign, format, language, status, rights links), tags (manual + vision auto-tags), **semantic search** (embeddings: "sunrise latte close-up, vertical"), versions with lineage, collections. Media is **served through the backend** (HTTP range requests for video), never through public blob URLs.

**Acceptance criteria**
* **CS-21-AC1** Assets upload and list with metadata; filters by campaign, format, language and status work.
* **CS-21-AC2** Semantic search on the seeded library returns the expected asset in the top-5 for ≥ 80 % of the seeded queries.
* **CS-21-AC3** Video is served through the API with range support (seekable); the storage container allows no anonymous access (asserted in the smoke test).
* **CS-21-AC4** Versions show lineage; collections support create/rename/add/remove.
* **CS-21-AC5** Archive/delete respects retention policy and is audited.

**Azure services.** *Target:* Blob/ADLS Gen2, Azure AI Search (vector), Front Door/CDN with signed URLs, Azure AI Vision / GPT vision for tagging, DAM connectors (Adobe AEM, Bynder, Frame.io, SharePoint). *Deployed slice:* Blob + Cosmos metadata + in-process embedding search.

**Reference scope / simulated.** Real storage and search at demo scale; no external DAM connector.

**Dependencies.** CS-01 (embeddings), CS-03, CS-13.

**KPIs moved.** KPI-03, KPI-01, KPI-14.

### CS-22 — Collaboration, roles & integrations (P1)

**Why / problem.** Agencies, regional teams and legal must work in the same system with the right access, and the output has to flow into ad platforms and DAMs.

**Description.** **Roles** (Admin, Brand Manager, Creative, Legal, Agency-guest) with an RBAC matrix and campaign-scoped guest access; **Teams/Slack-compatible webhook notifications** (approval requests, SLA breaches, rights expiry, budget alerts) with signed payloads and retries; a **campaign pack** export (zip: mp4, png, csv copy deck/variants/performance, provenance manifests with an index of hashes); a documented **REST API** (OpenAPI).

**Acceptance criteria**
* **CS-22-AC1** The RBAC matrix is enforced (table-driven test); an agency-guest sees only assigned campaigns and never the claims library or other brands.
* **CS-22-AC2** Webhooks post a Teams-compatible (Adaptive/Message Card) and a Slack-compatible payload, signed, with retry — verified against a local receiver.
* **CS-22-AC3** The campaign pack contains final MP4s, storyboard PNGs, CSVs and provenance manifests plus an index with hashes; pack integrity verifies.
* **CS-22-AC4** Assets with open rights/Guardian failures are excluded or marked "not cleared" in the pack.
* **CS-22-AC5** The OpenAPI document covers the resources of every feature.

**Azure services.** *Target:* Entra ID (app roles, B2B guest access), API Management, Logic Apps/Teams Adaptive Cards, Service Bus, ad-platform and DAM connectors via Functions. *Deployed slice:* app-level RBAC with demo role switcher, outbound webhooks, zip export.

**Reference scope / simulated.** No live Teams tenant or ad platform; payload formats are real and tested against a local receiver.

**Dependencies.** CS-13, CS-14, CS-03, CS-12.

**KPIs moved.** KPI-14, KPI-08, KPI-10.

### CS-23 — ROI & ACR calculator (P0)

**Why / problem.** A CMO/CFO will not buy on adjectives; the value case must be live, auditable and adjustable — and Microsoft needs a bottom-up view of the Azure consumption the solution implies.

**Description.** Agency baseline versus Studio: cost per asset, cycle time, variants per campaign, ROAS uplift, compliance-incident avoidance → **ROI, payback, NPV, IRR**; **Azure ACR by service family and year**; scenario switch (Conservative / Base / Upside); overrides for annual asset volume, cost per asset (agency vs Studio), markets, variants per campaign, media spend, ROAS uplift, discount rate and adoption ramp; assumption provenance visible. Uses the **vendored `business-case/model.py` + `assumptions.json`**.

**Acceptance criteria**
* **CS-23-AC1** For the Base reference scenario the calculator reproduces `business-case/outputs.json` within 0.5 % (unit test + API test).
* **CS-23-AC2** Overriding any supported key changes outputs consistently with the model (e.g. doubling media spend doubles the ROAS-uplift benefit).
* **CS-23-AC3** The three scenarios are returned together; ACR by family and year sums to the total.
* **CS-23-AC4** Invalid overrides are rejected with a 422 and a clear message.
* **CS-23-AC5** The live *cost per approved asset* from CS-15 is shown next to the model's Studio cost assumption.

**Azure services.** *Target:* Fabric/Power BI for portfolio-level tracking, Azure Retail Prices API refresh job. *Deployed slice:* the vendored pure-Python model inside the app.

**Reference scope / simulated.** Illustrative, assumption-driven; "validate with customer data" is shown on every output.

**Dependencies.** CS-15, `business-case/`.

**KPIs moved.** KPI-01, KPI-19.

### CS-24 — Observability, security & IaC (P0)

**Why / problem.** An enterprise product must be operable, secure by default and reproducible.

**Description.** OpenTelemetry → Application Insights / Log Analytics; **AI usage meter**; mandatory endpoints (`/healthz`, `/readyz`, `/api/meta`, `/api/usage`, `/api/features`, `/docs`); structured logs with request ids and PII redaction; **rate limits** (per-IP + global), request-size limits, **daily AI budget cap**; **keyless** by design (managed identity + RBAC; `disableLocalAuth`, no account keys, TLS 1.2+, no public blobs); **Bicep + azd** one-command deploy; smoke tests; teardown; optional Entra authentication switch.

**Acceptance criteria**
* **CS-24-AC1** `/healthz` returns 200 without dependencies; `/readyz` returns per-dependency status (Cosmos, Storage, Azure OpenAI) and 503 when one fails (simulated failure test).
* **CS-24-AC2** Exceeding rate limits returns 429 with `Retry-After`; oversized bodies return 413.
* **CS-24-AC3** A secret scan finds no keys/connection strings in code, env or IaC outputs; the deployment shows local auth disabled on Cosmos and AI Services and shared-key access disabled on Storage.
* **CS-24-AC4** `azd up` from a clean state yields a working deployment and the smoke test passes; the teardown command is documented and verified.
* **CS-24-AC5** Request and dependency telemetry appears in Application Insights with feature and request-id dimensions.
* **CS-24-AC6** PII redaction in logs is unit-tested.

**Azure services.** *Target:* Azure Monitor/App Insights/Log Analytics, Defender for Cloud, Key Vault, Private Link, Front Door + WAF, API Management, Azure Policy, Entra ID. *Deployed slice:* App Insights + Log Analytics (1 GB/day cap), managed identity RBAC, Bicep/azd, ACR remote build.

**Reference scope / simulated.** Real; private networking, WAF and Entra auth are documented target controls (optional switch for Entra).

**Dependencies.** Cross-cutting.

**KPIs moved.** KPI-15, KPI-20, KPI-16.

---

## Seed-data contract (so the demo narrative and the behavioural tests work)

| Domain | Minimum seed content |
|--------|----------------------|
| Tenant & brands | Tenant **Contoso Consumer Brands**; brand **Northwind Coffee Roasters** (product *Dawn Roast*), a second brand (e.g. **Fabrikam Snacks**) to show multi-brand isolation. |
| Brand Brain | Brand book (md/txt/docx-text/pdf-text), tone-of-voice, palette (≥ 5 hex colours with roles), typography, logo rules, product catalogue, ≥ 3 personas, ≥ 20 Q/A pairs for retrieval tests, a glossary with do-not-translate terms. |
| Claims | ≥ 30 claims, ≥ 4 categories, ≥ 5 markets; includes the prohibited "cures morning anxiety" and a paraphrase test set; one claim whose substantiation expires inside the alert horizon. |
| Rights | ≥ 6 music tracks (licensed / territory-limited / expired / unlicensed), ≥ 3 talents (one expired consent, one no-synthetic-voice), stock items. |
| Violations set | One seeded asset per violation: prohibited claim, missing disclaimer, forbidden word, palette violation, unlicensed music, expired consent, content-safety hit; ≥ 10 compliant controls. |
| Performance | Seeded simulator with ground-truth rates for the 12 Dawn Roast variants (best variant known), CSV golden dataset, ≥ 7 days of simulated daily data. |
| Cost | Agency baseline values taken from `business-case/assumptions.json` so the live meter and the calculator agree. |

---

## Release 2+ roadmap

Not part of the Release-1 contract. Items are *candidates*, sequenced by customer value and dependency; none is a commitment of Microsoft or any partner. **R2-01, R2-02, R2-08 / R2-22 and R2-21 are the optional expansion levers E1, E3, E4 and E2** modelled in `business-case/` (each with its own Azure consumption, customer benefit and cost; off in Base, on in Upside — see PRD §11).

| ID | Item | Release | Why it matters | Builds on |
|----|------|---------|----------------|-----------|
| R2-01 | **Generative video provider** behind `VideoProvider` (evaluated per licence, region availability, safety and cost) — *business-case expansion lever **E1**: billed per generated second, rejected takes included; sora-2 is deprecated in swedencentral, so provider and region are chosen per deployment* | R2 | Moves from motion-over-keyframes to generated motion without touching the pipeline | CS-08, CS-15 |
| R2-02 | **Personalisation at scale** — data-feed driven dynamic creative (segment × product × offer templates, 50k+ versions) with CDP audiences — *expansion lever **E3**: audience-level segment variants, 5–20× more versions per campaign* | R2 | Delivers the "50,000 versions" end-state | CS-11, CS-17 |
| R2-03 | **Live ad-platform connectors** (Google, Meta, TikTok, LinkedIn, DV360): read performance, push creatives, pause/allocate | R2 | Closes the loop on real spend | CS-18 |
| R2-04 | **DAM integrations** (Adobe AEM/Frame.io, Bynder, Brandfolder, SharePoint/OneDrive) | R2 | Fits the existing content supply chain | CS-21 |
| R2-05 | **Azure AI Search + Document Intelligence at scale** for the Brand Brain | R2 | Hybrid + semantic ranking over thousands of documents | CS-01 |
| R2-06 | **Agency multi-tenant mode** — workspaces, B2B guests, white-label, rate cards, chargeback metering | R2 | Partner-led distribution | CS-22 |
| R2-07 | **C2PA-conformant signing** (X.509 chain, Key Vault/HSM), Content Credentials verify page, invisible watermarking | R2 | Regulatory and platform readiness | CS-14 |
| R2-08 | **Fabric lakehouse + Power BI semantic model**, marketing-mix modelling, incrementality / geo-lift — *part of expansion lever **E4*** | R2 | Credible measurement | CS-18, CS-19 |
| R2-09 | **Voice consent workflow** (e-sign, Custom Neural Voice under Microsoft's limited-access process) and AI dubbing with timing alignment | R2 | Safe synthetic voice | CS-03, CS-09 |
| R2-10 | **Microsoft Teams app / Copilot agent** for approvals, briefs and status | R2 | Meets users in Teams | CS-13, CS-22 |
| R2-11 | **More formats** — retail media, DOOH, audio-only, email/CRM, app-store assets | R2 | Breadth of channels | CS-11 |
| R2-12 | **Evaluation & red-team harness** (groundedness, brand-voice drift, safety, regression suites) with model-drift dashboards | R2 | Responsible-AI evidence and safe model upgrades | CS-12 |
| R2-13 | **Talent marketplace & synthetic-likeness licensing workflow** | R3 | Managed consent economics | CS-03 |
| R2-14 | **FinOps integration** — chargeback by business unit, Cost Management tags/budgets, APIM metering | R2 | CFO-grade cost control | CS-15 |
| R2-15 | **Accessibility tooling** — audio description tracks, alt-text, caption QA to WCAG/EN 301 549 | R2 | Inclusive reach, EU accessibility rules | CS-09, CS-12 |
| R2-16 | **Regulatory packs** — more categories/markets, EU AI Act Art. 50 evidence pack, US state synthetic-media rules, platform-policy feed | R2 | Keeps rules current | CS-02, CS-14 |
| R2-17 | **Enterprise network & key control** — Private Link, customer-managed keys, EU data-boundary options, sovereign deployments | R2 | Security review blockers | CS-24 |
| R2-18 | **Creative memory** — find, reuse and remix proven winners | R2 | Reuse economics | CS-21, CS-18 |
| R2-19 | **Mobile/PWA approvals** | R3 | Faster gates | CS-13 |
| R2-20 | **Azure Marketplace transactable SaaS offer** with metered billing | R2 | Procurement via Azure commit | CS-15, CS-22 |
| R2-21 | **Catalog-scale product content** — PIM / e-commerce connectors; product-page images, lifestyle scenes, alt-text and localized descriptions for SKUs × markets, checked by the Guardian — *expansion lever **E2*** | R2 | Best-return expansion pack: avoided photography and retouching cost at cents per image | CS-05, CS-10, CS-12, CS-21 |
| R2-22 | **Marketing data & clean-room platform** — Fabric + OneLake with CRM / CDP integration, identity resolution and clean-room collaboration beyond the Release-1 CSV and connector ingestion — *expansion lever **E4*** | R2 | Wider measured media; the largest Azure consumption line among the levers | CS-18, R2-08 |
| R3-01 | **Always-on optimisation** — agents propose new variants daily within guardrails; contextual bandits; creative-level attribution | R3 | Autonomous learning loop | CS-17, CS-18 |
| R3-02 | **Cross-brand learning** with privacy boundaries (federated insights) | R3 | Portfolio-level lift | CS-18 |
| R3-03 | **Interactive and immersive formats** | R3 | New surfaces | CS-11 |

---

## Traceability matrix

Feature → PRD requirement(s) → KPI(s). Requirement ids are defined in [PRD.md §7](PRD.md#7-functional-requirements-by-epic); KPI ids in [PRD.md §10](PRD.md#10-success-metrics--kpis-and-measurement-plan).

| Feature | PRD requirement(s) | KPI(s) |
|---------|--------------------|--------|
| CS-01 Brand Kit & Brand Brain | FR-A1, FR-A2, FR-A3 | KPI-13, KPI-07, KPI-17 |
| CS-02 Claims & Compliance Library | FR-A4 | KPI-06, KPI-07, KPI-08 |
| CS-03 Rights & Consent Registry | FR-A5 | KPI-11, KPI-06, KPI-10 |
| CS-04 Brief intake & Briefing agent | FR-B1 | KPI-02, KPI-07, KPI-08 |
| CS-05 Strategy agent | FR-B2 | KPI-02, KPI-13, KPI-05 |
| CS-06 Script & Copy agent | FR-B3 | KPI-02, KPI-06, KPI-07 |
| CS-07 Storyboard & Art Direction agent | FR-B4 | KPI-02, KPI-13, KPI-01 |
| CS-08 Spot compositor / Video | FR-B5 | KPI-01, KPI-02, KPI-03 |
| CS-09 Voice & audio agent | FR-B6 | KPI-01, KPI-02, KPI-11 |
| CS-10 Localization agent | FR-B7 | KPI-09, KPI-02, KPI-06 |
| CS-11 Format factory & versioning | FR-B8 | KPI-01, KPI-03, KPI-09 |
| CS-12 Brand Guardian | FR-C1 | KPI-06, KPI-07, KPI-13, KPI-11 |
| CS-13 Approval workflow & audit trail | FR-C2, FR-C3 | KPI-06, KPI-08, KPI-02, KPI-20 |
| CS-14 AI disclosure & provenance | FR-C4 | KPI-10, KPI-06, KPI-20 |
| CS-15 Budget & cost guardrails | FR-C5 | KPI-01, KPI-16 |
| CS-16 Pre-flight creative scorecard | FR-D1 | KPI-18, KPI-12, KPI-05 |
| CS-17 Variant engine & experimentation | FR-D2, FR-D3 | KPI-04, KPI-05, KPI-12 |
| CS-18 Performance ingestion & insights | FR-D4, FR-D5 | KPI-17, KPI-05, KPI-12 |
| CS-19 Campaign planner & media-mix hints | FR-D6 | KPI-05, KPI-12 |
| CS-20 Studio UI | FR-E1, FR-E2 | KPI-14, KPI-08, KPI-15 |
| CS-21 Asset library / DAM | FR-E3 | KPI-03, KPI-01, KPI-14 |
| CS-22 Collaboration, roles & integrations | FR-E4, FR-E5 | KPI-14, KPI-08, KPI-10 |
| CS-23 ROI & ACR calculator | FR-E6 | KPI-01, KPI-19 |
| CS-24 Observability, security & IaC | FR-E7 (+ NFR-01 … NFR-14) | KPI-15, KPI-20, KPI-16 |

### KPI quick reference

| KPI | Metric | KPI | Metric |
|-----|--------|-----|--------|
| KPI-01 | Cost per approved asset (all-in) | KPI-11 | Rights breaches (target 0) |
| KPI-02 | Brief-to-approved-master cycle time | KPI-12 | Media waste (spend on below-median variants) |
| KPI-03 | Approved asset versions per year / per creative FTE | KPI-13 | Brand-consistency score |
| KPI-04 | Variants tested per campaign | KPI-14 | Adoption (users, campaigns, share of volume) |
| KPI-05 | ROAS uplift / CPA reduction vs control | KPI-15 | Reliability & performance |
| KPI-06 | Compliance incidents reaching market (target 0) | KPI-16 | Budget adherence |
| KPI-07 | First-pass Guardian pass rate / revision rounds | KPI-17 | Learning-loop latency |
| KPI-08 | Human review minutes per approved asset | KPI-18 | Pre-flight predictive validity |
| KPI-09 | Localisation cost and lead time per language version | KPI-19 | Azure Consumed Revenue per customer-year |
| KPI-10 | Provenance coverage | KPI-20 | Security & audit integrity |
