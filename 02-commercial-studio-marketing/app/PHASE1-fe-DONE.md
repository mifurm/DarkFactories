# Phase 1 — Spotlight FRONTEND (cs-fe-pl2) — DONE

Polish (`pl`) UI for Spotlight, English untouched. Owner scope: `app/web/**`, `app/e2e/**`, `deck/assets/screens-pl/**`. Nothing outside that scope was edited (the BE's `scripts/smoke_test.py` was only run).
Live-run results: `REPORT-TEST-AND-DEPLOYMENT.md` §12.8.

## What changed

* **i18n layer** `app/web/src/i18n/` — custom, ~600 lines, no runtime dependency, nothing loaded from a CDN (README there says why not i18next):
  `t("English source", {vars})` (English text is the key), `tn(n, {one, few, many, other})` (CLDR via `Intl.PluralRules`), `tEnum(group, id)` (statuses, roles, gates, feature names by id, ROI model keys),
  `tOpen` (open sets such as channels), `tKnown` (English constants the API returns verbatim), `tx` (markup inside a message), `fmt.*` (`Intl.NumberFormat/DateTimeFormat/RelativeTimeFormat/DisplayNames`, `pl-PL`, `Europe/Warsaw`),
  `sortByLocale` / `matchesQuery` (`Intl.Collator`, search folding that also maps ł/Ł). Missing key → English text + one `console.warn` + `window.__i18nMissing.push(...)` (array exists from startup). Test hook `window.__i18n` (read-only).
  Dictionaries: `en.ts` (id-keyed UI tables) and `pl.ts` + `pl/{messages-shell,brand,pipeline,governance,performance,platform,plurals,enums,features,roi}.ts`; terminology in `GLOSSARY.md`; how it works and how to add a language in `README.md`.
* **Language switch** (`components/LanguageSwitcher.tsx`, header of every page, accessible `<select>`): initial `?lang=` → `localStorage["studio.lang"]` → `navigator.languages` → `en`; sets `<html lang>`; no reload;
  an explicit switch drops a stale `?lang=` from the URL. Every API call sends `X-UI-Lang` and `Accept-Language`; the job SSE stream and media / download URLs carry `?lang=`; TanStack query keys include the language, so all server-localized text refetches on a switch.
* **Everything visible is Polish**: navigation, titles, subtitles, forms, placeholders, tooltips, `aria-label`s, toasts, empty states, all 24 feature names / summaries / epics (by feature id; `/api/features` stays English), statuses and enums via the dictionary,
  Recharts ticks / tooltips / legends through `fmt`, the footer banner, the Feature Map, the ROI / ACR calculator (labels, units, groups, categories, service families, lever names, tiers, sensitivity items — keyed by the model's keys, `pl/roi.ts`;
  `roi-keys.json` is generated from the vendored model and checked by a test), plurals everywhere a count appears, `1 234,56` / `18.11.2026` / 24 h / `2 godz. temu`. Server-localized text (BE) is shown as received.
* **Content language**: "Język kampanii / Campaign language" select in the brief wizard bound to `campaign.language` (follows the UI language until the user picks one); voice-over language defaults to the campaign language;
  the Localization tab takes the campaign language as its source (PL → EN/DE/FR… as well as EN → PL); claims page language filter + `label` / `notes_label`; rights `*_label` fields; badges with the content language (dashboard, brand documents, claims).
* **Layout for ~30 % longer Polish**: `Stat` values fit their tile, selects grow to their longest option, cards `min-w-0` with wrapping actions, brief wizard `Field group`, ROI KPI grid, library cards wrap instead of truncating. No clipped / overflowing text at 1280×720 and 1600×900.
  Fonts: Inter / Fraunces **latin-ext** woff2 are bundled (`@fontsource-variable`); a CDP probe in the E2E proves `ąćęłńóśźżĄĆĘŁŃÓŚŹŻ` is drawn by Inter / Fraunces, not a fallback.
* **Bugs found by the Polish run and fixed (also valid for English)**: first market chip named "Rynki DE FR …" (label around buttons), missing statuses (`in_progress`, `analyzed`, `briefing`), unhandled `ApiError` rejections,
  a stale `?lang=` beating the saved choice, voice-over hard-wired to English (the Polish render carried an English voice and badge), script VO / super inputs that kept the old claim after Auto-revise, ROI KPI tile clipping, claims page overflow.

## How to run every test

```bash
cd 02-commercial-studio-marketing/app/web
npm run typecheck && npm test && npm run build     # vitest: 36 passed + 1 opt-in report skipped (2 files, ~0.3 s)
npm run export:roi-keys -- --check                 # roi-keys.json in sync with the vendored business-case model

# offline stack on any free port (second terminal; stub AI, in-memory repo; serves web/dist, so build first). Dev server: SPOTLIGHT_API=http://127.0.0.1:8112 npx vite --port 5112 --strictPort
cd ../ && SPOTLIGHT_MODE=offline .venv/bin/uvicorn spotlight.main:app --port 8112

PY=/Users/michalfu/Dev/SwarmAI/.venv/bin/python        # Playwright (Chromium, headless)
$PY e2e/journeys_pl.py --base-url http://127.0.0.1:8112                 # 36 journeys, 33 page states, 29 screenshots → deck/assets/screens-pl/
BASE_URL=https://<app>.azurecontainerapps.io $PY e2e/journeys_pl.py     # same journeys against a deployed instance
#   --viewport 1280x720  --skip-live-ai (reuse an existing produced Polish campaign)  --only <name fragment>  --screens DIR  --no-screens  --keep-scratch
$PY e2e/journeys.py --base-url http://127.0.0.1:8112                    # English regression: 18 journeys (never pass --screens deck/assets/screens)
$PY ../../tools/pl_audit/pl_audit.py --app studio --base-url http://127.0.0.1:8112 --out <dir> --lang pl --viewport 1600x900   # orchestrator's independent audit
```

Results on the BE's code of 2026-11-18 10:50 (fresh offline backend):

| check | result |
|---|---|
| `npm run typecheck`, `npm run build` | clean |
| vitest (`i18n.test.ts`, `format.test.ts`) | 36 passed, 1 skipped (opt-in report) |
| `journeys_pl.py` 1600×900 | **36/36 journeys**, 33 page states, 29 screenshots |
| `journeys_pl.py --viewport 1280x720 --skip-live-ai` | **27/27 journeys**, 21 page states |
| `pl_audit` (27 routes × 2 viewports, incl. the 11 tab routes of the produced campaign) | `__i18nMissing` 0 · console errors 0 · overflow-x 0 · clipped 0 (excl. `.sr-only`) · skeletons 0 |
| `journeys.py` (English) | **18/18**; `deck/assets/screens/` untouched |
| `scripts/smoke_test.py` (BE's, run only) | 44/44 |

What the Polish E2E proves: language behaviour (`?lang=`, localStorage, `<html lang>`, no reload, headers on every call, `?lang=` on SSE / media / downloads, refetch on switch, header switch on every route, campaign-language select);
the Polish pipeline end to end (brief → questions → normalized brief → strategy → script → Guardian BLOCK on "leczy poranny niepokój" → auto-revise → storyboard → VO → render with ffprobe → formats → localization PL → EN → scorecard →
provenance + tamper test → approvals (Guardian refusal in Polish, then approved) + audit chain → variants → performance → planner → library → cost → ROI → team → ops → feature map → dashboard → fonts → API docs);
and on every page state: `window.__i18nMissing` empty, no English leftovers (stop-word scan over text and `placeholder` / `aria-label` / `title` / `alt`), no raw enum values, pl-PL number / date formats, no overflow / clipped text / cut-off `<select>` / cut-off placeholders, console clean.
Screenshots (1600×900) `deck/assets/screens-pl/NN-<view>.png`: the 26 names of `deck/assets/screens/` plus `02b`, `05a`, `05b`. They were taken against the **offline** backend (badge "OFFLINE · SYMULOWANE AI"); re-run against Azure to replace them.

## Facts for the docs agents (README "Languages", REPORT, FEATURES CS-10 / CS-20, ARCHITECTURE)

* Switch: header control on every page; remembered in `localStorage` (`studio.lang`); `?lang=pl` deep link. Adding a language: `app/web/src/i18n/README.md` ("Adding a language") + the BE catalog in `app/src/spotlight/i18n/`.
* ARCHITECTURE row: "UI i18n — custom layer (`Intl.*`, CLDR plurals, English-as-key, id-keyed enum tables), dictionaries completeness enforced by `npm test`, server text localized by the BE (locale middleware + catalogs), content language per campaign".
* Evidence: the table above, `deck/assets/screens-pl/` (29 PNG), `app/e2e/journeys_pl.py` (36 journeys), `app/web/src/i18n/*.test.ts` (36 tests).

## Known gaps / limits

* The FE translates a few **English constants the API returns verbatim** with `tKnown()` (library name "Spotlight Procedural Library …" and any team / planner / cost / scorecard / provenance / market note the server leaves in English).
  The BE now localizes all of these, so they pass through untouched; if the BE rewords an English constant that is not localized, the Polish UI silently shows the new English text.
* Items I asked the BE for during the run (formats-tree notes, caption chunking at sentence/comma boundaries, "claim/claimy" wording, `language` on the studio overview, localized job titles, insight platform label, music `licensor_label`) were fixed by the BE and verified on its 10:50 code.
  Job titles are shown as the server renders them (persona + details); the FE dictionary (`jobKind`) is only the fallback.
* Native `<input type="date">` follows the browser's locale, not the UI language. The browser tab title stays the product name (`Spotlight — SwarmAI Commercial Studio`) in both languages. English UI times use the browser's time zone; Polish uses `Europe/Warsaw`.
* Asset tags in the library (`cutdown`, `captions`, `ai-generated`, …) and file names are metadata shown as stored (they are editable and searched as stored); the Swagger UI at `/docs` is FastAPI's English developer documentation.
* `tools/pl_audit` heuristics report false positives that are correct Polish: `.sr-only` spans (reported as clipped), API paths and `{id}` templates in `<code>`, `Limit`, `5 min`, `OK`, `Format`, `master`, `m.in.` / `(WE)`, decimal commas with three digits (`0,171 USD`),
  `6/15/30 s`, document file names, aborted `<video preload>` requests on navigation (`requestfailed`, the server answers 206). Suggested allow-list for the tool.
* The English copy "Seven seeded violations — …" (Guardian playground) lists eight; the Polish text says "Osiem" (8 `expected_rules`). English left untouched on purpose.
* Not run by me: the live-Azure pass (orchestrator). With the real LLM the journeys assert the Polish UI and structure, not generated wording; the only content assumption is that the brief's mandatory line (inserted verbatim) is blocked by the Guardian.
* `app/web/tsconfig.tsbuildinfo` is tracked and is rewritten by every build; `package.json` gained `vitest` + `@types/node` (lock file updated, `npm ci` verified in dry-run), `vite.config.ts` reads `SPOTLIGHT_API` / `SPOTLIGHT_WEB_PORT` for a second dev instance.
