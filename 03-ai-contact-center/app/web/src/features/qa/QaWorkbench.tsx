import { ClipboardCheck, Quote } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { BarSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Slider, Spinner, Stat, Tabs, cx } from '../../lib/ui'

interface Review { id: string; conversation_id: string; channel: string; language: string; scored_at: number; scorer: string; dimensions: Record<string, number>; overall: number; band: string; auto_fail: { rule: string; detail?: string }[]; disposition: string | null; participants: string[]; calibration: { analyst: string; delta: Record<string, number>; scores: Record<string, number> } | null }
interface Evidence { dimension: string; note: string; quote?: string | null; idx?: number | null }
interface Detail extends Review { evidence: Evidence[]; transcript: { idx: number; role: string; text: string; flags: string[] }[]; segments?: Record<string, Record<string, number>> }
interface Dash { coverage: { qa_records_live: number; ended_conversations_live: number; historical_records: number; coverage_pct: number; manual_qa_baseline_pct: number }; bands: Record<string, number>; dimension_avg: Record<string, number>; weekly: { week: string; avg: number; n: number }[]; ai_vs_human: Record<string, { avg: number; n: number }>; agents: { agent: string; avg: number; n: number }[]; auto_fails_live: { conversation_id: string; rules: string[]; overall: number }[]; auto_fail_rate_hist: number; outliers: { conversation_id: string; overall: number; band: string }[] }
interface Labelled { overall: { within1_pct: number; exact_pct: number; kappa: number; n: number }; by_dimension: Record<string, { within1_pct: number; exact_pct: number; kappa: number }>; evidence_in_transcript_pct: number; target: { within1_pct: number }; cases: { case: string; auto: Record<string, number>; reference: Record<string, number>; auto_fail: string[] }[] }
interface Agree { n?: number; within1_pct?: number; kappa?: number; drift?: { flagged?: boolean; note?: string } | null; [k: string]: unknown }
interface Coaching { agent: string; conversations: number; avg_overall: number | null; suggestions: { dimension: string; title?: string; suggestion?: string; text?: string; avg?: number }[] }

const BAND_TONE: Record<string, string> = { excellent: 'green', good: 'blue', needs_improvement: 'amber', poor: 'red', fail: 'red' }
const DIMS = ['greeting', 'empathy', 'accuracy', 'policy', 'resolution', 'compliance', 'clarity']

export default function QaWorkbench() {
  const [tab, setTab] = useState('dashboard')
  const [sel, setSel] = useState<string | null>(null)
  const dash = useApi<Dash>('/api/qa/dashboard', { refreshMs: 20000 })
  const reviews = useApi<Review[]>('/api/qa/reviews?limit=80', { refreshMs: 20000 })
  return (
    <div>
      <PageHeader icon={ClipboardCheck} title="QA workbench" subtitle="100 % of conversations — AI and human — scored on a 7-dimension rubric with evidence snippets and compliance auto-fail; analysts calibrate and watch agreement." />
      <Tabs tabs={[{ id: 'dashboard', label: 'Dashboard' }, { id: 'reviews', label: `Reviews (${reviews.data?.length ?? 0})` }, { id: 'agreement', label: 'Calibration & agreement' }]} value={tab} onChange={setTab} />
      {tab === 'dashboard' && <DashboardTab dash={dash} />}
      {tab === 'reviews' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
          <Card title="Scored conversations" pad={false}>
            {reviews.loading && !reviews.data ? <Spinner /> : reviews.error ? <ErrorBox error={reviews.error} /> : (
              <DataTable dense rows={reviews.data ?? []} rowKey={(r) => r.conversation_id} selected={sel ?? undefined} onRowClick={(r) => setSel(r.conversation_id)} empty="No live conversation has ended yet - finish a chat in the widget, or play a scenario on the Evaluation page, and it is scored automatically." cols={[
                { key: 'c', header: 'Conversation', render: (r) => <span className="font-mono text-xs">{r.conversation_id}</span> },
                { key: 'o', header: 'Score', align: 'right', render: (r) => <b>{r.overall}</b> },
                { key: 'b', header: 'Band', render: (r) => <Badge tone={BAND_TONE[r.band]}>{r.band.replace('_', ' ')}</Badge> },
                { key: 'f', header: 'Auto-fail', render: (r) => (r.auto_fail.length ? <Badge tone="red">{r.auto_fail.map((a) => a.rule).join(', ')}</Badge> : <span className="text-slate-300">—</span>) },
                { key: 'p', header: 'Who', render: (r) => <span className="text-xs text-slate-600">{r.participants.join(' + ')}</span> },
                { key: 'k', header: 'Calibrated', render: (r) => (r.calibration ? <Badge tone="violet">by {r.calibration.analyst}</Badge> : '') },
              ]} />
            )}
          </Card>
          {sel ? <ReviewDetail id={sel} onSaved={() => { reviews.reload(); dash.reload() }} /> : <Card title="Review"><Empty>Select a scored conversation to see evidence and calibrate.</Empty></Card>}
        </div>
      )}
      {tab === 'agreement' && <AgreementTab />}
    </div>
  )
}

function DashboardTab({ dash }: { dash: ReturnType<typeof useApi<Dash>> }) {
  const d = dash.data
  if (dash.loading && !d) return <Spinner />
  if (dash.error || !d) return <ErrorBox error={dash.error} />
  const bandRows = Object.entries(d.bands).map(([band, n]) => ({ band: band.replace('_', ' '), n }))
  const dimRows = DIMS.map((k) => ({ dim: k, avg: d.dimension_avg[k] ?? 0 }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="QA coverage" value={`${d.coverage.coverage_pct}%`} hint={`manual QA baseline ${d.coverage.manual_qa_baseline_pct}%`} tone="green" />
        <Stat label="Scored (live)" value={d.coverage.qa_records_live} hint={`${d.coverage.ended_conversations_live} ended`} />
        <Stat label="Scored (synthetic history)" value={d.coverage.historical_records} />
        <Stat label="AI avg score" value={d.ai_vs_human.ai?.avg ?? '—'} hint={`${d.ai_vs_human.ai?.n ?? 0} conversations`} />
        <Stat label="Human avg score" value={d.ai_vs_human.human?.avg ?? '—'} hint={`${d.ai_vs_human.human?.n ?? 0} conversations`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Score bands"><BarSeries data={bandRows} x="band" bars={[{ key: 'n', name: 'conversations' }]} height={200} /></Card>
        <Card title="Weekly average score" subtitle="synthetic 90-day history"><LineSeries data={d.weekly} x="week" lines={[{ key: 'avg', name: 'avg score' }]} height={200} /></Card>
        <Card title="Average by rubric dimension (1-5)"><BarSeries data={dimRows} x="dim" bars={[{ key: 'avg', name: 'avg', color: '#7c3aed' }]} height={200} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Agents — lowest first" subtitle="outliers feed coaching" pad={false}>
          <DataTable dense rows={d.agents} rowKey={(a) => a.agent} cols={[{ key: 'a', header: 'Agent', render: (a) => <span className="font-medium">{a.agent}</span> }, { key: 's', header: 'Avg score', render: (a) => <div className="w-40"><div className="text-xs tabular-nums">{a.avg}</div><Progress value={a.avg} max={100} tone={a.avg >= 85 ? 'green' : a.avg >= 75 ? 'blue' : 'amber'} /></div> }, { key: 'n', header: 'n', align: 'right', render: (a) => a.n }]} />
        </Card>
        <Card title="Compliance auto-fails" subtitle={`historical auto-fail rate ${(d.auto_fail_rate_hist * 100).toFixed(1)}%`}>
          {!d.auto_fails_live.length ? <p className="text-sm text-slate-500">No live auto-fails. A conversation without the AI disclosure, or with a risky promise, is auto-failed with evidence.</p> : <ul className="space-y-1.5 text-sm">{d.auto_fails_live.map((f) => <li key={f.conversation_id} className="flex items-center gap-2"><Badge tone="red">{f.rules.join(', ')}</Badge><span className="font-mono text-xs">{f.conversation_id}</span><span className="text-xs text-slate-500">score {f.overall}</span></li>)}</ul>}
        </Card>
      </div>
    </div>
  )
}

function ReviewDetail({ id, onSaved }: { id: string; onSaved: () => void }) {
  const r = useApi<Detail>(`/api/qa/reviews/${id}`)
  const [scores, setScores] = useState<Record<string, number> | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const d = r.data
  const cur = scores ?? d?.calibration?.scores ?? d?.dimensions ?? {}
  const save = async () => {
    setBusy(true)
    try { await api(`/api/qa/reviews/${id}/calibrate`, { body: { scores: cur, note: 'analyst calibration' } }); setMsg('Calibration saved - agreement metrics updated.'); setScores(null); r.reload(); onSaved() } catch (e) { setMsg(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } finally { setBusy(false) }
  }
  if (r.loading && !d) return <Card title="Review"><Spinner /></Card>
  if (!d) return <Card title="Review"><ErrorBox error={r.error} /></Card>
  const evBy = (dim: string) => d.evidence.filter((e) => e.dimension === dim)
  return (
    <Card title={`Review · ${d.conversation_id}`} subtitle={`${d.scorer} · ${fmt.dt(d.scored_at)}`} actions={<Badge tone={BAND_TONE[d.band]}>{d.overall} · {d.band.replace('_', ' ')}</Badge>}>
      {d.auto_fail.length > 0 && <div className="mb-3 rounded-xl bg-rose-50 p-2.5 text-sm text-rose-800 ring-1 ring-rose-200"><b>Auto-fail:</b> {d.auto_fail.map((a) => `${a.rule}${a.detail ? ` (${a.detail})` : ''}`).join('; ')}</div>}
      <div className="space-y-2.5">
        {DIMS.map((dim) => (
          <div key={dim}>
            <Slider label={`${dim} (auto ${d.dimensions[dim]})`} value={cur[dim] ?? d.dimensions[dim]} min={1} max={5} onChange={(v) => setScores({ ...cur, [dim]: v })} />
            {evBy(dim).map((e, i) => <p key={i} className="ml-1 mt-0.5 text-[11px] text-slate-500"><Quote size={9} className="mr-1 inline" aria-hidden />{e.note}{e.quote && <> — <i>“{e.quote.slice(0, 110)}”</i></>}</p>)}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2"><Button variant="primary" busy={busy} onClick={save}>Save calibration</Button>{d.calibration && <span className="text-xs text-slate-500">last delta: {Object.entries(d.calibration.delta).filter(([, v]) => v).map(([k, v]) => `${k} ${v > 0 ? '+' : ''}${v}`).join(', ') || 'none'}</span>}</div>
      {msg && <p role="status" className="mt-2 text-xs text-slate-600">{msg}</p>}
      <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">Transcript ({d.transcript.length})</summary><ul className="scroll-thin mt-2 max-h-60 space-y-1 overflow-y-auto text-xs">{d.transcript.map((m) => <li key={m.idx} className={cx('rounded-lg px-2 py-1', m.role === 'customer' ? 'bg-slate-100' : 'bg-blue-50')}><b>{m.role}:</b> {m.text}</li>)}</ul></details>
    </Card>
  )
}

function AgreementTab() {
  const lab = useApi<Labelled>('/api/qa/labelled-eval')
  const agr = useApi<Agree>('/api/qa/agreement')
  const [agent, setAgent] = useState('concierge-ai')
  const coach = useApi<Coaching>(`/api/qa/coaching/${agent}`)
  const l = lab.data
  return (
    <div className="space-y-4">
      {l ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Within ±1 of reference" value={`${l.overall.within1_pct}%`} hint={`target ≥ ${l.target.within1_pct}%`} tone={l.overall.within1_pct >= l.target.within1_pct ? 'green' : 'red'} />
            <Stat label="Exact agreement" value={`${l.overall.exact_pct}%`} />
            <Stat label="Weighted kappa" value={l.overall.kappa} />
            <Stat label="Evidence found in transcript" value={`${l.evidence_in_transcript_pct}%`} hint="every non-perfect dimension" tone="green" />
          </div>
          <Card title="Auto-QA vs reference scores on the labelled transcript set" pad={false}>
            <DataTable dense rows={Object.entries(l.by_dimension).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[{ key: 'k', header: 'Dimension', render: (r) => <b>{r.k}</b> }, { key: 'w', header: 'Within ±1', align: 'right', render: (r) => `${r.within1_pct}%` }, { key: 'e', header: 'Exact', align: 'right', render: (r) => `${r.exact_pct}%` }, { key: 'kk', header: 'Kappa', align: 'right', render: (r) => r.kappa }]} />
          </Card>
        </>
      ) : <Spinner />}
      <Card title="Live calibration agreement" subtitle="analyst overrides vs auto scores (drift flagged)">
        {agr.data ? <Json2 data={agr.data} /> : <Spinner />}
      </Card>
      <Card title="Coaching suggestions" actions={<select aria-label="Agent" value={agent} onChange={(e) => setAgent(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">{['concierge-ai', 'AG-07', 'AG-04', 'AG-11', 'AG-03'].map((a) => <option key={a}>{a}</option>)}</select>}>
        {coach.data ? <><p className="mb-2 text-xs text-slate-500">{coach.data.conversations} conversations · avg {coach.data.avg_overall ?? '—'}</p><ol className="space-y-2">{coach.data.suggestions.map((s, i) => <li key={i} className="rounded-xl border border-slate-200 p-2.5 text-sm"><b>{s.title ?? s.dimension}</b><p className="text-xs text-slate-600">{s.suggestion ?? s.text}</p></li>)}</ol></> : <Spinner />}
      </Card>
    </div>
  )
}

function Json2({ data }: { data: unknown }) {
  return <pre className="scroll-thin max-h-56 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(data, null, 2)}</pre>
}
