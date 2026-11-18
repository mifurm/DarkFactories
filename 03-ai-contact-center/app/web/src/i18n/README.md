# i18n of the Concierge web app

English and Polish, switchable at run time without a reload, remembered per browser. The terminology lives in [GLOSSARY.md](GLOSSARY.md).

## Why this design (and not a library)

* **The English text is the key.** `t('Run suite')` reads like the screen, English stays byte-identical (the fallback *is* the key), and a missing Polish entry can never
  render a blank or an opaque id. A test extracts every literal from the source and compares it with the dictionary, so a typo in a key is a failing test, not a silent English leftover.
* **No runtime dependency.** The app already ships React 19 and Intl. Plurals use `Intl.PluralRules`, numbers / currency / dates `Intl.*Format`, sorting `Intl.Collator`. A message-format
  library would add a dependency and a second syntax for features this UI uses in four shapes (`t`, `tn`, `te`, `rich`).
* **One store, no remount.** The language lives in `core.ts` (`getLang` / `setLang` / `subscribeLang`, `useSyncExternalStore`). `setLang` writes `localStorage` (`concierge.lang`),
  `<html lang>` and the document title, and fires `concierge:lang`, so `useApi` refetches and every page re-renders in place.
* **Resolution order:** `?lang=` → saved choice → `navigator.languages` (first supported) → `en`.

## Files

| File | Role |
|---|---|
| `types.ts` | `Lang`, `Dict` (`t` literals, `n` plurals, `k` keyed tables), `window.__i18nMissing` |
| `core.ts` | language store, `translate`, `translateN`, `translateKeyed`, `translateLabel` (server label + UI override), `translateServer`, rich text |
| `format.ts` | `makeFmt(lang)`: numbers, percent, money (EUR / PLN / USD), dates and times (Europe/Warsaw), durations; `makeCollator`; `fold` / `includesFolded` (diacritic-insensitive, incl. ł / Ł) |
| `index.ts` | `I18nProvider`, `useI18n()` → `{ lang, t, tn, te, tl, ts, rich, fmt, compare, includes }` |
| `en.ts` | English tables for closed enum groups (statuses, bands, roles …); open sets fall back to the server value |
| `pl.ts`, `pl/*.ts` | the Polish dictionary: every partial in `pl/` is merged automatically; one file per feature area. Prose strings keep a one-letter word (i, w, z, o, u, a) together with the next word through `\u00a0`; see the typography rows of [GLOSSARY.md](GLOSSARY.md) |
| `mark.ts` | `N_('text')` marks a string for extraction when it is rendered later with `tr(variable)` |
| `extract.ts`, `i18n.test.ts` | static extractor of the sources + the vitest suite (`npm test`) |
| `leftovers.json` | allow-lists of English words/phrases the *English-leftover* heuristic accepts; shared with the Python E2E (`tests/e2e/i18n_helpers.py`) |
| `LanguageSwitcher.tsx` | the header switch (every page, including the customer widget and the call page) |
| `useConversationLang.ts` | the customer pages: the language selector sets **both** the labels and the conversation language |

## Using it in a page

```tsx
const { t, tn, te, tl, ts, rich, fmt, compare, includes } = useI18n()
t('Run suite')                                             // literal
t('Routed to {queue}', { queue })                           // placeholders must match in both languages
tn(n, { one: '{n} event', other: '{n} events' })           // Polish one / few / many / other from the dictionary
te('orderStatus', o.status)                                 // enum value -> label; never render the raw value
tl('queue', q.queue, q.name)                                // stable key + server label (UI dictionary wins if it has the key)
ts(serverProse)                                             // server text shown as received; a known deterministic English text gets a Polish fallback
fmt.money(o.total, o.currency)                              // 1 599,00 zł | $1,599.00 – never toFixed / toLocaleString in a page
rows.sort((a, b) => compare(a.name, b.name))                // ą after a, ł after l
includes(c.name, query)                                     // "lodz" finds „Łódź”
```

Rules: no visible string, `aria-label`, `placeholder`, `title`, chart title / tick / tooltip may be hard-coded; code identifiers (`CU-1010`, ids, tokens) get `font-mono`;
user content (transcripts, quotes) gets `data-user-content`; a deliberately truncated preview gets `title` and `data-allow-clip`.

The API client (`lib/api.ts`) sends `Accept-Language` and `X-UI-Lang` on every request and `?lang=` on SSE / WebSocket / download URLs; the server localizes read-time text
(queue names, SLA reasons, summaries) and keeps the stable keys.

## Tests

| What | Command |
|---|---|
| dictionary completeness, unused / duplicate keys, placeholders, plural forms (one / few / many / other), pl-PL formats, no raw enums, no hard-coded JSX English | `cd app/web && npm test` |
| type check, build | `npx tsc -b --noEmit`, `npm run build` |
| Polish journeys in a real browser (leftovers, `__i18nMissing`, overflow, console) | `cd app && .venv/bin/python -m pytest tests/e2e/test_journeys_pl.py -o addopts="" -q` |
| independent crawler of every route | `python tools/pl_audit/pl_audit.py --app concierge --base-url http://127.0.0.1:5113 --out <dir> --lang pl` |

`I18N_SHOW_ALL=1 npm test` prints complete lists instead of the first entries.

## Adding a language (say `de`)

1. `types.ts`: add `'de'` to `Lang`. `core.ts`: add it to `LANGS` and `LANG_NAMES`. `format.ts`: add `de: 'de-DE'` to `LOCALES` (and a time zone if the market has one).
2. Create `de.ts` like `pl.ts` (glob `./de/*.ts`) and the partials in `de/`; copy the shape of `pl/*.ts`. Plural forms follow `Intl.PluralRules('de')`; the dictionary needs the categories of that language.
3. Register it in `core.ts` (`DICTS`) and in `useConversationLang.ts` (`isUi`); `LanguageSwitcher.tsx` lists `LANGS`, so it appears in every header by itself.
4. Add the language's function words to `leftovers.json` only if a word is meant to stay English; extend the test's language table so completeness and lint run for `de`.
5. Backend: the language needs a message catalog in `src/concierge/core/i18n.py` and an entry in the `languages` of `GET /api/meta`.
6. Run `npm test`, the E2E journeys with `?lang=de`, and the crawler with `--lang de`.
