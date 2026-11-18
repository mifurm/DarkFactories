# PHASE 1 — Concierge frontend (Polish localization): DONE

Owner: cc-fe-pl2. Scope: `app/web/**`, `app/tests/e2e/**`, `deck/assets/screens-pl/**`. Nothing outside these paths was edited.

## What changed

**i18n core** (`web/src/i18n/`, design and usage in `README.md`, terminology in `GLOSSARY.md`)
* English-as-key dictionaries: `t()`, `tn()` (CLDR one / few / many / other), `te()` (enum by value), `tl()` (stable key + server label, UI dictionary wins), `ts()` (server prose as received, quiet Polish fallback), `rich()`; Polish dictionary = `pl/*.ts` partials (auto-merged).
* `fmt`: pl-PL numbers (NBSP grouping, decimal comma), PLN `1 599,00 zł`, EUR / USD per record currency (`fmt.money`), percent, dates `18.11.2026`, 24 h clock in Europe/Warsaw, relative times, durations; `Intl.Collator` sorting (`compare`); diacritic-insensitive search incl. ł / Ł (`includes`).
* Header language switch on **every** page including the customer widget and the call page; `?lang=` → saved choice → `navigator.languages` → `en`; `localStorage`, `<html lang>`, document title; no reload; the API client sends `Accept-Language` + `X-UI-Lang` on every call and `?lang=` on SSE / WebSocket / download URLs and refetches on a switch.
* Customer pages: the widget / call-page language selector sets **both** the labels and `conversation.language` (en / pl change the UI too; the other six only change the conversation).
* All 29 TSX files use it (the 24 routes, including the customer widget and the call page): titles, labels, placeholders, `aria-label`s, tooltips, table headers, empty states, toasts, chart titles / ticks / tooltips / legends, enum badges, feature map (by feature id), demo guide, roles, ROI / ACR calculator labels by model key, footer banner.
* `pl/server.ts`: Polish fallbacks for the static English prose the API still sends (tool descriptions, identity levels, SLO notes, deployment, role / connector notes, contract-check names). `ts()` shows the server's own text whenever it is not listed, so server localization wins.
* Layout for ~30 % longer text: supervisor grids stack below 1536 px, chips and summaries wrap, previews that are truncated on purpose carry `title` + `data-allow-clip`, chart Y-axis width follows the longest tick, long Polish chart labels are shortened at a word boundary with the full name in the tooltip.

**English stays intact.** Visible English differences (all additive or layout-only): routing per-intent column header "Support" → "Samples"; tool-level badge reads "dynamic" (was "Ldynamic"); KB admin has a document-language filter (English default = all); outbound counts show `30 / 32 / 16`; one extra sample chip on the multilingual page; `fmt.usd` groups thousands (`$1,234.50`); a long conversation id in the agent console wraps instead of being ellipsised.

## Tests (all green on the final tree)

| What | Command (from `03-ai-contact-center/app`) | Result |
|---|---|---|
| unit: dictionary completeness / unused / duplicate keys, placeholders, plural forms, no hard-coded English in JSX, no raw enums, pl-PL formats, ł folding, collator, ellipsis | `cd web && npm test` | 33 tests |
| types, bundle | `cd web && npx tsc -b --noEmit && npm run build` | 0 errors, OK |
| Polish journeys in Chromium (leftover scan, `__i18nMissing`, overflow / clipping, console; transcripts, chart tooltips, plurals, search, PLN) | `E2E_PORT=8113 .venv/bin/python -m pytest tests/e2e/test_journeys_pl.py -o addopts="" -q` | 54 passed |
| English journeys (unchanged file) | `E2E_PORT=8113 .venv/bin/python -m pytest tests/e2e/test_journeys.py -o addopts="" -q` | 27 passed |
| independent crawler, every route | `python tools/pl_audit/pl_audit.py --app concierge --base-url http://127.0.0.1:8113 --out <dir> --lang pl [--viewport 1280x720]` | 23 routes: 0 missing keys, 0 raw enums, 0 console errors, 7 + 2 noise findings (below) |

Notes
* `npm run build` first: the E2E server serves `web/dist`.
* Against a deployed app: `E2E_BASE_URL=https://<app> .venv/bin/python -m pytest tests/e2e/test_journeys_pl.py -o addopts="" -q` (`BASE_URL` also works). Screenshots go to `deck/assets/screens-pl/` (`E2E_PL_SHOTS_DIR` overrides, `E2E_NO_PL_SHOTS=1` disables); the English `E2E_SHOTS_DIR` fixture is unchanged and off by default, so `deck/assets/screens/` is never written.
* Run the Polish file as a whole: the QA journey lists the reviews that the widget journey at the top of the file produces (a fresh server has none); every other journey creates what it needs, and the page-actions journey skips its QA review step when there is none.
* The scan skips transcripts and user content by design; `assert_transcript_polish` checks the assistant / system / caption messages of the widget, handoff, agent console and call page separately (negative control: an English transcript is flagged).
* Journeys that depend on the model wording (live app with real models) assert deterministic parts only: UI labels, tool-driven amounts, the BE's fixed greeting.

## Screenshots (1600 × 900) — `deck/assets/screens-pl/`
22 files: the 21 names of `deck/assets/screens/` (`01-customer-widget-chat` … `18-compliance-guard`, with `07b`, `08b`, `10b`) plus `01-customer-widget-resolved`.

## Adding a language
See `web/src/i18n/README.md` ("Adding a language"): `Lang` / `LANGS` / `LANG_NAMES` / `LOCALES`, a `de.ts` + `de/*.ts` dictionary with the plural categories of that language, `DICTS` in `core.ts`, `leftovers.json` words, BE catalog + `/api/meta`.

## Known gaps / limits
* Seeded **conversation content** (QA transcripts, English seed rows, order item names of non-Polish customers) is shown as received; it is marked `data-user-content` and is the BE's content, not UI text.
* The static English prose the API still sends is translated by the FE fallback `pl/server.ts`; if the BE changes such an English sentence the fallback stops matching and the English text shows (the leftover scan would flag it).
* The auditor's heuristic is noisy; real remaining noise (all reviewed): `offline` (run-mode name), `limit` (Polish word), `home` (Contoso Home), Azure product / role names (Cosmos DB for NoSQL, Application Insights, Cognitive Services User), a person name containing "in" (Inês), `0,050 USD` flagged as US grouping (3-decimal price), `.sr-only` labels counted as clipped. Proposed allow-list entries for `tools/pl_audit`: those words, plus "sr-only is not clipping".
* Browsers: Chromium only; widths 1280 and 1600 (the spec's two viewports).
* Not run against Azure from here (no deployment in phase 1): the same journeys are ready for the orchestrator via `E2E_BASE_URL`.

## Requests to the BE side
All answered by the BE (CRM 360 and handoff `currency`, `output-check` in the request locale, CRM timeline titles and persona notes, Polish `demo-traffic`). None open.
