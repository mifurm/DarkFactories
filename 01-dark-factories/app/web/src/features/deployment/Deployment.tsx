import { useCallback, useEffect, useState } from 'react'
import { Mono } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Spinner, Table, Td } from '../../components/ui'
import { useApi } from '../../lib/api'

type Check = { status: string; backend?: string; latency_ms?: number; error?: string; model?: string; deployment?: string; endpoint?: string; account?: string; cached?: boolean }
type Ready = { status: string; mode: string; checks: Record<string, Check>; time: string }
type Meta = { name: string; version: string; build_id: string; mode: string; region: string; uptime_s: number; models: { chat: string; reasoning: string; backend: string }; persistence: { repository: string; blobs: string } }

type Info = { mode: string; region: string; resource_group: string; container_app: string; revision: string; endpoints: Record<string, string>; deployments: Record<string, string>; iac: { tool: string; scope: string; modules: string[]; remote_build: string; commands: Record<string, string> }; security: Record<string, string> }
type Res = { available: boolean; reason?: string; resource_group?: string; location?: string; tags?: Record<string, string>; resources: { name: string; type: string; provider: string; location: string; sku?: string; tags: Record<string, string> }[] }
type Smoke = { results: { name: string; status: string; detail?: string; ms?: number }[]; passed?: number; failed?: number; base_url?: string; reported_at?: string; note?: string }

export default function Deployment() {
  const meta = useApi<Meta>('/api/meta', { interval: 15000 })
  const info = useApi<Info>('/api/deployment/info')
  const res = useApi<Res>('/api/deployment/resources')
  const smoke = useApi<Smoke>('/api/deployment/smoke', { interval: 20000 })
  const [ready, setReady] = useState<Ready | null>(null)
  const [busy, setBusy] = useState(false)
  const check = useCallback(async (fresh: boolean) => {
    setBusy(true)
    try {
      const r = await fetch(`/readyz${fresh ? '?fresh=1' : ''}`)
      setReady((await r.json()) as Ready)
    } finally {
      setBusy(false)
    }
  }, [])
  useEffect(() => void check(false), [check])

  return (
    <Page title="IaC & deployment" subtitle="Bicep + azd, keyless managed-identity wiring and live dependency checks of this running instance.">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Runtime" right={meta.data && <Badge tone={meta.data.mode === 'azure' ? 'ok' : 'mute'}>{meta.data.mode}</Badge>}>
          {!meta.data ? <Spinner /> : (
            <>
              <Kv k="Application" v={`${meta.data.name} v${meta.data.version}`} />
              <Kv k="Build" v={meta.data.build_id} />
              <Kv k="Region" v={meta.data.region} />
              <Kv k="Uptime" v={`${Math.round(meta.data.uptime_s / 60)} min`} />
              <Kv k="Chat model deployment" v={meta.data.models.chat} />
              <Kv k="Reasoning model deployment" v={meta.data.models.reasoning} />
              <Kv k="Repository" v={meta.data.persistence.repository} />
              <Kv k="Blob store" v={meta.data.persistence.blobs} />
            </>
          )}
        </Card>
        <Card title="Dependency readiness (/readyz)" right={<Button size="sm" disabled={busy} onClick={() => void check(true)}>Re-check now</Button>}>
          {!ready ? <Spinner /> : (
            <div className="space-y-2">
              <div className="flex items-center gap-2"><Badge tone={ready.status === 'ready' ? 'ok' : 'bad'}>{ready.status}</Badge><span className="text-xs text-mute">{ready.time}</span></div>
              {Object.entries(ready.checks).map(([k, c]) => (
                <div key={k} className="flex items-center justify-between rounded-lg border border-line bg-panel2/50 px-3 py-2">
                  <div>
                    <div className="font-medium capitalize">{k === 'openai' ? 'Azure OpenAI' : k === 'cosmos' ? 'Cosmos DB' : 'Blob storage'}</div>
                    <div className="text-xs text-mute">{c.backend}{c.model ? ` · ${c.model}` : ''}{c.error ? ` · ${c.error}` : ''}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="tabnum text-xs text-mute">{c.latency_ms != null ? `${Math.round(c.latency_ms)} ms` : ''}{c.cached ? ' (cached)' : ''}</span>
                    <Badge tone={c.status === 'ok' ? 'ok' : 'bad'}>{c.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Infrastructure as code">
          {info.data ? (
            <>
              <Kv k="Tool" v={`${info.data.iac.tool} (${info.data.iac.scope} scope)`} />
              <Kv k="Modules" v={info.data.iac.modules.join(' · ')} />
              <Kv k="Image build" v={info.data.iac.remote_build} />
              <Kv k="Resource group" v={info.data.resource_group || '-'} />
              <Kv k="Container app / revision" v={`${info.data.container_app || '-'} / ${info.data.revision || '-'}`} />
              <div className="mt-2 space-y-1 text-[12px]">{Object.entries(info.data.iac.commands).map(([k, v]) => <div key={k} className="flex justify-between gap-3"><span className="text-mute">{k}</span><Mono>{v}</Mono></div>)}</div>
            </>
          ) : <Spinner />}
        </Card>
        <Card title="Security posture (keyless)">
          {info.data ? Object.entries(info.data.security).map(([k, v]) => <Kv key={k} k={k.replace(/_/g, ' ')} v={<span className="text-[12px]">{v}</span>} />) : <Spinner />}
        </Card>
      </div>
      <Card title={`Deployed resources${res.data?.resource_group ? ` · ${res.data.resource_group}` : ''}`} pad={false} right={res.data?.tags && <span className="flex flex-wrap gap-1">{Object.entries(res.data.tags).map(([k, v]) => <Badge key={k} tone="mute">{k}={v}</Badge>)}</span>}>
        {!res.data?.available ? <div className="p-4"><Empty>{res.data?.reason ?? 'Loading…'} (inventory is read from Azure Resource Manager with the app's managed identity.)</Empty></div> : (
          <Table head={['Resource', 'Type', 'SKU', 'Location', 'Governance tags']}>
            {res.data.resources.map((r) => <tr key={r.name}><Td className="font-mono text-[12px]">{r.name}</Td><Td className="text-[12px]">{r.provider.replace('Microsoft.', '')}/{r.type}</Td><Td className="text-[12px] text-mute">{r.sku ?? '-'}</Td><Td className="text-[12px] text-mute">{r.location}</Td><Td className="text-[11px] text-mute">{Object.entries(r.tags).map(([k, v]) => `${k}=${v}`).join(', ') || <span className="text-warn">untagged</span>}</Td></tr>)}
          </Table>
        )}
      </Card>
      <Card title="Smoke test results (scripts/smoke_test.py against this deployment)" pad={false} right={smoke.data?.reported_at && <span className="flex items-center gap-2 text-[11px] text-mute"><Badge tone={smoke.data.failed ? 'bad' : 'ok'}>{smoke.data.passed} pass / {smoke.data.failed} fail</Badge>{smoke.data.reported_at}</span>}>
        {!smoke.data?.results.length ? <div className="p-4"><Empty>{smoke.data?.note ?? 'No smoke test has reported yet.'}</Empty></div> : (
          <Table head={['Check', 'Result', 'Detail', 'ms']}>
            {smoke.data.results.map((r, i) => <tr key={i}><Td>{r.name}</Td><Td><Badge tone={r.status === 'PASS' ? 'ok' : 'bad'}>{r.status}</Badge></Td><Td className="max-w-[520px] truncate text-[12px] text-mute">{r.detail}</Td><Td className="tabnum text-mute">{r.ms != null ? Math.round(r.ms) : ''}</Td></tr>)}
          </Table>
        )}
      </Card>
    </Page>
  )
}
