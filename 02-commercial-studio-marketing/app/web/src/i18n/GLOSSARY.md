# Spotlight UI glossary — English → Polish (pl)

The single source of truth for terminology in `src/i18n/pl/*.ts`. When a term below appears in the UI it must be rendered **exactly** as shown, in every page, tooltip,
`aria-label`, toast and chart. Keep this file in sync with the dictionaries (reviewers: grep a term, then check this table).

**Style.** Natural, professional Polish — not literal MT; neutral operator-UI register (no "my / nasz" voice; the reader is addressed only in instructions, in the "Ty" form: "Wklej brief").
UI commands are **imperative**: native verbs in the perfective ("Zapisz", "Anuluj", "Dodaj claim", "Wklej brief", "Uruchom"), verbs borrowed from English in the imperfective ("Generuj", "Renderuj", "Synchronizuj", "Testuj", "Eksportuj") — one form per verb in labels (buttons, menus, tabs). Running instructions in empty states and hints may use the perfective of the same verb ("Najpierw wygeneruj klatki kluczowe", "Zsynchronizuj konektor lub wgraj plik CSV") because they describe one completed step.
Quotes are „low-high”. Dashes: a spaced em dash ` — ` between clauses, an unspaced en dash for ranges (`3–5`, `p10–p90`); ellipsis `…`; sentence case in titles and labels.
Polish marketing professionals keep a number of English loan words; so do we (brief, spot, storyboard, claim, hook, talent, stock, render, master, KPI, SLA, CTA, A/B …) — they are listed here on purpose.
Acronyms are written as is (ROI, NPV, IRR, ACR, CTR, CVR, CPA, ROAS, SKU, TTS, SRT, LUFS, C2PA) and explained once in the page text or tooltip where a reader may not know them.
A foreign gloss in brackets (`Strażnik marki (Brand Guardian)`, `księga stylu (style bible)`) appears **once** — where the term is introduced — and never again on the same page.

## Do not translate

Product and brand names (Spotlight, SwarmAI, Northwind, Contoso, Azure, Azure OpenAI, Azure AI Content Safety, Azure AI Speech, Cosmos DB, Fabric, Teams, Slack, Entra ID, Brand Brain),
model and deployment names (gpt-image-1.5, tts-hd, text-embedding-3-small), codes and ids (CS-01, `claims.prohibited`, `approval.approved`), API paths and JSON keys, file names,
territory / language / currency codes (PL, DE, USD), and **customer-typed or generated content** (campaign names, brief text, script lines, claims, comments) — it is shown as it was written.

## Terms

| English | Polish | Notes |
|---|---|---|
| brand kit / tagline | zestaw marki / hasło marki | versioned: *wersja zestawu*; "tagline" is never left in English (a Polish "claim" would be the compliance term below) |
| Brand Brain | Brand Brain | product name, never inflected in headings |
| Brand Guardian / Guardian | Strażnik marki / Strażnik | "Strażnik marki (Brand Guardian)" in exactly three places (dashboard intro, CS-12 page title, feature map); card titles "Strażnik marki"; everywhere else "Strażnik" |
| brief / creative brief | brief / brief kreatywny | "brief" is the everyday word, "brief kreatywny" only in the dashboard intro; *sfinalizować brief*, *znormalizowany brief*; mandatories = elementy obowiązkowe |
| artifact | materiał (wersjonowany) | brief, strategy, script … are versioned materials ("Materiał v3"); the server says "materiał" too |
| Briefing agent | Agent ds. briefów | other agents: Strateg, Agent scenariusza i tekstów, Dyrektor artystyczny, Projektant dźwięku, Lokalizator, Analityk mediowy |
| campaign | kampania | |
| campaign language / UI language | język kampanii / język interfejsu | the first is the language of the creative content, the second of the interface |
| strategy / territory / big idea | strategia / kierunek / główna idea (big idea) | "Wybierz ten kierunek" |
| script / beat / voice-over / super / captions | scenariusz / segment / lektor / napis ekranowy / napisy | *kwestia* = a spoken line; "lektor" = the narrator and the VO text (one word for both, never "narracja"); a bare "Napis" only in narrow table headers; "napisy" = captions / subtitles (SRT, wtopione w obraz) |
| storyboard / shot list / keyframe | storyboard / lista ujęć / klatka kluczowa | "księga stylu (style bible)" |
| spot / master / cutdown / end card / compositor | spot / master / wersja skrócona / plansza końcowa / montaż | "master" stays (video industry); the compositor is *montaż spotu* — never "kompozytor" (in Polish a music composer) |
| render quality: Preview / Cinematic | tryb renderu: podgląd / filmowy | "Tryb renderu", "Podgląd" (Ken-Burns camera moves on the keyframes, *ruch kamery na nieruchomych klatkach*) and "Filmowy" (AI video); chip "Filmowy · ruch AI: 4/4 ujęć" |
| AI motion / AI clip / motion prompt / model prompt | ruch AI / klip AI / opis ruchu / prompt dla modelu | one clip per shot; "opis ruchu" = what moves after the opening frame (*klatka kluczowa jest pierwszą klatką ujęcia*); the English prompt the model reads is "prompt dla modelu (EN)" |
| GPU worker / cold / warming up / ready / warm up | serwer GPU / uśpiony / rozgrzewa się / gotowy / rozgrzać GPU | "Serwer GPU: uśpiony" (scaled to zero), button "Rozgrzej GPU"; the offline procedural animator is "symulator ruchu offline" |
| cached clip / fallback shot | z pamięci podręcznej / ujęcie zastępcze | "pamięć podręczna", never "cache"; a fallback shot keeps *ruch kamery na klatce kluczowej* instead of the AI clip (plural: 1 ujęcie, 2 ujęcia, 5 ujęć zastępczych) |
| variant / experiment / bandit / hook / CTA / visual | wariant / eksperyment / test A/B / hook / CTA (wezwanie do działania) / obraz | nav "Warianty i testy A/B"; *bandyta* (Thompson sampling) only in the technical subtitle; "visual" = *obraz* in headers and chips, *warstwa wizualna* in sentences |
| claim | claim (pl. claimy) | loan used by Polish agencies and compliance teams; glossed once as "twierdzenie reklamowe" in the claims-library intro. approved / prohibited / needs substantiation = zatwierdzony / zakazany / wymaga udokumentowania. The regulatory pack is "oświadczenia zdrowotne UE" (health claims) |
| disclaimer / rule pack | zastrzeżenie / pakiet reguł | "wymagane zastrzeżenie" |
| rights registry / consent / licensor | rejestr praw i licencji / zgoda / licencjodawca | entry = wpis w rejestrze praw; talent = talent (osoba występująca), stock = materiał stockowy ("stock" in tables) |
| territory / window | terytorium / okres ważności | "Okres ważności" = valid-from → valid-to; "Emisja od / do" = on-air dates |
| finding / verdict | uwaga / werdykt | "uwaga blokująca"; the server's messages say "uwaga Strażnika marki" too. block = blokada, warn = ostrzeżenie, pass = zgodne |
| check / compliance check | kontrola / kontrola zgodności | button "Sprawdź zgodność"; the score is "Wynik zgodności"; "Uruchom Strażnika" runs all checks; "kontrola jakości" = QA |
| waive | zatwierdzić wyjątek | button "Zatwierdź wyjątek…", state "wyjątek" |
| auto-revise | autopoprawa | "Autopoprawa zakończona sukcesem" (server texts should use the same word, not "automatyczna korekta") |
| approval / stage gate / SLA | zatwierdzenie / bramka etapu / SLA | roles: Administrator, Brand Manager, Dyrektor kreatywny, Specjalista kreatywny, Dział prawny / Compliance, Agencja (gość) |
| audit trail / hash chain | ścieżka audytu / łańcuch skrótów | "łańcuch zweryfikowany"; the audit *log* is "dziennik audytu" |
| provenance / manifest / tamper test | pochodzenie / manifest pochodzenia / test manipulacji | in full: "pochodzenie treści"; not "ścieżka pochodzenia" — "ścieżka" is reserved for the audit trail; Content Credentials = poświadczenia treści (C2PA) |
| AI disclosure | oznaczenie AI | burned-in label: "Wygenerowano przez AI"; the requirement itself: "ujawnienie użycia AI" |
| localization / transcreation / back-translation | lokalizacja / transkreacja / tłumaczenie zwrotne | glossary = glosariusz, do-not-translate = terminy nietłumaczone (DNT), enforcement = egzekwowanie |
| scorecard (pre-flight) | karta oceny (przed emisją) | labelled "predykcja / symulacja" |
| cost meter / spend / cap | licznik kosztów / wydatki / limit | "Wydatki na AI", "limit dzienny", "limit na kampanię"; *fail closed* = "blokada po przekroczeniu limitu" (no English in the UI text) |
| insight / learning | wniosek / wniosek | one word for all three uses (the strategist's "Insights" card, the performance "Insights" page and nav item share one English key; learnings written back to the Brand Brain): "Wnioski", "Wnioski z wyników" |
| planner / media mix | planer / miks mediowy | |
| embeddings / embedded | embeddingi / zwektoryzowane | "zwektoryzowano i zaindeksowano 31 fragmentów" |
| seeded violations | naruszenia testowe | Guardian playground: "Przywróć naruszenia testowe" |
| asset library | biblioteka zasobów | |
| feature map / epic | mapa funkcji / epik | |
| ROI calculator | kalkulator ROI i ACR | ROI, NPV (wartość bieżąca netto), IRR, okres zwrotu, ACR = zużycie Azure; run-rate = roczny poziom zużycia; "business case" stays |
| lever / expansion / tier | dźwignia / ekspansja / poziom | E1–E4: wideo generatywne, treści katalogowe, personalizacja, platforma danych |
| scenario | scenariusz (kalkulatora) | Zachowawczy / Bazowy / Optymistyczny |
| sensitivity (tornado) | analiza wrażliwości (tornado) | |
| synthetic data / simulated | dane syntetyczne / symulowane | the footer banner |
| GDPR | RODO | |

## Numbers, dates, typography

* Numbers `1 234,56` (NBSP thousands, decimal comma; 4-digit numbers are grouped too so columns align), percent `12,3%`, USD `1 234,50 USD`, compact `6,98 mln USD` / `465 tys. USD`, PLN `379,00 zł`.
* Dates `18.11.2026`, times `08:21` (24 h, `Europe/Warsaw` for absolute times), relative `2 godz. temu`, `za 3 dni`, `wczoraj`.
* Units follow CLDR: `godz.`, `min`, `s`, `dni` (never a bare "d" or "h"), `mies.`, `mln`, `tys.`, `zł`; international symbols stay (`MB`, `KB`, `fps`, `LUFS`, `dBFS`, `bpm`, `ms`).
* Plurals follow CLDR one / few / many / other: 1 wariant, 2 warianty, 5 wariantów, 22 warianty, 1,5 wariantu (`tn()`); every count in the UI goes through it. Where a variable name or label follows a preposition it is put after a colon ("Cofnięto: {title}", "zgłaszający: {name}") so it never needs a case ending.
* A no-break space follows one-letter words (a, i, o, u, w, z) — `nbspOneLetterWords` does it for every translated string at run time — and sits between a number and its unit (`15 s`, `5 MB`, `1 mln`); the dictionary writes the latter as `\u00A0`.
* Sorting uses `Intl.Collator("pl")` (ą after a, ł after l, ś after s …); search is diacritic-insensitive including ł/Ł (`lodz` finds `Łódź`).
