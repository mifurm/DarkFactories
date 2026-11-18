import { Calculator, Gauge, TrendingUp } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmt, useApi } from '../../lib/api'
import { BarSeries, ComboSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, ErrorBox, PageHeader, Slider, Spinner, Stat, Tabs, cx } from '../../lib/ui'

interface K { contacts: number; containment_pct: number; verified_resolution_pct: number; resolved_pct: number; aht_human_s: number | null; aht_ai_s: number | null; fcr_pct: number; csat_pred: number; sla_pct: number | null; abandon_pct: number; cost_per_contact_usd: number; cost_per_resolved_usd: number | null; cost_total_usd: number; cost_ai_usd: number; escalated_pct: number }
interface Side { contacts: number; resolved_pct: number; aht_blended_s: number; csat_pred: number; fcr_pct: number; cost_per_contact_usd: number; cost_per_resolved_usd: number | null }
interface Metrics { window_days: number; kpis: K; ai_vs_human: { ai: Side; human: Side; cost_per_resolved_ratio: number | null }; by_queue: (K & { queue: string; name: string })[]; by_hour: { hour: number; contacts: number; containment_pct: number }[]; daily: { date: string; contacts: number; containment_pct: number; verified_resolution_pct: number; cost_per_contact_usd: number }[]; reconcile: { name: string; ok: boolean; detail: string }[]; capacity: { containment: number; fte_with_ai: number; fte_without_ai: number; fte_saved: number } | null; by_source: Record<string, K>; synthetic_note: string }
interface Driver { key: string; label: string; unit: string; base: number | number[]; low: number | number[]; high: number | number[]; kind: string; step?: number }
interface Model { drivers: Driver[]; scenarios: string[]; footnote: { price_basis: string; price_date: string; disclaimer: string; reference_customer: string }; headline_base: Head }
interface Head { npv_usd: number; roi_pct: number; payback_months: number; irr_pct: number; acr_year3_usd: number; acr_three_year_usd: number; benefit_total_usd: number; cost_total_usd: number; pull_through_ratio: number }
interface Roi { scenario: string; headline: Head; roi: { net_benefit_by_year: number[]; cumulative: number[] }; benefits: { by_category: Record<string, number[]>; total_by_year: number[] }; costs: { azure_by_family: Record<string, number[]>; total_by_year: number[] }; acr: { by_year: number[]; by_family: Record<string, number[]>; family_labels: Record<string, string>; run_rate_year3: number; tiers?: unknown }; tornado: { assumption: string; label: string; delta_at_low: number; delta_at_high: number; low_value: number; high_value: number }[]; compute_ms: number; footnote: string }
interface Parity { ok: boolean; tolerance: number; rows: { scenario: string; metric: string; rel_error: number; ok: boolean }[] }

const usdM = (v: number | null | undefined) => (v == null ? '—' : `$${(v / 1e6).toFixed(1)}M`)

export default function MetricsPage() {
  const [tab, setTab] = useState('ops')
  return (
    <div>
      <PageHeader icon={TrendingUp} title="CX metrics & ROI" subtitle="Operational metrics computed from stored interaction records, and the ROI / Azure-ACR calculator that serves the business-case model — change an assumption and everything recomputes." />
      <Tabs tabs={[{ id: 'ops', label: 'Operations' }, { id: 'roi', label: 'ROI & Azure ACR calculator' }]} value={tab} onChange={setTab} />
      {tab === 'ops' ? <Ops /> : <RoiCalc />}
    </div>
  )
}

function Ops() {
  const [source, setSource] = useState('all')
  const [days, setDays] = useState(90)
  const m = useApi<Metrics>(`/api/metrics?days=${days}&source=${source}`, { refreshMs: 30000 })
  const d = m.data
  if (m.loading && !d) return <Spinner />
  if (m.error || !d) return <ErrorBox error={m.error} onRetry={m.reload} />
  const k = d.kpis
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {['all', 'synthetic', 'live'].map((s) => <Button key={s} size="sm" variant={source === s ? 'primary' : 'secondary'} onClick={() => setSource(s)}>{s}</Button>)}
        <span className="mx-1 text-slate-300">|</span>
        {[30, 90].map((n) => <Button key={n} size="sm" variant={days === n ? 'primary' : 'secondary'} onClick={() => setDays(n)}>{n} days</Button>)}
        <span className="text-xs text-slate-500">{d.synthetic_note}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Contacts" value={fmt.num(k.contacts)} hint={`escalated ${k.escalated_pct}%`} />
        <Stat label="AI containment" value={`${k.containment_pct}%`} tone="blue" />
        <Stat label="Verified resolution (AI)" value={`${k.verified_resolution_pct}%`} tone="green" hint="never above containment" />
        <Stat label="FCR" value={`${k.fcr_pct}%`} />
        <Stat label="Predicted CSAT" value={k.csat_pred.toFixed(2)} hint="1-5" />
        <Stat label="AHT human" value={fmt.dur(k.aht_human_s)} />
        <Stat label="AHT AI" value={fmt.dur(k.aht_ai_s)} />
        <Stat label="SLA met" value={k.sla_pct != null ? `${k.sla_pct}%` : '—'} hint={`abandon ${k.abandon_pct}%`} />
        <Stat label="Cost / contact" value={fmt.usd(k.cost_per_contact_usd)} />
        <Stat label="Cost / resolved contact" value={fmt.usd(k.cost_per_resolved_usd)} tone="green" hint={d.ai_vs_human.cost_per_resolved_ratio ? `human ${d.ai_vs_human.cost_per_resolved_ratio}× AI` : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="AI vs human" subtitle="AI cost includes the metered Azure usage (CC-22); human cost = handle minutes × loaded cost per minute" pad={false}>
          <DataTable dense rows={[{ m: 'Contacts', a: fmt.num(d.ai_vs_human.ai.contacts), h: fmt.num(d.ai_vs_human.human.contacts) }, { m: 'Resolved', a: `${d.ai_vs_human.ai.resolved_pct}%`, h: `${d.ai_vs_human.human.resolved_pct}%` }, { m: 'Avg handle time', a: fmt.dur(d.ai_vs_human.ai.aht_blended_s), h: fmt.dur(d.ai_vs_human.human.aht_blended_s) }, { m: 'Predicted CSAT', a: d.ai_vs_human.ai.csat_pred, h: d.ai_vs_human.human.csat_pred }, { m: 'FCR', a: `${d.ai_vs_human.ai.fcr_pct}%`, h: `${d.ai_vs_human.human.fcr_pct}%` }, { m: 'Cost per contact', a: fmt.usd(d.ai_vs_human.ai.cost_per_contact_usd, 3), h: fmt.usd(d.ai_vs_human.human.cost_per_contact_usd, 2) }, { m: 'Cost per resolved contact', a: fmt.usd(d.ai_vs_human.ai.cost_per_resolved_usd, 3), h: fmt.usd(d.ai_vs_human.human.cost_per_resolved_usd, 2) }]} rowKey={(r) => r.m} cols={[{ key: 'm', header: 'Metric', render: (r) => r.m }, { key: 'a', header: 'AI agent', align: 'right', render: (r) => <b className="text-violet-700">{r.a}</b> }, { key: 'h', header: 'Human (after AI attempt)', align: 'right', render: (r) => r.h }]} />
        </Card>
        <Card title="Daily trend"><LineSeries data={d.daily} x="date" lines={[{ key: 'containment_pct', name: 'containment %' }, { key: 'verified_resolution_pct', name: 'verified resolution %', color: '#16a34a' }]} height={230} yFmt={(v) => `${v}%`} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="By queue" pad={false}>
          <DataTable dense rows={d.by_queue} rowKey={(q) => q.queue} cols={[{ key: 'q', header: 'Queue', render: (q) => <b>{q.name}</b> }, { key: 'n', header: 'Contacts', align: 'right', render: (q) => fmt.num(q.contacts) }, { key: 'c', header: 'Contain.', align: 'right', render: (q) => `${q.containment_pct}%` }, { key: 'r', header: 'Resolved', align: 'right', render: (q) => `${q.resolved_pct}%` }, { key: 'x', header: '$/resolved', align: 'right', render: (q) => fmt.usd(q.cost_per_resolved_usd) }, { key: 's', header: 'SLA', align: 'right', render: (q) => (q.sla_pct != null ? `${q.sla_pct}%` : '—') }]} />
        </Card>
        <Card title="By hour of day" subtitle="contacts and AI containment"><ComboSeries data={d.by_hour.map((h) => ({ ...h, label: `${h.hour}:00` }))} x="label" bars={[{ key: 'contacts', name: 'contacts' }]} lines={[{ key: 'containment_pct', name: 'containment %' }]} height={230} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Reconciliation" subtitle="the views must agree with each other (asserted in tests)"><ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">{d.reconcile.map((c) => <li key={c.name} className="flex items-center gap-2"><Badge tone={c.ok ? 'green' : 'red'}>{c.ok ? 'ok' : 'FAIL'}</Badge><span className="text-xs text-slate-700">{c.name}</span></li>)}</ul></Card>
        <Card title="Capacity plan (WFM → metrics)" subtitle="weekly human FTE with and without AI at the measured containment">
          {d.capacity ? <div className="grid grid-cols-3 gap-3 text-center"><div><div className="text-2xl font-semibold">{d.capacity.fte_without_ai}</div><div className="text-xs text-slate-500">FTE without AI</div></div><div><div className="text-2xl font-semibold text-emerald-600">{d.capacity.fte_with_ai}</div><div className="text-xs text-slate-500">FTE at {Math.round(d.capacity.containment * 100)}% containment</div></div><div><div className="text-2xl font-semibold text-violet-700">{d.capacity.fte_saved}</div><div className="text-xs text-slate-500">FTE freed (demo-tenant slice)</div></div></div> : <p className="text-sm text-slate-500">Not available.</p>}
        </Card>
      </div>
    </div>
  )
}

function RoiCalc() {
  const model = useApi<Model>('/api/roi/model')
  const parity = useApi<Parity>('/api/roi/parity')
  const [scenario, setScenario] = useState('base')
  const [ov, setOv] = useState<Record<string, number | number[]>>({})
  const [res, setRes] = useState<Roi | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drivers = model.data?.drivers ?? []

  useEffect(() => {
    if (!model.data) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try { setRes(await api<Roi>('/api/roi/compute', { body: { scenario, overrides: ov } })); setErr(null) } catch (e) { setErr(e) }
    }, 150)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [scenario, ov, model.data])

  const set = (k: string, v: number | number[]) => setOv((o) => ({ ...o, [k]: v }))
  const val = (d: Driver) => (ov[d.key] ?? d.base) as number | number[]
  const fam = useMemo(() => (res ? Object.entries(res.acr.by_family).map(([k, arr]) => ({ name: res.acr.family_labels[k]?.replace(/^Azure (OpenAI|AI) - /, '') ?? k, usd: Array.isArray(arr) ? arr[3] : 0 })).filter((r) => r.usd > 0).sort((a, b) => b.usd - a.usd).slice(0, 8) : []), [res])
  const yearRows = res ? res.roi.net_benefit_by_year.map((v, i) => ({ year: i === 0 ? 'Y0 (build)' : `Y${i}`, net: Math.round(v), cumulative: Math.round(res.roi.cumulative[i]), benefits: Math.round(res.benefits.total_by_year[i]), costs: -Math.round(res.costs.total_by_year[i]) })) : []
  if (model.loading && !model.data) return <Spinner />
  if (model.error || !model.data) return <ErrorBox error={model.error} onRetry={model.reload} />
  const h = res?.headline ?? model.data.headline_base
  const changed = Object.keys(ov).length
  return (
    <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
      <Card title="Drivers" subtitle={`${scenario} scenario${changed ? ` · ${changed} changed` : ''}`} actions={changed ? <Button size="sm" onClick={() => setOv({})}>Reset</Button> : undefined}>
        <div className="mb-3 flex gap-1" role="group" aria-label="Scenario">{model.data.scenarios.map((s) => <Button key={s} size="sm" variant={scenario === s ? 'primary' : 'secondary'} onClick={() => setScenario(s)}>{s}</Button>)}</div>
        <div className="space-y-3">
          {drivers.map((d) => {
            if (Array.isArray(d.base)) {
              const cur = val(d) as number[]
              const lo = d.low as number[]; const hi = d.high as number[]
              return <div key={d.key}><div className="mb-1 text-xs font-medium text-slate-600">{d.label} (Y1 · Y2 · Y3)</div>{cur.map((v, i) => <Slider key={i} label={`Year ${i + 1}`} value={v} min={lo[i]} max={hi[i]} step={0.01} onChange={(x) => { const n = [...cur]; n[i] = x; set(d.key, n) }} format={(x) => fmt.pct(x, 0)} />)}</div>
            }
            const base = d.base as number
            const pct = d.unit.includes('share') || d.key.includes('pct') || d.key.includes('rate') || d.key.includes('coverage')
            return <Slider key={d.key} label={d.label} value={val(d) as number} min={d.low as number} max={d.high as number} step={d.step ?? (base >= 1000 ? Math.round(base / 100) : base >= 10 ? 1 : 0.01)} onChange={(x) => set(d.key, x)} format={(x) => (pct ? fmt.pct(x, 0) : x >= 1000 ? fmt.num(x) : d.key.includes('cost') ? fmt.usd(x) : String(x))} />
          })}
        </div>
      </Card>
      <div className="space-y-4">
        {err ? <ErrorBox error={err} /> : null}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="3-year NPV" value={usdM(h.npv_usd)} tone="green" icon={Calculator} hint={`ROI ${Math.round(h.roi_pct)}%`} />
          <Stat label="Payback" value={`${h.payback_months.toFixed(1)} mo`} hint="from project start" />
          <Stat label="Azure ACR — year 3" value={usdM(h.acr_year3_usd)} tone="blue" icon={Gauge} hint={`3-yr ${usdM(h.acr_three_year_usd)}`} />
          <Stat label="Benefits / costs (3 yr)" value={`${usdM(h.benefit_total_usd)} / ${usdM(h.cost_total_usd)}`} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Net benefit by year" subtitle="USD, year 0 = build + pilot"><ComboSeries data={yearRows} x="year" bars={[{ key: 'net', name: 'net benefit' }]} lines={[{ key: 'cumulative', name: 'cumulative' }]} height={240} yFmt={(v) => usdM(v)} /></Card>
          <Card title="Azure consumption (ACR) — year 3 by service family"><BarSeries data={fam} x="name" bars={[{ key: 'usd', name: 'USD / year', color: '#0891b2' }]} horizontal height={240} yFmt={(v) => usdM(v)} /></Card>
        </div>
        <Card title="Tornado — NPV sensitivity" subtitle="each uncertain driver at its low / high bound, others at the current setting">
          {res && <BarSeries data={res.tornado.map((t) => ({ name: t.label.slice(0, 44), low: Math.round(t.delta_at_low), high: Math.round(t.delta_at_high) }))} x="name" bars={[{ key: 'low', name: 'at low bound', color: '#dc2626' }, { key: 'high', name: 'at high bound', color: '#16a34a' }]} stacked horizontal height={330} yFmt={(v) => usdM(v)} />}
        </Card>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {parity.data && <Badge tone={parity.data.ok ? 'green' : 'red'}>parity with business-case/outputs.json: {parity.data.ok ? `within ${parity.data.tolerance * 100}%` : 'FAILED'} (max error {(Math.max(...parity.data.rows.map((r) => r.rel_error)) * 100).toFixed(4)}%)</Badge>}
          {res && <span>computed in {res.compute_ms} ms</span>}
        </div>
        <p className={cx('rounded-xl bg-slate-100 p-3 text-xs text-slate-600')}>{model.data.footnote.price_basis} Retrieved {model.data.footnote.price_date}. {model.data.footnote.disclaimer} Reference customer: {model.data.footnote.reference_customer}</p>
      </div>
    </div>
  )
}
