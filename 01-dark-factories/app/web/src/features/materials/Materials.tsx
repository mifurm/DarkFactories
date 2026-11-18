import { Meter } from '../../components/bits'
import { Badge, Card, Empty, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi } from '../../plant'

type Inv = { material: string; unit: string; on_hand: number; min: number; max: number; lead_h: number; on_order: { eta_min: number; qty: number; source: string }[]; risk: { cover_min: number; next_eta_min: number | null; gap_min: number; rate_per_h: number; committed: number; shortfall: number; at_risk: boolean } }
type Sum = { inventory: Inv[]; spares: { part: string; on_hand: number; min: number; lead_h: number; price_eur: number }[]; amr: { id: string; state: string; battery: number }[]; cells: { id: string; kit_min: number }[]; amr_queue: number }
type Req = { amr_requests: { id?: string; cell?: string; asset?: string; score?: number; state?: string }[]; priority: Record<string, number> }

export default function Materials() {
  const sum = usePApi<Sum>('/api/materials/summary', { interval: 3000 })
  const req = usePApi<Req>('/api/materials/requests', { interval: 3000 })
  const s = sum.data
  const risky = (s?.inventory ?? []).filter((i) => i.risk.at_risk).length
  return (
    <Page title="Materials & logistics" subtitle="ERP min/max reordering is the baseline; the Materials agent adds committed-demand (MRP-style) checks against the schedule, expedites or switches source when cover is short, and prioritises AMR kit delivery to the cells that need it.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Materials at risk" value={risky} tone={risky ? 'warn' : 'ok'} />
        <Stat label="Open supply orders" value={(s?.inventory ?? []).reduce((a, i) => a + i.on_order.length, 0)} />
        <Stat label="AMRs running" value={`${(s?.amr ?? []).filter((a) => a.state === 'RUN').length}/${(s?.amr ?? []).length}`} />
        <Stat label="AMR queue" value={s?.amr_queue ?? 0} />
      </div>
      <Card title="Inventory & cover" pad={false}>
        <Table head={['Material', 'On hand', 'Min / max', 'Cover', 'Next delivery', 'Committed demand', 'On order', 'Status']}>
          {(s?.inventory ?? []).map((i) => (
            <tr key={i.material}>
              <Td className="font-medium">{i.material}</Td>
              <Td className="w-44"><div className="flex items-center gap-2"><span className="tabnum w-16 text-[12px]">{fmt.n(i.on_hand)} {i.unit}</span><Meter value={i.on_hand} max={i.max} tone={i.on_hand < i.min ? 'bad' : 'ok'} /></div></Td>
              <Td className="tabnum text-mute">{fmt.n(i.min)} / {fmt.n(i.max)}</Td>
              <Td className="tabnum">{fmt.dur(i.risk.cover_min)}</Td>
              <Td className="tabnum">{i.risk.next_eta_min != null ? fmt.dur(i.risk.next_eta_min) : '-'}</Td>
              <Td className="tabnum">{fmt.n(i.risk.committed)} {i.unit}</Td>
              <Td className="text-[12px]">{i.on_order.map((o, k) => <div key={k}>{fmt.n(o.qty)} · {o.source.replace('_', ' ')} · {fmt.dur(o.eta_min)}</div>)}</Td>
              <Td><Badge tone={i.risk.at_risk ? 'bad' : 'ok'}>{i.risk.at_risk ? `short ${fmt.n(i.risk.shortfall)} ${i.unit}` : 'covered'}</Badge></Td>
            </tr>
          ))}
        </Table>
      </Card>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="AMR fleet & kit feeding" pad={false}>
          <Table head={['AMR', 'State', 'Battery']}>{(s?.amr ?? []).map((a) => <tr key={a.id}><Td className="font-medium">{a.id}</Td><Td><Badge tone={a.state === 'RUN' ? 'ok' : 'mute'}>{a.state}</Badge></Td><Td className="w-40"><Meter value={a.battery} max={100} tone={a.battery < 30 ? 'warn' : 'ok'} /></Td></tr>)}</Table>
          <div className="border-t border-line p-3 text-[12px] text-mute">AMR dispatch priority set by the agent: {Object.keys(req.data?.priority ?? {}).length ? Object.entries(req.data?.priority ?? {}).map(([k, v]) => `${k} (${v.toFixed(1)})`).join(', ') : 'default order'}</div>
        </Card>
        <Card title="Kit stock per cell (minutes of work)" pad={false}>
          <div className="max-h-[260px] overflow-auto"><Table head={['Cell', 'Kit cover']}>{(s?.cells ?? []).map((c) => <tr key={c.id}><Td>{c.id}</Td><Td className="w-48"><div className="flex items-center gap-2"><span className="tabnum w-14 text-[12px]">{fmt.dur(c.kit_min)}</span><Meter value={c.kit_min} max={120} tone={c.kit_min < 25 ? 'bad' : c.kit_min < 50 ? 'warn' : 'ok'} /></div></Td></tr>)}</Table></div>
        </Card>
        <Card title="Spare parts" pad={false}>
          {!s?.spares.length ? <div className="p-4"><Empty>No spares tracked.</Empty></div> : <Table head={['Part', 'On hand', 'Min', 'Lead', 'Price']}>{s.spares.map((p) => <tr key={p.part}><Td className="font-mono text-[11px]">{p.part}</Td><Td className="tabnum">{p.on_hand}</Td><Td className="tabnum text-mute">{p.min}</Td><Td className="tabnum text-mute">{p.lead_h} h</Td><Td className="tabnum">{fmt.eur(p.price_eur)}</Td></tr>)}</Table>}
        </Card>
      </div>
    </Page>
  )
}
