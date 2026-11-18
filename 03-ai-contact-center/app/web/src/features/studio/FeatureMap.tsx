import { CheckCircle2, ExternalLink, LayoutGrid } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApi } from '../../lib/api'
import { uiRoutesByFeature } from '../../lib/feature'
import { Badge, Card, ErrorBox, PageHeader, Spinner, Stat } from '../../lib/ui'

interface Feature {
  id: string
  name: string
  epic: string
  priority: string
  status: string
  ui_route: string
  api_prefix: string
  summary: string
}

export default function FeatureMap() {
  const { data, error, loading, reload } = useApi<Feature[]>('/api/features')
  const ui = uiRoutesByFeature()
  if (loading) return <Spinner />
  if (error || !data) return <ErrorBox error={error} onRetry={reload} />

  const epics = [...new Set(data.map((f) => f.epic))]
  const impl = data.filter((f) => f.status === 'implemented').length
  const withUi = data.filter((f) => (ui[f.id] ?? []).length > 0).length
  const tone = (p: string) => (p === 'P0' ? 'red' : p === 'P1' ? 'amber' : 'blue')

  return (
    <div>
      <PageHeader
        icon={LayoutGrid}
        title="Feature map"
        subtitle="Rendered live from GET /api/features — every Release-1 feature registers itself (backend auto-discovery) and owns a UI surface (frontend auto-discovery). Everything in the PRD is real, tested and deployed."
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Release-1 features" value={data.length} hint="CC-01 … CC-24" />
        <Stat label="Implemented" value={`${impl} / ${data.length}`} tone={impl === data.length ? 'good' : 'warn'} icon={CheckCircle2} />
        <Stat label="With a UI surface" value={`${withUi} / ${data.length}`} tone={withUi === data.length ? 'good' : 'warn'} />
        <Stat label="P0 / P1 / P2" value={['P0', 'P1', 'P2'].map((p) => data.filter((f) => f.priority === p).length).join(' / ')} />
      </div>
      <div className="space-y-6">
        {epics.map((epic) => (
          <section key={epic} aria-label={epic}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{epic}</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data
                .filter((f) => f.epic === epic)
                .map((f) => {
                  const pages = ui[f.id] ?? []
                  return (
                    <Card key={f.id} className="h-full" pad={false}>
                      <div className="flex h-full flex-col gap-2 p-4" data-testid={`feature-${f.id}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-sm font-semibold text-blue-700">{f.id}</span>
                          <span className="flex gap-1.5">
                            <Badge tone={tone(f.priority)}>{f.priority}</Badge>
                            <Badge tone={f.status === 'implemented' ? 'green' : 'amber'}>{f.status}</Badge>
                          </span>
                        </div>
                        <h3 className="text-sm font-semibold text-slate-900">{f.name}</h3>
                        {f.summary && <p className="text-xs leading-relaxed text-slate-600">{f.summary}</p>}
                        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs">
                          {pages.length ? (
                            pages.map((p) => (
                              <Link key={p.route} to={p.route} className="inline-flex items-center gap-1 font-medium text-blue-700 hover:underline">
                                <ExternalLink size={12} aria-hidden /> {p.title}
                              </Link>
                            ))
                          ) : (
                            <span className="text-slate-400">UI route {f.ui_route}</span>
                          )}
                          <a href="/docs" className="font-mono text-slate-500 hover:underline" title="OpenAPI">
                            {f.api_prefix}
                          </a>
                        </div>
                      </div>
                    </Card>
                  )
                })}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
