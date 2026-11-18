import { Json, Mono, useAction } from '../../components/bits'
import { Badge, Button, Card, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { usePApi, usePlantCalls } from '../../plant'

type Sum = { enabled: boolean; recipe: Record<string, number>; bounds: Record<string, number[]>; steps: Record<string, number>; history: { t: number; event: string; recipe?: Record<string, number>; delta?: Record<string, number> }[]; trial: unknown; pilot: unknown }

export default function Process() {
  const calls = usePlantCalls()
  const sum = usePApi<Sum>('/api/process/summary', { interval: 4000 })
  const en = useAction()
  const opt = useAction<{ plans: unknown[]; history: unknown[] }>()
  const s = sum.data
  return (
    <Page title="Process optimisation (pilot)" subtitle="P2 pilot: the agent tunes injection-moulding recipes (injection speed, melt temperature, cool time) by evaluating each trial on a twin fork first, staying inside hard bounds and moving one small step at a time. Disabled by default; recipe changes need approval under the default policy." right={
      <div className="flex items-center gap-2">
        <Badge tone={s?.enabled ? 'ok' : 'mute'}>{s?.enabled ? 'agent enabled' : 'agent disabled'}</Badge>
        <Button size="sm" disabled={en.busy} onClick={async () => { await en.run(() => calls.post('/api/process/enable', { enabled: !s?.enabled })); void sum.reload() }}>{s?.enabled ? 'Disable agent' : 'Enable agent'}</Button>
        <Button size="sm" tone="primary" disabled={opt.busy} onClick={async () => { await opt.run(() => calls.post('/api/process/optimize', {})); void sum.reload() }}>{opt.busy ? 'Evaluating on twin…' : 'Run one optimisation step'}</Button>
      </div>}>
      {(en.error || opt.error) && <p role="alert" className="text-xs text-bad">{en.error ?? opt.error}</p>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Object.entries(s?.recipe ?? {}).map(([k, v]) => <Stat key={k} label={k.replace(/_/g, ' ')} value={v} sub={`bounds ${s?.bounds[k]?.join(' … ')} · step ${s?.steps[k]}`} />)}
        <Stat label="Trials run" value={(s?.history ?? []).length} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Optimisation history" pad={false}>
          <Table head={['t', 'Event', 'Recipe / change']}>
            {(s?.history ?? []).slice().reverse().slice(0, 12).map((h, i) => <tr key={i}><Td className="tabnum text-mute">{h.t}</Td><Td><Badge tone={h.event === 'converged' ? 'ok' : 'info'}>{h.event}</Badge></Td><Td className="text-[12px]"><Mono>{JSON.stringify(h.recipe ?? h.delta ?? {})}</Mono></Td></tr>)}
          </Table>
          {!(s?.history ?? []).length && <p className="p-4 text-sm text-mute">No trials yet.</p>}
        </Card>
        <Card title="How it stays safe">
          <Kv k="Search space" v="3 recipe parameters, bounded" />
          <Kv k="Step size" v="one small step per cycle" />
          <Kv k="Evaluation" v="twin fork before any live change" />
          <Kv k="Policy" v="process.recipe: approval required at L2-L3, supervised above" />
          <Kv k="Forbidden range" v="melt temperature outside 180-265 °C rejected in code" />
          {opt.result && <div className="mt-3"><Json data={opt.result} max={180} /></div>}
        </Card>
      </div>
    </Page>
  )
}
