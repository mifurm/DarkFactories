import { AlertOctagon, BrainCircuit, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { ellipsize, useI18n, type I18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { ComboSeries, LineSeries } from '../../lib/charts'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat } from '../../lib/ui'

interface Cluster { id: number; label: string; terms: string[]; volume: number; share: number; sentiment_start: number; sentiment_end: number; csat_pred: number; resolved_pct: number; escalated_pct: number; containment_pct: number; repeat_rate: number; churn_risk_avg: number; churn_high_pct: number; human_minutes: number; cost_usd: number; cost_per_contact_usd: number; dominant_driver: string; driver_purity: number; carriers: Record<string, number>; examples: { id: string; summary: string; text: string; language: string; sentiment: number }[] }
interface AlertT { id: string; severity: string; label: string; message: string; recent_per_day: number; baseline_per_day: number; ratio: number; z: number; carrier: { name: string; share_recent: number; share_baseline: number; lift: number } | null; carriers: { name: string; share_recent: number; share_baseline: number }[]; first_seen: string | null; evidence: string[]; evidence_summaries: string[]; markets: string[]; clusters?: number[] }
interface Voc { records: number; k: number; purity: number; labelled_by: string; embedder: string; computed_ms: number; clusters: Cluster[]; pareto_volume: { id: number; label: string; volume: number; cum_pct: number }[]; pareto_cost: { id: number; label: string; cost_usd: number; cum_pct: number }[]; trend: { week: string; n: number; sentiment: number; negative_pct: number }[]; alerts: AlertT[]; totals: { repeat_rate: number; high_churn_pct: number }; sample_factor: number; cost_per_min_usd: number; k_silhouette: Record<string, number> }
interface Evidence { id: string; date: string; market: string; language: string; carrier: string | null; product: string; summary: string; text: string }

/** Cluster labels are generated from the clusters' top terms ("Tracking · Delivery · Eta"): translate the terms, keep anything else. */
const vocLabel = (label: string, i: Pick<I18n, 'tl' | 'lang'>) =>
  i.lang === 'en'
    ? label
    : label
        .split(' · ')
        .map((term) => {
          const tr = i.tl('vocTerm', term.toLowerCase(), term)
          return tr !== term && term[0] === term[0]?.toUpperCase() ? tr.charAt(0).toLocaleUpperCase('pl') + tr.slice(1) : tr
        })
        .join(' · ')

export default function VocPage() {
  const i18n = useI18n()
  const { t, tn, te, tl, fmt, lang } = i18n
  const voc = useApi<Voc>('/api/voc/summary')
  const [sel, setSel] = useState<Cluster | null>(null)
  const [evidence, setEvidence] = useState<{ alert: string; rows: Evidence[] } | null>(null)
  const [control, setControl] = useState<{ passed: boolean; records: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const v = voc.data
  const guard = async (fn: () => Promise<void>) => { setBusy(true); setErr(null); try { await fn() } catch (e) { setErr(describeError(e)) } finally { setBusy(false) } }
  const refresh = () => guard(async () => { await api('/api/voc/refresh', { method: 'POST' }); voc.reload() })
  const showEvidence = (a: AlertT) => guard(async () => setEvidence({ alert: a.id, rows: await api<Evidence[]>(`/api/voc/evidence?ids=${a.evidence.join(',')}`) }))
  const runControl = () => guard(async () => setControl(await api('/api/voc/control')))
  const label = (s: string) => vocLabel(s, i18n)
  const cut = lang === 'pl' ? 24 : 18
  /** English keeps its fixed cut; long Polish names are shortened at a word boundary (…) and the tooltip shows the full name. */
  const shorten = (s: string) => (lang === 'pl' ? ellipsize(s, cut) : s.slice(0, cut))
  const paretoRows = <R extends { label: string }>(rows: R[]) => rows.map((p) => ({ ...p, name: shorten(label(p.label)), full: label(p.label) }))

  /** The English alert text is the server's; Polish is composed from the structured fields. */
  const alertMessage = (a: AlertT) => {
    if (lang === 'en' || !a.carrier) return a.message
    const base = t("“{label}”{related} is running at {recent}/day vs {baseline}/day baseline ({ratio}×) - {carrier} accounts for {share} of the recent contacts (baseline {baseShare}).", {
      label: label(a.label),
      related: a.clusters && a.clusters.length > 1 ? ` (${tn(a.clusters.length - 1, { one: '+{n} related topic cluster', other: '+{n} related topic clusters' })})` : '',
      recent: fmt.plain(a.recent_per_day),
      baseline: fmt.plain(a.baseline_per_day),
      ratio: fmt.plain(a.ratio),
      carrier: a.carrier.name,
      share: fmt.percent(a.carrier.share_recent, 0),
      baseShare: fmt.percent(a.carrier.share_baseline, 0),
    })
    return base
  }

  return (
    <div>
      <PageHeader icon={BrainCircuit} title={t('Voice-of-customer insights')} subtitle={t('Topics discovered by clustering conversation summaries (embeddings), contact-driver Pareto by volume and cost, sentiment trend, repeat/churn signals and emerging-issue alerts from anomaly detection.')}
        actions={<><Button icon={ShieldCheck} busy={busy} onClick={runControl}>{t('No-spike control')}</Button><Button variant="primary" icon={RefreshCw} busy={busy} onClick={refresh}>{t('Recompute')}</Button></>} />
      {err && <div role="alert" className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">{err}</div>}
      {voc.loading && !v ? <Spinner /> : voc.error || !v ? <ErrorBox error={voc.error} onRetry={voc.reload} /> : (
        <div className="space-y-4">
          {control && <div role="status" className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200">{t('Control dataset ({records}, same generator without the planted issue):', { records: tn(control.records, { one: '{n} record', other: '{n} records' }) })} <b>{control.passed ? t('no alert raised ✔') : t('ALERT RAISED ✘')}</b></div>}
          {v.alerts.length === 0 ? <div className="rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-600">{t('No emerging issues detected in the last 7 days.')}</div> : v.alerts.map((a) => (
            <Card key={a.id} className="border-rose-300 ring-1 ring-rose-200" title={<span className="flex items-center gap-2 text-rose-800"><AlertOctagon size={16} aria-hidden />{t('Emerging issue · {label}', { label: label(a.label) })}</span>} subtitle={`${te('severity', a.severity)} · z = ${fmt.plain(a.z)} · ${t('first seen {date}', { date: fmt.isoDate(a.first_seen) })}${a.clusters ? ` · ${tn(a.clusters.length, { one: '{n} related topic cluster merged', other: '{n} related topic clusters merged' })}` : ''}`} actions={<Button size="sm" onClick={() => showEvidence(a)}>{t('Evidence conversations')}</Button>}>
              <p className="text-sm text-slate-800">{alertMessage(a)}</p>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium text-slate-500">{t('Carrier attribution (share of recent contacts vs baseline)')}</div>
                  {a.carriers.map((c) => <div key={c.name} className="mb-1.5"><div className="flex justify-between gap-2 text-xs"><b className={c.name === a.carrier?.name ? 'text-rose-700' : ''}>{c.name}</b><span className="tabular-nums">{t('{now} now · {base} baseline', { now: fmt.percent(c.share_recent, 0), base: fmt.percent(c.share_baseline, 0) })}</span></div><Progress value={c.share_recent} tone={c.name === a.carrier?.name ? 'red' : 'blue'} /></div>)}
                </div>
                <div className="text-xs text-slate-600"><div className="mb-1 font-medium text-slate-500">{t('Markets · volume')}</div>{a.markets.join(', ')} · {t('{recent}/day vs {baseline}/day baseline ({ratio}×)', { recent: fmt.plain(a.recent_per_day), baseline: fmt.plain(a.baseline_per_day), ratio: fmt.plain(a.ratio) })}<ul className="mt-2 list-disc space-y-0.5 pl-4">{a.evidence_summaries.map((s, i) => <li key={i} lang={lang}>{s}</li>)}</ul></div>
              </div>
              {evidence?.alert === a.id && <div className="mt-3 overflow-x-auto"><DataTable dense rows={evidence.rows} rowKey={(r) => r.id} cols={[{ key: 'i', header: t('Conversation'), render: (r) => <span className="font-mono text-xs">{r.id}</span> }, { key: 'd', header: t('Date'), render: (r) => fmt.isoDate(r.date) }, { key: 'm', header: t('Market'), render: (r) => `${r.market} · ${r.language}` }, { key: 'c', header: t('Carrier'), render: (r) => r.carrier ?? '—' }, { key: 's', header: t('Summary'), render: (r) => <span className="text-xs" lang={lang}>{r.summary}</span> }]} /></div>}
            </Card>
          ))}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label={t('Interaction records')} value={fmt.number(v.records)} hint={t('synthetic sample 1:{n}', { n: v.sample_factor })} />
            <Stat label={t('Topic clusters')} value={v.k} hint={t('labelled by {by}', { by: te('vocLabeller', v.labelled_by) })} />
            <Stat label={t('Cluster purity')} value={fmt.percent(v.purity, 0)} hint={t('vs planted drivers (≥ 80%)')} tone={v.purity >= 0.8 ? 'green' : 'amber'} />
            <Stat label={t('Repeat contacts (7 d)')} value={fmt.percent(v.totals.repeat_rate, 1)} />
            <Stat label={t('High churn-risk')} value={fmt.percentValue(v.totals.high_churn_pct)} />
            <Stat label={t('Last recompute')} value={`${fmt.fixed(v.computed_ms / 1000, 1)} s`} hint={t('{embedder} embeddings · stored aggregate', { embedder: v.embedder.split(':')[0] })} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={t('Contact-driver Pareto — volume')}><ComboSeries data={paretoRows(v.pareto_volume)} x="name" fullKey="full" bars={[{ key: 'volume', name: t('contacts') }]} lines={[{ key: 'cum_pct', name: t('cumulative %') }]} height={260} /></Card>
            <Card title={t('Contact-driver Pareto — cost')} subtitle={t('handling minutes × {rate}/min + metered AI cost', { rate: fmt.usd(v.cost_per_min_usd) })}><ComboSeries data={paretoRows(v.pareto_cost)} x="name" fullKey="full" bars={[{ key: 'cost_usd', name: 'USD', color: '#d97706' }]} lines={[{ key: 'cum_pct', name: t('cumulative %') }]} height={260} /></Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2" title={t('Topics')} subtitle={t('click a row for example conversations')} pad={false}>
              <DataTable dense rows={v.clusters} rowKey={(c) => String(c.id)} selected={sel ? String(sel.id) : undefined} onRowClick={setSel} cols={[
                { key: 'l', header: t('Topic (LLM label)'), render: (c) => <span className="font-medium">{label(c.label)}</span> },
                { key: 'v', header: t('Volume'), align: 'right', render: (c) => fmt.number(c.volume) },
                { key: 's', header: t('Sentiment'), align: 'right', render: (c) => fmt.fixed(c.sentiment_end, 2) },
                { key: 'r', header: t('Repeat'), align: 'right', render: (c) => fmt.percent(c.repeat_rate, 0) },
                { key: 'c', header: t('Churn risk'), align: 'right', render: (c) => <Badge tone={c.churn_risk_avg > 0.25 ? 'red' : c.churn_risk_avg > 0.15 ? 'amber' : 'slate'}>{fmt.fixed(c.churn_risk_avg, 2)}</Badge> },
                { key: 'k', header: t('Cost'), align: 'right', render: (c) => fmt.usd(c.cost_usd, 0) },
                { key: 'd', header: t('Planted driver'), render: (c) => <span className="text-xs text-slate-500">{te('vocDriver', c.dominant_driver)} · {fmt.percent(c.driver_purity, 0)}</span> },
              ]} />
            </Card>
            <Card title={sel ? label(sel.label) : t('Topic detail')}>
              {!sel ? <Empty>{t('Select a topic.')}</Empty> : <div className="space-y-2"><div className="flex flex-wrap gap-1">{sel.terms.map((term) => <Badge key={term} tone="blue">{tl('vocTerm', term.toLowerCase(), term)}</Badge>)}{Object.entries(sel.carriers).map(([k, n]) => <Badge key={k} tone="slate">{k} ×{n}</Badge>)}</div>{sel.examples.map((e) => <div key={e.id} className="rounded-xl bg-slate-50 p-2 text-xs"><div className="mb-0.5 text-slate-500">{e.id} · {e.language}</div><div className="text-slate-800" lang={e.language}>{e.text}</div></div>)}</div>}
            </Card>
          </div>
          <Card title={t('Sentiment & negative share by week')}><LineSeries data={v.trend} x="week" xFmt={(w) => fmt.week(w)} lines={[{ key: 'negative_pct', name: t('negative contacts %'), color: '#dc2626' }]} height={200} yFmt={(x) => fmt.percentValue(x)} /></Card>
        </div>
      )}
    </div>
  )
}
