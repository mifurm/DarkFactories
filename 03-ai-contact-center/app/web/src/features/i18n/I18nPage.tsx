import { Download, Languages, Search } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, ErrorBox, Field, PageHeader, Spinner, Stat, Tabs, inputCls } from '../../lib/ui'

interface Lang { code: string; name: string; native: string; rtl: boolean; speech_locale: string; tier: string }
interface Langs { languages: Lang[]; total: number; evaluated: string[]; coverage_statement: string }
interface EvalRes { n: number; detection_accuracy: number; intent_accuracy: number; per_language: Record<string, { n: number; detection_accuracy: number; intent_accuracy: number }>; provider: string; failures: { lang: string; text: string; detected: string; intent: string; intent_expected: string }[]; targets: { detection: number; intent: number } }
interface RoundTrip { n: number; avg_overlap: number; provider: string | null; note: string; rows: { lang: string; original: string; english: string; back: string; overlap: number }[] }
interface Detect { language: string; confidence: number; name: string; tier: string; provider: string }
interface Tr { text: string; source: string; target: string; provider: string; cached?: boolean }

const SAMPLES = ['Mein Sofa ist beschädigt angekommen.', 'Ho bisogno di cambiare l’indirizzo di consegna.', 'Moja pralka przestała działać.', 'Quero devolver o armário.', 'Mijn levering is te laat.', 'Ma commande est arrivée incomplète.']

export default function I18nPage() {
  const [tab, setTab] = useState('try')
  return (
    <div>
      <PageHeader icon={Languages} title="Multilingual & accessibility" subtitle="Per-utterance language detection, translation for human agents, 45 languages with an honest coverage statement (eight Contoso markets are evaluated), downloadable transcripts and WebVTT captions." />
      <Tabs tabs={[{ id: 'try', label: 'Detect & translate' }, { id: 'eval', label: 'Evaluation' }, { id: 'catalogue', label: 'Language catalogue' }]} value={tab} onChange={setTab} />
      {tab === 'try' && <TryTab />}
      {tab === 'eval' && <EvalTab />}
      {tab === 'catalogue' && <Catalogue />}
    </div>
  )
}

function TryTab() {
  const [text, setText] = useState(SAMPLES[0])
  const [target, setTarget] = useState('en')
  const [det, setDet] = useState<Detect | null>(null)
  const [tr, setTr] = useState<Tr | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [conv, setConv] = useState('')
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const d = await api<Detect>('/api/i18n/detect', { body: { text } })
      setDet(d)
      setTr(await api<Tr>('/api/i18n/translate', { body: { text, target, source: d.language } }))
    } catch (e) { setErr(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } finally { setBusy(false) }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Detect & translate" subtitle="what the human-agent console does with each customer message">
        <Field label="Customer message"><textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className={inputCls} /></Field>
        <div className="mt-2 flex flex-wrap gap-1">{SAMPLES.map((s) => <button key={s} type="button" onClick={() => setText(s)} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-200">{s.slice(0, 28)}…</button>)}</div>
        <div className="mt-3 flex items-end gap-2"><Field label="Translate to"><select value={target} onChange={(e) => setTarget(e.target.value)} className={inputCls}>{['en', 'de', 'fr', 'es', 'it', 'nl', 'pl', 'pt'].map((l) => <option key={l} value={l}>{l}</option>)}</select></Field><Button variant="primary" icon={Search} busy={busy} onClick={run}>Detect & translate</Button></div>
        {err && <p role="alert" className="mt-2 text-sm text-rose-700">{err}</p>}
        {det && <div className="mt-4 space-y-2 text-sm"><p><Badge tone="blue">{det.name} ({det.language})</Badge> <span className="text-xs text-slate-500">confidence {(det.confidence * 100).toFixed(0)}% · {det.tier} · via {det.provider}</span></p>{tr && <p className="rounded-xl bg-emerald-50 p-3 text-slate-800 ring-1 ring-emerald-200">{tr.text}<span className="ml-2 text-[11px] text-slate-500">via {tr.provider}</span></p>}</div>}
      </Card>
      <Card title="Transcripts & captions" subtitle="download the transcript of any conversation (chat or voice) as text, JSON or WebVTT captions">
        <Field label="Conversation id" hint="e.g. open the widget, then copy the id from the URL (?c=…)"><input value={conv} onChange={(e) => setConv(e.target.value.trim())} placeholder="cv_…" className={inputCls} /></Field>
        <div className="mt-3 flex gap-2">{['txt', 'json', 'vtt'].map((f) => <a key={f} aria-disabled={!conv} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium ring-1 ring-slate-300 ${conv ? 'bg-white text-slate-800 hover:bg-slate-50' : 'pointer-events-none bg-slate-100 text-slate-400'}`} href={`/api/i18n/transcript/${conv}?format=${f}`} download><Download size={14} aria-hidden />{f.toUpperCase()}</a>)}</div>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-600"><li>Live captions: the voice page renders both transcripts in real time, in the caller's language.</li><li>Keyboard-only chat, visible focus, ARIA live region for new messages, reduced-motion and high-contrast support in the widget.</li><li>Right-to-left languages are catalogued; only the eight evaluated languages are claimed as supported.</li></ul>
      </Card>
    </div>
  )
}

function EvalTab() {
  const [ev, setEv] = useState<EvalRes | null>(null)
  const [rt, setRt] = useState<RoundTrip | null>(null)
  const [busy, setBusy] = useState('')
  const run = async (k: 'ev' | 'rt') => { setBusy(k); try { if (k === 'ev') setEv(await api<EvalRes>('/api/i18n/eval')); else setRt(await api<RoundTrip>('/api/i18n/eval/round-trip', { method: 'POST' })) } finally { setBusy('') } }
  return (
    <div className="space-y-4">
      <Card title="Detection & intent accuracy per language" subtitle={`${ev ? ev.n : 64} short opening messages across the eight Contoso markets · targets: detection ≥ 95%, intent ≥ 85%`} actions={<Button variant="primary" busy={busy === 'ev'} onClick={() => run('ev')}>Run evaluation</Button>}>
        {!ev ? <p className="text-sm text-slate-500">Run the evaluation to measure language detection (Azure AI Language in Azure mode) and intent understanding per language.</p> : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3"><Stat label="Detection accuracy" value={fmt.pct(ev.detection_accuracy)} tone={ev.detection_accuracy >= ev.targets.detection ? 'green' : 'amber'} /><Stat label="Intent accuracy" value={fmt.pct(ev.intent_accuracy)} tone={ev.intent_accuracy >= ev.targets.intent ? 'green' : 'amber'} /><Stat label="Provider" value={ev.provider} /></div>
            <DataTable dense rows={Object.entries(ev.per_language).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[{ key: 'k', header: 'Language', render: (r) => <b>{r.k}</b> }, { key: 'n', header: 'Samples', align: 'right', render: (r) => r.n }, { key: 'd', header: 'Detection', align: 'right', render: (r) => fmt.pct(r.detection_accuracy, 0) }, { key: 'i', header: 'Intent', align: 'right', render: (r) => fmt.pct(r.intent_accuracy, 0) }]} />
            {!!ev.failures.length && <details className="text-xs"><summary className="cursor-pointer font-medium text-slate-700">{ev.failures.length} misses</summary><ul className="mt-1 space-y-1">{ev.failures.map((f, i) => <li key={i} className="text-slate-600">[{f.lang}→{f.detected}] {f.text} — intent {f.intent} (expected {f.intent_expected})</li>)}</ul></details>}
          </div>
        )}
      </Card>
      <Card title="Translation round-trip" subtitle="customer language → English → customer language; token overlap proxies meaning preservation" actions={<Button busy={busy === 'rt'} onClick={() => run('rt')}>Run round-trip</Button>}>
        {!rt ? <p className="text-sm text-slate-500">Not run yet.</p> : (
          <div className="space-y-2"><p className="text-sm">Average overlap <b>{rt.avg_overlap}</b> over {rt.n} sentences via {rt.provider}. <span className="text-xs text-slate-500">{rt.note}</span></p>
            <DataTable dense rows={rt.rows} rowKey={(r) => `${r.lang}-${r.original}`} cols={[{ key: 'l', header: 'Lang', render: (r) => r.lang }, { key: 'o', header: 'Original', render: (r) => <span className="text-xs">{r.original}</span> }, { key: 'e', header: 'English', render: (r) => <span className="text-xs">{r.english}</span> }, { key: 'b', header: 'Back', render: (r) => <span className="text-xs">{r.back}</span> }, { key: 's', header: 'Overlap', align: 'right', render: (r) => r.overlap }]} /></div>
        )}
      </Card>
    </div>
  )
}

function Catalogue() {
  const l = useApi<Langs>('/api/i18n/languages')
  if (l.loading && !l.data) return <Spinner />
  if (l.error || !l.data) return <ErrorBox error={l.error} />
  return (
    <div className="space-y-4">
      <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">{l.data.coverage_statement}</p>
      <Card title={`${l.data.total} languages`} pad={false}><DataTable dense rows={l.data.languages} rowKey={(r) => r.code} cols={[{ key: 'c', header: 'Code', render: (r) => <span className="font-mono text-xs">{r.code}</span> }, { key: 'n', header: 'Language', render: (r) => r.name }, { key: 'x', header: 'Native', render: (r) => <span dir={r.rtl ? 'rtl' : 'ltr'}>{r.native}</span> }, { key: 's', header: 'Speech locale', render: (r) => <span className="font-mono text-xs">{r.speech_locale}</span> }, { key: 't', header: 'Support', render: (r) => <Badge tone={r.tier === 'evaluated' ? 'green' : 'slate'}>{r.tier}</Badge> }]} /></Card>
    </div>
  )
}
