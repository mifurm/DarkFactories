import { AlertOctagon, BrainCircuit, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { api, fmt, useApi } from '../../lib/api'
import { ComboSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat } from '../../lib/ui'

interface Cluster { id: number; label: string; terms: string[]; volume: number; share: number; sentiment_start: number; sentiment_end: number; csat_pred: number; resolved_pct: number; escalated_pct: number; containment_pct: number; repeat_rate: number; churn_risk_avg: number; churn_high_pct: number; human_minutes: number; cost_usd: number; cost_per_contact_usd: number; dominant_driver: string; driver_purity: number; carriers: Record<string, number>; examples: { id: string; summary: string; text: string; language: string; sentiment: number }[] }
interface AlertT { id: string; severity: string; label: string; message: string; recent_per_day: number; baseline_per_day: number; ratio: number; z: number; carrier: { name: string; share_recent: number; share_baseline: number; lift: number } | null; carriers: { name: string; share_recent: number; share_baseline: number }[]; first_seen: string | null; evidence: string[]; evidence_summaries: string[]; markets: string[]; clusters?: number[] }
interface Voc { records: number; k: number; purity: number; labelled_by: string; embedder: string; computed_ms: number; clusters: Cluster[]; pareto_volume: { id: number; label: string; volume: number; cum_pct: number }[]; pareto_cost: { id: number; label: string; cost_usd: number; cum_pct: number }[]; trend: { week: string; n: number; sentiment: number; negative_pct: number }[]; alerts: AlertT[]; totals: { repeat_rate: number; high_churn_pct: number }; sample_factor: number; cost_per_min_usd: number; k_silhouette: Record<string, number> }
interface Evidence { id: string; date: string; market: string; language: string; carrier: string | null; product: string; summary: string; text: string }

export default function VocPage() {
  const voc = useApi<Voc>('/api/voc/summary')
  const [sel, setSel] = useState<Cluster | null>(null)
  const [evidence, setEvidence] = useState<{ alert: string; rows: Evidence[] } | null>(null)
  const [control, setControl] = useState<{ passed: boolean; records: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const v = voc.data
  const refresh = async () => { setBusy(true); try { await api('/api/voc/refresh', { method: 'POST' }); voc.reload() } finally { setBusy(false) } }
  const showEvidence = async (a: AlertT) => setEvidence({ alert: a.id, rows: await api<Evidence[]>(`/api/voc/evidence?ids=${a.evidence.join(',')}`) })
  const runControl = async () => { setBusy(true); try { setControl(await api('/api/voc/control')) } finally { setBusy(false) } }

  return (
    <div>
      <PageHeader icon={BrainCircuit} title="Voice-of-customer insights" subtitle="Topics discovered by clustering conversation summaries (embeddings), contact-driver Pareto by volume and cost, sentiment trend, repeat/churn signals and emerging-issue alerts from anomaly detection."
        actions={<><Button icon={ShieldCheck} busy={busy} onClick={runControl}>No-spike control</Button><Button variant="primary" icon={RefreshCw} busy={busy} onClick={refresh}>Recompute</Button></>} />
      {voc.loading && !v ? <Spinner /> : voc.error || !v ? <ErrorBox error={voc.error} onRetry={voc.reload} /> : (
        <div className="space-y-4">
          {control && <div role="status" className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200">Control dataset ({control.records} records, same generator without the planted issue): <b>{control.passed ? 'no alert raised ✔' : 'ALERT RAISED ✘'}</b></div>}
          {v.alerts.length === 0 ? <div className="rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-600">No emerging issues detected in the last 7 days.</div> : v.alerts.map((a) => (
            <Card key={a.id} className="border-rose-300 ring-1 ring-rose-200" title={<span className="flex items-center gap-2 text-rose-800"><AlertOctagon size={16} aria-hidden />Emerging issue · {a.label}</span>} subtitle={`${a.severity} · z = ${a.z} · first seen ${a.first_seen ?? '—'}${a.clusters ? ` · ${a.clusters.length} related topic clusters merged` : ''}`} actions={<Button size="sm" onClick={() => showEvidence(a)}>Evidence conversations</Button>}>
              <p className="text-sm text-slate-800">{a.message}</p>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium text-slate-500">Carrier attribution (share of recent contacts vs baseline)</div>
                  {a.carriers.map((c) => <div key={c.name} className="mb-1.5"><div className="flex justify-between text-xs"><b className={c.name === a.carrier?.name ? 'text-rose-700' : ''}>{c.name}</b><span className="tabular-nums">{Math.round(c.share_recent * 100)}% now · {Math.round(c.share_baseline * 100)}% baseline</span></div><Progress value={c.share_recent} tone={c.name === a.carrier?.name ? 'red' : 'blue'} /></div>)}
                </div>
                <div className="text-xs text-slate-600"><div className="mb-1 font-medium text-slate-500">Markets · volume</div>{a.markets.join(', ')} · {a.recent_per_day}/day vs {a.baseline_per_day}/day baseline ({a.ratio}×)<ul className="mt-2 list-disc space-y-0.5 pl-4">{a.evidence_summaries.map((s, i) => <li key={i}>{s}</li>)}</ul></div>
              </div>
              {evidence?.alert === a.id && <div className="mt-3 overflow-x-auto"><DataTable dense rows={evidence.rows} rowKey={(r) => r.id} cols={[{ key: 'i', header: 'Conversation', render: (r) => <span className="font-mono text-xs">{r.id}</span> }, { key: 'd', header: 'Date', render: (r) => r.date }, { key: 'm', header: 'Market', render: (r) => `${r.market} · ${r.language}` }, { key: 'c', header: 'Carrier', render: (r) => r.carrier ?? '—' }, { key: 's', header: 'Summary', render: (r) => <span className="text-xs">{r.summary}</span> }]} /></div>}
            </Card>
          ))}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label="Interaction records" value={fmt.num(v.records)} hint={`synthetic sample 1:${v.sample_factor}`} />
            <Stat label="Topic clusters" value={v.k} hint={`labelled by ${v.labelled_by}`} />
            <Stat label="Cluster purity" value={`${Math.round(v.purity * 100)}%`} hint="vs planted drivers (≥ 80%)" tone={v.purity >= 0.8 ? 'green' : 'amber'} />
            <Stat label="Repeat contacts (7 d)" value={`${(v.totals.repeat_rate * 100).toFixed(1)}%`} />
            <Stat label="High churn-risk" value={`${v.totals.high_churn_pct}%`} />
            <Stat label="Last recompute" value={`${(v.computed_ms / 1000).toFixed(1)} s`} hint={`${v.embedder.split(':')[0]} embeddings · stored aggregate`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Contact-driver Pareto — volume"><ComboSeries data={v.pareto_volume.map((p) => ({ ...p, name: p.label.slice(0, 18) }))} x="name" bars={[{ key: 'volume', name: 'contacts' }]} lines={[{ key: 'cum_pct', name: 'cumulative %' }]} height={260} /></Card>
            <Card title="Contact-driver Pareto — cost" subtitle={`handling minutes × $${v.cost_per_min_usd}/min + metered AI cost`}><ComboSeries data={v.pareto_cost.map((p) => ({ ...p, name: p.label.slice(0, 18) }))} x="name" bars={[{ key: 'cost_usd', name: 'USD', color: '#d97706' }]} lines={[{ key: 'cum_pct', name: 'cumulative %' }]} height={260} /></Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2" title="Topics" subtitle="click a row for example conversations" pad={false}>
              <DataTable dense rows={v.clusters} rowKey={(c) => String(c.id)} selected={sel ? String(sel.id) : undefined} onRowClick={setSel} cols={[
                { key: 'l', header: 'Topic (LLM label)', render: (c) => <span className="font-medium">{c.label}</span> },
                { key: 'v', header: 'Volume', align: 'right', render: (c) => c.volume },
                { key: 's', header: 'Sentiment', align: 'right', render: (c) => c.sentiment_end.toFixed(2) },
                { key: 'r', header: 'Repeat', align: 'right', render: (c) => `${(c.repeat_rate * 100).toFixed(0)}%` },
                { key: 'c', header: 'Churn risk', align: 'right', render: (c) => <Badge tone={c.churn_risk_avg > 0.25 ? 'red' : c.churn_risk_avg > 0.15 ? 'amber' : 'slate'}>{c.churn_risk_avg.toFixed(2)}</Badge> },
                { key: 'k', header: 'Cost', align: 'right', render: (c) => fmt.usd(c.cost_usd, 0) },
                { key: 'd', header: 'Planted driver', render: (c) => <span className="text-xs text-slate-500">{c.dominant_driver} · {Math.round(c.driver_purity * 100)}%</span> },
              ]} />
            </Card>
            <Card title={sel ? sel.label : 'Topic detail'}>
              {!sel ? <Empty>Select a topic.</Empty> : <div className="space-y-2"><div className="flex flex-wrap gap-1">{sel.terms.map((t) => <Badge key={t} tone="blue">{t}</Badge>)}{Object.entries(sel.carriers).map(([k, n]) => <Badge key={k} tone="slate">{k} ×{n}</Badge>)}</div>{sel.examples.map((e) => <div key={e.id} className="rounded-xl bg-slate-50 p-2 text-xs"><div className="mb-0.5 text-slate-500">{e.id} · {e.language}</div><div className="text-slate-800">{e.text}</div></div>)}</div>}
            </Card>
          </div>
          <Card title="Sentiment & negative share by week"><LineSeries data={v.trend} x="week" lines={[{ key: 'negative_pct', name: 'negative contacts %', color: '#dc2626' }]} height={200} yFmt={(x) => `${x}%`} /></Card>
        </div>
      )}
    </div>
  )
}
