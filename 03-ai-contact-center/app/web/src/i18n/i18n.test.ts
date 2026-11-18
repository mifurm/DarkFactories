import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseLang, resolveInitialLang, translate, translateKeyed, translateLabel, translateN, translateServer } from './core'
import { en } from './en'
import { englishLeftovers, extractAll, hardcodedAll, placeholders, tags, type LeftoverLists } from './extract'
import { ellipsize, fold, includesFolded, makeCollator, makeFmt, pluralCategory } from './format'
import leftovers from './leftovers.json'
import { N_ } from './mark'
import { pl, plDuplicates, plIdentical } from './pl'

const SRC = join(import.meta.dirname, '..')
const ex = extractAll(SRC)
const lists = leftovers as LeftoverLists & { _comment: string }
const NBSP = '\u00a0'

const uniq = <T>(xs: T[]) => [...new Set(xs)]
const show = (xs: string[]) => (process.env.I18N_SHOW_ALL ? xs : xs.slice(0, 40))

// ================================================================================================ dictionary completeness
describe('Polish dictionary completeness (t / rich / N_ / tn literals found with a real parser)', () => {
  it('scans the whole source tree and finds no t()/tn()/te() call it cannot read statically', () => {
    expect(ex.files).toBeGreaterThan(40)
    expect(ex.literals.length).toBeGreaterThan(500)
    const dynamic = ex.dynamic.filter((d) => d.file !== 'i18n/core.ts' && d.file !== 'i18n/index.ts')
    expect(dynamic.map((d) => `${d.file}:${d.line} ${d.fn}`)).toEqual([])
  })

  it('every English source text has a Polish translation', () => {
    const missing = uniq(ex.literals.filter((l) => !(l.key in pl.t)).map((l) => `${l.file}:${l.line} ${JSON.stringify(l.key)}`))
    expect(show(missing)).toEqual([])
  })

  it('every tn() has Polish one / few / many / other forms', () => {
    const missing = uniq(ex.plurals.filter((p) => !(p.key in pl.n)).map((p) => `${p.file}:${p.line} ${JSON.stringify(p.key)}`))
    expect(show(missing)).toEqual([])
    for (const [key, forms] of Object.entries(pl.n)) {
      for (const f of ['one', 'few', 'many', 'other'] as const) expect(forms[f], `${f} of ${key}`).toBeTruthy()
    }
  })

  it('has no unused Polish keys', () => {
    const used = new Set(ex.literals.map((l) => l.key))
    const unusedT = Object.keys(pl.t).filter((k) => !used.has(k))
    const usedN = new Set(ex.plurals.map((p) => p.key))
    const unusedN = Object.keys(pl.n).filter((k) => !usedN.has(k))
    expect(show(unusedT)).toEqual([])
    expect(show(unusedN)).toEqual([])
  })

  it('defines no key twice across the partials', () => {
    expect(plDuplicates).toEqual([])
  })

  it('keeps {placeholders} and <b>/<i>/<code> tags intact in every translation', () => {
    const bad: string[] = []
    for (const [k, v] of Object.entries(pl.t)) {
      if (placeholders(k).join() !== placeholders(v).join()) bad.push(`placeholders: ${k}`)
      if (tags(k).join() !== tags(v).join()) bad.push(`tags: ${k}`)
    }
    for (const [k, forms] of Object.entries(pl.n)) {
      for (const [f, v] of Object.entries(forms)) if (placeholders(k).join() !== placeholders(v).join() && !(f === 'one' && placeholders(v).length === 0)) bad.push(`plural ${f}: ${k}`)
    }
    expect(show(bad)).toEqual([])
  })

  it('does not leave a translation identical to its English source unless it is only brand names, codes and loan words', () => {
    const same = Object.entries(pl.t)
      .filter(([k, v]) => k === v && englishLeftovers(k, lists).length > 0 && !plIdentical.includes(k))
      .map(([k]) => k)
    expect(show(same)).toEqual([])
  })

  it('contains no English function / UI words in Polish translations (brand names and phrases come from leftovers.json)', () => {
    const bad: string[] = []
    const check = (where: string, text: string) => {
      const found = englishLeftovers(text, lists)
      if (found.length) bad.push(`${where} [${found.join(', ')}] ${text.slice(0, 80)}`)
    }
    for (const [k, v] of Object.entries(pl.t)) check(`t:${k.slice(0, 40)}`, v)
    for (const [k, forms] of Object.entries(pl.n)) for (const v of Object.values(forms)) check(`n:${k}`, v)
    for (const [g, table] of Object.entries(pl.k)) for (const [k, v] of Object.entries(table)) if (g !== 'server') check(`k:${g}.${k}`, v)
    expect(show(bad)).toEqual([])
  })

  it('has no hard-coded English UI text in JSX or in label/title/header properties (everything goes through t / tn / N_)', () => {
    const allowed = new Set([...lists.allowWords, ...lists.allowPhrases.flatMap((p) => p.split(' '))].map((w) => w.toLowerCase()))
    for (const w of ['ok', 'vs', 'id', 'api', 'kb', 'pii', 'pci', 'ai', 'llm', 'sla', 'qa', 'wfm', 'voc', 'crm', 'csv', 'json', 'vtt', 'txt', 'sms', 'otp', 'dtmf', 'ms', 'usd', 'eur', 'pln', 'vip', 'http', 'get', 'post', 'tls', 'rbac', 'cc', 'mm', 'yy', 'cvv', 'nrb', 'pdf', 'md', 'wav', 'pcm', 'hd', 'ui', 'en', 'pl', 'de', 'fr', 'es', 'it', 'nl', 'pt', 'cx', 'roi', 'acr', 'npv', 'irr', 'tco', 'csat', 'aht', 'fcr', 'nps', 'l1', 'p50', 'p95', 'f1', 'url', 'eta', 'iac', 'cosmos', 'db', 'blob', 'iban', 'dpd', 'inpost', 'dhl', 'bm25', 'cv']) allowed.add(w)
    const bad = hardcodedAll(SRC)
      .filter((h) => {
        const words = (h.text.match(/[A-Za-z]{2,}/g) ?? []).map((w) => w.toLowerCase())
        return words.some((w) => !allowed.has(w))
      })
      .map((h) => `${h.file}:${h.line} ${h.where} ${h.name}: ${JSON.stringify(h.text.slice(0, 70))}`)
    expect(show(bad)).toEqual([])
  })
})

// ================================================================================================ keyed tables (enums, catalogue)
describe('keyed tables: enum / status values are looked up, never shown raw', () => {
  it('every table group the code reads exists in Polish, and every Polish group (except `server`) is read somewhere', () => {
    const used = uniq(ex.groups.map((g) => g.key))
    const missing = used.filter((g) => !(g in pl.k))
    expect(missing).toEqual([])
    const unused = Object.keys(pl.k).filter((g) => g !== 'server' && !used.includes(g))
    expect(unused).toEqual([])
  })

  it('has the same keys in English and Polish for every English table', () => {
    const bad: string[] = []
    for (const [g, table] of Object.entries(en.k)) {
      const plTable = pl.k[g] ?? {}
      for (const k of Object.keys(table)) if (!(k in plTable)) bad.push(`pl missing ${g}.${k}`)
      for (const k of Object.keys(plTable)) if (!(k in table)) bad.push(`en missing ${g}.${k}`)
    }
    expect(show(bad)).toEqual([])
  })

  it('never renders an enum value verbatim in Polish (snake_case, or identical to the raw value) unless it is a listed loan word', () => {
    const loan = new Set(['ok', 'offline', 'azure', 'AI', 'QA', 'WFM', 'webhook', 'SMS', 'e-mail', 'WhatsApp', 'LLM', 'LLMOps', 'supervisor', 'Start', 'VIP', 'L1', 'L2', 'L3', 'F1', 'CSAT', 'NPS', 'KPI', 'SLA', 'API', 'JSON', 'CSV', 'PDF', 'PCI', 'PII', 'stub', 'live', 'jailbreak', 'panel', 'problem', 'status', 'NIP', 'PESEL', 'REGON', 'VIP', 'link', 'c-tf-idf', 'realtime'])
    const bad: string[] = []
    for (const [g, table] of Object.entries(pl.k)) {
      if (g === 'server') continue
      for (const [k, v] of Object.entries(table)) {
        if (/[a-z]_[a-z]/.test(v)) bad.push(`${g}.${k} = ${v} (snake_case)`)
        if (v === k && /[a-z]{3,}/i.test(v) && !loan.has(v)) bad.push(`${g}.${k} = ${v} (raw)`)
      }
    }
    expect(show(bad)).toEqual([])
  })

  it('translates enum values by lookup and keeps English output unchanged', () => {
    expect(translateKeyed('en', 'trigger', 'legal_threat')).toBe('legal threat')
    expect(translateKeyed('pl', 'trigger', 'legal_threat')).toBe('groźba prawna')
    expect(translateKeyed('en', 'band', 'needs_improvement')).toBe('needs improvement')
    expect(translateKeyed('pl', 'convStatus', 'waiting_human')).toBe('oczekuje na konsultanta')
    // unknown values fall back to the raw value (never an empty cell)
    expect(translateKeyed('en', 'trigger', 'brand_new_code')).toBe('brand_new_code')
    expect(translateKeyed('en', 'unknownGroup', null, '—')).toBe('—')
  })

  it('shows a server-supplied label for a stable key unless the UI dictionary overrides it', () => {
    expect(translateLabel('en', 'queue', 'returns', 'Returns & refunds')).toBe('Returns & refunds')
    expect(translateLabel('pl', 'queue', 'returns', 'Returns & refunds')).toBe(pl.k.queue.returns)
    expect(translateLabel('pl', 'queue', 'brand_new_queue', 'Nowa kolejka')).toBe('Nowa kolejka')
    // already-localised server prose is shown as received; known English prose is translated quietly
    expect(translateServer('pl', 'Zwroty towaru i środków')).toBe('Zwroty towaru i środków')
    expect(translateServer('en', 'Returns & refunds')).toBe('Returns & refunds')
  })
})

// ================================================================================================ plurals
describe('plural rules (CLDR via Intl.PluralRules)', () => {
  it('Polish distinguishes one / few / many / other', () => {
    const cat = (n: number) => pluralCategory('pl', n)
    expect([1].map(cat)).toEqual(['one'])
    expect([2, 3, 4, 22, 23, 24, 102, 1002].map(cat)).toEqual(Array(8).fill('few'))
    expect([0, 5, 6, 11, 12, 13, 14, 15, 21, 25, 100, 111, 112, 1000].map(cat)).toEqual(Array(14).fill('many'))
    expect([1.5, 0.5, 2.5].map(cat)).toEqual(['other', 'other', 'other'])
  })

  it('English keeps one / other', () => {
    expect([pluralCategory('en', 1), pluralCategory('en', 2), pluralCategory('en', 0)]).toEqual(['one', 'other', 'other'])
  })

  it('tn() picks the right Polish form and localises the count', () => {
    const forms = { one: '{n} digit', other: '{n} digits' } // dictionary: pl.n['{n} digits']
    const p = (n: number) => translateN('pl', n, forms)
    expect(p(1)).toBe('1 cyfra')
    expect(p(2)).toBe('2 cyfry')
    expect(p(5)).toBe('5 cyfr')
    expect(p(12)).toBe('12 cyfr')
    expect(p(22)).toBe('22 cyfry')
    expect(p(0)).toBe('0 cyfr')
    expect(p(1.5)).toBe('1,5 cyfry')
    expect(p(1234)).toBe(`1${NBSP}234 cyfry`)
    expect(translateN('en', 1, forms)).toBe('1 digit')
    expect(translateN('en', 0, forms)).toBe('0 digits')
    expect(translateN('en', 1234, forms)).toBe('1,234 digits')
  })

  it('every Polish plural entry reads naturally for 1, 2, 5, 12, 22 and 1,5 (all four forms differ where Polish requires it)', () => {
    for (const [key, f] of Object.entries(pl.n)) {
      for (const n of [1, 2, 5, 12, 22]) {
        const out = translateN('pl', n, { one: key, other: key })
        expect(out, key).toContain(String(n))
        expect(out).not.toContain('{n}')
      }
      expect(f.few === f.many && f.few === f.one && f.one === f.many, `plural forms of ${key} should not all be identical`).toBe(false)
    }
  })
})

// ================================================================================================ number / currency / date formats
describe('pl-PL formatting (and English unchanged)', () => {
  const pln = makeFmt('pl')
  const eng = makeFmt('en')
  const ts = Date.UTC(2026, 10, 18, 12, 5, 9) / 1000 // 18 Nov 2026 12:05:09 UTC = 13:05:09 in Warsaw (CET, UTC+1)

  it('numbers: decimal comma, NBSP thousands (also for four digits, so columns align)', () => {
    expect(pln.number(1234.5, 1)).toBe(`1${NBSP}234,5`)
    expect(pln.number(1234567.89, 2)).toBe(`1${NBSP}234${NBSP}567,89`)
    expect(pln.fixed(0.15, 2)).toBe('0,15')
    expect(pln.plain(0.912)).toBe('0,912')
    expect(pln.number(null)).toBe('—')
    expect(eng.number(1234.5, 1)).toBe('1,234.5')
    expect(eng.fixed(0.15, 2)).toBe('0.15')
  })

  it('currency: 379,00 zł, 1 234,56 zł; USD / EUR with the code or symbol the locale uses; English keeps $ and €', () => {
    expect(pln.pln(379)).toBe(`379,00${NBSP}zł`)
    expect(pln.pln(1234.56)).toBe(`1${NBSP}234,56${NBSP}zł`)
    expect(pln.eur(379)).toBe(`379,00${NBSP}€`)
    expect(pln.usd(27.1)).toBe(`27,10${NBSP}USD`)
    expect(pln.usd(1234.5, 0)).toBe(`1${NBSP}235${NBSP}USD`)
    expect(eng.usd(27.1)).toBe('$27.10')
    expect(eng.eur(379)).toBe('€379.00')
    expect(eng.usd(null)).toBe('—')
  })

  it('percent: 61,4% (no space before the sign), English 61.4%', () => {
    expect(pln.percent(0.614)).toBe('61,4%')
    expect(pln.percent(0.5, 0)).toBe('50%')
    expect(pln.percentValue(61.4)).toBe('61,4%')
    expect(eng.percent(0.614)).toBe('61.4%')
  })

  it('dates and times: 18.11.2026, 24-hour clock, Europe/Warsaw', () => {
    expect(pln.date(ts)).toBe('18.11.2026')
    expect(pln.time(ts)).toBe('13:05:09')
    expect(pln.dt(ts)).toMatch(/^18 lis 2026,? 13:05$/)
    expect(pln.dateLong(ts)).toBe('18 listopada 2026')
    expect(pln.dateLong('2026-11-18')).toBe('18 listopada 2026')
    expect(pln.isoDate('2026-11-18')).toBe('18.11.2026')
    expect(pln.isoShort('2026-11-18')).toBe('18.11')
    expect(pln.weekday('2026-11-18')).toBe('śr.')
    expect(pln.week('2026-W34')).toBe('tydz. 34')
    expect(eng.isoDate('2026-11-18')).toBe('2026-11-18')
    expect(eng.isoShort('2026-11-18')).toBe('11-18')
    expect(eng.week('2026-W34')).toBe('2026-W34')
  })

  it('summer time follows Warsaw (CEST, UTC+2)', () => {
    expect(pln.time(Date.UTC(2026, 6, 1, 10, 0, 0) / 1000)).toBe('12:00:00')
  })

  it('durations, latencies and relative times', () => {
    expect(pln.dur(200)).toBe('3 min 20 s')
    expect(pln.dur(42)).toBe('42 s')
    expect(eng.dur(200)).toBe('3m 20s')
    expect(pln.ms(340)).toBe('340 ms')
    expect(pln.ms(1234)).toBe('1,2 s')
    expect(eng.ms(1234)).toBe('1.2 s')
    expect(pln.secs(120)).toBe('120 s')
    expect(eng.secs(120)).toBe('120s')
    const now = Date.UTC(2026, 10, 18, 12, 0, 0)
    expect(pln.relative(now / 1000 - 2 * 3600, now)).toBe('2 godz. temu')
    expect(pln.relative(now / 1000 - 5 * 60, now)).toBe('5 min temu')
    expect(pln.relative(now / 1000 + 3 * 86400, now)).toBe('za 3 dni')
  })

  it('lists and language names follow the UI language', () => {
    expect(pln.list(['a', 'b', 'c'])).toBe('a, b i c')
    expect(eng.list(['a', 'b', 'c'])).toBe('a, b, and c')
    expect(pln.languageName('de')).toBe('niemiecki')
    expect(pln.languageName('pl')).toBe('polski')
    expect(eng.languageName('de', 'German')).toBe('German')
    expect(pln.usdMillions(27_100_000)).toBe('27,1 mln USD')
    expect(eng.usdMillions(27_100_000)).toBe('$27.1M')
  })
})

// ================================================================================================ search and sorting
describe('Polish search folding and alphabet', () => {
  it('folds ł/Ł (NFKD leaves them untouched) and other non-decomposable letters', () => {
    expect('ł'.normalize('NFKD')).toBe('ł') // the trap
    expect(fold('Łódź')).toBe('lodz')
    expect(fold('ŁÓDŹ ŻÓŁW Gęślą jaźń')).toBe('lodz zolw gesla jazn')
    expect(fold('Straße Ørsted Đurđevac')).toBe('strasse orsted durdevac')
  })

  it('searches without diacritics, in either direction, with ł/Ł', () => {
    expect(includesFolded('Wrocław, ul. Gądowska 7', 'wroclaw')).toBe(true)
    expect(includesFolded('Wrocław, ul. Gądowska 7', 'GADOWSKA 7')).toBe(true)
    expect(includesFolded('wroclaw', 'Wrocław')).toBe(true)
    expect(includesFolded('Łódź', 'LODZ')).toBe(true)
    expect(includesFolded('Anna Kowalska', 'kowalski')).toBe(false)
    expect(includesFolded(null, '')).toBe(true)
    expect(includesFolded(undefined, 'x')).toBe(false)
  })

  it('sorts with the Polish alphabet (ą after a, ć after c, ł after l, ń after n, ó after o, ś after s, ź and ż after z)', () => {
    const words = ['Żabka', 'Zebra', 'Źrebię', 'Łódź', 'Lublin', 'Ćma', 'Czapka', 'Cegła', 'Ąbc', 'Abc', 'Boga', 'Ósemka', 'Opole', 'Pasza', 'Śnieg', 'Sosna', 'Tama', 'Ń', 'Nad', 'Ęś', 'Eko', 'Mały', 'Łyk']
    const sorted = [...words].sort(makeCollator('pl').compare)
    expect(sorted).toEqual(['Abc', 'Ąbc', 'Boga', 'Cegła', 'Czapka', 'Ćma', 'Eko', 'Ęś', 'Lublin', 'Łódź', 'Łyk', 'Mały', 'Nad', 'Ń', 'Opole', 'Ósemka', 'Pasza', 'Sosna', 'Śnieg', 'Tama', 'Zebra', 'Źrebię', 'Żabka'])
    expect(['b', 'a', 'ą'].sort(makeCollator('pl').compare)).toEqual(['a', 'ą', 'b'])
  })

  it('shortens long labels at a word boundary with an ellipsis, never in the middle of a Polish word', () => {
    expect(ellipsize('Problem z terminem montażu', 24)).toBe('Problem z terminem…')
    expect(ellipsize('Uszkodzenie przy dostawie', 24)).toBe('Uszkodzenie przy…')
    expect(ellipsize('Reklamacja', 24)).toBe('Reklamacja') // fits: unchanged
    expect(ellipsize('Nieprzyzwoicie_długi_identyfikator_bez_spacji', 12)).toBe('Nieprzyzwoic…') // no space to cut at: hard cut
  })
})

// ================================================================================================ language selection & missing keys
describe('language selection', () => {
  it('parses language tags', () => {
    expect(parseLang('pl-PL')).toBe('pl')
    expect(parseLang('PL_pl')).toBe('pl')
    expect(parseLang('en-GB')).toBe('en')
    expect(parseLang('de')).toBeNull()
    expect(parseLang(null)).toBeNull()
  })

  it('?lang= wins over the saved choice, which wins over navigator.languages, which wins over en', () => {
    expect(resolveInitialLang({ search: '?lang=pl', stored: 'en', languages: ['en-US'] })).toBe('pl')
    expect(resolveInitialLang({ search: '', stored: 'pl', languages: ['en-US'] })).toBe('pl')
    expect(resolveInitialLang({ search: '?lang=xx', stored: 'pl' })).toBe('pl')
    expect(resolveInitialLang({ search: '', stored: null, languages: ['de-DE', 'pl-PL', 'en'] })).toBe('pl')
    expect(resolveInitialLang({ search: '', stored: null, languages: ['de-DE'] })).toBe('en')
    expect(resolveInitialLang({})).toBe('en')
  })
})

describe('missing keys', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('falls back to English, warns once and records the key in window.__i18nMissing', () => {
    const win: { __i18nMissing?: string[] } = {}
    vi.stubGlobal('window', win)
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const key = N_('A sentence that is certainly not in any dictionary {n}')
    expect(translate('pl', key, { n: 3 })).toBe('A sentence that is certainly not in any dictionary 3')
    translate('pl', key, { n: 4 })
    expect(win.__i18nMissing).toEqual([`t:${key}`])
    expect(warn).toHaveBeenCalledTimes(1)
    translate('en', key, { n: 1 })
    expect(win.__i18nMissing).toHaveLength(1) // English never reports
    warn.mockRestore()
  })

  it('translates and interpolates', () => {
    expect(translate('pl', 'Retry')).toBe('Ponów')
    expect(translate('en', 'Hello {name}', { name: 'Anna' })).toBe('Hello Anna')
  })
})
