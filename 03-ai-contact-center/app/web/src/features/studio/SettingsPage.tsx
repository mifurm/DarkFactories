import { RefreshCw, Settings } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { LanguageSwitcher } from '../../i18n/LanguageSwitcher'
import { ROLES, api, describeError, getRole, setRole, useApi, type Role } from '../../lib/api'
import { Badge, Button, Card, ErrorBox, Json, PageHeader, Spinner } from '../../lib/ui'

interface SettingsDoc {
  meta: Record<string, unknown>
  seed: { status: string; steps: Record<string, { ok: boolean; seconds?: number }> }
  policy: Record<string, unknown>
  retention: Record<string, unknown>
}

export default function SettingsPage() {
  const { t, te, fmt } = useI18n()
  const s = useApi<SettingsDoc>('/api/studio/settings')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [role, setR] = useState<Role>(getRole())

  const resetBo = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await api('/api/admin/reset-backoffice', { method: 'POST' })
      setMsg(t('Demo orders restored: returns, refunds, credits and tickets created by journeys were cleared.'))
    } catch (e) {
      setMsg(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  const reseed = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api<{ status: string }>('/api/admin/reseed', { method: 'POST' })
      setMsg(t('Reseed finished: {status}', { status: te('seedStatus', r.status) }))
      s.reload()
    } catch (e) {
      setMsg(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader icon={Settings} title={t('Settings & demo data')} subtitle={t('Environment, demo role, seeded synthetic data and policy parameters. Seeding is idempotent and runs automatically on first start.')} />
      {s.loading && !s.data && <Spinner />}
      {s.error && <ErrorBox error={s.error} onRetry={s.reload} />}
      {s.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={t('Demo role (CC-21)')} subtitle={t('The role switcher sets the X-Demo-Role header; the API enforces permissions per role. In Entra mode the same checks use validated JWT app roles.')}>
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
                  {te('role', r)}
                </Button>
              ))}
            </div>
          </Card>
          <Card title={t('Interface language')} subtitle={t('The language of this console. Your choice is remembered in this browser; server-generated texts follow it too. Customer conversations have their own language selector.')}>
            <LanguageSwitcher />
          </Card>
          <Card
            title={t('Seed data')}
            subtitle={t('Back-office (customers, orders, shipments), knowledge base, 90-day analytics history, WFM interval history')}
            actions={
              <>
                <Button size="sm" busy={busy} onClick={resetBo} data-testid="reset-backoffice">
                  {t('Reset demo orders')}
                </Button>
                <Button size="sm" icon={RefreshCw} busy={busy} onClick={reseed} data-testid="reseed">
                  {t('Reseed')}
                </Button>
              </>
            }
          >
            <div className="mb-2 flex items-center gap-2 text-sm">
              {t('Status:')} <Badge tone={s.data.seed.status === 'done' ? 'green' : 'amber'}>{te('seedStatus', s.data.seed.status)}</Badge>
              {msg && <span className="text-xs text-slate-500">{msg}</span>}
            </div>
            <ul className="space-y-1 text-xs text-slate-600">
              {Object.entries(s.data.seed.steps ?? {}).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="font-mono">{k}</span>
                  <span>{v.ok ? t('ok · {seconds}s', { seconds: fmt.plain(v.seconds ?? 0) }) : t('failed')}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t('Environment')}>
            <Json data={s.data.meta} max={260} />
          </Card>
          <Card title={t('Active policy parameters (code-enforced)')}>
            <Json data={s.data.policy} max={260} />
          </Card>
        </div>
      )}
    </div>
  )
}
