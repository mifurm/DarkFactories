import { Bars } from '../../components/charts'
import { Meter } from '../../components/bits'
import { Badge, Card, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { useApi } from '../../lib/api'
import { fmt } from '../../lib/feature'

type FeatureM = { count: number; errors_5xx: number; p50_ms: number; p95_ms: number; mean_ms: number }
type M = { uptime_s: number; features: Record<string, FeatureM>; requests_total?: number; errors_total?: number; agent_decisions: Record<string, { cycles: number; proposals: number; executed: number; vetoed: number; errors: number; p50_ms: number; p95_ms: number }>; sse_subscribers: number; events_published: number; otel: { app_insights: boolean; auth: string; mode: string } }
type Bucket = { calls: number; tokens_in: number; tokens_out: number; cost_usd: number; latency_ms: number }
type F = { usage: { est_cost_usd: number; daily_budget_usd: number; remaining_usd: number; budget_blocked: boolean; calls: number; errors: number; tokens_in: number; tokens_out: number; by_feature?: Record<string, Bucket>; by_model?: Record<string, Bucket> }; guard: { daily_budget_usd: number; remaining_usd: number; blocked: boolean; fails_closed: boolean; behaviour: string }; hint: string }
type H = { ready: { status: string; checks: Record<string, { status: string; latency_ms?: number; backend?: string }> }; write_behind: { queued: number; written: number; failed: number; dropped: number }; plants: Record<string, { t: number; paused: boolean; speed: number; ledger: number; ledger_ok: boolean; agents_enabled: number }> }

export default function Observability() {
  const m = useApi<M>('/api/observability/metrics', { interval: 4000 })
  const f = useApi<F>('/api/observability/finops', { interval: 6000 })
  const h = useApi<H>('/api/observability/health', { interval: 6000 })
  const feats = Object.entries(m.data?.features ?? {}).sort((a, b) => b[1].count - a[1].count)
  const total = feats.reduce((a, [, v]) => a + v.count, 0)
  const u = f.data?.usage
  return (
    <Page title="Observability & FinOps" subtitle="Structured JSON logs with request ids, per-feature latency and error counters, agent-decision metrics, OpenTelemetry to Application Insights (managed identity), and a FinOps view of Azure OpenAI spend with a daily budget guard that fails closed.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Uptime" value={`${Math.round((m.data?.uptime_s ?? 0) / 60)} min`} />
        <Stat label="API requests" value={fmt.n(total)} sub={`${feats.reduce((a, [, v]) => a + v.errors_5xx, 0)} server errors`} />
        <Stat label="SSE subscribers" value={m.data?.sse_subscribers ?? 0} sub={`${fmt.n(m.data?.events_published)} events published`} />
        <Stat label="AI spend today (est.)" value={`$${(u?.est_cost_usd ?? 0).toFixed(3)}`} sub={`cap $${u?.daily_budget_usd ?? '-'}`} tone={u?.budget_blocked ? 'bad' : 'info'} />
        <Stat label="App Insights" value={m.data?.otel.app_insights ? 'connected' : 'off'} sub={m.data?.otel.auth} tone={m.data?.otel.app_insights ? 'ok' : 'mute'} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="API latency by feature (ms)" pad={false}>
          <div className="max-h-[360px] overflow-auto">
            <Table head={['Feature', 'Requests', '5xx', 'p50', 'p95', 'mean']}>
              {feats.map(([k, v]) => <tr key={k}><Td className="font-medium">{k}</Td><Td className="tabnum">{v.count}</Td><Td className={`tabnum ${v.errors_5xx ? 'text-bad' : 'text-mute'}`}>{v.errors_5xx}</Td><Td className="tabnum">{v.p50_ms.toFixed(1)}</Td><Td className="tabnum">{v.p95_ms.toFixed(1)}</Td><Td className="tabnum text-mute">{v.mean_ms.toFixed(1)}</Td></tr>)}
            </Table>
          </div>
        </Card>
        <Card title="Agent decision cycle time (ms, p95 across plants)">
          <Bars data={Object.entries(m.data?.agent_decisions ?? {}).map(([k, v]) => ({ agent: k, p95: Number(v.p95_ms.toFixed(1)), p50: Number(v.p50_ms.toFixed(1)) }))} x="agent" bars={[{ key: 'p50', color: '#38bdf8' }, { key: 'p95', color: '#a78bfa' }]} height={230} />
          <Table head={['Agent', 'Cycles', 'Proposals', 'Executed', 'Vetoed', 'Errors']} className="mt-2">
            {Object.entries(m.data?.agent_decisions ?? {}).map(([k, v]) => <tr key={k}><Td className="capitalize">{k}</Td><Td className="tabnum">{v.cycles}</Td><Td className="tabnum">{v.proposals}</Td><Td className="tabnum">{v.executed}</Td><Td className="tabnum">{v.vetoed}</Td><Td className="tabnum">{v.errors}</Td></tr>)}
          </Table>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="FinOps: Azure OpenAI daily budget guard" right={<Badge tone={f.data?.guard.blocked ? 'bad' : 'ok'}>{f.data?.guard.blocked ? 'BLOCKED - deterministic fallback' : 'within budget'}</Badge>}>
          <Meter value={u?.est_cost_usd ?? 0} max={u?.daily_budget_usd || 1} tone={f.data?.guard.blocked ? 'bad' : 'info'} label="AI budget used" />
          <div className="mt-2"><Kv k="Estimated spend today" v={`$${(u?.est_cost_usd ?? 0).toFixed(4)}`} /><Kv k="Daily cap" v={`$${u?.daily_budget_usd}`} /><Kv k="Remaining" v={`$${(u?.remaining_usd ?? 0).toFixed(3)}`} /><Kv k="Calls / tokens in / out" v={`${u?.calls ?? 0} / ${fmt.n(u?.tokens_in)} / ${fmt.n(u?.tokens_out)}`} /></div>
          <Table head={['AI feature', 'Calls', 'Tokens in / out', 'Cost', 'Avg latency']} className="mt-2">
            {Object.entries(u?.by_feature ?? {}).sort((a, b) => b[1].cost_usd - a[1].cost_usd).map(([k, v]) => <tr key={k}><Td>{k}</Td><Td className="tabnum">{v.calls}</Td><Td className="tabnum text-mute">{fmt.n(v.tokens_in)} / {fmt.n(v.tokens_out)}</Td><Td className="tabnum">${(v.cost_usd ?? 0).toFixed(4)}</Td><Td className="tabnum text-mute">{v.calls ? Math.round(v.latency_ms / v.calls) : 0} ms</Td></tr>)}
          </Table>
          <p className="mt-2 text-[11px] text-mute">{f.data?.guard.behaviour}. {f.data?.hint}</p>
        </Card>
        <Card title="Platform health">
          {Object.entries(h.data?.ready.checks ?? {}).map(([k, c]) => <Kv key={k} k={k} v={<span className="flex items-center justify-end gap-2"><span className="text-[11px] text-mute">{c.backend} {c.latency_ms != null ? `· ${Math.round(c.latency_ms)} ms` : ''}</span><Badge tone={c.status === 'ok' ? 'ok' : 'bad'}>{c.status}</Badge></span>} />)}
          <Kv k="Cosmos write-behind (queued / written / failed / dropped)" v={h.data ? `${h.data.write_behind.queued} / ${h.data.write_behind.written} / ${h.data.write_behind.failed} / ${h.data.write_behind.dropped}` : '-'} />
          {Object.entries(h.data?.plants ?? {}).map(([k, p]) => <Kv key={k} k={`${k} sim`} v={<span className="flex items-center justify-end gap-2">t={fmt.n(p.t)} · {p.speed}x · ledger {p.ledger}<Badge tone={p.ledger_ok ? 'ok' : 'bad'}>{p.ledger_ok ? 'chain ok' : 'broken'}</Badge></span>} />)}
        </Card>
      </div>
    </Page>
  )
}
