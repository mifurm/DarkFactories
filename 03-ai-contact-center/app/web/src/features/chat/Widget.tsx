import { Bot, Download, Headphones, Mic, PhoneCall, RefreshCw, Send, ShieldCheck, Smartphone, User, UserCheck, Wrench } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { N_, i18nFor, type Lang, type Vars } from '../../i18n'
import { CONV_LANGS, useConversationLang } from '../../i18n/useConversationLang'
import { api, describeError, withLang, wsUrl } from '../../lib/api'
import { Badge, Button, cx } from '../../lib/ui'

interface Citation { ref: string; title: string; chunk_id: string; snippet?: string }
interface ToolRec { name: string; status: string }
interface Msg { id?: string; idx?: number; role: string; text: string; citations?: Citation[]; tools?: ToolRec[]; flags?: string[]; streaming?: boolean }
interface Pending { action_id: string; summary: string; tool: string; confirmed: boolean }
interface OutboxItem { kind: string; channel: string; to: string; body: string; code?: string }
interface Session {
  id: string
  status: string
  language: string
  messages: Msg[]
  pending: Pending[]
  outbox: OutboxItem[]
  identity: { verified: boolean; level: number }
  handoff: { state: string; queue: string; est_wait_min: number; trigger: string } | null
  agent: { id: string; name: string } | null
  consent: { recording: string }
}

// English and Polish labels come from the i18n dictionaries (UI language = widget language);
// the six other conversation languages keep their built-in label sets below.
const L = {
  title: N_('Contoso Home — Concierge'),
  sub: N_('AI assistant · a colleague is always one tap away'),
  ph: N_('Write a message…'),
  send: N_('Send'),
  ctitle: N_('Before we start'),
  cbody: N_('You are chatting with an AI assistant. The conversation may be recorded and analysed to improve our service.'),
  accept: N_('Accept & start'),
  decline: N_('Decline recording'),
  call: N_('Call us'),
  confirm: N_('Confirm'),
  cancel: N_('Not now'),
  ctrl: N_('Please confirm this action'),
  phone: N_('Your phone (simulated SMS)'),
  newc: N_('New chat'),
  dl: N_('Transcript'),
  verified: N_('Verified'),
  waiting: N_('A colleague will join shortly'),
  yes: N_('Yes, please go ahead.'),
}
type LabelKey = keyof typeof L

const LEGACY: Record<string, Record<LabelKey, string>> = {
  de: { title: 'Contoso Home — Concierge', sub: 'KI-Assistent · ein Kollege ist immer nur einen Klick entfernt', ph: 'Nachricht schreiben…', send: 'Senden', ctitle: 'Bevor wir starten', cbody: 'Sie chatten mit einem KI-Assistenten. Das Gespräch kann zur Qualitätssicherung aufgezeichnet und ausgewertet werden.', accept: 'Akzeptieren & starten', decline: 'Aufzeichnung ablehnen', call: 'Anrufen', confirm: 'Bestätigen', cancel: 'Jetzt nicht', ctrl: 'Bitte bestätigen Sie diese Aktion', phone: 'Ihr Handy (simulierte SMS)', newc: 'Neuer Chat', dl: 'Protokoll', verified: 'Verifiziert', waiting: 'Ein Kollege ist gleich bei Ihnen', yes: 'Ja, bitte so machen.' },
  fr: { title: 'Contoso Home — Concierge', sub: 'Assistant IA · un conseiller est toujours à portée de clic', ph: 'Écrivez un message…', send: 'Envoyer', ctitle: 'Avant de commencer', cbody: 'Vous échangez avec un assistant IA. La conversation peut être enregistrée et analysée pour améliorer notre service.', accept: 'Accepter et démarrer', decline: "Refuser l'enregistrement", call: 'Appeler', confirm: 'Confirmer', cancel: 'Pas maintenant', ctrl: 'Merci de confirmer cette action', phone: 'Votre téléphone (SMS simulé)', newc: 'Nouveau chat', dl: 'Transcription', verified: 'Vérifié', waiting: 'Un conseiller arrive', yes: 'Oui, allez-y.' },
  es: { title: 'Contoso Home — Concierge', sub: 'Asistente de IA · un compañero siempre a un clic', ph: 'Escriba un mensaje…', send: 'Enviar', ctitle: 'Antes de empezar', cbody: 'Está hablando con un asistente de IA. La conversación puede grabarse y analizarse para mejorar el servicio.', accept: 'Aceptar y empezar', decline: 'Rechazar grabación', call: 'Llamar', confirm: 'Confirmar', cancel: 'Ahora no', ctrl: 'Confirme esta acción', phone: 'Su teléfono (SMS simulado)', newc: 'Nuevo chat', dl: 'Transcripción', verified: 'Verificado', waiting: 'Un compañero se unirá enseguida', yes: 'Sí, adelante.' },
  it: { title: 'Contoso Home — Concierge', sub: 'Assistente IA · un collega è sempre a un clic', ph: 'Scrivi un messaggio…', send: 'Invia', ctitle: 'Prima di iniziare', cbody: 'Stai parlando con un assistente IA. La conversazione può essere registrata e analizzata per migliorare il servizio.', accept: 'Accetta e inizia', decline: 'Rifiuta la registrazione', call: 'Chiama', confirm: 'Conferma', cancel: 'Non ora', ctrl: 'Conferma questa azione', phone: 'Il tuo telefono (SMS simulato)', newc: 'Nuova chat', dl: 'Trascrizione', verified: 'Verificato', waiting: 'Un collega arriva a breve', yes: 'Sì, procedi.' },
  nl: { title: 'Contoso Home — Concierge', sub: 'AI-assistent · een collega is altijd dichtbij', ph: 'Schrijf een bericht…', send: 'Verstuur', ctitle: 'Voor we beginnen', cbody: 'U chat met een AI-assistent. Het gesprek kan worden opgenomen en geanalyseerd om de service te verbeteren.', accept: 'Accepteren en starten', decline: 'Opname weigeren', call: 'Bel ons', confirm: 'Bevestigen', cancel: 'Nu niet', ctrl: 'Bevestig deze actie', phone: 'Uw telefoon (gesimuleerde sms)', newc: 'Nieuwe chat', dl: 'Transcript', verified: 'Geverifieerd', waiting: 'Een collega komt zo', yes: 'Ja, graag.' },
  pt: { title: 'Contoso Home — Concierge', sub: 'Assistente de IA · um colega está sempre à distância de um clique', ph: 'Escreva uma mensagem…', send: 'Enviar', ctitle: 'Antes de começar', cbody: 'Está a falar com um assistente de IA. A conversa pode ser gravada e analisada para melhorar o serviço.', accept: 'Aceitar e começar', decline: 'Recusar gravação', call: 'Ligar', confirm: 'Confirmar', cancel: 'Agora não', ctrl: 'Confirme esta ação', phone: 'O seu telemóvel (SMS simulado)', newc: 'Nova conversa', dl: 'Transcrição', verified: 'Verificado', waiting: 'Um colega junta-se já', yes: 'Sim, pode avançar.' },
}
const SUGGEST_BASE = [N_('My sofa arrived damaged (order CH-100231)'), N_('Where is my order CH-100232?'), N_('What is your return policy?'), N_('I want to talk to a person')]
const LEGACY_SUGGEST: Record<string, string[]> = {
  de: ['Mein Sofa ist beschädigt angekommen. Bestellnummer CH-100231.', 'Wo ist meine Bestellung CH-100232?', 'Wie lange habe ich Rückgaberecht?', 'Ich möchte mit einem Mitarbeiter sprechen'],
  fr: ['Mon canapé est arrivé endommagé (commande CH-100231)', 'Où est ma commande CH-100232 ?', 'Quelle est votre politique de retour ?', 'Je veux parler à un conseiller'],
  es: ['Mi sofá llegó dañado (pedido CH-100231)', '¿Dónde está mi pedido CH-100232?', '¿Cuál es su política de devolución?', 'Quiero hablar con una persona'],
  it: ['Il mio divano è arrivato danneggiato (ordine CH-100231)', "Dov'è il mio ordine CH-100232?", 'Qual è la vostra politica di reso?', 'Vorrei parlare con un operatore'],
  nl: ['Mijn bank is beschadigd aangekomen (CH-100231)', 'Waar is mijn bestelling CH-100232?', 'Wat is jullie retourbeleid?', 'Ik wil een medewerker spreken'],
  pt: ['O meu sofá chegou danificado (encomenda CH-100231)', 'Onde está a minha encomenda CH-100232?', 'Qual é a política de devoluções?', 'Quero falar com uma pessoa'],
}

function Bubble({ m }: { m: Msg }) {
  const mine = m.role === 'customer'
  const sys = m.role === 'system_notice'
  if (sys) return <div className="my-2 text-center text-xs text-slate-500">— {m.text} —</div>
  return (
    <div className={cx('flex gap-2', mine ? 'flex-row-reverse' : '')}>
      <span className={cx('mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white', mine ? 'bg-slate-500' : m.role === 'agent_human' ? 'bg-emerald-600' : 'bg-gradient-to-br from-blue-600 to-violet-600')} aria-hidden>
        {mine ? <User size={14} /> : m.role === 'agent_human' ? <UserCheck size={14} /> : <Bot size={14} />}
      </span>
      <div className={cx('max-w-[82%] rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm', mine ? 'rounded-tr-sm bg-blue-600 text-white' : 'rounded-tl-sm border border-slate-200 bg-white text-slate-800')}>
        <div className="whitespace-pre-wrap">{m.text.replace(/\*\*(.+?)\*\*/g, '$1')}{m.streaming && <span className="typing-dot ml-0.5">▍</span>}</div>
        {!!m.tools?.length && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {m.tools.map((tool, i) => (
              <span key={i} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600"><Wrench size={9} aria-hidden />{tool.name}</span>
            ))}
          </div>
        )}
        {!!m.citations?.length && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {m.citations.map((c) => (
              <span key={c.chunk_id} title={c.snippet} className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{c.ref} {c.title}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Widget() {
  const [params] = useSearchParams()
  const { conv, choose } = useConversationLang(params)
  const loc: Lang = conv === 'pl' ? 'pl' : 'en'
  // reads the language at call time, so callbacks created earlier (WebSocket handlers) never show a stale language
  const locRef = useRef<Lang>(loc)
  locRef.current = loc
  const tw = (key: string, vars?: Vars) => i18nFor(locRef.current).tr(key, vars)
  const trw = (key: string) => i18nFor(locRef.current).tr(key)
  const label = (k: LabelKey) => LEGACY[conv]?.[k] ?? trw(L[k])
  const suggestions = LEGACY_SUGGEST[conv] ?? SUGGEST_BASE.map((s) => trw(s))
  const [consent, setConsent] = useState<'pending' | 'granted' | 'declined'>(params.get('c') ? 'granted' : 'pending')
  const [sess, setSess] = useState<Session | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState<string | null>(null)
  const [agentLabel, setAgentLabel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const ws = useRef<WebSocket | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const streamRef = useRef('')

  const refresh = useCallback(async (id: string) => {
    const r = await api<{ session: Session }>(`/api/chat/sessions/${id}`, { role: 'customer' })
    setSess(r.session)
    setMsgs((cur) => {
      const streaming = cur.find((m) => m.streaming)
      return streaming ? [...r.session.messages, streaming] : r.session.messages
    })
  }, [])

  const connect = useCallback(
    (id: string) => {
      const sock = new WebSocket(wsUrl(`/ws/chat/${id}`))
      ws.current = sock
      sock.onmessage = (e) => {
        const ev = JSON.parse(e.data) as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
        switch (ev.type) {
          case 'state':
            setSess(ev.session)
            setMsgs(ev.session.messages)
            break
          case 'token':
            streamRef.current += ev.text
            setMsgs((cur) => {
              const rest = cur.filter((m) => !m.streaming)
              return [...rest, { role: 'agent_ai', text: streamRef.current, streaming: true }]
            })
            break
          case 'replace':
            streamRef.current = ev.text
            setMsgs((cur) => cur.map((m) => (m.streaming ? { ...m, text: ev.text } : m)))
            break
          case 'tool_start':
            setActivity(ev.name)
            break
          case 'agent':
            setAgentLabel(ev.agent)
            break
          case 'message':
            if (ev.message.role !== 'customer') {
              streamRef.current = ''
              setMsgs((cur) => [...cur.filter((m) => !m.streaming && !(m.idx !== undefined && m.idx === ev.message.idx)), ev.message])
            }
            break
          case 'turn_done':
            setBusy(false)
            setActivity(null)
            refresh(id).catch(() => undefined)
            break
          case 'handoff':
          case 'status':
            refresh(id).catch(() => undefined)
            break
          case 'error':
            setBusy(false)
            setError(ev.error === 'conversation_closed' ? tw('This conversation has ended.') : tw('Error: {error}', { error: ev.error }))
            break
        }
      }
      sock.onclose = () => {
        if (ws.current === sock) ws.current = null
      }
    },
    [refresh],
  )

  const start = useCallback(
    async (c: 'granted' | 'declined') => {
      setConsent(c)
      setError(null)
      try {
        const r = await api<{ session: Session }>('/api/chat/sessions', { body: { language: conv, recording_consent: c }, role: 'customer' })
        setSess(r.session)
        setMsgs(r.session.messages)
        connect(r.session.id)
      } catch (e) {
        setError(describeError(e))
      }
    },
    [conv, connect],
  )

  useEffect(() => {
    const c = params.get('c')
    if (c) {
      refresh(c).then(() => connect(c)).catch(() => setError(tw('Conversation not found')))
    }
    return () => ws.current?.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs, busy])

  const send = async (raw: string) => {
    const v = raw.trim()
    if (!v || !sess || busy) return
    setText('')
    setBusy(true)
    streamRef.current = ''
    setMsgs((cur) => [...cur, { role: 'customer', text: v }])
    // `language` lets the server follow a language switched mid-session (ignored by servers that detect it per message)
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify({ type: 'message', text: v, language: conv }))
    else {
      try {
        await api(`/api/chat/sessions/${sess.id}/messages`, { body: { text: v, language: conv }, role: 'customer' })
        await refresh(sess.id)
      } catch (e) {
        setError(describeError(e))
      }
      setBusy(false)
    }
  }
  const decide = async (accept: boolean) => {
    if (!sess) return
    await api(`/api/chat/sessions/${sess.id}/confirm`, { body: { accept }, role: 'customer' })
    if (accept) await send(label('yes'))
    else await refresh(sess.id)
  }
  const reset = () => {
    ws.current?.close()
    setSess(null)
    setMsgs([])
    setConsent('pending')
    setError(null)
  }
  const otp = useMemo(() => [...(sess?.outbox ?? [])].reverse().find((o) => o.kind === 'otp'), [sess])
  const ended = sess && ['closed', 'resolved'].includes(sess.status)

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col gap-4 p-4 md:h-screen md:flex-row">
      <main className="flex min-h-[560px] flex-1 flex-col overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 shadow-xl md:min-h-0" aria-label={tw('Customer chat')}>
        <header className="flex flex-wrap items-center justify-between gap-2 bg-gradient-to-r from-ink to-ink-2 px-4 py-3 text-white">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/15"><Headphones size={18} aria-hidden /></span>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold">{label('title')}</h1>
              <p className="text-[11px] text-blue-100">{label('sub')}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="lang">{tw('Language')}</label>
            <select id="lang" data-testid="widget-lang" value={conv} onChange={(e) => choose(e.target.value)} className="rounded-lg border border-white/20 bg-white/10 px-2 py-1 text-xs text-white [&>option]:text-slate-900">
              {Object.entries(CONV_LANGS).map(([k, v]) => <option key={k} value={k} lang={k}>{v}</option>)}
            </select>
            {sess && (
              <Link to={`/call?c=${sess.id}&lang=${conv}`} className="inline-flex items-center gap-1 rounded-lg bg-white/15 px-2.5 py-1.5 text-xs font-medium hover:bg-white/25"><PhoneCall size={13} aria-hidden />{label('call')}</Link>
            )}
          </div>
        </header>

        {consent === 'pending' && !sess ? (
          <div className="m-auto max-w-sm p-6 text-center">
            <ShieldCheck className="mx-auto mb-2 text-blue-600" size={32} aria-hidden />
            <h2 className="text-lg font-semibold text-slate-900">{label('ctitle')}</h2>
            <p className="mt-2 text-sm text-slate-600">{label('cbody')}</p>
            <div className="mt-4 flex flex-col gap-2">
              <Button variant="primary" onClick={() => start('granted')}>{label('accept')}</Button>
              <Button onClick={() => start('declined')}>{label('decline')}</Button>
              <Link to={`/call?lang=${conv}`} className="mt-1 inline-flex items-center justify-center gap-1.5 text-sm font-medium text-blue-700 hover:underline"><Mic size={14} aria-hidden />{label('call')}</Link>
            </div>
          </div>
        ) : (
          <>
            <div className="scroll-thin flex-1 space-y-3 overflow-y-auto px-3 py-4" role="log" aria-live="polite" aria-relevant="additions" aria-label={tw('Conversation')}>
              {msgs.map((m, i) => <Bubble key={m.id ?? i} m={m} />)}
              {busy && !msgs.some((m) => m.streaming) && (
                <div className="flex items-center gap-2 text-xs text-slate-500" aria-label={tw('Assistant is typing')}>
                  <span className="typing-dot">●</span><span className="typing-dot" style={{ animationDelay: '.2s' }}>●</span><span className="typing-dot" style={{ animationDelay: '.4s' }}>●</span>
                  {activity && <Badge tone="slate"><Wrench size={10} aria-hidden /> {activity}</Badge>}
                  {agentLabel && <span>{agentLabel}</span>}
                </div>
              )}
              {(sess?.pending?.filter((p) => !p.confirmed).length ?? 0) > 0 && (
                <div className="rounded-2xl border border-amber-300 bg-amber-50 p-3 text-sm shadow-sm" role="group" aria-label={label('ctrl')}>
                  <div className="mb-1 flex items-center gap-1.5 font-semibold text-amber-900"><ShieldCheck size={14} aria-hidden />{label('ctrl')}</div>
                  <ol className="list-decimal space-y-1 pl-5 text-slate-800">
                    {sess?.pending?.filter((p) => !p.confirmed).map((p) => <li key={p.action_id}>{p.summary}</li>)}
                  </ol>
                  <div className="mt-2 flex gap-2">
                    <Button variant="primary" size="sm" onClick={() => decide(true)}>{label('confirm')}</Button>
                    <Button size="sm" onClick={() => decide(false)}>{label('cancel')}</Button>
                  </div>
                </div>
              )}
              {sess?.handoff && sess.status === 'waiting_human' && (
                <div className="rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-800 ring-1 ring-emerald-200">{label('waiting')} · {tw('~{n} min', { n: sess.handoff.est_wait_min })}</div>
              )}
              {error && <div role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">{error}</div>}
              <div ref={bottom} />
            </div>
            <footer className="border-t border-slate-200 bg-white p-3">
              {msgs.length <= 2 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {suggestions.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-left text-xs text-slate-700 hover:border-blue-300 hover:bg-blue-50">{s}</button>
                  ))}
                </div>
              )}
              <form onSubmit={(e) => { e.preventDefault(); send(text) }} className="flex items-center gap-2">
                <label htmlFor="msg" className="sr-only">{label('ph')}</label>
                <input id="msg" value={text} onChange={(e) => setText(e.target.value)} placeholder={ended ? '—' : label('ph')} disabled={!sess || !!ended} autoComplete="off" maxLength={2000} className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500" />
                <Button type="submit" variant="primary" disabled={!sess || busy || !text.trim() || !!ended} icon={Send}>{label('send')}</Button>
              </form>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px] text-slate-500">
                <span className="flex flex-wrap items-center gap-2">
                  {sess?.identity.verified && <Badge tone="green"><UserCheck size={10} aria-hidden /> {label('verified')} L{sess.identity.level}</Badge>}
                  {sess?.agent && <Badge tone="blue">{sess.agent.name}</Badge>}
                  {sess?.consent.recording === 'declined' && <Badge tone="amber">{tw('not recorded')}</Badge>}
                </span>
                <span className="flex items-center gap-3">
                  {sess && <a className="inline-flex items-center gap-1 hover:underline" href={withLang(`/api/i18n/transcript/${sess.id}?format=txt`, loc)}><Download size={11} aria-hidden />{label('dl')}</a>}
                  <button type="button" onClick={reset} className="inline-flex items-center gap-1 hover:underline"><RefreshCw size={11} aria-hidden />{label('newc')}</button>
                </span>
              </div>
            </footer>
          </>
        )}
      </main>

      <aside className="w-full shrink-0 md:w-72 md:overflow-y-auto" aria-label={tw('Simulated phone')}>
        <div className="rounded-3xl border border-slate-300 bg-white p-3 shadow-lg">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-600"><Smartphone size={14} aria-hidden />{label('phone')}</div>
          {!sess?.outbox?.length ? <p className="text-xs text-slate-400">—</p> : (
            <ul className="space-y-2">
              {sess.outbox.map((o, i) => (
                <li key={i} className="rounded-2xl rounded-tl-sm bg-slate-100 px-3 py-2 text-xs text-slate-800">
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">{o.channel} · {o.to}</div>
                  {o.body}
                </li>
              ))}
            </ul>
          )}
          {otp?.code && !sess?.identity.verified && (
            <Button size="sm" className="mt-3 w-full" onClick={() => setText(otp.code!)}>{otp.code}</Button>
          )}
        </div>
        <p className="mt-3 px-2 text-center text-[11px] text-slate-600">{tw('Synthetic data · simulated environment')}</p>
      </aside>
    </div>
  )
}
