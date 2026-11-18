import { useState } from 'react'
import { Input, Json, Meter, Mono, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Agent = { name: string; role: string; enabled: boolean; decision_classes: string[]; stats: Record<string, number>; p50_ms: number; p95_ms: number }
type Proposal = { agent: string; title: string; rationale: string; impact: Record<string, number>; risk: number; cost_eur: number; utility?: number; kind?: string }
type Plan = { id: string; trigger: string; status: string; utility: number; decision_class: string; assets: string[]; cost_eur: number; risk: number; proposals: Proposal[]; whatif: { explanation?: string; delta?: Record<string, number> } | null; decision: { policy?: Record<string, unknown> }; notes: string[] }
type Swarm = { cycles: number; stats: Record<string, number>; weights: Record<string, number>; sim_first: string; agents: Agent[]; pending: number }

const planTone = (s: string) => (/execut|applied/.test(s) ? 'ok' : /veto|reject|denied|sim_rejected|expired/.test(s) ? 'bad' : /approval|pending|inbox/.test(s) ? 'warn' : 'mute') as 'ok' | 'bad' | 'warn' | 'mute'

export default function Swarm() {
  const calls = usePlantCalls()
  const sw = usePApi<Swarm>('/api/swarm/agents', { interval: 3000 })
  const plans = usePApi<Plan[]>('/api/swarm/plans', { interval: 3000 })
  const w = usePApi<{ weights: Record<string, number>; meaning: string }>('/api/swarm/weights')
  const [sel, setSel] = useState<string | null>(null)
  const [draft, setDraft] = useState<Record<string, number> | null>(null)
  const toggle = useAction()
  const save = useAction()
  const explain = useAction<{ explanation?: string; text?: string; source?: string }>()
  const plan = plans.data?.find((p) => p.id === sel) ?? plans.data?.[0]
  const weights = draft ?? w.data?.weights ?? {}
  const s = sw.data?.stats ?? {}
  return (
    <Page title="Agent swarm" subtitle="Seven specialist agents (deterministic algorithms first, LLM for narration) share a blackboard; the supervisor arbitrates objective conflicts, vetoes unsafe plans, runs the twin before acting and hands the result to the policy engine.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {[['Cycles', sw.data?.cycles], ['Proposals', s.proposals], ['Auto-executed', s.auto], ['To humans', s.approvals], ['Vetoed', s.vetoed], ['Sim-rejected', s.sim_rejected]].map(([l, v]) => (
          <div key={String(l)} className="rounded-lg border border-line bg-panel px-3 py-2"><div className="text-[10px] uppercase tracking-wider text-mute">{l}</div><div className="tabnum text-xl font-semibold">{fmt.n(v as number)}</div></div>
        ))}
      </div>
      <Card title="Agents" pad={false} right={<Badge tone="info">sim-first: {sw.data?.sim_first ?? '…'}</Badge>}>
        <Table head={['Agent', 'Role', 'Decision classes', 'Proposals', 'Executed', 'Vetoed', 'p50 / p95 ms', 'Enabled']}>
          {(sw.data?.agents ?? []).map((a) => (
            <tr key={a.name}>
              <Td className="font-medium capitalize">{a.name}</Td>
              <Td className="max-w-[260px] text-[12px] text-mute">{a.role}</Td>
              <Td><div className="flex flex-wrap gap-1">{a.decision_classes.map((c) => <Mono key={c}>{c}</Mono>)}</div></Td>
              <Td className="tabnum">{a.stats.proposals ?? 0}</Td><Td className="tabnum">{a.stats.executed ?? 0}</Td><Td className="tabnum">{a.stats.vetoed ?? 0}</Td>
              <Td className="tabnum text-mute">{a.p50_ms.toFixed(1)} / {a.p95_ms.toFixed(1)}</Td>
              <Td><button role="switch" aria-checked={a.enabled} aria-label={`Toggle ${a.name} agent`} disabled={toggle.busy} onClick={async () => { await toggle.run(() => calls.post(`/api/swarm/agents/${a.name}/toggle`, { enabled: !a.enabled })); void sw.reload() }} className={`h-5 w-9 rounded-full p-0.5 transition ${a.enabled ? 'bg-ok/70' : 'bg-white/15'}`}><span className={`block h-4 w-4 rounded-full bg-white transition ${a.enabled ? 'translate-x-4' : ''}`} /></button></Td>
            </tr>
          ))}
        </Table>
        {toggle.error && <p role="alert" className="p-3 text-xs text-bad">{toggle.error}</p>}
      </Card>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
        <Card title={`Plans & negotiations (${plans.data?.length ?? 0})`} pad={false}>
          {!plans.data?.length ? <div className="p-4"><Empty>No plans yet - the agents propose as soon as there is something to improve.</Empty></div> : (
            <div className="max-h-[560px] overflow-auto">
              <Table head={['Plan', 'Status', 'Class', 'Assets', 'Agents', 'Utility €', 'Risk']}>
                {plans.data.map((p) => (
                  <tr key={p.id} onClick={() => setSel(p.id)} className={`cursor-pointer hover:bg-white/5 ${plan?.id === p.id ? 'bg-accent/10' : ''}`}>
                    <Td className="font-mono text-[11px]">{p.id}</Td><Td><Badge tone={planTone(p.status)}>{p.status}</Badge></Td><Td><Mono>{p.decision_class}</Mono></Td>
                    <Td className="text-[12px]">{p.assets.join(', ')}</Td><Td className="text-[12px] capitalize">{[...new Set(p.proposals.map((x) => x.agent))].join(', ')}</Td>
                    <Td className="tabnum">{fmt.n(p.utility)}</Td><Td className="tabnum">{p.risk.toFixed(2)}</Td>
                  </tr>
                ))}
              </Table>
            </div>
          )}
        </Card>
        <div className="space-y-4">
          {plan && (
            <Card title={`Plan ${plan.id}`} right={<Badge tone={planTone(plan.status)}>{plan.status}</Badge>}>
              <div className="space-y-2">
                {plan.proposals.map((p, i) => (
                  <div key={i} className="rounded-lg border border-line bg-panel2/50 p-2 text-[12px]">
                    <div className="flex items-center justify-between"><Badge tone="violet">{p.agent}</Badge><span className="tabnum text-mute">risk {p.risk.toFixed(2)} · €{fmt.n(p.cost_eur)} · utility €{fmt.n(p.utility)}</span></div>
                    <div className="mt-1 font-medium">{p.title}</div><div className="text-mute">{p.rationale}</div>
                  </div>
                ))}
              </div>
              {plan.whatif?.explanation && <p className="mt-2 text-[12px]"><span className="text-mute">Twin check: </span>{plan.whatif.explanation}</p>}
              {plan.notes.length > 0 && <ul className="mt-2 list-disc pl-5 text-[12px] text-warn">{plan.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
              <details className="mt-2 text-[12px]"><summary className="cursor-pointer text-mute">Policy decision</summary><Json data={plan.decision} max={180} /></details>
              <div className="mt-3 flex items-center gap-2">
                <Button size="sm" disabled={explain.busy} onClick={() => explain.run(() => calls.post('/api/swarm/explain', { plan_id: plan.id }))}>{explain.busy ? 'Explaining…' : 'Explain this plan'}</Button>
                {explain.error && <span role="alert" className="text-xs text-bad">{explain.error}</span>}
              </div>
              {explain.result && <p className="mt-2 text-[13px]">{explain.result.explanation ?? explain.result.text}{explain.result.source && <Badge tone="info" className="ml-2">{explain.result.source}</Badge>}</p>}
            </Card>
          )}
          <Card title="Objective weights (EUR-equivalents)">
            <p className="mb-2 text-[12px] text-mute">{w.data?.meaning}</p>
            <div className="space-y-1.5">
              {Object.entries(weights).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-sm"><span className="w-32 text-mute">{k.replace('_eur', '').replace('_', ' ')}</span><Input aria-label={k} type="number" step="0.1" className="w-24" value={v} onChange={(e) => setDraft({ ...weights, [k]: Number(e.target.value) })} /><Meter value={v} max={3} /></div>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2"><Button size="sm" tone="primary" disabled={!draft || save.busy} onClick={async () => { await save.run(() => calls.put('/api/swarm/weights', { weights })); setDraft(null); void w.reload() }}>Apply weights</Button>{save.error && <span role="alert" className="text-xs text-bad">{save.error}</span>}</div>
          </Card>
          <Card title="Supervisor outcome counters"><Kv k="Executed" v={s.executed ?? 0} /><Kv k="Denied by policy" v={s.denied ?? 0} /><Kv k="Arbitrated conflicts" v={s.arbitrated ?? 0} /><Kv k="Expired approvals" v={s.expired ?? 0} /><Kv k="Pending in flight" v={sw.data?.pending ?? 0} /></Card>
        </div>
      </div>
    </Page>
  )
}
