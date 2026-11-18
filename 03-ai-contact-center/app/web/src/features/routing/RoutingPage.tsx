import { Route, Shuffle } from 'lucide-react'
import { useState } from 'react'
import { api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Dot, ErrorBox, PageHeader, Slider, Spinner, Stat, Tabs, cx, inputCls, sentimentTone } from '../../lib/ui'

interface Decision { queue: string; queue_name: string; priority: number; required_skills: string[]; language: string; sla_s: number; rule: string; reasons: string[]; distribution: string }
interface Qs { queues: { id: string; name: string; sla_s: number; skills: string[]; distribution: string; waiting: number }[]; rules: { id: string; when: string; queue: string; base: number; skills: string[] }[]; semantics: string }
interface Worker { id: string; name: string; skills: string[]; languages: string[]; presence: string; active: string[]; capacity: { voice: number; chat: number } }
interface Analysis { intent: string; sentiment: number; emotion: string; urgency: string; risk_flags: string[]; language: string; entities: Record<string, unknown>; confidence: number; source: string }
interface Sim { timeline: { text: string; intent: string; sentiment: number; emotion: string; risk_flags: string[]; fired: { code: string; reason: string; severity: string }[] }[]; fired_once: string[] }
interface Lab { macro_f1: number; accuracy: number; n: number; misses: { text: string; expected: string; got: string }[]; per_intent: Record<string, { precision: number; recall: number; f1: number; support: number }> }

const INTENTS = ['order_status', 'damaged_item', 'return_request', 'refund_status', 'delivery_change', 'installation_info', 'address_change', 'warranty_claim', 'billing_question', 'complaint', 'goodwill_request', 'cancel_order', 'other']
const RISKS = ['legal_threat', 'fraud_suspected', 'safety_issue', 'vulnerable_customer', 'regulatory_complaint']
const DEMO_TURNS = ['My sofa is damaged and I am quite upset.', 'This is the third time I contact you about this!', 'I will contact my lawyer if nobody fixes this today.', 'Let me speak to a manager.']

export default function RoutingPage() {
  const [tab, setTab] = useState('playground')
  return (
    <div>
      <PageHeader icon={Route} title="Routing & escalation" subtitle="Provider-neutral, in-process skills-based routing with Job-Router-style semantics (queues, classification policy, distribution policy, exception policy) — no dependency on a retiring service — and explicit, configurable escalation triggers that fire once." />
      <Tabs tabs={[{ id: 'playground', label: 'Routing playground' }, { id: 'triggers', label: 'Escalation triggers' }, { id: 'config', label: 'Queues, rules & agents' }, { id: 'eval', label: 'Classifier evaluation' }]} value={tab} onChange={setTab} />
      {tab === 'playground' && <Playground />}
      {tab === 'triggers' && <Triggers />}
      {tab === 'config' && <ConfigTab />}
      {tab === 'eval' && <EvalTab />}
    </div>
  )
}

function Playground() {
  const [text, setText] = useState('Mein Sofa ist beschädigt angekommen, bitte um Rückerstattung.')
  const [ana, setAna] = useState<Analysis | null>(null)
  const [intent, setIntent] = useState('damaged_item')
  const [risks, setRisks] = useState<string[]>([])
  const [vip, setVip] = useState(false)
  const [vul, setVul] = useState(false)
  const [sent, setSent] = useState(-0.2)
  const [dec, setDec] = useState<Decision | null>(null)
  const analyze = async () => { const a = await api<Analysis>('/api/routing/analyze', { body: { text } }); setAna(a); setIntent(a.intent); setRisks(a.risk_flags); setSent(a.sentiment) }
  const route = async () => setDec(await api<Decision>('/api/routing/route', { body: { intent, risk_flags: risks, sentiment: sent, vip, vulnerable: vul, language: ana?.language ?? 'en' } }))
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="1 · Understand the message" subtitle="intent, sentiment, emotion, risk flags, language (rules + LLM in Azure mode)">
        <textarea aria-label="Customer message" rows={3} value={text} onChange={(e) => setText(e.target.value)} className={inputCls} />
        <Button className="mt-2" variant="primary" onClick={analyze}>Analyse</Button>
        {ana && <div className="mt-3 flex flex-wrap gap-1.5"><Badge tone="blue">{ana.intent}</Badge><Badge tone="slate">{ana.language.toUpperCase()}</Badge><Badge tone={sentimentTone(ana.sentiment)}>{ana.emotion} {ana.sentiment.toFixed(2)}</Badge><Badge tone="slate">urgency {ana.urgency}</Badge>{ana.risk_flags.map((r) => <Badge key={r} tone="red">{r}</Badge>)}</div>}
      </Card>
      <Card title="2 · Route the job" subtitle="adjust the inputs and see the queue, priority, skills and the rule that matched">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs font-medium text-slate-600">Intent<select value={intent} onChange={(e) => setIntent(e.target.value)} className={cx(inputCls, 'mt-1')}>{INTENTS.map((i) => <option key={i}>{i}</option>)}</select></label>
          <Slider label="Sentiment" value={sent} min={-1} max={1} step={0.05} onChange={setSent} />
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-sm">{RISKS.map((r) => <label key={r} className="flex items-center gap-1.5"><input type="checkbox" checked={risks.includes(r)} onChange={(e) => setRisks(e.target.checked ? [...risks, r] : risks.filter((x) => x !== r))} className="accent-rose-600" />{r.replace('_', ' ')}</label>)}<label className="flex items-center gap-1.5"><input type="checkbox" checked={vip} onChange={(e) => setVip(e.target.checked)} className="accent-violet-600" />VIP</label><label className="flex items-center gap-1.5"><input type="checkbox" checked={vul} onChange={(e) => setVul(e.target.checked)} className="accent-amber-600" />vulnerable</label></div>
        <Button className="mt-3" variant="primary" icon={Shuffle} onClick={route}>Route</Button>
        {dec && <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm"><div className="flex flex-wrap items-center gap-2"><Badge tone="blue">{dec.queue_name}</Badge><Badge tone="amber">priority {dec.priority}</Badge><Badge tone="slate">SLA {dec.sla_s}s</Badge><Badge tone="violet">{dec.rule}</Badge><Badge tone="slate">{dec.distribution}</Badge></div><p className="mt-2 text-xs text-slate-600">needs skills: {dec.required_skills.join(', ')} · language {dec.language}</p><ul className="mt-1 list-disc pl-4 text-xs text-slate-600">{dec.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
      </Card>
    </div>
  )
}

function Triggers() {
  const [turns, setTurns] = useState(DEMO_TURNS.join('\n'))
  const [res, setRes] = useState<Sim | null>(null)
  const run = async () => setRes(await api<Sim>('/api/routing/triggers/simulate', { body: { turns: turns.split('\n').filter(Boolean), language: 'en' } }))
  return (
    <Card title="Replay a transcript turn by turn" subtitle="each trigger (legal threat, fraud, safety, vulnerable, explicit request, sentiment, loop, tool failure, knowledge gap …) fires exactly once">
      <textarea aria-label="Customer turns, one per line" rows={5} value={turns} onChange={(e) => setTurns(e.target.value)} className={inputCls} />
      <Button className="mt-2" variant="primary" onClick={run}>Simulate</Button>
      {res && <ol className="mt-3 space-y-2">{res.timeline.map((t, i) => <li key={i} className="rounded-xl border border-slate-200 p-2.5 text-sm"><div className="text-slate-800">“{t.text}”</div><div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs"><Badge tone="blue">{t.intent}</Badge><Badge tone={sentimentTone(t.sentiment)}>{t.emotion} {t.sentiment.toFixed(2)}</Badge>{t.risk_flags.map((r) => <Badge key={r} tone="red">{r}</Badge>)}{t.fired.map((f) => <Badge key={f.code} tone="violet">⚡ {f.code}</Badge>)}</div></li>)}<li className="text-sm text-slate-600">Fired once: {res.fired_once.join(', ') || 'none'}</li></ol>}
    </Card>
  )
}

function ConfigTab() {
  const qs = useApi<Qs>('/api/routing/queues', { refreshMs: 10000 })
  const ws = useApi<Worker[]>('/api/routing/workers', { refreshMs: 10000 })
  if (qs.loading && !qs.data) return <Spinner />
  if (qs.error || !qs.data) return <ErrorBox error={qs.error} />
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">{qs.data.semantics}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Queues" pad={false}><DataTable dense rows={qs.data.queues} rowKey={(q) => q.id} cols={[{ key: 'n', header: 'Queue', render: (q) => <b>{q.name}</b> }, { key: 's', header: 'SLA', align: 'right', render: (q) => `${q.sla_s}s` }, { key: 'k', header: 'Skills', render: (q) => q.skills.join(', ') }, { key: 'd', header: 'Distribution', render: (q) => <span className="text-xs">{q.distribution}</span> }, { key: 'w', header: 'Waiting', align: 'right', render: (q) => q.waiting }]} /></Card>
        <Card title="Classification rules (priority order)" pad={false}><DataTable dense rows={qs.data.rules} rowKey={(r) => r.id} cols={[{ key: 'i', header: 'Rule', render: (r) => <Badge tone="violet">{r.id}</Badge> }, { key: 'w', header: 'When', render: (r) => <span className="text-xs">{r.when}</span> }, { key: 'q', header: 'Queue', render: (r) => r.queue }, { key: 'b', header: 'Base', align: 'right', render: (r) => r.base }]} /></Card>
      </div>
      <Card title="Human agent roster (simulated)" subtitle="skills, languages, presence and current load" pad={false}>
        <DataTable dense rows={ws.data ?? []} rowKey={(w) => w.id} cols={[{ key: 'n', header: 'Agent', render: (w) => <span className="flex items-center gap-2"><Dot tone={w.presence === 'available' ? 'green' : w.presence === 'busy' ? 'amber' : 'slate'} /><b>{w.name}</b></span> }, { key: 's', header: 'Skills', render: (w) => <span className="text-xs">{w.skills.join(', ')}</span> }, { key: 'l', header: 'Languages', render: (w) => w.languages.join(', ') }, { key: 'a', header: 'Active', align: 'right', render: (w) => `${w.active.length}/${w.capacity.chat}` }]} />
      </Card>
    </div>
  )
}

function EvalTab() {
  const lab = useApi<Lab>('/api/routing/labelled-eval')
  const d = lab.data
  if (lab.loading && !d) return <Spinner />
  if (lab.error || !d) return <ErrorBox error={lab.error} />
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3"><Stat label="Intent macro-F1" value={d.macro_f1} tone="green" hint={`target ≥ 0.85 · ${d.n} labelled utterances, 8 languages`} /><Stat label="Accuracy" value={fmt.pct(d.accuracy, 1)} /><Stat label="Misses" value={d.misses.length} /></div>
      <Card title="Per-intent precision / recall" pad={false}><DataTable dense rows={Object.entries(d.per_intent).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[{ key: 'k', header: 'Intent', render: (r) => <b>{r.k}</b> }, { key: 'p', header: 'Precision', align: 'right', render: (r) => r.precision }, { key: 'r', header: 'Recall', align: 'right', render: (r) => r.recall }, { key: 'f', header: 'F1', align: 'right', render: (r) => r.f1 }, { key: 's', header: 'Support', align: 'right', render: (r) => r.support }]} /></Card>
      {d.misses.length > 0 && <Card title="Misclassified"><ul className="space-y-1 text-sm">{d.misses.map((m, i) => <li key={i}>“{m.text}” → <Badge tone="red">{m.got}</Badge> expected <Badge tone="green">{m.expected}</Badge></li>)}</ul></Card>}
    </div>
  )
}
