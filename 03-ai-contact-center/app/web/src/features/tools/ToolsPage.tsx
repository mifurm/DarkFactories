import { Wrench } from 'lucide-react'
import { useState } from 'react'
import { api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Spinner, Tabs } from '../../lib/ui'

interface Tool { name: string; description: string; state_changing: boolean; min_level: number | string; idempotent: boolean; agents: string[]; needs_confirmation?: boolean }
interface Cat { config: string; agents: Record<string, string[]>; tools: Tool[]; policy: Record<string, unknown> }
interface Approval { id: string; kind: string; amount: number; order_id: string | null; conv_id: string; status: string; reason: string; created_at: number; decided_by?: string; note?: string }
interface AuditRow { seq: number; ts: number; actor: string; action: string; resource: string; outcome: string; conv_id: string | null; detail: Record<string, unknown> }

export default function ToolsPage() {
  const [tab, setTab] = useState('catalogue')
  const cat = useApi<Cat>('/api/tools/catalogue')
  const appr = useApi<Approval[]>('/api/tools/approvals', { refreshMs: 8000 })
  const audit = useApi<AuditRow[]>('/api/tools/audit?limit=60', { refreshMs: 10000 })
  const [busy, setBusy] = useState(false)
  const decide = async (a: Approval, approve: boolean) => { setBusy(true); try { await api(`/api/tools/approvals/${a.id}/decision`, { body: { approve, note: approve ? 'approved' : 'declined' } }); appr.reload() } finally { setBusy(false) } }
  return (
    <div>
      <PageHeader icon={Wrench} title="Transactional tools & policy" subtitle="The model can only request tools. Allow-lists per agent, authentication levels, refund caps, a customer-confirmation gate, idempotency keys and an audit trail are enforced in code — a prompt cannot talk its way around them." />
      <Tabs tabs={[{ id: 'catalogue', label: `Tool catalogue (${cat.data?.tools.length ?? '…'})` }, { id: 'approvals', label: `Approvals (${appr.data?.filter((a) => a.status === 'pending').length ?? 0} pending)` }, { id: 'audit', label: 'Tool audit trail' }]} value={tab} onChange={setTab} />
      {tab === 'catalogue' && (cat.loading && !cat.data ? <Spinner /> : cat.error || !cat.data ? <ErrorBox error={cat.error} /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card title={`Tools (config ${cat.data.config})`} pad={false}><DataTable dense rows={cat.data.tools} rowKey={(t) => t.name} cols={[{ key: 'n', header: 'Tool', render: (t) => <span className="font-mono text-xs font-semibold">{t.name}</span> }, { key: 'd', header: 'What it does', render: (t) => <span className="text-xs text-slate-600">{t.description}</span> }, { key: 'l', header: 'Auth level', render: (t) => <Badge tone={t.min_level === 0 ? 'slate' : 'blue'}>L{String(t.min_level)}</Badge> }, { key: 's', header: 'Writes', render: (t) => (t.state_changing ? <Badge tone="amber">confirm + idempotent</Badge> : <span className="text-slate-300">read</span>) }, { key: 'a', header: 'Allowed for', render: (t) => <span className="text-xs">{t.agents.join(', ')}</span> }]} /></Card>
          <div className="space-y-4">
            <Card title="Policy (config as code)"><dl className="space-y-1 text-sm">{Object.entries(cat.data.policy).filter(([, v]) => typeof v !== 'object').map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-slate-500">{k}</dt><dd className="font-medium tabular-nums">{String(v)}</dd></div>)}</dl></Card>
            <Card title="Allow-lists"><dl className="space-y-2 text-xs">{Object.entries(cat.data.agents).map(([a, ts]) => <div key={a}><dt className="font-semibold text-slate-700">{a}</dt><dd className="mt-0.5 flex flex-wrap gap-1">{ts.map((t) => <Badge key={t}>{t}</Badge>)}</dd></div>)}</dl></Card>
          </div>
        </div>
      ))}
      {tab === 'approvals' && (
        <Card title="Above-cap approvals" subtitle="refunds above the autonomous cap are requested by the AI and decided by a supervisor" pad={false}>
          {!appr.data?.length ? <div className="p-4"><Empty>None yet. In the widget as customer CU-1004 (Carlos, Spanish): “Mi colchón llegó dañado, pedido CH-100270 … quiero un reembolso”.</Empty></div> : <DataTable dense rows={appr.data} rowKey={(a) => a.id} cols={[{ key: 'i', header: 'Request', render: (a) => <span className="font-mono text-xs">{a.id}</span> }, { key: 'k', header: 'What', render: (a) => `${a.kind} ${fmt.eur(a.amount)}` }, { key: 'o', header: 'Order', render: (a) => a.order_id }, { key: 's', header: 'Status', render: (a) => <Badge tone={a.status === 'pending' ? 'amber' : a.status === 'approved' ? 'green' : 'red'}>{a.status}</Badge> }, { key: 'b', header: 'Decided by', render: (a) => a.decided_by ?? '—' }, { key: 'x', header: '', render: (a) => (a.status === 'pending' ? <div className="flex gap-1.5"><Button size="sm" variant="success" disabled={busy} onClick={() => decide(a, true)}>Approve</Button><Button size="sm" variant="danger" disabled={busy} onClick={() => decide(a, false)}>Deny</Button></div> : null) }]} />}
        </Card>
      )}
      {tab === 'audit' && (
        <Card title="Audit trail" subtitle="hash-chained; every tool call records actor, arguments (redacted), outcome and idempotency key" pad={false}>
          <DataTable dense rows={audit.data ?? []} rowKey={(r) => String(r.seq)} empty="No tool calls yet." cols={[{ key: 's', header: '#', render: (r) => r.seq }, { key: 't', header: 'Time', render: (r) => fmt.time(r.ts) }, { key: 'a', header: 'Action', render: (r) => <span className="font-mono text-xs">{r.action}</span> }, { key: 'w', header: 'Actor', render: (r) => r.actor }, { key: 'o', header: 'Outcome', render: (r) => <Badge tone={r.outcome === 'ok' ? 'green' : 'amber'}>{r.outcome}</Badge> }, { key: 'd', header: 'Detail', render: (r) => <span className="text-xs text-slate-500">{JSON.stringify(r.detail).slice(0, 100)}</span> }]} />
        </Card>
      )}
    </div>
  )
}
