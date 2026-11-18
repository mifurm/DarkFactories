import { CalendarClock, Download } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, fmt, useApi } from '../../lib/api'
import { ComboSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, ErrorBox, PageHeader, Slider, Spinner, Stat, cx, inputCls } from '../../lib/ui'

interface QueueInfo { queue: string; name: string; aht_s: number; sl_seconds: number; avg_daily: number; last_date: string }
interface Hist { daily: { date: string; dow: string; total: number; event: string | null }[]; heatmap: number[][]; intervals: string[] }
interface Fc { days: { offset: number; date: string; dow_label: string; total: number; low: number; high: number; promo: boolean }[]; params: Record<string, number>; band_pct: number; backtest: Record<string, { mape_daily: number; mape_interval: number; wape_interval: number }>; event_uplift: number | null }
interface BtQ { summary: Record<string, { mape_daily: number; wape_interval: number }>; improvement_pct: number; improvement_daily_pct: number; folds: unknown[]; targets: { mape_daily_max: number; min_improvement_vs_naive_pct: number } }
interface Bt { queues: Record<string, BtQ> }
interface Sim { sl_mean: number; sl_min: number; sl_max: number; asa_s: number; occupancy: number; max_queue: number; meets_target: boolean; sl_target: number; t_s: number; sl_by_interval: (number | null)[]; replications: number }
interface PlanDay { offset: number; date: string; dow: string; forecast_total: number; plan: { human_volume: number[]; agents_required: number[]; heads_scheduled: number[]; ai_concurrent_sessions: number[]; ai_voice_minutes: number[]; aht_human_s: number; totals: Record<string, number> }; schedule: { roster: { start: string; end: string; agents: number }[]; agents_total: number; coverage: number[]; requirement: number[]; paid_hours: number; uncovered_intervals: number[] }; simulation?: Sim }
interface Plan { days: PlanDay[]; fte_week: number; week_paid_hours: number; sl_seconds: number; intervals: string[] }
interface Sweep { rows: { containment: number; fte_week: number; peak_agents: number; peak_ai_sessions: number; ai_voice_minutes_week: number; human_contacts_week: number }[] }
interface Erl { traffic_erlangs: number; agents_required: number; service_level: number; p_wait: number; asa_s: number; occupancy: number }

export default function WfmPage() {
  const queues = useApi<QueueInfo[]>('/api/wfm/queues')
  const [queue, setQueue] = useState('delivery')
  const [containment, setContainment] = useState(0.3)
  const [slTarget, setSlTarget] = useState(0.8)
  const [shrink, setShrink] = useState(0.15)
  const [dayOffset, setDayOffset] = useState(2)
  const [promo, setPromo] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const hist = useApi<Hist>(`/api/wfm/history?queue=${queue}`)
  const fc = useApi<Fc>(`/api/wfm/forecast?queue=${queue}${promo ? `&promo=${dayOffset}` : ''}`)
  const bt = useApi<Bt>('/api/wfm/backtest')
  const sweep = useApi<Sweep>(`/api/wfm/sweep?queue=${queue}&sl_target=${slTarget}`)

  useEffect(() => {
    const t = setTimeout(async () => {
      try { setPlan(await api<Plan>('/api/wfm/plan', { body: { queue, containment, sl_target: slTarget, shrinkage: shrink, day_offset: dayOffset, promo_offsets: promo ? [dayOffset] : [], simulate: true } })); setErr(null) } catch (e) { setErr(e) }
    }, 200)
    return () => clearTimeout(t)
  }, [queue, containment, slTarget, shrink, dayOffset, promo])

  const day = plan?.days.find((d) => d.offset === dayOffset)
  const series = useMemo(() => {
    if (!hist.data || !fc.data) return []
    const h = hist.data.daily.slice(-21).map((d) => ({ date: d.date.slice(5), actual: d.total, forecast: null as number | null, low: null as number | null, high: null as number | null }))
    const f = fc.data.days.map((d) => ({ date: d.date.slice(5), actual: null as number | null, forecast: d.total, low: d.low, high: d.high }))
    return [...h, ...f]
  }, [hist.data, fc.data])
  const rows = useMemo(() => (day && plan ? plan.intervals.map((label, i) => ({ t: label, contacts: day.plan.human_volume[i], required: day.plan.agents_required[i], scheduled: day.schedule.coverage[i], ai: day.plan.ai_concurrent_sessions[i], sl: day.simulation?.sl_by_interval[i] != null ? Math.round((day.simulation.sl_by_interval[i] as number) * 100) : null })).filter((_, i) => i >= 12 && i <= 46) : []), [day, plan])
  const q = queues.data?.find((x) => x.queue === queue)

  return (
    <div>
      <PageHeader icon={CalendarClock} title="Workforce forecast & staffing" subtitle="Interval forecast (Holt-Winters × intraday profile vs seasonal-naive), Erlang-C requirement, AI-vs-human capacity with containment what-ifs, schedule recommendation validated by a discrete-event simulation."
        actions={<><a href={`/api/wfm/export/forecast.csv?queue=${queue}`}><Button icon={Download}>Forecast CSV</Button></a><a href={`/api/wfm/export/plan.csv?queue=${queue}&containment=${containment}&day_offset=${dayOffset}`}><Button icon={Download}>Plan CSV</Button></a></>} />
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card title="Planner">
          <div className="space-y-3">
            <label className="block text-xs font-medium text-slate-600">Queue<select value={queue} onChange={(e) => setQueue(e.target.value)} className={cx(inputCls, 'mt-1')}>{(queues.data ?? []).map((x) => <option key={x.queue} value={x.queue}>{x.name} · {x.avg_daily}/day</option>)}</select></label>
            <Slider label="AI containment (what-if)" value={containment} min={0} max={0.6} step={0.05} onChange={setContainment} format={(v) => fmt.pct(v, 0)} />
            <Slider label="Service-level target" value={slTarget} min={0.6} max={0.95} step={0.01} onChange={setSlTarget} format={(v) => `${Math.round(v * 100)}% in ${q?.sl_seconds ?? 120}s`} />
            <Slider label="Shrinkage" value={shrink} min={0.05} max={0.3} step={0.01} onChange={setShrink} format={(v) => fmt.pct(v, 0)} />
            <label className="block text-xs font-medium text-slate-600">Plan day<select value={dayOffset} onChange={(e) => setDayOffset(Number(e.target.value))} className={cx(inputCls, 'mt-1')}>{(fc.data?.days ?? []).map((d) => <option key={d.offset} value={d.offset}>{d.dow_label} {d.date}</option>)}</select></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={promo} onChange={(e) => setPromo(e.target.checked)} className="accent-blue-600" />Planned promotion on that day <span className="text-xs text-slate-400">(uplift learned from past events)</span></label>
          </div>
        </Card>
        <div className="space-y-4">
          {err ? <ErrorBox error={err} /> : null}
          {!plan || !day ? <Spinner /> : (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                <Stat label="Human FTE (week)" value={plan.fte_week} hint={`${plan.week_paid_hours} paid hours`} tone="blue" />
                <Stat label="Peak agents on phones" value={day.plan.totals.peak_agents} hint={`${day.dow} ${day.date}`} />
                <Stat label="Human contacts / day" value={fmt.num(day.plan.totals.human_contacts)} hint={`of ${fmt.num(day.plan.totals.contacts)} · ${fmt.num(day.plan.totals.ai_contacts)} contained by AI`} />
                <Stat label="Peak concurrent AI sessions" value={day.plan.totals.peak_ai_sessions.toFixed(1)} hint={`${fmt.num(day.plan.totals.ai_voice_minutes)} AI voice min/day`} tone="green" />
                <Stat label="Simulated service level" value={day.simulation ? `${Math.round(day.simulation.sl_mean * 100)}%` : '—'} hint={day.simulation ? `target ${Math.round(day.simulation.sl_target * 100)}% · min ${Math.round(day.simulation.sl_min * 100)}%` : undefined} tone={day.simulation?.meets_target ? 'green' : 'red'} />
              </div>
              <Card title={`Requirement vs schedule — ${day.dow} ${day.date}`} subtitle="Erlang-C agents required per 30-minute interval (bars: human contacts) vs scheduled coverage; AI sessions run in parallel"><ComboSeries data={rows} x="t" bars={[{ key: 'contacts', name: 'human contacts' }]} lines={[{ key: 'required', name: 'agents required', color: '#dc2626' }, { key: 'scheduled', name: 'scheduled coverage', color: '#16a34a' }, { key: 'ai', name: 'concurrent AI sessions', color: '#7c3aed', dashed: true }]} height={280} /></Card>
            </>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Volume forecast (daily)" subtitle={`Holt-Winters; ±${fc.data?.band_pct ?? '…'}% band from backtest error`}>
              {fc.error ? <ErrorBox error={fc.error} /> : <LineSeries data={series} x="date" lines={[{ key: 'actual', name: 'actual' }, { key: 'forecast', name: 'forecast', color: '#16a34a' }, { key: 'high', name: 'upper', color: '#94a3b8', dashed: true }, { key: 'low', name: 'lower', color: '#94a3b8', dashed: true }]} height={240} />}
            </Card>
            <Card title="Containment what-if" subtitle="weekly human FTE and the AI capacity Azure must provide"><ComboSeries data={(sweep.data?.rows ?? []).map((r) => ({ ...r, c: `${Math.round(r.containment * 100)}%` }))} x="c" bars={[{ key: 'fte_week', name: 'human FTE / week', color: '#2563eb' }]} lines={[{ key: 'peak_ai_sessions', name: 'peak AI sessions', color: '#7c3aed' }]} height={240} /></Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Forecast accuracy (rolling-origin backtest)" subtitle="WFM planners judge forecasts by MAPE against a naive baseline" pad={false}>
              <DataTable dense rows={Object.entries(bt.data?.queues ?? {}).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} cols={[{ key: 'k', header: 'Queue', render: (r) => <b>{r.k}</b> }, { key: 'a', header: 'MAPE daily (HW)', align: 'right', render: (r) => fmt.pct(r.summary.hw.mape_daily, 1) }, { key: 'b', header: 'naive', align: 'right', render: (r) => fmt.pct(r.summary.naive.mape_daily, 1) }, { key: 'c', header: 'WAPE 30-min (HW)', align: 'right', render: (r) => fmt.pct(r.summary.hw.wape_interval, 1) }, { key: 'd', header: 'naive', align: 'right', render: (r) => fmt.pct(r.summary.naive.wape_interval, 1) }, { key: 'e', header: 'better by', align: 'right', render: (r) => <Badge tone={r.improvement_pct >= r.targets.min_improvement_vs_naive_pct ? 'green' : 'amber'}>{r.improvement_pct}%</Badge> }]} />
            </Card>
            <Card title="Recommended roster" subtitle={day ? `${day.schedule.agents_total} agents · ${day.schedule.paid_hours} paid hours · shrinkage ${Math.round(shrink * 100)}%` : undefined} pad={false}>
              <DataTable dense rows={day?.schedule.roster ?? []} rowKey={(r) => r.start} cols={[{ key: 's', header: 'Shift', render: (r) => <b>{r.start}–{r.end}</b> }, { key: 'a', header: 'Agents', align: 'right', render: (r) => r.agents }]} />
            </Card>
          </div>
          <ErlangCard />
        </div>
      </div>
    </div>
  )
}

function ErlangCard() {
  const [calls, setCalls] = useState(100)
  const [aht, setAht] = useState(180)
  const [t, setT] = useState(20)
  const [sl, setSl] = useState(0.8)
  const e = useApi<Erl>(`/api/wfm/erlang?calls=${calls}&aht=${aht}&t=${t}&sl=${sl}`)
  return (
    <Card title="Erlang-C calculator" subtitle="numerically verified against exact references (tests)">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Slider label="Calls / 30 min" value={calls} min={10} max={500} onChange={setCalls} /><Slider label="AHT (s)" value={aht} min={60} max={900} step={10} onChange={setAht} /><Slider label="Answer within (s)" value={t} min={5} max={180} step={5} onChange={setT} /><Slider label="Service level" value={sl} min={0.5} max={0.99} step={0.01} onChange={setSl} format={(v) => fmt.pct(v, 0)} /></div>
      {e.data && <div className="mt-3 grid grid-cols-2 gap-3 text-center md:grid-cols-5"><Stat label="Traffic" value={`${e.data.traffic_erlangs} E`} /><Stat label="Agents required" value={e.data.agents_required} tone="blue" /><Stat label="Service level" value={fmt.pct(e.data.service_level, 1)} /><Stat label="P(wait)" value={fmt.pct(e.data.p_wait, 1)} /><Stat label="ASA / occupancy" value={`${e.data.asa_s}s · ${fmt.pct(e.data.occupancy, 0)}`} /></div>}
    </Card>
  )
}
