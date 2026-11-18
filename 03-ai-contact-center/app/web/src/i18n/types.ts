export type Lang = 'en' | 'pl'

/** Variables for `{name}` interpolation. */
export type Vars = Record<string, string | number | null | undefined>

/** CLDR plural forms. English uses one/other, Polish one/few/many/other. */
export interface PluralForms {
  one: string
  few: string
  many: string
  other: string
}

/** What a call site passes to `tn()` (the English forms; `other` doubles as the dictionary key). */
export interface PluralSource {
  one: string
  other: string
}

export interface Dict {
  /** literal translations: English source text -> translation */
  t: Record<string, string>
  /** plural translations: English `other` form -> CLDR forms */
  n: Record<string, PluralForms>
  /** keyed tables (enums, feature catalogue, calculator labels): group -> key -> text */
  k: Record<string, Record<string, string>>
}

declare global {
  interface Window {
    /** Keys that had no translation when they were rendered (the E2E suite asserts this stays empty). */
    __i18nMissing?: string[]
  }
}
