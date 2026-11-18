import { createElement, Fragment, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createTranslator, DEFAULT_LANG, LANG_META, LANG_STORAGE_KEY, normalizeLang, resolveInitialLang, SUPPORTED_LANGS, type Lang, type Translator, type Vars } from "./core";
import { en } from "./en";
import { pl } from "./pl";

export { LANG_META, SUPPORTED_LANGS, sortByLocale, matchesQuery } from "./core";
export { foldText } from "./search";
export type { Lang, Translator, Vars } from "./core";

/** Marks a string for extraction/translation without translating it now; translate later with t(value). */
export const msg = <S extends string>(source: S): S => source;

const translators: Partial<Record<Lang, Translator>> = {};
export function getTranslator(lang: Lang = current): Translator {
  return (translators[lang] ??= createTranslator(lang, { pl }, en.enums));
}

let current: Lang = DEFAULT_LANG;
const listeners = new Set<() => void>();
export const getLang = (): Lang => current;
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

function readSaved(): string | null {
  try {
    return localStorage.getItem(LANG_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** <html lang>, document title and meta description follow the UI language. */
function applyDocument(lang: Lang): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = lang;
  const tr = getTranslator(lang);
  document.title = tr.t("Spotlight — SwarmAI Commercial Studio");
  document.querySelector('meta[name="description"]')?.setAttribute("content", tr.t("SwarmAI Commercial Studio (Spotlight) — brief-to-broadcast AI commercial studio"));
}

/** Call once before the first render: ?lang= → saved choice → navigator.languages → en. */
export function initLang(): Lang {
  const search = typeof location !== "undefined" ? location.search : "";
  const fromUrl = normalizeLang(new URLSearchParams(search).get("lang"));
  current = resolveInitialLang({ search, saved: readSaved(), navigatorLanguages: typeof navigator !== "undefined" ? navigator.languages : [] });
  if (fromUrl) {
    try {
      localStorage.setItem(LANG_STORAGE_KEY, current);
    } catch {
      /* storage unavailable (private mode): the choice lasts for this page view */
    }
  }
  applyDocument(current);
  return current;
}

/** An explicit choice must survive a reload: a leftover ?lang= in the address bar would win over the saved choice again, so it is dropped. */
function dropLangParam(): void {
  if (typeof location === "undefined" || typeof history === "undefined") return;
  const url = new URL(location.href);
  if (!url.searchParams.has("lang")) return;
  url.searchParams.delete("lang");
  history.replaceState(history.state, "", url.pathname + url.search + url.hash);
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
  dropLangParam();
  applyDocument(lang);
  listeners.forEach((l) => l());
}

type Tags = Record<string, (chunks: ReactNode) => ReactNode>;
/** `<tag>inner</tag>` → tags.tag(inner); the markup lives inside the translated message so word order can differ per language. */
function renderRich(text: string, tags: Tags, depth = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /<(\w+)>([\s\S]*?)<\/\1>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const wrap = tags[m[1]];
    const inner = depth < 3 ? renderRich(m[2], tags, depth + 1) : [m[2]];
    out.push(createElement(Fragment, { key: `${depth}-${i++}` }, wrap ? wrap(inner) : inner));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export interface I18n extends Translator {
  setLang: (lang: Lang) => void;
  /** rich message: `tx("None yet — <go>start one</go>.", { go: (c) => <Link>{c}</Link> })` */
  tx: (key: string, tags: Tags, vars?: Vars) => ReactNode;
  langs: readonly Lang[];
}

/** Reactive access to the language, translators and formatters: components using it re-render when the language changes. */
export function useI18n(): I18n {
  const lang = useSyncExternalStore(subscribe, getLang, getLang);
  return useMemo(() => {
    const tr = getTranslator(lang);
    return { ...tr, setLang, langs: SUPPORTED_LANGS, tx: (key: string, tags: Tags, vars?: Vars) => createElement(Fragment, null, ...renderRich(tr.t(key, vars), tags)) };
  }, [lang]);
}

/** Runs `cb` when the UI language changes (not on mount) — used to re-request server-localized results that live in component state. */
export function useOnLangChange(cb: (lang: Lang) => void): void {
  const { lang } = useI18n();
  const prev = useRef(lang);
  const latest = useRef(cb);
  latest.current = cb;
  useEffect(() => {
    if (prev.current === lang) return;
    prev.current = lang;
    latest.current(lang);
  }, [lang]);
}

/** A text value whose default depends on the language (sample copy, default names): follows the language until the user edits it. */
export function useLocalizedDefault(make: (i18n: Translator) => string): [string, (v: string) => void, () => void] {
  const { lang } = useI18n();
  const [custom, setCustom] = useState<string | null>(null);
  const value = custom ?? make(getTranslator(lang));
  return [value, setCustom, () => setCustom(null)];
}

export const languageLabel = (lang: Lang) => LANG_META[lang].name;

/** Initialises the language on first render (idempotent). State is module-level so non-React code (api.ts) shares it with the components. */
export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Lang }) {
  useState(() => {
    if (initial) setLang(initial);
    return null;
  });
  return children;
}

declare global {
  interface Window {
    /** Read-only hook for the E2E journeys: they derive Polish selectors from the dictionary instead of hard-coding strings. */
    __i18n?: { lang: () => Lang; t: Translator["t"]; tn: Translator["tn"]; tEnum: Translator["tEnum"] };
  }
}
if (typeof window !== "undefined") {
  window.__i18n = { lang: getLang, t: (k, v) => getTranslator().t(k, v), tn: (n, f, v) => getTranslator().tn(n, f, v), tEnum: (g, i, f) => getTranslator().tEnum(g, i, f) };
}
