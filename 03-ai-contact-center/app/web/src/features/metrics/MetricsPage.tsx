import { Calculator, Gauge, TrendingUp } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ellipsize, useI18n } from '../../i18n'
import { api, useApi } from '../../lib/api'
import { BarSeries, ComboSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, ErrorBox, PageHeader, Slider, Spinner, Stat, Tabs, cx } from '../../lib/ui'

interface K { contacts: number; containment_pct: number; verified_resolution_pct: number; resolved_pct: number; aht_human_s: number | null; aht_ai_s: number | null; fcr_pct: number; csat_pred: number; sla_pct: number | null; abandon_pct: number; cost_per_contact_usd: number; cost_per_resolved_usd: number | null; cost_total_usd: number; cost_ai_usd: number; escalated_pct: number }
interface Side { contacts: number; resolved_pct: number; aht_blended_s: number; csat_pred: number; fcr_pct: number; cost_per_contact_usd: number; cost_per_resolved_usd: number | null }
interface Metrics { window_days: number; kpis: K; ai_vs_human: { ai: Side; human: Side; cost_per_resolved_ratio: number | null }; by_queue: (K & { queue: string; name: string })[]; by_hour: { hour: number; contacts: number; containment_pct: number }[]; daily: { date: string; contacts: number; containment_pct: number; verified_resolution_pct: number; cost_per_contact_usd: number }[]; reconcile: { name: string; ok: boolean; detail: string }[]; capacity: { containment: number; fte_with_ai: number; fte_without_ai: number; fte_saved: number } | null; by_source: Record<string, K>; synthetic_note: string }
interface Driver { key: string; label: string; unit: string; base: number | number[]; low: number | number[]; high: number | number[]; kind: string; step?: number }
interface Model { drivers: Driver[]; scenarios: string[]; footnote: { price_basis: string; price_date: string; disclaimer: string; reference_customer: string }; headline_base: Head }
interface Head { npv_usd: number; roi_pct: number; payback_months: number; irr_pct: number; acr_year3_usd: number; acr_three_year_usd: number; benefit_total_usd: number; cost_total_usd: number; pull_through_ratio: number }
interface Tier { name: string; seats: number; contacts_per_year?: number; annual_acr_usd: number; acr_per_seat_per_month_usd?: number }
interface Roi { scenario: string; headline: Head; roi: { net_benefit_by_year: number[]; cumulative: number[] }; benefits: { by_category: Record<string, number[]>; total_by_year: number[]; labels?: Record<string, string> }; costs: { azure_by_family: Record<string, number[]>; total_by_year: number[] }; acr: { by_year: number[]; by_family: Record<string, number[]>; family_labels: Record<string, string>; run_rate_year3: number; tiers?: Tier[] }; tornado: { assumption: string; label: string; delta_at_low: number; delta_at_high: number; low_value: number; high_value: number }[]; compute_ms: number; footnote: string }
interface Parity { ok: boolean; tolerance: number; rows: { scenario: string; metric: string; rel_error: number; ok: boolean }[] }

export default function MetricsPage() {
  const { t } = useI18n()
  const [tab, setTab] = useState('ops')
  return (
    <div>
      <PageHeader icon={TrendingUp} title={t('CX metrics & ROI')} subtitle={t('Operational metrics computed from stored interaction records, and the ROI / Azure-ACR calculator that serves the business-case model — change an assumption and everything recomputes.')} />
      <Tabs tabs={[{ id: 'ops', label: t('Operations') }, { id: 'roi', label: t('ROI & Azure ACR calculator') }]} value={tab} onChange={setTab} />
      {tab === 'ops' ? <Ops /> : <RoiCalc />}
    </div>
  )
}

function Ops() {
  const { t, tn, te, tl, ts, fmt } = useI18n()
  const [source, setSource] = useState('all')
  const [days, setDays] = useState(90)
  const m = useApi<Metrics>(`/api/metrics?days=${days}&source=${source}`, { refreshMs: 30000 })
  const d = m.data
  if (m.loading && !d) return <Spinner />
  if (m.error || !d) return <ErrorBox error={m.error} onRetry={m.reload} />
  const k = d.kpis
  const a = d.ai_vs_human.ai
  const h = d.ai_vs_human.human
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {['all', 'synthetic', 'live'].map((s) => <Button key={s} size="sm" variant={source === s ? 'primary' : 'secondary'} onClick={() => setSource(s)}>{te('metricsSource', s)}</Button>)}
        <span className="mx-1 text-slate-300">|</span>
        {[30, 90].map((n) => <Button key={n} size="sm" variant={days === n ? 'primary' : 'secondary'} onClick={() => setDays(n)}>{tn(n, { one: '{n} day', other: '{n} days' })}</Button>)}
        <span className="text-xs text-slate-500">{ts(d.synthetic_note)}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={t('Contacts')} value={fmt.number(k.contacts)} hint={t('escalated {pct}', { pct: fmt.percentValue(k.escalated_pct) })} />
        <Stat label={t('AI containment')} value={fmt.percentValue(k.containment_pct)} tone="blue" />
        <Stat label={t('Verified resolution (AI)')} value={fmt.percentValue(k.verified_resolution_pct)} tone="green" hint={t('never above containment')} />
        <Stat label="FCR" value={fmt.percentValue(k.fcr_pct)} />
        <Stat label={t('Predicted CSAT')} value={fmt.fixed(k.csat_pred, 2)} hint="1-5" />
        <Stat label={t('AHT human')} value={fmt.dur(k.aht_human_s)} />
        <Stat label={t('AHT AI')} value={fmt.dur(k.aht_ai_s)} />
        <Stat label={t('SLA met')} value={k.sla_pct != null ? fmt.percentValue(k.sla_pct) : '—'} hint={t('abandon {pct}', { pct: fmt.percentValue(k.abandon_pct) })} />
        <Stat label={t('Cost / contact')} value={fmt.usd(k.cost_per_contact_usd)} />
        <Stat label={t('Cost / resolved contact')} value={fmt.usd(k.cost_per_resolved_usd)} tone="green" hint={d.ai_vs_human.cost_per_resolved_ratio ? t('human {n}× AI', { n: fmt.plain(d.ai_vs_human.cost_per_resolved_ratio) }) : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('AI vs human')} subtitle={t('AI cost includes the metered Azure usage (CC-22); human cost = handle minutes × loaded cost per minute')} pad={false}>
          <DataTable dense rows={[{ m: t('Contacts'), a: fmt.number(a.contacts), h: fmt.number(h.contacts) }, { m: t('Resolved'), a: fmt.percentValue(a.resolved_pct), h: fmt.percentValue(h.resolved_pct) }, { m: t('Avg handle time'), a: fmt.dur(a.aht_blended_s), h: fmt.dur(h.aht_blended_s) }, { m: t('Predicted CSAT'), a: fmt.plain(a.csat_pred), h: fmt.plain(h.csat_pred) }, { m: 'FCR', a: fmt.percentValue(a.fcr_pct), h: fmt.percentValue(h.fcr_pct) }, { m: t('Cost per contact'), a: fmt.usd(a.cost_per_contact_usd, 3), h: fmt.usd(h.cost_per_contact_usd, 2) }, { m: t('Cost per resolved contact'), a: fmt.usd(a.cost_per_resolved_usd, 3), h: fmt.usd(h.cost_per_resolved_usd, 2) }]} rowKey={(r) => r.m} cols={[{ key: 'm', header: t('Metric'), render: (r) => r.m }, { key: 'a', header: t('AI agent'), align: 'right', render: (r) => <b className="text-violet-700">{r.a}</b> }, { key: 'h', header: t('Human (after AI attempt)'), align: 'right', render: (r) => r.h }]} />
        </Card>
        <Card title={t('Daily trend')}><LineSeries data={d.daily} x="date" xFmt={(v) => fmt.isoDate(String(v))} lines={[{ key: 'containment_pct', name: t('containment %') }, { key: 'verified_resolution_pct', name: t('verified resolution %'), color: '#16a34a' }]} height={230} yFmt={(v) => fmt.percentValue(v)} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('By queue')} pad={false}>
          <DataTable dense rows={d.by_queue} rowKey={(q) => q.queue} cols={[{ key: 'q', header: t('Queue'), render: (q) => <b>{tl('queue', q.queue, q.name)}</b> }, { key: 'n', header: t('Contacts'), align: 'right', render: (q) => fmt.number(q.contacts) }, { key: 'c', header: t('Contain.'), align: 'right', render: (q) => fmt.percentValue(q.containment_pct) }, { key: 'r', header: t('Resolved'), align: 'right', render: (q) => fmt.percentValue(q.resolved_pct) }, { key: 'x', header: t('$/resolved'), align: 'right', render: (q) => fmt.usd(q.cost_per_resolved_usd) }, { key: 's', header: 'SLA', align: 'right', render: (q) => (q.sla_pct != null ? fmt.percentValue(q.sla_pct) : '—') }]} />
        </Card>
        <Card title={t('By hour of day')} subtitle={t('contacts and AI containment')}><ComboSeries data={d.by_hour.map((x) => ({ ...x, label: `${x.hour}:00` }))} x="label" bars={[{ key: 'contacts', name: t('contacts') }]} lines={[{ key: 'containment_pct', name: t('containment %') }]} height={230} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('Reconciliation')} subtitle={t('the views must agree with each other (asserted in tests)')}><ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">{d.reconcile.map((c) => <li key={c.name} className="flex items-center gap-2"><Badge tone={c.ok ? 'green' : 'red'}>{c.ok ? t('ok') : t('FAIL')}</Badge><span className="text-xs text-slate-700">{ts(c.name)}</span></li>)}</ul></Card>
        <Card title={t('Capacity plan (WFM → metrics)')} subtitle={t('weekly human FTE with and without AI at the measured containment')}>
          {d.capacity ? <div className="grid grid-cols-3 gap-3 text-center"><div><div className="text-2xl font-semibold">{fmt.plain(d.capacity.fte_without_ai)}</div><div className="text-xs text-slate-500">{t('FTE without AI')}</div></div><div><div className="text-2xl font-semibold text-emerald-600">{fmt.plain(d.capacity.fte_with_ai)}</div><div className="text-xs text-slate-500">{t('FTE at {pct} containment', { pct: fmt.percent(d.capacity.containment, 0) })}</div></div><div><div className="text-2xl font-semibold text-violet-700">{fmt.plain(d.capacity.fte_saved)}</div><div className="text-xs text-slate-500">{t('FTE freed (demo-tenant slice)')}</div></div></div> : <p className="text-sm text-slate-500">{t('Not available.')}</p>}
        </Card>
      </div>
    </div>
  )
}

function RoiCalc() {
  const { t, te, tl, fmt, lang } = useI18n()
  const model = useApi<Model>('/api/roi/model')
  const parity = useApi<Parity>('/api/roi/parity')
  const [scenario, setScenario] = useState('base')
  const [ov, setOv] = useState<Record<string, number | number[]>>({})
  const [res, setRes] = useState<Roi | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drivers = model.data?.drivers ?? []
  const usdM = (v: number | null | undefined) => fmt.usdMillions(v)

  useEffect(() => {
    if (!model.data) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try { setRes(await api<Roi>('/api/roi/compute', { body: { scenario, overrides: ov } })); setErr(null) } catch (e) { setErr(e) }
    }, 150)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [scenario, ov, model.data])

  const set = (key: string, v: number | number[]) => setOv((o) => ({ ...o, [key]: v }))
  const val = (d: Driver) => (ov[d.key] ?? d.base) as number | number[]
  const famName = (key: string, labels: Record<string, string>) => tl('roiFamily', key, labels[key]?.replace(/^Azure (OpenAI|AI) - /, '') ?? key)
  const fam = useMemo(() => (res ? Object.entries(res.acr.by_family).map(([k, arr]) => ({ name: famName(k, res.acr.family_labels), usd: Array.isArray(arr) ? arr[3] : 0 })).filter((r) => r.usd > 0).sort((a, b) => b.usd - a.usd).slice(0, 8) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [res, lang])
  const yearRows = res ? res.roi.net_benefit_by_year.map((v, i) => ({ year: i === 0 ? t('Y0 (build)') : t('Y{n}', { n: i }), net: Math.round(v), cumulative: Math.round(res.roi.cumulative[i]), benefits: Math.round(res.benefits.total_by_year[i]), costs: -Math.round(res.costs.total_by_year[i]) })) : []
  const benefitRows = res ? Object.entries(res.benefits.by_category).map(([k, arr]) => ({ name: tl('roiCategory', k, res.benefits.labels?.[k] ?? k), usd: Math.round(arr.reduce((s, x) => s + x, 0)) })).filter((r) => r.usd > 0).sort((a, b) => b.usd - a.usd) : []
  if (model.loading && !model.data) return <Spinner />
  if (model.error || !model.data) return <ErrorBox error={model.error} onRetry={model.reload} />
  const head = res?.headline ?? model.data.headline_base
  const changed = Object.keys(ov).length
  const fnote = model.data.footnote
  return (
    <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
      <Card title={t('Drivers')} subtitle={changed ? t('{scenario} scenario · {n} changed', { scenario: te('roiScenario', scenario), n: changed }) : t('{scenario} scenario', { scenario: te('roiScenario', scenario) })} actions={changed ? <Button size="sm" onClick={() => setOv({})}>{t('Reset')}</Button> : undefined}>
        <div className="mb-3 flex flex-wrap gap-1" role="group" aria-label={t('Scenario')}>{model.data.scenarios.map((s) => <Button key={s} size="sm" variant={scenario === s ? 'primary' : 'secondary'} onClick={() => setScenario(s)}>{te('roiScenario', s)}</Button>)}</div>
        <div className="space-y-3">
          {drivers.map((d) => {
            const label = tl('roiDriver', d.key, d.label)
            if (Array.isArray(d.base)) {
              const cur = val(d) as number[]
              const lo = d.low as number[]; const hi = d.high as number[]
              return <div key={d.key}><div className="mb-1 text-xs font-medium text-slate-600">{t('{label} (Y1 · Y2 · Y3)', { label })}</div>{cur.map((v, i) => <Slider key={i} label={t('Year {n}', { n: i + 1 })} value={v} min={lo[i]} max={hi[i]} step={0.01} onChange={(x) => { const n = [...cur]; n[i] = x; set(d.key, n) }} format={(x) => fmt.percent(x, 0)} />)}</div>
            }
            const base = d.base as number
            const pct = d.unit.includes('share') || d.key.includes('pct') || d.key.includes('rate') || d.key.includes('coverage')
            return <Slider key={d.key} label={label} value={val(d) as number} min={d.low as number} max={d.high as number} step={d.step ?? (base >= 1000 ? Math.round(base / 100) : base >= 10 ? 1 : 0.01)} onChange={(x) => set(d.key, x)} format={(x) => (pct ? fmt.percent(x, 0) : x >= 1000 ? fmt.number(x) : d.key.includes('cost') ? fmt.usd(x) : fmt.plain(x))} />
          })}
        </div>
      </Card>
      <div className="space-y-4">
        {err ? <ErrorBox error={err} /> : null}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label={t('3-year NPV')} value={usdM(head.npv_usd)} tone="green" icon={Calculator} hint={t('ROI {pct}', { pct: fmt.percentValue(Math.round(head.roi_pct)) })} />
          <Stat label={t('Payback')} value={t('{n} mo', { n: fmt.fixed(head.payback_months, 1) })} hint={t('from project start')} />
          <Stat label={t('Azure ACR — year 3')} value={usdM(head.acr_year3_usd)} tone="blue" icon={Gauge} hint={t('3-yr {total}', { total: usdM(head.acr_three_year_usd) })} />
          <Stat label={t('Benefits / costs (3 yr)')} value={`${usdM(head.benefit_total_usd)} / ${usdM(head.cost_total_usd)}`} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={t('Net benefit by year')} subtitle={t('USD, year 0 = build + pilot')}><ComboSeries data={yearRows} x="year" bars={[{ key: 'net', name: t('net benefit') }]} lines={[{ key: 'cumulative', name: t('cumulative') }]} height={240} yFmt={(v) => usdM(v)} /></Card>
          <Card title={t('Azure consumption (ACR) — year 3 by service family')}><BarSeries data={fam} x="name" bars={[{ key: 'usd', name: t('USD / year'), color: '#0891b2' }]} horizontal height={240} yFmt={(v) => usdM(v)} labelWidth={lang === 'pl' ? 210 : 150} /></Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={t('Benefits by category (3 years)')} subtitle={t('USD, risk-adjusted')}><BarSeries data={benefitRows} x="name" bars={[{ key: 'usd', name: t('USD'), color: '#16a34a' }]} horizontal height={260} yFmt={(v) => usdM(v)} labelWidth={lang === 'pl' ? 230 : 190} /></Card>
          <Card title={t('Azure consumption by customer size')} subtitle={t('annual ACR at maturity for each deployment tier')} pad={false}>
            <DataTable dense rows={res?.acr.tiers ?? []} rowKey={(x) => x.name} empty={t('No data')} cols={[{ key: 'n', header: t('Tier'), render: (x) => <b>{tl('roiTier', x.name, x.name)}</b> }, { key: 's', header: t('Seats'), align: 'right', render: (x) => fmt.number(x.seats) }, { key: 'a', header: t('ACR / year'), align: 'right', render: (x) => usdM(x.annual_acr_usd) }, { key: 'm', header: t('USD / seat / month'), align: 'right', render: (x) => fmt.usd(x.acr_per_seat_per_month_usd, 0) }]} />
          </Card>
        </div>
        <Card title={t('Tornado — NPV sensitivity')} subtitle={t('each uncertain driver at its low / high bound, others at the current setting')}>
          {res && <BarSeries data={res.tornado.map((x) => { const name = tl('roiSens', x.assumption, x.label); return { name: lang === 'pl' ? ellipsize(name, 72) : name.slice(0, 44), low: Math.round(x.delta_at_low), high: Math.round(x.delta_at_high) } })} x="name" bars={[{ key: 'low', name: t('at low bound'), color: '#dc2626' }, { key: 'high', name: t('at high bound'), color: '#16a34a' }]} stacked horizontal height={330} yFmt={(v) => usdM(v)} labelWidth={lang === 'pl' ? 250 : 150} />}
        </Card>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {parity.data && <Badge tone={parity.data.ok ? 'green' : 'red'}>{t('parity with business-case/outputs.json: {result} (max error {err}%)', { result: parity.data.ok ? t('within {tol}%', { tol: fmt.plain(parity.data.tolerance * 100) }) : t('FAILED'), err: fmt.fixed(Math.max(...parity.data.rows.map((r) => r.rel_error)) * 100, 4) })}</Badge>}
          {res && <span>{t('computed in {n} ms', { n: fmt.plain(res.compute_ms) })}</span>}
        </div>
        <p className={cx('rounded-xl bg-slate-100 p-3 text-xs text-slate-600')}>{tl('roiFootnote', 'price_basis', fnote.price_basis)} {t('Retrieved {date}.', { date: fnote.price_date })} {tl('roiFootnote', 'disclaimer', fnote.disclaimer)} {t('Reference customer:')} {tl('roiFootnote', 'reference_customer', fnote.reference_customer)}</p>
      </div>
    </div>
  )
}
