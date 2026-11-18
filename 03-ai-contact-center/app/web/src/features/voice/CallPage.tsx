import { Activity, Bot, Info, Mic, MicOff, Phone, PhoneOff, Radio, Send, User } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { i18nFor, type Lang, type Vars } from '../../i18n'
import { CONV_LANGS, useConversationLang } from '../../i18n/useConversationLang'
import { api, describeError, useApi, wsUrl } from '../../lib/api'
import { Badge, Button, Card, Tabs, cx } from '../../lib/ui'

interface Line { id: number; role: 'customer' | 'agent' | 'system'; text: string; final: boolean }
interface Cfg { mode: string; realtime_model: string; fallback_model: string; vad: string; fallback_pipeline: string; telephony: { provisioned: boolean; note: string; adapters: { id: string; name: string; role: string }[] }; max_concurrent: number; active: number }
interface Metrics { turns_measured: number; turn_latency_ms: { p50: number | null; p95: number | null }; target_p95_ms: number; voice_conversations: number }
interface SimResult { call_id: string; provider: string; timeline: { event: string; state: string; actions: string[]; commands: string[] }[]; exchange?: { agent_lines: string[]; audio_seconds: number; mode: string }; final: { consent: string | null } }
interface AdapterInfo { id: string; name: string; role: string; strategic: boolean; status: string; inbound: string; media: string }
interface Adapters { adapters: AdapterInfo[]; production: string; states: string[] }

const STATE_TONE: Record<string, string> = { idle: 'slate', connecting: 'amber', listening: 'green', thinking: 'amber', speaking: 'blue' }
const DTMF = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']

export default function CallPage() {
  const [params] = useSearchParams()
  const { conv: lang, choose } = useConversationLang(params)
  // English and Polish are UI languages; the other conversation languages keep this page's English chrome (as before)
  const loc: Lang = lang === 'pl' ? 'pl' : 'en'
  const { tn, te, rich, ts, fmt } = i18nFor(loc)
  // reads the language at call time, so the WebSocket handlers created on the first render never show a stale language
  const locRef = useRef<Lang>(loc)
  locRef.current = loc
  const tw = (key: string, vars?: Vars) => i18nFor(locRef.current).tr(key, vars)
  const [tab, setTab] = useState('call')
  const [state, setState] = useState<'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'>('idle')
  const [live, setLive] = useState(false)
  const [lines, setLines] = useState<Line[]>([])
  const [latency, setLatency] = useState<number[]>([])
  const [muted, setMuted] = useState(false)
  const [level, setLevel] = useState(0)
  const [info, setInfo] = useState<{ mode: string; model: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [payment, setPayment] = useState<{ status: string; digits?: number; link?: string } | null>(null)
  const [handoff, setHandoff] = useState<string | null>(null)
  const [typed, setTyped] = useState('')
  const [convId, setConvId] = useState<string | null>(params.get('c'))
  const [sim, setSim] = useState<SimResult | null>(null)
  const [provider, setProvider] = useState('sip')
  const [busy, setBusy] = useState(false)
  const cfg = useApi<Cfg>('/api/voice/config')
  const adapters = useApi<Adapters>('/api/voice/telephony/adapters')
  const metrics = useApi<Metrics>('/api/voice/metrics', { refreshMs: 15000 })

  const ws = useRef<WebSocket | null>(null)
  const ctx = useRef<AudioContext | null>(null)
  const node = useRef<AudioWorkletNode | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const nextPlay = useRef(0)
  const playing = useRef<Set<AudioBufferSourceNode>>(new Set())
  const mutedRef = useRef(false)
  const lineId = useRef(0)
  const logEnd = useRef<HTMLDivElement>(null)

  const addLine = (role: Line['role'], text: string, final = true) => setLines((cur) => [...cur, { id: ++lineId.current, role, text, final }])
  const upsertLine = (role: 'customer' | 'agent', text: string, final: boolean) =>
    setLines((cur) => {
      const last = cur[cur.length - 1]
      if (last && last.role === role && !last.final) return [...cur.slice(0, -1), { ...last, text, final }]
      return [...cur, { id: ++lineId.current, role, text, final }]
    })

  const stopPlayback = () => {
    playing.current.forEach((s) => {
      try { s.stop() } catch { /* already stopped */ }
    })
    playing.current.clear()
    if (ctx.current) nextPlay.current = ctx.current.currentTime
  }
  const play = (buf: ArrayBuffer) => {
    const c = ctx.current
    if (!c) return
    const i16 = new Int16Array(buf.slice(0, buf.byteLength - (buf.byteLength % 2)))
    if (i16.length === 0) return
    const f32 = new Float32Array(i16.length)
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000
    const ab = c.createBuffer(1, f32.length, 24000)
    ab.copyToChannel(f32, 0)
    const src = c.createBufferSource()
    src.buffer = ab
    src.connect(c.destination)
    const start = Math.max(c.currentTime + 0.02, nextPlay.current)
    src.start(start)
    nextPlay.current = start + ab.duration
    playing.current.add(src)
    src.onended = () => playing.current.delete(src)
  }

  const onEvent = useCallback((ev: Record<string, any>) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    const i18n = i18nFor(locRef.current)
    switch (ev.type) {
      case 'session': setInfo({ mode: ev.mode, model: ev.model }); break
      case 'state': setState(ev.state); break
      case 'transcript': upsertLine(ev.role, ev.text, !!ev.final); break
      case 'latency': setLatency((x) => [...x.slice(-19), ev.first_audio_ms]); break
      case 'audio.clear': stopPlayback(); break
      case 'fallback': setNotice(i18n.ts(ev.reason)); break
      case 'tool': if (ev.status !== 'running') addLine('system', tw('tool {name}: {status}', { name: ev.name, status: i18n.te('toolStatus', ev.status) })); break
      case 'handoff': setHandoff(`${ev.handoff.queue} · ${tw('~{n} min', { n: ev.handoff.est_wait_min })}`); break
      case 'payment': setPayment({ status: ev.status, digits: ev.digits, link: ev.link }); break
      case 'error': setNotice(ev.message ?? ev.error); break
      case 'ended': hangup(false); break
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const hangup = (notify = true) => {
    if (notify && ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify({ type: 'end' }))
    ws.current?.close()
    ws.current = null
    node.current?.disconnect()
    stream.current?.getTracks().forEach((track) => track.stop())
    stopPlayback()
    ctx.current?.close().catch(() => undefined)
    ctx.current = null
    setLive(false)
    setState('idle')
    setLevel(0)
  }

  const dial = async () => {
    setNotice(null)
    setLines([])
    setLatency([])
    setHandoff(null)
    setPayment(null)
    setState('connecting')
    try {
      let id = convId
      if (!id) {
        const s = await api<{ conversation_id: string }>('/api/voice/sessions', { body: { language: lang, recording_consent: 'granted' }, role: 'customer' })
        id = s.conversation_id
        setConvId(id)
      }
      const ac = new AudioContext({ sampleRate: 24000 })
      ctx.current = ac
      nextPlay.current = ac.currentTime
      try {
        stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
        await ac.audioWorklet.addModule('/worklets/pcm-capture.js')
        const src = ac.createMediaStreamSource(stream.current)
        node.current = new AudioWorkletNode(ac, 'pcm-capture')
        src.connect(node.current)
        node.current.port.onmessage = (e) => {
          if (e.data.level !== undefined) setLevel(Math.min(1, e.data.level * 6))
          else if (e.data.pcm && !mutedRef.current && ws.current?.readyState === WebSocket.OPEN) ws.current.send(e.data.pcm)
        }
      } catch {
        setNotice(tw('Microphone not available - use the text box below (the model still answers with audio).'))
      }
      const sock = new WebSocket(wsUrl(`/ws/voice/${id}`))
      sock.binaryType = 'arraybuffer'
      sock.onmessage = (m) => {
        if (typeof m.data === 'string') onEvent(JSON.parse(m.data))
        else play(m.data as ArrayBuffer)
      }
      sock.onclose = () => { if (ws.current === sock) hangup(false) }
      sock.onopen = () => { setLive(true); setState('listening') }
      ws.current = sock
    } catch (e) {
      setNotice(describeError(e))
      hangup(false)
    }
  }
  const sendText = (v: string) => {
    if (!v.trim() || ws.current?.readyState !== WebSocket.OPEN) return
    ws.current.send(JSON.stringify({ type: 'text', text: v }))
    setTyped('')
  }
  const toggleMute = () => { mutedRef.current = !mutedRef.current; setMuted(mutedRef.current); ws.current?.send(JSON.stringify({ type: 'mute', muted: mutedRef.current })) }
  const pressKey = (d: string) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify({ type: 'dtmf', digit: d }))
  const simulate = async (scenario: string) => {
    setBusy(true)
    try { setSim(await api<SimResult>('/api/voice/telephony/simulate', { body: { scenario, provider }, role: 'customer' })) } catch (e) { setNotice(describeError(e)) } finally { setBusy(false) }
  }
  useEffect(() => () => hangup(false), []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: 'end' })
  }, [lines])

  const paySubtitle = payment
    ? `${tw('Secure payment: {status}', { status: te('payStatus', payment.status) })}${payment.digits ? ` · ${tn(payment.digits, { one: '{n} digit', other: '{n} digits' })}` : ''}`
    : tw('Card digits are captured here, never by the AI')

  return (
    <div className="mx-auto min-h-screen max-w-5xl p-4">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold text-slate-900">{tw('Contoso Home — Call us')}</h1>
          <p className="max-w-3xl text-sm text-slate-600">{tw('Talk to Concierge, our AI voice assistant, from your browser. A colleague is one sentence away.')}</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="sr-only" htmlFor="call-lang">{tw('Language')}</label>
          <select id="call-lang" data-testid="call-lang" value={lang} onChange={(e) => choose(e.target.value)} disabled={live} className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-800">
            {Object.entries(CONV_LANGS).map(([k, v]) => <option key={k} value={k} lang={k}>{v}</option>)}
          </select>
          <Link to={convId ? `/widget?c=${convId}&lang=${lang}` : `/widget?lang=${lang}`} className="text-sm font-medium text-blue-700 hover:underline">{tw('← Chat instead')}</Link>
        </div>
      </header>
      <Tabs tabs={[{ id: 'call', label: tw('Voice call') }, { id: 'telephony', label: tw('Telephony adapters (simulated)') }, { id: 'how', label: tw('How it works') }]} value={tab} onChange={setTab} />
      {tab === 'call' && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
          <Card title={tw('Live call')} actions={<Badge tone={STATE_TONE[state]}>{te('callState', state)}</Badge>}>
            <div className="flex flex-col items-center gap-4 py-4">
              <div className={cx('grid h-28 w-28 place-items-center rounded-full text-white shadow-lg', live ? 'bg-emerald-600 pulse-ring' : 'bg-blue-600')} aria-hidden>
                <Radio size={40} style={{ opacity: 0.5 + level * 0.5, transform: `scale(${1 + level * 0.25})` }} />
              </div>
              <div className="flex items-center gap-2">
                {!live ? (
                  <Button variant="primary" icon={Phone} onClick={dial} busy={state === 'connecting'} aria-label={tw('Start call')}>{tw('Start call')}</Button>
                ) : (
                  <>
                    <Button icon={muted ? MicOff : Mic} onClick={toggleMute} aria-pressed={muted}>{muted ? tw('Unmute') : tw('Mute')}</Button>
                    <Button variant="danger" icon={PhoneOff} onClick={() => hangup(true)} aria-label={tw('End call')}>{tw('End call')}</Button>
                  </>
                )}
              </div>
              <div className="flex flex-wrap justify-center gap-2 text-xs">
                {info && <Badge tone="violet">{te('voiceMode', info.mode)} · {info.model}</Badge>}
                {latency.length > 0 && <Badge tone="blue" title={tw('end of speech to first audio')}><Activity size={10} aria-hidden /> {tw('last turn {time}', { time: fmt.ms(latency[latency.length - 1]) })}</Badge>}
                {handoff && <Badge tone="green">{tw('handoff → {to}', { to: handoff })}</Badge>}
              </div>
              {notice && <p role="status" className="max-w-md text-center text-xs text-amber-700">{notice}</p>}
            </div>
            <div className="scroll-thin max-h-72 space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-3" role="log" aria-live="polite" aria-label={tw('Live captions')}>
              {lines.length === 0 && <p className="text-center text-xs text-slate-600">{tw('Live captions appear here — both directions.')}</p>}
              {lines.map((l) => (
                <div key={l.id} className={cx('flex gap-2 text-sm', l.role === 'customer' && 'flex-row-reverse text-right')}>
                  {l.role === 'system' ? <span className="mx-auto text-xs text-slate-400">{l.text}</span> : (
                    <>
                      <span className={cx('mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-white', l.role === 'agent' ? 'bg-violet-600' : 'bg-slate-500')} aria-hidden>{l.role === 'agent' ? <Bot size={12} /> : <User size={12} />}</span>
                      <span className={cx('max-w-[85%] rounded-2xl px-3 py-1.5', l.role === 'agent' ? 'bg-white shadow-sm ring-1 ring-slate-200' : 'bg-blue-600 text-white', !l.final && 'opacity-70')}>{l.text}</span>
                    </>
                  )}
                </div>
              ))}
              <div ref={logEnd} />
            </div>
            <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); sendText(typed) }}>
              <label htmlFor="typed" className="sr-only">{tw('Type instead of speaking')}</label>
              <input id="typed" value={typed} onChange={(e) => setTyped(e.target.value)} disabled={!live} placeholder={live ? tw('Type instead of speaking (test path) …') : tw('Start the call first')} className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              <Button type="submit" icon={Send} disabled={!live || !typed.trim()}>{tw('Send')}</Button>
            </form>
          </Card>
          <div className="space-y-4">
            <Card title={tw('Keypad (DTMF)')} subtitle={paySubtitle}>
              <div className="grid grid-cols-3 gap-2">
                {DTMF.map((d) => (
                  <button key={d} type="button" disabled={!live} onClick={() => pressKey(d)} className="rounded-xl border border-slate-200 bg-white py-2 text-lg font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:opacity-40" aria-label={tw('Key {key}', { key: d })}>{d}</button>
                ))}
              </div>
            </Card>
            <Card title={tw('Voice latency')} subtitle={tw('target p95 ≤ {ms} ms (natural conversation)', { ms: fmt.number(metrics.data?.target_p95_ms ?? 800) })}>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div><div className="text-lg font-semibold">{fmt.ms(metrics.data?.turn_latency_ms.p50)}</div><div className="text-[11px] text-slate-500">p50</div></div>
                <div><div className="text-lg font-semibold">{fmt.ms(metrics.data?.turn_latency_ms.p95)}</div><div className="text-[11px] text-slate-500">p95</div></div>
                <div><div className="text-lg font-semibold">{metrics.data ? fmt.number(metrics.data.turns_measured) : '—'}</div><div className="text-[11px] text-slate-500">{tw('turns')}</div></div>
              </div>
            </Card>
          </div>
        </div>
      )}
      {tab === 'telephony' && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card title={tw('Simulated inbound call')} subtitle={tw('One provider-neutral state machine behind three adapters — no PSTN number, carrier or Azure Communication Services resource is provisioned')}>
            <fieldset className="mb-3">
              <legend className="mb-1 text-xs font-medium text-slate-600">{tw('Provider adapter')}</legend>
              <div className="flex flex-wrap gap-2">
                {(adapters.data?.adapters ?? []).map((a) => (
                  <label key={a.id} className={cx('cursor-pointer rounded-lg px-3 py-1.5 text-sm ring-1', provider === a.id ? 'bg-blue-600 text-white ring-blue-600' : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50')}>
                    <input type="radio" name="provider" value={a.id} checked={provider === a.id} onChange={() => setProvider(a.id)} className="sr-only" />
                    {a.id === 'sip' ? tw('SIP → Realtime') : a.id === 'teams' ? tw('Teams Phone') : tw('ACS (legacy)')}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={busy} onClick={() => simulate('damaged_sofa')} icon={Phone}>{tw('Damaged-sofa call')}</Button>
              <Button busy={busy} onClick={() => simulate('decline_consent')}>{tw('Caller declines recording')}</Button>
              <Button busy={busy} onClick={() => simulate('silent_consent')}>{tw('No answer to consent (never granted)')}</Button>
              <Button busy={busy} onClick={() => simulate('transfer')}>{tw('Escalation → transfer')}</Button>
              <Button busy={busy} onClick={() => simulate('hangup_early')}>{tw('Caller hangs up early')}</Button>
            </div>
            <ul className="mt-4 space-y-2">
              {(adapters.data?.adapters ?? []).map((a) => (
                <li key={a.id} className="rounded-lg bg-slate-50 p-2 text-xs text-slate-600"><div className="flex flex-wrap items-center gap-1.5"><b className="text-slate-800">{ts(a.name)}</b><Badge tone={a.strategic ? 'green' : 'amber'}>{ts(a.role)}</Badge></div><p className="mt-1">{ts(a.status)}</p></li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-slate-500">{ts(adapters.data?.production)}</p>
          </Card>
          <Card title={tw('Event state machine')}>
            {!sim ? <p className="text-sm text-slate-500">{tw("Run a scenario to see the provider's native events, the neutral states they drive (idle → answering → connected → consent → listening → disconnected) and the native call-control commands rendered for each step.")}</p> : (
              <div className="space-y-2">
                <ol className="space-y-1.5">
                  {sim.timeline.map((step, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2 text-sm"><Badge tone="blue">{step.event}</Badge><span className="text-slate-400">→</span><Badge tone="green">{te('telState', step.state)}</Badge><span className="text-xs text-slate-500">{step.actions.join(', ')}</span>{!!step.commands.length && <span className="font-mono text-[11px] text-violet-700">⇒ {step.commands.join(', ')}</span>}</li>
                  ))}
                </ol>
                {sim.exchange && <div className="rounded-xl bg-slate-50 p-2 text-sm"><div className="mb-1 text-xs text-slate-500">{tw('Agent lines ({mode}, {seconds} s audio)', { mode: sim.exchange.mode, seconds: fmt.plain(sim.exchange.audio_seconds) })}</div>{sim.exchange.agent_lines.map((l, i) => <p key={i} className="text-slate-800">“{l}”</p>)}</div>}
                <p className="text-xs text-slate-500">{tw('Recording consent:')} <b>{sim.final.consent ? te('consent', sim.final.consent) : tw('n/a')}</b> · {tw('adapter')} <b>{te('telephonyProvider', sim.provider)}</b></p>
              </div>
            )}
          </Card>
        </div>
      )}
      {tab === 'how' && (
        <Card className="mt-4" title={tw('Browser → relay → Azure OpenAI Realtime')}>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">
            <li>{rich('<b>Capture:</b> microphone → AudioWorklet → PCM16 24 kHz mono frames (20 ms) → WebSocket <code>/ws/voice/<id></code>.')}</li>
            <li>{rich('<b>Relay:</b> the server holds the Entra-token WebSocket to <code>{model}</code> (fallback <code>{fallback}</code>) — no keys in the browser; server VAD with barge-in; tool calls run through the same policy-guarded tool layer as chat.', { model: cfg.data?.realtime_model, fallback: cfg.data?.fallback_model })}</li>
            <li>{rich('<b>Fallback:</b> {pipeline}.', { pipeline: ts(cfg.data?.fallback_pipeline) })}</li>
            <li>{rich('<b>VAD:</b> {vad}. Barge-in cancels the response and truncates what was not yet played.', { vad: ts(cfg.data?.vad) })}</li>
            <li><b>{tw('Telephony:')}</b> <Info size={12} className="inline" aria-hidden /> {ts(cfg.data?.telephony.note)}</li>
          </ul>
        </Card>
      )}
    </div>
  )
}
