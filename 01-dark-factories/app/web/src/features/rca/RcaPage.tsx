import { useMemo, useState } from 'react'
import { Bars } from '../../components/charts'
import { Meter, Mono, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Hyp = { cause: string; asset: string; score: number; evidence: { t: number; event: string; detail: Record<string, unknown> }[]; first_t: number; rank: number; confidence: number; explanation: string }
type Rca = { asset: string; symptom: { t: number; state: string; reason: string } | null; pareto: { cause: string; minutes: number; share: number; cumulative: number; worst_asset: string }[]; hypotheses: Hyp[]; graph: { nodes: { id: string; asset: string; count: number; first_t: number }[]; edges: { from: string; to: string; co_occurrences: number; median_lag_min: number; topology: string }[]; window_min: number }; assets: string[] }

function Graph({ g }: { g: Rca['graph'] }) {
  const n = g.nodes.length
  if (!n) return <Empty>No correlated loss events in the window yet.</Empty>
  const R = 150
  const pos = new Map(g.nodes.map((nd, i) => [nd.id, { x: 330 + R * 1.5 * Math.cos((2 * Math.PI * i) / n - Math.PI / 2), y: 175 + R * Math.sin((2 * Math.PI * i) / n - Math.PI / 2) }]))
  return (
    <svg viewBox="0 0 660 350" className="w-full" role="img" aria-label="Causal graph of correlated loss events">
      <defs><marker id="arr" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L8 4L0 8z" fill="#38bdf8" /></marker></defs>
      {g.edges.map((e, i) => {
        const a = pos.get(e.from)
        const b = pos.get(e.to)
        if (!a || !b) return null
        return <g key={i}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#38bdf8" strokeOpacity={0.5} strokeWidth={Math.min(4, 1 + e.co_occurrences)} markerEnd="url(#arr)" /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} fontSize={9} fill="#8499ae" textAnchor="middle">{e.median_lag_min} min</text></g>
      })}
      {g.nodes.map((nd) => {
        const p = pos.get(nd.id)!
        const [asset, state] = nd.id.split(':')
        return <g key={nd.id} transform={`translate(${p.x - 52},${p.y - 16})`}><rect width={104} height={32} rx={7} fill="#162231" stroke="#34455a" /><text x={52} y={14} fontSize={10.5} fontWeight={600} textAnchor="middle" fill="#d9e4ef">{asset}</text><text x={52} y={26} fontSize={9} textAnchor="middle" fill="#fbbf24">{state} ×{nd.count}</text></g>
      })}
    </svg>
  )
}

export default function RcaPage() {
  const calls = usePlantCalls()
  const [asset, setAsset] = useState('')
  const rca = usePApi<Rca>(`/api/rca/analyze${asset ? `?asset=${asset}` : ''}`, { interval: 8000 })
  const nar = useAction<{ text: string; source: string }>()
  const r = rca.data
  const bars = useMemo(() => (r?.pareto ?? []).slice(0, 8).map((p) => ({ cause: p.cause.replace('state:', ''), minutes: Math.round(p.minutes) })), [r])
  return (
    <Page title="Root-cause analysis" subtitle="Loss events are mined from the event log into a Pareto, then candidate causes are ranked by temporal precedence, topology (upstream/downstream) and co-occurrence. The ranked hypotheses are deterministic; the model only narrates them for the plant manager." right={
      <div className="flex items-center gap-2"><Select aria-label="RCA asset" className="w-44" value={asset} onChange={(e) => { setAsset(e.target.value); nar.setResult(null) }}><option value="">worst asset (auto)</option>{(r?.assets ?? []).map((a) => <option key={a}>{a}</option>)}</Select><Button tone="primary" size="sm" disabled={nar.busy} onClick={() => nar.run(() => calls.post('/api/rca/narrate', { asset: asset || r?.asset }))}>{nar.busy ? 'Narrating…' : 'Narrate'}</Button></div>}>
      {nar.error && <p role="alert" className="text-xs text-bad">{nar.error}</p>}
      {nar.result && <Card title="Narrative" right={<Badge tone="info">{nar.result.source}</Badge>}><p className="text-sm">{nar.result.text}</p></Card>}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Loss Pareto (minutes)">
          {bars.length ? <Bars data={bars} x="cause" bars={[{ key: 'minutes', color: '#fbbf24' }]} layout="vertical" height={280} /> : <Empty>No loss events recorded yet.</Empty>}
        </Card>
        <Card title={`Hypotheses for ${r?.asset ?? '…'}`} right={r?.symptom && <Mono>{r.symptom.state} · {r.symptom.reason}</Mono>}>
          {!r?.hypotheses.length ? <Empty>No correlated upstream events found for this symptom.</Empty> : (
            <div className="space-y-2">
              {r.hypotheses.slice(0, 4).map((h) => (
                <div key={h.rank} className="rounded-lg border border-line bg-panel2/50 p-3">
                  <div className="flex items-center justify-between gap-2"><div className="font-medium">#{h.rank} {h.cause}</div><span className="tabnum text-[12px] text-mute">confidence {fmt.pct(h.confidence, 0)}</span></div>
                  <div className="my-1"><Meter value={h.confidence} max={1} tone={h.confidence > 0.6 ? 'ok' : 'warn'} /></div>
                  <p className="text-[12px] text-mute">{h.explanation}</p>
                  <details className="mt-1 text-[11px]"><summary className="cursor-pointer text-mute">{h.evidence.length} evidence event(s)</summary><ul className="mt-1 space-y-0.5">{h.evidence.slice(0, 5).map((e, i) => <li key={i} className="tabnum text-mute">t={e.t} · {e.event} · {JSON.stringify(e.detail)}</li>)}</ul></details>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <Card title={`Causal graph · window ${fmt.dur(r?.graph.window_min)}`}>{r ? <Graph g={r.graph} /> : <Empty>Loading…</Empty>}</Card>
    </Page>
  )
}
