import { ArrowRight, Headphones, LayoutDashboard, MessageSquare, Play, ShieldCheck, TrendingUp, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, useApi } from '../../lib/api'
import { Badge, Button, Card, PageHeader, Stat } from '../../lib/ui'

interface PlayState { status: string; scenario?: string; conversation_id?: string; passed?: boolean; handoff?: boolean; error?: string }

const PLAYS = [
  { id: 'S01', label: 'Damaged sofa (German) → refund + pickup', hint: 'resolved by the AI, no human' },
  { id: 'S19', label: 'Legal threat → warm handoff', hint: 'lands in the escalations queue with a context package' },
  { id: 'S03', label: 'Above-cap mattress refund (Spanish)', hint: 'needs supervisor approval' },
]

function PlayDemo() {
  const [states, setStates] = useState<Record<string, PlayState>>({})
  const [err, setErr] = useState<string | null>(null)
  const timers = useRef<number[]>([])
  useEffect(() => () => timers.current.forEach((t) => window.clearInterval(t)), [])
  const start = async (id: string) => {
    setErr(null)
    setStates((s) => ({ ...s, [id]: { status: 'running' } }))
    try {
      await api<PlayState>('/api/evals/play', { body: { scenario_id: id } })
      const t = window.setInterval(async () => {
        const r = await api<PlayState>(`/api/evals/play/${id}`).catch(() => null)
        if (r && r.status !== 'running') {
          window.clearInterval(t)
          setStates((s) => ({ ...s, [id]: r }))
        }
      }, 2000)
      timers.current.push(t)
    } catch (e) {
      setStates((s) => ({ ...s, [id]: { status: 'error' } }))
      setErr(e instanceof ApiError ? JSON.stringify(e.body) : String(e))
    }
  }
  return (
    <Card className="mt-4" title="Play a scenario against the live app" subtitle="a scripted customer chats with the real agent; the conversation then appears in the agent console, supervisor view, QA workbench and VoC">
      <ul className="grid gap-3 md:grid-cols-3">
        {PLAYS.map((p) => {
          const s = states[p.id]
          return (
            <li key={p.id} className="rounded-xl border border-slate-200 p-3">
              <div className="text-sm font-semibold text-slate-900">{p.label}</div>
              <div className="mb-2 text-xs text-slate-500">{p.hint}</div>
              <Button size="sm" variant="primary" icon={Play} busy={s?.status === 'running'} onClick={() => start(p.id)}>
                Play {p.id}
              </Button>
              {s?.status === 'done' && s.conversation_id && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={s.passed ? 'green' : 'amber'}>{s.passed ? 'as expected' : 'deviated'}</Badge>
                  {s.handoff && <Badge tone="violet">handoff</Badge>}
                  <Link className="font-medium text-blue-700 hover:underline" to={`/agent?conversation=${s.conversation_id}`}>console</Link>
                  <a className="font-medium text-blue-700 hover:underline" href={`/widget?c=${s.conversation_id}`} target="_blank" rel="noreferrer">customer view</a>
                </div>
              )}
              {s?.status === 'error' && <p className="mt-2 text-xs text-rose-700">{s.error ?? 'failed'}</p>}
            </li>
          )
        })}
      </ul>
      {err && <p role="alert" className="mt-2 text-xs text-rose-700">{err}</p>}
    </Card>
  )
}

interface Meta {
  mode: string
  features: number
  llm: string
  deployments: Record<string, string>
  seed: { status: string }
  simulated: string[]
}

const STEPS = [
  { n: 1, to: '/widget', icon: MessageSquare, title: 'Customer widget — chat or “Call us”', text: 'In German: “Mein Sofa ist beschädigt angekommen.” The Greeter detects the language, the Authentication agent verifies via OTP, the Resolution agent cites the damage policy, enforces the refund cap, books the pickup and wraps up — no human.' },
  { n: 2, to: '/agent', icon: Headphones, title: 'Human-agent console — warm handoff', text: 'A second customer is angry and mentions legal action. Sentiment + legal-risk trigger a warm handoff: the console already shows the summary, steps tried, sentiment, suggested resolution and policy citations while Agent Assist whispers next-best-actions.' },
  { n: 3, to: '/supervisor', icon: Users, title: 'Supervisor console', text: 'Live queues, containment, SLA-risk alerts, take-over / whisper / approve above-cap refunds.' },
  { n: 4, to: '/qa', icon: ShieldCheck, title: 'QA workbench & VoC', text: '100 % of conversations auto-scored with evidence; VoC flags the “damaged on delivery” spike for one carrier.' },
  { n: 5, to: '/metrics', icon: TrendingUp, title: 'CX metrics, WFM and the ROI / ACR view', text: 'Cost per resolved contact vs baseline, staffing what-ifs with AI containment, and the ROI & Azure-consumption calculator.' },
]

export default function Home() {
  const meta = useApi<Meta>('/api/meta')
  return (
    <div>
      <PageHeader
        icon={LayoutDashboard}
        title="Concierge — the AI-first contact center"
        subtitle="Every contact starts with an AI agent that can actually resolve — grounded in knowledge and able to act through policy-guarded tools. Humans become the escalation and expertise layer. Quality is measured on 100 % of interactions."
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Mode" value={meta.data?.mode ?? '…'} hint={meta.data ? `LLM: ${meta.data.llm}` : undefined} />
        <Stat label="Features live" value={meta.data ? `${meta.data.features} / 24` : '…'} hint="see Feature map" />
        <Stat label="Chat model" value={meta.data?.deployments?.chat ?? '…'} />
        <Stat label="Voice model" value={meta.data?.deployments?.realtime ?? '…'} hint="Azure OpenAI Realtime" />
      </div>
      <Card title="Guided demo — the narrative, end to end" subtitle="Contoso Home Retail (fictional omnichannel retailer with delivery & installation)">
        <ol className="space-y-3">
          {STEPS.map((s) => (
            <li key={s.n} className="flex gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-blue-600 text-sm font-semibold text-white">{s.n}</span>
              <div className="flex-1">
                <Link to={s.to} className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:underline">
                  <s.icon size={14} aria-hidden /> {s.title} <ArrowRight size={12} aria-hidden />
                </Link>
                <p className="text-sm text-slate-600">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </Card>
      <PlayDemo />
      <Card className="mt-4" title="What is real and what is simulated">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li>
            <b>Real (azure mode):</b> Azure OpenAI chat + Realtime voice, embeddings, Azure AI Speech, Azure AI Language, Azure AI Content Safety, Cosmos DB, Blob Storage, App Insights — all via managed identity, no keys.
          </li>
          {(meta.data?.simulated ?? []).map((s) => (
            <li key={s}>
              <Badge tone="amber">simulated</Badge> {s}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
