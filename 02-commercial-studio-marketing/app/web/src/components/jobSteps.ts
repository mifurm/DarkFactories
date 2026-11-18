import type { Translator } from "../i18n/core";

/**
 * Step ids a background job reports (`render`, `line-3`, `render-pl`, `6s cutdown` …) as readable pills. English keeps the raw id (historical UI).
 * Pure function so the unit test can run it on every step the backend can emit (backend-enums.json).
 */
export function stepLabel(i18n: Pick<Translator, "lang" | "hasEnum" | "tEnum" | "t">, name: string): string {
  if (i18n.lang === "en") return name;
  if (i18n.hasEnum("jobStep", name)) return i18n.tEnum("jobStep", name);
  let m: RegExpMatchArray | null;
  if ((m = name.match(/^(\d+)s cutdown$/))) return i18n.t("{n}s cutdown", { n: m[1] });
  if ((m = name.match(/^line-(\d+)$/))) return i18n.t("Line {n}", { n: m[1] });
  if ((m = name.match(/^frame-s?(\d+)$/))) return i18n.t("Keyframe {n}", { n: m[1] });
  if ((m = name.match(/^guardian-(\d+)$/))) return i18n.t("Guardian · {n} s", { n: m[1] });
  if ((m = name.match(/^transcreate-([a-z]{2})$/))) return i18n.t("Transcreation · {lang}", { lang: m[1].toUpperCase() });
  if ((m = name.match(/^backtranslate-([a-z]{2})$/))) return i18n.t("Back-translation · {lang}", { lang: m[1].toUpperCase() });
  if ((m = name.match(/^voice-([a-z]{2})$/))) return i18n.t("Voice-over · {lang}", { lang: m[1].toUpperCase() });
  if ((m = name.match(/^render-([a-z]{2})$/))) return i18n.t("Render · {lang}", { lang: m[1].toUpperCase() });
  return name;
}
