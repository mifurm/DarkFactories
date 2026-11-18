import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pl } from "./pl";

/**
 * /api/features stays English; the UI translates the name and the summary of every feature by its id (FeatureMap.tsx: tEnum("feature" | "featureSummary", id)).
 * A feature the backend registers without a Polish entry is reported as a missing key on the Feature map page — so the ids of the backend catalog are checked here.
 */
const REGISTRY = path.resolve(__dirname, "../../../src/spotlight/registry.py");

describe.runIf(fs.existsSync(REGISTRY))("Polish names for every registered feature", () => {
  const ids = [...fs.readFileSync(REGISTRY, "utf8").matchAll(/^\s*\("(CS-\d\d)",/gm)].map((m) => m[1]);

  it("reads the backend catalog", () => {
    expect(ids.length).toBeGreaterThanOrEqual(25);
    expect(ids).toContain("CS-25");
  });

  it("has a Polish name and summary for each id (and none for an unknown one)", () => {
    const names = pl.enums.feature ?? {};
    const summaries = pl.enums.featureSummary ?? {};
    expect(ids.filter((id) => !names[id])).toEqual([]);
    expect(ids.filter((id) => !summaries[id])).toEqual([]);
    expect(Object.keys(names).filter((id) => !ids.includes(id))).toEqual([]);
    expect(Object.keys(summaries).filter((id) => !ids.includes(id))).toEqual([]);
  });

  it("the cinematic-motion feature is described in Polish", () => {
    expect(pl.enums.feature?.["CS-25"]).toBe("Ruch filmowy AI (wideo generatywne)");
    expect(pl.enums.featureSummary?.["CS-25"]).toContain("klatka kluczowa");
    expect(pl.enums.featureSummary?.["CS-08"]).toContain("klipy generowane przez AI");
  });
});
