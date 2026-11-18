import { useEffect, useRef, useState } from 'react'
import { Field, Input, Json, Meter, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Table, Td } from '../../components/ui'
import { api, post } from '../../lib/api'
import { fmt } from '../../lib/feature'

export type Metric = { label: string; unit: string; lower_is_better: boolean; off_mean: number; on_mean: number; improvement: number; improvement_pct: number | null; ci_low: number; ci_high: number; p_one_sided: number; significant: boolean; n: number; per_seed: number[] }
export type Ab = { available?: boolean; config: { seeds: number[]; horizon_h: number; warmup_min: number; intensity: number; plant: string; latency_min: number }; seeds: number[]; metrics: Record<string, Metric>; elapsed_s: number; method: string; caveat: string; rows: { seed: number; off: Record<string, number>; on: Record<string, number> }[] }
type Job = { id: string; status: 'running' | 'done' | 'failed'; progress: number; error?: string; result?: Ab }

const HEADLINE = ['downtime_h', 'late_orders', 'loss_eur', 'oee', 'tardiness_h', 'scrap_units', 'otif']
const fx = (v: number, unit: string) => (unit === 'EUR' ? fmt.eur(v) : unit === 'pts' ? `${v.toFixed(1)} pts` : `${fmt.n(v, Math.abs(v) < 10 ? 2 : 0)} ${unit}`)

function Forest({ metrics }: { metrics: [string, Metric][] }) {
  const rows = metrics.filter(([, m]) => m.improvement_pct != null && Math.abs(m.off_mean) > 1e-9)
  const lim = Math.max(30, ...rows.flatMap(([, m]) => [Math.abs((m.ci_low / m.off_mean) * 100), Math.abs((m.ci_high / m.off_mean) * 100)]))
  const W = 1000
  const L = 320
  const x = (p: number) => L + ((p + lim) / (2 * lim)) * (W - L - 90)
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * 30 + 34}`} className="w-full" role="img" aria-label="Improvement with 95 % confidence intervals">
      <line x1={x(0)} x2={x(0)} y1={6} y2={rows.length * 30 + 8} stroke="#8499ae" strokeDasharray="3 3" />
      {[-lim, -lim / 2, lim / 2, lim].map((v) => <text key={v} x={x(v)} y={rows.length * 30 + 24} fontSize={9} textAnchor="middle" fill="#8499ae">{v > 0 ? '+' : ''}{v.toFixed(0)}%</text>)}
      <text x={x(0)} y={rows.length * 30 + 24} fontSize={9} textAnchor="middle" fill="#8499ae">0</text>
      {rows.map(([k, m], i) => {
        const y = 20 + i * 30
        const lo = (m.ci_low / m.off_mean) * 100
        const hi = (m.ci_high / m.off_mean) * 100
        const pt = (m.improvement / m.off_mean) * 100
        const col = m.significant ? '#34d399' : '#fbbf24'
        return (
          <g key={k}>
            <text x={L - 10} y={y + 4} fontSize={11} textAnchor="end" fill="#d9e4ef">{m.label.length > 46 ? m.label.slice(0, 44) + '…' : m.label}</text>
            <line x1={x(Math.max(-lim, lo))} x2={x(Math.min(lim, hi))} y1={y} y2={y} stroke={col} strokeWidth={3} strokeLinecap="round" />
            <circle cx={x(Math.max(-lim, Math.min(lim, pt)))} cy={y} r={5} fill={col} />
            <text x={W - 6} y={y + 4} fontSize={10} textAnchor="end" fill={col}>{pt > 0 ? '+' : ''}{pt.toFixed(0)}%</text>
          </g>
        )
      })}
    </svg>
  )
}

export default function AbPanel({ onResult }: { onResult?: (a: Ab) => void }) {
  const [res, setRes] = useState<Ab | null>(null)
  const [cfg, setCfg] = useState({ n_seeds: 16, horizon_h: 8, intensity: 1, latency_min: 20 })
  const [job, setJob] = useState<Job | null>(null)
  const [design, setDesign] = useState<Record<string, unknown> | null>(null)
  const act = useAction<Job>()
  const timer = useRef<number | null>(null)

  const load = async () => {
    const r = await api<Ab & { available: boolean; running?: boolean }>('/api/value/ab/latest')
    if (r.available) {
      setRes(r)
      onResult?.(r)
    } else if (r.running) timer.current = window.setTimeout(load, 1500)
  }
  useEffect(() => {
    void load()
    void api<{ ab_design: Record<string, unknown> }>('/api/value/assumptions').then((a) => setDesign(a.ab_design)).catch(() => undefined)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const poll = (id: string) => {
    timer.current = window.setTimeout(async () => {
      try {
        const j = await api<Job>(`/api/value/ab/jobs/${id}`)
        setJob(j)
        if (j.status === 'running') poll(id)
        else if (j.status === 'done' && j.result) { setRes(j.result); onResult?.(j.result) }
      } catch { /* ignore transient */ }
    }, 600)
  }
  const run = async () => {
    const j = await act.run(() => post<Job>('/api/value/ab/run', cfg))
    if (j) { setJob(j); poll(j.id) }
  }
  const metrics = Object.entries(res?.metrics ?? {})
  const head = metrics.filter(([k]) => HEADLINE.includes(k)).sort((a, b) => HEADLINE.indexOf(a[0]) - HEADLINE.indexOf(b[0]))
  const sig = metrics.filter(([, m]) => m.significant).length
  return (
    <div className="space-y-4">
      <Card title="Replay: swarm OFF vs ON — same seeds, same fault schedule" right={res && <Badge tone="info">{res.config.seeds.length} seeds · {res.config.horizon_h} sim-h · {res.elapsed_s.toFixed(1)} s</Badge>}>
        <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-5">
          <Field label="Seeds"><Input type="number" min={3} max={30} value={cfg.n_seeds} onChange={(e) => setCfg({ ...cfg, n_seeds: Number(e.target.value) })} aria-label="Number of seeds" /></Field>
          <Field label="Horizon (sim-h)"><Select value={cfg.horizon_h} onChange={(e) => setCfg({ ...cfg, horizon_h: Number(e.target.value) })} aria-label="Horizon">{[4, 8, 12].map((h) => <option key={h} value={h}>{h} h</option>)}</Select></Field>
          <Field label="Fault intensity" hint="share of the fault library"><Select value={cfg.intensity} onChange={(e) => setCfg({ ...cfg, intensity: Number(e.target.value) })} aria-label="Fault intensity"><option value={0.5}>0.5x</option><option value={1}>1.0x (stress)</option></Select></Field>
          <Field label="Human approval latency"><Select value={cfg.latency_min} onChange={(e) => setCfg({ ...cfg, latency_min: Number(e.target.value) })} aria-label="Approval latency">{[5, 20, 45, 90].map((m) => <option key={m} value={m}>{m} sim-min</option>)}</Select></Field>
          <Button tone="primary" disabled={act.busy || job?.status === 'running'} onClick={run}>{job?.status === 'running' ? 'Running…' : 'Run replay'}</Button>
        </div>
        {job?.status === 'running' && <div className="mt-3"><Meter value={job.progress} max={1} label="A/B progress" /><p className="mt-1 text-[11px] text-mute">Simulating {cfg.n_seeds} seeds × 2 arms… {(job.progress * 100).toFixed(0)}%</p></div>}
        {(act.error || job?.status === 'failed') && <p role="alert" className="mt-2 text-xs text-bad">{act.error ?? job?.error}</p>}
      </Card>
      {!res ? <Empty>Computing the default 10-seed replay on the server…</Empty> : (
        <>
          <Card title={`Improvement with 95 % confidence intervals · ${sig}/${metrics.length} metrics significant`} right={<Badge tone="warn">synthetic plant · assumed fault load</Badge>}>
            <Forest metrics={metrics} />
            <p className="mt-1 text-[11px] text-mute">Bars are paired differences (ON vs OFF, same seed) as a % of the baseline mean; green = the 95 % interval excludes zero. Positive = the swarm is better.</p>
          </Card>
          <Card title="Results (mean over seeds)" pad={false}>
            <Table head={['Metric', 'Swarm OFF', 'Swarm ON', 'Improvement', '95 % CI', 'p (one-sided)', 'Verdict']}>
              {(head.length ? [...head, ...metrics.filter(([k]) => !HEADLINE.includes(k))] : metrics).map(([k, m]) => (
                <tr key={k} data-testid={`ab-${k}`}>
                  <Td className="font-medium">{m.label}</Td><Td className="tabnum">{fx(m.off_mean, m.unit)}</Td><Td className="tabnum">{fx(m.on_mean, m.unit)}</Td>
                  <Td className={`tabnum font-medium ${m.improvement > 0 ? 'text-ok' : 'text-bad'}`}>{m.improvement > 0 ? '+' : ''}{fx(m.improvement, m.unit)}{m.improvement_pct != null && ` (${m.improvement_pct > 0 ? '+' : ''}${m.improvement_pct.toFixed(0)}%)`}</Td>
                  <Td className="tabnum text-[12px] text-mute">[{m.ci_low.toFixed(2)}, {m.ci_high.toFixed(2)}]</Td><Td className="tabnum text-mute">{m.p_one_sided < 0.001 ? '<0.001' : m.p_one_sided.toFixed(3)}</Td>
                  <Td><Badge tone={m.significant ? 'ok' : m.improvement > 0 ? 'warn' : 'bad'}>{m.significant ? 'significant' : m.improvement > 0 ? 'not significant' : 'not better'}</Badge></Td>
                </tr>
              ))}
            </Table>
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="How to read this (honest limits)">
              <p className="text-[13px]">{res.method}</p>
              <p className="mt-2 rounded-lg border border-warn/30 bg-warn/10 p-2 text-[12px] text-warn">{res.caveat}</p>
              <p className="mt-2 text-[12px] text-mute">Absolute energy cost can be <i>higher</i> with the swarm because the plant does more work in the same window; energy per unit-operation is the fair comparison and is shown separately.</p>
            </Card>
            <Card title="Experiment design & assumptions (editable in sim/assumptions.yaml)">
              {design ? <Json data={design} max={220} /> : <Empty>Loading…</Empty>}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
