# SwarmAI — three Azure-native AI concepts

Each folder is a complete concept package: **PRD**, **Azure architecture**, **executive deck**, **feature backlog**, a **business case** (customer ROI + Azure Consumed Revenue, ACR) and a **working, tested reference implementation deployed to Azure** (Sweden Central).

| # | Concept (interpretation of `scope.md`) | Live app | Executive deck | Start here |
|---|---|---|---|---|
| 1 | **[Dark Factories](01-dark-factories/)** — lights-out manufacturing run by a governed swarm of AI agents on a digital twin ("Nightshift") | [ca-nightshift…azurecontainerapps.io](https://ca-nightshift.blackforest-a28408f9.swedencentral.azurecontainerapps.io) | [full (67 slides)](01-dark-factories/deck/DarkFactory-Executive-Deck.pdf) · [customer-only (55)](01-dark-factories/deck/DarkFactory-Executive-Deck-customer.pdf) | [README](01-dark-factories/README.md) · [PRD](01-dark-factories/PRD.md) · [Architecture](01-dark-factories/ARCHITECTURE.md) · [Features](01-dark-factories/FEATURES.md) · [Report](01-dark-factories/REPORT-TEST-AND-DEPLOYMENT.md) |
| 2 | **[Commercial Studio for Marketing](02-commercial-studio-marketing/)** — a brief-to-broadcast AI commercial studio: brand-safe, localized, measurable ("Spotlight") | [ca-studio-web…azurecontainerapps.io](https://ca-studio-web.yellowgrass-9740f562.swedencentral.azurecontainerapps.io) | [deck (56 slides)](02-commercial-studio-marketing/deck/CommercialStudio-Executive-Deck.pdf) | [README](02-commercial-studio-marketing/README.md) · [PRD](02-commercial-studio-marketing/PRD.md) · [Architecture](02-commercial-studio-marketing/ARCHITECTURE.md) · [Features](02-commercial-studio-marketing/FEATURES.md) · [Report](02-commercial-studio-marketing/REPORT-TEST-AND-DEPLOYMENT.md) |
| 3 | **[AI Contact Center](03-ai-contact-center/)** — AI agents resolve, humans escalate, 100% of conversations QA'd ("Concierge") | [ca-concierge…azurecontainerapps.io](https://ca-concierge-imsov4laqyzgs.delightfuldune-2bc64772.swedencentral.azurecontainerapps.io) | [deck (48 slides)](03-ai-contact-center/deck/ContactCenter-Executive-Deck.pdf) | [README](03-ai-contact-center/README.md) · [PRD](03-ai-contact-center/PRD.md) · [Architecture](03-ai-contact-center/ARCHITECTURE.md) · [Features](03-ai-contact-center/FEATURES.md) · [Report](03-ai-contact-center/REPORT-TEST-AND-DEPLOYMENT.md) |

Editable `.pptx` files sit next to every PDF. Open any live app and use its **Feature Map** page (in the navigation) to see every Release-1 feature, its status and the screen that proves it.

## Business case at a glance (Base scenario, list prices, illustrative — validate with customer data)

| | Reference customer | 3-yr NPV | ROI | Payback | ACR Year 3 | ACR run-rate at scale |
|---|---|---:|---:|---:|---:|---|
| Dark Factories | Contoso Industrial Group (8 plants, US$2B) | **$8.3M** | 104% | 22 mo | **$0.68M** | $0.91M (8 plants) → $1.87M with expansion levers → $5.4M (25 plants) → ≈$21M (100-plant fleet, illustrative) |
| Commercial Studio | Contoso Consumer Brands (US$8B, 12 markets) | **$7.0M** | 140% | 15 mo | **$0.47M** | $0.94M with levers → $2.05M (agency network) → $2.63M (enterprise scale); illustrative partner pipeline $7.6M (Base) / $15.1M (Upside) in Year 3 |
| AI Contact Center | Contoso Home Retail (1,500 agents, 18M contacts/yr) | **$27.1M** | 216% | 16 mo | **$2.98M** | $0.13M (50 seats) → $19.5M (10,000 seats) |

Every number comes from each concept's `business-case/model.py` (pure Python, bottom-up ACR from the Azure Retail Prices API, three scenarios, sensitivity), and each live app's ROI/ACR calculator runs the **same model** with a parity test against `outputs.json`. Honest reading: the contact center is the strongest ACR driver (realtime voice, speech, tokens); the Studio is ROI-heavy with moderate per-customer ACR that scales through expansion packs and agency networks; for Dark Factories, ACR roughly doubles with the optional levers but those levers *lower* 3-year NPV (their investment comes first).

## How this was verified (re-run independently, not just reported)

| | Unit/API tests | Live smoke test against Azure | Static / security |
|---|---|---|---|
| Dark Factories | 113 pass, 93% coverage | **25/25** | ruff clean; keyless; tags verified on RG + 14 resources |
| Commercial Studio | 97 pass, 88% coverage | **30/30** (real image + voice + rendered MP4 + provenance) | ruff clean; keyless; tags verified |
| Contact Center | 212 pass (+27 Playwright), 85% coverage | **21/21** (real refund tool call, realtime voice path, eval harness) | ruff clean; keyless; tags verified |

Evidence, load checks, screenshots and bugs found are in each `REPORT-TEST-AND-DEPLOYMENT.md` (raw outputs in `app/evidence/` where provided).

## What is real and what is simulated

* **Real:** the applications, the Azure deployments, Cosmos DB, Blob Storage, Azure OpenAI (chat, reasoning, vision, image, TTS, embeddings, realtime), Content Safety/Speech/Language, managed identity, hash-chained audit ledgers, policy engines, budget guards.
* **Simulated by construction (synthetic data, labelled in every UI):** the factory (plant, PLCs, faults), ad platforms and audience panels, the contact-center back office/CRM, SMS/WhatsApp/e-mail, and **telephony — no PSTN number is provisioned**. Azure Communication Services retires as a standalone offering on 30 Sep 2028 (verified on Microsoft Learn), so telephony sits behind a provider-neutral adapter (SIP→Realtime, Teams Phone, ACS legacy).
* **Dark Factories A/B replay:** simulation evidence only — significant for downtime (−79% over 16 seeds; −72% in the 10-seed live default), OEE (+13.5 pts), late orders, tardiness and the effective energy price; **not** significant for scrap, OTIF or absolute energy cost (slightly worse). The PRD, features and deck say so explicitly.
* **Commercial Studio video:** Azure OpenAI `sora-2` is deprecated in Sweden Central, so the studio ships an ffmpeg compositor behind a swappable `VideoProvider`.

## Azure footprint, cost and governance

* One resource group per concept — `rg-swarmai-darkfactory`, `rg-swarmai-studio`, `rg-swarmai-contactcenter` — each with Container Apps (single always-on replica), ACR Basic, Cosmos DB serverless, Storage, an AI Services account with model deployments, Log Analytics, Application Insights and a user-assigned managed identity (14 resources each).
* **Tags** on every resource group and resource, as instructed: `SecurityControl=Ignore`, `SecurityExemption=StorageAccountKeyAccess` (plus `project`, `concept`, `owner`, `environment`). With these, public access and key settings are not rewritten by governance policy (verified by experiment). The apps are nevertheless **keyless**: Entra/managed-identity only, local auth disabled on Cosmos and AI Services, Storage shared-key disabled.
* **Estimated idle cost ≈ US$100/month in total** (Dark Factories ≈ $45, Studio ≈ $30, Contact Center ≈ $28) plus AI usage, bounded by daily budget guards (Dark Factories $5, Studio $5, **Contact Center $8** — raised by the engineer to keep the demo usable after verification spend; restore with `az containerapp update -g rg-swarmai-contactcenter -n ca-concierge-imsov4laqyzgs --set-env-vars AI_DAILY_BUDGET_USD=5`).
* **Teardown** (per concept, from its folder): `azd down --purge --force` (or `az group delete -n rg-swarmai-<name>`; AI Services accounts are soft-deleted unless purged).

## Known limits to be aware of

Public demo endpoints with a self-declared role switcher (Entra authentication is an optional Bicep switch; production hardening — private endpoints, Front Door/WAF — is described in each ARCHITECTURE.md); Dark Factories runs a single replica because the simulation is in-process; Contact Center realtime quota allows ~1–2 concurrent calls, voice was tested through a fake realtime server and text input rather than a human microphone, the chat first-token SLO burns on tool-calling turns (p95 6.4 s), and generic webhook signatures are not verified; Studio caption fonts cover Latin/Cyrillic/Greek only; market statistics are sourced in each PRD but all customer-specific values are assumptions to validate.

## Repository layout

```
01-dark-factories/ · 02-commercial-studio-marketing/ · 03-ai-contact-center/
  PRD.md  ARCHITECTURE.md  FEATURES.md  README.md  REPORT-TEST-AND-DEPLOYMENT.md  azure.yaml
  business-case/   assumptions.json · model.py · outputs.json/.md · tests
  deck/            executive deck (.pptx + .pdf), build_deck.py, assets/screens (live-app screenshots)
  app/             FastAPI backend + React UI + tests + Dockerfile      infra/  Bicep      scripts/  smoke/load/deploy helpers
tools/deckkit/     shared python-pptx deck toolkit (+ render.py for headless LibreOffice QA)
```

Local dependencies (`app/.venv`, `app/web/node_modules`, `.venv`) are git-ignored build artifacts and can be deleted; each README explains how to recreate them.
