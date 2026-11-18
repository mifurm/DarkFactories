import { FlaskConical, Play, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { BarSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat, Tabs, cx, inputCls } from '../../lib/ui'

interface RunRow { id: string; status?: string; suite: string; config_id: string; mode?: string; stress?: boolean; ts: number; totals?: { scenarios: number; passed: number; failed: number; pass_rate: number }; dimensions?: Record<string, number>; duration_s?: number; cost_usd?: number; gate?: Gate | null; progress?: number; total?: number }
interface Check { name: string; group: string; ok: boolean; detail: string }
interface Result { id: string; title: string; category: string; passed: boolean; scores: Record<string, number>; checks: Check[]; turns: number; errors: string[]; status: string; handoff: string | null; qa_overall: number | null }
interface Report { run_id: string; suite: string; config_id: string; config_name: string; mode: string; stress: boolean; duration_s: number; cost_usd: number; totals: { scenarios: number; passed: number; failed: number; pass_rate: number; avg_turn_ms: number }; dimensions: Record<string, number>; by_category: Record<string, { total: number; passed: number }>; results: Result[]; failures: { id: string; title: string; failed_checks: string[] }[]; status: string; gate?: Gate | null; progress?: number; total?: number }
interface Gate { passed: boolean; reasons: string[]; thresholds: Record<string, unknown>; comparison: { deltas: Record<string, number>; regressions: { id: string; title: string; failed_checks: string[] }[] } }
interface Scenario { id: string; title: string; category: string; language: string; customer: string | null; turns: number; suites: string[] }

const DIM_TONE: Record<string, string> = { resolution: 'blue', accuracy: 'green', policy: 'amber', safety: 'red' }

export default function EvalPage() {
  const [tab, setTab] = useState('runs')
  const [suite, setSuite] = useState('core')
  const [stress, setStress] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const runs = useApi<RunRow[]>('/api/evals/runs?limit=15', { refreshMs: 4000 })
  const report = useApi<Report>(sel ? `/api/evals/runs/${sel}` : null, { refreshMs: sel ? 3000 : undefined })
  const variants = useApi<Record<string, string>>('/api/evals/variants')
  const scenarios = useApi<Scenario[]>('/api/evals/scenarios?suite=all')
  const [gateRun, setGateRun] = useState<string | null>(null)
  const gate = useApi<Report>(gateRun ? `/api/evals/runs/${gateRun}` : null, { refreshMs: gateRun ? 3000 : undefined })
  const [variant, setVariant] = useState('remove_refund_cap')
  const [play, setPlay] = useState<Record<string, { status: string; conversation_id?: string; passed?: boolean }>>({})
  const poll = useRef<ReturnType<typeof setInterval> | null>(null)

  const start = async () => {
    setBusy(true); setMsg(null)
    try { const r = await api<{ run_id: string }>('/api/evals/runs', { body: { suite, stress, concurrency: 4 } }); setSel(r.run_id); runs.reload() } catch (e) { setMsg(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } finally { setBusy(false) }
  }
  const runGate = async (broken: boolean) => {
    setBusy(true); setMsg(null)
    try { const r = await api<{ run_id: string }>('/api/evals/gate', { body: broken ? { broken_variant: variant, suite: 'gate' } : { suite: 'gate' } }); setGateRun(r.run_id) } catch (e) { setMsg(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } finally { setBusy(false) }
  }
  const playOne = async (id: string) => {
    setPlay((p) => ({ ...p, [id]: { status: 'running' } }))
    await api('/api/evals/play', { body: { scenario_id: id } })
    if (poll.current) clearInterval(poll.current)
    poll.current = setInterval(async () => {
      const s = await api<{ status: string; conversation_id?: string; passed?: boolean }>(`/api/evals/play/${id}`)
      setPlay((p) => ({ ...p, [id]: s }))
      if (s.status !== 'running' && poll.current) clearInterval(poll.current)
    }, 1500)
  }
  useEffect(() => () => { if (poll.current) clearInterval(poll.current) }, [])
  useEffect(() => { if (!sel && runs.data?.length) setSel(runs.data[0].id) }, [runs.data, sel])

  const r = report.data
  const running = r?.status === 'running'
  const g = gate.data
  return (
    <div>
      <PageHeader icon={FlaskConical} title="Evaluation & simulation harness" subtitle="≥ 30 scripted + persona-simulated scenarios scored on resolution, accuracy, policy compliance and safety; a regression gate that blocks a deliberately broken prompt; and a red-team pack."
        actions={<><select aria-label="Suite" value={suite} onChange={(e) => setSuite(e.target.value)} className={cx(inputCls, 'w-36')}>{['core', 'gate', 'smoke', 'redteam', 'all'].map((s) => <option key={s}>{s}</option>)}</select><label className="flex items-center gap-1.5 text-xs text-slate-600"><input type="checkbox" checked={stress} onChange={(e) => setStress(e.target.checked)} className="accent-rose-600" />stress (guard off + gullible model)</label><Button variant="primary" icon={Play} busy={busy} onClick={start}>Run suite</Button></>} />
      {msg && <div role="alert" className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{msg}</div>}
      <Tabs tabs={[{ id: 'runs', label: 'Runs & report' }, { id: 'gate', label: 'CI gate (broken prompt)' }, { id: 'play', label: 'Play scenarios live' }]} value={tab} onChange={setTab} />
      {tab === 'runs' && (
        <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Card title="Recent runs" pad={false}>
            {runs.loading && !runs.data ? <Spinner /> : !runs.data?.length ? <div className="p-4"><Empty>No runs yet — press “Run suite”.</Empty></div> : (
              <ul className="divide-y divide-slate-100">{runs.data.map((x) => <li key={x.id}><button type="button" onClick={() => setSel(x.id)} className={cx('w-full px-4 py-2.5 text-left hover:bg-blue-50/60', sel === x.id && 'bg-blue-50')}><div className="flex items-center justify-between"><span className="text-sm font-medium">{x.suite}{x.stress ? ' · stress' : ''}</span>{x.status === 'running' ? <Badge tone="amber">{x.progress}/{x.total}</Badge> : <Badge tone={(x.totals?.pass_rate ?? 0) >= 0.9 ? 'green' : 'amber'}>{x.totals?.passed}/{x.totals?.scenarios}</Badge>}</div><div className="text-[11px] text-slate-500">{x.config_id} · {fmt.dt(x.ts)}{x.gate && <> · gate <b className={x.gate.passed ? 'text-emerald-700' : 'text-rose-700'}>{x.gate.passed ? 'pass' : 'FAIL'}</b></>}</div></button></li>)}</ul>
            )}
          </Card>
          <div className="space-y-4">
            {!sel ? <Empty>Select a run.</Empty> : report.loading && !r ? <Spinner /> : report.error ? <ErrorBox error={report.error} /> : r && (running ? <Card title="Running…"><Progress value={r.progress ?? 0} max={r.total ?? 1} /><p className="mt-2 text-sm text-slate-600">{r.progress}/{r.total} scenarios complete.</p></Card> : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                  <Stat label="Pass rate" value={fmt.pct(r.totals.pass_rate, 0)} hint={`${r.totals.passed}/${r.totals.scenarios} scenarios`} tone={r.totals.pass_rate >= 0.9 ? 'green' : 'amber'} />
                  {['resolution', 'accuracy', 'policy', 'safety'].map((d) => <Stat key={d} label={d} value={(r.dimensions[d] ?? 0).toFixed(2)} tone={DIM_TONE[d]} hint={d === 'safety' || d === 'policy' ? 'must be 1.00' : undefined} />)}
                </div>
                <Card title={`Report · ${r.run_id}`} subtitle={`${r.mode} · config ${r.config_id} (${r.config_name}) · ${r.duration_s}s · $${r.cost_usd}${r.stress ? ' · STRESS' : ''}`} actions={<a className="text-sm font-medium text-blue-700 hover:underline" href={`/api/evals/runs/${r.run_id}/report.md`} target="_blank" rel="noreferrer">Markdown report</a>}>
                  <BarSeries data={Object.entries(r.by_category).map(([k, v]) => ({ cat: k, passed: v.passed, failed: v.total - v.passed }))} x="cat" bars={[{ key: 'passed', color: '#16a34a' }, { key: 'failed', color: '#dc2626' }]} stacked height={170} />
                </Card>
                <Card title="Scenarios" pad={false}>
                  <DataTable dense rows={r.results} rowKey={(x) => x.id} cols={[
                    { key: 'i', header: 'ID', render: (x) => <span className="font-mono text-xs">{x.id}</span> },
                    { key: 't', header: 'Scenario', render: (x) => <span className="text-sm">{x.title}</span> },
                    { key: 'p', header: 'Result', render: (x) => <Badge tone={x.passed ? 'green' : 'red'}>{x.passed ? 'PASS' : 'FAIL'}</Badge> },
                    { key: 's', header: 'Res · Acc · Pol · Saf', render: (x) => <span className="font-mono text-xs">{['resolution', 'accuracy', 'policy', 'safety'].map((d) => x.scores[d].toFixed(1)).join(' · ')}</span> },
                    { key: 'f', header: 'Failed checks', render: (x) => <span className="text-xs text-rose-700">{x.checks.filter((c) => !c.ok).map((c) => c.name).slice(0, 2).join('; ') || (x.errors[0] ?? '')}</span> },
                  ]} />
                </Card>
              </>
            ))}
          </div>
        </div>
      )}
      {tab === 'gate' && (
        <div className="space-y-4">
          <Card title="Regression gate" subtitle="a candidate configuration must keep resolution/accuracy and 100 % policy + safety versus the active baseline; otherwise promotion is blocked (CI exit code ≠ 0)">
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={ShieldCheck} busy={busy} onClick={() => runGate(false)}>Gate the active config</Button>
              <span className="text-slate-300">|</span>
              <select aria-label="Broken variant" value={variant} onChange={(e) => setVariant(e.target.value)} className={cx(inputCls, 'w-80')}>{Object.entries(variants.data ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <Button variant="danger" icon={ShieldAlert} busy={busy} onClick={() => runGate(true)}>Inject broken prompt & gate</Button>
            </div>
          </Card>
          {gateRun && (gate.loading && !g ? <Spinner /> : g?.status === 'running' ? <Card title="Running gate suite…"><Progress value={g.progress ?? 0} max={g.total ?? 1} /></Card> : g?.gate && (
            <Card title={<span className="flex items-center gap-2">CI gate <Badge tone={g.gate.passed ? 'green' : 'red'}>{g.gate.passed ? 'PASSED' : 'FAILED — promotion blocked'}</Badge></span>} subtitle={`candidate ${g.config_id} (${g.config_name}) vs baseline ${(g.gate.comparison as { baseline?: string }).baseline ?? '—'}`}>
              {g.gate.reasons.length > 0 && <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-rose-700">{g.gate.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5"><Stat label="Pass rate" value={fmt.pct(g.totals.pass_rate, 0)} tone={g.gate.passed ? 'green' : 'red'} />{['resolution', 'accuracy', 'policy', 'safety'].map((d) => <Stat key={d} label={`${d} (Δ ${(g.gate!.comparison.deltas[d] ?? 0).toFixed(2)})`} value={(g.dimensions[d] ?? 0).toFixed(2)} />)}</div>
              {g.gate.comparison.regressions.length > 0 && <div className="mt-3"><div className="mb-1 text-xs font-medium text-slate-500">Regressions vs baseline</div><ul className="space-y-1 text-sm">{g.gate.comparison.regressions.map((x) => <li key={x.id}><Badge tone="red">{x.id}</Badge> {x.title} <span className="text-xs text-slate-500">— {x.failed_checks.join('; ')}</span></li>)}</ul></div>}
            </Card>
          ))}
        </div>
      )}
      {tab === 'play' && (
        <Card title="Play a scripted customer against the live app" subtitle="the conversation appears in the agent console, supervisor console and QA workbench" pad={false}>
          {scenarios.loading && !scenarios.data ? <Spinner /> : (
            <DataTable dense rows={(scenarios.data ?? []).filter((s) => !s.id.startsWith('RT'))} rowKey={(s) => s.id} cols={[
              { key: 'i', header: 'ID', render: (s) => <span className="font-mono text-xs">{s.id}</span> },
              { key: 't', header: 'Scenario', render: (s) => s.title },
              { key: 'c', header: 'Category', render: (s) => <Badge>{s.category}</Badge> },
              { key: 'l', header: 'Lang', render: (s) => s.language.toUpperCase() },
              { key: 'p', header: '', render: (s) => <div className="flex items-center gap-2"><Button size="sm" icon={Play} disabled={play[s.id]?.status === 'running'} onClick={() => playOne(s.id)}>Play</Button>{play[s.id]?.status === 'done' && <Badge tone={play[s.id].passed ? 'green' : 'amber'}>{play[s.id].passed ? 'passed' : 'finished'}</Badge>}{play[s.id]?.status === 'running' && <Badge tone="blue">running…</Badge>}</div> },
            ]} />
          )}
        </Card>
      )}
    </div>
  )
}
