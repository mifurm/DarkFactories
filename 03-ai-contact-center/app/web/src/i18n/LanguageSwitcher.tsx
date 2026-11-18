import { Globe } from 'lucide-react'
import { LANGS, LANG_NAMES, useI18n, type Lang } from './index'

/** The UI-language switch of the app header (and Settings). Remembered in localStorage, no reload, refetches data. */
export function LanguageSwitcher({ className = '' }: { className?: string }) {
  const { lang, setLang, t } = useI18n()
  return (
    <label className={`flex items-center gap-1.5 ${className}`}>
      <Globe size={14} aria-hidden className="text-slate-500" />
      <select
        data-testid="ui-lang"
        aria-label={t('Interface language')}
        value={lang}
        onChange={(e) => setLang(e.target.value as Lang)}
        className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-800"
      >
        {LANGS.map((l) => (
          <option key={l} value={l} lang={l}>
            {LANG_NAMES[l]}
          </option>
        ))}
      </select>
    </label>
  )
}
