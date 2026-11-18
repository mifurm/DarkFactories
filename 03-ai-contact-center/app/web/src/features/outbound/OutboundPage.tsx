import { Megaphone, OctagonX, Play } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, ErrorBox, PageHeader, Spinner, Stat, cx } from '../../lib/ui'

interface Campaign { id: string; name: string; trigger: string; state: string; caps: { per_customer_7d: number; per_day: number }; quiet_hours: { start: number; end: number } }
interface Decision { id: string; ts: number; campaign_id: string; trigger: string; customer_id: string; market: string; decision: string; reason: string; channel: string | null; scheduled_for: number | null; consent_evidence: Record<string, unknown> | null; checks: string[]; order_id?: string; conversation_id?: string; composed_by?: string; message?: string; released_from?: string }
interface Overview { kill_switch: boolean; campaigns: Campaign[]; counts: Record<string, number>; reasons: Record<string, number>; decisions: Decision[]; consent_coverage: { customers: number; sms: number; email: number; voice: number; opted_out: number }; callbacks: number }
interface Cb { id: string; conversation_id: string; window: string; reason: string; status: string; source: string; created_at: number }

const TONE: Record<string, string> = { sent: 'green', deferred: 'amber', suppressed: 'red' }

export default function OutboundPage() {
  const ov = useApi<Overview>('/api/outbound/overview', { refreshMs: 6000 })
  const cbs = useApi<Cb[]>('/api/outbound/callbacks', { refreshMs: 10000 })
  const [sel, setSel] = useState<Decision | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const act = async (fn: () => Promise<unknown>, ok: (r: any) => string) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    setBusy(true); setMsg(null)
    try { const r = await fn(); setMsg(ok(r)); ov.reload(); cbs.reload() } catch (e) { setMsg(`Error: ${e instanceof ApiError ? JSON.stringify(e.body) : String(e)}`) } finally { setBusy(false) }
  }
  const fire = (trigger: string, as_of?: string) => act(() => api('/api/outbound/events', { body: { trigger, as_of } }), (r) => `${r.candidates} affected customers → ${r.counts.sent} sent, ${r.counts.deferred} deferred, ${r.counts.suppressed} suppressed.`)
  const o = ov.data
  const night = new Date(); night.setUTCHours(22, 30, 0, 0)
  const noon = new Date(); noon.setUTCHours(11, 0, 0, 0)
  return (
    <div>
      <PageHeader icon={Megaphone} title="Proactive & outbound engagement" subtitle="Event-triggered outreach — only with valid consent. Opt-outs are never contacted; quiet hours follow the recipient's time zone; frequency caps and a kill switch apply; every decision is audited with its consent evidence. Delivery is simulated (no PSTN / SMS / e-mail provider)."
        actions={<Button variant={o?.kill_switch ? 'danger' : 'secondary'} icon={OctagonX} busy={busy} onClick={() => act(() => api('/api/outbound/kill-switch', { body: { on: !o?.kill_switch } }), () => `Kill switch ${o?.kill_switch ? 'released' : 'ON - all outreach is suppressed immediately'}.`)}>{o?.kill_switch ? 'Kill switch ON — release' : 'Kill switch'}</Button>} />
      {msg && <div role="status" className="mb-3 rounded-xl bg-blue-50 px-3 py-2 text-sm text-blue-800 ring-1 ring-blue-200">{msg}</div>}
      {ov.loading && !o ? <Spinner /> : ov.error || !o ? <ErrorBox error={ov.error} /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label="Sent" value={o.counts.sent} tone="green" /><Stat label="Deferred (quiet hours)" value={o.counts.deferred} tone="amber" /><Stat label="Suppressed" value={o.counts.suppressed} tone="red" /><Stat label="Opted out" value={o.consent_coverage.opted_out} hint={`of ${o.consent_coverage.customers} customers`} /><Stat label="SMS / e-mail / voice consent" value={`${o.consent_coverage.sms}/${o.consent_coverage.email}/${o.consent_coverage.voice}`} /><Stat label="Callbacks scheduled" value={o.callbacks} />
          </div>
          <Card title="Trigger an event" subtitle="the simulated event selects affected customers; each gets a consent / opt-out / quiet-hours / cap decision">
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={Play} busy={busy} onClick={() => fire('shipment_delayed')}>Shipment delayed — now</Button>
              <Button busy={busy} onClick={() => fire('shipment_delayed', night.toISOString())}>… at 22:30 UTC (quiet hours)</Button>
              <Button busy={busy} onClick={() => fire('shipment_delayed', noon.toISOString())}>… at 11:00 UTC (business hours)</Button>
              <Button busy={busy} onClick={() => fire('appointment_reminder')}>Appointment reminder</Button>
              <Button busy={busy} onClick={() => act(() => api('/api/outbound/release-deferred', { method: 'POST' }), (r) => `Released ${r.released}, blocked ${r.blocked}.`)}>Release due deferrals</Button>
              <Button busy={busy} onClick={() => act(() => api('/api/outbound/reset-demo', { method: 'POST' }), (r) => `Removed ${r.deleted} decisions.`)}>Reset demo</Button>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-3">
            {o.campaigns.map((c) => (
              <Card key={c.id} title={c.name} subtitle={`trigger ${c.trigger} · caps ${c.caps.per_customer_7d}/customer/7d, ${c.caps.per_day}/day · quiet ${c.quiet_hours.start}:00-${c.quiet_hours.end}:00 local`} actions={<Badge tone={c.state === 'active' ? 'green' : 'amber'}>{c.state}</Badge>}>
                <div className="flex gap-2">{['active', 'paused', 'killed'].map((s) => <Button key={s} size="sm" variant={c.state === s ? 'primary' : 'secondary'} disabled={busy} onClick={() => act(() => api(`/api/outbound/campaigns/${c.id}`, { method: 'PUT', body: { state: s } }), () => `${c.name}: ${s}.`)}>{s}</Button>)}</div>
              </Card>
            ))}
            <Card title="Why outreach was not sent" subtitle="suppression and deferral reasons"><ul className="space-y-1 text-sm">{Object.entries(o.reasons).map(([k, n]) => <li key={k} className="flex justify-between gap-2"><span className="text-slate-700">{k}</span><b>{n}</b></li>)}{!Object.keys(o.reasons).length && <li className="text-slate-500">No suppressions yet.</li>}</ul></Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <Card title="Decisions (audited)" pad={false}>
              <DataTable dense rows={o.decisions} rowKey={(d) => d.id} selected={sel?.id} onRowClick={setSel} empty="No outreach yet — trigger an event." cols={[
                { key: 'c', header: 'Customer', render: (d) => <span className="font-mono text-xs">{d.customer_id} · {d.market}</span> },
                { key: 'd', header: 'Decision', render: (d) => <Badge tone={TONE[d.decision]}>{d.decision}{d.released_from ? ' (released)' : ''}</Badge> },
                { key: 'h', header: 'Channel', render: (d) => d.channel ?? '—' },
                { key: 'r', header: 'Reason', render: (d) => <span className="text-xs text-slate-600">{d.reason}</span> },
                { key: 'w', header: 'Send at', render: (d) => (d.scheduled_for ? fmt.dt(d.scheduled_for) : '') },
              ]} />
            </Card>
            <Card title={sel ? `Decision ${sel.id}` : 'Consent evidence'}>
              {!sel ? <p className="text-sm text-slate-500">Select a decision to see the checks that ran and the consent record used.</p> : (
                <div className="space-y-2 text-xs">
                  <div className="flex flex-wrap gap-1">{sel.checks.map((c) => <Badge key={c} tone={c.includes('deferred') || c.includes('cap') || c.includes('none') || c.includes('on') ? 'amber' : 'green'}>{c}</Badge>)}</div>
                  {sel.message && <p className={cx('rounded-xl bg-slate-50 p-2 text-sm text-slate-800')}>{sel.message}</p>}
                  {sel.composed_by && <p className="text-slate-500">composed by {sel.composed_by} · guard checked</p>}
                  <pre className="scroll-thin max-h-48 overflow-auto rounded-lg bg-slate-900 p-2 text-[11px] text-slate-100">{JSON.stringify(sel.consent_evidence, null, 1)}</pre>
                  {sel.conversation_id && <a className="font-medium text-blue-700 hover:underline" href={`/widget?c=${sel.conversation_id}`} target="_blank" rel="noreferrer">Open the customer's conversation →</a>}
                </div>
              )}
            </Card>
          </div>
          <Card title="Callbacks (visible to WFM & supervisors)" pad={false}><DataTable dense rows={cbs.data ?? []} rowKey={(c) => c.id} empty="No callbacks yet." cols={[{ key: 'i', header: 'Id', render: (c) => <span className="font-mono text-xs">{c.id}</span> }, { key: 'w', header: 'Window', render: (c) => c.window }, { key: 'r', header: 'Reason', render: (c) => <span className="text-xs">{c.reason}</span> }, { key: 's', header: 'Source', render: (c) => c.source }, { key: 't', header: 'Status', render: (c) => <Badge tone="blue">{c.status}</Badge> }]} /></Card>
        </div>
      )}
    </div>
  )
}
