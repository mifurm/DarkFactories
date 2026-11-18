import { ClipboardCheck, Quote } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { BarSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Slider, Spinner, Stat, Tabs, cx } from '../../lib/ui'

interface Review { id: string; conversation_id: string; channel: string; language: string; scored_at: number; scorer: string; dimensions: Record<string, number>; overall: number; band: string; auto_fail: { rule: string; detail?: string }[]; disposition: string | null; participants: string[]; calibration: { analyst: string; delta: Record<string, number>; scores: Record<string, number> } | null }
interface Evidence { dimension: string; note: string; quote?: string | null; idx?: number | null }
interface Detail extends Review { evidence: Evidence[]; transcript: { idx: number; role: string; text: string; flags: string[] }[]; segments?: Record<string, Record<string, number>> }
interface Dash { coverage: { qa_records_live: number; ended_conversations_live: number; historical_records: number; coverage_pct: number; manual_qa_baseline_pct: number }; bands: Record<string, number>; dimension_avg: Record<string, number>; weekly: { week: string; avg: number; n: number }[]; ai_vs_human: Record<string, { avg: number; n: number }>; agents: { agent: string; avg: number; n: number }[]; auto_fails_live: { conversation_id: string; rules: string[]; overall: number }[]; auto_fail_rate_hist: number; outliers: { conversation_id: string; overall: number; band: string }[] }
interface Labelled { overall: { within1_pct: number; exact_pct: number; kappa: number; n: number }; by_dimension: Record<string, { within1_pct: number; exact_pct: number; kappa: number }>; evidence_in_transcript_pct: number; target: { within1_pct: number }; cases: { case: string; auto: Record<string, number>; reference: Record<string, number>; auto_fail: string[] }[] }
interface Agree { overall?: { n?: number; exact_pct?: number | null; within1_pct?: number | null; mae?: number | null; kappa?: number | null }; calibrated_conversations?: number; drift?: { flag?: boolean; recent_mae?: number | null; earlier_mae?: number | null } | null }
interface Coaching { agent: string; conversations: number; avg_overall: number | null; suggestions: { dimension: string; title?: string; suggestion?: string; text?: string; avg?: number; avg_score?: number }[] }

const BAND_TONE: Record<string, string> = { excellent: 'green', good: 'blue', needs_improvement: 'amber', poor: 'red', fail: 'red' }
const DIMS = ['greeting', 'empathy', 'accuracy', 'policy', 'resolution', 'compliance', 'clarity']

export default function QaWorkbench() {
  const { t } = useI18n()
  const [tab, setTab] = useState('dashboard')
  const [sel, setSel] = useState<string | null>(null)
  const dash = useApi<Dash>('/api/qa/dashboard', { refreshMs: 20000 })
  const reviews = useApi<Review[]>('/api/qa/reviews?limit=80', { refreshMs: 20000 })
  return (
    <div>
      <PageHeader icon={ClipboardCheck} title={t('QA workbench')} subtitle={t('100 % of conversations — AI and human — scored on a 7-dimension rubric with evidence snippets and compliance auto-fail; analysts calibrate and watch agreement.')} />
      <Tabs tabs={[{ id: 'dashboard', label: t('Dashboard') }, { id: 'reviews', label: t('Reviews ({count})', { count: reviews.data?.length ?? 0 }) }, { id: 'agreement', label: t('Calibration & agreement') }]} value={tab} onChange={setTab} />
      {tab === 'dashboard' && <DashboardTab dash={dash} />}
      {tab === 'reviews' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
          <Card title={t('Scored conversations')} pad={false}>
            {reviews.loading && !reviews.data ? <Spinner /> : reviews.error ? <ErrorBox error={reviews.error} /> : <ReviewTable reviews={reviews.data ?? []} sel={sel} onSelect={setSel} />}
          </Card>
          {sel ? <ReviewDetail id={sel} onSaved={() => { reviews.reload(); dash.reload() }} /> : <Card title={t('Review')}><Empty>{t('Select a scored conversation to see evidence and calibrate.')}</Empty></Card>}
        </div>
      )}
      {tab === 'agreement' && <AgreementTab />}
    </div>
  )
}

function ReviewTable({ reviews, sel, onSelect }: { reviews: Review[]; sel: string | null; onSelect: (id: string) => void }) {
  const { t, te } = useI18n()
  return (
    <DataTable dense rows={reviews} rowKey={(r) => r.conversation_id} selected={sel ?? undefined} onRowClick={(r) => onSelect(r.conversation_id)} empty={t('No live conversation has ended yet - finish a chat in the widget, or play a scenario on the Evaluation page, and it is scored automatically.')} cols={[
      { key: 'c', header: t('Conversation'), render: (r) => <span className="font-mono text-xs">{r.conversation_id}</span> },
      { key: 'o', header: t('Score'), align: 'right', render: (r) => <b>{r.overall}</b> },
      { key: 'b', header: t('Band'), render: (r) => <Badge tone={BAND_TONE[r.band]}>{te('band', r.band)}</Badge> },
      { key: 'f', header: t('Auto-fail'), render: (r) => (r.auto_fail.length ? <Badge tone="red">{r.auto_fail.map((a) => te('autoFailRule', a.rule)).join(', ')}</Badge> : <span className="text-slate-300">—</span>) },
      { key: 'p', header: t('Who'), render: (r) => <span className="text-xs text-slate-600">{r.participants.join(' + ')}</span> },
      { key: 'k', header: t('Calibrated'), render: (r) => (r.calibration ? <Badge tone="violet">{t('by {analyst}', { analyst: r.calibration.analyst })}</Badge> : '') },
    ]} />
  )
}

function DashboardTab({ dash }: { dash: ReturnType<typeof useApi<Dash>> }) {
  const { t, tn, te, tl, fmt } = useI18n()
  const d = dash.data
  if (dash.loading && !d) return <Spinner />
  if (dash.error || !d) return <ErrorBox error={dash.error} />
  const bandRows = Object.entries(d.bands).map(([band, n]) => ({ band: te('band', band), n }))
  const dimRows = DIMS.map((k) => ({ dim: te('qaDim', k), avg: d.dimension_avg[k] ?? 0 }))
  const convs = (n: number) => tn(n, { one: '{n} conversation', other: '{n} conversations' })
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={t('QA coverage')} value={fmt.percentValue(d.coverage.coverage_pct)} hint={t('manual QA baseline {pct}', { pct: fmt.percentValue(d.coverage.manual_qa_baseline_pct) })} tone="green" />
        <Stat label={t('Scored (live)')} value={d.coverage.qa_records_live} hint={t('{n} ended', { n: d.coverage.ended_conversations_live })} />
        <Stat label={t('Scored (synthetic history)')} value={d.coverage.historical_records} />
        <Stat label={t('AI avg score')} value={d.ai_vs_human.ai?.avg != null ? fmt.plain(d.ai_vs_human.ai.avg) : '—'} hint={convs(d.ai_vs_human.ai?.n ?? 0)} />
        <Stat label={t('Human avg score')} value={d.ai_vs_human.human?.avg != null ? fmt.plain(d.ai_vs_human.human.avg) : '—'} hint={convs(d.ai_vs_human.human?.n ?? 0)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t('Score bands')}><BarSeries data={bandRows} x="band" bars={[{ key: 'n', name: t('conversations') }]} height={200} /></Card>
        <Card title={t('Weekly average score')} subtitle={t('synthetic 90-day history')}><LineSeries data={d.weekly} x="week" xFmt={(v) => fmt.week(v)} lines={[{ key: 'avg', name: t('avg score') }]} height={200} /></Card>
        <Card title={t('Average by rubric dimension (1-5)')}><BarSeries data={dimRows} x="dim" bars={[{ key: 'avg', name: t('avg'), color: '#7c3aed' }]} height={200} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('Agents — lowest first')} subtitle={t('outliers feed coaching')} pad={false}>
          <DataTable dense rows={d.agents} rowKey={(a) => a.agent} cols={[{ key: 'a', header: t('Agent'), render: (a) => <span className="font-medium">{tl('qaAgent', a.agent, a.agent)}</span> }, { key: 's', header: t('Avg score'), render: (a) => <div className="w-40"><div className="text-xs tabular-nums">{fmt.plain(a.avg)}</div><Progress value={a.avg} max={100} tone={a.avg >= 85 ? 'green' : a.avg >= 75 ? 'blue' : 'amber'} /></div> }, { key: 'n', header: 'n', align: 'right', render: (a) => a.n }]} />
        </Card>
        <Card title={t('Compliance auto-fails')} subtitle={t('historical auto-fail rate {pct}', { pct: fmt.percent(d.auto_fail_rate_hist, 1) })}>
          {!d.auto_fails_live.length ? <p className="text-sm text-slate-500">{t('No live auto-fails. A conversation without the AI disclosure, or with a risky promise, is auto-failed with evidence.')}</p> : <ul className="space-y-1.5 text-sm">{d.auto_fails_live.map((f) => <li key={f.conversation_id} className="flex flex-wrap items-center gap-2"><Badge tone="red">{f.rules.map((r) => te('autoFailRule', r)).join(', ')}</Badge><span className="font-mono text-xs">{f.conversation_id}</span><span className="text-xs text-slate-500">{t('score {n}', { n: fmt.plain(f.overall) })}</span></li>)}</ul>}
        </Card>
      </div>
    </div>
  )
}

function ReviewDetail({ id, onSaved }: { id: string; onSaved: () => void }) {
  const { t, te, fmt } = useI18n()
  const r = useApi<Detail>(`/api/qa/reviews/${id}`)
  const [scores, setScores] = useState<Record<string, number> | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const d = r.data
  const cur = scores ?? d?.calibration?.scores ?? d?.dimensions ?? {}
  const save = async () => {
    setBusy(true)
    try { await api(`/api/qa/reviews/${id}/calibrate`, { body: { scores: cur, note: t('analyst calibration') } }); setMsg(t('Calibration saved - agreement metrics updated.')); setScores(null); r.reload(); onSaved() } catch (e) { setMsg(describeError(e)) } finally { setBusy(false) }
  }
  if (r.loading && !d) return <Card title={t('Review')}><Spinner /></Card>
  if (!d) return <Card title={t('Review')}><ErrorBox error={r.error} /></Card>
  const evBy = (dim: string) => d.evidence.filter((e) => e.dimension === dim)
  const delta = d.calibration ? Object.entries(d.calibration.delta).filter(([, v]) => v).map(([k, v]) => `${te('qaDim', k)} ${v > 0 ? '+' : ''}${v}`).join(', ') : ''
  return (
    <Card title={t('Review · {id}', { id: d.conversation_id })} subtitle={`${te('qaScorer', d.scorer)} · ${fmt.dt(d.scored_at)}`} actions={<Badge tone={BAND_TONE[d.band]}>{d.overall} · {te('band', d.band)}</Badge>}>
      {d.auto_fail.length > 0 && <div className="mb-3 rounded-xl bg-rose-50 p-2.5 text-sm text-rose-800 ring-1 ring-rose-200"><b>{t('Auto-fail:')}</b> {d.auto_fail.map((a) => `${te('autoFailRule', a.rule)}${a.detail ? ` (${a.detail})` : ''}`).join('; ')}</div>}
      <div className="space-y-2.5">
        {DIMS.map((dim) => (
          <div key={dim}>
            <Slider label={t('{dimension} (auto {score})', { dimension: te('qaDim', dim), score: d.dimensions[dim] })} value={cur[dim] ?? d.dimensions[dim]} min={1} max={5} onChange={(v) => setScores({ ...cur, [dim]: v })} />
            {evBy(dim).map((e, i) => <p key={i} className="ml-1 mt-0.5 text-[11px] text-slate-500"><Quote size={9} className="mr-1 inline" aria-hidden />{e.note}{e.quote && <> — <i data-user-content>“{e.quote.slice(0, 110)}”</i></>}</p>)}
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2"><Button variant="primary" busy={busy} onClick={save}>{t('Save calibration')}</Button>{d.calibration && <span className="text-xs text-slate-500">{t('last delta: {delta}', { delta: delta || t('none') })}</span>}</div>
      {msg && <p role="status" className="mt-2 text-xs text-slate-600">{msg}</p>}
      <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">{t('Transcript ({count})', { count: d.transcript.length })}</summary><ul className="scroll-thin mt-2 max-h-60 space-y-1 overflow-y-auto text-xs">{d.transcript.map((m) => <li key={m.idx} className={cx('rounded-lg px-2 py-1', m.role === 'customer' ? 'bg-slate-100' : 'bg-blue-50')}><b>{te('msgRole', m.role)}:</b> <span data-user-content lang={d.language}>{m.text}</span></li>)}</ul></details>
    </Card>
  )
}

function AgreementTab() {
  const { t, tn, te, tl, fmt } = useI18n()
  const lab = useApi<Labelled>('/api/qa/labelled-eval')
  const agr = useApi<Agree>('/api/qa/agreement')
  const [agent, setAgent] = useState('concierge-ai')
  const coach = useApi<Coaching>(`/api/qa/coaching/${agent}`)
  const l = lab.data
  const a = agr.data
  return (
    <div className="space-y-4">
      {l ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label={t('Within ±1 of reference')} value={fmt.percentValue(l.overall.within1_pct)} hint={t('target ≥ {pct}', { pct: fmt.percentValue(l.target.within1_pct) })} tone={l.overall.within1_pct >= l.target.within1_pct ? 'green' : 'red'} />
            <Stat label={t('Exact agreement')} value={fmt.percentValue(l.overall.exact_pct)} />
            <Stat label={t('Weighted kappa')} value={fmt.plain(l.overall.kappa)} />
            <Stat label={t('Evidence found in transcript')} value={fmt.percentValue(l.evidence_in_transcript_pct)} hint={t('every non-perfect dimension')} tone="green" />
          </div>
          <Card title={t('Auto-QA vs reference scores on the labelled transcript set')} pad={false}>
            <DataTable dense rows={Object.entries(l.by_dimension).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[{ key: 'k', header: t('Dimension'), render: (r) => <b>{te('qaDim', r.k)}</b> }, { key: 'w', header: t('Within ±1'), align: 'right', render: (r) => fmt.percentValue(r.within1_pct) }, { key: 'e', header: t('Exact'), align: 'right', render: (r) => fmt.percentValue(r.exact_pct) }, { key: 'kk', header: t('Kappa'), align: 'right', render: (r) => fmt.plain(r.kappa) }]} />
          </Card>
        </>
      ) : <Spinner />}
      <Card title={t('Live calibration agreement')} subtitle={t('analyst overrides vs auto scores (drift flagged)')}>
        {a ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Stat label={t('Calibrated conversations')} value={a.calibrated_conversations ?? 0} />
              <Stat label={t('Exact agreement')} value={a.overall?.exact_pct != null ? fmt.percentValue(a.overall.exact_pct) : '—'} />
              <Stat label={t('Within ±1')} value={a.overall?.within1_pct != null ? fmt.percentValue(a.overall.within1_pct) : '—'} />
              <Stat label={t('Mean absolute error')} value={a.overall?.mae != null ? fmt.plain(a.overall.mae) : '—'} />
              <Stat label={t('Weighted kappa')} value={a.overall?.kappa != null ? fmt.plain(a.overall.kappa) : '—'} />
            </div>
            <p className="text-sm text-slate-600">
              <Badge tone={a.drift?.flag ? 'red' : 'green'}>{a.drift?.flag ? t('drift detected') : t('no drift')}</Badge>{' '}
              {!a.calibrated_conversations ? t('No analyst calibrations yet — calibrate a review to see live agreement.') : t('recent MAE {recent} vs earlier {earlier}', { recent: a.drift?.recent_mae != null ? fmt.plain(a.drift.recent_mae) : '—', earlier: a.drift?.earlier_mae != null ? fmt.plain(a.drift.earlier_mae) : '—' })}
            </p>
          </div>
        ) : <Spinner />}
      </Card>
      <Card title={t('Coaching suggestions')} actions={<select aria-label={t('Agent')} value={agent} onChange={(e) => setAgent(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">{['concierge-ai', 'AG-07', 'AG-04', 'AG-11', 'AG-03'].map((x) => <option key={x} value={x}>{tl('qaAgent', x, x)}</option>)}</select>}>
        {coach.data ? <><p className="mb-2 text-xs text-slate-500">{t('{conversations} · avg {avg}', { conversations: tn(coach.data.conversations, { one: '{n} conversation', other: '{n} conversations' }), avg: coach.data.avg_overall != null ? fmt.plain(coach.data.avg_overall) : '—' })}</p><ol className="space-y-2">{coach.data.suggestions.map((s, i) => <li key={i} className="rounded-xl border border-slate-200 p-2.5 text-sm"><b>{s.title ?? te('qaDim', s.dimension)}</b><p className="text-xs text-slate-600">{s.suggestion ?? s.text}</p></li>)}</ol></> : <Spinner />}
      </Card>
    </div>
  )
}
