# Spotlight i18n (web)

A small custom i18n layer (no runtime dependency, ~600 lines, fully bundled — no CDN): English text is the key, dictionaries live in `pl/`, ICU (`Intl.*`) does plurals, numbers, dates, collation.
Custom instead of i18next because the whole surface is one SPA with two languages, the English source text must stay readable in the code, and the test that every literal has a Polish entry needs a TypeScript-AST extractor (`extract.ts`) either way.

```tsx
const { t, tn, tEnum, tOpen, tKnown, tx, fmt, lang, setLang } = useI18n();
t("Save")                                              // English source = key; {name} interpolation: t("Hello {name}", { name })
tn(n, { one: "{n} file", other: "{n} files" })         // CLDR plurals (Polish: one / few / many / other)
tEnum("status", "in_review")                           // id-keyed labels (statuses, roles, feature names, ROI model keys); API text / humanized id as fallback
tOpen("channel", id)                                   // open sets (channels, territories): the label when known, otherwise the raw id (never "missing")
tKnown(apiText)                                        // API text as received, unless it is one of the dictionary's own English sources (the server did not localize it)
tx("None yet — <go>start one</go>.", { go: (c) => <Link>{c}</Link> })   // markup inside the message, so word order can differ per language
fmt.number / fixed / usd / currency / percent / pct / date / time / dateTime / relative / compactUsd / isoDate / languageName / codes
```

* **Missing key** → English text, `console.warn` once, entry pushed into `window.__i18nMissing` (an array that always exists; the E2E asserts it is empty on every page).
* **Language state** is module-level (`getLang()`), so `api.ts` reads it too: every request carries `X-UI-Lang` and `Accept-Language`; `withLang(url)` adds `?lang=` to EventSource URLs. All TanStack queries include the language in their hash → a switch refetches everything.
* **Initial language**: `?lang=` → saved choice (`localStorage["studio.lang"]`) → `navigator.languages` → `en`. An explicit switch drops a leftover `?lang=` from the address bar. `<html lang>`, the document title and the meta description follow.
* **Test hook** `window.__i18n = { lang, t, tn, tEnum }` (read-only) lets the E2E derive selectors from the dictionary.
* **Server text** is shown as received (the BE localizes messages, hints, Guardian findings, summaries). Machine ids (`code`, `status`, `key`) are never translated by the BE; the UI maps them with `tEnum`.
* **ROI / ACR labels** are keyed by the business-case model's keys: `pl/roi.ts`. `npm run export:roi-keys` regenerates `roi-keys.json` from `spotlight.vendor.model`; the unit test fails when a lever, benefit, cost, service family, sensitivity driver, override spec or unit has no Polish label (`-- --check` reports a stale file).

## Files

| file | purpose |
|---|---|
| `core.ts` | pure functions: `createTranslator`, plurals (`Intl.PluralRules`), interpolation, `resolveInitialLang`, collation, `matchesQuery` |
| `format.ts` | `createFormatter(lang)` — `Intl.NumberFormat/DateTimeFormat/RelativeTimeFormat/DisplayNames`, `pl-PL`, `Europe/Warsaw` |
| `search.ts` | `foldText` — accent folding that also maps ł/Ł, ø, đ, ß … (NFKD does not decompose them) |
| `index.tsx` | React glue: `useI18n`, `setLang`, `initLang`, `useOnLangChange`, `useLocalizedDefault`, `msg()` |
| `en.ts` | ID-keyed English tables the UI owns (statuses, roles, gates …) |
| `pl.ts`, `pl/*.ts` | the Polish dictionary: `messages-*.ts` (by area), `plurals.ts`, `enums.ts`, `features.ts`, `roi.ts`, `backend.ts` (values only a real backend returns), `motion.ts` (cinematic motion: messages + plurals + enums) |
| `extract.ts` | TypeScript-AST extraction of every `t()/tx()/msg()/tn()/tEnum()` literal (test only) |
| `GLOSSARY.md` | terminology |

## Tests (`npm test`, ~0.3 s)

* `i18n.test.ts` — every literal has a Polish entry and no Polish entry is unused; `{placeholders}` match; no Polish text equals the English source unless it is on the explicit `SAME_IN_POLISH` list (names, cognates, loan words);
  all four Polish plural forms; enum tables complete in both languages; every ROI model key has a Polish label.
* `format.test.ts` — plural categories (1 / 2–4 / 5–21 / 22–24 / 1,5), number / currency / percent / date / time / relative formats, collation (ą ć ę ł ń ó ś ź ż), ł-safe search, language resolution, `tKnown`, `tEnum`, `tOpen`.
* `motion-pl.test.ts` — typography of the cinematic-motion strings (ellipsis, quotes, no-break unit spaces, punctuation and case parity with the source, rich-message tags, plural forms). The motion components themselves are tested in `src/motion/*.test.ts(x)`: pure helpers + mocked `fetch`, and the components rendered with `react-dom/server` in node (no DOM library) in English and Polish, asserting roles/labels, the states (unavailable / cold / warming / ready / budget refusal) and that no key is reported missing.
* Browser: `app/e2e/journeys_pl.py` (Polish journeys + per-page quality gate), `app/e2e/journeys.py` (English, unchanged).

## Adding a language (e.g. German)

1. `core.ts`: add `"de"` to `Lang`, `SUPPORTED_LANGS`, `LANG_META` (`name: "Deutsch"`, `locale: "de-DE"`, optional `timeZone`); `format.ts`: the grouping/zone defaults and `compactUsd` for the language.
2. Create `de.ts` + `de/*.ts` shaped like `pl` (`messages`, `plurals` with the language's CLDR categories, `enums`, `features`, `roi`), register it in `index.tsx` (`createTranslator(lang, { pl, de }, en.enums)`), and extend `i18n.test.ts` so the completeness / unused / placeholder checks loop over every dictionary.
3. `npm run export:roi-keys` is language-neutral; add the German tables in `de/roi.ts`.
4. Backend: add the catalog in `app/src/spotlight/i18n/` (messages, plural rules, formats) and the language to `/api/meta`.
5. Add `journeys_<lang>.py` by copying `journeys_pl.py` (labels are read from the dictionary, so the selectors carry over) and the glyph/overflow checks for the new language's letters.
