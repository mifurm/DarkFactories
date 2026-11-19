import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { placeholders } from "./core";
import { en } from "./en";
import { motionEnums, motionMessages, motionPlurals } from "./pl/motion";

/**
 * The cinematic-motion strings follow the Polish typography of the glossary (GLOSSARY.md): „…” quotes, one-character ellipsis, a spaced em dash between clauses,
 * a no-break space between a number and its unit, sentence punctuation as in the English source. The generic completeness checks live in i18n.test.ts.
 */
const entries = Object.entries(motionMessages);
const plural = Object.entries(motionPlurals).flatMap(([other, forms]) => Object.entries(forms).map(([form, text]) => [`${other} (${form})`, text, other] as const));
const everyPolishText = [...entries.map(([k, v]) => [k, v] as const), ...plural.map(([k, v]) => [k, v] as const), ...Object.entries(motionEnums).flatMap(([g, t]) => Object.entries(t).map(([id, v]) => [`${g}.${id}`, v] as const))];

describe("Polish typography of the motion strings", () => {
  it("uses the ellipsis character, no straight quotes, no hyphen as a dash, no stray spaces", () => {
    const problems: string[] = [];
    for (const [key, text] of everyPolishText) {
      if (text.includes("...")) problems.push(`${key}: three dots instead of …`);
      if (text.includes('"')) problems.push(`${key}: straight double quote (use „…”)`);
      if (/ - /.test(text)) problems.push(`${key}: " - " (use a spaced em dash)`);
      if (/ {2,}/.test(text)) problems.push(`${key}: double space`);
      if (text !== text.trim()) problems.push(`${key}: leading or trailing space`);
      if (/\s[,.;:!?]/.test(text)) problems.push(`${key}: space before punctuation`);
    }
    expect(problems).toEqual([]);
  });

  it("separates a number or a {placeholder} from its unit with a no-break space", () => {
    const unit = /(?:\d|\})[ ](?:s|min|ms|MB|KB|fps|USD|zł|LUFS|dBFS|bpm)\b/;
    const bad = everyPolishText.filter(([, text]) => unit.test(text)).map(([key]) => key);
    expect(bad, "write the space as \\u00A0").toEqual([]);
  });

  it("keeps the sentence shape of the English source: same final punctuation, same first-letter case", () => {
    const problems: string[] = [];
    const final = (s: string) => (/[.…:?!)]$/.exec(s) ?? [""])[0];
    const upper = (s: string) => {
      const first = [...s].find((c) => c.toLowerCase() !== c.toUpperCase());
      return first === undefined ? null : first === first.toUpperCase();
    };
    for (const [source, text] of entries) {
      if (source.includes("<")) continue; // markup message: the tag text is translated inside the sentence
      if (final(source) !== final(text)) problems.push(`${source}: ends with "${final(text)}" instead of "${final(source)}"`);
      const acronymStart = /^[A-Z]{2,}\b/.test(source); // "AI video …" is capitalised because of the acronym, its Polish counterpart ("wideo AI …") is not
      if (!acronymStart && upper(source) !== null && upper(text) !== null && upper(source) !== upper(text)) problems.push(`${source}: first letter case differs`);
    }
    expect(problems).toEqual([]);
  });

  it("keeps the markup of rich messages and every {placeholder} of the source", () => {
    for (const [source, text] of entries) {
      expect(placeholders(text).join(), source).toBe(placeholders(source).join());
      expect(text.match(/<\/?\w+>/g) ?? [], source).toEqual(source.match(/<\/?\w+>/g) ?? []);
    }
  });

  it("every plural form carries the count and the right noun form", () => {
    for (const [name, text, other] of plural) {
      expect(placeholders(text).join(), name).toBe(placeholders(other).join());
      expect(text, name).toContain("{n}");
    }
    expect(motionPlurals["{n} fallbacks"]).toMatchObject({ one: "{n} ujęcie zastępcze", few: "{n} ujęcia zastępcze", many: "{n} ujęć zastępczych" });
    expect(motionPlurals["{n} jobs in the GPU queue"]).toMatchObject({ one: "{n} zadanie w kolejce GPU", few: "{n} zadania w kolejce GPU", many: "{n} zadań w kolejce GPU" });
  });

  it("the glossary terms are used consistently", () => {
    const texts = everyPolishText.map(([, t]) => t).join("\n");
    expect(texts).not.toMatch(/\bcache\b/i); // "pamięć podręczna", as in the rest of the UI
    expect(texts).not.toMatch(/\bshot\b|\bclip\b|\bmotion\b/i); // no English leftovers
    expect(texts).not.toMatch(/kompozytor/i); // never "kompozytor" for the compositor (a music composer)
    expect(texts).toContain("pamięci podręcznej");
    expect(texts).toContain("ujęcie");
  });
});

/**
 * Why a shot fell back to camera moves: the codes are the backend's (spotlight/motion/models.py FALLBACK_REASONS; the server also sends a localized `reason_text`, which the UI prefers —
 * the dictionary labels payloads that carry only the code). `unavailable`, `failed` and `bad_clip` are the codes of an earlier revision: kept, so older artifacts still read well.
 */
const BACKEND_MODELS = path.resolve(__dirname, "../../../src/spotlight/motion/models.py");
const EARLIER_CODES = ["unavailable", "failed", "bad_clip"];

describe("Fallback reason labels", () => {
  it("the new backend codes read as specified", () => {
    expect(motionEnums.motionFallback).toMatchObject({ worker_unavailable: "GPU niedostępne", internal: "błąd wewnętrzny generowania", disabled: "ruch AI wyłączony na serwerze" });
    expect(en.enums.motionFallback).toMatchObject({ worker_unavailable: "GPU unavailable", internal: "internal generation error", disabled: "AI motion turned off on the server" });
  });

  it("the earlier codes stay labelled in both languages", () => {
    for (const code of EARLIER_CODES) {
      expect(Object.keys(en.enums.motionFallback), code).toContain(code);
      expect(Object.keys(motionEnums.motionFallback), code).toContain(code);
    }
  });

  describe.runIf(fs.existsSync(BACKEND_MODELS))("against the backend list", () => {
    const codes = [...(/FALLBACK_REASONS\s*=\s*\(([^)]*)\)/.exec(fs.readFileSync(BACKEND_MODELS, "utf8"))?.[1] ?? "").matchAll(/"(\w+)"/g)].map((m) => m[1]);

    it("reads the backend list", () => {
      expect(codes.length).toBeGreaterThanOrEqual(8);
      expect(codes).toContain("worker_unavailable");
    });

    it("every backend code has an English and a Polish label, and nothing else is labelled but the earlier codes", () => {
      for (const labelled of [Object.keys(en.enums.motionFallback), Object.keys(motionEnums.motionFallback)]) {
        expect(codes.filter((c) => !labelled.includes(c))).toEqual([]);
        expect(labelled.filter((c) => !codes.includes(c) && !EARLIER_CODES.includes(c))).toEqual([]);
      }
    });
  });
});

/** The motion-quality gate's wording (levels, retry note, tooltip) as agreed; the sentences of the hint are checked where they render (components.test.tsx). */
describe("Motion-quality labels", () => {
  it("the three levels read as agreed, in both languages, with the same ids", () => {
    expect(en.enums.motionLevel).toEqual({ rich: "Rich motion", subtle: "Subtle motion", low: "Low motion" });
    expect(motionEnums.motionLevel).toEqual({ rich: "Dużo ruchu", subtle: "Subtelny ruch", low: "Mało ruchu" });
  });

  it("the retry note and the tooltip read as agreed (decimal comma and no-break spaces before the units come from the formatter and the dictionary)", () => {
    expect(motionMessages["retried with another seed"]).toBe("ponowiono z innym ziarnem");
    expect(motionMessages["Non-rigid motion: {value} px per 0.4 s (a still with camera moves: ≈ {still})"]).toBe("Ruch niesztywny: {value}\u00A0px na 0,4\u00A0s (ruch kamery na nieruchomej klatce: ≈ {still})");
  });
});
