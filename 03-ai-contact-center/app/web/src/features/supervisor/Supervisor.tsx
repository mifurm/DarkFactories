import { AlertTriangle, BellRing, Eye, Flame, MessageSquareWarning, Radio, Users, Zap } from 'lucide-react'
import { useState } from 'react'
import { N_, useI18n } from '../../i18n'
import { api, describeError, useApi, useEventStream } from '../../lib/api'
import { Badge, Button, Card, DataTable, Dot, Empty, ErrorBox, PageHeader, Progress, Spinner, Stat, cx, inputCls, sentimentBg, sentimentTone } from '../../lib/ui'

interface QueueRow { queue: string; name: string; waiting: number; with_human: number; longest_wait_s: number; sla_s: number; sla_clock_pct: number; projected_wait_s: number; agents_available: number; agents_capable: number; abandons_1h: number; state: 'ok' | 'at_risk' | 'breach' }
interface Alert { id: string; queue: string; name: string; severity: string; raised_at: number; cleared_at: number | null; reason: string }
interface Conv { id: string; customer: string | null; channel: string; status: string; handler: string; queue: string | null; intent: string | null; sentiment: number; emotion: string; language: string; assigned_agent: string | null; risk_flags: string[]; messages: number; updated_at: number; last_customer_text: string; sim: boolean }
interface Approval { id: string; kind: string; amount: number; currency?: string; order_id: string | null; conv_id: string; reason: string; status: string }
interface Worker { id: string; name: string; presence: string; active: number; languages: string[] }
interface Overview { ts: number; queues: QueueRow[]; alerts: Alert[]; alert_history: Alert[]; conversations: Conv[]; heat_map: { key: string; queue?: string | null; label?: string; counts: Record<string, number>; total: number }[]; containment: { live_ai: number; live_waiting: number; live_with_human: number; ended: number; ai_contained: number; containment_pct: number | null; avg_sentiment: number | null }; approvals: Approval[]; workers: Worker[] }

const EMOTIONS = ['angry', 'frustrated', 'anxious', 'neutral', 'satisfied']
const EMO_BG: Record<string, string> = { angry: '#fecaca', frustrated: '#fde68a', anxious: '#fed7aa', neutral: '#e2e8f0', satisfied: '#bbf7d0' }
const STATE_TONE = { ok: 'green', at_risk: 'amber', breach: 'red' } as const
const PRESENCE = [N_('available'), N_('busy'), N_('offline')]

export default function Supervisor() {
  const { t, tn, te, tl, ts, fmt } = useI18n()
  const ov = useApi<Overview>('/api/supervisor/overview', { refreshMs: 4000 })
  const [sel, setSel] = useState<Conv | null>(null)
  const [note, setNote] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(0)
  useEventStream(['supervisor'], () => { setLive((n) => n + 1); ov.reload() })

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try { await fn(); setFlash(ok); ov.reload() } catch (e) { setFlash(t('Error: {error}', { error: describeError(e) })) } finally { setBusy(false) }
  }
  const o = ov.data
  return (
    <div>
      <PageHeader icon={Users} title={t('Supervisor console')} subtitle={t('One live view of AI + human work: queues with SLA clocks, active conversations, sentiment, SLA-risk alerts and the levers to intervene.')}
        actions={<><Badge tone="green"><Dot pulse /> {tn(live, { one: 'live feed · {n} event', other: 'live feed · {n} events' })}</Badge><Button variant="primary" icon={Zap} busy={busy} onClick={() => act(() => api('/api/supervisor/demo-traffic', { body: { count: 4 } }), t('Started 4 scripted customers asking for a human.'))}>{t('Demo traffic')}</Button><Button onClick={() => act(() => api('/api/supervisor/demo-traffic/clear', { method: 'POST' }), t('Demo conversations closed.'))}>{t('Clear demo')}</Button></>} />
      {flash && <div role="status" className="mb-3 rounded-xl bg-blue-50 px-3 py-2 text-sm text-blue-800 ring-1 ring-blue-200">{flash}</div>}
      {ov.loading && !o ? <Spinner /> : ov.error ? <ErrorBox error={ov.error} onRetry={ov.reload} /> : o && (
        <>
          {o.alerts.length > 0 && (
            <div className="mb-4 space-y-2" role="alert">
              {o.alerts.map((a) => <div key={a.id} className={cx('flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm ring-1', a.severity === 'critical' ? 'bg-rose-50 text-rose-800 ring-rose-200' : 'bg-amber-50 text-amber-900 ring-amber-200')}><BellRing size={16} aria-hidden className="shrink-0" /><b>{t('SLA risk · {name}', { name: tl('queue', a.queue, a.name) })}</b><span>{a.reason}</span></div>)}
            </div>
          )}
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label={t('AI handling now')} value={o.containment.live_ai} icon={Radio} />
            <Stat label={t('Waiting for a human')} value={o.containment.live_waiting} tone={o.containment.live_waiting ? 'amber' : undefined} icon={MessageSquareWarning} />
            <Stat label={t('With a human')} value={o.containment.live_with_human} icon={Users} />
            <Stat label={t('AI containment')} value={o.containment.containment_pct != null ? fmt.percentValue(o.containment.containment_pct) : '—'} hint={t('{contained}/{ended} ended', { contained: o.containment.ai_contained, ended: o.containment.ended })} />
            <Stat label={t('Pending approvals')} value={o.approvals.length} tone={o.approvals.length ? 'amber' : undefined} icon={AlertTriangle} />
          </div>
          <div className="grid gap-4 2xl:grid-cols-3">
            <Card className="2xl:col-span-2" title={t('Queues & SLA clocks')} subtitle={t('longest wait vs SLA, projected wait for the next arrival')} pad={false}>
              <DataTable dense rows={o.queues} rowKey={(q) => q.queue} cols={[
                { key: 'q', header: t('Queue'), render: (q) => <span className="font-medium">{tl('queue', q.queue, q.name)}</span> },
                { key: 'w', header: t('Waiting'), align: 'right', render: (q) => q.waiting },
                { key: 'h', header: t('With human'), align: 'right', render: (q) => q.with_human },
                { key: 'l', header: t('Longest wait'), render: (q) => <div className="w-32"><div className="mb-0.5 text-xs tabular-nums">{fmt.dur(q.longest_wait_s)} / {fmt.secs(q.sla_s)}</div><Progress value={q.longest_wait_s} max={q.sla_s} tone={q.state === 'breach' ? 'red' : q.state === 'at_risk' ? 'amber' : 'blue'} /></div> },
                { key: 'p', header: t('Projected'), align: 'right', render: (q) => fmt.dur(q.projected_wait_s) },
                { key: 'a', header: t('Agents'), align: 'right', render: (q) => `${q.agents_available}/${q.agents_capable}` },
                { key: 's', header: t('State'), render: (q) => <Badge tone={STATE_TONE[q.state]}>{te('queueState', q.state)}</Badge> },
              ]} />
            </Card>
            <Card title={t('Sentiment heat map')} subtitle={t('active conversations by handler and emotion')}>
              {!o.heat_map.length ? <Empty>{t('No active conversations.')}</Empty> : (
                <table className="w-full text-xs"><thead><tr><th className="pb-1 text-left font-medium text-slate-500">{t('handler')}</th>{EMOTIONS.map((e) => <th key={e} className="pb-1 font-medium text-slate-500" title={te('emotion', e)}>{te('emotionShort', e)}</th>)}</tr></thead>
                  <tbody>{o.heat_map.map((r) => <tr key={r.key}><td className="py-0.5 pr-2 font-medium text-slate-700">{r.queue ? tl('queue', r.queue, r.label ?? r.key) : ts(r.label ?? r.key)}</td>{EMOTIONS.map((e) => <td key={e} className="p-0.5 text-center"><div className="rounded-md py-1.5 font-semibold tabular-nums" style={{ background: r.counts[e] ? EMO_BG[e] : '#f8fafc', color: r.counts[e] ? '#0f172a' : '#cbd5e1' }}>{r.counts[e] ?? 0}</div></td>)}</tr>)}</tbody></table>
              )}
            </Card>
          </div>
          <div className="mt-4 grid gap-4 2xl:grid-cols-3">
            <Card className="2xl:col-span-2" title={t('Active conversations ({count})', { count: o.conversations.length })} pad={false}>
              <DataTable dense rows={o.conversations} rowKey={(c) => c.id} selected={sel?.id} onRowClick={setSel} empty={t('No active conversations - press “Demo traffic”.')} cols={[
                { key: 'c', header: t('Customer'), render: (c) => <span className="font-medium">{c.customer ?? t('anonymous')}</span> },
                { key: 'h', header: t('Handler'), render: (c) => <Badge tone={c.handler === 'ai' ? 'violet' : c.handler === 'queue' ? 'amber' : 'green'}>{c.handler === 'ai' ? 'AI' : c.handler === 'queue' ? t('queue · {queue}', { queue: te('queue', c.queue) }) : t('human · {agent}', { agent: c.assigned_agent })}</Badge> },
                { key: 'i', header: t('Intent'), render: (c) => <span className="text-xs text-slate-600">{c.intent ? te('intent', c.intent) : '—'} · {c.language.toUpperCase()}</span> },
                { key: 's', header: t('Sentiment'), render: (c) => <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded" style={{ background: sentimentBg(c.sentiment) }} /><Badge tone={sentimentTone(c.sentiment)}>{te('emotion', c.emotion)}</Badge></span> },
                { key: 'r', header: t('Risk'), render: (c) => c.risk_flags.map((r) => <Badge key={r} tone="red">{te('risk', r)}</Badge>) },
                { key: 't', header: t('Last customer message'), render: (c) => <span data-user-content data-allow-clip title={c.last_customer_text} className="line-clamp-1 max-w-[260px] text-xs text-slate-500">{c.last_customer_text}</span> },
              ]} />
            </Card>
            <div className="space-y-4">
              <Card title={sel ? t('Intervene · {who}', { who: sel.customer ?? sel.id }) : t('Interventions')} subtitle={t('take over · whisper · monitor / barge (voice simulated)')}>
                {!sel ? <Empty>{t('Select a conversation.')}</Empty> : (
                  <div className="space-y-2">
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="primary" disabled={busy || sel.handler === 'human'} onClick={() => act(() => api(`/api/supervisor/${sel.id}/takeover`, { body: {} }), t('Took over - history is intact for the new handler.'))}>{t('Take over')}</Button>
                      <Button size="sm" icon={Eye} disabled={busy} onClick={() => act(() => api(`/api/supervisor/${sel.id}/monitor`, { body: { mode: 'listen' } }), t('Silent monitor started (audited).'))}>{t('Monitor')}</Button>
                      <Button size="sm" disabled={busy} onClick={() => act(() => api(`/api/supervisor/${sel.id}/monitor`, { body: { mode: 'barge' } }), t('Barge-in requested (voice is simulated).'))}>{t('Barge')}</Button>
                    </div>
                    <div className="flex gap-2"><input aria-label={t('Whisper to the agent')} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('Whisper (agent / AI only, never the customer)…')} className={inputCls} /><Button size="sm" disabled={!note.trim() || busy} onClick={() => act(async () => { await api(`/api/assist/${sel.id}/whisper`, { body: { text: note, agent_id: 'AG-08' } }); setNote('') }, t('Whisper delivered (audited).'))}>{t('Whisper')}</Button></div>
                  </div>
                )}
              </Card>
              <Card title={t('Approvals above the cap ({count})', { count: o.approvals.length })}>
                {!o.approvals.length ? <p className="text-sm text-slate-500">{t('None pending. Ask for a {amount} refund on the damaged mattress (CU-1004) to create one.', { amount: fmt.eur(900, 0) })}</p> : (
                  <ul className="space-y-2">{o.approvals.map((a) => <li key={a.id} className="rounded-xl border border-amber-200 bg-amber-50 p-2.5 text-sm"><div className="flex items-center justify-between gap-2"><b>{te('approvalKind', a.kind)} {fmt.money(a.amount, a.currency)}</b><span className="text-xs text-slate-500">{a.order_id}</span></div><p className="text-xs text-slate-600">{a.reason}</p><div className="mt-2 flex gap-2"><Button size="sm" variant="success" onClick={() => act(() => api(`/api/tools/approvals/${a.id}/decision`, { body: { approve: true, note: t('approved by supervisor') } }), t('Approved - action executed and audited.'))}>{t('Approve')}</Button><Button size="sm" variant="danger" onClick={() => act(() => api(`/api/tools/approvals/${a.id}/decision`, { body: { approve: false, note: t('declined') } }), t('Declined - nothing was executed.'))}>{t('Deny')}</Button></div></li>)}</ul>
                )}
              </Card>
            </div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card title={t('Agents & presence')} subtitle={t('set an agent offline to watch the SLA-risk alert fire')}>
              <ul className="grid grid-cols-1 gap-1.5 2xl:grid-cols-2">
                {o.workers.map((w) => (
                  <li key={w.id} className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 px-2.5 py-1.5 text-sm">
                    <span className="flex min-w-0 items-center gap-2"><Dot tone={w.presence === 'available' ? 'green' : w.presence === 'busy' ? 'amber' : 'slate'} /><span className="truncate">{w.name}</span><span className="text-[11px] text-slate-400">{w.languages.join('/')}</span></span>
                    <select aria-label={t('Presence of {name}', { name: w.name })} value={w.presence} onChange={(e) => act(() => api(`/api/supervisor/workers/${w.id}/presence`, { method: 'POST', body: { presence: e.target.value } }), t('{name} is now {presence}.', { name: w.name, presence: te('presence', e.target.value) }))} className="rounded-md border border-slate-200 bg-white px-1 py-0.5 text-xs">{PRESENCE.map((p) => <option key={p} value={p}>{te('presence', p)}</option>)}</select>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title={t('Alert history')} subtitle={t('raised → cleared')}>
              {!o.alert_history.length ? <p className="text-sm text-slate-500">{t('No alerts raised yet. Set the relevant agents offline and start demo traffic to raise one.')}</p> : <ul className="space-y-1.5 text-sm">{o.alert_history.map((a) => <li key={a.id} className="flex items-center gap-2"><Flame size={13} className="text-amber-600" aria-hidden /><b>{tl('queue', a.queue, a.name)}</b><span className="text-xs text-slate-500">{fmt.time(a.raised_at)} → {fmt.time(a.cleared_at)}</span></li>)}</ul>}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
