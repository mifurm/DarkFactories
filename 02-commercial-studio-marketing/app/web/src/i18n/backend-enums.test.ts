import { describe, expect, it } from "vitest";
import { createTranslator, type Dictionary } from "./core";
import { en } from "./en";
import { pl } from "./pl";
import { stepLabel } from "../components/jobSteps";
import data from "./backend-enums.json";

/**
 * Keeps the UI's Polish dictionary in step with what the BACKEND can return (backend-enums.json, generated from the backend sources by
 * `npm run export:backend-enums`, plus a hand-kept `observed` section for values only a deployed azure-mode instance shows).
 * An enum group rendered with tOpen() never reports a missing key — an id the dictionary does not know simply shows up raw (an English identifier in a
 * Polish page) — so this test is what catches a new backend value: add its label to src/i18n/pl/backend.ts (and to en.ts when the group has an English table).
 */
type Section = "catalog" | "code" | "observed";
interface Check {
  from: [Section, string];
  /** every id must be defined in ALL of these groups … */
  groups?: string[];
  /** … or in at least ONE of these */
  anyOf?: string[];
  /** ids handled by code instead of a dictionary entry (patterns, generic composition) */
  skip?: RegExp;
}

const CHECKS: Check[] = [
  { from: ["catalog", "audit"], groups: ["auditAction"] },
  { from: ["catalog", "label.check"], groups: ["guardianCheck"] },
  { from: ["catalog", "label.gate"], groups: ["gate"] },
  { from: ["catalog", "label.role"], groups: ["role", "roleId", "roleChip"] },
  { from: ["catalog", "label.pack"], groups: ["rulePack"] },
  { from: ["catalog", "label.territory"], groups: ["territory"] },
  { from: ["catalog", "label.channel"], groups: ["channel"] },
  { from: ["catalog", "label.rkind"], groups: ["rightsKind"] },
  { from: ["catalog", "label.tone"], groups: ["tone"] },
  { from: ["catalog", "label.beat"], groups: ["beatRole"] },
  { from: ["catalog", "label.verdict"], groups: ["verdict"] },
  { from: ["catalog", "label.call"], groups: ["costKind"] },
  { from: ["catalog", "label.claim_type"], groups: ["status"] },
  { from: ["catalog", "label.state"], groups: ["status"] },
  { from: ["catalog", "label.status"], groups: ["status"] },
  { from: ["catalog", "label.kind"], anyOf: ["textKind", "artifactKind", "copyKind"], skip: /^artifact$/ },
  { from: ["code", "backend"], groups: ["backend"] },
  { from: ["code", "jobKind"], groups: ["jobKind"] },
  { from: ["code", "jobStep"], groups: ["jobStep"] },
  { from: ["code", "costKind"], groups: ["costKind"] },
  { from: ["code", "opsDependency"], groups: ["opsDependency"] },
  { from: ["observed", "costFeature"], groups: ["costFeature"], skip: /^CS-\d\d$/ }, // CS-xx: shown through the feature names (cost meter)
  { from: ["observed", "perfSource"], groups: ["perfSource"], skip: /^connector:/ }, // connector:<platform>: composed from the platform label
  { from: ["observed", "providerKind"], groups: ["providerKind"] },
  { from: ["observed", "assetTag"], groups: ["assetTag"] },
];

const values = (section: Section, key: string): string[] => ((data as unknown as Record<string, Record<string, string[]> | undefined>)[section]?.[key] ?? []) as string[];

describe("backend enum values have Polish labels", () => {
  for (const check of CHECKS) {
    const [section, key] = check.from;
    it(`${section}.${key} → ${(check.groups ?? check.anyOf ?? []).join(" / ")}`, () => {
      const ids = values(section, key).filter((id) => !check.skip?.test(id));
      expect(ids.length, `no values for ${section}.${key}: run npm run export:backend-enums`).toBeGreaterThan(0);
      const problems: string[] = [];
      for (const id of ids) {
        if (check.groups) for (const g of check.groups) if (pl.enums[g]?.[id] === undefined) problems.push(`pl.enums.${g} lacks "${id}"`);
        if (check.anyOf && !check.anyOf.some((g) => pl.enums[g]?.[id] !== undefined)) problems.push(`none of ${check.anyOf.join(", ")} has "${id}"`);
      }
      expect(problems).toEqual([]);
    });
  }

  it("groups that have an English table list the same backend ids in English", () => {
    const enEnums = en.enums as unknown as Record<string, Record<string, string> | undefined>; // `en.enums` is typed by its literal keys; the test walks it by group name
    const problems: string[] = [];
    for (const check of CHECKS) {
      const [section, key] = check.from;
      for (const g of check.groups ?? []) {
        const table = enEnums[g];
        if (!table) continue;
        for (const id of values(section, key).filter((i) => !check.skip?.test(i))) if (table[id] === undefined) problems.push(`en.enums.${g} lacks "${id}"`);
      }
    }
    expect(problems).toEqual([]);
  });

  it("every OpenAI voice name the catalogue can send has a Polish translation", () => {
    const names: Record<string, string> = {
      "openai:nova": "Nova — warm, friendly",
      "openai:shimmer": "Shimmer — bright, upbeat",
      "openai:alloy": "Alloy — neutral, clear",
      "openai:fable": "Fable — expressive storyteller",
      "openai:echo": "Echo — calm, composed",
      "openai:onyx": "Onyx — deep, authoritative",
    };
    expect(values("code", "openaiVoice").sort()).toEqual(Object.keys(names).sort());
    const tr = createTranslator("pl", { pl: pl as Dictionary }, en.enums, () => undefined);
    for (const name of Object.values(names)) expect(tr.tKnown(name), name).not.toBe(name);
  });
});

describe("job steps", () => {
  const trPl = createTranslator("pl", { pl: pl as Dictionary }, en.enums, () => undefined);
  const trEn = createTranslator("en", { pl: pl as Dictionary }, en.enums, () => undefined);

  it("every step prefix the backend builds with an f-string is rendered by stepLabel", () => {
    const sample = (prefix: string) => (prefix.endsWith("-") ? `${prefix}${/^(line|frame|guardian)-$/.test(prefix) ? "3" : "pl"}` : prefix);
    const raw = values("code", "jobStepPrefix").map(sample).filter((name) => stepLabel(trPl, name) === name);
    expect(raw, "step ids shown raw in the Polish UI").toEqual([]);
  });

  it("the steps seen on a deployed instance (cutdowns, frames, per-language steps) are localized; English keeps the raw id", () => {
    for (const name of values("observed", "jobStepSample")) {
      expect(stepLabel(trPl, name), name).not.toBe(name);
      expect(stepLabel(trEn, name)).toBe(name);
    }
  });
});
