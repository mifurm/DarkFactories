import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { I18nProvider, initLang } from './i18n'
import './styles.css'

initLang() // ?lang= -> saved choice -> navigator.languages -> en; sets <html lang> before the first paint

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
)
