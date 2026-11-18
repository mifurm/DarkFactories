import { Route, Shuffle } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Dot, ErrorBox, PageHeader, Slider, Spinner, Stat, Tabs, cx, inputCls, sentimentTone } from '../../lib/ui'

interface Decision { queue: string; queue_name: string; priority: number; required_skills: string[]; language: string; sla_s: number; rule: string; reasons: string[]; distribution: string }
interface Qs { queues: { id: string; name: string; sla_s: number; skills: string[]; distribution: string; waiting: number }[]; rules: { id: string; when: string; queue: string; base: number; skills: string[] }[]; semantics: string }
interface Worker { id: string; name: string; skills: string[]; languages: string[]; presence: string; active: string[]; capacity: { voice: number; chat: number } }
interface Analysis { intent: string; sentiment: number; emotion: string; urgency: string; risk_flags: string[]; language: string; entities: Record<string, unknown>; confidence: number; source: string }
interface Sim { timeline: { text: string; intent: string; sentiment: number; emotion: string; risk_flags: string[]; fired: { code: string; reason: string; severity: string }[] }[]; fired_once: string[] }
interface Lab { macro_f1: number; accuracy: number; n: number; misses: { text: string; expected: string; got: string }[]; per_intent: Record<string, { precision: number; recall: number; f1: number; support: number }> }

const INTENTS = ['order_status', 'damaged_item', 'return_request', 'refund_status', 'delivery_change', 'installation_info', 'address_change', 'warranty_claim', 'billing_question', 'complaint', 'goodwill_request', 'cancel_order', 'other']
const RISKS = ['legal_threat', 'fraud_suspected', 'safety_issue', 'vulnerable_customer', 'regulatory_complaint']
/** Customer-typed sample messages (not UI text): the demo conversation in the UI language. */
const SAMPLE_TEXT = { en: 'Mein Sofa ist beschädigt angekommen, bitte um Rückerstattung.', pl: 'Moja sofa dotarła uszkodzona, proszę o zwrot środków.' }
const DEMO_TURNS = {
  en: ['My sofa is damaged and I am quite upset.', 'This is the third time I contact you about this!', 'I will contact my lawyer if nobody fixes this today.', 'Let me speak to a manager.'],
  pl: ['Moja sofa jest uszkodzona i jestem bardzo zdenerwowany.', 'To już trzeci raz, kiedy kontaktuję się w tej sprawie!', 'Jeśli nikt tego dziś nie naprawi, zwrócę się do prawnika.', 'Proszę połączyć mnie z kierownikiem.'],
}

export default function RoutingPage() {
  const { t } = useI18n()
  const [tab, setTab] = useState('playground')
  return (
    <div>
      <PageHeader icon={Route} title={t('Routing & escalation')} subtitle={t('Provider-neutral, in-process skills-based routing with Job-Router-style semantics (queues, classification policy, distribution policy, exception policy) — no dependency on a retiring service — and explicit, configurable escalation triggers that fire once.')} />
      <Tabs tabs={[{ id: 'playground', label: t('Routing playground') }, { id: 'triggers', label: t('Escalation triggers') }, { id: 'config', label: t('Queues, rules & agents') }, { id: 'eval', label: t('Classifier evaluation') }]} value={tab} onChange={setTab} />
      {tab === 'playground' && <Playground />}
      {tab === 'triggers' && <Triggers />}
      {tab === 'config' && <ConfigTab />}
      {tab === 'eval' && <EvalTab />}
    </div>
  )
}

function Playground() {
  const { t, te, tl, ts, fmt, lang } = useI18n()
  const [text, setText] = useState(SAMPLE_TEXT[lang])
  const [ana, setAna] = useState<Analysis | null>(null)
  const [intent, setIntent] = useState('damaged_item')
  const [risks, setRisks] = useState<string[]>([])
  const [vip, setVip] = useState(false)
  const [vul, setVul] = useState(false)
  const [sent, setSent] = useState(-0.2)
  const [dec, setDec] = useState<Decision | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const guard = async (fn: () => Promise<void>) => {
    setErr(null)
    try {
      await fn()
    } catch (e) {
      setErr(describeError(e))
    }
  }
  const analyze = () => guard(async () => {
    const a = await api<Analysis>('/api/routing/analyze', { body: { text } })
    setAna(a)
    setIntent(a.intent)
    setRisks(a.risk_flags)
    setSent(a.sentiment)
  })
  const route = () => guard(async () => setDec(await api<Decision>('/api/routing/route', { body: { intent, risk_flags: risks, sentiment: sent, vip, vulnerable: vul, language: ana?.language ?? lang } })))
  return (
    <div className="space-y-3">
      {err && <p role="alert" className="text-sm text-rose-700">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('1 · Understand the message')} subtitle={t('intent, sentiment, emotion, risk flags, language (rules + LLM in Azure mode)')}>
          <textarea aria-label={t('Customer message')} rows={3} value={text} onChange={(e) => setText(e.target.value)} className={inputCls} />
          <Button className="mt-2" variant="primary" onClick={analyze}>{t('Analyse')}</Button>
          {ana && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Badge tone="blue">{te('intent', ana.intent)}</Badge>
              <Badge tone="slate">{ana.language.toUpperCase()}</Badge>
              <Badge tone={sentimentTone(ana.sentiment)}>{te('emotion', ana.emotion)} {fmt.fixed(ana.sentiment, 2)}</Badge>
              <Badge tone="slate">{t('urgency {urgency}', { urgency: te('urgency', ana.urgency) })}</Badge>
              {ana.risk_flags.map((r) => <Badge key={r} tone="red">{te('risk', r)}</Badge>)}
            </div>
          )}
        </Card>
        <Card title={t('2 · Route the job')} subtitle={t('adjust the inputs and see the queue, priority, skills and the rule that matched')}>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs font-medium text-slate-600">{t('Intent')}<select value={intent} onChange={(e) => setIntent(e.target.value)} className={cx(inputCls, 'mt-1')}>{INTENTS.map((i) => <option key={i} value={i}>{te('intent', i)}</option>)}</select></label>
            <Slider label={t('Sentiment')} value={sent} min={-1} max={1} step={0.05} onChange={setSent} format={(v) => fmt.plain(v)} />
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-sm">
            {RISKS.map((r) => <label key={r} className="flex items-center gap-1.5"><input type="checkbox" checked={risks.includes(r)} onChange={(e) => setRisks(e.target.checked ? [...risks, r] : risks.filter((x) => x !== r))} className="accent-rose-600" />{te('trigger', r)}</label>)}
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={vip} onChange={(e) => setVip(e.target.checked)} className="accent-violet-600" />VIP</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={vul} onChange={(e) => setVul(e.target.checked)} className="accent-amber-600" />{t('vulnerable')}</label>
          </div>
          <Button className="mt-3" variant="primary" icon={Shuffle} onClick={route}>{t('Route')}</Button>
          {dec && (
            <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="blue">{tl('queue', dec.queue, dec.queue_name)}</Badge>
                <Badge tone="amber">{t('priority {n}', { n: dec.priority })}</Badge>
                <Badge tone="slate">{t('SLA {sla}', { sla: fmt.secs(dec.sla_s) })}</Badge>
                <Badge tone="violet">{dec.rule}</Badge>
                <Badge tone="slate">{te('distribution', dec.distribution)}</Badge>
              </div>
              <p className="mt-2 text-xs text-slate-600">{t('needs skills: {skills} · language {language}', { skills: dec.required_skills.map((s) => te('skill', s)).join(', '), language: fmt.languageName(dec.language, dec.language) })}</p>
              <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">{dec.reasons.map((r, i) => <li key={i}>{ts(r)}</li>)}</ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function Triggers() {
  const { t, te, fmt, lang } = useI18n()
  const [turns, setTurns] = useState(() => DEMO_TURNS[lang].join('\n'))
  const [res, setRes] = useState<Sim | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setErr(null)
    try {
      setRes(await api<Sim>('/api/routing/triggers/simulate', { body: { turns: turns.split('\n').filter(Boolean), language: lang } }))
    } catch (e) {
      setErr(describeError(e))
    }
  }
  return (
    <Card title={t('Replay a transcript turn by turn')} subtitle={t('each trigger (legal threat, fraud, safety, vulnerable, explicit request, sentiment, loop, tool failure, knowledge gap …) fires exactly once')}>
      <textarea aria-label={t('Customer turns, one per line')} rows={5} value={turns} onChange={(e) => setTurns(e.target.value)} className={inputCls} />
      <Button className="mt-2" variant="primary" onClick={run}>{t('Simulate')}</Button>
      {err && <p role="alert" className="mt-2 text-sm text-rose-700">{err}</p>}
      {res && (
        <ol className="mt-3 space-y-2">
          {res.timeline.map((x, i) => (
            <li key={i} className="rounded-xl border border-slate-200 p-2.5 text-sm">
              <div data-user-content className="text-slate-800">“{x.text}”</div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                <Badge tone="blue">{te('intent', x.intent)}</Badge>
                <Badge tone={sentimentTone(x.sentiment)}>{te('emotion', x.emotion)} {fmt.fixed(x.sentiment, 2)}</Badge>
                {x.risk_flags.map((r) => <Badge key={r} tone="red">{te('risk', r)}</Badge>)}
                {x.fired.map((f) => <Badge key={f.code} tone="violet">⚡ {te('trigger', f.code)}</Badge>)}
              </div>
            </li>
          ))}
          <li className="text-sm text-slate-600">{t('Fired once: {triggers}', { triggers: res.fired_once.map((c) => te('trigger', c)).join(', ') || t('none') })}</li>
        </ol>
      )}
    </Card>
  )
}

function ConfigTab() {
  const { t, te, tl, ts, fmt } = useI18n()
  const qs = useApi<Qs>('/api/routing/queues', { refreshMs: 10000 })
  const ws = useApi<Worker[]>('/api/routing/workers', { refreshMs: 10000 })
  if (qs.loading && !qs.data) return <Spinner />
  if (qs.error || !qs.data) return <ErrorBox error={qs.error} />
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">{ts(qs.data.semantics)}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('Queues')} pad={false}>
          <DataTable dense rows={qs.data.queues} rowKey={(q) => q.id} cols={[
            { key: 'n', header: t('Queue'), render: (q) => <b>{tl('queue', q.id, q.name)}</b> },
            { key: 's', header: t('SLA'), align: 'right', render: (q) => fmt.secs(q.sla_s) },
            { key: 'k', header: t('Skills'), render: (q) => q.skills.map((s) => te('skill', s)).join(', ') },
            { key: 'd', header: t('Distribution'), render: (q) => <span className="text-xs">{te('distribution', q.distribution)}</span> },
            { key: 'w', header: t('Waiting'), align: 'right', render: (q) => q.waiting },
          ]} />
        </Card>
        <Card title={t('Classification rules (priority order)')} pad={false}>
          <DataTable dense rows={qs.data.rules} rowKey={(r) => r.id} cols={[
            { key: 'i', header: t('Rule'), render: (r) => <Badge tone="violet">{r.id}</Badge> },
            { key: 'w', header: t('When'), render: (r) => <span className="text-xs">{ts(r.when)}</span> },
            { key: 'q', header: t('Queue'), render: (r) => te('queue', r.queue) },
            { key: 'b', header: t('Base'), align: 'right', render: (r) => r.base },
          ]} />
        </Card>
      </div>
      <Card title={t('Human agent roster (simulated)')} subtitle={t('skills, languages, presence and current load')} pad={false}>
        <DataTable dense rows={ws.data ?? []} rowKey={(w) => w.id} cols={[
          { key: 'n', header: t('Agent'), render: (w) => <span className="flex items-center gap-2"><Dot tone={w.presence === 'available' ? 'green' : w.presence === 'busy' ? 'amber' : 'slate'} /><b>{w.name}</b></span> },
          { key: 's', header: t('Skills'), render: (w) => <span className="text-xs">{w.skills.map((s) => te('skill', s)).join(', ')}</span> },
          { key: 'l', header: t('Languages'), render: (w) => w.languages.map((c) => fmt.languageName(c, c)).join(', ') },
          { key: 'a', header: t('Active'), align: 'right', render: (w) => `${w.active.length}/${w.capacity.chat}` },
        ]} />
      </Card>
    </div>
  )
}

function EvalTab() {
  const { t, tn, te, fmt } = useI18n()
  const lab = useApi<Lab>('/api/routing/labelled-eval')
  const d = lab.data
  if (lab.loading && !d) return <Spinner />
  if (lab.error || !d) return <ErrorBox error={lab.error} />
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label={t('Intent macro-F1')} value={fmt.plain(d.macro_f1)} tone="green" hint={t('target ≥ 0.85 · {count}, 8 languages', { count: tn(d.n, { one: '{n} labelled utterance', other: '{n} labelled utterances' }) })} />
        <Stat label={t('Accuracy')} value={fmt.percent(d.accuracy, 1)} />
        <Stat label={t('Misses')} value={d.misses.length} />
      </div>
      <Card title={t('Per-intent precision / recall')} pad={false}>
        <DataTable dense rows={Object.entries(d.per_intent).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[
          { key: 'k', header: t('Intent'), render: (r) => <b>{te('intent', r.k)}</b> },
          { key: 'p', header: t('Precision'), align: 'right', render: (r) => fmt.plain(r.precision) },
          { key: 'r', header: t('Recall'), align: 'right', render: (r) => fmt.plain(r.recall) },
          { key: 'f', header: 'F1', align: 'right', render: (r) => fmt.plain(r.f1) },
          { key: 's', header: t('Samples'), align: 'right', render: (r) => r.support },
        ]} />
      </Card>
      {d.misses.length > 0 && (
        <Card title={t('Misclassified')}>
          <ul className="space-y-1 text-sm">{d.misses.map((m, i) => <li key={i}><span data-user-content>“{m.text}”</span> → <Badge tone="red">{te('intent', m.got)}</Badge> {t('expected')} <Badge tone="green">{te('intent', m.expected)}</Badge></li>)}</ul>
        </Card>
      )}
    </div>
  )
}
