import { describe, expect, it } from "vitest";
import { collatorFor, createTranslator, nbspOneLetterWords, normalizeLang, pluralCategory, resolveInitialLang, sortByLocale, matchesQuery, type MissingEntry } from "./core";
import { createFormatter } from "./format";
import { foldText } from "./search";
import { en } from "./en";
import { pl } from "./pl";

const NB = "\u00A0";
const plT = (onMissing?: (e: MissingEntry) => void) => createTranslator("pl", { pl }, en.enums, onMissing);
const enT = () => createTranslator("en", { pl }, en.enums);

describe("CLDR plural categories", () => {
  it("Polish: one / few / many / other", () => {
    const cat = (n: number) => pluralCategory("pl", n);
    expect([1].map(cat)).toEqual(["one"]);
    expect([2, 3, 4, 22, 23, 24, 32, 102].map(cat)).toEqual(Array(8).fill("few"));
    expect([0, 5, 6, 11, 12, 13, 14, 15, 21, 25, 100, 111, 112].map(cat)).toEqual(Array(13).fill("many"));
    expect(cat(1.5)).toBe("other");
  });

  it("English: one / other", () => {
    expect([1].map((n) => pluralCategory("en", n))).toEqual(["one"]);
    expect([0, 2, 5, 1.5].map((n) => pluralCategory("en", n))).toEqual(["other", "other", "other", "other"]);
  });

  it("tn() inflects the noun with the Polish form (1 plik, 2 pliki, 5 plików, 1,5 pliku)", () => {
    const { tn } = plT();
    const forms = { one: "{n} file", other: "{n} files" };
    expect([1, 2, 4, 5, 12, 22, 25].map((n) => tn(n, forms))).toEqual(["1 plik", "2 pliki", "4 pliki", "5 plików", "12 plików", "22 pliki", "25 plików"]);
    expect(tn(1.5, forms)).toBe("1,5 pliku");
    expect(tn(1234, forms)).toBe(`1${NB}234 pliki`); // …34 → few
    expect(tn(1235, forms)).toBe(`1${NB}235 plików`);
  });

  it("tn() keeps the English one/other source in English", () => {
    const { tn } = enT();
    const forms = { one: "{n} file", other: "{n} files" };
    expect([0, 1, 2].map((n) => tn(n, forms))).toEqual(["0 files", "1 file", "2 files"]);
  });

  it("every Polish plural entry reads correctly for 1, 2, 5 and 22 (sampled)", () => {
    const { tn } = plT();
    expect([1, 2, 5, 22].map((n) => tn(n, { one: "{n} variant", other: "{n} variants" }))).toEqual(["1 wariant", "2 warianty", "5 wariantów", "22 warianty"]);
    expect([1, 3, 7].map((n) => tn(n, { one: "{n} insight(s)", other: "{n} insight(s)" }))).toEqual(["1 wniosek", "3 wnioski", "7 wniosków"]);
  });
});

describe("pl-PL formatting", () => {
  const f = createFormatter("pl");
  const e = createFormatter("en");

  it("numbers: decimal comma and non-breaking thousands separator", () => {
    expect(f.number(1234.56, 2)).toBe(`1${NB}234,56`);
    expect(f.number(1234, 0)).toBe(`1${NB}234`); // 4-digit numbers are grouped too, so columns of figures stay aligned
    expect(f.fixed(7, 2)).toBe("7,00");
    expect(f.number(null)).toBe("—");
    expect(e.number(1234.56, 2)).toBe("1,234.56");
  });

  it("currency and percent", () => {
    expect(f.usd(1234.5)).toBe(`1${NB}234,50${NB}USD`);
    expect(f.currency(379, "PLN")).toBe(`379,00${NB}zł`);
    expect(f.pct(12.3)).toBe("12,3%");
    expect(f.percent(0.5, 0)).toBe("50%");
    expect(e.usd(1234.5)).toBe("$1,234.50");
  });

  it("compact USD as the business case quotes it", () => {
    expect(f.compactUsd(6_980_000)).toBe(`6,98${NB}mln${NB}USD`);
    expect(f.compactUsd(465_000)).toBe(`465${NB}tys.${NB}USD`);
    expect(e.compactUsd(6_980_000)).toBe("$6.98M");
    expect(e.compactUsd(465_000)).toBe("$465k");
  });

  it("dates and times: 18.11.2026, 24 h clock, Europe/Warsaw (winter and summer time)", () => {
    expect(f.date("2026-11-18T07:21:47Z")).toBe("18.11.2026");
    expect(f.time("2026-11-18T07:21:47Z")).toBe("08:21");
    expect(f.time("2026-07-01T10:00:00Z")).toBe("12:00");
    expect(f.time("2026-11-18T23:05:00Z")).toBe("00:05"); // never "24:05"
    expect(f.dateTime("2026-11-18T07:21:47Z")).toBe("18.11.2026, 08:21");
    expect(f.isoDate("2026-12-01")).toBe("01.12.2026");
    expect(e.isoDate("2026-12-01")).toBe("2026-12-01");
    expect(f.date(null)).toBe("—");
    expect(f.date("not a date")).toBe("—");
  });

  it("relative time: 2 godz. temu, za 3 dni, wczoraj", () => {
    const now = Date.parse("2026-11-18T12:00:00Z");
    expect(f.relative(now - 2 * 3600_000, now)).toBe("2 godz. temu");
    expect(f.relative(now + 3 * 86400_000, now)).toBe("za 3 dni");
    expect(f.relative(now - 86400_000, now)).toBe("wczoraj");
    expect(f.relative(now - 5 * 60_000, now)).toBe("5 min temu");
  });

  it("language names come from Intl.DisplayNames in the UI language", () => {
    expect(f.languageName("de")).toBe("Niemiecki");
    expect(f.languageName("en")).toBe("Angielski");
    expect(e.languageName("de")).toBe("German");
  });

  it("short codes: compact in English, spaced in Polish", () => {
    expect(e.codes(["US", "DE"])).toBe("US,DE");
    expect(f.codes(["PL", "DE"])).toBe("PL, DE");
  });
});

describe("Polish collation (Intl.Collator)", () => {
  it("sorts ą after a, ć after c, ł after l, ń after n, ó after o, ś after s, ź/ż after z", () => {
    const words = ["Żaba", "Zebra", "Źrebak", "Śląsk", "Sopot", "Łódź", "Lublin", "Ósemka", "Orzeł", "Ćma", "Cukier", "ąbc", "abc", "Ń", "N"];
    expect(sortByLocale("pl", words)).toEqual(["abc", "ąbc", "Cukier", "Ćma", "Lublin", "Łódź", "N", "Ń", "Orzeł", "Ósemka", "Sopot", "Śląsk", "Zebra", "Źrebak", "Żaba"]);
  });

  it("sorts by a key and does not mutate the input; numeric parts sort naturally", () => {
    const rows = [{ n: "Wersja 10" }, { n: "Wersja 2" }, { n: "Łączenie" }];
    const out = sortByLocale("pl", rows, (r) => r.n);
    expect(out.map((r) => r.n)).toEqual(["Łączenie", "Wersja 2", "Wersja 10"]);
    expect(rows[0].n).toBe("Wersja 10");
    expect(collatorFor("pl")).toBe(collatorFor("pl"));
  });
});

describe("diacritic-insensitive search (ł/Ł included — NFKD does not decompose them)", () => {
  it("folds Polish letters", () => {
    expect(foldText("Zażółć gęślą jaźń")).toBe("zazolc gesla jazn");
    expect(foldText("ŁÓDŹ — Gdańsk")).toBe("lodz — gdansk");
    expect(foldText("Straße Øl")).toBe("strasse ol");
  });

  it("finds Łódź with 'lodz' and 'ŁODZ', and does not find Lublin", () => {
    expect(matchesQuery("Spot dla Łodzi i Łódzkiego", "lodz")).toBe(true);
    expect(matchesQuery("Łódź", "ŁODZ")).toBe(true);
    expect(matchesQuery("Zespół i integracje", "zespol")).toBe(true);
    expect(matchesQuery("Współpraca", "wspolpraca")).toBe(true);
    expect(matchesQuery("Lublin", "lodz")).toBe(false);
    expect(matchesQuery("cokolwiek", "")).toBe(true);
  });
});

describe("language resolution", () => {
  it("?lang= beats the saved choice, which beats navigator.languages, which beats the default", () => {
    expect(resolveInitialLang({ search: "?lang=pl", saved: "en", navigatorLanguages: ["en-US"] })).toBe("pl");
    expect(resolveInitialLang({ search: "?x=1&lang=EN", saved: "pl", navigatorLanguages: ["pl-PL"] })).toBe("en");
    expect(resolveInitialLang({ search: "", saved: "pl", navigatorLanguages: ["en-US"] })).toBe("pl");
    expect(resolveInitialLang({ search: "", saved: null, navigatorLanguages: ["de-DE", "pl-PL", "en"] })).toBe("pl");
    expect(resolveInitialLang({ search: "?lang=xx", saved: "zz", navigatorLanguages: ["fr"] })).toBe("en");
  });

  it("normalizes locale tags", () => {
    expect(normalizeLang("pl-PL")).toBe("pl");
    expect(normalizeLang("PL_pl")).toBe("pl");
    expect(normalizeLang("de")).toBeNull();
    expect(normalizeLang(undefined)).toBeNull();
  });
});

describe("translator behaviour", () => {
  it("keeps one-letter words (a, i, o, u, w, z) with the next word using a non-breaking space", () => {
    expect(nbspOneLetterWords("Kawa i mleko w domu")).toBe(`Kawa i${NB}mleko w${NB}domu`);
    expect(nbspOneLetterWords("Ala ma kota")).toBe("Ala ma kota");
    expect(plT().t("Create {n} variants", { n: 3 })).toBeTruthy();
  });

  it("falls back to English, reports a missing key once and records it", () => {
    const seen: MissingEntry[] = [];
    const tr = plT((e) => seen.push(e));
    expect(tr.t("A string nobody translated")).toBe("A string nobody translated");
    expect(seen).toEqual([{ lang: "pl", kind: "message", key: "A string nobody translated" }]);
  });

  it("interpolates numbers with the locale and leaves unknown {tokens} alone", () => {
    expect(plT().t("{n} MB", { n: 1234.5 })).toBe(`1${NB}234,5${NB}MB`);
    expect(enT().t("{n} MB", { n: 1234.5 })).toBe("1,234.5 MB");
    expect(enT().t("a {b} c", { x: 1 })).toBe("a {b} c");
  });

  it("tKnown(): server text is shown as received unless it is one of the dictionary's own English sources", () => {
    const tr = plT();
    expect(tr.tKnown("Neutral US English.")).toBe("Neutralna amerykańska angielszczyzna.");
    expect(tr.tKnown("Tekst z serwera po polsku")).toBe("Tekst z serwera po polsku");
    expect(tr.tKnown(undefined)).toBe("");
    expect(enT().tKnown("Neutral US English.")).toBe("Neutral US English.");
  });

  it("tEnum(): dictionary label by id; API text / humanized id as the English fallback", () => {
    const p = plT();
    expect(p.tEnum("status", "in_review")).toBe(`w${NB}przeglądzie`); // one-letter words are kept with the next word
    expect(p.tEnum("status", null)).toBe("—");
    expect(enT().tEnum("status", "changes_requested")).toBe("changes requested");
    expect(p.tOpen("channel", "tiktok")).toBe("TikTok");
    expect(p.tOpen("channel", "myspace")).toBe("myspace"); // open sets show the raw id, never a "missing key"
  });
});
