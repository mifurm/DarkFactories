import { useMemo, useState } from 'react'
import { Bars, Lines } from '../../components/charts'
import { Select } from '../../components/bits'
import { Badge, Card, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi } from '../../plant'

type K = { oee: number; availability: number; performance: number; quality: number; throughput_uph: number; units_good: number; fpy: number; scrap_pct: number; mtbf_h: number | null; mttr_min: number | null; failures: number; downtime_min: number; otif: number; orders_completed: number; tardiness_h: number; energy_kwh: number; kwh_per_unit: number; co2_per_unit_kg: number; energy_cost_eur: number; peak_kw: number; revenue_eur: number }
type Resp = { plant: string; window_h: number; plant_kpi: K; impact_eur: Record<string, number>; lines: Record<string, { availability: number; performance: number; quality: number; oee: number; failures: number; down_min: number; units: number; kwh: number }>; assets: Record<string, { oee: number; availability: number; down_min: number; units: number }> }

export default function Kpis() {
  const [hours, setHours] = useState(8)
  const k = usePApi<Resp>(`/api/kpi?window_hours=${hours}`, { interval: 5000 })
  const trend = usePApi<{ t: number; oee: number; availability: number; throughput_uph: number; downtime_min: number }[]>('/api/kpi/trend?points=24', { interval: 8000 })
  const snaps = usePApi<{ persisted: number; backend: string; items: { t: number; sim_time: string; oee: number }[] }>('/api/kpi/snapshots?limit=24', { interval: 15000 })
  const p = k.data?.plant_kpi
  const impact = useMemo(() => Object.entries(k.data?.impact_eur ?? {}).filter(([n]) => !['loss_total', 'tardiness_open'].includes(n)).map(([name, eur]) => ({ name, eur: Math.round(eur) })), [k.data])
  const assets = useMemo(() => Object.entries(k.data?.assets ?? {}).map(([id, a]) => ({ id, oee: Math.round(a.oee * 1000) / 10 })).sort((a, b) => a.oee - b.oee).slice(0, 12), [k.data])
  return (
    <Page title="KPIs & business impact" subtitle="OEE (availability x performance x quality), throughput, OTIF, MTBF/MTTR, energy and carbon per unit - and the EUR impact of each loss category (valued from the simulation cost assumptions). Hourly snapshots persist to Cosmos DB." right={
      <Select aria-label="KPI window" className="w-36" value={hours} onChange={(e) => setHours(Number(e.target.value))}>{[1, 4, 8, 24].map((h) => <option key={h} value={h}>last {h} h</option>)}</Select>}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="OEE" value={fmt.pct(p?.oee, 1)} tone={(p?.oee ?? 0) > 0.7 ? 'ok' : 'warn'} />
        <Stat label="Availability" value={fmt.pct(p?.availability, 1)} />
        <Stat label="Performance" value={fmt.pct(p?.performance, 1)} />
        <Stat label="Quality (FPY)" value={fmt.pct(p?.fpy, 2)} />
        <Stat label="Throughput" value={`${fmt.n(p?.throughput_uph, 1)} u/h`} sub={`${fmt.n(p?.units_good)} good units`} />
        <Stat label="OTIF" value={fmt.pct(p?.otif, 0)} sub={`${fmt.n(p?.orders_completed)} orders done`} />
        <Stat label="MTBF / MTTR" value={`${p?.mtbf_h != null ? fmt.n(p.mtbf_h, 1) + ' h' : '-'} / ${p?.mttr_min != null ? fmt.n(p.mttr_min, 0) + ' min' : '-'}`} sub={`${p?.failures ?? 0} failures`} />
        <Stat label="Energy / unit" value={`${fmt.n(p?.kwh_per_unit, 2)} kWh`} sub={`${fmt.n(p?.co2_per_unit_kg, 2)} kg CO₂ · ${fmt.eur(p?.energy_cost_eur)}`} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="OEE & availability trend (hourly points)">
          <Lines data={(trend.data ?? []).map((t) => ({ x: Math.round(t.t / 60), oee: t.oee, availability: t.availability }))} lines={[{ key: 'oee', name: 'OEE', color: '#38bdf8' }, { key: 'availability', name: 'availability', color: '#34d399' }]} height={230} yDomain={[0, 1]} xFormatter={(v) => `${v} h`} legend />
        </Card>
        <Card title="Loss impact by category (EUR, window)" right={<Badge tone="warn">simulation cost assumptions</Badge>}>
          <Bars data={impact} x="name" bars={[{ key: 'eur', color: '#f87171' }]} height={230} />
          <p className="mt-1 text-[11px] text-mute">Total loss {fmt.eur(k.data?.impact_eur.loss_total)} in the window; open tardiness exposure {fmt.eur(k.data?.impact_eur.tardiness_open)}.</p>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Lines" pad={false}>
          <Table head={['Line', 'OEE', 'Avail.', 'Perf.', 'Failures', 'Down (min)', 'Units', 'kWh']}>
            {Object.entries(k.data?.lines ?? {}).map(([n, l]) => <tr key={n}><Td className="font-medium">{n}</Td><Td className="tabnum">{fmt.pct(l.oee, 1)}</Td><Td className="tabnum">{fmt.pct(l.availability, 1)}</Td><Td className="tabnum">{fmt.pct(l.performance, 1)}</Td><Td className="tabnum">{l.failures}</Td><Td className="tabnum">{fmt.n(l.down_min)}</Td><Td className="tabnum">{fmt.n(l.units)}</Td><Td className="tabnum">{fmt.n(l.kwh)}</Td></tr>)}
          </Table>
        </Card>
        <Card title="Lowest-OEE assets (%)" right={<Badge tone="info">Cosmos snapshots: {snaps.data?.persisted ?? 0} ({snaps.data?.backend})</Badge>}>
          <Bars data={assets} x="id" bars={[{ key: 'oee', color: '#a78bfa' }]} layout="vertical" height={Math.max(180, assets.length * 22)} />
        </Card>
      </div>
    </Page>
  )
}
