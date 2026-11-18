import { Bot, CheckCircle2, ClipboardList, Headphones, Languages, Lightbulb, PhoneForwarded, Send, ShieldAlert, Sparkles, User, UserCheck, Wrench } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { N_, useI18n } from '../../i18n'
import { api, describeError, useApi, useEventStream } from '../../lib/api'
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Progress, Spinner, Tabs, cx, inputCls, sentimentTone } from '../../lib/ui'

interface QueueItem { conversation_id: string; queue: string; priority: number; language: string; channel: string; waiting_s: number | null; sla_s: number | null; trigger: { code: string; reason: string } | null; customer: string | null; summary: string | null; sentiment: number | null; risk_flags: string[]; completeness: number | null; state: string | null; offered_to: string | null }
interface Summary { id: string; customer: string | null; intent: string | null; sentiment: number; language: string; status: string; handler: string; last_customer_text: string; channel: string }
interface Console { agent_id: string; waiting: QueueItem[]; mine: Summary[]; live_ai: Summary[] }
interface Msg { idx: number; role: string; text: string; flags: string[]; translations?: Record<string, string>; author?: string | null; visible_to_customer: boolean; tools?: { name: string; status: string }[] }
interface Conv { id: string; status: string; language: string; handler: string; messages: Msg[]; identity: { verified: boolean; level: number; customer_id: string | null }; summary: Summary; disposition_preview?: { code?: string; disposition?: string } | string; wrapup?: Record<string, any> | null } // eslint-disable-line @typescript-eslint/no-explicit-any
interface Pkg { summary: string; summary_source: string; completeness: number; intent: string; customer: { first_name: string | null; tier: string | null; vulnerable?: boolean }; verification: { verified: boolean; level: number; method: string | null }; steps_tried: { tool: string; status: string; summary: string }[]; sentiment: { current: number; emotion: string }; risk_flags: string[]; suggested_resolution: string; policy_citations: { ref: string; title: string; snippet: string }[]; pending_approvals: { id: string; kind: string; amount: number; currency?: string; status: string }[]; trigger: { code: string; reason: string }; routing: { queue: string; priority: number }; package_ms?: number }
interface Assist { next_best_actions: { id: string; rank: number; title: string; rationale: string; confidence: number; citation?: { title: string } | null }[]; suggested_replies: { id: string; text: string; tone: string }[]; compliance_reminders: { text?: string; id?: string }[] | string[]; form_autofill: Record<string, any>; tone: { advice?: string; sentiment?: number; flags?: string[] } & Record<string, any>; generated_ms: number } // eslint-disable-line @typescript-eslint/no-explicit-any

const AGENTS = [
  ['AG-08', 'Hannah Clarke', N_('senior, EN/DE')],
  ['AG-01', 'Lena Fischer', N_('DE')],
  ['AG-03', 'Camille Bernard', N_('FR, VIP')],
  ['AG-09', 'Daniel Weber', N_('legal/safety')],
  ['AG-06', 'Anna Wiśniewska', N_('PL, EN')],
]
const TRIGGER_TONE: Record<string, string> = { legal_threat: 'red', fraud_suspected: 'red', safety_issue: 'red', vulnerable_customer: 'amber', explicit_request: 'blue', sentiment: 'amber', policy_block: 'violet', tool_failure: 'slate', loop: 'slate', knowledge_gap: 'slate' }

export default function AgentConsole() {
  const { t, te, tr, fmt, lang } = useI18n()
  const [params] = useSearchParams()
  const [agentId, setAgentId] = useState('AG-08')
  const [sel, setSel] = useState<string | null>(params.get('conversation'))
  const [tab, setTab] = useState('context')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState<{ tone: string; text: string } | null>(null)
  const con = useApi<Console>(`/api/assist/console?agent_id=${agentId}`, { refreshMs: 5000 })
  const conv = useApi<Conv>(sel ? `/api/assist/${sel}/conversation` : null, { refreshMs: 4000 })
  const pkg = useApi<Pkg>(sel ? `/api/handoff/${sel}/package` : null)
  const assist = useApi<Assist>(sel ? `/api/assist/${sel}${draft.length > 8 ? `?draft=${encodeURIComponent(draft.slice(0, 300))}` : ''}` : null, { refreshMs: 9000 })

  useEventStream(['agents'], () => { con.reload() })
  useEffect(() => { if (sel) conv.reload() }, [sel]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    setFlash(null)
    try {
      await fn()
      setFlash({ tone: 'green', text: ok })
      con.reload(); conv.reload(); pkg.reload()
    } catch (e) {
      setFlash({ tone: 'red', text: describeError(e) })
    } finally {
      setBusy(false)
    }
  }
  const accept = (id: string) => act(() => api(`/api/handoff/${id}/accept`, { body: { agent_id: agentId } }), t('You joined the conversation - the customer was notified.')).then(() => setSel(id))
  const takeover = (id: string) => act(() => api(`/api/assist/${id}/takeover`, { body: { agent_id: agentId } }), t('Took over from the AI with the history intact.')).then(() => setSel(id))
  const send = () => act(async () => { const r = await api<{ guard: { modified: boolean; issues: string[] } }>(`/api/assist/${sel}/message`, { body: { text: draft, agent_id: agentId } }); setDraft(''); if (r.guard.modified) setFlash({ tone: 'amber', text: t('Guard modified the message: {issues}', { issues: r.guard.issues.join(', ') }) }) }, t('Message sent.'))
  const useReply = async (r: { id: string; text: string }) => { setDraft(r.text); await api(`/api/assist/${sel}/feedback`, { body: { suggestion_id: r.id, kind: 'reply', action: 'accepted' } }).catch(() => undefined) }
  const c = conv.data
  const mine = c?.handler === 'human'
  const waiting = c?.status === 'waiting_human'
  const counts = { waiting: con.data?.waiting.length ?? 0, mine: con.data?.mine.length ?? 0 }

  return (
    <div>
      <PageHeader icon={Headphones} title={t('Human-agent console')} subtitle={t('Warm handoff with the full context package, Agent Assist (next-best-action, suggested replies, tone coaching, translation) and policy-guarded actions.')}
        actions={<select aria-label={t('Acting as agent')} value={agentId} onChange={(e) => setAgentId(e.target.value)} className={cx(inputCls, 'w-72')}>{AGENTS.map(([id, name, note]) => <option key={id} value={id}>{name} ({tr(note)})</option>)}</select>} />
      {flash && <div role="status" className={cx('mb-3 rounded-xl px-3 py-2 text-sm ring-1', flash.tone === 'green' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : flash.tone === 'amber' ? 'bg-amber-50 text-amber-800 ring-amber-200' : 'bg-rose-50 text-rose-700 ring-rose-200')}>{flash.text}</div>}
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_380px]">
        <div className="space-y-4">
          <Card title={t('Waiting for a human ({count})', { count: counts.waiting })} pad={false}>
            {con.loading && !con.data ? <Spinner /> : con.error ? <ErrorBox error={con.error} onRetry={con.reload} /> : !con.data?.waiting.length ? <div className="p-4"><Empty>{t('No handoffs waiting. Start a conversation in the widget and ask for a person, or use “Demo traffic” in the supervisor console.')}</Empty></div> : (
              <ul className="divide-y divide-slate-100">
                {con.data.waiting.map((q) => (
                  <li key={q.conversation_id}>
                    <button type="button" onClick={() => { setSel(q.conversation_id); setTab('context') }} className={cx('w-full px-4 py-3 text-left hover:bg-blue-50/60', sel === q.conversation_id && 'bg-blue-50')}>
                      <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-900">{q.customer ?? t('Unverified customer')}</span><Badge tone={TRIGGER_TONE[q.trigger?.code ?? ''] ?? 'slate'}>{te('trigger', q.trigger?.code)}</Badge></div>
                      <p data-user-content className="mt-0.5 text-xs text-slate-600">{q.summary}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500"><span>{te('queue', q.queue)}</span><span>·</span><span>{q.language.toUpperCase()}</span><span>·</span><span>{t('wait {time}', { time: fmt.dur(q.waiting_s) })}</span><Badge tone={sentimentTone(q.sentiment)}>{q.sentiment != null ? fmt.fixed(q.sentiment, 2) : '—'}</Badge></div>
                      {q.sla_s && q.waiting_s != null && <div className="mt-1.5"><Progress value={q.waiting_s} max={q.sla_s} tone={q.waiting_s > q.sla_s ? 'red' : q.waiting_s > 0.7 * q.sla_s ? 'amber' : 'blue'} /></div>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title={t('My conversations ({count})', { count: counts.mine })} pad={false}>
            {!con.data?.mine.length ? <div className="p-4 text-sm text-slate-500">{t('None yet.')}</div> : <ul className="divide-y divide-slate-100">{con.data.mine.map((s) => <li key={s.id}><button type="button" onClick={() => setSel(s.id)} className={cx('w-full px-4 py-2.5 text-left text-sm hover:bg-blue-50/60', sel === s.id && 'bg-blue-50')}><b>{s.customer ?? s.id}</b> <span className="text-xs text-slate-500">{te('intent', s.intent)}</span></button></li>)}</ul>}
          </Card>
          <Card title={t('Live AI conversations (take over)')} pad={false}>
            {!con.data?.live_ai.length ? <div className="p-4 text-sm text-slate-500">{t('No active AI conversations.')}</div> : <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto">{con.data.live_ai.map((s) => <li key={s.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm"><button type="button" className="min-w-0 flex-1 break-words text-left hover:underline" onClick={() => setSel(s.id)}>{s.customer ?? s.id} · <span className="text-xs text-slate-500">{s.intent ? te('intent', s.intent) : t('new')}</span></button><Button size="sm" onClick={() => takeover(s.id)} disabled={busy}>{t('Take over')}</Button></li>)}</ul>}
          </Card>
        </div>

        <Card title={c ? `${c.summary.customer ?? t('Customer')} · ${c.language.toUpperCase()} · ${te('convStatus', c.status)}` : t('Conversation')} subtitle={c ? `${te('channel', c.summary.channel)} · ${c.identity.verified ? t('identity verified L{level}', { level: c.identity.level }) : t('identity not verified')}` : undefined}
          actions={c && <>{waiting && <Button variant="primary" size="sm" onClick={() => accept(c.id)} disabled={busy} icon={UserCheck}>{t('Accept')}</Button>}{mine && <><Button size="sm" onClick={() => act(() => api(`/api/handoff/${c.id}/return-to-ai`, { method: 'POST' }), t('Returned to the AI assistant.'))} disabled={busy} icon={Bot}>{t('Return to AI')}</Button><Button size="sm" onClick={() => act(() => api(`/api/handoff/${c.id}/callback`, { body: {} }), t('Callback scheduled (visible to WFM / supervisor).'))} disabled={busy} icon={PhoneForwarded}>{t('Callback')}</Button><Button size="sm" variant="success" onClick={() => act(() => api(`/api/assist/${c.id}/end`, { body: {} }), t('Conversation ended - wrap-up and QA run automatically.'))} disabled={busy} icon={CheckCircle2}>{t('End & wrap-up')}</Button></>}</>}>
          {!sel ? <Empty>{t('Select a waiting handoff, one of your conversations, or take over a live AI conversation.')}</Empty> : conv.loading && !c ? <Spinner /> : conv.error ? <ErrorBox error={conv.error} /> : c && (
            <div className="flex h-[560px] flex-col">
              <div className="scroll-thin flex-1 space-y-3 overflow-y-auto pr-1" role="log" aria-label={t('Transcript')}>
                {c.messages.filter((m) => m.visible_to_customer || m.role === 'supervisor').map((m) => {
                  // an operator reads the customer's message in the UI language when the server provides it, else in English
                  const translated = m.role === 'customer' && c.language !== lang ? (m.translations?.[lang] ?? (c.language !== 'en' ? m.translations?.en : undefined)) : undefined
                  return (
                    <div key={m.idx} className={cx('rounded-xl px-3 py-2 text-sm', m.role === 'customer' ? 'bg-slate-100' : m.role === 'supervisor' ? 'border border-dashed border-violet-300 bg-violet-50' : m.role === 'system_notice' ? 'bg-transparent text-center text-xs text-slate-500' : m.role === 'agent_human' ? 'bg-emerald-50' : 'bg-blue-50')}>
                      {m.role !== 'system_notice' && <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{m.role === 'customer' ? <User size={11} aria-hidden /> : m.role === 'agent_human' ? <UserCheck size={11} aria-hidden /> : <Bot size={11} aria-hidden />}{te('msgRole', m.role)}{m.flags.includes('whisper') && <Badge tone="violet">{t('agent only')}</Badge>}</div>}
                      <div className="whitespace-pre-wrap text-slate-800">{m.text}</div>
                      {translated && <div className="mt-1 flex items-start gap-1 border-t border-slate-200 pt-1 text-xs text-slate-600"><Languages size={12} className="mt-0.5 shrink-0" aria-hidden />{translated}</div>}
                      {!!m.tools?.length && <div className="mt-1 flex flex-wrap gap-1">{m.tools.map((tool, i) => <span key={i} className="inline-flex items-center gap-1 rounded-full bg-white px-1.5 py-0.5 text-[10px] text-slate-600 ring-1 ring-slate-200"><Wrench size={9} aria-hidden />{tool.name}: {te('toolStatus', tool.status)}</span>)}</div>}
                    </div>
                  )
                })}
              </div>
              {assist.data?.suggested_replies?.length ? <div className="mt-2 flex flex-wrap gap-1.5">{assist.data.suggested_replies.slice(0, 3).map((r) => <button key={r.id} type="button" onClick={() => useReply(r)} title={r.text} className="max-w-full whitespace-normal rounded-xl border border-violet-200 bg-violet-50 px-2.5 py-1 text-left text-xs text-violet-800 hover:bg-violet-100"><Sparkles size={10} className="mr-1 inline" aria-hidden />{te('replyTone', r.tone)}: {r.text}</button>)}</div> : null}
              <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) send() }}>
                <label htmlFor="reply" className="sr-only">{t('Reply to customer')}</label>
                <textarea id="reply" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} disabled={!mine} placeholder={mine ? t('Reply to the customer (output guard checks every message)…') : t('Accept or take over to reply')} className={cx(inputCls, 'resize-none')} />
                <Button type="submit" variant="primary" icon={Send} disabled={!mine || !draft.trim() || busy}>{t('Send')}</Button>
              </form>
              {assist.data?.tone && (assist.data.tone.advice || assist.data.tone.flags?.length) ? <p className="mt-1 text-xs text-amber-700"><Lightbulb size={11} className="mr-1 inline" aria-hidden />{assist.data.tone.advice ?? assist.data.tone.flags?.join(', ')}</p> : null}
            </div>
          )}
        </Card>

        <div>
          <Tabs tabs={[{ id: 'context', label: t('Context package') }, { id: 'assist', label: t('Agent Assist') }, { id: 'actions', label: t('Actions') }]} value={tab} onChange={setTab} />
          {!sel ? <Empty>{t('The context package appears here.')}</Empty> : tab === 'context' ? <ContextPackage pkg={pkg} /> : tab === 'assist' ? <AssistPanel assist={assist} /> : <ActionsPanel convId={sel} agentId={agentId} mine={!!mine} act={act} />}
        </div>
      </div>
    </div>
  )
}

function ContextPackage({ pkg }: { pkg: ReturnType<typeof useApi<Pkg>> }) {
  const { t, te, rich, fmt } = useI18n()
  const p = pkg.data
  if (pkg.loading && !p) return <Spinner />
  if (pkg.error || !p) return <Empty>{t('No handoff package for this conversation (it was not escalated).')}</Empty>
  return (
    <div className="space-y-3">
      <Card title={t('Why you are here')} actions={<Badge tone={TRIGGER_TONE[p.trigger.code] ?? 'slate'}>{te('trigger', p.trigger.code)}</Badge>}>
        <p className="text-sm text-slate-800" data-user-content>{p.summary}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-slate-500"><ClipboardList size={12} aria-hidden />{t('context completeness {pct}% · summary: {source}', { pct: p.completeness, source: te('summarySource', p.summary_source) })}{p.package_ms != null && <> · {t('built in {ms} ms', { ms: fmt.number(p.package_ms) })}</>}</div>
        <div className="mt-1"><Progress value={p.completeness} max={100} tone={p.completeness >= 90 ? 'green' : 'amber'} /></div>
      </Card>
      <Card title={t('Customer & risk')}>
        <div className="flex flex-wrap gap-1.5 text-xs"><Badge tone="blue">{p.customer.first_name ?? t('unverified')}</Badge>{p.customer.tier === 'vip' && <Badge tone="violet">VIP</Badge>}<Badge tone={p.verification.verified ? 'green' : 'amber'}>{p.verification.verified ? t('verified L{level}', { level: p.verification.level }) : t('not verified')}</Badge><Badge tone={sentimentTone(p.sentiment.current)}>{te('emotion', p.sentiment.emotion)} {fmt.fixed(p.sentiment.current, 2)}</Badge>{p.risk_flags.map((r) => <Badge key={r} tone="red"><ShieldAlert size={10} aria-hidden />{te('risk', r)}</Badge>)}</div>
        <p className="mt-2 text-xs text-slate-500">{rich('Routed to <b>{queue}</b> (priority {priority}). Intent: {intent}.', { queue: te('queue', p.routing.queue), priority: p.routing.priority, intent: te('intent', p.intent) })}</p>
      </Card>
      <Card title={t('Already done by the assistant')}>
        {!p.steps_tried.length ? <p className="text-sm text-slate-500">{t('Nothing yet.')}</p> : <ul className="space-y-1 text-sm">{p.steps_tried.map((s, i) => <li key={i} className="flex gap-2"><Badge tone={s.status === 'ok' ? 'green' : 'amber'}>{s.tool}</Badge><span className="text-xs text-slate-600">{s.summary}</span></li>)}</ul>}
      </Card>
      <Card title={t('Suggested resolution')}><p className="text-sm text-slate-800">{p.suggested_resolution}</p>{p.policy_citations.map((c) => <p key={c.ref} className="mt-1.5 rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-900"><b>{c.ref} {c.title}</b> — {c.snippet}</p>)}</Card>
      {!!p.pending_approvals.length && <Card title={t('Pending approvals')}>{p.pending_approvals.map((a) => <p key={a.id} className="text-sm">{te('approvalKind', a.kind)} {fmt.money(a.amount, a.currency)} <Badge tone="amber">{te('approvalStatus', a.status)}</Badge></p>)}</Card>}
    </div>
  )
}

function AssistPanel({ assist }: { assist: ReturnType<typeof useApi<Assist>> }) {
  const { t, te, tl, ts, fmt } = useI18n()
  const a = assist.data
  if (assist.loading && !a) return <Spinner />
  if (!a) return <Empty>{t('No assist data.')}</Empty>
  const show = (k: string, v: unknown): string => {
    if (typeof v === 'boolean') return te('bool', String(v))
    if (v == null) return '—'
    if (typeof v === 'object') return JSON.stringify(v)
    if (k === 'priority') return te('priority', String(v))
    if (k === 'category') return te('formCategory', String(v))
    return ts(String(v))
  }
  return (
    <div className="space-y-3">
      <Card title={t('Next-best-action')} subtitle={t('generated in {ms} ms · every suggestion cites policy', { ms: fmt.number(a.generated_ms) })}>
        <ol className="space-y-2">{a.next_best_actions.map((n) => <li key={n.id} className="rounded-xl border border-slate-200 p-2.5"><div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-900">{n.rank}. {n.title}</span><Badge tone="green">{Math.round(n.confidence * 100)}%</Badge></div><p className="text-xs text-slate-600">{n.rationale}</p>{n.citation && <p className="mt-1 text-[11px] text-blue-700">{t('cites: {title}', { title: n.citation.title })}</p>}</li>)}</ol>
      </Card>
      <Card title={t('Compliance reminders')}><ul className="list-disc space-y-1 pl-4 text-xs text-slate-700">{(a.compliance_reminders as (string | { text?: string })[]).map((r, i) => <li key={i}>{typeof r === 'string' ? r : r.text}</li>)}</ul></Card>
      <Card title={t('Form auto-fill (agent reviews before saving)')}><dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">{Object.entries(a.form_autofill).map(([k, v]) => <div key={k} className="contents"><dt className="text-slate-500">{tl('formField', k, k)}</dt><dd className="truncate font-medium text-slate-800">{show(k, v)}</dd></div>)}</dl></Card>
    </div>
  )
}

function ActionsPanel({ convId, agentId, mine, act }: { convId: string; agentId: string; mine: boolean; act: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const { t } = useI18n()
  const [order, setOrder] = useState('CH-100231')
  const [amount, setAmount] = useState('379')
  const [identifier, setIdentifier] = useState('anna.becker@example.com')
  const [out, setOut] = useState<unknown>(null)
  const run = (tool: string, args: Record<string, unknown>) => act(async () => setOut(await api('/api/tools/execute', { body: { conversation_id: convId, tool, args } })), t('{tool} executed through the policy engine.', { tool }))
  return (
    <div className="space-y-3">
      <Card title={t('Verify the customer (by phone)')} subtitle={t('Links the account; audited; counts as L1')}><div className="flex gap-2"><input value={identifier} onChange={(e) => setIdentifier(e.target.value)} className={inputCls} aria-label={t('E-mail, phone or order id')} /><Button disabled={!mine} onClick={() => act(() => api(`/api/assist/${convId}/link-customer`, { body: { identifier } }), t('Customer linked.'))}>{t('Link')}</Button></div></Card>
      <Card title={t('Policy-guarded tools')} subtitle={t('Same caps, confirmations and audit as the AI')}>
        <div className="grid grid-cols-2 gap-2"><input value={order} onChange={(e) => setOrder(e.target.value)} className={inputCls} aria-label={t('Order id')} /><input value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} aria-label={t('Amount in EUR')} /></div>
        <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" disabled={!mine} onClick={() => run('issue_refund', { order_id: order, amount: Number(amount), reason: t('agent-initiated refund') })}>{t('Issue refund')}</Button><Button size="sm" disabled={!mine} onClick={() => run('goodwill_credit', { order_id: order, amount: Number(amount), reason: t('agent goodwill') })}>{t('Goodwill credit')}</Button><Button size="sm" disabled={!mine} onClick={() => run('lookup_order', { order_id: order })}>{t('Look up order')}</Button></div>
        {out != null && <pre data-i18n-skip className="scroll-thin mt-2 max-h-44 overflow-auto rounded-lg bg-slate-900 p-2 text-[11px] text-slate-100">{JSON.stringify(out, null, 2).slice(0, 1400)}</pre>}
        <p className="mt-2 text-[11px] text-slate-500">{t('Acting as {agent}. Refunds above the cap create an approval for a supervisor (see Supervisor console).', { agent: agentId })}</p>
      </Card>
    </div>
  )
}
