import { Fragment, createContext, createElement, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import { includesFolded, makeCollator, makeFmt, type Fmt } from './format'
import { getLang, interpolate, parseRich, setLang as setLangCore, subscribeLang, translate, translateKeyed, translateLabel, translateN, translateRich, translateServer } from './core'
import type { Lang, PluralSource, Vars } from './types'

export { LANGS, LANG_NAMES, getLang, initLang, parseLang, resolveInitialLang } from './core'
export { N_ } from './mark'
export { ellipsize, fold, includesFolded, makeFmt, pluralCategory, makeCollator, type Fmt, type Currency } from './format'
export type { Lang, Vars, PluralSource } from './types'

export interface I18n {
  lang: Lang
  setLang: (l: Lang) => void
  /** `t('English source text {name}', { name })` */
  t: (key: string, vars?: Vars) => string
  /** Same as `t` for strings that were marked with `N_()` elsewhere (not statically extracted at the call site). */
  tr: (key: string, vars?: Vars) => string
  /** `tn(count, { one: '{n} file', other: '{n} files' })` with CLDR plural rules (Polish: one / few / many / other). */
  tn: (count: number, forms: PluralSource, vars?: Vars) => string
  /** Enum / catalogue label by value: `te('band', 'needs_improvement')`. */
  te: (group: string, key: string | null | undefined, fallback?: string) => string
  /** Text with inline <b>, <i>, <code>: `rich('Routed to <b>{queue}</b>', { queue })`. */
  rich: (key: string, vars?: Vars) => ReactNode
  /** Server prose: shown as received; known deterministic English texts are translated (quietly) in Polish. */
  ts: (text: string | null | undefined) => string
  /** Server label for a stable key (queue, rubric dimension …): the UI dictionary overrides it when it has an entry, else the server's label is shown. */
  tl: (group: string, key: string | null | undefined, label: string | null | undefined) => string
  fmt: Fmt
  collator: Intl.Collator
  /** `Array.sort` comparator following the UI language's alphabet (Polish: ą after a, ł after l, ś after s …). */
  compare: (a: string, b: string) => number
  /** Diacritic-insensitive (incl. ł/Ł) case-insensitive contains. */
  includes: (haystack: string | null | undefined, needle: string) => boolean
}

function richNodes(lang: Lang, key: string, vars?: Vars): ReactNode {
  const text = translateRich(lang, key, undefined)
  const parts = parseRich(text)
  if (parts.length === 1 && typeof parts[0] === 'string') return interpolate(parts[0], vars)
  return createElement(
    Fragment,
    null,
    ...parts.map((p, i) => (typeof p === 'string' ? createElement(Fragment, { key: i }, interpolate(p, vars)) : createElement(p.tag, { key: i }, interpolate(p.text, vars)))),
  )
}

function build(lang: Lang): I18n {
  const collator = makeCollator(lang)
  const t = (key: string, vars?: Vars) => translate(lang, key, vars)
  return {
    lang,
    setLang: setLangCore,
    t,
    tr: t,
    tn: (count, forms, vars) => translateN(lang, count, forms, vars),
    te: (group, key, fallback) => translateKeyed(lang, group, key, fallback),
    rich: (key, vars) => richNodes(lang, key, vars),
    ts: (text) => translateServer(lang, text),
    tl: (group, key, label) => translateLabel(lang, group, key, label),
    fmt: makeFmt(lang),
    collator,
    compare: (a, b) => collator.compare(a, b),
    includes: includesFolded,
  }
}

const cache = new Map<Lang, I18n>()
function forLang(lang: Lang): I18n {
  let v = cache.get(lang)
  if (!v) {
    v = build(lang)
    cache.set(lang, v)
  }
  return v
}

const Ctx = createContext<I18n | null>(null)

/** Provides the active language to the tree; switching re-renders consumers without a reload or a remount. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const lang = useSyncExternalStore(subscribeLang, getLang, () => 'en' as Lang)
  const value = useMemo(() => forLang(lang), [lang])
  return createElement(Ctx.Provider, { value }, children)
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx)
  // outside a provider (tests, early boot) fall back to the module state
  return ctx ?? forLang(getLang())
}

/** Non-hook accessor for code outside React (the API client, error formatting). */
export const i18nFor = forLang
