import { useState } from 'react'
import { ApprovalCard, type InboxItemT } from '../../components/approvals'
import { Json, useAction } from '../../components/bits'
import { Badge, Card, Empty, Page, Stat, Tabs } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Resp = { items: InboxItemT[]; stats: { pending: number; breached: number; escalations: number; expired: number; total: number; mean_decision_min: number | null }; t: number; teams: { configured: boolean; sent: number } }

export default function Inbox() {
  const calls = usePlantCalls()
  const inbox = usePApi<Resp>('/api/inbox', { interval: 2500 })
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending')
  const [card, setCard] = useState<{ id: string; card: unknown } | null>(null)
  const act = useAction()
  const items = (inbox.data?.items ?? []).filter((i) => (tab === 'pending' ? i.status === 'pending' : i.status !== 'pending')).slice().reverse()
  const st = inbox.data?.stats
  return (
    <Page title="Approvals inbox" subtitle="Plans the policy engine does not auto-execute wait here with a rationale, the twin's what-if result, an SLA and an escalation path. Unanswered requests expire fail-safe (nothing is executed). Each request can also go to Microsoft Teams as an Adaptive Card.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Pending" value={st?.pending ?? 0} tone={st?.pending ? 'warn' : 'ok'} />
        <Stat label="SLA breached" value={st?.breached ?? 0} tone={st?.breached ? 'bad' : 'ok'} />
        <Stat label="Escalations" value={st?.escalations ?? 0} />
        <Stat label="Expired (fail-safe)" value={st?.expired ?? 0} />
        <Stat label="Mean decision time" value={st?.mean_decision_min != null ? fmt.dur(st.mean_decision_min) : '-'} sub="simulated minutes" />
      </div>
      <Tabs tabs={[{ id: 'pending', label: `Pending (${st?.pending ?? 0})` }, { id: 'resolved', label: 'Resolved' }]} value={tab} onChange={setTab} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">
          {items.length === 0 ? <Empty>{tab === 'pending' ? 'Nothing waiting for a human. Inject a fault (Control Tower) or lower the autonomy dial (Policy) to see decisions arrive here.' : 'No resolved decisions yet.'}</Empty> : items.map((i) => (
            <div key={i.id}>
              <ApprovalCard item={i} onDone={() => void inbox.reload()} />
              <div className="mt-1 flex items-center gap-2 pl-1">
                <button className="text-[11px] text-accent hover:underline" onClick={async () => { const r = await act.run(() => calls.get<unknown>(`/api/inbox/${i.id}/teams-card`)); if (r) setCard({ id: i.id, card: r }) }}>Teams Adaptive Card</button>
                <button className="text-[11px] text-accent hover:underline" onClick={() => act.run(() => calls.post(`/api/inbox/${i.id}/notify`))}>Send to Teams</button>
              </div>
            </div>
          ))}
          {act.error && <p role="alert" className="text-xs text-bad">{act.error}</p>}
        </div>
        <div className="space-y-4">
          <Card title="Microsoft Teams integration" right={<Badge tone={inbox.data?.teams.configured ? 'ok' : 'mute'}>{inbox.data?.teams.configured ? `webhook configured · ${inbox.data.teams.sent} sent` : 'webhook not configured'}</Badge>}>
            <p className="text-[12px] text-mute">Cards are always generated (Adaptive Card 1.4); posting happens only when a Teams Workflows webhook URL is configured (HTTPS, allow-listed hosts). In this deployment no webhook is set, so the card is previewed below.</p>
            {card && <div className="mt-2"><div className="mb-1 text-[11px] text-mute">Card for {card.id}</div><Json data={card.card} max={300} /></div>}
          </Card>
        </div>
      </div>
    </Page>
  )
}
