import type { EnumTable } from "../core";

/**
 * Polish labels for values that a real (azure-mode) backend returns and the offline stubs never do — adapter ids, cost features, job steps, voices, asset tags —
 * plus the few messages that go with them. It lives in its own file so it never collides with the wording edits in the per-area files; ../pl.ts merges it group
 * by group (an id defined here wins over the same id there). `../backend-enums.json` lists the backend values; backend-enums.test.ts keeps both in sync.
 */
export const backendEnums: Record<string, EnumTable> = {
  // /readyz and /api/ops/status: the adapter that answered (product names, not translated)
  backend: {
    "azure-blob": "Azure Blob Storage",
    "azure-openai": "Azure OpenAI",
    "azure-content-safety": "Azure AI Content Safety",
    "azure-speech": "Azure AI Speech",
  },
  providerKind: { "generative video (stub)": "wideo generatywne (atrapa)" },
  // the studio's catalogue knows more territories and channels than the demo data uses (message catalog label.territory / label.channel)
  territory: { PT: "PT", CA: "CA", MX: "MX", EEA: "EOG" },
  channel: { ooh: "OOH", web: "web" },
  textKind: { legal: "tekst prawny", dialogue: "dialog" },
  // the cost meter groups spend by the feature that caused it: a campaign sub-resource (request path) or CS-xx (jobs, shown through the feature names)
  costFeature: {
    strategy: "strategia",
    script: "scenariusz",
    storyboard: "storyboard",
    audio: "lektor i audio",
    spot: "spot",
    formats: "formaty",
    localization: "lokalizacja",
    copy: "teksty",
  },
  jobStep: { build: "Budowanie pakietu" },
  // price table rows: "TTS neural" / "TTS tts-hd"
  ttsTier: { neural: "neuronowy" },
  // tags the studio puts on the assets it creates (user tags, aspect ratios and language codes stay as they are)
  assetTag: {
    "ai-generated": "wygenerowane przez AI",
    "campaign-pack": "pakiet kampanii",
    "voice-over": "lektor",
    captions: "napisy",
    poster: "miniatura",
    export: "eksport",
    storyboard: "storyboard",
    spot: "spot",
    master: "master",
    format: "format",
    cutdown: "wersja skrócona",
    localized: "zlokalizowana",
    hook: "hook",
    product: "produkt",
    proof: "dowód",
    brand: "marka",
    cta: "CTA",
    upload: "wgrane",
  },
};

export const backendMessages: Record<string, string> = {
  // Recharts draws every legend swatch as <svg aria-label="{series} legend icon">: the label is localized after rendering (components/common.tsx)
  "{name} legend icon": "ikona legendy: {name}",
  "{name} ({lang}, neural voice)": "{name} ({lang}, głos neuronowy)",
  // the voice catalogue's English names; the current server already sends them in Polish (identical wording), an older one still sends these
  "Nova — warm, friendly": "Nova — ciepły, przyjazny",
  "Shimmer — bright, upbeat": "Shimmer — jasny, pogodny",
  "Alloy — neutral, clear": "Alloy — neutralny, wyraźny",
  "Fable — expressive storyteller": "Fable — wyrazisty gawędziarz",
  "Echo — calm, composed": "Echo — spokojny, opanowany",
  "Onyx — deep, authoritative": "Onyx — głęboki, autorytatywny",
};
