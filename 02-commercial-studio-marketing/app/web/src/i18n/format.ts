/** Locale-aware formatting built on Intl.* (en-US / pl-PL). Pure: no DOM, no React. */
import type { Lang } from "./core";

type DateInput = string | number | Date | null | undefined;
type NumberOpts = number | Intl.NumberFormatOptions;
export type CurrencyDigits = number | { min?: number; max?: number };

export interface Formatter {
  lang: Lang;
  locale: string;
  /** zone used for absolute times (Polish UI: Europe/Warsaw; English: the browser's zone) */
  timeZone?: string;
  /** number → maximum fraction digits, or full Intl options; "—" for null/NaN */
  number(v: number | null | undefined, opts?: NumberOpts): string;
  /** exactly `digits` fraction digits */
  fixed(v: number | null | undefined, digits: number): string;
  currency(v: number | null | undefined, currency?: string, digits?: CurrencyDigits): string;
  /** USD amount with `digits` fraction digits (the app is USD based: "$1,234.50" / "1 234,50 USD") */
  usd(v: number | null | undefined, digits?: CurrencyDigits): string;
  /** fraction → percent string (0.123 → "12.3%" / "12,3%") */
  percent(fraction: number | null | undefined, digits?: number): string;
  /** a value that is already a percentage (12.3 → "12.3%") */
  pct(percentValue: number | null | undefined, digits?: number): string;
  date(v: DateInput): string;
  /** a calendar date given as "YYYY-MM-DD" (no time zone): English keeps the ISO text, Polish shows 01.12.2026 */
  isoDate(v: string | null | undefined): string;
  time(v: DateInput): string;
  dateTime(v: DateInput): string;
  /** "2 hr. ago" / "2 godz. temu" */
  relative(v: DateInput, now?: number): string;
  /** USD in compact form: $6.98M · $465k (English, as the business case quotes it) / 6,98 mln USD · 465 tys. USD */
  compactUsd(v: number | null | undefined): string;
  /** "Polish" in the active language (Intl.DisplayNames), capitalised; falls back to `fallback` */
  languageName(code: string, fallback?: string): string;
  /** short codes/labels joined for display: English keeps the compact historical "US,DE" form, Polish reads "PL, DE" */
  codes(items: readonly string[]): string;
}

const DASH = "—";
const toDate = (v: DateInput): Date | null => {
  if (v === null || v === undefined || v === "") return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
};

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat | Intl.DisplayNames>();
function memo<T extends Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat | Intl.DisplayNames>(key: string, make: () => T): T {
  let v = cache.get(key) as T | undefined;
  if (!v) cache.set(key, (v = make()));
  return v;
}

export function createFormatter(lang: Lang): Formatter {
  const pl = lang === "pl";
  const locale = pl ? "pl-PL" : "en-US";
  const timeZone = pl ? "Europe/Warsaw" : undefined;
  // Polish groups 4-digit numbers only from 5 digits by CLDR default; "always" keeps columns of figures consistent ("1 234").
  const grouping = pl ? ({ useGrouping: "always" } as Intl.NumberFormatOptions) : {};

  const nf = (o: Intl.NumberFormatOptions) => memo(`n|${locale}|${JSON.stringify(o)}`, () => new Intl.NumberFormat(locale, { ...grouping, ...o }));
  const df = (o: Intl.DateTimeFormatOptions) => memo(`d|${locale}|${timeZone}|${JSON.stringify(o)}`, () => new Intl.DateTimeFormat(locale, { timeZone, ...o }));

  const finite = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);
  const digitsOf = (d: CurrencyDigits | undefined, fallback = 2) => {
    if (typeof d === "number") return { minimumFractionDigits: d, maximumFractionDigits: d };
    if (d && typeof d === "object") return { minimumFractionDigits: d.min ?? 0, maximumFractionDigits: d.max ?? d.min ?? fallback };
    return { minimumFractionDigits: fallback, maximumFractionDigits: fallback };
  };

  const number: Formatter["number"] = (v, opts = 0) => {
    if (!finite(v)) return DASH;
    return nf(typeof opts === "number" ? { maximumFractionDigits: opts } : opts).format(v);
  };
  const currency: Formatter["currency"] = (v, cur = "USD", digits) => (finite(v) ? nf({ style: "currency", currency: cur, ...digitsOf(digits) }).format(v) : DASH);
  const percent: Formatter["percent"] = (f, d = 1) => (finite(f) ? nf({ style: "percent", minimumFractionDigits: d, maximumFractionDigits: d }).format(f) : DASH);

  const dateTime: Formatter["dateTime"] = (v) => {
    const d = toDate(v);
    if (!d) return DASH;
    return (pl ? df({ day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : df({ dateStyle: "medium", timeStyle: "short" })).format(d);
  };

  return {
    lang,
    locale,
    timeZone,
    number,
    fixed: (v, digits) => number(v, { minimumFractionDigits: digits, maximumFractionDigits: digits }),
    currency,
    usd: (v, digits) => currency(v, "USD", digits),
    percent,
    pct: (v, d = 1) => (finite(v) ? percent(v / 100, d) : DASH),
    date(v) {
      const d = toDate(v);
      if (!d) return DASH;
      return (pl ? df({ day: "2-digit", month: "2-digit", year: "numeric" }) : df({ dateStyle: "medium" })).format(d);
    },
    isoDate(v) {
      if (!v) return DASH;
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
      return pl && m ? `${m[3]}.${m[2]}.${m[1]}` : v;
    },
    time(v) {
      const d = toDate(v);
      if (!d) return DASH;
      return (pl ? df({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : df({ timeStyle: "short" })).format(d);
    },
    dateTime,
    relative(v, now = Date.now()) {
      const d = toDate(v);
      if (!d) return DASH;
      const rtf = memo(`r|${locale}`, () => new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" }));
      const sec = Math.round((d.getTime() - now) / 1000);
      const abs = Math.abs(sec);
      const steps: [number, Intl.RelativeTimeFormatUnit, number][] = [
        [45, "second", 1],
        [45 * 60, "minute", 60],
        [22 * 3600, "hour", 3600],
        [6 * 86400, "day", 86400],
        [26 * 86400, "week", 7 * 86400],
        [320 * 86400, "month", 30 * 86400],
      ];
      for (const [limit, unit, size] of steps) if (abs < limit) return rtf.format(unit === "second" ? 0 : Math.round(sec / size), unit);
      return rtf.format(Math.round(sec / (365 * 86400)), "year");
    },
    compactUsd(v) {
      if (!finite(v)) return DASH;
      const a = Math.abs(v);
      if (!pl) {
        const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(0)}k` : a.toFixed(0);
        return `${v < 0 ? "−" : ""}$${s}`;
      }
      return nf({ style: "currency", currency: "USD", notation: "compact", compactDisplay: "short", maximumFractionDigits: a >= 1e6 ? 2 : 0 }).format(v);
    },
    languageName(code, fallback) {
      try {
        const name = memo(`l|${locale}`, () => new Intl.DisplayNames(locale, { type: "language" })).of(code);
        if (name && name !== code) return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
      } catch {
        /* unknown code */
      }
      return fallback ?? code;
    },
    codes: (items) => items.join(pl ? ", " : ","),
  };
}
