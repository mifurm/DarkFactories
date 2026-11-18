import { useMemo } from 'react'
import { useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Slot = { order: string; idx: number; stage: string; asset: string; start: number; end: number; setup: number; reason: string; pinned: boolean }
type Sched = { rule: string; now: number; tardiness_min: number; tardiness_eur: number; late_orders: number; makespan_min: number; utilization: number; setup_min: number; order_end: Record<string, number>; slots: Slot[]; notes: string[]; violations: string[]; machines: Record<string, unknown> }
type Cmp = { planner: Sched; fifo: Sched; improvement: { tardiness_min: number; late_orders: number; tardiness_eur: number } }
type Exp = { summary: string; orders: { order: string; projected_end: number; baseline_end: number; ops: { stage: string; asset: string; start: number; end: number; why: string }[] }[] }

const COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#a78bfa', '#f472b6', '#22d3ee', '#fb923c', '#a3e635', '#e879f9', '#60a5fa']
const colorOf = (o: string) => COLORS[[...o].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length]

function Gantt({ sched }: { sched: Sched }) {
  const rows = useMemo(() => [...new Set(sched.slots.map((s) => s.asset))].sort(), [sched])
  const t0 = sched.now
  const t1 = Math.max(t0 + 240, ...sched.slots.map((s) => s.end))
  const W = 1000
  const L = 70
  const x = (t: number) => L + ((t - t0) / (t1 - t0)) * (W - L - 8)
  const RH = 22
  const ticks = Array.from({ length: Math.floor((t1 - t0) / 120) + 1 }, (_, i) => t0 + i * 120)
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * RH + 26}`} className="w-full" role="img" aria-label="Schedule Gantt chart">
      {ticks.map((t) => (
        <g key={t}><line x1={x(t)} x2={x(t)} y1={12} y2={rows.length * RH + 14} stroke="#213245" strokeDasharray="3 3" /><text x={x(t)} y={9} fontSize={9} textAnchor="middle" fill="#8499ae">+{Math.round((t - t0) / 60)} h</text></g>
      ))}
      {rows.map((r, i) => (
        <g key={r} transform={`translate(0,${14 + i * RH})`}>
          <text x={L - 8} y={RH / 2 + 3} fontSize={10} textAnchor="end" fill="#8499ae">{r}</text>
          <rect x={L} y={RH - 1} width={W - L - 8} height={0.5} fill="#213245" />
          {sched.slots.filter((s) => s.asset === r).map((s, k) => (
            <g key={k}>
              {s.setup > 0 && <rect x={x(s.start)} y={3} width={Math.max(1, x(s.start + s.setup) - x(s.start))} height={RH - 7} fill="#64748b" opacity={0.6} />}
              <rect x={x(s.start + s.setup)} y={3} width={Math.max(2, x(s.end) - x(s.start + s.setup))} height={RH - 7} rx={3} fill={colorOf(s.order)} opacity={s.pinned ? 1 : 0.8} stroke={s.pinned ? '#fff' : 'none'} strokeOpacity={0.5}>
                <title>{`${s.order} · ${s.stage} on ${s.asset}\n${fmt.dur(s.start - t0)} → ${fmt.dur(s.end - t0)} (setup ${s.setup} min)\n${s.reason}`}</title>
              </rect>
              {x(s.end) - x(s.start + s.setup) > 38 && <text x={x(s.start + s.setup) + 4} y={RH / 2 + 2} fontSize={8.5} fill="#06101a" fontWeight={600}>{s.order.replace('SO-', '')}</text>}
            </g>
          ))}
        </g>
      ))}
    </svg>
  )
}

export default function Planner() {
  const calls = usePlantCalls()
  const sched = usePApi<Sched>('/api/planner/schedule', { interval: 4000 })
  const cmp = usePApi<Cmp>('/api/planner/compare', { interval: 6000 })
  const exp = usePApi<Exp>('/api/planner/explain')
  const act = useAction()
  const s = sched.data
  const c = cmp.data
  const metric = (label: string, a?: number, b?: number, f: (v?: number) => string = (v) => fmt.n(v, 0), lowerBetter = true) => (
    <tr><Td>{label}</Td><Td className="tabnum">{f(a)}</Td><Td className="tabnum text-mute">{f(b)}</Td><Td className={`tabnum ${a === undefined || b === undefined ? '' : (lowerBetter ? a < b : a > b) ? 'text-ok' : a === b ? 'text-mute' : 'text-bad'}`}>{a !== undefined && b !== undefined ? `${a - b > 0 ? '+' : ''}${fmt.n(a - b, 1)}` : ''}</Td></tr>
  )
  return (
    <Page title="Planner / scheduler" subtitle="Dispatch-rule scheduling over finite-capacity machines with sequence-dependent set-ups, held to a feasibility check; re-plans on disruption and compares itself against plain FIFO on the same plant state." right={
      <div className="flex items-center gap-2"><Button size="sm" tone="primary" disabled={act.busy} onClick={async () => { await act.run(() => calls.post('/api/planner/replan', {})); void sched.reload(); void cmp.reload() }}>Re-plan now</Button></div>}>
      {act.error && <p role="alert" className="text-xs text-bad">{act.error}</p>}
      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Late orders (forecast)" value={s.late_orders} tone={s.late_orders ? 'warn' : 'ok'} />
          <Stat label="Tardiness" value={fmt.dur(s.tardiness_min)} sub={fmt.eur(s.tardiness_eur)} />
          <Stat label="Makespan" value={fmt.dur(s.makespan_min)} />
          <Stat label="Utilisation" value={fmt.pct(s.utilization, 0)} />
          <Stat label="Set-up time" value={fmt.dur(s.setup_min)} />
        </div>
      )}
      <Card title="Gantt - next hours (set-ups hatched grey, outlined = already running)" right={s && <Badge tone={s.violations.length ? 'bad' : 'ok'}>{s.violations.length ? `${s.violations.length} violations` : 'schedule feasible'}</Badge>}>
        {s?.slots.length ? <Gantt sched={s} /> : <Empty>No open operations to schedule.</Empty>}
        {s?.notes.map((n, i) => <p key={i} className="mt-1 text-[12px] text-warn">{n}</p>)}
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Planner vs FIFO (same plant state)" pad={false}>
          <Table head={['Metric', 'Planner', 'FIFO', 'Δ']}>
            {metric('Tardiness (min)', c?.planner.tardiness_min, c?.fifo.tardiness_min)}
            {metric('Late orders', c?.planner.late_orders, c?.fifo.late_orders)}
            {metric('Tardiness cost (EUR)', c?.planner.tardiness_eur, c?.fifo.tardiness_eur, (v) => fmt.eur(v))}
            {metric('Makespan (min)', c?.planner.makespan_min, c?.fifo.makespan_min)}
            {metric('Set-up time (min)', c?.planner.setup_min, c?.fifo.setup_min)}
          </Table>
          {c && <p className="p-3 text-[12px] text-mute">Improvement: {fmt.n(c.improvement.tardiness_min)} tardiness-min, {fmt.n(c.improvement.late_orders)} late orders, {fmt.eur(c.improvement.tardiness_eur)}.</p>}
        </Card>
        <Card title="Why this schedule?" pad={false}>
          <div className="max-h-[340px] overflow-auto p-3 text-[12px]">
            <p className="mb-2 text-sm">{exp.data?.summary}</p>
            {(exp.data?.orders ?? []).slice(0, 6).map((o) => (
              <div key={o.order} className="mb-2 rounded-lg border border-line bg-panel2/50 p-2">
                <div className="flex justify-between"><b>{o.order}</b><span className="text-mute">ends +{fmt.dur(o.projected_end - (s?.now ?? 0))} (FIFO +{fmt.dur(o.baseline_end - (s?.now ?? 0))})</span></div>
                {o.ops.map((op, i) => <Kv key={i} k={`${op.stage} → ${op.asset}`} v={<span className="text-[11px] text-mute">{op.why}</span>} />)}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </Page>
  )
}
