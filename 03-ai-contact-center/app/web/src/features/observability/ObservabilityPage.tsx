import { Activity, FileCheck2, Gauge } from 'lucide-react'
import { useState } from 'react'
import { fmt, useApi } from '../../lib/api'
import { BarSeries } from '../../lib/charts'
import { Badge, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat, Tabs } from '../../lib/ui'

interface Slo { id: string; name: string; unit: string; p50_target: number; p95_target: number; objective: number; note: string; samples: number; p50: number | null; p95: number | null; max: number | null; burn_rate: number; status: string; p50_ok: boolean | null; p95_ok: boolean | null }
interface SloRes { slos: Slo[]; mode: string; window: string; burn_definition: string }
interface Metering { budget: { day: string; budget_usd: number; spent_usd: number; remaining_usd: number; budget_pct: number; status: string; blocked_calls: number }; by_model: Record<string, { calls: number; input_tokens: number; output_tokens: number; audio_seconds: number; cost_usd: number }>; by_feature: Record<string, { calls: number; cost_usd: number; latency_p50_ms: number; latency_p95_ms: number }>; conversations: { conversation_id: string; channel: string; status: string; tool_calls: number; input_tokens: number; output_tokens: number; audio_seconds: number; calls: number; cost_usd: number }[]; completeness: { pct: number; ended_conversations_with_ai: number; metered: number }; cost_per_resolved_contact_usd: number | null; avg_cost_per_conversation_usd: number | null }
interface Pricing { comparison: { model: string; meter_in: number; meter_out: number; business_case_global_in: number; business_case_global_out: number; business_case_datazone_in: number; business_case_datazone_out: number }[]; note: string; meter: { retrieved: string; source: string } }
interface Span { span_id: string; parent: string | null; name: string; start: number; duration_ms: number; attrs: Record<string, unknown> }
interface Trace { trace_id: string; name: string; start: number; duration_ms: number; attrs: Record<string, unknown>; spans: Span[] }
interface Redaction { input: string; logged: Record<string, unknown>; leaks: string[]; passed: boolean }
interface Health { version: string; build: string; mode: string; region: string; uptime_s: number; readyz: Record<string, { ok: boolean; latency_ms?: number }> | null; seed: string; telemetry: { application_insights: boolean; exporter: string; log_analytics_cap: string }; repository: string }

export default function ObservabilityPage() {
  const [tab, setTab] = useState('slo')
  return (
    <div>
      <PageHeader icon={Activity} title="Observability & FinOps" subtitle="Latency SLOs with burn, per-interaction metering with an estimated cost per resolved contact, traces from the voice relay to the model, PII-safe logs and the daily AI budget guard (fails closed)." />
      <Tabs tabs={[{ id: 'slo', label: 'SLOs' }, { id: 'cost', label: 'Metering & FinOps' }, { id: 'traces', label: 'Traces' }, { id: 'ops', label: 'Health & logs' }]} value={tab} onChange={setTab} />
      {tab === 'slo' && <SloTab />}
      {tab === 'cost' && <CostTab />}
      {tab === 'traces' && <TracesTab />}
      {tab === 'ops' && <OpsTab />}
    </div>
  )
}

function SloTab() {
  const s = useApi<SloRes>('/api/observability/slo', { refreshMs: 15000 })
  if (s.loading && !s.data) return <Spinner />
  if (s.error || !s.data) return <ErrorBox error={s.error} />
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">Mode: {s.data.mode} · {s.data.window}. {s.data.burn_definition}</p>
      <div className="grid gap-4 md:grid-cols-2">
        {s.data.slos.map((x) => (
          <Card key={x.id} title={x.name} subtitle={x.note} actions={<Badge tone={x.status === 'ok' ? 'green' : x.status === 'no data' ? 'slate' : 'red'}>{x.status} · burn {x.burn_rate}</Badge>}>
            <div className="mb-3 grid grid-cols-3 gap-2 text-center"><div><div className="text-xl font-semibold tabular-nums">{fmt.ms(x.p50)}</div><div className="text-[11px] text-slate-500">p50 (target ≤ {fmt.ms(x.p50_target)})</div></div><div><div className={`text-xl font-semibold tabular-nums ${x.p95_ok === false ? 'text-rose-600' : ''}`}>{fmt.ms(x.p95)}</div><div className="text-[11px] text-slate-500">p95 (target ≤ {fmt.ms(x.p95_target)})</div></div><div><div className="text-xl font-semibold tabular-nums">{x.samples}</div><div className="text-[11px] text-slate-500">samples</div></div></div>
            <Progress value={x.p95 ?? 0} max={x.p95_target * 1.5} tone={x.p95_ok === false ? 'red' : 'green'} />
            <div className="mt-1 flex justify-between text-[10px] text-slate-400"><span>0</span><span>target p95 {fmt.ms(x.p95_target)}</span><span>{fmt.ms(x.p95_target * 1.5)}</span></div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function CostTab() {
  const m = useApi<Metering>('/api/observability/metering', { refreshMs: 15000 })
  const p = useApi<Pricing>('/api/observability/pricing')
  if (m.loading && !m.data) return <Spinner />
  if (m.error || !m.data) return <ErrorBox error={m.error} />
  const d = m.data
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Daily AI budget" value={`$${d.budget.spent_usd.toFixed(2)} / $${d.budget.budget_usd}`} hint={`${d.budget.budget_pct}% · ${d.budget.status}`} tone={d.budget.status === 'ok' ? 'green' : 'amber'} icon={Gauge} />
        <Stat label="Blocked by budget guard" value={d.budget.blocked_calls} hint="fails closed with a UI message" />
        <Stat label="Metering completeness" value={`${d.completeness.pct}%`} hint={`${d.completeness.metered}/${d.completeness.ended_conversations_with_ai} conversations`} tone="green" />
        <Stat label="Cost / resolved contact" value={d.cost_per_resolved_contact_usd != null ? `$${d.cost_per_resolved_contact_usd}` : '—'} />
        <Stat label="Avg cost / conversation" value={d.avg_cost_per_conversation_usd != null ? `$${d.avg_cost_per_conversation_usd}` : '—'} />
      </div>
      <Progress value={d.budget.spent_usd} max={d.budget.budget_usd} tone={d.budget.budget_pct > 80 ? 'red' : 'blue'} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Spend by model" pad={false}><DataTable dense rows={Object.entries(d.by_model).map(([k, v]) => ({ k, ...v }))} rowKey={(r) => r.k} empty="No AI calls yet today." cols={[{ key: 'k', header: 'Model', render: (r) => <span className="font-mono text-xs">{r.k}</span> }, { key: 'c', header: 'Calls', align: 'right', render: (r) => r.calls }, { key: 'i', header: 'In tok', align: 'right', render: (r) => fmt.num(r.input_tokens) }, { key: 'o', header: 'Out tok', align: 'right', render: (r) => fmt.num(r.output_tokens) }, { key: 'u', header: 'USD', align: 'right', render: (r) => `$${r.cost_usd}` }]} /></Card>
        <Card title="Latency by feature (LLM calls)"><BarSeries data={Object.entries(d.by_feature).map(([k, v]) => ({ feature: k, p50: v.latency_p50_ms, p95: v.latency_p95_ms }))} x="feature" bars={[{ key: 'p50' }, { key: 'p95', color: '#d97706' }]} height={220} yFmt={(v) => `${v} ms`} /></Card>
      </div>
      <Card title="Per-interaction metering" subtitle="tokens, audio seconds, tool calls and estimated $ per conversation" pad={false}><DataTable dense rows={d.conversations} rowKey={(c) => c.conversation_id} empty="No conversations." cols={[{ key: 'c', header: 'Conversation', render: (c) => <span className="font-mono text-xs">{c.conversation_id}</span> }, { key: 'h', header: 'Channel', render: (c) => c.channel }, { key: 's', header: 'Status', render: (c) => <Badge>{c.status}</Badge> }, { key: 'l', header: 'LLM calls', align: 'right', render: (c) => c.calls }, { key: 't', header: 'Tool calls', align: 'right', render: (c) => c.tool_calls }, { key: 'i', header: 'Tokens in/out', align: 'right', render: (c) => `${fmt.num(c.input_tokens)} / ${fmt.num(c.output_tokens)}` }, { key: 'a', header: 'Audio s', align: 'right', render: (c) => c.audio_seconds }, { key: 'u', header: 'Est. $', align: 'right', render: (c) => `$${c.cost_usd}` }]} /></Card>
      {p.data && <Card title="Unit prices: live meter vs business case" subtitle={p.data.note} pad={false}><DataTable dense rows={p.data.comparison} rowKey={(r) => r.model} cols={[{ key: 'm', header: 'Model (USD / 1M tokens)', render: (r) => <span className="font-mono text-xs">{r.model}</span> }, { key: 'a', header: 'Meter in / out', align: 'right', render: (r) => `${r.meter_in} / ${r.meter_out}` }, { key: 'b', header: 'Business case global', align: 'right', render: (r) => `${r.business_case_global_in} / ${r.business_case_global_out}` }, { key: 'c', header: 'Business case EU Data Zone', align: 'right', render: (r) => `${r.business_case_datazone_in} / ${r.business_case_datazone_out}` }]} /></Card>}
    </div>
  )
}

function TracesTab() {
  const [kind, setKind] = useState('voice')
  const t = useApi<{ traces: Trace[]; exported_to_app_insights: boolean; hint: string }>(`/api/observability/traces?kind=${kind}`, { refreshMs: 8000, deps: [kind] })
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">{['voice', 'chat'].map((k) => <button key={k} type="button" onClick={() => setKind(k)} className={`rounded-lg px-3 py-1.5 text-sm font-medium ${kind === k ? 'bg-blue-600 text-white' : 'bg-white text-slate-700 ring-1 ring-slate-200'}`}>{k}</button>)}<span className="text-xs text-slate-500">{t.data?.hint} · App Insights export: {t.data?.exported_to_app_insights ? 'on' : 'off (offline)'}</span></div>
      {!t.data?.traces.length ? <Empty>No {kind} traces yet — have a {kind === 'voice' ? 'call' : 'chat'} first.</Empty> : t.data.traces.slice(0, 6).map((tr) => (
        <Card key={tr.trace_id} title={`${tr.name} · ${tr.trace_id}`} subtitle={`${fmt.ms(tr.duration_ms)} · ${Object.entries(tr.attrs).map(([k, v]) => `${k}=${String(v)}`).join(' ')}`}>
          <ul className="space-y-1">{tr.spans.map((s) => <li key={s.span_id} className="flex items-center gap-2 text-xs"><span className={`w-56 shrink-0 truncate font-mono ${s.parent ? 'pl-4 text-slate-600' : 'font-semibold text-slate-900'}`}>{s.name}</span><div className="h-2 flex-1 rounded bg-slate-100"><div className="h-2 rounded bg-blue-500" style={{ width: `${Math.max(2, Math.min(100, (s.duration_ms / Math.max(tr.duration_ms, 1)) * 100))}%` }} /></div><span className="w-16 text-right tabular-nums">{fmt.ms(s.duration_ms)}</span></li>)}</ul>
        </Card>
      ))}
    </div>
  )
}

function OpsTab() {
  const h = useApi<Health>('/api/observability/health', { refreshMs: 20000 })
  const r = useApi<Redaction>('/api/observability/log-redaction')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Health" subtitle="/healthz is dependency-free; /readyz checks Cosmos DB, Storage, Azure OpenAI and Azure AI services">
        {!h.data ? <Spinner /> : <><div className="grid grid-cols-2 gap-2 text-sm"><div><span className="text-slate-500">version</span> {h.data.version} · {h.data.build}</div><div><span className="text-slate-500">mode</span> {h.data.mode} · {h.data.region}</div><div><span className="text-slate-500">uptime</span> {fmt.dur(h.data.uptime_s)}</div><div><span className="text-slate-500">seed</span> {h.data.seed}</div></div>
          <div className="mt-3 flex flex-wrap gap-1.5">{Object.entries(h.data.readyz ?? {}).map(([k, v]) => <Badge key={k} tone={v.ok ? 'green' : 'red'}>{k} {v.latency_ms != null ? `${Math.round(v.latency_ms)} ms` : ''}</Badge>)}</div>
          <p className="mt-3 text-xs text-slate-500"><FileCheck2 size={12} className="mr-1 inline" aria-hidden />Telemetry: {h.data.telemetry.exporter}; Log Analytics cap {h.data.telemetry.log_analytics_cap}.</p></>}
      </Card>
      <Card title="Logs contain no PII / PCI" subtitle="self-test of the structured-log formatter" actions={r.data && <Badge tone={r.data.passed ? 'green' : 'red'}>{r.data.passed ? 'no leaks' : 'LEAK'}</Badge>}>
        {!r.data ? <Spinner /> : <div className="space-y-2 text-xs"><div><div className="mb-0.5 text-slate-500">input</div><p className="rounded-lg bg-slate-50 p-2">{r.data.input}</p></div><div><div className="mb-0.5 text-slate-500">what is logged</div><pre className="scroll-thin overflow-auto rounded-lg bg-slate-900 p-2 text-slate-100">{JSON.stringify(r.data.logged, null, 1)}</pre></div></div>}
      </Card>
    </div>
  )
}
