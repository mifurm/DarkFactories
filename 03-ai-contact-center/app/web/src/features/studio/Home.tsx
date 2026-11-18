import { ArrowRight, Headphones, LayoutDashboard, MessageSquare, Play, ShieldCheck, TrendingUp, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { N_, useI18n } from '../../i18n'
import { api, describeError, useApi, withLang } from '../../lib/api'
import { Badge, Button, Card, PageHeader, Stat, cx } from '../../lib/ui'

interface PlayState { status: string; scenario?: string; conversation_id?: string; passed?: boolean; handoff?: boolean; error?: string }

const PLAYS = [
  { id: 'S01', label: N_('Damaged sofa (German) → refund + pickup'), hint: N_('resolved by the AI, no human') },
  { id: 'S19', label: N_('Legal threat → warm handoff'), hint: N_('lands in the escalations queue with a context package') },
  { id: 'S03', label: N_('Above-cap mattress refund (Spanish)'), hint: N_('needs supervisor approval') },
]
// the Polish demo set (scenario pack `pl`) is offered when the console is Polish
const PLAYS_PL = [
  { id: 'PL-01', label: N_('Damaged sofa (Polish) → refund + pickup'), hint: N_('resolved by the AI, no human') },
  { id: 'PL-03', label: N_('Legal threat (Polish) → warm handoff'), hint: N_('lands in the escalations queue with a context package') },
  { id: 'PL-09', label: N_('Unanswerable question (Polish) → “I don’t know” and a colleague'), hint: N_('the agent does not guess and offers a person') },
  { id: 'PL-11', label: N_('Prompt injection (Polish) → refused'), hint: N_('the guard neutralises it, no tool is called') },
]

function PlayDemo() {
  const { t, tr, lang } = useI18n()
  const plays = lang === 'pl' ? PLAYS_PL : PLAYS
  const [states, setStates] = useState<Record<string, PlayState>>({})
  const [err, setErr] = useState<string | null>(null)
  const timers = useRef<number[]>([])
  useEffect(() => () => timers.current.forEach((x) => window.clearInterval(x)), [])
  const start = async (id: string) => {
    setErr(null)
    setStates((s) => ({ ...s, [id]: { status: 'running' } }))
    try {
      await api<PlayState>('/api/evals/play', { body: { scenario_id: id } })
      const timer = window.setInterval(async () => {
        const r = await api<PlayState>(`/api/evals/play/${id}`).catch(() => null)
        if (r && r.status !== 'running') {
          window.clearInterval(timer)
          setStates((s) => ({ ...s, [id]: r }))
        }
      }, 2000)
      timers.current.push(timer)
    } catch (e) {
      setStates((s) => ({ ...s, [id]: { status: 'error' } }))
      setErr(describeError(e))
    }
  }
  return (
    <Card className="mt-4" title={t('Play a scenario against the live app')} subtitle={t('a scripted customer chats with the real agent; the conversation then appears in the agent console, supervisor view, QA workbench and VoC')}>
      <ul className={cx('grid gap-3', plays.length > 3 ? 'md:grid-cols-2 xl:grid-cols-4' : 'md:grid-cols-3')}>
        {plays.map((p) => {
          const s = states[p.id]
          return (
            <li key={p.id} className="rounded-xl border border-slate-200 p-3">
              <div className="text-sm font-semibold text-slate-900">{tr(p.label)}</div>
              <div className="mb-2 text-xs text-slate-500">{tr(p.hint)}</div>
              <Button size="sm" variant="primary" icon={Play} busy={s?.status === 'running'} onClick={() => start(p.id)}>
                {t('Play {id}', { id: p.id })}
              </Button>
              {s?.status === 'done' && s.conversation_id && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={s.passed ? 'green' : 'amber'}>{s.passed ? t('as expected') : t('deviated')}</Badge>
                  {s.handoff && <Badge tone="violet">{t('handoff')}</Badge>}
                  <Link className="font-medium text-blue-700 hover:underline" to={`/agent?conversation=${s.conversation_id}`}>{t('console')}</Link>
                  <a className="font-medium text-blue-700 hover:underline" href={withLang(`/widget?c=${s.conversation_id}`)} target="_blank" rel="noreferrer">{t('customer view')}</a>
                </div>
              )}
              {s?.status === 'error' && <p className="mt-2 text-xs text-rose-700">{s.error ?? t('failed')}</p>}
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
  {
    n: 1,
    to: '/widget',
    icon: MessageSquare,
    title: N_('Customer widget — chat or “Call us”'),
    text: N_('In German: “Mein Sofa ist beschädigt angekommen.” The Greeter detects the language, the Authentication agent verifies via OTP, the Resolution agent cites the damage policy, enforces the refund cap, books the pickup and wraps up — no human.'),
  },
  {
    n: 2,
    to: '/agent',
    icon: Headphones,
    title: N_('Human-agent console — warm handoff'),
    text: N_('A second customer is angry and mentions legal action. Sentiment + legal-risk trigger a warm handoff: the console already shows the summary, steps tried, sentiment, suggested resolution and policy citations while Agent Assist whispers next-best-actions.'),
  },
  { n: 3, to: '/supervisor', icon: Users, title: N_('Supervisor console'), text: N_('Live queues, containment, SLA-risk alerts, take-over / whisper / approve above-cap refunds.') },
  { n: 4, to: '/qa', icon: ShieldCheck, title: N_('QA workbench & VoC'), text: N_('100 % of conversations auto-scored with evidence; VoC flags the “damaged on delivery” spike for one carrier.') },
  { n: 5, to: '/metrics', icon: TrendingUp, title: N_('CX metrics, WFM and the ROI / ACR view'), text: N_('Cost per resolved contact vs baseline, staffing what-ifs with AI containment, and the ROI & Azure-consumption calculator.') },
]

export default function Home() {
  const { t, tr, te, ts, fmt } = useI18n()
  const meta = useApi<Meta>('/api/meta')
  return (
    <div>
      <PageHeader
        icon={LayoutDashboard}
        title={t('Concierge — the AI-first contact center')}
        subtitle={t('Every contact starts with an AI agent that can actually resolve — grounded in knowledge and able to act through policy-guarded tools. Humans become the escalation and expertise layer. Quality is measured on 100 % of interactions.')}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t('Mode')} value={meta.data ? te('mode', meta.data.mode) : '…'} hint={meta.data ? t('LLM: {llm}', { llm: meta.data.llm }) : undefined} />
        <Stat label={t('Features live')} value={meta.data ? `${fmt.number(meta.data.features)} / 24` : '…'} hint={t('see Feature map')} />
        <Stat label={t('Chat model')} value={meta.data?.deployments?.chat ?? '…'} />
        <Stat label={t('Voice model')} value={meta.data?.deployments?.realtime ?? '…'} hint={t('Azure OpenAI Realtime')} />
      </div>
      <Card title={t('Guided demo — the narrative, end to end')} subtitle={t('Contoso Home Retail (fictional omnichannel retailer with delivery & installation)')}>
        <ol className="space-y-3">
          {STEPS.map((s) => (
            <li key={s.n} className="flex gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-blue-600 text-sm font-semibold text-white">{s.n}</span>
              <div className="flex-1">
                <Link to={s.to} className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:underline">
                  <s.icon size={14} aria-hidden /> {tr(s.title)} <ArrowRight size={12} aria-hidden />
                </Link>
                <p className="text-sm text-slate-600">{tr(s.text)}</p>
              </div>
            </li>
          ))}
        </ol>
      </Card>
      <PlayDemo />
      <Card className="mt-4" title={t('What is real and what is simulated')}>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li>
            <b>{t('Real (azure mode):')}</b> {t('Azure OpenAI chat + Realtime voice, embeddings, Azure AI Speech, Azure AI Language, Azure AI Content Safety, Cosmos DB, Blob Storage, App Insights — all via managed identity, no keys.')}
          </li>
          {(meta.data?.simulated ?? []).map((s) => (
            <li key={s}>
              <Badge tone="amber">{t('simulated')}</Badge> {ts(s)}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
