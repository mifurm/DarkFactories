import { useMemo, useState } from 'react'
import { Lines } from '../../components/charts'
import { Json, Mono, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page, Table, Td } from '../../components/ui'
import { usePApi, usePlantCalls } from '../../plant'

type Leaf = { value: number | string; unit: string; source: string }
type Tree = { [k: string]: Tree | Leaf }
const isLeaf = (n: Tree | Leaf): n is Leaf => 'value' in n && 'source' in n && typeof (n as Leaf).source === 'string'

function Node({ name, node, path, depth, onPick, open }: { name: string; node: Tree | Leaf; path: string; depth: number; onPick: (topic: string) => void; open: boolean }) {
  const [o, setO] = useState(open || depth < 3)
  if (isLeaf(node)) {
    return (
      <button onClick={() => onPick(path)} className="flex w-full items-center justify-between gap-3 rounded px-1.5 py-0.5 text-left text-[12px] hover:bg-white/5" style={{ paddingLeft: depth * 12 }}>
        <span className="truncate text-ink/90">{name}</span>
        <span className="tabnum text-mute">{typeof node.value === 'number' ? node.value.toFixed(2) : node.value} {node.unit}</span>
      </button>
    )
  }
  return (
    <div>
      <button onClick={() => setO(!o)} className="flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] font-medium hover:bg-white/5" style={{ paddingLeft: depth * 12 }}>
        <span className="w-3 text-mute">{o ? '▾' : '▸'}</span>{name}
      </button>
      {o && Object.entries(node).map(([k, v]) => <Node key={k} name={k} node={v} path={path ? `${path}/${k}` : k} depth={depth + 1} onPick={onPick} open={false} />)}
    </div>
  )
}

type Msg = { topic: string; ts: number; value: number | string; unit: string; quality: string; source: string }

export default function Telemetry() {
  const calls = usePlantCalls()
  const tree = usePApi<{ plant: string; topics: number; tree: Tree }>('/api/telemetry/tree', { interval: 8000 })
  const adapters = usePApi<{ adapters: { name: string; status: string; description: string; topics?: number; accepted?: number; rejected?: number }[]; isa95: string; example_topic: string }>('/api/telemetry/adapters', { interval: 8000 })
  const latest = usePApi<Msg[]>('/api/telemetry/latest?limit=12', { interval: 3000 })
  const [topic, setTopic] = useState<string>('')
  const effective = topic || adapters.data?.example_topic || ''
  const series = usePApi<{ topic: string; points: { t: number; value: number | null }[] }>(effective ? `/api/telemetry/series?topic=${encodeURIComponent(effective)}&n=240` : null, { interval: 4000 })
  const act = useAction<{ accepted: number; rejected: number; errors: string[] }>()
  const [val, setVal] = useState('42.5')
  const data = useMemo(() => (series.data?.points ?? []).map((p) => ({ x: p.t, v: p.value })), [series.data])
  const ingest = () =>
    act.run(() => calls.post('/api/telemetry/ingest', { messages: [{ topic: `${(adapters.data?.example_topic ?? '').split('/').slice(0, 6).join('/')}/ext_probe`, value: Number(val), unit: 'C', quality: 'good' }] }))
  return (
    <Page title="Telemetry & Unified Namespace" subtitle={`ISA-95 topic model ${adapters.data?.isa95 ?? ''} - the simulator publishes validated messages; HTTP ingest accepts external ones; MQTT / Event Hubs decoders are implemented but no broker is connected in this deployment.`}>
      <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card title={`UNS tree · ${tree.data?.topics ?? '…'} topics`} pad={false}>
          <div className="max-h-[560px] overflow-auto p-2">
            {tree.data ? Object.entries(tree.data.tree).map(([k, v]) => <Node key={k} name={k} node={v} path={k} depth={0} onPick={setTopic} open />) : <Empty>Loading…</Empty>}
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Time series" right={<Mono>{effective.split('/').slice(-2).join('/')}</Mono>}>
            <Lines data={data} lines={[{ key: 'v', name: 'value', color: '#38bdf8' }]} height={230} />
            <p className="mt-1 break-all text-[11px] text-mute">{effective}</p>
          </Card>
          <Card title="Live messages (latest values)" pad={false}>
            <Table head={['Topic', 'Value', 'Unit', 'Quality', 'Source']}>
              {(latest.data ?? []).map((m) => (
                <tr key={m.topic}><Td className="max-w-[420px] truncate font-mono text-[11px]">{m.topic.split('/').slice(-3).join('/')}</Td><Td className="tabnum">{typeof m.value === 'number' ? m.value.toFixed(2) : m.value}</Td><Td>{m.unit}</Td><Td><Badge tone={m.quality === 'good' ? 'ok' : 'warn'}>{m.quality}</Badge></Td><Td className="text-mute">{m.source}</Td></tr>
              ))}
            </Table>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Adapters">
              <ul className="space-y-2 text-sm">
                {(adapters.data?.adapters ?? []).map((a) => (
                  <li key={a.name}>
                    <div className="flex items-center gap-2"><b>{a.name}</b><Badge tone={a.status === 'active' ? 'ok' : 'mute'}>{a.status}</Badge>{a.topics !== undefined && <span className="text-[11px] text-mute">{a.topics} topics</span>}{a.accepted !== undefined && <span className="text-[11px] text-mute">{a.accepted} accepted / {a.rejected} rejected</span>}</div>
                    <div className="text-[12px] text-mute">{a.description}</div>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="HTTP ingest test">
              <div className="flex gap-2">
                <input aria-label="Probe value" value={val} onChange={(e) => setVal(e.target.value)} className="w-28 rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm" />
                <Button size="sm" tone="primary" disabled={act.busy} onClick={ingest}>Send external reading</Button>
              </div>
              <p className="mt-2 text-[11px] text-mute">Messages are validated (topic depth, ISA-95 prefix, finite numeric value, size and rate limits) before they enter the store.</p>
              {act.error && <p role="alert" className="mt-1 text-xs text-bad">{act.error}</p>}
              {act.result && <div className="mt-2"><Json data={act.result} max={120} /></div>}
            </Card>
          </div>
        </div>
      </div>
    </Page>
  )
}
