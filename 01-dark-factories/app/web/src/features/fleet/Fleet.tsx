import { useState } from 'react'
import { Bars } from '../../components/charts'
import { Field, Input, Mono, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePlant } from '../../plant'
import { useNavigate } from 'react-router-dom'
import { post, useApi } from '../../lib/api'

type P = { id: string; name: string; location: string; profile: string; assets: number; sim_time: string; oee: number; otif: number; throughput_uph: number; downtime_min: number; kwh_per_unit: number; co2_per_unit_kg: number; scrap_pct: number; pending_approvals: number; kill_switch: boolean; rank?: Record<string, number> }
type Cmp = { plants: P[]; median: Record<string, number>; notes: string[] }
type PB = { id: string; from_plant: string; asset: string; signature: { name: string; description: string; source: string }; adopted_by: string[] }

export default function Fleet() {
  const { setPlantId } = usePlant()
  const nav = useNavigate()
  const cmp = useApi<Cmp>('/api/fleet/compare', { interval: 4000 })
  const plants = useApi<{ plants: P[]; totals: { plants: number; assets: number; pending_approvals: number; mean_oee: number } }>('/api/fleet/plants', { interval: 4000 })
  const pbs = useApi<{ playbooks: PB[]; libraries: Record<string, { name: string; source: string }[]> }>('/api/fleet/playbooks', { interval: 5000 })
  const [src, setSrc] = useState('KAT-1')
  const [asset, setAsset] = useState('CNC-04')
  const learn = useAction()
  const adopt = useAction()
  const rows = cmp.data?.plants ?? plants.data?.plants ?? []
  const t = plants.data?.totals
  return (
    <Page title="Fleet" subtitle="Three simulated plants run side by side as independent in-process twins (different layouts, tariffs and fault rates). Compare them on the same KPIs, and share what one plant learns - a failure signature - with the others as a playbook.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Plants" value={t?.plants ?? rows.length} sub={`${t?.assets ?? ''} assets`} />
        <Stat label="Fleet mean OEE" value={fmt.pct(t?.mean_oee, 1)} />
        <Stat label="Approvals pending" value={t?.pending_approvals ?? 0} tone={t?.pending_approvals ? 'warn' : 'ok'} />
        <Stat label="Playbooks shared" value={pbs.data?.playbooks.length ?? 0} />
      </div>
      <Card title="Plant comparison" pad={false}>
        <Table head={['Plant', 'Profile', 'OEE', 'OTIF', 'Throughput', 'Downtime', 'kWh/unit', 'CO₂/unit', 'Scrap', 'Pending', '']}>
          {rows.map((p) => (
            <tr key={p.id}>
              <Td className="font-medium">{p.id} <span className="text-[11px] text-mute">{p.name}</span><div className="text-[10px] text-mute">{p.location}</div></Td><Td className="max-w-[180px] text-[12px] text-mute">{p.profile}</Td>
              <Td className="tabnum">{fmt.pct(p.oee, 1)} {p.rank && <Badge tone={p.rank.oee === 1 ? 'ok' : 'mute'}>#{p.rank.oee}</Badge>}</Td>
              <Td className="tabnum">{fmt.pct(p.otif, 0)}</Td><Td className="tabnum">{fmt.n(p.throughput_uph, 1)} u/h</Td><Td className="tabnum">{fmt.n(p.downtime_min)} min</Td>
              <Td className="tabnum">{fmt.n(p.kwh_per_unit, 2)}</Td><Td className="tabnum">{fmt.n(p.co2_per_unit_kg, 2)}</Td><Td className="tabnum">{fmt.pct(p.scrap_pct, 2)}</Td>
              <Td><Badge tone={p.pending_approvals ? 'warn' : 'mute'}>{p.pending_approvals}</Badge>{p.kill_switch && <Badge tone="bad" className="ml-1">kill</Badge>}</Td>
              <Td><Button size="sm" tone="ghost" onClick={() => { setPlantId(p.id); nav('/') }}>Open →</Button></Td>
            </tr>
          ))}
        </Table>
        {(cmp.data?.notes ?? []).map((n, i) => <p key={i} className="border-t border-line px-4 py-2 text-[12px] text-mute">{n}</p>)}
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="OEE by plant (vs fleet median)">
          <Bars data={rows.map((p) => ({ plant: p.id, oee: Math.round(p.oee * 1000) / 10, median: Math.round((cmp.data?.median.oee ?? 0) * 1000) / 10 }))} x="plant" bars={[{ key: 'oee', name: 'OEE %', color: '#38bdf8' }, { key: 'median', name: 'fleet median %', color: '#8499ae' }]} height={220} />
        </Card>
        <Card title="Share a learned failure signature">
          <p className="mb-2 text-[12px] text-mute">Turns the current anomaly residual of an asset into a reusable signature, adds it to that plant's library and publishes it as a playbook. Requires an asset that is currently drifting (inject a bearing fault first).</p>
          <div className="grid grid-cols-3 items-end gap-2">
            <Field label="Plant"><Select value={src} onChange={(e) => setSrc(e.target.value)} aria-label="Source plant">{rows.map((p) => <option key={p.id}>{p.id}</option>)}</Select></Field>
            <Field label="Asset"><Input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} aria-label="Source asset" /></Field>
            <Button tone="primary" size="sm" disabled={learn.busy} onClick={async () => { await learn.run(() => post('/api/fleet/playbooks/learn', { plant: src, asset, note: '' })); void pbs.reload() }}>Learn & publish</Button>
          </div>
          {learn.error && <p role="alert" className="mt-2 text-xs text-bad">{learn.error}</p>}
        </Card>
      </div>
      <Card title="Playbook library" pad={false}>
        {!pbs.data?.playbooks.length ? <div className="p-4"><Empty>No playbooks published yet.</Empty></div> : (
          <Table head={['Playbook', 'From', 'Signature', 'Adopted by', 'Adopt in']}>
            {pbs.data.playbooks.map((pb) => (
              <tr key={pb.id}><Td className="font-mono text-[12px]">{pb.id}</Td><Td>{pb.from_plant} · {pb.asset}</Td><Td><div className="font-medium">{pb.signature.name}</div><div className="text-[11px] text-mute">{pb.signature.description}</div></Td><Td>{pb.adopted_by.length ? pb.adopted_by.map((x) => <Badge key={x} tone="ok" className="mr-1">{x}</Badge>) : <span className="text-mute">-</span>}</Td>
                <Td><div className="flex gap-1">{rows.filter((p) => p.id !== pb.from_plant && !pb.adopted_by.includes(p.id)).map((p) => <Button key={p.id} size="sm" tone="ghost" disabled={adopt.busy} onClick={async () => { await adopt.run(() => post(`/api/fleet/playbooks/${pb.id}/adopt`, { plant: p.id })); void pbs.reload() }}>{p.id}</Button>)}</div></Td></tr>
            ))}
          </Table>
        )}
        {adopt.error && <p role="alert" className="px-4 pb-2 text-xs text-bad">{adopt.error}</p>}
      </Card>
      <Card title="Signature libraries per plant">
        <div className="grid gap-4 md:grid-cols-3">{Object.entries(pbs.data?.libraries ?? {}).map(([pid, lib]) => <div key={pid}><div className="mb-1 text-sm font-medium">{pid} <span className="text-[11px] text-mute">({lib.length})</span></div><div className="flex flex-wrap gap-1">{lib.map((s) => <Mono key={s.name}>{s.name}</Mono>)}</div></div>)}</div>
      </Card>
    </Page>
  )
}
