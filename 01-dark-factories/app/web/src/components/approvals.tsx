import { useState } from 'react'
import { Badge, Button } from './ui'
import { Meter, Mono, useAction } from './bits'
import { fmt } from '../lib/feature'
import { usePlantCalls } from '../plant'

export type InboxItemT = {
  id: string
  plan_id: string
  title: string
  decision_class: string
  explanation: string
  options: { id: string; label: string }[]
  impact: Record<string, number | string>
  risk_score: number
  reasons: string[]
  sla_min: number
  sla_remaining_min?: number
  breached?: boolean
  advisory: boolean
  level: number
  assigned_role: string
  status: string
  resolved_by: string
  resolution: string
  comment: string
  history: { t: number; event: string; by: string }[]
  whatif?: { explanation?: string; delta?: Record<string, number> } | null
}

export const statusTone = (s: string) => ({ pending: 'warn', approved: 'ok', applied: 'ok', rejected: 'bad', expired: 'bad', deferred: 'info' }[s] ?? 'mute') as 'warn' | 'ok' | 'bad' | 'info' | 'mute'

export function ApprovalCard({ item, onDone, compact }: { item: InboxItemT; onDone?: () => void; compact?: boolean }) {
  const calls = usePlantCalls()
  const act = useAction()
  const [comment, setComment] = useState('')
  const pending = item.status === 'pending'
  const resolve = (option: 'approve' | 'reject' | 'defer') =>
    act.run(async () => {
      const r = await calls.post(`/api/inbox/${item.id}/resolve`, { option, comment })
      onDone?.()
      return r
    })
  const delta = item.whatif?.delta
  return (
    <div className="rounded-lg border border-line bg-panel2/60 p-3" data-testid="approval-card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{item.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-mute">
            <Mono>{item.decision_class}</Mono>
            <Badge tone={statusTone(item.status)}>{item.status}</Badge>
            <span>L{item.level}</span>
            <span>risk {item.risk_score.toFixed(2)}</span>
            <span>for {item.assigned_role.replace('_', ' ')}</span>
          </div>
        </div>
        {pending && item.sla_remaining_min !== undefined && (
          <Badge tone={item.breached ? 'bad' : item.sla_remaining_min < 10 ? 'warn' : 'info'} title="SLA remaining (simulated minutes); escalates, then expires fail-safe">
            {item.breached ? 'SLA breached' : `${fmt.dur(item.sla_remaining_min)} left`}
          </Badge>
        )}
      </div>
      {!compact && <p className="mt-2 text-[13px] text-ink/90">{item.explanation}</p>}
      {!compact && item.reasons.length > 0 && <div className="mt-1 text-[11px] text-mute">Policy: {item.reasons.join(' · ')}</div>}
      {!compact && Object.keys(item.impact ?? {}).length > 0 && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 text-[12px] sm:grid-cols-4">
          {Object.entries(item.impact).slice(0, 8).map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-line/40 py-0.5">
              <span className="text-mute">{k.replace(/_/g, ' ')}</span>
              <span className="tabnum">{typeof v === 'number' ? fmt.n(v, Math.abs(v) < 10 ? 2 : 0) : String(v)}</span>
            </div>
          ))}
        </div>
      )}
      {!compact && delta && (
        <div className="mt-2 rounded-md bg-black/20 p-2 text-[12px]">
          <span className="text-mute">What-if (digital-twin fork): </span>
          net value <b className={(delta.net_value_eur ?? 0) >= 0 ? 'text-ok' : 'text-bad'}>{fmt.eur(delta.net_value_eur)}</b>, downtime {fmt.n(delta.downtime_min, 0)} min, late orders {fmt.n(delta.late_orders, 0)}
        </div>
      )}
      {pending && (
        <>
          <Meter value={item.sla_remaining_min ?? 0} max={item.sla_min} tone={item.breached ? 'bad' : 'info'} label="SLA" />
          {item.advisory && <div className="mt-1 text-[11px] text-warn">Advisory (L1): a human carries out this recommendation.</div>}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {!compact && <input aria-label="Decision comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (optional, goes to the ledger)" className="min-w-[10rem] flex-1 rounded-md border border-line bg-panel px-2 py-1 text-xs" />}
            <Button size="sm" tone="ok" disabled={act.busy} onClick={() => resolve('approve')}>Approve</Button>
            <Button size="sm" tone="danger" disabled={act.busy} onClick={() => resolve('reject')}>Reject</Button>
            <Button size="sm" tone="ghost" disabled={act.busy} onClick={() => resolve('defer')}>Defer</Button>
          </div>
          {act.error && <div role="alert" className="mt-1 text-xs text-bad">{act.error}</div>}
        </>
      )}
      {!pending && item.resolved_by && (
        <div className="mt-2 text-[11px] text-mute">
          {item.resolution || item.status} by {item.resolved_by}
          {item.comment ? ` - "${item.comment}"` : ''}
        </div>
      )}
    </div>
  )
}
