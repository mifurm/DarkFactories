import type { Dict, PluralForms } from './types'
/**
 * Polish dictionary = every partial in ./pl/ merged (auto-discovered, like the feature folders). Each partial is `{ t, n, k }`:
 *   t – English source text -> Polish; n – plural forms keyed by the English `other` form; k – keyed tables (enums, catalogue, calculator labels).
 */
const modules = import.meta.glob<{ default: Partial<Dict> }>('./pl/*.ts', { eager: true })
const PARTS: Partial<Dict>[] = Object.keys(modules).sort().map((k) => modules[k].default)

/** Keys defined by more than one partial (the test fails on these). */
export const plDuplicates: string[] = []

function merge(parts: Partial<Dict>[]): Dict {
  const out: Dict = { t: {}, n: {}, k: {} }
  for (const p of parts) {
    for (const [k, v] of Object.entries(p.t ?? {})) {
      if (k in out.t) plDuplicates.push(`t:${k}`)
      out.t[k] = v
    }
    for (const [k, v] of Object.entries(p.n ?? {})) {
      if (k in out.n) plDuplicates.push(`n:${k}`)
      out.n[k] = v as PluralForms
    }
    for (const [group, table] of Object.entries(p.k ?? {})) {
      const into = (out.k[group] ??= {})
      for (const [k, v] of Object.entries(table)) {
        if (k in into) plDuplicates.push(`k:${group}.${k}`)
        into[k] = v
      }
    }
  }
  return out
}

export const pl: Dict = merge(PARTS)

/** English strings that are intentionally identical in Polish (product names, loan words, units). */
export const plIdentical: string[] = ['LLMOps', 'Start']
