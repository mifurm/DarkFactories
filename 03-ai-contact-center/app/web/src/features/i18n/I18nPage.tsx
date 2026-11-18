import { Download, Languages, Search } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi, withLang } from '../../lib/api'
import { Badge, Button, Card, DataTable, ErrorBox, Field, PageHeader, Spinner, Stat, Tabs, inputCls } from '../../lib/ui'

interface Lang { code: string; name: string; native: string; rtl: boolean; speech_locale: string; tier: string }
interface Langs { languages: Lang[]; total: number; evaluated: string[]; coverage_statement: string }
interface EvalRes { n: number; detection_accuracy: number; intent_accuracy: number; per_language: Record<string, { n: number; detection_accuracy: number; intent_accuracy: number }>; provider: string; failures: { lang: string; text: string; detected: string; intent: string; intent_expected: string }[]; targets: { detection: number; intent: number } }
interface RoundTrip { n: number; avg_overlap: number; provider: string | null; note: string; rows: { lang: string; original: string; english: string; back: string; overlap: number }[] }
interface Detect { language: string; confidence: number; name: string; tier: string; provider: string }
interface Tr { text: string; source: string; target: string; provider: string; cached?: boolean }

/** Customer messages in their own languages (sample inputs, not UI text); the last one is Polish typed without diacritics, as on a phone. */
const SAMPLES = ['Mein Sofa ist beschädigt angekommen.', 'Ho bisogno di cambiare l’indirizzo di consegna.', 'Moja pralka przestała działać.', 'Quero devolver o armário.', 'Mijn levering is te laat.', 'Ma commande est arrivée incomplète.', 'Kanapa dotarla uszkodzona, prosze o zwrot.']
const TARGETS = ['en', 'de', 'fr', 'es', 'it', 'nl', 'pl', 'pt']

export default function I18nPage() {
  const { t, tn } = useI18n()
  const [tab, setTab] = useState('try')
  const langs = useApi<Langs>('/api/i18n/languages')
  return (
    <div>
      <PageHeader icon={Languages} title={t('Multilingual & accessibility')} subtitle={t('Per-utterance language detection, translation for human agents, {languages} with an honest coverage statement (eight Contoso markets are evaluated), downloadable transcripts and WebVTT captions.', { languages: tn(langs.data?.total ?? 47, { one: '{n} language', other: '{n} languages' }) })} />
      <Tabs tabs={[{ id: 'try', label: t('Detect & translate') }, { id: 'eval', label: t('Evaluation') }, { id: 'catalogue', label: t('Language catalogue') }]} value={tab} onChange={setTab} />
      {tab === 'try' && <TryTab />}
      {tab === 'eval' && <EvalTab />}
      {tab === 'catalogue' && <Catalogue l={langs} />}
    </div>
  )
}

function TryTab() {
  const { t, te, fmt, lang } = useI18n()
  const [text, setText] = useState(() => (lang === 'pl' ? SAMPLES[2] : SAMPLES[0]))
  const [target, setTarget] = useState('en')
  const [det, setDet] = useState<Detect | null>(null)
  const [tr, setTr] = useState<Tr | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [conv, setConv] = useState('')
  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      const d = await api<Detect>('/api/i18n/detect', { body: { text } })
      setDet(d)
      setTr(await api<Tr>('/api/i18n/translate', { body: { text, target, source: d.language } }))
    } catch (e) {
      setErr(describeError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={t('Detect & translate')} subtitle={t('what the human-agent console does with each customer message')}>
        <Field label={t('Customer message')}><textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className={inputCls} /></Field>
        <div className="mt-2 flex flex-wrap gap-1">{SAMPLES.map((s) => <button key={s} type="button" onClick={() => setText(s)} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-200">{s.slice(0, 28)}…</button>)}</div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Field label={t('Translate to')}><select value={target} onChange={(e) => setTarget(e.target.value)} className={inputCls}>{TARGETS.map((l) => <option key={l} value={l}>{fmt.languageName(l, l)}</option>)}</select></Field>
          <Button variant="primary" icon={Search} busy={busy} onClick={run}>{t('Detect & translate')}</Button>
        </div>
        {err && <p role="alert" className="mt-2 text-sm text-rose-700">{err}</p>}
        {det && (
          <div className="mt-4 space-y-2 text-sm">
            <p><Badge tone="blue">{fmt.languageName(det.language, det.name)} ({det.language})</Badge> <span className="text-xs text-slate-500">{t('confidence {pct} · {tier} · via {provider}', { pct: fmt.percent(det.confidence, 0), tier: te('langTier', det.tier), provider: te('i18nProvider', det.provider) })}</span></p>
            {tr && <p className="rounded-xl bg-emerald-50 p-3 text-slate-800 ring-1 ring-emerald-200">{tr.text}<span className="ml-2 text-[11px] text-slate-500">{t('via {provider}', { provider: te('i18nProvider', tr.provider) })}</span></p>}
          </div>
        )}
      </Card>
      <Card title={t('Transcripts & captions')} subtitle={t('download the transcript of any conversation (chat or voice) as text, JSON or WebVTT captions')}>
        <Field label={t('Conversation id')} hint={t('e.g. open the widget, then copy the id from the URL (?c=…)')}><input value={conv} onChange={(e) => setConv(e.target.value.trim())} placeholder="cv_…" className={inputCls} /></Field>
        <div className="mt-3 flex gap-2">{['txt', 'json', 'vtt'].map((f) => <a key={f} aria-disabled={!conv} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium ring-1 ring-slate-300 ${conv ? 'bg-white text-slate-800 hover:bg-slate-50' : 'pointer-events-none bg-slate-100 text-slate-400'}`} href={withLang(`/api/i18n/transcript/${conv}?format=${f}`)} download><Download size={14} aria-hidden />{f.toUpperCase()}</a>)}</div>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-600">
          <li>{t('Live captions: the voice page renders both transcripts in real time, in the caller\'s language.')}</li>
          <li>{t('Keyboard-only chat, visible focus, ARIA live region for new messages, reduced-motion and high-contrast support in the widget.')}</li>
          <li>{t('Right-to-left languages are catalogued; only the eight evaluated languages are claimed as supported.')}</li>
        </ul>
      </Card>
    </div>
  )
}

function EvalTab() {
  const { t, tn, te, ts, rich, fmt } = useI18n()
  const [ev, setEv] = useState<EvalRes | null>(null)
  const [rt, setRt] = useState<RoundTrip | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const run = async (k: 'ev' | 'rt') => {
    setBusy(k)
    setErr(null)
    try {
      if (k === 'ev') setEv(await api<EvalRes>('/api/i18n/eval'))
      else setRt(await api<RoundTrip>('/api/i18n/eval/round-trip', { method: 'POST' }))
    } catch (e) {
      setErr(describeError(e))
    } finally {
      setBusy('')
    }
  }
  return (
    <div className="space-y-4">
      {err && <p role="alert" className="text-sm text-rose-700">{err}</p>}
      <Card title={t('Detection & intent accuracy per language')} subtitle={t('{count} across the eight Contoso markets · targets: detection ≥ 95%, intent ≥ 85%', { count: tn(ev ? ev.n : 64, { one: '{n} short opening message', other: '{n} short opening messages' }) })} actions={<Button variant="primary" busy={busy === 'ev'} onClick={() => run('ev')}>{t('Run evaluation')}</Button>}>
        {!ev ? <p className="text-sm text-slate-500">{t('Run the evaluation to measure language detection (Azure AI Language in Azure mode) and intent understanding per language.')}</p> : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3"><Stat label={t('Detection accuracy')} value={fmt.percent(ev.detection_accuracy)} tone={ev.detection_accuracy >= ev.targets.detection ? 'green' : 'amber'} /><Stat label={t('Intent accuracy')} value={fmt.percent(ev.intent_accuracy)} tone={ev.intent_accuracy >= ev.targets.intent ? 'green' : 'amber'} /><Stat label={t('Provider')} value={te('i18nProvider', ev.provider)} /></div>
            <DataTable dense rows={Object.entries(ev.per_language).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[
              { key: 'k', header: t('Language'), render: (r) => <b>{fmt.languageName(r.k, r.k)}</b> },
              { key: 'n', header: t('Samples'), align: 'right', render: (r) => r.n },
              { key: 'd', header: t('Detection'), align: 'right', render: (r) => fmt.percent(r.detection_accuracy, 0) },
              { key: 'i', header: t('Intent'), align: 'right', render: (r) => fmt.percent(r.intent_accuracy, 0) },
            ]} />
            {!!ev.failures.length && (
              <details className="text-xs">
                <summary className="cursor-pointer font-medium text-slate-700">{tn(ev.failures.length, { one: '{n} miss', other: '{n} misses' })}</summary>
                <ul className="mt-1 space-y-1">{ev.failures.map((f, i) => <li key={i} className="text-slate-600">{t('[{lang}→{detected}] {text} — intent {intent} (expected {expected})', { lang: f.lang, detected: f.detected, text: f.text, intent: te('intent', f.intent), expected: te('intent', f.intent_expected) })}</li>)}</ul>
              </details>
            )}
          </div>
        )}
      </Card>
      <Card title={t('Translation round-trip')} subtitle={t('customer language → English → customer language; token overlap proxies meaning preservation')} actions={<Button busy={busy === 'rt'} onClick={() => run('rt')}>{t('Run round-trip')}</Button>}>
        {!rt ? <p className="text-sm text-slate-500">{t('Not run yet.')}</p> : (
          <div className="space-y-2">
            <p className="text-sm">{rich('Average overlap <b>{overlap}</b> over {sentences} via {provider}.', { overlap: fmt.plain(rt.avg_overlap), sentences: tn(rt.n, { one: '{n} sentence', other: '{n} sentences' }), provider: rt.provider ? te('i18nProvider', rt.provider) : '—' })} <span className="text-xs text-slate-500">{ts(rt.note)}</span></p>
            <DataTable dense rows={rt.rows} rowKey={(r) => `${r.lang}-${r.original}`} cols={[
              { key: 'l', header: t('Lang'), render: (r) => r.lang },
              { key: 'o', header: t('Original'), render: (r) => <span data-user-content className="text-xs">{r.original}</span> },
              { key: 'e', header: t('English'), render: (r) => <span data-user-content className="text-xs">{r.english}</span> },
              { key: 'b', header: t('Back'), render: (r) => <span data-user-content className="text-xs">{r.back}</span> },
              { key: 's', header: t('Overlap'), align: 'right', render: (r) => fmt.plain(r.overlap) },
            ]} />
          </div>
        )}
      </Card>
    </div>
  )
}

function Catalogue({ l }: { l: ReturnType<typeof useApi<Langs>> }) {
  const { tn, te, ts, t, fmt } = useI18n()
  if (l.loading && !l.data) return <Spinner />
  if (l.error || !l.data) return <ErrorBox error={l.error} />
  return (
    <div className="space-y-4">
      <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">{ts(l.data.coverage_statement)}</p>
      <Card title={tn(l.data.total, { one: '{n} language', other: '{n} languages' })} pad={false}>
        <DataTable dense rows={l.data.languages} rowKey={(r) => r.code} cols={[
          { key: 'c', header: t('Code'), render: (r) => <span className="font-mono text-xs">{r.code}</span> },
          { key: 'n', header: t('Language'), render: (r) => fmt.languageName(r.code, r.name) },
          { key: 'x', header: t('Native'), render: (r) => <span dir={r.rtl ? 'rtl' : 'ltr'} lang={r.code}>{r.native}</span> },
          { key: 's', header: t('Speech locale'), render: (r) => <span className="font-mono text-xs">{r.speech_locale}</span> },
          { key: 't', header: t('Support'), render: (r) => <Badge tone={r.tier === 'evaluated' ? 'green' : 'slate'}>{te('langTier', r.tier)}</Badge> },
        ]} />
      </Card>
    </div>
  )
}
