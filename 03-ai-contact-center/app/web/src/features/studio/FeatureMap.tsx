import { CheckCircle2, ExternalLink, LayoutGrid } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useI18n } from '../../i18n'
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
  const { t, tr, te, fmt, lang } = useI18n()
  const { data, error, loading, reload } = useApi<Feature[]>('/api/features')
  const ui = uiRoutesByFeature()
  if (loading && !data) return <Spinner />
  if (error || !data) return <ErrorBox error={error} onRetry={reload} />

  const epics = [...new Set(data.map((f) => f.epic))]
  const impl = data.filter((f) => f.status === 'implemented').length
  const withUi = data.filter((f) => (ui[f.id] ?? []).length > 0).length
  const tone = (p: string) => (p === 'P0' ? 'red' : p === 'P1' ? 'amber' : 'blue')
  // /api/features stays English (a contract with the docs and the smoke test): names, summaries and epics are translated here by feature id / epic letter
  const epicLabel = (epic: string) => (lang === 'en' ? epic : `${epic.charAt(0)} — ${te('feature.epic', epic.charAt(0), epic.replace(/^\S+\s—\s/, ''))}`)

  return (
    <div>
      <PageHeader
        icon={LayoutGrid}
        title={t('Feature map')}
        subtitle={t('Rendered live from GET /api/features — every Release-1 feature registers itself (backend auto-discovery) and owns a UI surface (frontend auto-discovery). Everything in the PRD is real, tested and deployed.')}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t('Release-1 features')} value={fmt.number(data.length)} hint="CC-01 … CC-24" />
        <Stat label={t('Implemented')} value={`${impl} / ${data.length}`} tone={impl === data.length ? 'good' : 'warn'} icon={CheckCircle2} />
        <Stat label={t('With a UI surface')} value={`${withUi} / ${data.length}`} tone={withUi === data.length ? 'good' : 'warn'} />
        <Stat label="P0 / P1 / P2" value={['P0', 'P1', 'P2'].map((p) => data.filter((f) => f.priority === p).length).join(' / ')} />
      </div>
      <div className="space-y-6">
        {epics.map((epic) => (
          <section key={epic} aria-label={epicLabel(epic)}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{epicLabel(epic)}</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data
                .filter((f) => f.epic === epic)
                .map((f) => {
                  const pages = ui[f.id] ?? []
                  const summary = te('feature.summary', f.id, f.summary)
                  return (
                    <Card key={f.id} className="h-full" pad={false}>
                      <div className="flex h-full flex-col gap-2 p-4" data-testid={`feature-${f.id}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-sm font-semibold text-blue-700">{f.id}</span>
                          <span className="flex gap-1.5">
                            <Badge tone={tone(f.priority)}>{f.priority}</Badge>
                            <Badge tone={f.status === 'implemented' ? 'green' : 'amber'}>{te('featureStatus', f.status)}</Badge>
                          </span>
                        </div>
                        <h3 className="text-sm font-semibold text-slate-900">{te('feature.name', f.id, f.name)}</h3>
                        {summary && <p className="text-xs leading-relaxed text-slate-600">{summary}</p>}
                        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs">
                          {pages.length ? (
                            pages.map((p) => (
                              <Link key={p.route} to={p.route} className="inline-flex items-center gap-1 font-medium text-blue-700 hover:underline">
                                <ExternalLink size={12} aria-hidden /> {tr(p.title)}
                              </Link>
                            ))
                          ) : (
                            <span className="text-slate-400">{t('UI route {route}', { route: f.ui_route })}</span>
                          )}
                          <a href="/docs" className="font-mono text-slate-500 hover:underline" title={t('OpenAPI')}>
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
