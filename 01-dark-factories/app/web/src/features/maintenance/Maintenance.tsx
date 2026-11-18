import { useMemo, useState } from 'react'
import { Lines } from '../../components/charts'
import { Input, Meter, Mono, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Row = { asset: string; type: string; ready: boolean; status: string; baseline_cycles: number; score: number; iso: number; vib: number | null; temp: number | null; health_est: number | null; rul_min: number | null; signature: { name: string; similarity: number; actionable: boolean } | null; alert: boolean }
type Health = { assets: Row[]; alerts: { t: number; asset: string; rul_min: number; signature: string }[]; spares: { part: string; on_hand: number; min: number; lead_h: number }[]; windows: { start_t: number; end_t: number }[]; t: number }
type WO = { id: string; asset: string; start_t: number; start_in_min: number; duration: number; kind: string; reason: string; spare: string | null; tool: boolean; status: string; created_by: string }
type Sig = { name: string; description: string; source: string; actionable: boolean; vector: number[] }

const woTone = (s: string) => (s === 'done' ? 'ok' : s === 'active' || s === 'running' ? 'violet' : s === 'cancelled' ? 'mute' : 'info') as 'ok' | 'violet' | 'mute' | 'info'

export default function Maintenance() {
  const calls = usePlantCalls()
  const health = usePApi<Health>('/api/maintenance/health', { interval: 3000 })
  const wos = usePApi<WO[]>('/api/maintenance/work-orders', { interval: 4000 })
  const sigs = usePApi<Sig[]>('/api/maintenance/signatures')
  const [asset, setAsset] = useState('CNC-04')
  const vib = usePApi<{ values: (number | null)[]; t0: number }>(`/api/maintenance/series?asset=${asset}&metric=vibration_rms&n=240`, { interval: 4000 })
  const tmp = usePApi<{ values: (number | null)[]; t0: number }>(`/api/maintenance/series?asset=${asset}&metric=bearing_temp_c&n=240`, { interval: 4000 })
  const create = useAction()
  const [startIn, setStartIn] = useState(60)
  const rows = health.data?.assets ?? []
  const sel = rows.find((r) => r.asset === asset)
  const chart = useMemo(() => (vib.data?.values ?? []).map((v, i) => ({ x: (vib.data?.t0 ?? 0) + i, vib: v, temp: tmp.data?.values?.[i] ?? null })), [vib.data, tmp.data])
  const alerts = rows.filter((r) => r.alert)
  return (
    <Page title="Predictive maintenance" subtitle="Per-asset baselines learned online, EWMA z-scores plus an isolation-forest score detect drift; failure signatures give a remaining-useful-life estimate with an uncertainty band; scheduling goes through the planner, spares and the policy engine.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Monitored assets" value={rows.length} sub={`${rows.filter((r) => r.ready).length} baselines ready`} />
        <Stat label="Active alerts" value={alerts.length} tone={alerts.length ? 'bad' : 'ok'} />
        <Stat label="Work orders" value={(wos.data ?? []).length} sub={`${(wos.data ?? []).filter((w) => w.status === 'done').length} done`} />
        <Stat label="Spares OK" value={`${(health.data?.spares ?? []).filter((s) => s.on_hand > s.min).length}/${(health.data?.spares ?? []).length}`} />
        <Stat label="Next window" value={health.data?.windows?.[0] ? fmt.dur(health.data.windows[0].start_t - health.data.t) : '-'} sub="planned maintenance" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_480px]">
        <Card title="Asset health" pad={false}>
          <div className="max-h-[420px] overflow-auto">
            <Table head={['Asset', 'Status', 'Anomaly score', 'Signature', 'Health est.', 'RUL']}>
              {rows.map((r) => (
                <tr key={r.asset} onClick={() => setAsset(r.asset)} className={`cursor-pointer hover:bg-white/5 ${asset === r.asset ? 'bg-accent/10' : ''}`}>
                  <Td className="font-medium">{r.asset} <span className="text-[10px] text-mute">{r.type}</span></Td>
                  <Td><Badge tone={r.alert ? 'bad' : r.ready ? 'ok' : 'mute'}>{r.status}</Badge></Td>
                  <Td className="w-40"><div className="flex items-center gap-2"><span className="tabnum w-8 text-[12px]">{(r.score ?? 0).toFixed(1)}</span><Meter value={r.score ?? 0} max={5} tone={(r.score ?? 0) > 3.2 ? 'bad' : (r.score ?? 0) > 2 ? 'warn' : 'ok'} /></div></Td>
                  <Td className="text-[12px]">{r.signature ? `${r.signature.name} (${(r.signature.similarity * 100).toFixed(0)}%)` : <span className="text-mute">-</span>}</Td>
                  <Td className="tabnum">{r.health_est != null ? fmt.pct(r.health_est, 0) : '-'}</Td>
                  <Td className="tabnum">{r.rul_min != null ? fmt.dur(r.rul_min) : '-'}</Td>
                </tr>
              ))}
            </Table>
          </div>
        </Card>
        <Card title={`${asset} - vibration & bearing temperature`} right={sel && <Badge tone={sel.alert ? 'bad' : 'ok'}>{sel.status}</Badge>}>
          <Lines data={chart} lines={[{ key: 'vib', name: 'vibration RMS', color: '#38bdf8' }]} height={150} xFormatter={() => ''} />
          <Lines data={chart} lines={[{ key: 'temp', name: 'bearing °C', color: '#fbbf24' }]} height={130} xFormatter={() => ''} />
          {sel?.alert && <p className="mt-1 text-[12px] text-bad">Drift detected: signature <b>{sel.signature?.name}</b>, RUL {sel.rul_min != null ? fmt.dur(sel.rul_min) : '?'}.</p>}
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Work orders" pad={false} right={
          <div className="flex items-center gap-2">
            <Select aria-label="Work-order asset" className="w-28" value={asset} onChange={(e) => setAsset(e.target.value)}>{rows.map((r) => <option key={r.asset}>{r.asset}</option>)}</Select>
            <Input aria-label="Start in minutes" type="number" className="w-20" value={startIn} onChange={(e) => setStartIn(Number(e.target.value))} />
            <Button size="sm" tone="primary" disabled={create.busy} onClick={async () => { await create.run(() => calls.post('/api/maintenance/work-orders', { asset, start_in_min: startIn, reason: 'manual work order from UI' })); void wos.reload() }}>Create</Button>
          </div>}>
          {create.error && <p role="alert" className="px-4 pt-2 text-xs text-bad">{create.error}</p>}
          {!wos.data?.length ? <div className="p-4"><Empty>No work orders yet. Inject a bearing fault on the Control Tower, or create one here (it goes through the policy engine).</Empty></div> : (
            <Table head={['WO', 'Asset', 'Start', 'Duration', 'Reason', 'Status']}>
              {wos.data.slice(0, 12).map((w) => (
                <tr key={w.id}><Td className="font-mono text-[11px]">{w.id}</Td><Td>{w.asset}</Td><Td className="tabnum">{w.start_in_min >= 0 ? `in ${fmt.dur(w.start_in_min)}` : `${fmt.dur(-w.start_in_min)} ago`}</Td><Td className="tabnum">{w.duration} min</Td><Td className="max-w-[240px] truncate text-[12px] text-mute">{w.reason}{w.spare ? ` · ${w.spare}` : ''}</Td><Td><Badge tone={woTone(w.status)}>{w.status}</Badge></Td></tr>
              ))}
            </Table>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Failure-signature library" pad={false}>
            <Table head={['Signature', 'Source', 'Description']}>
              {(sigs.data ?? []).map((s) => <tr key={s.name}><Td className="font-medium">{s.name}</Td><Td><Mono>{s.source}</Mono></Td><Td className="text-[12px] text-mute">{s.description}</Td></tr>)}
            </Table>
          </Card>
          <Card title="Spares">
            <div className="grid grid-cols-3 gap-3 text-sm">
              {(health.data?.spares ?? []).map((s) => <div key={s.part} className="rounded-lg border border-line bg-panel2/50 p-2"><div className="font-mono text-[11px] text-mute">{s.part}</div><div className="tabnum text-lg font-semibold">{s.on_hand}</div><div className="text-[10px] text-mute">min {s.min} · lead {s.lead_h} h</div></div>)}
            </div>
          </Card>
        </div>
      </div>
    </Page>
  )
}
