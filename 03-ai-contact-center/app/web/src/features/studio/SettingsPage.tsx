import { RefreshCw, Settings } from 'lucide-react'
import { useState } from 'react'
import { ROLES, api, getRole, setRole, useApi, type Role } from '../../lib/api'
import { Badge, Button, Card, ErrorBox, Json, PageHeader, Spinner } from '../../lib/ui'

interface SettingsDoc {
  meta: Record<string, unknown>
  seed: { status: string; steps: Record<string, { ok: boolean; seconds?: number }> }
  policy: Record<string, unknown>
  retention: Record<string, unknown>
}

export default function SettingsPage() {
  const s = useApi<SettingsDoc>('/api/studio/settings')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [role, setR] = useState<Role>(getRole())

  const resetBo = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await api('/api/admin/reset-backoffice', { method: 'POST' })
      setMsg('Demo orders restored: returns, refunds, credits and tickets created by journeys were cleared.')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const reseed = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api<{ status: string }>('/api/admin/reseed', { method: 'POST' })
      setMsg(`Reseed finished: ${r.status}`)
      s.reload()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader icon={Settings} title="Settings & demo data" subtitle="Environment, demo role, seeded synthetic data and policy parameters. Seeding is idempotent and runs automatically on first start." />
      {s.loading && <Spinner />}
      {s.error && <ErrorBox error={s.error} onRetry={s.reload} />}
      {s.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Demo role (CC-21)" subtitle="The role switcher sets the X-Demo-Role header; the API enforces permissions per role. In Entra mode the same checks use validated JWT app roles.">
            <div className="flex flex-wrap gap-2">
              {ROLES.map((r) => (
                <Button
                  key={r}
                  variant={role === r ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => {
                    setRole(r)
                    setR(r)
                  }}
                >
                  {r}
                </Button>
              ))}
            </div>
          </Card>
          <Card
            title="Seed data"
            subtitle="Back-office (customers, orders, shipments), knowledge base, 90-day analytics history, WFM interval history"
            actions={
              <>
                <Button size="sm" busy={busy} onClick={resetBo} data-testid="reset-backoffice">
                  Reset demo orders
                </Button>
                <Button size="sm" icon={RefreshCw} busy={busy} onClick={reseed} data-testid="reseed">
                  Reseed
                </Button>
              </>
            }
          >
            <div className="mb-2 flex items-center gap-2 text-sm">
              Status: <Badge tone={s.data.seed.status === 'done' ? 'green' : 'amber'}>{s.data.seed.status}</Badge>
              {msg && <span className="text-xs text-slate-500">{msg}</span>}
            </div>
            <ul className="space-y-1 text-xs text-slate-600">
              {Object.entries(s.data.seed.steps ?? {}).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="font-mono">{k}</span>
                  <span>{v.ok ? `ok · ${v.seconds ?? 0}s` : 'failed'}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Environment">
            <Json data={s.data.meta} max={260} />
          </Card>
          <Card title="Active policy parameters (code-enforced)">
            <Json data={s.data.policy} max={260} />
          </Card>
        </div>
      )}
    </div>
  )
}
