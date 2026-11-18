import { useEffect, useRef, useState } from 'react'
import { Mono } from '../../components/bits'
import { Badge, Button, Card, Page } from '../../components/ui'
import { postSSE } from '../../lib/api'
import { usePApi, usePlant, withPlant } from '../../plant'

type Msg = { role: 'user' | 'assistant'; content: string; cites?: { ref?: string; id?: string }[]; tools?: string[]; meta?: string }
const SUGGEST = [
  'Why is the plant running this way right now?',
  'Which assets look unhealthy and what is being done about them?',
  'What did the agents decide in the last hour, and was it approved by a human?',
  'What happens to on-time delivery if CNC-04 goes down for an hour?',
  'Summarise energy cost and carbon so far this shift.',
]

export default function Copilot() {
  const { plantId } = usePlant()
  const tools = usePApi<{ name: string; description: string }[]>('/api/copilot/tools')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ctl = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => () => ctl.current?.abort(), [])
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }) }, [msgs]) // scroll the chat, not the page

  const ask = async (text: string) => {
    if (!text.trim() || busy) return
    const history = [...msgs, { role: 'user' as const, content: text }]
    setMsgs([...history, { role: 'assistant', content: '', tools: [] }])
    setQ('')
    setBusy(true)
    setError('')
    ctl.current = new AbortController()
    const patch = (fn: (m: Msg) => Msg) => setMsgs((all) => all.map((m, i) => (i === all.length - 1 ? fn(m) : m)))
    try {
      await postSSE(withPlant('/api/copilot/chat', plantId), { messages: history.map(({ role, content }) => ({ role, content })).slice(-10) }, (ev, d) => {
        if (ev === 'token') patch((m) => ({ ...m, content: m.content + d.text }))
        else if (ev === 'tool_call') patch((m) => ({ ...m, tools: [...(m.tools ?? []), d.name] }))
        else if (ev === 'citations') patch((m) => ({ ...m, cites: d.citations }))
        else if (ev === 'done') patch((m) => ({ ...m, meta: `${d.mode}${d.model ? ' · ' + d.model : ''}` }))
        else if (ev === 'error') setError(d.message)
      }, ctl.current.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Page title="Ask the Factory" subtitle="A copilot that answers only from live tools - KPIs, assets, the decision ledger, the twin and what-if - and cites what it used. It is read-only: it can run a what-if, but it cannot change the plant. Works with Azure OpenAI tool calling, or a deterministic planner when the model is unreachable or the AI budget is spent.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card title="Conversation" pad={false} right={<Button size="sm" tone="ghost" onClick={() => setMsgs([])}>Clear</Button>}>
          <div className="flex h-[560px] flex-col">
            <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
              {msgs.length === 0 && (
                <div className="space-y-2 text-sm text-mute">
                  <p>Try one of these:</p>
                  <div className="flex flex-wrap gap-2">{SUGGEST.map((s) => <button key={s} onClick={() => void ask(s)} className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-left text-[13px] text-ink hover:border-accent">{s}</button>)}</div>
                </div>
              )}
              {msgs.map((m, i) => (
                <div key={i} className={m.role === 'user' ? 'ml-auto max-w-[80%] rounded-xl bg-accent/15 px-3 py-2 text-sm' : 'max-w-[92%] rounded-xl border border-line bg-panel2/60 px-3 py-2 text-sm'}>
                  {m.role === 'assistant' && (m.tools?.length ?? 0) > 0 && <div className="mb-1 flex flex-wrap gap-1">{m.tools!.map((t, k) => <Mono key={k}>{t}()</Mono>)}</div>}
                  <div className="whitespace-pre-wrap leading-snug">{m.content || (busy && i === msgs.length - 1 ? '…' : '')}</div>
                  {m.cites && m.cites.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{m.cites.map((c, k) => <Badge key={k} tone="info">{c.ref ?? c.id ?? JSON.stringify(c)}</Badge>)}</div>}
                  {m.meta && <div className="mt-1 text-[10px] text-mute">{m.meta}</div>}
                </div>
              ))}
            </div>
            {error && <p role="alert" className="px-4 text-xs text-bad">{error}</p>}
            <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); void ask(q) }}>
              <input aria-label="Ask the factory" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about assets, decisions, KPIs, or a what-if…" className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-3 py-2 text-sm" />
              <Button tone="primary" type="submit" disabled={busy || !q.trim()}>{busy ? 'Thinking…' : 'Ask'}</Button>
            </form>
          </div>
        </Card>
        <Card title="Tools the copilot may call (read-only)">
          <ul className="space-y-2 text-[12px]">{(tools.data ?? []).map((t) => <li key={t.name}><Mono>{t.name}</Mono><div className="text-mute">{t.description}</div></li>)}</ul>
          <p className="mt-3 text-[11px] text-mute">Every answer carries citations to assets, ledger entries and KPI windows. Tool results are the only facts the model sees.</p>
        </Card>
      </div>
    </Page>
  )
}
