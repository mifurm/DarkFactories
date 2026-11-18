import { Rocket } from 'lucide-react'
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
  const { data, error, loading, reload } = useApi<Info>('/api/deployment/info')
  if (loading) return <Spinner />
  if (error || !data) return <ErrorBox error={error} onRetry={reload} />
  return (
    <div>
      <PageHeader icon={Rocket} title="Deployment (IaC)" subtitle="Bicep + azd with remote ACR build, keyless managed-identity access, governance tags on the resource group and every taggable resource." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Deployed slice" subtitle={`${data.region} · ${data.resource_group ?? 'local'} · build ${data.build_id}`}>
          <ul className="space-y-2 text-sm">
            {data.resources.map((r) => (
              <li key={r.type} className="rounded-lg border border-slate-100 p-2">
                <div className="font-medium text-slate-900">{r.type}</div>
                <div className="text-xs text-slate-600">{r.role}</div>
                <div className="font-mono text-xs text-slate-500">{r.name}</div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-4">
          <Card title="Governance tags (RG + every resource)">
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.tags).map(([k, v]) => (
                <Badge key={k} tone="blue">
                  {k}={v}
                </Badge>
              ))}
            </div>
          </Card>
          <Card title="Commands">
            <dl className="space-y-2 text-sm">
              {Object.entries(data.commands).map(([k, v]) => (
                <div key={k}>
                  <dt className="text-xs font-medium uppercase text-slate-500">{k}</dt>
                  <dd className="font-mono text-xs text-slate-800">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {data.smoke_results && (
            <Card title="Last smoke test (self-reported)">
              <Json data={data.smoke_results} />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
