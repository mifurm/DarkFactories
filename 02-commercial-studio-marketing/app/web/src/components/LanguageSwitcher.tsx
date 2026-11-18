/* eslint-disable @typescript-eslint/no-explicit-any */
import { Languages } from "lucide-react";
import { LANG_META, useI18n, type Lang } from "../i18n";

/** Header control next to the role switcher: EN ⇄ PL without a reload (state + <html lang> + localStorage are handled by setLang). */
export function LanguageSwitcher() {
  const { lang, setLang, langs, t } = useI18n();
  return (
    <label className="flex items-center gap-2 text-[12px] text-espresso-500">
      <Languages className="h-3.5 w-3.5" aria-hidden="true" />
      <span className="sr-only">{t("Language")}</span>
      <select
        aria-label={t("Language")}
        data-testid="lang-switcher"
        value={lang}
        onChange={(e) => setLang(e.target.value as Lang)}
        className="rounded-lg border border-cream-300 bg-white px-2 py-1 text-[12.5px] font-medium text-espresso-800"
      >
        {langs.map((l) => (
          <option key={l} value={l} lang={l}>
            {LANG_META[l].name}
          </option>
        ))}
      </select>
    </label>
  );
}
