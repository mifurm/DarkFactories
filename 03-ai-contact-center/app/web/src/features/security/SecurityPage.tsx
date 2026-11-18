import { Lock } from 'lucide-react'
import { useMemo, useState } from 'react'
import { fmt, useApi } from '../../lib/api'
import { Badge, Card, DataTable, ErrorBox, PageHeader, Spinner, Stat, Tabs, cx, inputCls } from '../../lib/ui'

interface Who { role: string; user: string; source: string; permissions: string[]; auth_mode: string; label: string }
interface Matrix { roles: { role: string; description: string; permissions: string[] }[]; endpoints: { method: string; path: string; requires: string[] | null; public: boolean; roles: string[] }[]; groups: { group: string; endpoints: number; public: number; roles_any: string[] }[]; totals: { endpoints: number; public: number; protected: number }; principle: string }
interface Settings { auth_mode: string; demo_role_switcher: boolean; demo_label: string; entra: { tenant_id: string | null; audience: string | null; validation: string; container_apps_builtin_auth: string }; identity: { azure_access: string; keys: string }; transport: { tls: string; headers: string[]; ws_origin_check: boolean; rate_limits: Record<string, number> }; retention: { class: string; days: number; enforced_by: string }[] }
interface AuditRow { seq: number; ts: number; actor: string; action: string; resource: string; outcome: string; detail: Record<string, unknown> }
interface AccessAudit { entries: AuditRow[]; verify: { ok: boolean; checked: number }; readonly: boolean }

const ROLE_TONE: Record<string, string> = { admin: 'red', supervisor: 'violet', agent: 'blue', qa: 'green', wfm: 'cyan', auditor: 'amber', customer: 'slate' }

export default function SecurityPage() {
  const [tab, setTab] = useState('roles')
  const who = useApi<Who>('/api/security/whoami')
  return (
    <div>
      <PageHeader icon={Lock} title="Security, identity & RBAC" subtitle="Seven roles enforced at the API (staff capabilities are default-deny), Entra-ready JWT validation, a clearly labelled demo role switcher, an access audit of who viewed which record, and keyless managed-identity access to every Azure service."
        actions={who.data && <Badge tone={ROLE_TONE[who.data.role]}>you are {who.data.role} · {who.data.label}</Badge>} />
      <Tabs tabs={[{ id: 'roles', label: 'Roles & permissions' }, { id: 'endpoints', label: 'Endpoint matrix' }, { id: 'settings', label: 'Auth, transport & retention' }, { id: 'audit', label: 'Access audit' }]} value={tab} onChange={setTab} />
      {tab === 'roles' && <Roles />}
      {tab === 'endpoints' && <Endpoints />}
      {tab === 'settings' && <SettingsTab />}
      {tab === 'audit' && <AuditTab />}
    </div>
  )
}

function Roles() {
  const m = useApi<Matrix>('/api/security/matrix')
  if (m.loading && !m.data) return <Spinner />
  if (m.error || !m.data) return <ErrorBox error={m.error} />
  const groups = m.data.groups.filter((g) => g.group.startsWith('/api/') && g.public < g.endpoints)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3"><Stat label="HTTP endpoints" value={m.data.totals.endpoints} /><Stat label="Role-protected" value={m.data.totals.protected} tone="green" /><Stat label="Public by design" value={m.data.totals.public} hint="customer flows, health, catalogues" /></div>
      <Card title="Role × API group" subtitle={m.data.principle} pad={false}>
        <div className="scroll-thin overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><th className="px-3 py-2 text-left font-medium">API group</th>{m.data.roles.map((r) => <th key={r.role} className="px-2 py-2 font-medium">{r.role}</th>)}</tr></thead>
          <tbody>{groups.map((g) => <tr key={g.group} className="border-b border-slate-100"><td className="px-3 py-1.5 font-mono text-xs">{g.group}</td>{m.data!.roles.map((r) => <td key={r.role} className="px-2 py-1.5 text-center">{g.roles_any.includes(r.role) ? <span className={cx('inline-block h-4 w-4 rounded-full', r.role === 'admin' ? 'bg-rose-400' : 'bg-emerald-500')} title="allowed" /> : <span className="inline-block h-4 w-4 rounded-full bg-slate-100" title="denied" />}</td>)}</tr>)}</tbody></table></div>
      </Card>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{m.data.roles.map((r) => <Card key={r.role} title={<Badge tone={ROLE_TONE[r.role]}>{r.role}</Badge>} subtitle={r.description}><div className="flex flex-wrap gap-1">{r.permissions.map((p) => <Badge key={p} tone="slate">{p}</Badge>)}</div></Card>)}</div>
    </div>
  )
}

function Endpoints() {
  const m = useApi<Matrix>('/api/security/matrix')
  const [q, setQ] = useState('')
  const [only, setOnly] = useState(true)
  const rows = useMemo(() => (m.data?.endpoints ?? []).filter((e) => (!only || !e.public) && (q === '' || e.path.includes(q))), [m.data, q, only])
  if (m.loading && !m.data) return <Spinner />
  return (
    <Card title={`Endpoints (${rows.length})`} subtitle="introspected from the running route table — not hand-written" actions={<><input aria-label="Filter paths" value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter…" className={cx(inputCls, 'w-44')} /><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} className="accent-blue-600" />protected only</label></>} pad={false}>
      <div className="max-h-[560px] overflow-y-auto"><DataTable dense rows={rows.slice(0, 250)} rowKey={(e) => `${e.method} ${e.path}`} cols={[{ key: 'm', header: 'Method', render: (e) => <Badge tone={e.method === 'GET' ? 'blue' : 'amber'}>{e.method}</Badge> }, { key: 'p', header: 'Path', render: (e) => <span className="font-mono text-xs">{e.path}</span> }, { key: 'r', header: 'Requires one of', render: (e) => (e.requires ? <span className="text-xs">{e.requires.join(' | ')}</span> : <Badge tone="slate">public</Badge>) }, { key: 'o', header: 'Roles', render: (e) => <span className="text-xs text-slate-500">{e.public ? 'all' : e.roles.join(', ')}</span> }]} /></div>
    </Card>
  )
}

function SettingsTab() {
  const s = useApi<Settings>('/api/security/settings')
  if (s.loading && !s.data) return <Spinner />
  if (s.error || !s.data) return <ErrorBox error={s.error} />
  const d = s.data
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Authentication" actions={<Badge tone={d.demo_role_switcher ? 'amber' : 'green'}>{d.auth_mode}</Badge>}><p className="text-sm text-slate-700">{d.demo_label}</p><dl className="mt-3 space-y-1 text-xs"><div className="flex gap-2"><dt className="w-24 shrink-0 text-slate-500">Entra tenant</dt><dd>{d.entra.tenant_id ?? 'not configured (demo mode)'}</dd></div><div className="flex gap-2"><dt className="w-24 shrink-0 text-slate-500">Audience</dt><dd>{d.entra.audience ?? '—'}</dd></div><div className="flex gap-2"><dt className="w-24 shrink-0 text-slate-500">Validation</dt><dd>{d.entra.validation}</dd></div><div className="flex gap-2"><dt className="w-24 shrink-0 text-slate-500">Built-in auth</dt><dd>{d.entra.container_apps_builtin_auth}</dd></div></dl></Card>
      <Card title="Keyless Azure access"><p className="text-sm text-slate-700">{d.identity.azure_access}</p><p className="mt-2 rounded-lg bg-emerald-50 p-2 text-xs text-emerald-900">{d.identity.keys}</p></Card>
      <Card title="Transport & abuse protection"><p className="text-sm text-slate-700">{d.transport.tls}</p><div className="mt-2 flex flex-wrap gap-1">{d.transport.headers.map((h) => <Badge key={h} tone="green">{h}</Badge>)}<Badge tone="green">WebSocket origin check</Badge></div><p className="mt-2 text-xs text-slate-500">Rate limits: {Object.entries(d.transport.rate_limits).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}</p></Card>
      <Card title="Retention by data class" pad={false}><DataTable dense rows={d.retention} rowKey={(r) => r.class} cols={[{ key: 'c', header: 'Class', render: (r) => r.class }, { key: 'd', header: 'Days', align: 'right', render: (r) => r.days }, { key: 'e', header: 'Enforced by', render: (r) => <span className="text-xs">{r.enforced_by}</span> }]} /></Card>
    </div>
  )
}

function AuditTab() {
  const a = useApi<AccessAudit>('/api/security/access-audit?limit=100', { refreshMs: 15000 })
  if (a.error) return <ErrorBox error={a.error} />
  return (
    <Card title="Access audit" subtitle="who viewed which transcript / record (Agent, Supervisor, QA, Auditor) — read-only for the Auditor role" actions={a.data && <Badge tone={a.data.verify.ok ? 'green' : 'red'}>chain {a.data.verify.ok ? 'intact' : 'BROKEN'} · {a.data.verify.checked}</Badge>} pad={false}>
      {!a.data ? <Spinner /> : <DataTable dense rows={a.data.entries} rowKey={(r) => String(r.seq)} empty="No access events yet — open a conversation in the agent console or QA workbench." cols={[{ key: 't', header: 'Time', render: (r) => fmt.dt(r.ts) }, { key: 'a', header: 'Action', render: (r) => <span className="font-mono text-xs">{r.action}</span> }, { key: 'w', header: 'Actor', render: (r) => r.actor }, { key: 'r', header: 'Resource', render: (r) => <span className="text-xs text-slate-500">{r.resource}</span> }]} />}
    </Card>
  )
}
