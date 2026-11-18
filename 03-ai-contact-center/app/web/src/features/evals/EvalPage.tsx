import { FlaskConical, Play, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi, withLang } from '../../lib/api'
import { BarSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat, Tabs, cx, inputCls } from '../../lib/ui'
import { localizeCheck, localizeGateReason, localizeScenarioTitle } from './checks'

interface RunRow { id: string; status?: string; suite: string; config_id: string; mode?: string; stress?: boolean; ts: number; totals?: { scenarios: number; passed: number; failed: number; pass_rate: number }; dimensions?: Record<string, number>; duration_s?: number; cost_usd?: number; gate?: Gate | null; progress?: number; total?: number }
interface Check { name: string; group: string; ok: boolean; detail: string }
interface Result { id: string; title: string; category: string; passed: boolean; scores: Record<string, number>; checks: Check[]; turns: number; errors: string[]; status: string; handoff: string | null; qa_overall: number | null }
interface Report { run_id: string; suite: string; config_id: string; config_name: string; mode: string; stress: boolean; duration_s: number; cost_usd: number; totals: { scenarios: number; passed: number; failed: number; pass_rate: number; avg_turn_ms: number }; dimensions: Record<string, number>; by_category: Record<string, { total: number; passed: number }>; results: Result[]; failures: { id: string; title: string; failed_checks: string[] }[]; status: string; gate?: Gate | null; progress?: number; total?: number }
interface Gate { passed: boolean; reasons: string[]; thresholds: Record<string, unknown>; comparison: { deltas: Record<string, number>; regressions: { id: string; title: string; failed_checks: string[] }[] } }
interface Scenario { id: string; title: string; category: string; language: string; customer: string | null; turns: number; suites: string[] }

const DIM_TONE: Record<string, string> = { resolution: 'blue', accuracy: 'green', policy: 'amber', safety: 'red' }
const DIMS = ['resolution', 'accuracy', 'policy', 'safety']
const SUITES = ['core', 'gate', 'smoke', 'redteam', 'all', 'pl']
const GATE_SUITES = ['gate', 'smoke', 'pl']
/** The Polish UI also offers the compact Polish suites (8 and 21 scenarios): a quick Polish run for a demo, and a gate that is affordable against a real model. */
const PL_SUITES = ['pl-smoke', 'pl-gate']

export default function EvalPage() {
  const i18n = useI18n()
  const { t, te, ts, tl, fmt, lang, compare } = i18n
  const [tab, setTab] = useState('runs')
  const [suite, setSuite] = useState(lang === 'pl' ? 'pl' : 'core')
  const [gateSuite, setGateSuite] = useState(lang === 'pl' ? 'pl' : 'gate')
  const [stress, setStress] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [scenarioLang, setScenarioLang] = useState(lang === 'pl' ? 'pl' : 'all')
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
    try { const r = await api<{ run_id: string }>('/api/evals/runs', { body: { suite, stress, concurrency: 4 } }); setSel(r.run_id); runs.reload() } catch (e) { setMsg(describeError(e)) } finally { setBusy(false) }
  }
  const runGate = async (broken: boolean) => {
    setBusy(true); setMsg(null)
    try { const r = await api<{ run_id: string }>('/api/evals/gate', { body: broken ? { broken_variant: variant, suite: gateSuite } : { suite: gateSuite } }); setGateRun(r.run_id) } catch (e) { setMsg(describeError(e)) } finally { setBusy(false) }
  }
  const playOne = async (id: string) => {
    setPlay((p) => ({ ...p, [id]: { status: 'running' } }))
    try { await api('/api/evals/play', { body: { scenario_id: id } }) } catch (e) { setPlay((p) => ({ ...p, [id]: { status: 'error' } })); setMsg(describeError(e)); return }
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
  const title = (id: string, text: string) => localizeScenarioTitle(id, text, i18n)
  const langs = [...new Set((scenarios.data ?? []).filter((s) => !s.id.startsWith('RT')).map((s) => s.language))].sort((a, b) => compare(fmt.languageName(a, a), fmt.languageName(b, b)))
  const shown = (scenarios.data ?? []).filter((s) => !s.id.startsWith('RT') && (scenarioLang === 'all' || s.language === scenarioLang))
  return (
    <div>
      <PageHeader icon={FlaskConical} title={t('Evaluation & simulation harness')} subtitle={t('≥ 30 scripted + persona-simulated scenarios scored on resolution, accuracy, policy compliance and safety; a regression gate that blocks a deliberately broken prompt; and a red-team pack.')}
        actions={<><select aria-label={t('Suite')} value={suite} onChange={(e) => setSuite(e.target.value)} className={cx(inputCls, lang === 'pl' ? 'w-64' : 'w-36')}>{(lang === 'pl' ? [...SUITES, ...PL_SUITES] : SUITES).map((s) => <option key={s} value={s}>{te('suite', s)}</option>)}</select><label className="flex items-center gap-1.5 text-xs text-slate-600"><input type="checkbox" checked={stress} onChange={(e) => setStress(e.target.checked)} className="accent-rose-600" />{t('stress (guard off + gullible model)')}</label><Button variant="primary" icon={Play} busy={busy} onClick={start}>{t('Run suite')}</Button></>} />
      {msg && <div role="alert" className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{msg}</div>}
      <Tabs tabs={[{ id: 'runs', label: t('Runs & report') }, { id: 'gate', label: t('CI gate (broken prompt)') }, { id: 'play', label: t('Play scenarios live') }]} value={tab} onChange={setTab} />
      {tab === 'runs' && (
        <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Card title={t('Recent runs')} pad={false}>
            {runs.loading && !runs.data ? <Spinner /> : !runs.data?.length ? <div className="p-4"><Empty>{t('No runs yet — press “Run suite”.')}</Empty></div> : (
              <ul className="divide-y divide-slate-100">{runs.data.map((x) => <li key={x.id}><button type="button" onClick={() => setSel(x.id)} className={cx('w-full px-4 py-2.5 text-left hover:bg-blue-50/60', sel === x.id && 'bg-blue-50')}><div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">{te('suite', x.suite)}{x.stress ? ` · ${t('stress')}` : ''}</span>{x.status === 'running' ? <Badge tone="amber">{x.progress}/{x.total}</Badge> : <Badge tone={(x.totals?.pass_rate ?? 0) >= 0.9 ? 'green' : 'amber'}>{x.totals?.passed}/{x.totals?.scenarios}</Badge>}</div><div className="text-[11px] text-slate-500">{x.config_id} · {fmt.dt(x.ts)}{x.gate && <> · {t('gate')} <b className={x.gate.passed ? 'text-emerald-700' : 'text-rose-700'}>{x.gate.passed ? t('pass') : t('FAIL')}</b></>}</div></button></li>)}</ul>
            )}
          </Card>
          <div className="space-y-4">
            {!sel ? <Empty>{t('Select a run.')}</Empty> : report.loading && !r ? <Spinner /> : report.error ? <ErrorBox error={report.error} /> : r && (running ? <Card title={t('Running…')}><Progress value={r.progress ?? 0} max={r.total ?? 1} /><p className="mt-2 text-sm text-slate-600">{t('{progress}/{total} scenarios complete.', { progress: r.progress, total: r.total })}</p></Card> : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                  <Stat label={t('Pass rate')} value={fmt.percent(r.totals.pass_rate, 0)} hint={t('{passed}/{scenarios} scenarios', { passed: r.totals.passed, scenarios: r.totals.scenarios })} tone={r.totals.pass_rate >= 0.9 ? 'green' : 'amber'} />
                  {DIMS.map((d) => <Stat key={d} label={te('evalDim', d)} value={fmt.fixed(r.dimensions[d] ?? 0, 2)} tone={DIM_TONE[d]} hint={d === 'safety' || d === 'policy' ? t('must be 1.00') : undefined} />)}
                </div>
                <Card title={t('Report · {id}', { id: r.run_id })} subtitle={`${te('evalMode', r.mode)} · ${t('config {id} ({name})', { id: r.config_id, name: ts(r.config_name) })} · ${fmt.secs(r.duration_s)} · ${fmt.usd(r.cost_usd, 2)}${r.stress ? ` · ${t('STRESS')}` : ''}`} actions={<a className="text-sm font-medium text-blue-700 hover:underline" href={withLang(`/api/evals/runs/${r.run_id}/report.md`)} target="_blank" rel="noreferrer">{t('Markdown report')}</a>}>
                  <BarSeries data={Object.entries(r.by_category).map(([k, v]) => ({ cat: te('evalCategory', k), passed: v.passed, failed: v.total - v.passed }))} x="cat" bars={[{ key: 'passed', name: te('evalResult', 'passed'), color: '#16a34a' }, { key: 'failed', name: te('evalResult', 'failed'), color: '#dc2626' }]} stacked height={170} />
                </Card>
                <Card title={t('Scenarios')} pad={false}>
                  <DataTable dense rows={r.results} rowKey={(x) => x.id} cols={[
                    { key: 'i', header: t('ID'), render: (x) => <span className="font-mono text-xs">{x.id}</span> },
                    { key: 't', header: t('Scenario'), render: (x) => <span className="text-sm">{title(x.id, x.title)}</span> },
                    { key: 'p', header: t('Result'), render: (x) => <Badge tone={x.passed ? 'green' : 'red'}>{x.passed ? t('PASS') : t('FAIL')}</Badge> },
                    { key: 's', header: t('Res · Acc · Pol · Saf'), render: (x) => <span className="font-mono text-xs">{DIMS.map((d) => fmt.fixed(x.scores[d], 1)).join(' · ')}</span> },
                    { key: 'f', header: t('Failed checks'), render: (x) => <span className="text-xs text-rose-700">{x.checks.filter((c) => !c.ok).map((c) => localizeCheck(c.name, i18n)).slice(0, 2).join('; ') || (x.errors[0] ?? '')}</span> },
                  ]} />
                </Card>
              </>
            ))}
          </div>
        </div>
      )}
      {tab === 'gate' && (
        <div className="space-y-4">
          <Card title={t('Regression gate')} subtitle={t('a candidate configuration must keep resolution/accuracy and 100 % policy + safety versus the active baseline; otherwise promotion is blocked (CI exit code ≠ 0)')}>
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label={t('Gate suite')} value={gateSuite} onChange={(e) => setGateSuite(e.target.value)} className={cx(inputCls, lang === 'pl' ? 'w-64' : 'w-32')}>{(lang === 'pl' ? [...GATE_SUITES, ...PL_SUITES] : GATE_SUITES).map((s) => <option key={s} value={s}>{te('suite', s)}</option>)}</select>
              <Button icon={ShieldCheck} busy={busy} onClick={() => runGate(false)}>{t('Gate the active config')}</Button>
              <span className="text-slate-300">|</span>
              <select aria-label={t('Broken variant')} value={variant} onChange={(e) => setVariant(e.target.value)} className={cx(inputCls, 'w-80 max-w-full')}>{Object.entries(variants.data ?? {}).map(([k, v]) => <option key={k} value={k}>{tl('brokenVariant', k, v)}</option>)}</select>
              <Button variant="danger" icon={ShieldAlert} busy={busy} onClick={() => runGate(true)}>{t('Inject broken prompt & gate')}</Button>
            </div>
          </Card>
          {gateRun && (gate.loading && !g ? <Spinner /> : g?.status === 'running' ? <Card title={t('Running gate suite…')}><Progress value={g.progress ?? 0} max={g.total ?? 1} /></Card> : g?.gate && (
            <Card title={<span className="flex flex-wrap items-center gap-2">{t('CI gate')} <Badge tone={g.gate.passed ? 'green' : 'red'}>{g.gate.passed ? t('PASSED') : t('FAILED — promotion blocked')}</Badge></span>} subtitle={t('candidate {id} ({name}) vs baseline {baseline}', { id: g.config_id, name: ts(g.config_name), baseline: (g.gate.comparison as { baseline?: string }).baseline ?? '—' })}>
              {g.gate.reasons.length > 0 && <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-rose-700">{g.gate.reasons.map((x, i) => <li key={i}>{localizeGateReason(x, i18n)}</li>)}</ul>}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5"><Stat label={t('Pass rate')} value={fmt.percent(g.totals.pass_rate, 0)} tone={g.gate.passed ? 'green' : 'red'} />{DIMS.map((d) => <Stat key={d} label={t('{dimension} (Δ {delta})', { dimension: te('evalDim', d), delta: fmt.fixed(g.gate!.comparison.deltas[d] ?? 0, 2) })} value={fmt.fixed(g.dimensions[d] ?? 0, 2)} />)}</div>
              {g.gate.comparison.regressions.length > 0 && <div className="mt-3"><div className="mb-1 text-xs font-medium text-slate-500">{t('Regressions vs baseline')}</div><ul className="space-y-1 text-sm">{g.gate.comparison.regressions.map((x) => <li key={x.id}><Badge tone="red">{x.id}</Badge> {title(x.id, x.title)} <span className="text-xs text-slate-500">— {x.failed_checks.map((c) => localizeCheck(c, i18n)).join('; ')}</span></li>)}</ul></div>}
            </Card>
          ))}
        </div>
      )}
      {tab === 'play' && (
        <Card title={t('Play a scripted customer against the live app')} subtitle={t('the conversation appears in the agent console, supervisor console and QA workbench')} actions={<select aria-label={t('Scenario language')} value={scenarioLang} onChange={(e) => setScenarioLang(e.target.value)} className={cx(inputCls, 'w-40')}><option value="all">{t('All languages')}</option>{langs.map((l) => <option key={l} value={l}>{fmt.languageName(l, l.toUpperCase())}</option>)}</select>} pad={false}>
          {scenarios.loading && !scenarios.data ? <Spinner /> : (
            <DataTable dense rows={shown} rowKey={(s) => s.id} cols={[
              { key: 'i', header: t('ID'), render: (s) => <span className="font-mono text-xs">{s.id}</span> },
              { key: 't', header: t('Scenario'), render: (s) => <span lang={s.language}>{title(s.id, s.title)}</span> },
              { key: 'c', header: t('Category'), render: (s) => <Badge>{te('evalCategory', s.category)}</Badge> },
              { key: 'l', header: t('Lang'), render: (s) => s.language.toUpperCase() },
              { key: 'p', header: '', render: (s) => <div className="flex items-center gap-2"><Button size="sm" icon={Play} disabled={play[s.id]?.status === 'running'} onClick={() => playOne(s.id)}>{t('Play')}</Button>{play[s.id]?.status === 'done' && <Badge tone={play[s.id].passed ? 'green' : 'amber'}>{play[s.id].passed ? t('passed') : t('finished')}</Badge>}{play[s.id]?.status === 'running' && <Badge tone="blue">{t('running…')}</Badge>}</div> },
            ]} />
          )}
        </Card>
      )}
    </div>
  )
}
