import { useEffect, useState } from 'react'
import { Mono } from '../../components/bits'
import { Badge, Card, Page, Table, Td } from '../../components/ui'
import { ROLES, getRole, setRole, useApi, type Role } from '../../lib/api'

type Roles = { roles: { id: string; label: string; permissions: string[] }[]; permissions: Record<string, string[]>; auth: { demo_role_switcher: boolean; entra_jwt_validation: boolean; default_role: string } }
type Me = { role: string; label: string; subject: string; source: string; permissions: string[] }
type Audit = { items: { t: number; role: string; subject: string; permission?: string; action?: string; allowed: boolean; path?: string }[]; denied_total: number; entries: number }

export default function Access() {
  const [role, setRoleState] = useState<Role>(getRole())
  const roles = useApi<Roles>('/api/access/roles')
  const me = useApi<Me>(`/api/access/me?r=${role}`)
  const canAudit = me.data?.permissions.includes('audit_view') ?? false
  const audit = useApi<Audit>(canAudit ? `/api/access/audit?r=${role}` : null, { interval: 5000 })
  useEffect(() => {
    const h = () => setRoleState(getRole())
    window.addEventListener('nightshift-role', h)
    return () => window.removeEventListener('nightshift-role', h)
  }, [])
  const perms = Object.keys(roles.data?.permissions ?? {}).sort()
  return (
    <Page title="Access control (RBAC)" subtitle="Five roles gate every consequential API call server-side (HTTP 403 otherwise) and every grant or denial is audited. Production sign-in is Microsoft Entra ID (JWT validation implemented and tested); this demo uses a role switcher in the header so you can see the effect.">
      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card title="You are">
          <div className="flex items-center gap-2"><Badge tone="info">{me.data?.label ?? role}</Badge><span className="text-[12px] text-mute">{me.data?.subject} · via {me.data?.source}</span></div>
          <div className="mt-3 flex flex-wrap gap-1.5">{ROLES.map((r) => <button key={r} onClick={() => setRole(r)} className={`rounded-md border px-2 py-1 text-xs ${role === r ? 'border-accent bg-accent/15 text-accent' : 'border-line hover:border-accent'}`}>{r.replace('_', ' ')}</button>)}</div>
          <p className="mt-3 text-[12px] text-mute">Switching role changes what the server allows - try the Policy dial as <i>operator</i> (denied) vs <i>plant manager</i>.</p>
          <div className="mt-3 text-[11px] text-mute">Auth mode: {roles.data?.auth.entra_jwt_validation ? 'Entra JWT validation ON' : 'demo role switcher'} · default role {roles.data?.auth.default_role}</div>
        </Card>
        <Card title="Permission matrix" pad={false}>
          <div className="max-h-[420px] overflow-auto">
            <Table head={['Permission', ...(roles.data?.roles.map((r) => r.label) ?? [])]}>
              {perms.map((p) => <tr key={p}><Td className="font-mono text-[12px]">{p}</Td>{(roles.data?.roles ?? []).map((r) => <Td key={r.id} className={r.id === role ? 'bg-accent/5' : ''}>{roles.data!.permissions[p].includes(r.id) ? <span className="text-ok">✓</span> : <span className="text-mute/50">–</span>}</Td>)}</tr>)}
            </Table>
          </div>
        </Card>
      </div>
      <Card title={`Audit log (${audit.data?.entries ?? 0} entries · ${audit.data?.denied_total ?? 0} denied)`} pad={false}>
        {!canAudit ? <p className="p-4 text-sm text-warn">The audit log is visible to auditors and administrators only (you are {role.replace('_', ' ')}). Switch role to view it - the same server-side check returns HTTP 403 for anyone else.</p> : (
          <Table head={['When', 'Role', 'Subject', 'Action', 'Result']}>
            {(audit.data?.items ?? []).slice(0, 15).map((a, i) => <tr key={i}><Td className="tabnum text-mute">{new Date(a.t * 1000).toISOString().slice(11, 19)}</Td><Td>{a.role}</Td><Td className="text-[12px] text-mute">{a.subject}</Td><Td><Mono>{a.permission ?? a.action ?? a.path}</Mono></Td><Td><Badge tone={a.allowed ? 'ok' : 'bad'}>{a.allowed ? 'allowed' : 'denied (403)'}</Badge></Td></tr>)}
          </Table>
        )}
      </Card>
    </Page>
  )
}
