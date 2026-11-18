import { Wrench } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Spinner, Tabs } from '../../lib/ui'

interface Tool { name: string; description: string; state_changing: boolean; min_level: number | string; idempotent: boolean; agents: string[]; needs_confirmation?: boolean }
interface Cat { config: string; agents: Record<string, string[]>; tools: Tool[]; policy: Record<string, unknown> }
interface Approval { id: string; kind: string; amount: number; currency?: string; amount_eur?: number; order_id: string | null; conv_id: string; status: string; reason: string; created_at: number; decided_by?: string; note?: string }
interface AuditRow { seq: number; ts: number; actor: string; action: string; resource: string; outcome: string; conv_id: string | null; detail: Record<string, unknown> }

export default function ToolsPage() {
  const { t, te, tl, ts, fmt } = useI18n()
  const [tab, setTab] = useState('catalogue')
  const cat = useApi<Cat>('/api/tools/catalogue')
  const appr = useApi<Approval[]>('/api/tools/approvals', { refreshMs: 8000 })
  const audit = useApi<AuditRow[]>('/api/tools/audit?limit=60', { refreshMs: 10000 })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const decide = async (a: Approval, approve: boolean) => {
    setBusy(true)
    setErr(null)
    try {
      await api(`/api/tools/approvals/${a.id}/decision`, { body: { approve, note: approve ? 'approved' : 'declined' } })
      appr.reload()
    } catch (e) {
      setErr(describeError(e))
    } finally {
      setBusy(false)
    }
  }
  const policyValue = (v: unknown) => (typeof v === 'boolean' ? te('bool', String(v)) : typeof v === 'number' ? fmt.plain(v) : te('policyValue', String(v)))
  const pending = appr.data?.filter((a) => a.status === 'pending').length ?? 0
  return (
    <div>
      <PageHeader icon={Wrench} title={t('Transactional tools & policy')} subtitle={t('The model can only request tools. Allow-lists per agent, authentication levels, refund caps, a customer-confirmation gate, idempotency keys and an audit trail are enforced in code — a prompt cannot talk its way around them.')} />
      <Tabs tabs={[{ id: 'catalogue', label: t('Tool catalogue ({n})', { n: cat.data?.tools.length ?? '…' }) }, { id: 'approvals', label: t('Approvals ({n} pending)', { n: pending }) }, { id: 'audit', label: t('Tool audit trail') }]} value={tab} onChange={setTab} />
      {err && <p role="alert" className="mb-3 text-sm text-rose-700">{err}</p>}
      {tab === 'catalogue' && (cat.loading && !cat.data ? <Spinner /> : cat.error || !cat.data ? <ErrorBox error={cat.error} /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card title={t('Tools (config {config})', { config: cat.data.config })} pad={false}>
            <DataTable dense rows={cat.data.tools} rowKey={(x) => x.name} cols={[
              { key: 'n', header: t('Tool'), render: (x) => <span className="font-mono text-xs font-semibold">{x.name}</span> },
              { key: 'd', header: t('What it does'), render: (x) => <span className="text-xs text-slate-600">{ts(x.description)}</span> },
              { key: 'l', header: t('Auth level'), render: (x) => (typeof x.min_level === 'number' ? <Badge tone={x.min_level === 0 ? 'slate' : 'blue'}>L{x.min_level}</Badge> : <Badge tone="blue">{te('toolLevel', x.min_level)}</Badge>) },
              { key: 's', header: t('Writes'), render: (x) => (x.state_changing ? <Badge tone="amber">{t('confirm + idempotent')}</Badge> : <span className="text-slate-400">{t('read')}</span>) },
              { key: 'a', header: t('Allowed for'), render: (x) => <span className="text-xs">{x.agents.map((a) => te('agentRole', a)).join(', ')}</span> },
            ]} />
          </Card>
          <div className="space-y-4">
            <Card title={t('Policy (config as code)')}>
              <dl className="space-y-1 text-sm">{Object.entries(cat.data.policy).filter(([, v]) => typeof v !== 'object').map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-slate-500">{te('policyParam', k)}</dt><dd className="font-medium tabular-nums">{policyValue(v)}</dd></div>)}</dl>
            </Card>
            <Card title={t('Allow-lists')}>
              <dl className="space-y-2 text-xs">{Object.entries(cat.data.agents).map(([a, names]) => <div key={a}><dt className="font-semibold text-slate-700">{te('agentRole', a)}</dt><dd className="mt-0.5 flex flex-wrap gap-1">{names.map((n) => <Badge key={n} className="font-mono">{n}</Badge>)}</dd></div>)}</dl>
            </Card>
          </div>
        </div>
      ))}
      {tab === 'approvals' && (
        <Card title={t('Above-cap approvals')} subtitle={t('refunds above the autonomous cap are requested by the AI and decided by a supervisor')} pad={false}>
          {!appr.data?.length ? <div className="p-4"><Empty>{t('None yet. In the widget as customer CU-1004 (Carlos, Spanish): “Mi colchón llegó dañado, pedido CH-100270 … quiero un reembolso”.')}</Empty></div> : (
            <DataTable dense rows={appr.data} rowKey={(a) => a.id} cols={[
              { key: 'i', header: t('Request'), render: (a) => <span className="font-mono text-xs">{a.id}</span> },
              { key: 'k', header: t('What'), render: (a) => `${te('approvalKind', a.kind)} ${fmt.money(a.amount, a.currency)}` },
              { key: 'o', header: t('Order'), render: (a) => a.order_id },
              { key: 's', header: t('Status'), render: (a) => <Badge tone={a.status === 'pending' ? 'amber' : a.status === 'approved' ? 'green' : 'red'}>{te('approvalStatus', a.status)}</Badge> },
              { key: 'b', header: t('Decided by'), render: (a) => a.decided_by ?? '—' },
              { key: 'x', header: '', render: (a) => (a.status === 'pending' ? <div className="flex gap-1.5"><Button size="sm" variant="success" disabled={busy} onClick={() => decide(a, true)}>{t('Approve')}</Button><Button size="sm" variant="danger" disabled={busy} onClick={() => decide(a, false)}>{t('Deny')}</Button></div> : null) },
            ]} />
          )}
        </Card>
      )}
      {tab === 'audit' && (
        <Card title={t('Audit trail')} subtitle={t('hash-chained; every tool call records actor, arguments (redacted), outcome and idempotency key')} pad={false}>
          <DataTable dense rows={audit.data ?? []} rowKey={(r) => String(r.seq)} empty={t('No tool calls yet.')} cols={[
            { key: 's', header: '#', render: (r) => r.seq },
            { key: 't', header: t('Time'), render: (r) => fmt.time(r.ts) },
            { key: 'a', header: t('Action'), render: (r) => <span className="font-mono text-xs">{r.action}</span> },
            { key: 'w', header: t('Actor'), render: (r) => tl('role', r.actor, r.actor) },
            { key: 'o', header: t('Outcome'), render: (r) => <Badge tone={r.outcome === 'ok' ? 'green' : 'amber'}>{te('outcome', r.outcome)}</Badge> },
            { key: 'd', header: t('Detail'), render: (r) => <span data-user-content className="text-xs text-slate-500">{JSON.stringify(r.detail).slice(0, 100)}</span> },
          ]} />
        </Card>
      )}
    </div>
  )
}
