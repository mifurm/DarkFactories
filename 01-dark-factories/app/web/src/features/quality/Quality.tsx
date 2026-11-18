import { useMemo, useState } from 'react'
import { Lines } from '../../components/charts'
import { Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls, withPlant, usePlant } from '../../plant'

type QRow = { asset: string; cpk: number | null; shift_sigma: number; offset: number; contained: boolean; violations: unknown[]; subgroups: number; status: string }
type Spc = { asset: string; available: boolean; metric: string; nominal: number; sigma: number; limits: { center: number; ucl: number; lcl: number; ucl_r: number; lcl_r: number; rbar: number }; points: { t: number; z: number; r: number }[]; violations: { rule: number; detail: string; index: number }[]; cpk: number | null; offset: number; contained: boolean; state: string }
type VItem = { id: string; predicted: string; confidence: number; source: string; findings: string[]; status: string; truth?: string; agree?: boolean; needs_review?: boolean }
type VStats = { inspected: number; agreement: number | null; pending_review: number; sources: string[] }

export default function Quality() {
  const calls = usePlantCalls()
  const { plantId } = usePlant()
  const sum = usePApi<{ assets: QRow[]; interventions: { t: number; asset: string; kind: string; dev?: number; offset?: number }[] }>('/api/quality/summary', { interval: 4000 })
  const [asset, setAsset] = useState('CNC-04')
  const spc = usePApi<Spc>(`/api/quality/spc/${asset}`, { interval: 4000 })
  const queue = usePApi<{ items: VItem[]; stats: VStats }>('/api/quality/vision/queue', { interval: 5000 })
  const batch = useAction<{ results: VItem[]; stats: VStats; threshold: number }>()
  const review = useAction()
  const rows = sum.data?.assets ?? []
  const s = spc.data
  const data = useMemo(() => (s?.points ?? []).map((p) => ({ x: p.t, z: p.z, r: p.r })), [s])
  const stats = batch.result?.stats ?? queue.data?.stats
  return (
    <Page title="Quality & vision" subtitle="SPC (X-bar/R charts, Western Electric rules, Cpk) watches every measured characteristic; on a shift the agent compensates, contains the lot and tells Maintenance. Vision inspection uses a multimodal model on synthetic part images, with human review of low-confidence calls.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_520px]">
        <div className="space-y-4">
          <Card title="Process capability" pad={false}>
            <div className="max-h-[300px] overflow-auto">
              <Table head={['Asset', 'Status', 'Cpk', 'Shift (σ)', 'Compensation', 'Violations']}>
                {rows.map((r) => (
                  <tr key={r.asset} onClick={() => setAsset(r.asset)} className={`cursor-pointer hover:bg-white/5 ${asset === r.asset ? 'bg-accent/10' : ''}`}>
                    <Td className="font-medium">{r.asset}</Td>
                    <Td><Badge tone={r.status === 'ok' ? 'ok' : r.contained ? 'violet' : 'warn'}>{r.status}{r.contained ? ' · contained' : ''}</Badge></Td>
                    <Td className={`tabnum ${r.cpk != null && r.cpk < 1.33 ? 'text-warn' : ''}`}>{r.cpk != null ? r.cpk.toFixed(2) : '-'}</Td>
                    <Td className="tabnum">{(r.shift_sigma ?? 0).toFixed(2)}</Td><Td className="tabnum">{(r.offset ?? 0).toFixed(2)} σ</Td><Td className="tabnum">{(r.violations ?? []).length}</Td>
                  </tr>
                ))}
              </Table>
            </div>
          </Card>
          <Card title={`X-bar chart · ${asset}${s?.metric ? ' · ' + s.metric : ''}`} right={<span className="flex gap-2">{s && <Badge tone={s.violations.length ? 'bad' : 'ok'}>{s.violations.length} rule violation(s)</Badge>}<Select aria-label="SPC asset" className="w-28" value={asset} onChange={(e) => setAsset(e.target.value)}>{rows.map((r) => <option key={r.asset}>{r.asset}</option>)}</Select></span>}>
            {s?.available ? (
              <>
                <Lines data={data} lines={[{ key: 'z', name: 'subgroup mean (σ from nominal)', color: '#38bdf8' }]} height={210} refs={[{ y: s.limits.ucl, label: 'UCL', color: '#f87171' }, { y: s.limits.center, label: 'CL', color: '#8499ae' }, { y: s.limits.lcl, label: 'LCL', color: '#f87171' }]} />
                <Lines data={data} lines={[{ key: 'r', name: 'range', color: '#a78bfa' }]} height={110} refs={[{ y: s.limits.ucl_r, label: 'UCL(R)', color: '#f87171' }]} />
                {s.violations.length > 0 && <ul className="mt-1 list-disc pl-5 text-[12px] text-bad">{s.violations.slice(0, 4).map((v, i) => <li key={i}>Rule {v.rule}: {v.detail}</li>)}</ul>}
              </>
            ) : <Empty>This asset has no measured quality characteristic (SPC applies to machining, molding and assembly).</Empty>}
          </Card>
          <Card title="Agent interventions (compensation / containment)" pad={false}>
            {!sum.data?.interventions.length ? <div className="p-4"><Empty>No interventions yet - inject "Quality drift" or "Tool wear" on the Control Tower.</Empty></div> : (
              <Table head={['t (min)', 'Asset', 'Action', 'Deviation (σ)', 'New offset']}>
                {sum.data.interventions.slice().reverse().slice(0, 8).map((i, k) => <tr key={k}><Td className="tabnum">{i.t}</Td><Td>{i.asset}</Td><Td>{i.kind}</Td><Td className="tabnum">{fmt.n(i.dev, 2)}</Td><Td className="tabnum">{fmt.n(i.offset, 2)}</Td></tr>)}
              </Table>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Vision inspection" right={<Badge tone="warn">synthetic part images</Badge>}>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Inspected" value={stats?.inspected ?? 0} />
              <Stat label="Agreement" value={stats?.agreement != null ? fmt.pct(stats.agreement, 0) : '-'} sub="vs known defect" />
              <Stat label="To review" value={stats?.pending_review ?? 0} tone={stats?.pending_review ? 'warn' : 'ok'} />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Button tone="primary" size="sm" disabled={batch.busy} onClick={async () => { await batch.run(() => calls.post('/api/quality/vision/batch', { n: 6, seed: Math.floor(Math.random() * 10000) })); void queue.reload() }}>{batch.busy ? 'Inspecting…' : 'Inspect 6 new parts'}</Button>
              <span className="text-[11px] text-mute">{(stats?.sources ?? []).join(', ') || 'model: Azure OpenAI vision (offline: classical CV)'}</span>
            </div>
            {batch.error && <p role="alert" className="mt-2 text-xs text-bad">{batch.error}</p>}
            {batch.result && (
              <div className="mt-3 grid grid-cols-3 gap-2">
                {batch.result.results.map((r) => (
                  <div key={r.id} className="rounded-lg border border-line bg-panel2/50 p-1.5 text-[11px]">
                    <img src={withPlant(`/api/quality/vision/image/${r.id}`, plantId)} alt={`Part ${r.id}`} className="aspect-square w-full rounded object-cover" />
                    <div className="mt-1 flex items-center justify-between"><Badge tone={r.agree ? 'ok' : 'bad'}>{r.predicted}</Badge><span className="tabnum text-mute">{(r.confidence * 100).toFixed(0)}%</span></div>
                    <div className="text-mute">truth: {r.truth}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title="Human review queue" pad={false}>
            {!queue.data?.items.length ? <div className="p-4"><Empty>No low-confidence calls waiting.</Empty></div> : (
              <ul className="divide-y divide-line/60">
                {queue.data.items.slice(0, 5).map((i) => (
                  <li key={i.id} className="flex items-center gap-3 p-3">
                    <img src={withPlant(`/api/quality/vision/image/${i.id}`, plantId)} alt="" className="h-12 w-12 rounded object-cover" />
                    <div className="min-w-0 flex-1 text-[12px]"><div className="font-mono">{i.id}</div><div className="text-mute">model: {i.predicted} ({(i.confidence * 100).toFixed(0)}%)</div></div>
                    {i.status === 'pending' ? (
                      <div className="flex gap-1">{['ok', 'scratch', 'crack', 'dent'].map((l) => <Button key={l} size="sm" tone="ghost" disabled={review.busy} onClick={async () => { await review.run(() => calls.post(`/api/quality/vision/review/${i.id}`, { label: l })); void queue.reload() }}>{l}</Button>)}</div>
                    ) : <Badge tone="ok">reviewed</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </Page>
  )
}
