# Polish terminology glossary (Concierge UI)

One term, one translation. The Polish dictionaries in `pl/*.ts` follow this table; `i18n.test.ts` keeps them complete, but wording is a human decision, so
change a term **here and in the dictionaries together**. English is the key language of the code (`t('English text')`), so the left column is the English
term the UI uses.

## Register and style

| Rule | Example |
|---|---|
| Operator UI (consoles, admin pages): imperative / infinitive, short | „Zapisz”, „Anuluj”, „Uruchom ocenę”, „Przejmij” |
| Toward customers (widget, voice, e-mail/SMS text): formal **Pan / Pani / Państwo**, gender-neutral phrasing where possible | „Czy mogę w czymś jeszcze pomóc?”, never a guessed „Pan” or „Pani” |
| Natural professional Polish, not word for word | *containment* = „obsługa w całości przez AI”, not „powstrzymanie” |
| Quotation marks | „…” (U+201E / U+201D) in Polish text; the English UI keeps “…” |
| Dashes, ranges, ellipsis | spaced em dash between clauses („… — …”), en dash in ranges („1–5”, „09:00–17:00”), one ellipsis character „…” (never three dots) |
| Non-breaking space | in prose (descriptions, hints, long sentences) a one-letter word (**i, w, z, o, u, a**) is followed by U+00A0, written `\u00a0` in the dictionary string, so it never ends a line; not in short labels: `'w\u00a0widżecie'` |
| Button verbs | imperative, the verb a Polish UI normally uses (perfective for one-off actions: „Zapisz”, „Uruchom”; imperfective for modes: „Symuluj”, „Monitoruj”); confirmations in the impersonal past: „Zapisano”, „Zaplanowano” |
| Tone | factual; no exclamation marks, no emoji in operator text |

## Roles and objects

| English | Polish | Notes |
|---|---|---|
| human agent / contact-center agent | **konsultant** (pl. konsultanci, gen. pl. *konsultantów*) | never plain „agent” for a person |
| AI agent | **agent AI** | „agent” alone means the AI; „Agent Assist” stays as a product name |
| supervisor | **supervisor** (gen. *supervisora*, pl. *supervisorzy*) | loan word used by Polish contact-center professionals |
| customer | **klient** (gen. pl. *klientów*) | |
| queue | **kolejka** | queue names come from the server, localized there |
| routing | **routing** | loan word; the button verb is „Skieruj” |
| escalation | **eskalacja** | |
| handoff | **przekazanie rozmowy** | „przekazanie do konsultanta” when the target is named |
| warm handoff with context package | **przekazanie rozmowy z pakietem kontekstu** | |
| wrap-up | **podsumowanie rozmowy** | button „Zakończ i podsumuj” |
| conversation / contact | **rozmowa** / **kontakt** | *contact* in metrics = **kontakt** |
| Customer 360 | **Klient 360** | |
| knowledge base | **baza wiedzy** | article = **artykuł**, quarantine = **kwarantanna** |
| citation | **cytowanie** / „powołuje się na” | |
| groundedness | **ugruntowanie odpowiedzi** („oparta na źródłach” for the badge) | |
| approval | **zatwierdzenie** | status values via `te('approvalStatus', …)` |
| audit trail | **ślad audytu** | |
| retention | **retencja** | „Retencja i audyt” |
| guard (input / output) | **ochrona** wejścia / wyjścia | the tab „Ochrona wejścia i wyjścia”, the page „Zgodność i ochrona przed ryzykiem”; not „strażnik” (a person, not a safeguard) |
| budget guard (daily AI budget) | **bezpiecznik budżetu** | fails closed: „po jego wyczerpaniu blokuje wywołania” |
| red team | **red team** | „zestaw red team”; not translated |
| stress mode (guard off + gullible model) | **warunki skrajne** | not „stres” |
| data exfiltration | **eksfiltracja danych** | not „wyprowadzanie danych” |
| evaluation harness | **środowisko oceny i symulacji** | |
| evaluation gate | **bramka oceny** | |
| canary | **kanarek** | „kanarek 10%” |
| rollout / promote / rollback | **wdrożenie** / **wdróż** / **wycofanie** | „promocja” only for a marketing promotion (WFM planner), never for promoting a version |
| agent configuration | **konfiguracja agenta** | |
| persona | **persona** | |
| scenario | **scenariusz** | |
| connector | **konektor** | |
| whisper (supervisor to agent) | **podpowiedź (whisper)** | the English name stays in brackets |
| take over / barge-in / monitor | **przejęcie** / **wejście w rozmowę** / **monitorowanie** | |
| callback | **oddzwonienie** | |
| quiet hours | **cisza nocna** | outbound time window |
| opt-out | **rezygnacja** | inbound keywords STOP, REZYGNUJĘ, WYPISZ MNIE |
| prompt injection | **prompt injection** | not translated |
| redaction / masking | **maskowanie** / **zamaskowano** | never „redakcja”; PII = **dane osobowe** (RODO), PCI = **dane kart płatniczych** |
| OTP | **kod jednorazowy (OTP)** | KBA = zapasowa weryfikacja wiedzą |
| verification level | **poziom weryfikacji** | L0, L1, L2 stay |
| turn (one exchange in a dialogue) | **wypowiedź** (customer) / **odpowiedź** (AI) | „tura” is not used |
| next-best-action | **kolejne najlepsze działanie** | |
| tenant (Entra) / customer organisation | **dzierżawa** / **organizacja** | |
| legacy / retiring service | **wycofywany** | „przestarzały” would mean *deprecated* |
| stub / mock | **atrapa** (**atrapa (stub)** where the mode is named) | |
| cache (tokens) | **pamięć podręczna** | |
| disposition code | **kod wyniku rozmowy** | not „dyspozycja” (a bank instruction) |
| policy (system rule) / policy (business rule) | **polityka** (policy engine, „pod kontrolą polityk”) / **zasady** (return policy, KB) | |

## Customer-service vocabulary (the legal meaning matters)

| English | Polish | Notes |
|---|---|---|
| return of goods | **zwrot towaru** | the physical return, pickup |
| refund | **zwrot środków** | money back; „zwrot pieniędzy” only in customer speech |
| warranty claim / consumer complaint about a defect | **reklamacja** | |
| complaint (dissatisfaction, no legal claim) | **skarga** | **not** the same as *reklamacja* |
| regulatory complaint | **skarga do organu nadzoru** | |
| withdrawal from a distance contract (14 days) | **odstąpienie od umowy (14 dni)** | |
| statutory warranty / commercial guarantee | **rękojmia** / **gwarancja** | |
| GDPR | **RODO** | `privacy` = „prywatność (RODO)” |
| goodwill credit | **bon rekompensacyjny** | never „uznanie handlowe” |
| goodwill gesture / request | **gest dobrej woli** | the gesture itself; its money form is the *bon rekompensacyjny* |
| legal threat | **groźba prawna** | short tag; asserted by `i18n.test.ts` and the BE catalogue („groźba kroków prawnych” in running text) |
| order / delivery / carrier | **zamówienie** / **dostawa** / **przewoźnik** | InPost, DPD, DHL are names, not translated |

## Metrics and analytics

| English | Polish | Notes |
|---|---|---|
| containment (resolved by AI alone) | **obsługa w całości przez AI** (short: „Obsł. przez AI”) | what-if: „Symulacja udziału AI”; the English word may follow once in brackets |
| deflection (AI-resolved share) | **odciążenie (deflection)** | never above containment |
| AI-first contact | **kontakt AI-first** (kierowany najpierw do AI) | |
| service level (SL, e.g. 80/20) | **poziom obsługi (SL)** | not „poziom usług”; SLA stays |
| capacity plan / AI capacity | **plan zasobów** / **przepustowość AI** | not „zdolności” |
| churn (risk) | **odejście klienta** („ryzyko odejścia klienta”), aggregate **odpływ klientów** | „rezygnacja” is only an outbound opt-out |
| business case (the ROI model) | **model finansowy** | „model biznesowy” means *business model* |
| burn rate (error budget) | **tempo spalania** (budżetu błędów) | |
| overflow (excess traffic sent to a contractor) | **overflow** | kept; explained once in the ROI labels |
| first-contact resolution (FCR) | **rozwiązanie za pierwszym kontaktem (FCR)** | acronym kept |
| average handle time (AHT) | **średni czas obsługi (AHT)** | |
| CSAT, SLA, KPI, QA, VoC, WFM, FTE, ASA, MAPE | kept as acronyms | the text that introduces one expands it once, e.g. „Analityka głosu klienta (VoC)” |
| voice of customer | **analityka głosu klienta (VoC)** | |
| workforce forecast & staffing | **prognoza i obsada (WFM)** | |
| FTE | **etat** | „Etaty konsultantów” |
| shrinkage | **współczynnik nieobecności (shrinkage)** | |
| occupancy | **obłożenie** | |
| backtest | **backtest** | „backtest kroczący” |
| contact driver (Pareto) | **przyczyna kontaktu** | |
| sentiment | **nastrój** | heat map = **mapa cieplna nastrojów** |
| calibration / agreement / weighted kappa | **kalibracja** / **zgodność ocen** / **ważona kappa** | |
| scoring rubric / dimension | **karta oceny** / **wymiar oceny** | „rubryka” means a newspaper column |
| coaching | **coaching** | |
| ACR (Azure consumed revenue) | **ACR** („konsumpcja Azure (ACR)”) | sales term; measured usage in the metering pages = **zużycie**. ROI / ACR calculator labels come from the model keys: `tl('roi…', key, label)` |

## Loan words that stay in English

supervisor, routing, SLA, KPI, QA, VoC, WFM, CSAT, AHT, FCR, FTE, ASA, OTP, PII, PCI, API, IaC, FinOps, red team, prompt injection, jailbreak, Agent Assist, whisper, shrinkage, backtest, coaching, overflow, embedding, endpoint, trunk SIP.
Product and company names are never translated: Concierge, Contoso Home Retail, Azure OpenAI, Cosmos DB, InPost, DPD, DHL.
The allow-lists of the leftover scan (`leftovers.json`) must contain every English word that is meant to stay, and nothing else.

## Formats (always through `useI18n().fmt`; never `toFixed` / `toLocaleString` inside a page)

| Kind | English UI | Polish UI |
|---|---|---|
| number | `1,234.5` | `1 234,5` (NBSP; grouping also for 4 digits) |
| percent | `12.5%` | `12,5%` |
| currency | `$27.10`, `€379.00` | `27,10 USD`, `379,00 €`, **`1 599,00 zł`** (PLN) |
| amount of a record (order, refund, approval) | its own currency: `fmt.money(amount, currency)` | same; EUR and PLN are never mixed up |
| date / time | `Nov 18, 2026, 9:41 AM` | `18 lis 2026, 09:41`; numeric `18.11.2026`; time zone Europe/Warsaw |
| plural | one / other: `tn(n, { one: '{n} file', other: '{n} files' })` | one / few / many / other, stored in the dictionary (`n` table, key = the English `other` form): `1 zdarzenie`, `2 zdarzenia`, `5 zdarzeń`, `22 zdarzenia` |
| sort | by code | `Intl.Collator('pl')`: ą after a, ł after l, ś after s |
| search | case-insensitive | additionally diacritic-insensitive, including ł / Ł (`lodz` finds „Łódź”) |

After „z”, „dla”, „od” the noun is in the genitive plural („z 20 klientów”, „dla 8 zdań”): write the Polish `few` / `many` forms of such a string in the genitive.

## Adding or changing a term

1. Edit the dictionary entry in `pl/<area>.ts` (the key is the exact English string).
2. Run `npm test`: it fails on missing, unused or duplicated keys, wrong `{placeholders}` and untranslated English words.
3. Update this table when the term is a recurring one.
