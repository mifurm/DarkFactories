import { describe, expect, it } from "vitest";
import { placeholders } from "./core";
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
