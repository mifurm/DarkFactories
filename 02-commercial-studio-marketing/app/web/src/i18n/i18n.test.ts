import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { createTranslator, placeholders, type Dictionary, type MissingEntry } from "./core";
import { en } from "./en";
import { pl } from "./pl";
import { extractFromSource } from "./extract";

const SRC = path.resolve(__dirname, "..");
const extraction = extractFromSource(SRC);

// Dynamic t(variable) calls are fed by msg("…") constants (nav labels, workspace tab labels, known server texts); nothing else may use them.
const DYNAMIC_ALLOWED = [/^App\.tsx$/, /^i18n[\\/]index\.tsx$/, /^features[\\/]cs20-studio[\\/]/, /^features[\\/]cs23-roi[\\/]/, /^components[\\/]ui\.tsx$/];

// Messages that are legitimately identical in Polish: product names, codes and identifiers, Polish cognates ("Status", "Format", "Model"…) and the
// loan words Polish marketing/IT professionals use unchanged (brief, storyboard, claim, hook, talent, stock, render, webhook, SLA, CTA — spec §2).
const SAME_IN_POLISH = new Set([
  // names, codes, identifiers
  "Spotlight — SwarmAI Commercial Studio", "Brand Brain", "IRR", "CTR", "VTR", "CVR", "CPA", "ROAS", "OpenAPI", "gpt-image-1.5", "gpt-image-1-mini", "URL", "{n} MB", "CS-01 · Brand kit & Brand Brain",
  "REST API", "Webhook", "SLA", "CTA:", "{title} · sha256 {hash}…",
  // Polish cognates
  "Logo", "Status", "status", "Audio", "Format", "Generator", "Premium", "Model", "Persona", "studio", "Region",
  // loan words kept by Polish professionals
  "Brief", "Storyboard", "Claim", "Render · {lang}", "Hook: {text}", "Talent: {name}", "Stock: {title}",
]);

// Plural messages whose count is implicit (the noun inflects with it, the number itself is not printed): they need no {n} in the Polish forms.
const COUNT_IMPLICIT = new Set(["Write {list}s scripts"]);

describe("report (opt-in)", () => {
  it.runIf(!!process.env.I18N_REPORT)("writes the extracted keys and the gaps to $I18N_REPORT", () => {
    const missing = [...extraction.messages.keys()].filter((k) => !(k in pl.messages));
    const missingPlurals = [...extraction.plurals.keys()].filter((k) => !(k in pl.plurals));
    const byFile: Record<string, string[]> = {};
    for (const [k, sites] of extraction.messages) (byFile[sites[0].file] ??= []).push(k);
    const pluralsByFile: Record<string, { one: string; other: string }[]> = {};
    for (const [other, variants] of extraction.plurals) for (const v of variants) (pluralsByFile[v.sites[0].file] ??= []).push({ one: v.one, other });
    const out = {
      messages: extraction.messages.size,
      plurals: extraction.plurals.size,
      missing,
      missingPlurals: missingPlurals.map((k) => ({ other: k, one: extraction.plurals.get(k)!.map((e) => e.one) })),
      unused: Object.keys(pl.messages).filter((k) => !extraction.messages.has(k)),
      dynamic: extraction.dynamic,
      enumGroups: [...extraction.enumGroups.keys()],
      byFile,
      pluralsByFile,
    };
    fs.writeFileSync(process.env.I18N_REPORT!, JSON.stringify(out, null, 1));
    expect(true).toBe(true);
  });
});

describe("dictionary completeness", () => {
  it("extracts a plausible number of keys", () => {
    expect(extraction.messages.size).toBeGreaterThan(300);
    expect(extraction.plurals.size).toBeGreaterThan(20);
  });

  it("has a Polish translation for every t()/tx()/msg() literal", () => {
    const missing = [...extraction.messages.keys()].filter((k) => !(k in pl.messages));
    expect(missing, `missing pl messages:\n${missing.join("\n")}`).toEqual([]);
  });

  it("has no unused Polish messages", () => {
    const unused = Object.keys(pl.messages).filter((k) => !extraction.messages.has(k));
    expect(unused, `unused pl messages:\n${unused.join("\n")}`).toEqual([]);
  });

  it("keeps {placeholders} identical between source and translation", () => {
    const bad = Object.entries(pl.messages).filter(([k, v]) => placeholders(k).join() !== placeholders(v).join());
    expect(bad.map(([k]) => k)).toEqual([]);
  });

  it("does not leave Polish messages equal to the English source (unless it is a name/code or the same Polish word)", () => {
    const same = Object.entries(pl.messages).filter(([k, v]) => k === v && !SAME_IN_POLISH.has(k) && /[A-Za-z]{3,}/.test(k.replace(/\{\w+\}/g, "")));
    expect(same.map(([k]) => k), "translations identical to the English source — translate them or add them (deliberately) to SAME_IN_POLISH").toEqual([]);
  });

  it("has all four Polish plural forms for every tn() call and no unused plural entries", () => {
    const problems: string[] = [];
    for (const [other, variants] of extraction.plurals) {
      if (variants.length > 1) problems.push(`two tn() calls share the key "${other}" with different "one" forms`);
      const entry = pl.plurals[other];
      if (!entry) {
        problems.push(`missing pl plural: ${other}`);
        continue;
      }
      for (const form of ["one", "few", "many", "other"] as const) {
        if (!entry[form]) problems.push(`pl plural "${other}" lacks "${form}"`);
        else if (!COUNT_IMPLICIT.has(other) && !placeholders(entry[form]!).includes("n")) problems.push(`pl plural "${other}" (${form}) lacks {n}`);
      }
      const want = placeholders(other).join();
      for (const [form, text] of Object.entries(entry)) if (text && placeholders(text).join() !== want) problems.push(`pl plural "${other}" (${form}) placeholders differ`);
    }
    for (const k of Object.keys(pl.plurals)) if (!extraction.plurals.has(k)) problems.push(`unused pl plural: ${k}`);
    expect(problems).toEqual([]);
  });

  it("allows non-literal t() arguments only where msg() constants feed them", () => {
    const bad = extraction.dynamic.filter((d) => !DYNAMIC_ALLOWED.some((r) => r.test(d.file)));
    expect(bad.map((d) => `${d.file}:${d.line} ${d.text}`)).toEqual([]);
  });
});

describe("ID-keyed tables", () => {
  it("defines every English enum id in Polish (and nothing else)", () => {
    const problems: string[] = [];
    for (const [group, table] of Object.entries(en.enums)) {
      const plTable = pl.enums[group];
      if (!plTable) {
        problems.push(`pl.enums lacks group ${group}`);
        continue;
      }
      for (const id of Object.keys(table)) if (!(id in plTable)) problems.push(`pl.enums.${group} lacks "${id}"`);
      for (const id of Object.keys(plTable)) if (!(id in table)) problems.push(`pl.enums.${group} has unknown id "${id}"`);
    }
    expect(problems).toEqual([]);
  });

  it("only uses enum groups that exist", () => {
    const known = new Set([...Object.keys(en.enums), ...Object.keys(pl.enums)]);
    const bad = [...extraction.enumGroups.keys()].filter((g) => !known.has(g));
    expect(bad).toEqual([]);
  });

  it("returns the English label (or the API text) in English and never reports a missing key for it", () => {
    const missing: MissingEntry[] = [];
    const tr = createTranslator("en", { pl: pl as Dictionary }, en.enums, (e) => missing.push(e));
    expect(tr.tEnum("status", "in_review")).toBe("in review");
    expect(tr.tEnum("feature", "CS-01", "Brand Kit & Brand Brain")).toBe("Brand Kit & Brand Brain");
    expect(missing).toEqual([]);
  });
});

describe("ROI & ACR calculator labels (keyed by the business-case model's keys)", () => {
  // roi-keys.json is generated from the vendored model (`npm run export:roi-keys`; `-- --check` fails when it is stale).
  const roiKeys = JSON.parse(fs.readFileSync(path.join(__dirname, "roi-keys.json"), "utf8")) as Record<string, string | Record<string, string>>;
  const groups = Object.entries(roiKeys).filter((e): e is [string, Record<string, string>] => typeof e[1] === "object");

  it("covers every lever, tier, benefit, cost, service family, sensitivity driver, override spec and unit of the model — and nothing else", () => {
    expect(groups.map(([g]) => g).sort()).toEqual(["roiBenefit", "roiCost", "roiFamily", "roiLever", "roiScenario", "roiSens", "roiSpec", "roiTier", "roiTierDesc", "roiUnit"]);
    const problems: string[] = [];
    for (const [group, table] of groups) {
      const plTable = pl.enums[group];
      if (!plTable) {
        problems.push(`pl.enums lacks ${group}`);
        continue;
      }
      for (const id of Object.keys(table)) if (!(id in plTable)) problems.push(`pl.enums.${group} lacks model key "${id}"`);
      for (const id of Object.keys(plTable)) if (!(id in table)) problems.push(`pl.enums.${group} has "${id}", which is not a model key`);
    }
    expect(problems).toEqual([]);
  });

  it("translates every long label (no Polish label equals its English source, units and product names aside)", () => {
    const KEEP = new Set(["Azure AI Content Safety", "Azure AI Search", "Azure Cosmos DB"]); // product names
    const same: string[] = [];
    for (const [group, table] of groups)
      for (const [id, label] of Object.entries(table)) {
        const pln = pl.enums[group]?.[id];
        if (pln === label && !KEEP.has(label) && /[A-Za-z]{4,}/.test(label)) same.push(`${group}.${id}`);
      }
    expect(same).toEqual([]);
  });

  it("falls back to the API's English label when there is no table for the language (English UI)", () => {
    const tr = createTranslator("en", { pl: pl as Dictionary }, en.enums, () => undefined);
    expect(tr.tEnum("roiSpec", "markets", "Number of markets")).toBe("Number of markets");
    expect(createTranslator("pl", { pl: pl as Dictionary }, en.enums, () => undefined).tEnum("roiSpec", "markets", "Number of markets")).toBe("Liczba rynków");
  });
});
