import { useState } from 'react'
import { Field, Input, Json, Mono, Select, outcomeTone, simTime, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { usePApi, usePlant, usePlantCalls, withPlant } from '../../plant'

type Entry = { seq: number; ts: string; sim_t: number; sim_time: string; plant: string; kind: string; agent: string; asset: string; assets: string[]; decision_class: string; outcome: string; summary: string; rationale: string; counterfactual: Record<string, unknown>; payload: Record<string, unknown>; corr: string; prev_hash?: string; hash?: string }
type Verify = { ok: boolean; length: number; broken_at: number | null; reason: string; head: string; anchor: string; first_seq: number }

export default function Ledger() {
  const calls = usePlantCalls()
  const { plantId } = usePlant()
  const [f, setF] = useState({ kind: '', agent: '', asset: '', q: '' })
  const qs = Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
  const list = usePApi<{ total: number; items: Entry[] }>(`/api/ledger?limit=60${qs ? '&' + qs : ''}`, { interval: 4000 })
  const verify = usePApi<Verify>('/api/ledger/verify', { interval: 8000 })
  const stats = usePApi<{ entries: number; by_kind: Record<string, number> }>('/api/ledger/stats', { interval: 8000 })
  const [sel, setSel] = useState<Entry | null>(null)
  const explain = useAction<{ explanation?: string; text?: string; source?: string }>()
  const v = verify.data
  return (
    <Page title="Decision ledger" subtitle="Every observation-driven proposal, policy decision, action, veto and outcome is appended to a SHA-256 hash chain (each entry commits to the previous one) and persisted to Cosmos DB. Editing or deleting any entry breaks verification." right={
      <a href={withPlant(`/api/ledger/export?${qs}`, plantId)} download className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-sm hover:border-accent">Export JSONL</a>}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Chain integrity" value={v ? (v.ok ? 'VALID' : 'BROKEN') : '…'} tone={v?.ok ? 'ok' : v ? 'bad' : 'mute'} sub={v ? `${v.length} entries verified` : ''} />
        <Stat label="Head hash" value={<span className="font-mono text-base">{v?.head.slice(0, 12) ?? '…'}</span>} sub={v?.reason} />
        <Stat label="Entries" value={stats.data?.entries ?? 0} />
        <Stat label="By kind" value={<span className="text-[12px] font-normal">{Object.entries(stats.data?.by_kind ?? {}).map(([k, n]) => `${k} ${n}`).join(' · ')}</span>} />
      </div>
      <Card title="Filters" right={<Button size="sm" tone="ghost" onClick={() => setF({ kind: '', agent: '', asset: '', q: '' })}>Clear</Button>}>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Field label="Kind"><Select aria-label="Kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="">any</option>{['proposal', 'decision', 'action', 'veto', 'whatif', 'outcome', 'narration', 'override', 'system', 'arbitration'].map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label="Agent"><Input aria-label="Agent" value={f.agent} onChange={(e) => setF({ ...f, agent: e.target.value })} placeholder="maintenance" /></Field>
          <Field label="Asset"><Input aria-label="Asset" value={f.asset} onChange={(e) => setF({ ...f, asset: e.target.value.toUpperCase() })} placeholder="CNC-04" /></Field>
          <Field label="Text search"><Input aria-label="Search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="bearing" /></Field>
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
        <Card title={`Entries (${list.data?.total ?? 0})`} pad={false}>
          <div className="max-h-[620px] overflow-auto">
            <Table head={['#', 'Sim time', 'Kind', 'Agent', 'Asset', 'Summary', 'Outcome']}>
              {(list.data?.items ?? []).map((e) => (
                <tr key={e.seq} onClick={() => { setSel(e); explain.setResult(null) }} className={`cursor-pointer hover:bg-white/5 ${sel?.seq === e.seq ? 'bg-accent/10' : ''}`}>
                  <Td className="tabnum text-mute">{e.seq}</Td><Td className="tabnum text-mute">{simTime(e.sim_time)}</Td><Td><Badge tone="violet">{e.kind}</Badge></Td><Td className="text-[12px]">{e.agent}</Td><Td className="text-[12px]">{e.asset}</Td>
                  <Td className="max-w-[420px] truncate text-[12px]" >{e.summary}</Td><Td><Badge tone={outcomeTone(e.outcome)}>{e.outcome || '-'}</Badge></Td>
                </tr>
              ))}
            </Table>
            {!list.data?.items.length && <div className="p-4"><Empty>No entries match.</Empty></div>}
          </div>
        </Card>
        <Card title={sel ? `Entry #${sel.seq}` : 'Entry detail'} right={sel && <Badge tone={outcomeTone(sel.outcome)}>{sel.outcome}</Badge>}>
          {!sel ? <Empty>Select an entry to see its rationale, counterfactual and hash links.</Empty> : (
            <div className="space-y-2 text-[13px]">
              <p>{sel.summary}</p>
              {sel.rationale && <p className="text-mute">{sel.rationale}</p>}
              <Kv k="Decision class" v={<Mono>{sel.decision_class || '-'}</Mono>} /><Kv k="Correlation (plan)" v={<Mono>{sel.corr || '-'}</Mono>} /><Kv k="Assets" v={sel.assets.join(', ') || '-'} />
              <Kv k="Hash" v={<span className="font-mono text-[11px]">{sel.hash?.slice(0, 20)}…</span>} /><Kv k="Previous hash" v={<span className="font-mono text-[11px]">{sel.prev_hash?.slice(0, 20)}…</span>} />
              {Object.keys(sel.counterfactual ?? {}).length > 0 && <div><div className="text-[11px] uppercase tracking-wider text-mute">Counterfactual</div><Json data={sel.counterfactual} max={120} /></div>}
              <details><summary className="cursor-pointer text-[12px] text-mute">Payload</summary><Json data={sel.payload} max={180} /></details>
              <Button size="sm" disabled={explain.busy} onClick={() => explain.run(() => calls.post('/api/ledger/explain', { seq: sel.seq }))}>{explain.busy ? 'Explaining…' : 'Explain this decision'}</Button>
              {explain.error && <p role="alert" className="text-xs text-bad">{explain.error}</p>}
              {explain.result && <p className="rounded-lg bg-black/20 p-2 text-[13px]">{explain.result.explanation ?? explain.result.text}{explain.result.source && <Badge tone="info" className="ml-2">{explain.result.source}</Badge>}</p>}
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
