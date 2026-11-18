/** Polish (pl) dictionary — assembled from the per-area files in ./pl/. See GLOSSARY.md for the terminology and README.md for the conventions. */
import type { Dictionary } from "./core";
import { messages as shell } from "./pl/messages-shell";
import { messages as brand } from "./pl/messages-brand";
import { messages as pipeline } from "./pl/messages-pipeline";
import { messages as governance } from "./pl/messages-governance";
import { messages as performance } from "./pl/messages-performance";
import { messages as platform } from "./pl/messages-platform";
import { plurals } from "./pl/plurals";
import { enums } from "./pl/enums";
import { features, epics, featureSummaries } from "./pl/features";
import { roiEnums } from "./pl/roi";
import { backendEnums, backendMessages } from "./pl/backend";
import { motionEnums, motionMessages, motionPlurals } from "./pl/motion";

/** Group-by-group merge: ids of ./pl/backend.ts are added to (and win over) the same group of the per-area files. */
const mergeGroups = (base: Dictionary["enums"], extra: Dictionary["enums"]): Dictionary["enums"] => {
  const out = { ...base };
  for (const [group, table] of Object.entries(extra)) out[group] = { ...out[group], ...table };
  return out;
};

export const pl: Dictionary = {
  messages: { ...shell, ...brand, ...pipeline, ...governance, ...performance, ...platform, ...backendMessages, ...motionMessages },
  plurals: { ...plurals, ...motionPlurals },
  enums: mergeGroups(mergeGroups({ ...enums, feature: features, featureSummary: featureSummaries, epic: epics, ...roiEnums }, backendEnums), motionEnums),
};
