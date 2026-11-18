import { useMemo, useState } from 'react'
import { Field, Input, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type G = { nodes: { id: string; type: string; label: string }[]; edges: { from: string; to: string; kind: string }[]; t: number }
type Snap = { t: number; assets: { id: string }[] }
type Res = {
  accept: boolean
  explanation: string
  horizon_min: number
  mode: string
  t: number
  delta: Record<string, number>
  baseline: Record<string, number>
  with_actions: Record<string, number>
  counterfactual: { baseline_failures: unknown[]; action_failures: unknown[]; avoided_downtime_min: number; avoided_loss_eur: number; failure_avoided: boolean }
}
type ActionT = { kind: string; asset?: string; pct?: number; order?: string; duration?: number; start_in?: number }

const KINDS: Record<string, string> = { schedule_maintenance: 'Schedule maintenance', set_speed: 'Set speed', tool_change: 'Tool change', safe_stop: 'Safe-stop', expedite_order: 'Expedite order' }

const COLS = ['plant', 'area', 'line', 'machine', 'AMR']
function GraphView({ g }: { g: G }) {
  const layout = useMemo(() => {
    const col = (t: string) => (t === 'plant' ? 0 : t === 'area' ? 1 : t === 'line' ? 2 : t === 'AMR' ? 4 : 3)
    const groups: Record<number, G['nodes']> = {}
    g.nodes.forEach((n) => (groups[col(n.type)] ??= []).push(n))
    const pos = new Map<string, { x: number; y: number }>()
    Object.entries(groups).forEach(([c, list]) => list.forEach((n, i) => pos.set(n.id, { x: 70 + Number(c) * 215, y: 20 + (i + 0.5) * (460 / Math.max(list.length, 1)) })))
    return pos
  }, [g])
  const color = (k: string) => (k === 'flows_to' ? '#38bdf8' : k === 'supplies' ? '#fbbf24' : '#34455a')
  return (
    <svg viewBox="0 0 1010 500" className="w-full" role="img" aria-label="Asset graph: plant, areas, lines, machines">
      {g.edges.map((e, i) => {
        const a = layout.get(e.from)
        const b = layout.get(e.to)
        return a && b ? <line key={i} x1={a.x + 38} y1={a.y} x2={b.x - 38} y2={b.y} stroke={color(e.kind)} strokeOpacity={e.kind === 'contains' ? 0.45 : 0.55} strokeWidth={e.kind === 'contains' ? 0.8 : 1.1} strokeDasharray={e.kind === 'supplies' ? '3 3' : undefined} /> : null
      })}
      {g.nodes.map((n) => {
        const p = layout.get(n.id)
        if (!p) return null
        return (
          <g key={n.id} transform={`translate(${p.x - 38},${p.y - 9})`}>
            <rect width={76} height={18} rx={5} fill="#162231" stroke="#213245" />
            <text x={38} y={12.5} fontSize={9.5} textAnchor="middle" fill="#d9e4ef">{n.label.length > 13 ? n.label.slice(0, 12) + '…' : n.label}</text>
          </g>
        )
      })}
      {COLS.map((c, i) => <text key={c} x={70 + i * 215} y={10} fontSize={9} textAnchor="middle" fill="#8499ae" letterSpacing={1.4}>{c.toUpperCase()}</text>)}
    </svg>
  )
}

const METRICS: [string, string, 'lower' | 'higher'][] = [['oee', 'OEE', 'higher'], ['downtime_min', 'Downtime (min)', 'lower'], ['tardiness_h', 'Tardiness (h)', 'lower'], ['overdue_orders', 'Overdue orders', 'lower'], ['scrap_units', 'Scrap units', 'lower'], ['energy_kwh', 'Energy (kWh)', 'lower'], ['units_good', 'Good units', 'higher']]

export default function Twin() {
  const calls = usePlantCalls()
  const graph = usePApi<G>('/api/twin/graph')
  const snap = usePApi<Snap>('/api/tower/snapshot', { interval: 5000 })
  const ids = (snap.data?.assets ?? []).map((a) => a.id)
  const [actions, setActions] = useState<ActionT[]>([{ kind: 'schedule_maintenance', asset: 'CNC-04', duration: 45, start_in: 15 }])
  const [horizon, setHorizon] = useState(240)
  const act = useAction<Res>()
  const fork = useAction<{ forked_at_t: number; minutes: number; live_t_unchanged: number; kpi: Record<string, number>; failures: unknown[] }>()
  const upd = (i: number, patch: Partial<ActionT>) => setActions((a) => a.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const run = () => {
    const t = snap.data?.t ?? 0
    const body = actions.map((a) => {
      if (a.kind === 'schedule_maintenance') return { kind: a.kind, asset: a.asset, start_t: t + (a.start_in ?? 15), duration: a.duration ?? 45 }
      if (a.kind === 'set_speed') return { kind: a.kind, asset: a.asset, pct: a.pct ?? 85 }
      if (a.kind === 'expedite_order') return { kind: a.kind, order: a.order ?? 'SO-0001' }
      return { kind: a.kind, asset: a.asset }
    })
    return act.run(() => calls.post<Res>('/api/twin/whatif', { actions: body, horizon_min: horizon }))
  }
  const r = act.result
  return (
    <Page title="Digital twin & what-if" subtitle="A live asset graph plus a deterministic fork of the running plant: evaluate any action sequence on a copy, compare KPIs and cost, and see the counterfactual - without touching the live plant.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
        <div className="space-y-4">
          <Card title={`Asset graph · ${graph.data?.nodes.length ?? '…'} nodes · ${graph.data?.edges.length ?? '…'} relations`} right={<span className="flex gap-2 text-[10px] text-mute"><span className="text-[#38bdf8]">— flows to</span><span className="text-warn">- - supplies</span></span>}>
            {graph.data ? <GraphView g={graph.data} /> : <Empty>Loading…</Empty>}
          </Card>
          {r && (
            <Card title="What-if result" right={<Badge tone={r.accept ? 'ok' : 'warn'}>{r.accept ? 'recommended' : 'not recommended'}</Badge>}>
              <p className="mb-3 text-sm">{r.explanation}</p>
              <Table head={['KPI', 'Baseline (no action)', 'With actions', 'Δ']}>
                {METRICS.map(([k, label, better]) => {
                  const d = (r.with_actions[k] ?? 0) - (r.baseline[k] ?? 0)
                  const good = better === 'lower' ? d < 0 : d > 0
                  return (
                    <tr key={k}>
                      <Td>{label}</Td>
                      <Td className="tabnum">{fmt.n(r.baseline[k], k === 'oee' ? 3 : 1)}</Td>
                      <Td className="tabnum">{fmt.n(r.with_actions[k], k === 'oee' ? 3 : 1)}</Td>
                      <Td className={`tabnum ${Math.abs(d) < 1e-9 ? 'text-mute' : good ? 'text-ok' : 'text-bad'}`}>{d > 0 ? '+' : ''}{fmt.n(d, k === 'oee' ? 3 : 1)}</Td>
                    </tr>
                  )
                })}
              </Table>
              <div className="mt-3 grid gap-x-8 md:grid-cols-2">
                <Kv k="Net value (EUR)" v={<b className={r.delta.net_value_eur >= 0 ? 'text-ok' : 'text-bad'}>{fmt.eur(r.delta.net_value_eur)}</b>} />
                <Kv k="Failure avoided (counterfactual)" v={r.counterfactual.failure_avoided ? <Badge tone="ok">yes</Badge> : <Badge tone="mute">no</Badge>} />
                <Kv k="Avoided downtime" v={`${fmt.n(r.counterfactual.avoided_downtime_min)} min`} />
                <Kv k="Avoided loss" v={fmt.eur(r.counterfactual.avoided_loss_eur)} />
                <Kv k="Fork mode" v={r.mode} />
                <Kv k="Horizon" v={fmt.dur(r.horizon_min)} />
              </div>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Action sequence" right={<Button size="sm" tone="ghost" disabled={actions.length >= 6} onClick={() => setActions([...actions, { kind: 'set_speed', asset: ids[0] ?? 'CNC-01', pct: 85 }])}>+ add</Button>}>
            <div className="space-y-2">
              {actions.map((a, i) => (
                <div key={i} className="rounded-lg border border-line bg-panel2/50 p-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Action"><Select aria-label={`Action ${i + 1}`} value={a.kind} onChange={(e) => upd(i, { kind: e.target.value })}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
                    {a.kind === 'expedite_order' ? (
                      <Field label="Order"><Input value={a.order ?? 'SO-0001'} onChange={(e) => upd(i, { order: e.target.value })} aria-label="Order id" /></Field>
                    ) : (
                      <Field label="Asset"><Select aria-label={`Asset ${i + 1}`} value={a.asset} onChange={(e) => upd(i, { asset: e.target.value })}>{(ids.length ? ids : [a.asset ?? '']).map((x) => <option key={x}>{x}</option>)}</Select></Field>
                    )}
                    {a.kind === 'schedule_maintenance' && <><Field label="Start in (min)"><Input type="number" value={a.start_in ?? 15} onChange={(e) => upd(i, { start_in: Number(e.target.value) })} /></Field><Field label="Duration (min)"><Input type="number" value={a.duration ?? 45} onChange={(e) => upd(i, { duration: Number(e.target.value) })} /></Field></>}
                    {a.kind === 'set_speed' && <Field label="Speed %"><Input type="number" value={a.pct ?? 85} onChange={(e) => upd(i, { pct: Number(e.target.value) })} /></Field>}
                  </div>
                  {actions.length > 1 && <button className="mt-1 text-[11px] text-mute hover:text-bad" onClick={() => setActions(actions.filter((_, j) => j !== i))}>remove</button>}
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-end gap-2">
              <Field label="Horizon (min)" className="w-32"><Input type="number" min={15} max={720} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} /></Field>
              <Button tone="primary" disabled={act.busy} onClick={run}>{act.busy ? 'Simulating…' : 'Run what-if'}</Button>
            </div>
            {act.error && <p role="alert" className="mt-2 text-xs text-bad">{act.error}</p>}
          </Card>
          <Card title="Free-running fork">
            <p className="text-[12px] text-mute">Fork the live plant, let the copy run N minutes with no actions, and prove the live clock is untouched.</p>
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" disabled={fork.busy} onClick={() => fork.run(() => calls.post('/api/twin/fork', { minutes: 120 }))}>Fork + run 120 min</Button>
            </div>
            {fork.error && <p role="alert" className="mt-1 text-xs text-bad">{fork.error}</p>}
            {fork.result && (
              <div className="mt-2 text-[12px]">
                <Kv k="forked at t" v={fork.result.forked_at_t} />
                <Kv k="live clock afterwards" v={`${fork.result.live_t_unchanged} (unchanged by the fork)`} />
                <Kv k="OEE of fork" v={fmt.pct(fork.result.kpi.oee, 1)} />
                <Kv k="failures in fork" v={fork.result.failures.length} />
              </div>
            )}
          </Card>
        </div>
      </div>
    </Page>
  )
}
