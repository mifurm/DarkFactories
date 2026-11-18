import type { Lang } from './types'

/** UI language -> BCP-47 locale used for every Intl formatter. */
export const LOCALES: Record<Lang, string> = { en: 'en-US', pl: 'pl-PL' }
/** Absolute times are shown in Polish business time when the UI is Polish (English keeps the browser's own zone, as before). */
export const POLAND_TZ = 'Europe/Warsaw'

export type Currency = 'USD' | 'EUR' | 'PLN'

const pluralRules = new Map<Lang, Intl.PluralRules>()
/** CLDR plural category for an integer or fractional count: Polish gives one / few / many / other. */
export function pluralCategory(lang: Lang, n: number): Intl.LDMLPluralRule {
  let r = pluralRules.get(lang)
  if (!r) {
    r = new Intl.PluralRules(LOCALES[lang])
    pluralRules.set(lang, r)
  }
  return r.select(n)
}

const FOLD_MAP: Record<string, string> = {
  ł: 'l', Ł: 'L', ø: 'o', Ø: 'O', đ: 'd', Đ: 'D', ð: 'd', Ð: 'D', þ: 'th', Þ: 'TH', ħ: 'h', Ħ: 'H', ı: 'i', ĸ: 'k', ŀ: 'l', Ŀ: 'L', ß: 'ss', ẞ: 'SS', æ: 'ae', Æ: 'AE', œ: 'oe', Œ: 'OE', ŧ: 't', Ŧ: 'T',
}

/**
 * Case- and diacritic-insensitive form for searching. NFKD alone is NOT enough: it leaves ł/Ł (and ø, đ, ß, …) untouched,
 * so "Łódź" would never match "lodz".
 */
export function fold(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .replace(/[łŁøØđĐðÐþÞħĦıĸŀĿßẞæÆœŒŧŦ]/gu, (c) => FOLD_MAP[c] ?? c)
    .toLowerCase()
}

/** Diacritic-insensitive "contains"; an empty needle matches everything. */
export function includesFolded(haystack: string | null | undefined, needle: string): boolean {
  const n = fold(needle.trim())
  return n === '' || fold(haystack ?? '').includes(n)
}

export function makeCollator(lang: Lang): Intl.Collator {
  return new Intl.Collator(LOCALES[lang], { numeric: true })
}

/** Shortens at a word boundary with an ellipsis (a hard cut of a long Polish word leaves "monta"); text that fits is returned unchanged. */
export function ellipsize(s: string, max: number): string {
  if (s.length <= max) return s
  const head = s.slice(0, max)
  const at = head.lastIndexOf(' ')
  return `${(at > max / 2 ? head.slice(0, at) : head).trimEnd()}…`
}

const memo = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat | Intl.ListFormat | Intl.DisplayNames>()
function cached<T extends Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat | Intl.ListFormat | Intl.DisplayNames>(key: string, make: () => T): T {
  let v = memo.get(key) as T | undefined
  if (!v) {
    v = make()
    memo.set(key, v)
  }
  return v
}
const numFmt = (locale: string, o: Intl.NumberFormatOptions) => cached(`n|${locale}|${JSON.stringify(o)}`, () => new Intl.NumberFormat(locale, o))
const dateFmt = (locale: string, o: Intl.DateTimeFormatOptions) => cached(`d|${locale}|${JSON.stringify(o)}`, () => new Intl.DateTimeFormat(locale, o))

type Num = number | null | undefined
const DASH = '—'

export interface Fmt {
  lang: Lang
  locale: string
  /** grouped number with at most `digits` fraction digits (1 234 567,9 / 1,234,567.9) */
  number: (n: Num, digits?: number) => string
  /** exactly `digits` fraction digits, no grouping (replaces toFixed: 0,15 / 0.15) */
  fixed: (n: Num, digits: number) => string
  /** an already rounded value shown as is (0,912 / 0.912) */
  plain: (n: Num) => string
  /** ratio 0..1 -> percent (61,4% / 61.4%) */
  percent: (ratio: Num, digits?: number) => string
  /** a value already in percent units (61.4 -> 61,4% / 61.4%) */
  percentValue: (pct: Num, digits?: number) => string
  currency: (n: Num, currency: Currency, digits?: number) => string
  /** amount in the currency a record carries (order, refund, approval): EUR / PLN / USD, anything else is shown as EUR */
  money: (n: Num, cur?: string | null, digits?: number) => string
  usd: (n: Num, digits?: number) => string
  eur: (n: Num, digits?: number) => string
  pln: (n: Num, digits?: number) => string
  /** $27.1M / 27,1 mln USD */
  usdMillions: (v: Num) => string
  /** milliseconds -> 340 ms / 1,2 s */
  ms: (n: Num) => string
  /** whole seconds -> 120s / 120 s */
  secs: (n: Num) => string
  /** seconds -> 3m 20s / 3 min 20 s */
  dur: (s: Num) => string
  /** epoch seconds -> clock time (24 h in Polish, Europe/Warsaw) */
  time: (ts: Num) => string
  /** epoch seconds -> date + time */
  dt: (ts: Num) => string
  /** epoch seconds -> date only (18.11.2026) */
  date: (ts: Num) => string
  /** epoch seconds or ISO date -> long date (18 listopada 2026 / November 18, 2026) */
  dateLong: (v: number | string | null | undefined) => string
  /** 'YYYY-MM-DD' -> 18.11.2026 (English keeps ISO, as the API sends it) */
  isoDate: (iso: string | null | undefined) => string
  /** 'YYYY-MM-DD' -> 18.11 (English keeps MM-DD) */
  isoShort: (iso: string) => string
  /** weekday of an ISO date; English keeps the API's own label */
  weekday: (iso: string, fallback?: string) => string
  /** epoch seconds -> "2 godz. temu" / "2 hr. ago" */
  relative: (ts: Num, nowMs?: number) => string
  /** 'YYYY-Www' -> "tydz. 34" (English keeps the API's label) */
  week: (label: string | number) => string
  list: (items: string[]) => string
  /** language name for an ISO code in the UI language (English keeps the API's name) */
  languageName: (code: string, fallback?: string) => string
}

const REL_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 86400],
  ['month', 30 * 86400],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

const isNum = (n: Num): n is number => typeof n === 'number' && Number.isFinite(n)

const instances = new Map<Lang, Fmt>()

export function makeFmt(lang: Lang): Fmt {
  const hit = instances.get(lang)
  if (hit) return hit
  const pl = lang === 'pl'
  const locale = LOCALES[lang]
  const tz = pl ? { timeZone: POLAND_TZ } : {}
  const secs = (ts: number) => new Date(ts * 1000)

  const number = (n: Num, digits = 0) => (isNum(n) ? numFmt(locale, { maximumFractionDigits: digits, useGrouping: pl ? 'always' : true }).format(n) : DASH)
  const fixed = (n: Num, digits: number) => (isNum(n) ? (pl ? numFmt(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false }).format(n) : n.toFixed(digits)) : DASH)
  const plain = (n: Num) => (isNum(n) ? (pl ? numFmt(locale, { maximumFractionDigits: 12, useGrouping: false }).format(n) : String(n)) : DASH)
  const percent = (ratio: Num, digits = 1) => (isNum(ratio) ? (pl ? numFmt(locale, { style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(ratio) : `${(ratio * 100).toFixed(digits)}%`) : DASH)
  const percentValue = (pct: Num, digits?: number) => {
    if (!isNum(pct)) return DASH
    if (!pl) return digits === undefined ? `${pct}%` : `${pct.toFixed(digits)}%`
    return `${digits === undefined ? plain(pct) : fixed(pct, digits)}%`
  }
  const currency = (n: Num, cur: Currency, digits = 2) => {
    if (!isNum(n)) return DASH
    if (!pl) {
      const sym = cur === 'USD' ? '$' : cur === 'EUR' ? '€' : 'PLN '
      return `${sym}${n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
    }
    return numFmt(locale, { style: 'currency', currency: cur, minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: 'always' }).format(n)
  }
  const dt = (ts: Num) => (ts ? (pl ? dateFmt(locale, { dateStyle: 'medium', timeStyle: 'short', ...tz }).format(secs(ts)) : secs(ts).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })) : DASH)
  const isoDate = (iso: string | null | undefined) => {
    if (!iso) return DASH
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
    return pl && m ? `${m[3]}.${m[2]}.${m[1]}` : iso
  }

  const f: Fmt = {
    lang,
    locale,
    number,
    fixed,
    plain,
    percent,
    percentValue,
    currency,
    money: (n, cur, d = 2) => currency(n, (['USD', 'EUR', 'PLN'] as const).find((c) => c === String(cur ?? 'EUR').toUpperCase()) ?? 'EUR', d),
    usd: (n, d = 2) => currency(n, 'USD', d),
    eur: (n, d = 2) => currency(n, 'EUR', d),
    pln: (n, d = 2) => currency(n, 'PLN', d),
    usdMillions: (v) => (isNum(v) ? (pl ? `${numFmt(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v / 1e6)} mln USD` : `$${(v / 1e6).toFixed(1)}M`) : DASH),
    ms: (n) => (isNum(n) ? (n >= 1000 ? `${pl ? fixed(n / 1000, 1) : (n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`) : DASH),
    secs: (n) => (isNum(n) ? (pl ? `${number(n, 0)} s` : `${n}s`) : DASH),
    dur: (s) => {
      if (!isNum(s)) return DASH
      const m = Math.floor(s / 60)
      if (pl) return m > 0 ? `${m} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`
      return m > 0 ? `${m}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`
    },
    time: (ts) => (ts ? (pl ? dateFmt(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', ...tz }).format(secs(ts)) : secs(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })) : DASH),
    dt,
    date: (ts) => (ts ? (pl ? dateFmt(locale, { day: '2-digit', month: '2-digit', year: 'numeric', ...tz }).format(secs(ts)) : secs(ts).toLocaleDateString([], { dateStyle: 'medium' })) : DASH),
    dateLong: (v) => {
      if (v == null || v === '') return DASH
      const d = typeof v === 'number' ? secs(v) : new Date(/^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T12:00:00Z` : v)
      if (Number.isNaN(d.getTime())) return String(v)
      return dateFmt(locale, { dateStyle: 'long', ...(typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? { timeZone: 'UTC' } : tz) }).format(d)
    },
    isoDate,
    isoShort: (iso) => {
      const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso)
      return m ? (pl ? `${m[2]}.${m[1]}` : `${m[1]}-${m[2]}`) : iso
    },
    weekday: (iso, fallback) => {
      if (!pl && fallback) return fallback
      const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`)
      return Number.isNaN(d.getTime()) ? (fallback ?? iso) : dateFmt(locale, { weekday: 'short', timeZone: 'UTC' }).format(d)
    },
    relative: (ts, nowMs = Date.now()) => {
      if (!ts) return DASH
      const diff = ts - nowMs / 1000
      const [unit, size] = REL_UNITS.find(([, sz]) => Math.abs(diff) >= sz) ?? REL_UNITS[REL_UNITS.length - 1]
      return cached(`r|${locale}`, () => new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' })).format(Math.round(diff / size), unit)
    },
    week: (label) => {
      const m = /^(\d{4})-W(\d{1,2})$/.exec(String(label))
      return pl && m ? `tydz. ${Number(m[2])}` : String(label)
    },
    list: (items) => cached(`l|${locale}`, () => new Intl.ListFormat(locale, { style: 'long', type: 'conjunction' })).format(items),
    languageName: (code, fallback) => {
      if (!pl) return fallback ?? code
      try {
        return cached(`dn|${locale}`, () => new Intl.DisplayNames([locale], { type: 'language' })).of(code) ?? fallback ?? code
      } catch {
        return fallback ?? code
      }
    },
  }
  instances.set(lang, f)
  return f
}
