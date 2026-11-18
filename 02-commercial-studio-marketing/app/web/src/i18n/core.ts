/**
 * i18n core — pure functions, no DOM, no React (unit-testable in node).
 *
 * Source language = English, used as the message KEY:  t("Save") → "Save" in English, the pl dictionary entry in Polish.
 *  - `{name}` interpolation (numbers are formatted for the active locale),
 *  - plurals through CLDR rules (Intl.PluralRules): English one/other, Polish one/few/many/other,
 *  - ID-keyed tables (enums, roles, feature names, ROI model keys) via `tEnum(group, id, fallback)`,
 *  - a missing translation falls back to English, warns once and is recorded in window.__i18nMissing (asserted by the E2E journeys).
 */
import { createFormatter, type Formatter } from "./format";
import { foldText } from "./search";

export type Lang = "en" | "pl";
export const SUPPORTED_LANGS: readonly Lang[] = ["en", "pl"];
export const DEFAULT_LANG: Lang = "en";
export const LANG_STORAGE_KEY = "studio.lang";

export interface LangMeta {
  /** endonym shown in the switcher */
  name: string;
  /** BCP-47 locale used by Intl.* */
  locale: string;
  /** user-facing absolute times are shown in this zone (undefined = the browser's zone) */
  timeZone?: string;
}
export const LANG_META: Record<Lang, LangMeta> = {
  en: { name: "English", locale: "en-US" },
  pl: { name: "Polski", locale: "pl-PL", timeZone: "Europe/Warsaw" },
};

export type Vars = Record<string, string | number | null | undefined>;
/** CLDR plural categories. English uses one/other, Polish one/few/many/other. */
export type PluralForms = { zero?: string; one?: string; two?: string; few?: string; many?: string; other: string };
export type EnumTable = Record<string, string>;

/** A non-English dictionary. English needs no `messages`/`plurals`: the English source text is the key. */
export interface Dictionary {
  /** English source text → translation */
  messages: Record<string, string>;
  /** English plural "other" form → translated plural forms (selected with the language's CLDR rules) */
  plurals: Record<string, PluralForms>;
  /** group → id → label (statuses, roles, feature names, ROI model keys, …) */
  enums: Record<string, EnumTable>;
}

export interface MissingEntry {
  lang: Lang;
  kind: "message" | "plural" | "enum";
  key: string;
}

export function normalizeLang(raw: string | null | undefined): Lang | null {
  if (!raw) return null;
  const primary = String(raw).trim().toLowerCase().replace("_", "-").split("-")[0];
  return (SUPPORTED_LANGS as readonly string[]).includes(primary) ? (primary as Lang) : null;
}

/** ?lang= → saved choice → navigator.languages → "en" */
export function resolveInitialLang(input: { search?: string; saved?: string | null; navigatorLanguages?: readonly string[] }): Lang {
  const fromUrl = normalizeLang(new URLSearchParams(input.search ?? "").get("lang"));
  if (fromUrl) return fromUrl;
  const saved = normalizeLang(input.saved);
  if (saved) return saved;
  for (const l of input.navigatorLanguages ?? []) {
    const n = normalizeLang(l);
    if (n) return n;
  }
  return DEFAULT_LANG;
}

const VAR_RE = /\{(\w+)\}/g;
export function interpolate(template: string, vars?: Vars, formatNumber?: (n: number) => string): string {
  if (!vars) return template;
  return template.replace(VAR_RE, (token, name: string) => {
    if (!(name in vars)) return token;
    const v = vars[name];
    if (v === null || v === undefined) return "";
    return typeof v === "number" ? (formatNumber ? formatNumber(v) : String(v)) : String(v);
  });
}

/** `{name}` placeholders of a message (used by the completeness test to compare source and translation). */
export function placeholders(template: string): string[] {
  return [...template.matchAll(VAR_RE)].map((m) => m[1]).sort();
}

/** Polish typography: keep one-letter words (a, i, o, u, w, z) with the following word so lines never end on them. */
export function nbspOneLetterWords(text: string): string {
  return text.replace(/(?<=^|[\s(„“"])([aiouwzAIOUWZ])[ \t]+(?=\S)/g, "$1\u00A0");
}

export const humanize = (v: string) => v.replace(/_/g, " ");

const pluralRules = new Map<string, Intl.PluralRules>();
export function pluralCategory(lang: Lang, n: number): Intl.LDMLPluralRule {
  const locale = LANG_META[lang].locale;
  let pr = pluralRules.get(locale);
  if (!pr) pluralRules.set(locale, (pr = new Intl.PluralRules(locale)));
  return pr.select(n);
}

export interface Translator {
  lang: Lang;
  locale: string;
  fmt: Formatter;
  t(key: string, vars?: Vars): string;
  /** plural message: the English forms are the source, the dictionary key is the English `other` form */
  tn(count: number, forms: { one: string; other: string }, vars?: Vars): string;
  /** ID-keyed lookup; `fallback` (usually the English text the API returned) is used when there is no entry */
  tEnum(group: string, id: string | null | undefined, fallback?: string): string;
  /** lenient lookup for open sets (country codes, channels, platforms): the label when known, otherwise the raw id — never reported as missing */
  tOpen(group: string, id: string | null | undefined): string;
  /** is there a label for this id in the active language (no missing-key report) */
  hasEnum(group: string, id: string): boolean;
  /** reverse lookup: the id whose label in the active language equals `text` (diacritic- and case-insensitive); undefined when there is none, and always in English */
  findEnum(group: string, text: string): string | undefined;
  /**
   * Server text shown as received — except when it is one of the dictionary's own English sources (a constant the API returns verbatim because it
   * did not localize it): then the translation is shown. Never reports a missing key; declare the sources with msg("…") so they are extracted/tested.
   */
  tKnown(text: string | null | undefined): string;
}

declare global {
  interface Window {
    __i18nMissing?: MissingEntry[];
  }
}

const warned = new Set<string>();
/** The hook exists from the start (an empty array = "no missing keys"), so the E2E can tell "none missing" from "hook not there". */
if (typeof window !== "undefined") window.__i18nMissing ??= [];
export function reportMissing(entry: MissingEntry): void {
  const id = `${entry.lang}|${entry.kind}|${entry.key}`;
  if (warned.has(id)) return;
  warned.add(id);
  if (typeof console !== "undefined") console.warn(`[i18n] missing ${entry.lang} ${entry.kind}: ${entry.key}`);
  if (typeof window !== "undefined") (window.__i18nMissing ??= []).push(entry);
}
/** test helper */
export function resetMissingReports(): void {
  warned.clear();
  if (typeof window !== "undefined") window.__i18nMissing = [];
}

export function createTranslator(
  lang: Lang,
  dictionaries: Partial<Record<Lang, Dictionary>>,
  englishEnums: Record<string, EnumTable> = {},
  onMissing: (e: MissingEntry) => void = reportMissing,
): Translator {
  const meta = LANG_META[lang];
  const fmt = createFormatter(lang);
  const dict = lang === "en" ? undefined : dictionaries[lang];
  const typoCache = new Map<string, string>();
  const typo = (s: string) => {
    if (lang !== "pl") return s;
    let v = typoCache.get(s);
    if (v === undefined) typoCache.set(s, (v = nbspOneLetterWords(s)));
    return v;
  };
  const formatNumber = (n: number) => fmt.number(n, 3);

  return {
    lang,
    locale: meta.locale,
    fmt,
    t(key, vars) {
      let template = key;
      if (lang !== "en") {
        const hit = dict?.messages[key];
        if (hit === undefined) onMissing({ lang, kind: "message", key });
        else template = typo(hit);
      }
      return interpolate(template, vars, formatNumber);
    },
    tn(count, forms, vars) {
      const category = pluralCategory(lang, count);
      let template: string;
      if (lang === "en") template = category === "one" ? forms.one : forms.other;
      else {
        const entry = dict?.plurals[forms.other];
        if (!entry) {
          onMissing({ lang, kind: "plural", key: forms.other });
          template = category === "one" ? forms.one : forms.other;
        } else template = typo(entry[category] ?? entry.other);
      }
      return interpolate(template, { n: count, ...vars }, formatNumber);
    },
    tEnum(group, id, fallback) {
      if (id === null || id === undefined || id === "") return "—";
      const key = String(id);
      if (lang !== "en") {
        const hit = dict?.enums[group]?.[key];
        if (hit !== undefined) return typo(hit);
        onMissing({ lang, kind: "enum", key: `${group}:${key}` });
      }
      return englishEnums[group]?.[key] ?? fallback ?? humanize(key);
    },
    hasEnum(group, id) {
      return lang === "en" ? englishEnums[group]?.[id] !== undefined : dict?.enums[group]?.[id] !== undefined;
    },
    findEnum(group, text) {
      const q = foldText(text).trim();
      if (lang === "en" || !dict || !q) return undefined;
      return Object.entries(dict.enums[group] ?? {}).find(([, label]) => foldText(label) === q)?.[0];
    },
    tOpen(group, id) {
      if (id === null || id === undefined || id === "") return "—";
      const key = String(id);
      const hit = lang === "en" ? englishEnums[group]?.[key] : dict?.enums[group]?.[key];
      return hit === undefined ? key : lang === "en" ? hit : typo(hit);
    },
    tKnown(text) {
      if (text === null || text === undefined) return "";
      const hit = lang === "en" ? undefined : dict?.messages[text];
      return hit === undefined ? text : typo(hit);
    },
  };
}

// ----------------------------------------------------------------------------------------------- collation + search
const collators = new Map<string, Intl.Collator>();
export function collatorFor(lang: Lang): Intl.Collator {
  const locale = LANG_META[lang].locale;
  let c = collators.get(locale);
  if (!c) collators.set(locale, (c = new Intl.Collator(locale, { sensitivity: "base", numeric: true })));
  return c;
}
/** Sorts by the language's alphabet (Polish: ą after a, ł after l, ś after s …); returns a new array. */
export function sortByLocale<T>(lang: Lang, items: readonly T[], key: (item: T) => string = (x) => String(x)): T[] {
  const c = collatorFor(lang);
  return [...items].sort((a, b) => c.compare(key(a), key(b)));
}
/** Diacritic-insensitive, case-insensitive containment (ł/Ł included): "lodz" finds "Łódź". */
export function matchesQuery(haystack: string, query: string): boolean {
  const q = foldText(query).trim();
  return q === "" || foldText(haystack).includes(q);
}
