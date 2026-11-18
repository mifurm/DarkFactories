import { Rocket } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useApi } from '../../lib/api'
import { Badge, Card, ErrorBox, Json, PageHeader, Spinner } from '../../lib/ui'

interface Info {
  mode: string
  build_id: string
  region: string
  resource_group: string | null
  tags: Record<string, string>
  resources: { type: string; role: string; name: string }[]
  commands: Record<string, string>
  smoke_results: Record<string, unknown> | null
}

export default function DeploymentPage() {
  const { t, te, ts } = useI18n()
  const { data, error, loading, reload } = useApi<Info>('/api/deployment/info')
  if (loading) return <Spinner />
  if (error || !data) return <ErrorBox error={error} onRetry={reload} />
  return (
    <div>
      <PageHeader icon={Rocket} title={t('Deployment (IaC)')} subtitle={t('Bicep + azd with remote ACR build, keyless managed-identity access, governance tags on the resource group and every taggable resource.')} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('Deployed slice')} subtitle={t('{region} · {group} · build {build}', { region: data.region, group: data.resource_group ?? t('local'), build: data.build_id })}>
          <ul className="space-y-2 text-sm">
            {data.resources.map((r) => (
              <li key={r.type} className="rounded-lg border border-slate-100 p-2">
                <div className="font-medium text-slate-900">{ts(r.type)}</div>
                <div className="text-xs text-slate-600">{ts(r.role)}</div>
                <div className="font-mono text-xs text-slate-500">{ts(r.name)}</div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-4">
          <Card title={t('Governance tags (RG + every resource)')}>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.tags).map(([k, v]) => (
                <Badge key={k} tone="blue">
                  {k}={v}
                </Badge>
              ))}
            </div>
          </Card>
          <Card title={t('Commands')}>
            <dl className="space-y-2 text-sm">
              {Object.entries(data.commands).map(([k, v]) => (
                <div key={k}>
                  <dt className="text-xs font-medium uppercase text-slate-500">{te('deployCommand', k)}</dt>
                  <dd className="font-mono text-xs text-slate-800">{ts(v)}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {data.smoke_results && (
            <Card title={t('Last smoke test (self-reported)')}>
              <Json data={data.smoke_results} />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
