import { useMemo } from 'react'
import { Areas, Lines } from '../../components/charts'
import { Meter } from '../../components/bits'
import { Badge, Card, Empty, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi } from '../../plant'

type Shift = { utility: string; active: boolean; soc: number; cap: number; discharge_kw: number; charge_kw: number; hi: number; lo: number; until: number; shifted_kwh: number; saved_eur: number }
type Sum = { plan: { price_now: number; carbon_now: number; spike: boolean; lo: number; hi: number }; shifts: Shift[]; forecast: { t: number; price: number; carbon: number }[]; standby: string[]; deferred: Record<string, unknown>; price_now: number; carbon_now: number; total_kw: number; saved_eur: number; kpi: { energy_kwh: number; kwh_per_unit: number; co2_kg: number; co2_per_unit_kg: number; energy_cost_eur: number; peak_kw: number } }

export default function Energy() {
  const sum = usePApi<Sum>('/api/energy/summary', { interval: 3000 })
  const trend = usePApi<{ t: number; kw: number; price: number; carbon: number }[]>('/api/energy/trend', { interval: 5000 })
  const s = sum.data
  const fc = useMemo(() => (s?.forecast ?? []).map((f, i) => ({ x: `+${(i * 0.5).toFixed(1)} h`, price: f.price, carbon: f.carbon })), [s])
  return (
    <Page title="Energy & sustainability" subtitle="Time-of-use tariff and carbon curves drive two levers: shift thermal-buffer load (compressed air, chilled water) away from price peaks, and defer deferrable jobs - never at the cost of a due date (twin-checked). Savings are measured against the no-shift counterfactual.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Price now" value={`€${(s?.price_now ?? 0).toFixed(3)}`} sub="per kWh" tone={s?.plan.spike ? 'bad' : 'ok'} />
        <Stat label="Grid carbon" value={`${s?.carbon_now ?? '-'}`} sub="g CO₂/kWh" />
        <Stat label="Plant power" value={`${fmt.n(s?.total_kw, 0)} kW`} sub={`peak ${fmt.n(s?.kpi.peak_kw, 0)} kW`} />
        <Stat label="Energy per unit" value={`${fmt.n(s?.kpi.kwh_per_unit, 2)} kWh`} sub={`${fmt.n(s?.kpi.co2_per_unit_kg, 2)} kg CO₂`} />
        <Stat label="Energy cost" value={fmt.eur(s?.kpi.energy_cost_eur)} sub="rolling window" />
        <Stat label="Saved by load shift" value={fmt.eur(s?.saved_eur, 1)} tone="ok" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Tariff forecast (next 24 h)" right={s?.plan.spike ? <Badge tone="bad">price spike</Badge> : <Badge tone="ok">normal tariff</Badge>}>
          <Areas data={fc} keys={[{ key: 'price', name: 'EUR/kWh', color: '#fbbf24' }]} height={190} />
          <p className="text-[11px] text-mute">Shifting thresholds: charge below €{s?.plan.lo.toFixed(3)}, discharge above €{s?.plan.hi.toFixed(3)}.</p>
        </Card>
        <Card title="Plant power (last hour)">
          <Lines data={(trend.data ?? []).map((p) => ({ x: p.t, kw: p.kw }))} lines={[{ key: 'kw', name: 'kW', color: '#38bdf8' }]} height={190} xFormatter={() => ''} />
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card title="Thermal buffers (load-shifting assets)" pad={false}>
          <Table head={['Utility', 'Mode', 'State of charge', 'Shifted kWh', 'Saved', 'Capacity']}>
            {(s?.shifts ?? []).map((u) => (
              <tr key={u.utility}>
                <Td className="font-medium">{u.utility}</Td>
                <Td><Badge tone={u.active ? 'violet' : 'mute'}>{u.active ? `shifting until +${fmt.dur(u.until)}` : 'idle'}</Badge></Td>
                <Td className="w-48"><div className="flex items-center gap-2"><span className="tabnum w-10 text-[12px]">{fmt.pct(u.cap ? u.soc / u.cap : 0, 0)}</span><Meter value={u.soc} max={u.cap || 1} tone="info" /></div></Td>
                <Td className="tabnum">{fmt.n(u.shifted_kwh, 1)}</Td><Td className="tabnum text-ok">{fmt.eur(u.saved_eur, 1)}</Td><Td className="tabnum text-mute">{u.cap} kWh</Td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="Standby / deferred">
          {(s?.standby.length ?? 0) === 0 && Object.keys(s?.deferred ?? {}).length === 0 ? <Empty>No machines in standby and no jobs deferred right now.</Empty> : (
            <div className="space-y-2 text-sm">
              {s?.standby.map((a) => <div key={a} className="flex items-center gap-2"><Badge tone="info">standby</Badge>{a}</div>)}
              {Object.entries(s?.deferred ?? {}).map(([o, v]) => <div key={o} className="flex items-center gap-2"><Badge tone="warn">deferred</Badge>{o} <span className="text-[11px] text-mute">{JSON.stringify(v)}</span></div>)}
            </div>
          )}
          <p className="mt-3 text-[11px] text-mute">Honest note: absolute energy cost can rise when the swarm keeps machines busier (more output). The A/B replay on the Value page reports both absolute cost and energy per unit.</p>
        </Card>
      </div>
    </Page>
  )
}
