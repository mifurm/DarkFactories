import { Megaphone, OctagonX, Play } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, ErrorBox, PageHeader, Spinner, Stat, cx } from '../../lib/ui'

interface Campaign { id: string; name: string; trigger: string; state: string; caps: { per_customer_7d: number; per_day: number }; quiet_hours: { start: number; end: number } }
interface Decision { id: string; ts: number; campaign_id: string; trigger: string; customer_id: string; market: string; decision: string; reason: string; channel: string | null; scheduled_for: number | null; consent_evidence: Record<string, unknown> | null; checks: string[]; order_id?: string; conversation_id?: string; composed_by?: string; message?: string; released_from?: string }
interface Overview { kill_switch: boolean; campaigns: Campaign[]; counts: Record<string, number>; reasons: Record<string, number>; decisions: Decision[]; consent_coverage: { customers: number; sms: number; email: number; voice: number; opted_out: number }; callbacks: number }
interface Cb { id: string; conversation_id: string; window: string; reason: string; status: string; source: string; created_at: number }

const TONE: Record<string, string> = { sent: 'green', deferred: 'amber', suppressed: 'red' }

export default function OutboundPage() {
  const { t, tn, te, ts, lang, fmt } = useI18n()
  const ov = useApi<Overview>('/api/outbound/overview', { refreshMs: 6000 })
  const cbs = useApi<Cb[]>('/api/outbound/callbacks', { refreshMs: 10000 })
  const [sel, setSel] = useState<Decision | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const act = async (fn: () => Promise<unknown>, ok: (r: any) => string) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    setBusy(true)
    setMsg(null)
    try {
      const r = await fn()
      setMsg(ok(r))
      ov.reload()
      cbs.reload()
    } catch (e) {
      setMsg(t('Error: {error}', { error: describeError(e) }))
    } finally {
      setBusy(false)
    }
  }
  const fire = (trigger: string, as_of?: string) => act(() => api('/api/outbound/events', { body: { trigger, as_of } }), (r) => t('{customers} → {sent} sent, {deferred} deferred, {suppressed} suppressed.', { customers: tn(r.candidates, { one: '{n} affected customer', other: '{n} affected customers' }), sent: r.counts.sent, deferred: r.counts.deferred, suppressed: r.counts.suppressed }))
  const o = ov.data
  const night = new Date(); night.setUTCHours(22, 30, 0, 0)
  const noon = new Date(); noon.setUTCHours(11, 0, 0, 0)
  /** Decision reasons come from the API; the one with a time zone and local time is composed here when the server sent it in English. */
  const reasonText = (r: string) => {
    if (lang === 'en') return r
    const m = /^quiet hours in the recipient's time zone \((.+), (\d{1,2}:\d{2}) local\)$/.exec(r)
    return m ? t('quiet hours in the recipient\'s time zone ({zone}, {time} local)', { zone: m[1], time: m[2] }) : ts(r)
  }
  /** Decision checks arrive as `name:value` codes (`consent:email`, `quiet_hours:ok`); English shows them as they are. */
  const checkLabel = (c: string) => {
    if (lang === 'en') return c
    const [name, ...rest] = c.split(':')
    return rest.length ? `${te('outboundCheck', name)}: ${te('outboundCheckValue', rest.join(':'))}` : te('outboundCheck', name)
  }
  return (
    <div>
      <PageHeader icon={Megaphone} title={t('Proactive & outbound engagement')} subtitle={t('Event-triggered outreach — only with valid consent. Opt-outs are never contacted; quiet hours follow the recipient\'s time zone; frequency caps and a kill switch apply; every decision is audited with its consent evidence. Delivery is simulated (no PSTN / SMS / e-mail provider).')}
        actions={<Button variant={o?.kill_switch ? 'danger' : 'secondary'} icon={OctagonX} busy={busy} onClick={() => act(() => api('/api/outbound/kill-switch', { body: { on: !o?.kill_switch } }), () => (o?.kill_switch ? t('Kill switch released.') : t('Kill switch ON - all outreach is suppressed immediately.')))}>{o?.kill_switch ? t('Kill switch ON — release') : t('Kill switch')}</Button>} />
      {msg && <div role="status" className="mb-3 rounded-xl bg-blue-50 px-3 py-2 text-sm text-blue-800 ring-1 ring-blue-200">{msg}</div>}
      {ov.loading && !o ? <Spinner /> : ov.error || !o ? <ErrorBox error={ov.error} /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label={t('Sent')} value={o.counts.sent} tone="green" />
            <Stat label={t('Deferred (quiet hours)')} value={o.counts.deferred} tone="amber" />
            <Stat label={t('Suppressed')} value={o.counts.suppressed} tone="red" />
            <Stat label={t('Opted out')} value={o.consent_coverage.opted_out} hint={tn(o.consent_coverage.customers, { one: 'of {n} customer', other: 'of {n} customers' })} />
            <Stat label={t('SMS / e-mail / voice consent')} value={`${o.consent_coverage.sms} / ${o.consent_coverage.email} / ${o.consent_coverage.voice}`} />
            <Stat label={t('Callbacks scheduled')} value={o.callbacks} />
          </div>
          <Card title={t('Trigger an event')} subtitle={t('the simulated event selects affected customers; each gets a consent / opt-out / quiet-hours / cap decision')}>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={Play} busy={busy} onClick={() => fire('shipment_delayed')}>{t('Shipment delayed — now')}</Button>
              <Button busy={busy} onClick={() => fire('shipment_delayed', night.toISOString())}>{t('… at 22:30 UTC (quiet hours)')}</Button>
              <Button busy={busy} onClick={() => fire('shipment_delayed', noon.toISOString())}>{t('… at 11:00 UTC (business hours)')}</Button>
              <Button busy={busy} onClick={() => fire('appointment_reminder')}>{t('Appointment reminder')}</Button>
              <Button busy={busy} onClick={() => act(() => api('/api/outbound/release-deferred', { method: 'POST' }), (r) => t('Released {released}, blocked {blocked}.', { released: r.released, blocked: r.blocked }))}>{t('Release due deferrals')}</Button>
              <Button busy={busy} onClick={() => act(() => api('/api/outbound/reset-demo', { method: 'POST' }), (r) => tn(r.deleted, { one: 'Removed {n} decision.', other: 'Removed {n} decisions.' }))}>{t('Reset demo')}</Button>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-3">
            {o.campaigns.map((c) => (
              <Card key={c.id} title={ts(c.name)} subtitle={t('trigger {trigger} · caps {perCustomer}/customer/7d, {perDay}/day · quiet {start}:00-{end}:00 local', { trigger: te('outboundTrigger', c.trigger), perCustomer: c.caps.per_customer_7d, perDay: c.caps.per_day, start: c.quiet_hours.start, end: c.quiet_hours.end })} actions={<Badge tone={c.state === 'active' ? 'green' : 'amber'}>{te('campaignState', c.state)}</Badge>}>
                <div className="flex gap-2">{['active', 'paused', 'killed'].map((s) => <Button key={s} size="sm" variant={c.state === s ? 'primary' : 'secondary'} disabled={busy} onClick={() => act(() => api(`/api/outbound/campaigns/${c.id}`, { method: 'PUT', body: { state: s } }), () => t('{name}: {state}.', { name: ts(c.name), state: te('campaignState', s) }))}>{te('campaignState', s)}</Button>)}</div>
              </Card>
            ))}
            <Card title={t('Why outreach was not sent')} subtitle={t('suppression and deferral reasons')}>
              <ul className="space-y-1 text-sm">
                {Object.entries(o.reasons).map(([k, n]) => <li key={k} className="flex justify-between gap-2"><span className="text-slate-700">{reasonText(k)}</span><b>{n}</b></li>)}
                {!Object.keys(o.reasons).length && <li className="text-slate-500">{t('No suppressions yet.')}</li>}
              </ul>
            </Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <Card title={t('Decisions (audited)')} pad={false}>
              <DataTable dense rows={o.decisions} rowKey={(d) => d.id} selected={sel?.id} onRowClick={setSel} empty={t('No outreach yet — trigger an event.')} cols={[
                { key: 'c', header: t('Customer'), render: (d) => <span className="font-mono text-xs">{d.customer_id} · {d.market}</span> },
                { key: 'd', header: t('Decision'), render: (d) => <Badge tone={TONE[d.decision]}>{te('outboundDecision', d.decision)}{d.released_from ? ` ${t('(released)')}` : ''}</Badge> },
                { key: 'h', header: t('Channel'), render: (d) => (d.channel ? te('channel', d.channel) : '—') },
                { key: 'r', header: t('Reason'), render: (d) => <span className="text-xs text-slate-600">{reasonText(d.reason)}</span> },
                { key: 'w', header: t('Send at'), render: (d) => (d.scheduled_for ? fmt.dt(d.scheduled_for) : '') },
              ]} />
            </Card>
            <Card title={sel ? t('Decision {id}', { id: sel.id }) : t('Consent evidence')}>
              {!sel ? <p className="text-sm text-slate-500">{t('Select a decision to see the checks that ran and the consent record used.')}</p> : (
                <div className="space-y-2 text-xs">
                  <div className="flex flex-wrap gap-1">{sel.checks.map((c) => <Badge key={c} tone={c.includes('deferred') || c.includes('cap') || c.includes('none') || c.includes('on') ? 'amber' : 'green'}>{checkLabel(c)}</Badge>)}</div>
                  {sel.message && <p className={cx('rounded-xl bg-slate-50 p-2 text-sm text-slate-800')}>{sel.message}</p>}
                  {sel.composed_by && <p className="text-slate-500">{t('composed by {by} · guard checked', { by: te('summarySource', sel.composed_by) })}</p>}
                  <pre data-i18n-skip className="scroll-thin max-h-48 overflow-auto rounded-lg bg-slate-900 p-2 text-[11px] text-slate-100">{JSON.stringify(sel.consent_evidence, null, 1)}</pre>
                  {sel.conversation_id && <a className="font-medium text-blue-700 hover:underline" href={`/widget?c=${sel.conversation_id}&lang=${lang}`} target="_blank" rel="noreferrer">{t('Open the customer\'s conversation →')}</a>}
                </div>
              )}
            </Card>
          </div>
          <Card title={t('Callbacks (visible to WFM & supervisors)')} pad={false}>
            <DataTable dense rows={cbs.data ?? []} rowKey={(c) => c.id} empty={t('No callbacks yet.')} cols={[
              { key: 'i', header: t('Id'), render: (c) => <span className="font-mono text-xs">{c.id}</span> },
              { key: 'w', header: t('Window'), render: (c) => c.window },
              { key: 'r', header: t('Reason'), render: (c) => <span className="text-xs">{ts(c.reason)}</span> },
              { key: 's', header: t('Source'), render: (c) => ts(c.source) },
              { key: 't', header: t('Status'), render: (c) => <Badge tone="blue">{te('callbackStatus', c.status)}</Badge> },
            ]} />
          </Card>
        </div>
      )}
    </div>
  )
}
