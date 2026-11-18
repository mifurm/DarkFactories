import { en } from './en'
import { N_ } from './mark'
import { pl } from './pl'
import { makeFmt, pluralCategory } from './format'
import type { Dict, Lang, PluralSource, Vars } from './types'

export const LANGS: readonly Lang[] = ['en', 'pl']
export const LANG_KEY = 'concierge.lang'
/** Autonyms: a language is always named in itself. */
export const LANG_NAMES: Record<Lang, string> = { en: 'English', pl: 'Polski' }

const DICTS: Record<Exclude<Lang, 'en'>, Dict> = { pl }

export const DOC_TITLE = N_('Concierge · AI Contact Center')
export const DOC_DESCRIPTION = N_('Concierge - AI-first contact center on Azure (synthetic-data reference implementation)')

/** "pl", "pl-PL", "PL_pl" -> "pl"; anything unsupported -> null. */
export function parseLang(v: string | null | undefined): Lang | null {
  if (!v) return null
  const base = v.trim().toLowerCase().split(/[-_]/)[0]
  return (LANGS as readonly string[]).includes(base) ? (base as Lang) : null
}

/** Initial UI language: ?lang= -> saved choice -> navigator.languages (first supported) -> en. */
export function resolveInitialLang(input: { search?: string; stored?: string | null; languages?: readonly string[] }): Lang {
  const q = parseLang(new URLSearchParams(input.search ?? '').get('lang'))
  if (q) return q
  const s = parseLang(input.stored)
  if (s) return s
  for (const l of input.languages ?? []) {
    const p = parseLang(l)
    if (p) return p
  }
  return 'en'
}

// ------------------------------------------------------------------------------------------------ current language (module state)
let current: Lang = 'en'
let initialised = false
const listeners = new Set<() => void>()

function readStored(): string | null {
  try {
    return localStorage.getItem(LANG_KEY)
  } catch {
    return null
  }
}
function writeStored(l: Lang): void {
  try {
    localStorage.setItem(LANG_KEY, l)
  } catch {
    /* private mode: the choice just is not remembered */
  }
}

function applyDocument(l: Lang): void {
  if (typeof document === 'undefined') return
  document.documentElement.lang = l
  document.title = translate(l, DOC_TITLE)
  document.querySelector('meta[name="description"]')?.setAttribute('content', translate(l, DOC_DESCRIPTION))
}

/** Reads ?lang= / localStorage / navigator once; called lazily by getLang() and explicitly at start-up. */
export function initLang(): Lang {
  if (initialised || typeof window === 'undefined') return current
  initialised = true
  const params = new URLSearchParams(window.location.search)
  current = resolveInitialLang({ search: window.location.search, stored: readStored(), languages: navigator.languages?.length ? navigator.languages : [navigator.language] })
  if (parseLang(params.get('lang'))) writeStored(current)
  applyDocument(current)
  return current
}

export function getLang(): Lang {
  if (!initialised) initLang()
  return current
}

export function setLang(l: Lang): void {
  if (!initialised) initLang()
  if (l === current) return
  current = l
  writeStored(l)
  applyDocument(l)
  listeners.forEach((f) => f())
  window.dispatchEvent(new CustomEvent('concierge:lang', { detail: l }))
}

export function subscribeLang(f: () => void): () => void {
  listeners.add(f)
  return () => listeners.delete(f)
}

// ------------------------------------------------------------------------------------------------ missing keys
const warned = new Set<string>()
function missing(lang: Lang, kind: 't' | 'n' | 'k' | 'rich', key: string): void {
  if (lang === 'en' || typeof window === 'undefined') return
  const id = `${kind}:${key}`
  if (warned.has(id)) return
  warned.add(id)
  ;(window.__i18nMissing ??= []).push(id)
  console.warn(`[i18n] no ${lang} translation (${id})`)
}

// ------------------------------------------------------------------------------------------------ translation primitives
export function interpolate(s: string, vars?: Vars): string {
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (vars[k] != null ? String(vars[k]) : m))
}

/** Looks up an English source string; English is the key itself. */
export function translate(lang: Lang, key: string, vars?: Vars): string {
  if (lang === 'en') return interpolate(key, vars)
  const v = DICTS[lang].t[key]
  if (v === undefined) {
    missing(lang, 't', key)
    return interpolate(key, vars)
  }
  return interpolate(v, vars)
}

/** Count-dependent text with CLDR plural rules. `{n}` is the localised count; other vars are interpolated too. */
export function translateN(lang: Lang, count: number, forms: PluralSource, vars?: Vars): string {
  const cat = pluralCategory(lang, count)
  let tpl: string
  if (lang === 'en') {
    tpl = cat === 'one' ? forms.one : forms.other
  } else {
    const entry = DICTS[lang].n[forms.other]
    if (!entry) {
      missing(lang, 'n', forms.other)
      tpl = pluralCategory('en', count) === 'one' ? forms.one : forms.other
    } else {
      tpl = entry[cat as keyof typeof entry] ?? entry.other
    }
  }
  return interpolate(tpl, { n: makeFmt(lang).number(count, Number.isInteger(count) ? 0 : 2), ...vars })
}

/** Enum / catalogue value -> label. English falls back to the raw value, so existing English output is preserved. */
export function translateKeyed(lang: Lang, group: string, key: string | null | undefined, fallback?: string): string {
  if (key == null || key === '') return fallback ?? ''
  const source = en.k[group]?.[key]
  if (lang === 'en') return source ?? fallback ?? key
  const v = DICTS[lang].k[group]?.[key]
  if (v === undefined) {
    missing(lang, 'k', `${group}.${key}`)
    return source ?? fallback ?? key
  }
  return v
}

/**
 * Server-provided prose is shown as the server sent it (the API localises it from the request language). This is a quiet safety net for
 * deterministic English texts we know about (group `server`, keyed by the English text): no "missing" report when the server already answered in Polish.
 */
export function translateServer(lang: Lang, text: string | null | undefined): string {
  if (!text) return text ?? ''
  if (lang === 'en') return text
  return DICTS[lang].k.server?.[text] ?? text
}

/** A server-supplied label for a stable key: the UI dictionary may override it, otherwise the server's own (localised) label is shown. */
export function translateLabel(lang: Lang, group: string, key: string | null | undefined, label: string | null | undefined): string {
  if (lang === 'en' || key == null) return label ?? key ?? ''
  return DICTS[lang].k[group]?.[key] ?? label ?? key
}

export type RichPart = string | { tag: 'b' | 'i' | 'code'; text: string }

/** Splits "text <b>bold</b> more" into parts (only <b>, <i>, <code>; no nesting). */
export function parseRich(s: string): RichPart[] {
  const out: RichPart[] = []
  const re = /<(b|i|code)>(.*?)<\/\1>/gs
  let last = 0
  for (let m = re.exec(s); m; m = re.exec(s)) {
    if (m.index > last) out.push(s.slice(last, m.index))
    out.push({ tag: m[1] as 'b' | 'i' | 'code', text: m[2] })
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

/** For `rich()` keys: report a miss under the 'rich' kind, otherwise behave like translate(). */
export function translateRich(lang: Lang, key: string, vars?: Vars): string {
  if (lang === 'en') return interpolate(key, vars)
  const v = DICTS[lang].t[key]
  if (v === undefined) {
    missing(lang, 'rich', key)
    return interpolate(key, vars)
  }
  return interpolate(v, vars)
}
