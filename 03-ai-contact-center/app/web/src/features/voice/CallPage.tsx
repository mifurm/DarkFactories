import { Activity, Bot, Info, Mic, MicOff, Phone, PhoneOff, Radio, Send, User } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmt, useApi, wsUrl } from '../../lib/api'
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
  const lang = params.get('lang') ?? 'en'
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
    switch (ev.type) {
      case 'session': setInfo({ mode: ev.mode, model: ev.model }); break
      case 'state': setState(ev.state); break
      case 'transcript': upsertLine(ev.role, ev.text, !!ev.final); break
      case 'latency': setLatency((l) => [...l.slice(-19), ev.first_audio_ms]); break
      case 'audio.clear': stopPlayback(); break
      case 'fallback': setNotice(ev.reason); break
      case 'tool': if (ev.status !== 'running') addLine('system', `tool ${ev.name}: ${ev.status}`); break
      case 'handoff': setHandoff(`${ev.handoff.queue} · ~${ev.handoff.est_wait_min} min`); break
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
    stream.current?.getTracks().forEach((t) => t.stop())
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
        setNotice('Microphone not available - use the text box below (the model still answers with audio).')
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
      setNotice(String((e as Error).message))
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
    try { setSim(await api<SimResult>('/api/voice/telephony/simulate', { body: { scenario, provider }, role: 'customer' })) } finally { setBusy(false) }
  }
  useEffect(() => () => hangup(false), []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: 'end' })
  }, [lines])

  return (
    <div className="mx-auto min-h-screen max-w-5xl p-4">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Contoso Home — Call us</h1>
          <p className="text-sm text-slate-600">Talk to Concierge, our AI voice assistant, from your browser. A colleague is one sentence away.</p>
        </div>
        <Link to={convId ? `/widget?c=${convId}` : '/widget'} className="text-sm font-medium text-blue-700 hover:underline">← Chat instead</Link>
      </header>
      <Tabs tabs={[{ id: 'call', label: 'Voice call' }, { id: 'telephony', label: 'Telephony adapters (simulated)' }, { id: 'how', label: 'How it works' }]} value={tab} onChange={setTab} />
      {tab === 'call' && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
          <Card title="Live call" actions={<Badge tone={STATE_TONE[state]}>{state}</Badge>}>
            <div className="flex flex-col items-center gap-4 py-4">
              <div className={cx('grid h-28 w-28 place-items-center rounded-full text-white shadow-lg', live ? 'bg-emerald-600 pulse-ring' : 'bg-blue-600')} aria-hidden>
                <Radio size={40} style={{ opacity: 0.5 + level * 0.5, transform: `scale(${1 + level * 0.25})` }} />
              </div>
              <div className="flex items-center gap-2">
                {!live ? (
                  <Button variant="primary" icon={Phone} onClick={dial} busy={state === 'connecting'} aria-label="Start call">Start call</Button>
                ) : (
                  <>
                    <Button icon={muted ? MicOff : Mic} onClick={toggleMute} aria-pressed={muted}>{muted ? 'Unmute' : 'Mute'}</Button>
                    <Button variant="danger" icon={PhoneOff} onClick={() => hangup(true)} aria-label="End call">End call</Button>
                  </>
                )}
              </div>
              <div className="flex flex-wrap justify-center gap-2 text-xs">
                {info && <Badge tone="violet">{info.mode} · {info.model}</Badge>}
                {latency.length > 0 && <Badge tone="blue" title="end of speech to first audio"><Activity size={10} aria-hidden /> last turn {fmt.ms(latency[latency.length - 1])}</Badge>}
                {handoff && <Badge tone="green">handoff → {handoff}</Badge>}
              </div>
              {notice && <p role="status" className="max-w-md text-center text-xs text-amber-700">{notice}</p>}
            </div>
            <div className="scroll-thin max-h-72 space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-3" role="log" aria-live="polite" aria-label="Live captions">
              {lines.length === 0 && <p className="text-center text-xs text-slate-600">Live captions appear here — both directions.</p>}
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
              <label htmlFor="typed" className="sr-only">Type instead of speaking</label>
              <input id="typed" value={typed} onChange={(e) => setTyped(e.target.value)} disabled={!live} placeholder={live ? 'Type instead of speaking (test path) …' : 'Start the call first'} className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              <Button type="submit" icon={Send} disabled={!live || !typed.trim()}>Send</Button>
            </form>
          </Card>
          <div className="space-y-4">
            <Card title="Keypad (DTMF)" subtitle={payment ? `Secure payment: ${payment.status}${payment.digits ? ` · ${payment.digits} digits` : ''}` : 'Card digits are captured here, never by the AI'}>
              <div className="grid grid-cols-3 gap-2">
                {DTMF.map((d) => (
                  <button key={d} type="button" disabled={!live} onClick={() => pressKey(d)} className="rounded-xl border border-slate-200 bg-white py-2 text-lg font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:opacity-40" aria-label={`Key ${d}`}>{d}</button>
                ))}
              </div>
            </Card>
            <Card title="Voice latency" subtitle={`target p95 ≤ ${metrics.data?.target_p95_ms ?? 800} ms (natural conversation)`}>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div><div className="text-lg font-semibold">{fmt.ms(metrics.data?.turn_latency_ms.p50)}</div><div className="text-[11px] text-slate-500">p50</div></div>
                <div><div className="text-lg font-semibold">{fmt.ms(metrics.data?.turn_latency_ms.p95)}</div><div className="text-[11px] text-slate-500">p95</div></div>
                <div><div className="text-lg font-semibold">{metrics.data?.turns_measured ?? '—'}</div><div className="text-[11px] text-slate-500">turns</div></div>
              </div>
            </Card>
          </div>
        </div>
      )}
      {tab === 'telephony' && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card title="Simulated inbound call" subtitle="One provider-neutral state machine behind three adapters — no PSTN number, carrier or Azure Communication Services resource is provisioned">
            <fieldset className="mb-3">
              <legend className="mb-1 text-xs font-medium text-slate-600">Provider adapter</legend>
              <div className="flex flex-wrap gap-2">
                {(adapters.data?.adapters ?? []).map((a) => (
                  <label key={a.id} className={cx('cursor-pointer rounded-lg px-3 py-1.5 text-sm ring-1', provider === a.id ? 'bg-blue-600 text-white ring-blue-600' : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50')}>
                    <input type="radio" name="provider" value={a.id} checked={provider === a.id} onChange={() => setProvider(a.id)} className="sr-only" />
                    {a.id === 'sip' ? 'SIP → Realtime' : a.id === 'teams' ? 'Teams Phone' : 'ACS (legacy)'}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={busy} onClick={() => simulate('damaged_sofa')} icon={Phone}>Damaged-sofa call</Button>
              <Button busy={busy} onClick={() => simulate('decline_consent')}>Caller declines recording</Button>
              <Button busy={busy} onClick={() => simulate('silent_consent')}>No answer to consent (never granted)</Button>
              <Button busy={busy} onClick={() => simulate('transfer')}>Escalation → transfer</Button>
              <Button busy={busy} onClick={() => simulate('hangup_early')}>Caller hangs up early</Button>
            </div>
            <ul className="mt-4 space-y-2">
              {(adapters.data?.adapters ?? []).map((a) => (
                <li key={a.id} className="rounded-lg bg-slate-50 p-2 text-xs text-slate-600"><div className="flex flex-wrap items-center gap-1.5"><b className="text-slate-800">{a.name}</b><Badge tone={a.strategic ? 'green' : 'amber'}>{a.role}</Badge></div><p className="mt-1">{a.status}</p></li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-slate-500">{adapters.data?.production}</p>
          </Card>
          <Card title="Event state machine">
            {!sim ? <p className="text-sm text-slate-500">Run a scenario to see the provider's native events, the neutral states they drive (idle → answering → connected → consent → listening → disconnected) and the native call-control commands rendered for each step.</p> : (
              <div className="space-y-2">
                <ol className="space-y-1.5">
                  {sim.timeline.map((t, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2 text-sm"><Badge tone="blue">{t.event}</Badge><span className="text-slate-400">→</span><Badge tone="green">{t.state}</Badge><span className="text-xs text-slate-500">{t.actions.join(', ')}</span>{!!t.commands.length && <span className="font-mono text-[11px] text-violet-700">⇒ {t.commands.join(', ')}</span>}</li>
                  ))}
                </ol>
                {sim.exchange && <div className="rounded-xl bg-slate-50 p-2 text-sm"><div className="mb-1 text-xs text-slate-500">Agent lines ({sim.exchange.mode}, {sim.exchange.audio_seconds}s audio)</div>{sim.exchange.agent_lines.map((l, i) => <p key={i} className="text-slate-800">“{l}”</p>)}</div>}
                <p className="text-xs text-slate-500">Recording consent: <b>{sim.final.consent ?? 'n/a'}</b> · adapter <b>{sim.provider}</b></p>
              </div>
            )}
          </Card>
        </div>
      )}
      {tab === 'how' && (
        <Card className="mt-4" title="Browser → relay → Azure OpenAI Realtime">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">
            <li><b>Capture:</b> microphone → AudioWorklet → PCM16 24 kHz mono frames (20 ms) → WebSocket <code>/ws/voice/&lt;id&gt;</code>.</li>
            <li><b>Relay:</b> the server holds the Entra-token WebSocket to <code>{cfg.data?.realtime_model}</code> (fallback <code>{cfg.data?.fallback_model}</code>) — no keys in the browser; server VAD with barge-in; tool calls run through the same policy-guarded tool layer as chat.</li>
            <li><b>Fallback:</b> {cfg.data?.fallback_pipeline}.</li>
            <li><b>VAD:</b> {cfg.data?.vad}. Barge-in cancels the response and truncates what was not yet played.</li>
            <li><b>Telephony:</b> <Info size={12} className="inline" aria-hidden /> {cfg.data?.telephony.note}</li>
          </ul>
        </Card>
      )}
    </div>
  )
}
