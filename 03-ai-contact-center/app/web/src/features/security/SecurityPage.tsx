import { Lock } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useI18n } from '../../i18n'
import { useApi } from '../../lib/api'
import { Badge, Card, DataTable, ErrorBox, PageHeader, Spinner, Stat, Tabs, cx, inputCls } from '../../lib/ui'

interface Who { role: string; user: string; source: string; permissions: string[]; auth_mode: string; label: string }
interface Matrix { roles: { role: string; description: string; permissions: string[] }[]; endpoints: { method: string; path: string; requires: string[] | null; public: boolean; roles: string[] }[]; groups: { group: string; endpoints: number; public: number; roles_any: string[] }[]; totals: { endpoints: number; public: number; protected: number }; principle: string }
interface Settings { auth_mode: string; demo_role_switcher: boolean; demo_label: string; entra: { tenant_id: string | null; audience: string | null; validation: string; container_apps_builtin_auth: string }; identity: { azure_access: string; keys: string }; transport: { tls: string; headers: string[]; ws_origin_check: boolean; rate_limits: Record<string, number> }; retention: { class: string; days: number; enforced_by: string }[] }
interface AuditRow { seq: number; ts: number; actor: string; action: string; resource: string; outcome: string; detail: Record<string, unknown> }
interface AccessAudit { entries: AuditRow[]; verify: { ok: boolean; checked: number }; readonly: boolean }

const ROLE_TONE: Record<string, string> = { admin: 'red', supervisor: 'violet', agent: 'blue', qa: 'green', wfm: 'cyan', auditor: 'amber', customer: 'slate' }

export default function SecurityPage() {
  const { t, te, ts } = useI18n()
  const [tab, setTab] = useState('roles')
  const who = useApi<Who>('/api/security/whoami')
  return (
    <div>
      <PageHeader icon={Lock} title={t('Security, identity & RBAC')} subtitle={t('Seven roles enforced at the API (staff capabilities are default-deny), Entra-ready JWT validation, a clearly labelled demo role switcher, an access audit of who viewed which record, and keyless managed-identity access to every Azure service.')}
        actions={who.data && <Badge tone={ROLE_TONE[who.data.role]}>{t('you are {role} · {label}', { role: te('role', who.data.role), label: ts(who.data.label) })}</Badge>} />
      <Tabs tabs={[{ id: 'roles', label: t('Roles & permissions') }, { id: 'endpoints', label: t('Endpoint matrix') }, { id: 'settings', label: t('Auth, transport & retention') }, { id: 'audit', label: t('Access audit') }]} value={tab} onChange={setTab} />
      {tab === 'roles' && <Roles />}
      {tab === 'endpoints' && <Endpoints />}
      {tab === 'settings' && <SettingsTab />}
      {tab === 'audit' && <AuditTab />}
    </div>
  )
}

function Roles() {
  const { t, te, ts } = useI18n()
  const m = useApi<Matrix>('/api/security/matrix')
  if (m.loading && !m.data) return <Spinner />
  if (m.error || !m.data) return <ErrorBox error={m.error} />
  const groups = m.data.groups.filter((g) => g.group.startsWith('/api/') && g.public < g.endpoints)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3"><Stat label={t('HTTP endpoints')} value={m.data.totals.endpoints} /><Stat label={t('Role-protected')} value={m.data.totals.protected} tone="green" /><Stat label={t('Public by design')} value={m.data.totals.public} hint={t('customer flows, health, catalogues')} /></div>
      <Card title={t('Role × API group')} subtitle={ts(m.data.principle)} pad={false}>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><th className="px-3 py-2 text-left font-medium">{t('API group')}</th>{m.data.roles.map((r) => <th key={r.role} className="px-2 py-2 font-medium">{te('role', r.role)}</th>)}</tr></thead>
            <tbody>{groups.map((g) => <tr key={g.group} className="border-b border-slate-100"><td className="px-3 py-1.5 font-mono text-xs">{g.group}</td>{m.data!.roles.map((r) => <td key={r.role} className="px-2 py-1.5 text-center">{g.roles_any.includes(r.role) ? <span className={cx('inline-block h-4 w-4 rounded-full', r.role === 'admin' ? 'bg-rose-400' : 'bg-emerald-500')} title={t('allowed')} /> : <span className="inline-block h-4 w-4 rounded-full bg-slate-100" title={t('denied')} />}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </Card>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{m.data.roles.map((r) => <Card key={r.role} title={<Badge tone={ROLE_TONE[r.role]}>{te('role', r.role)}</Badge>} subtitle={ts(r.description)}><div className="flex flex-wrap gap-1">{r.permissions.map((p) => <Badge key={p} tone="slate" className="font-mono">{p}</Badge>)}</div></Card>)}</div>
    </div>
  )
}

function Endpoints() {
  const { t, te, includes } = useI18n()
  const m = useApi<Matrix>('/api/security/matrix')
  const [q, setQ] = useState('')
  const [only, setOnly] = useState(true)
  const rows = useMemo(() => (m.data?.endpoints ?? []).filter((e) => (!only || !e.public) && includes(e.path, q)), [m.data, q, only, includes])
  if (m.loading && !m.data) return <Spinner />
  return (
    <Card title={t('Endpoints ({n})', { n: rows.length })} subtitle={t('introspected from the running route table — not hand-written')} actions={<><input aria-label={t('Filter paths')} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('filter…')} className={cx(inputCls, 'w-44')} /><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} className="accent-blue-600" />{t('protected only')}</label></>} pad={false}>
      <div className="max-h-[560px] overflow-y-auto">
        <DataTable dense rows={rows.slice(0, 250)} rowKey={(e) => `${e.method} ${e.path}`} cols={[
          { key: 'm', header: t('Method'), render: (e) => <Badge tone={e.method === 'GET' ? 'blue' : 'amber'} className="font-mono">{e.method}</Badge> },
          { key: 'p', header: t('Path'), render: (e) => <span className="font-mono text-xs">{e.path}</span> },
          { key: 'r', header: t('Requires one of'), render: (e) => (e.requires ? <span className="text-xs">{e.requires.join(' | ')}</span> : <Badge tone="slate">{t('public')}</Badge>) },
          { key: 'o', header: t('Roles'), render: (e) => <span className="text-xs text-slate-500">{e.public ? t('all') : e.roles.map((r) => te('role', r)).join(', ')}</span> },
        ]} />
      </div>
    </Card>
  )
}

function SettingsTab() {
  const { t, te, ts, fmt } = useI18n()
  const s = useApi<Settings>('/api/security/settings')
  if (s.loading && !s.data) return <Spinner />
  if (s.error || !s.data) return <ErrorBox error={s.error} />
  const d = s.data
  const row = (label: string, value: string | null | undefined) => <div className="flex gap-2"><dt className="w-24 shrink-0 text-slate-500">{label}</dt><dd>{value ?? '—'}</dd></div>
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={t('Authentication')} actions={<Badge tone={d.demo_role_switcher ? 'amber' : 'green'}>{te('authMode', d.auth_mode)}</Badge>}>
        <p className="text-sm text-slate-700">{ts(d.demo_label)}</p>
        <dl className="mt-3 space-y-1 text-xs">
          {row(t('Entra tenant'), d.entra.tenant_id ?? t('not configured (demo mode)'))}
          {row(t('Audience'), d.entra.audience)}
          {row(t('Validation'), ts(d.entra.validation))}
          {row(t('Built-in auth'), ts(d.entra.container_apps_builtin_auth))}
        </dl>
      </Card>
      <Card title={t('Keyless Azure access')}><p className="text-sm text-slate-700">{ts(d.identity.azure_access)}</p><p className="mt-2 rounded-lg bg-emerald-50 p-2 text-xs text-emerald-900">{ts(d.identity.keys)}</p></Card>
      <Card title={t('Transport & abuse protection')}>
        <p className="text-sm text-slate-700">{ts(d.transport.tls)}</p>
        <div className="mt-2 flex flex-wrap gap-1">{d.transport.headers.map((h) => <Badge key={h} tone="green" className="font-mono">{h}</Badge>)}<Badge tone="green">{t('WebSocket origin check')}</Badge></div>
        <p className="mt-2 text-xs text-slate-500">{t('Rate limits: {limits}', { limits: Object.entries(d.transport.rate_limits).map(([k, v]) => `${te('rateLimit', k)} ${fmt.plain(v)}`).join(' · ') })}</p>
      </Card>
      <Card title={t('Retention by data class')} pad={false}>
        <DataTable dense rows={d.retention} rowKey={(r) => r.class} cols={[
          { key: 'c', header: t('Class'), render: (r) => ts(r.class) },
          { key: 'd', header: t('Days'), align: 'right', render: (r) => fmt.plain(r.days) },
          { key: 'e', header: t('Enforced by'), render: (r) => <span className="text-xs">{ts(r.enforced_by)}</span> },
        ]} />
      </Card>
    </div>
  )
}

function AuditTab() {
  const { t, tl, fmt } = useI18n()
  const a = useApi<AccessAudit>('/api/security/access-audit?limit=100', { refreshMs: 15000 })
  if (a.error) return <ErrorBox error={a.error} />
  return (
    <Card title={t('Access audit')} subtitle={t('who viewed which transcript / record (Agent, Supervisor, QA, Auditor) — read-only for the Auditor role')} actions={a.data && <Badge tone={a.data.verify.ok ? 'green' : 'red'}>{a.data.verify.ok ? t('chain intact') : t('BROKEN')} · {fmt.plain(a.data.verify.checked)}</Badge>} pad={false}>
      {!a.data ? <Spinner /> : (
        <DataTable dense rows={a.data.entries} rowKey={(r) => String(r.seq)} empty={t('No access events yet — open a conversation in the agent console or QA workbench.')} cols={[
          { key: 't', header: t('Time'), render: (r) => fmt.dt(r.ts) },
          { key: 'a', header: t('Action'), render: (r) => <span className="font-mono text-xs">{r.action}</span> },
          { key: 'w', header: t('Actor'), render: (r) => tl('role', r.actor, r.actor) },
          { key: 'r', header: t('Resource'), render: (r) => <span className="text-xs text-slate-500">{r.resource}</span> },
        ]} />
      )}
    </Card>
  )
}
