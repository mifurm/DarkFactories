import { useEffect, useState } from 'react'
import { useI18n, type Lang } from './index'

/** Languages the customer widget and the voice page can hold a conversation in (autonyms). */
export const CONV_LANGS: Record<string, string> = { en: 'English', de: 'Deutsch', fr: 'Français', es: 'Español', it: 'Italiano', nl: 'Nederlands', pl: 'Polski', pt: 'Português' }

const isUi = (l: string): l is Lang => l === 'en' || l === 'pl'

/**
 * The conversation language of the customer pages (?lang= -> UI language). For English and Polish it IS the UI language
 * (choosing one switches the labels everywhere and is remembered); the other six languages only change the conversation language
 * (the widget keeps its own built-in labels for those).
 */
export function useConversationLang(search: URLSearchParams) {
  const { lang: ui, setLang } = useI18n()
  const q = search.get('lang')
  const [conv, setConv] = useState<string>(() => (q && q in CONV_LANGS ? q : ui))
  useEffect(() => {
    // the UI language changed elsewhere (e.g. another tab or the history) -> follow it while on en / pl
    if (isUi(conv) && conv !== ui) setConv(ui)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui])
  const choose = (next: string) => {
    setConv(next)
    if (isUi(next)) setLang(next)
  }
  return { conv, choose }
}
