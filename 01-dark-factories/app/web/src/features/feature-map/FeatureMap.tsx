import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, ErrorBox, Page, Spinner, Stat, Table, Td } from '../../components/ui'
import { useApi } from '../../lib/api'
import { featureUis, type FeatureSpec } from '../../lib/feature'

export default function FeatureMap() {
  const { data, error, loading } = useApi<FeatureSpec[]>('/api/features')
  const [prio, setPrio] = useState('all')
  const have = useMemo(() => new Set(featureUis.map((f) => f.route)), [])
  const rows = (data ?? []).filter((f) => prio === 'all' || f.priority === prio)
  const impl = (data ?? []).filter((f) => f.status === 'implemented').length

  return (
    <Page
      title="Feature Map"
      subtitle="Everything in the PRD is real: every Release-1 feature self-registers here with its status, API surface and screen."
      right={
        <select aria-label="Priority filter" value={prio} onChange={(e) => setPrio(e.target.value)} className="rounded-md border border-line bg-panel2 px-2 py-1 text-sm">
          <option value="all">All priorities</option>
          {['P0', 'P1', 'P2'].map((p) => <option key={p}>{p}</option>)}
        </select>
      }
    >
      <ErrorBox error={error} />
      {loading && <Spinner />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Release-1 features" value={data.length} />
            <Stat label="Implemented" value={impl} tone={impl === data.length ? 'ok' : 'warn'} sub={`${data.length - impl} planned`} />
            <Stat label="P0" value={data.filter((f) => f.priority === 'P0').length} />
            <Stat label="P1" value={data.filter((f) => f.priority === 'P1').length} />
            <Stat label="P2" value={data.filter((f) => f.priority === 'P2').length} />
          </div>
          <Card pad={false}>
            <Table head={['ID', 'Feature', 'Epic', 'Pri', 'Status', 'API', 'Screen', 'What is real']}>
              {rows.map((f) => (
                <tr key={f.id} className="hover:bg-white/[0.02]">
                  <Td className="tabnum whitespace-nowrap font-semibold text-accent">{f.id}</Td>
                  <Td className="min-w-48">
                    <div className="font-medium">{f.name}</div>
                    <div className="mt-0.5 max-w-xl text-xs text-mute">{f.summary}</div>
                  </Td>
                  <Td className="whitespace-nowrap text-xs text-mute">{f.epic}</Td>
                  <Td><Badge tone={f.priority === 'P0' ? 'info' : f.priority === 'P1' ? 'violet' : 'mute'}>{f.priority}</Badge></Td>
                  <Td><Badge tone={f.status === 'implemented' ? 'ok' : 'warn'}>{f.status}</Badge></Td>
                  <Td className="font-mono text-xs text-mute">{f.api_prefix}</Td>
                  <Td>{have.has(f.ui_route) ? <Link className="text-accent hover:underline" to={f.ui_route}>{f.ui_route}</Link> : <span className="text-mute">-</span>}</Td>
                  <Td className="max-w-sm text-xs text-mute">{f.depth}</Td>
                </tr>
              ))}
            </Table>
          </Card>
        </>
      )}
    </Page>
  )
}
