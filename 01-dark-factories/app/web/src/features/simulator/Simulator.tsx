import { useState } from 'react'
import { Field, Json, Select, StateBadge, TextArea, simTime, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'
import { FaultConsole, SimControls, type Snap } from '../control-tower/Panels'

type Order = { id: string; sku: string; qty: number; priority: number; rush: boolean; deferrable: boolean; due_in_min: number; ops: { stage: string; done: number; qty: number; finished_t?: number | null }[] }
type Ev = { t: number; kind: string; asset: string; frm?: string; to?: string; reason?: string }

const PRESETS: Record<string, object> = {
  'Slow a machine': { kind: 'set_speed', asset: 'CNC-02', pct: 85 },
  'Safe-stop a cell': { kind: 'safe_stop', asset: 'CNC-02' },
  Resume: { kind: 'resume', asset: 'CNC-02' },
  'Expedite order': { kind: 'expedite_order', order: 'SO-0001' },
  'Out-of-range speed (rejected)': { kind: 'set_speed', asset: 'CNC-02', pct: 240 },
}

export default function Simulator() {
  const calls = usePlantCalls()
  const state = usePApi<Snap>('/api/sim/state', { interval: 2000 })
  const orders = usePApi<Order[]>('/api/sim/orders', { interval: 5000 })
  const events = usePApi<Ev[]>('/api/sim/events?limit=40', { interval: 3000 })
  const cfg = usePApi<{ assumptions: Record<string, any> }>('/api/sim/config')
  const [snaps, setSnaps] = useState<string[]>([])
  const [preset, setPreset] = useState('Slow a machine')
  const [json, setJson] = useState(JSON.stringify({ action: PRESETS['Slow a machine'] }, null, 2))
  const act = useAction<unknown>()
  const snapAct = useAction<{ id: string; available: string[] }>()
  const s = state.data

  const take = async () => {
    const r = await snapAct.run(() => calls.post('/api/sim/snapshot'))
    if (r) setSnaps(r.available)
  }
  return (
    <Page title="Factory simulator" subtitle="Seeded, deterministic discrete-time plant (1 tick = 1 simulated minute). Not a physical plant: every number here is synthetic, calibrated against the assumptions below.">
      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Simulated time" value={simTime(s.sim_time)} sub={`t = ${fmt.n(s.t)} min`} />
          <Stat label="Speed" value={`${s.speed}x`} sub={s.paused ? 'paused' : 'running'} tone={s.paused ? 'warn' : 'ok'} />
          <Stat label="Assets" value={s.assets.length} sub={`${s.assets.filter((a) => a.state === 'RUN').length} running`} />
          <Stat label="Open orders" value={s.open_orders} />
          <Stat label="Plant power" value={`${fmt.n(s.total_kw, 0)} kW`} sub={`€${s.price_eur_kwh.toFixed(3)}/kWh · ${s.carbon_g_kwh} g/kWh`} />
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Time control" right={s && <SimControls snap={s} />}>
          <p className="text-sm text-mute">Default 1 simulated minute per real second (60x). Pause and single-step for deterministic demos; a seeded RNG stream per asset keeps A/B replays comparable.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={snapAct.busy} onClick={take}>📸 Snapshot</Button>
            {snaps.map((id) => (
              <Button key={id} size="sm" tone="ghost" onClick={() => act.run(() => calls.post(`/api/sim/restore/${id}`))}>Restore {id}</Button>
            ))}
            {snapAct.error && <span role="alert" className="text-xs text-bad">{snapAct.error}</span>}
          </div>
        </Card>
        <FaultConsole />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Control API (what agents call)" right={<Badge tone="info">validated · rejected if physically impossible</Badge>}>
          <div className="mb-2 flex gap-2">
            <Select aria-label="Action preset" value={preset} onChange={(e) => { setPreset(e.target.value); setJson(JSON.stringify({ action: PRESETS[e.target.value] }, null, 2)) }}>
              {Object.keys(PRESETS).map((k) => <option key={k}>{k}</option>)}
            </Select>
            <Button size="sm" tone="primary" disabled={act.busy} onClick={() => { try { void act.run(() => calls.post('/api/sim/action', JSON.parse(json))) } catch { act.setError('Invalid JSON') } }}>Send</Button>
          </div>
          <Field label="Request body"><TextArea rows={5} value={json} onChange={(e) => setJson(e.target.value)} aria-label="Action JSON" /></Field>
          {act.error && <p role="alert" className="mt-2 text-xs text-bad">{act.error}</p>}
          {act.result ? <div className="mt-2"><Json data={act.result} max={140} /></div> : null}
        </Card>
        <Card title="State-change log" pad={false}>
          <div className="max-h-[280px] overflow-y-auto">
            <Table head={['t', 'event', 'asset', 'change']}>
              {(events.data ?? []).slice().reverse().map((e, i) => (
                <tr key={i}><Td className="tabnum text-mute">{e.t}</Td><Td>{e.kind}</Td><Td>{e.asset}</Td><Td className="text-mute">{e.frm ? `${e.frm} → ${e.to}` : ''} {e.reason ?? ''}</Td></tr>
              ))}
            </Table>
          </div>
        </Card>
      </div>
      <Card title="Orders and routings" pad={false}>
        {!orders.data?.length ? <div className="p-4"><Empty>No open orders.</Empty></div> : (
          <Table head={['Order', 'SKU', 'Qty', 'Priority', 'Due in', 'Routing progress']}>
            {orders.data.map((o) => (
              <tr key={o.id}>
                <Td className="font-medium">{o.id} {o.rush && <Badge tone="bad">rush</Badge>} {o.deferrable && <Badge tone="mute">deferrable</Badge>}</Td>
                <Td>{o.sku}</Td><Td className="tabnum">{o.qty}</Td><Td className="tabnum">P{o.priority}</Td>
                <Td className={`tabnum ${o.due_in_min < 0 ? 'text-bad' : ''}`}>{fmt.dur(o.due_in_min)}</Td>
                <Td><div className="flex gap-1">{o.ops.map((op, i) => <span key={i} title={`${op.stage}: ${Math.round(op.done)}/${op.qty}`} className={`rounded px-1.5 py-0.5 text-[10px] ${op.finished_t != null ? 'bg-ok/20 text-ok' : op.done > 0 ? 'bg-accent/20 text-accent' : 'bg-white/5 text-mute'}`}>{op.stage}</span>)}</div></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Card title="Assets">
        <div className="grid gap-x-8 md:grid-cols-2">
          {(s?.assets ?? []).map((a) => <Kv key={a.id} k={<span>{a.id} <span className="text-[11px]">{a.name}</span></span>} v={<span className="flex items-center justify-end gap-2"><StateBadge state={a.state} /> {a.power_kw.toFixed(1)} kW</span>} />)}
        </div>
      </Card>
      <Card title="Simulation assumptions (tunable, shown on purpose)" right={<Badge tone="warn">synthetic calibration</Badge>}>
        <p className="mb-2 text-sm text-mute">Every cost, tariff, fault and plant-profile parameter lives in <code className="font-mono text-xs">sim/assumptions.yaml</code>. The A/B value story and the ROI calculator are only as good as these numbers - change them there and re-run.</p>
        {cfg.data && <Json data={cfg.data.assumptions} max={360} />}
      </Card>
    </Page>
  )
}
