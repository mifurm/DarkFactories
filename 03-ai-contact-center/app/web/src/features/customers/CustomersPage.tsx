import { Database, PlugZap, Search, UserRound } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Spinner, Stat, Tabs, inputCls, sentimentTone } from '../../lib/ui'

interface Cust { id: string; name: string; tier: string; market: string; language: string; email: string; city: string | null; vulnerable: boolean; note?: string }
interface Ev { ts: number; type: string; id: string; title: string; detail?: string; sentiment?: number; handler?: string; status?: string; ai?: boolean; qa?: number | null }
interface C360 { customer: { id: string; name: string; email: string; phone: string; language: string; market: string; tier: string; vulnerable?: boolean; masked?: boolean; address?: { city?: string; postal_code?: string; street?: string } }; orders: { id: string; status: string; total: number; placed_at: number; items: string[] }[]; timeline: Ev[]; stats: { orders: number; interactions: number; ai_interactions: number; avg_sentiment: number | null; last_contact: number | null }; connector: string; masking: string }
interface Connectors { active: string; outage_simulated: boolean; ports: Record<string, string[]>; adapters: { name: string; kind: string; status: string; note: string }[]; tools_through_connector: string[]; resilience: string }
interface Contract { [adapter: string]: { passed: number; total: number; checks: { name: string; ok: boolean; detail: string }[] } | { passed: number; total: number; ms: number } }

const TYPE_TONE: Record<string, string> = { conversation: 'violet', order: 'blue', delivery: 'green', return: 'amber', refund: 'green', note: 'slate', task: 'slate', case: 'red', appointment: 'cyan' }

export default function CustomersPage() {
  const [tab, setTab] = useState('c360')
  return (
    <div>
      <PageHeader icon={UserRound} title="Customer 360 & CRM integration layer" subtitle="A connector abstraction (customer / order / case ports) with a mock CRM/OMS, a Dynamics 365 / Dataverse adapter and a config-driven generic REST adapter — the agent tools do not change when you swap the connector. PII is masked by role." />
      <Tabs tabs={[{ id: 'c360', label: 'Customer 360' }, { id: 'conn', label: 'Connectors & contract tests' }]} value={tab} onChange={setTab} />
      {tab === 'c360' ? <C360Tab /> : <ConnectorsTab />}
    </div>
  )
}

function C360Tab() {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState('CU-1001')
  const list = useApi<Cust[]>(`/api/crm/customers?q=${encodeURIComponent(q)}`, { deps: [q] })
  const c = useApi<C360>(sel ? `/api/crm/customers/${sel}/360` : null, { deps: [sel] })
  const d = c.data
  return (
    <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <Card title="Customers" pad={false}>
        <div className="border-b border-slate-100 p-3"><label className="relative block"><span className="sr-only">Search customers</span><Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" aria-hidden /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, e-mail, id, market…" className={`${inputCls} pl-8`} /></label></div>
        <ul className="max-h-[560px] divide-y divide-slate-100 overflow-y-auto">{(list.data ?? []).map((x) => <li key={x.id}><button type="button" onClick={() => setSel(x.id)} className={`w-full px-4 py-2 text-left hover:bg-blue-50/60 ${sel === x.id ? 'bg-blue-50' : ''}`}><div className="flex items-center justify-between"><b className="text-sm">{x.name}</b><span className="text-[11px] text-slate-500">{x.id}</span></div><div className="mt-0.5 flex gap-1 text-[11px]"><Badge>{x.market}</Badge>{x.tier === 'vip' && <Badge tone="violet">VIP</Badge>}{x.vulnerable && <Badge tone="amber">vulnerable</Badge>}</div>{x.note && <p className="mt-0.5 line-clamp-1 text-[11px] text-slate-500">{x.note}</p>}</button></li>)}</ul>
      </Card>
      <div className="space-y-4">
        {c.loading && !d ? <Spinner /> : c.error ? <ErrorBox error={c.error} /> : d && (
          <>
            <Card title={d.customer.name} subtitle={`${d.customer.id} · ${d.customer.market} · ${d.customer.language}`} actions={<Badge tone={d.customer.masked ? 'amber' : 'green'}>{d.masking}</Badge>}>
              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <div><div className="text-xs text-slate-500">E-mail</div>{d.customer.email}</div><div><div className="text-xs text-slate-500">Phone</div>{d.customer.phone}</div><div><div className="text-xs text-slate-500">City</div>{d.customer.address?.city}</div><div><div className="text-xs text-slate-500">Tier</div>{d.customer.tier}</div>
              </div>
            </Card>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Stat label="Orders" value={d.stats.orders} /><Stat label="AI / total interactions" value={`${d.stats.ai_interactions}/${d.stats.interactions}`} /><Stat label="Avg sentiment" value={d.stats.avg_sentiment ?? '—'} /><Stat label="Last contact" value={d.stats.last_contact ? fmt.dt(d.stats.last_contact) : '—'} /></div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Orders" pad={false}><DataTable dense rows={d.orders} rowKey={(o) => o.id} cols={[{ key: 'i', header: 'Order', render: (o) => <b>{o.id}</b> }, { key: 's', header: 'Status', render: (o) => <Badge tone={o.status === 'delivered' ? 'green' : o.status === 'delayed' ? 'red' : 'blue'}>{o.status}</Badge> }, { key: 't', header: 'Total', align: 'right', render: (o) => fmt.eur(o.total) }, { key: 'x', header: 'Items', render: (o) => <span className="text-xs text-slate-600">{o.items.join(', ')}</span> }]} /></Card>
              <Card title="Timeline" subtitle="orders, deliveries, cases, notes, AI and human interactions — newest first"><ol className="scroll-thin max-h-80 space-y-2 overflow-y-auto pr-1">{d.timeline.map((e, i) => <li key={i} className="flex gap-2 text-sm"><span className="w-28 shrink-0 text-[11px] text-slate-400">{fmt.dt(e.ts)}</span><div className="min-w-0"><div className="flex flex-wrap items-center gap-1.5"><Badge tone={TYPE_TONE[e.type] ?? 'slate'}>{e.type}</Badge><span className="font-medium text-slate-800">{e.title}</span>{e.sentiment != null && <Badge tone={sentimentTone(e.sentiment)}>{e.sentiment.toFixed(2)}</Badge>}{e.ai && <Badge tone="violet">AI</Badge>}</div>{e.detail && <p className="line-clamp-2 text-xs text-slate-500">{e.detail}</p>}</div></li>)}{!d.timeline.length && <Empty>No events.</Empty>}</ol></Card>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function ConnectorsTab() {
  const conn = useApi<Connectors>('/api/crm/connectors')
  const [rep, setRep] = useState<Contract | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const run = async () => { setBusy(true); try { setRep(await api<Contract>('/api/crm/contract-tests', { method: 'POST' })) } finally { setBusy(false) } }
  const outage = async (on: boolean) => { try { await api('/api/crm/outage', { body: { on } }); setMsg(on ? 'CRM outage simulated: customer/order reads now fail → tool failures → escalation to a human (never a crash).' : 'CRM restored.'); conn.reload() } catch (e) { setMsg(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } }
  const c = conn.data
  if (conn.loading && !c) return <Spinner />
  if (conn.error || !c) return <ErrorBox error={conn.error} />
  const s = rep?.summary as { passed: number; total: number; ms: number } | undefined
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        {c.adapters.map((a) => <Card key={a.name} title={<span className="flex items-center gap-2"><Database size={14} aria-hidden />{a.name}</span>} actions={<Badge tone={a.status === 'active' ? 'green' : 'blue'}>{a.status}</Badge>}><p className="text-sm text-slate-700">{a.kind}</p><p className="mt-1 text-xs text-slate-500">{a.note}</p></Card>)}
      </div>
      <Card title="Connector ports" subtitle="the interface the tools depend on"><div className="grid gap-3 md:grid-cols-3">{Object.entries(c.ports).map(([k, v]) => <div key={k}><div className="text-sm font-semibold text-slate-800">{k}</div><div className="mt-1 flex flex-wrap gap-1">{v.map((m) => <Badge key={m} tone="slate">{m}</Badge>)}</div></div>)}</div><p className="mt-3 text-xs text-slate-500">{c.resilience}</p></Card>
      <Card title="Contract tests" subtitle="the same suite runs against all three adapters (HTTP adapters against mocked servers: paging, auth header, 4xx/5xx, 429 Retry-After)" actions={<Button variant="primary" icon={PlugZap} busy={busy} onClick={run}>Run contract tests</Button>}>
        {!rep ? <p className="text-sm text-slate-500">Run the suite to see every check.</p> : (
          <div className="space-y-3">
            {s && <p className="text-sm"><Badge tone={s.passed === s.total ? 'green' : 'red'}>{s.passed}/{s.total} passed</Badge> <span className="text-xs text-slate-500">in {s.ms} ms</span></p>}
            <div className="grid gap-4 lg:grid-cols-3">{Object.entries(rep).filter(([k]) => k !== 'summary').map(([k, v]) => { const a = v as { passed: number; total: number; checks: { name: string; ok: boolean; detail: string }[] }; return <div key={k}><div className="mb-1 flex items-center gap-2 text-sm font-semibold"><span>{k}</span><Badge tone={a.passed === a.total ? 'green' : 'red'}>{a.passed}/{a.total}</Badge></div><ul className="scroll-thin max-h-72 space-y-0.5 overflow-y-auto text-[11px]">{a.checks.map((ch) => <li key={ch.name} className={ch.ok ? 'text-slate-600' : 'font-semibold text-rose-700'}>{ch.ok ? '✔' : '✘'} {ch.name.replace(/^[a-z0-9-]+: /, '')}</li>)}</ul></div> })}</div>
          </div>
        )}
      </Card>
      <Card title="Graceful degradation" subtitle="admin only: simulate a CRM outage and chat with the assistant">
        <div className="flex gap-2"><Button variant="danger" onClick={() => outage(true)}>Simulate CRM outage</Button><Button onClick={() => outage(false)}>Restore</Button>{c.outage_simulated && <Badge tone="red">outage active</Badge>}</div>{msg && <p role="status" className="mt-2 text-sm text-slate-700">{msg}</p>}
      </Card>
    </div>
  )
}
