import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApprovalCard, type InboxItemT } from '../../components/approvals'
import { Field, Mono, Select, StateBadge, outcomeTone, simTime, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Tabs } from '../../components/ui'
import { postSSE } from '../../lib/api'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls, withPlant } from '../../plant'
import type { AssetT } from './PlantMap'

export type Snap = {
  plant: { id: string; name: string; location?: string; profile?: string }
  t: number
  sim_time: string
  speed: number
  paused: boolean
  kill_switch: boolean
  kill_info: { reason?: string; by?: string }
  global_cap: number
  price_eur_kwh: number
  carbon_g_kwh: number
  total_kw: number
  assets: AssetT[]
  kpi: Record<string, number | null>
  zones: Record<string, { occupied: boolean; wait: number }>
  inbox: { pending: number; breached: number; escalations: number; expired: number; total: number }
  ledger: { entries: number; head: string }
  open_orders: number
  supervisor: Record<string, number>
  in_window: boolean
  agents: { name: string; role: string; enabled: boolean }[]
  alerts?: { t: number; kind: string; asset: string | null; order?: string; late_min?: number; sim_time: string; cause?: string }[]
  activity?: FeedItem[]
}
export type FeedItem = { seq: number; sim_time: string; kind: string; agent: string; asset: string; summary: string; outcome: string }

const FEED_KINDS = new Set(['proposal', 'decision', 'action', 'veto', 'arbitration', 'outcome', 'whatif', 'narration', 'override', 'system'])

export function SimControls({ snap }: { snap: Snap }) {
  const calls = usePlantCalls()
  const act = useAction()
  const speeds = [1, 5, 10, 30, 60, 120]
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" tone={snap.paused ? 'primary' : 'default'} disabled={act.busy} onClick={() => act.run(() => calls.post('/api/sim/control', { command: snap.paused ? 'resume' : 'pause' }))}>
        {snap.paused ? '▶ Resume' : '❚❚ Pause'}
      </Button>
      <Button size="sm" disabled={act.busy || !snap.paused} title="Advance 15 simulated minutes (while paused)" onClick={() => act.run(() => calls.post('/api/sim/control', { command: 'step', value: 15 }))}>
        Step 15 min
      </Button>
      <label className="flex items-center gap-1 text-[11px] text-mute">
        sim speed
        <select aria-label="Simulation speed" value={speeds.includes(snap.speed) ? snap.speed : ''} onChange={(e) => act.run(() => calls.post('/api/sim/control', { command: 'speed', value: Number(e.target.value) }))} className="rounded-md border border-line bg-panel2 px-1.5 py-1 text-xs text-ink">
          {!speeds.includes(snap.speed) && <option value="">{snap.speed} sim-min / s</option>}
          {speeds.map((s) => (
            <option key={s} value={s}>{s} sim-min / s</option>
          ))}
        </select>
      </label>
      {act.error && <span role="alert" className="text-xs text-bad">{act.error}</span>}
    </div>
  )
}

type Catalog = { faults: { kind: string; label: string; hint?: string; target_kind: string; targets: string[]; params: Record<string, number> }[]; scenarios: { id: string; description: string }[] }

const DEMO_DEFAULTS: Record<string, Record<string, number>> = { bearing_wear: { ttf_h: 5 } } // a watchable story: failure ~5 running hours after injection

export function FaultConsole({ preset }: { preset?: string | null }) {
  const calls = usePlantCalls()
  const cat = usePApi<Catalog>('/api/sim/catalog')
  const [kind, setKind] = useState('bearing_wear')
  const [target, setTarget] = useState('CNC-04')
  const act = useAction<{ message?: string }>()
  const [note, setNote] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const fault = cat.data?.faults.find((f) => f.kind === kind)
  useEffect(() => {
    if (fault) setParams({ ...fault.params, ...(DEMO_DEFAULTS[fault.kind] ?? {}) })
  }, [fault])
  useEffect(() => {
    if (fault && fault.targets.length && !fault.targets.includes(target)) setTarget(fault.targets.includes('CNC-04') ? 'CNC-04' : fault.targets[0])
  }, [fault, target])
  useEffect(() => {
    if (preset) {
      setKind('bearing_wear')
      setTarget(preset)
    }
  }, [preset])
  const inject = async () => {
    if (!fault) return
    const body: Record<string, unknown> = { kind, params }
    if (fault.target_kind !== 'plant') body[fault.target_kind] = target
    const r = await act.run(() => calls.post('/api/sim/faults', body))
    if (r) setNote(`Injected ${fault.label}${fault.target_kind !== 'plant' ? ` on ${target}` : ''} - watch the agents react.`)
  }
  return (
    <Card title="Fault-injection console" right={<Badge tone="warn">simulation only</Badge>}>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Fault">
          <Select aria-label="Fault kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            {(cat.data?.faults ?? []).map((f) => (
              <option key={f.kind} value={f.kind}>{f.label}</option>
            ))}
          </Select>
        </Field>
        <Field label={fault?.target_kind === 'plant' ? 'Target' : (fault?.target_kind ?? 'target')}>
          <Select aria-label="Fault target" value={target} disabled={!fault?.targets.length} onChange={(e) => setTarget(e.target.value)}>
            {fault?.targets.length ? fault.targets.map((t) => <option key={t}>{t}</option>) : <option>whole plant</option>}
          </Select>
        </Field>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button tone="danger" size="sm" disabled={act.busy || !fault} onClick={inject}>⚡ Inject fault</Button>
        {Object.entries(params).map(([k, v]) => (
          <label key={k} className="flex items-center gap-1 text-[11px] text-mute">
            {k}
            <input aria-label={`Fault parameter ${k}`} type="number" step="any" value={v} onChange={(e) => setParams({ ...params, [k]: Number(e.target.value) })} className="w-16 rounded border border-line bg-panel2 px-1 py-0.5 text-xs text-ink" />
          </label>
        ))}
      </div>
      <div className="mt-3 border-t border-line pt-2">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-mute">Scripted scenarios</div>
        <div className="flex flex-wrap gap-1.5">
          {(cat.data?.scenarios ?? []).map((s) => (
            <button key={s.id} title={s.description} disabled={act.busy} onClick={async () => { const r = await act.run(() => calls.post(`/api/sim/scenario/${s.id}`)); if (r) setNote(`Scenario "${s.id}" started: ${s.description}`) }} className="rounded-md border border-line bg-panel2 px-2 py-1 text-[11px] hover:border-accent hover:text-accent">
              {s.id}
            </button>
          ))}
        </div>
      </div>
      {note && <p className="mt-2 text-[11px] text-ok">{note}</p>}
      {act.error && <p role="alert" className="mt-2 text-xs text-bad">{act.error}</p>}
    </Card>
  )
}

type PolicyT = { levels: Record<string, number>; level_names: Record<string, string>; global_cap: number; kill_switch: boolean; kill_info: { reason?: string; by?: string } }

export function AutonomyPanel({ snap }: { snap: Snap }) {
  const calls = usePlantCalls()
  const pol = usePApi<PolicyT>('/api/policy', { interval: 5000 })
  const act = useAction()
  const names = pol.data?.level_names ?? {}
  const cap = snap.global_cap
  return (
    <Card title="Autonomy dial" right={<Badge tone={snap.kill_switch ? 'bad' : 'ok'}>{snap.kill_switch ? 'KILL SWITCH ON' : `cap L${cap}`}</Badge>}>
      <div className="grid grid-cols-6 gap-1" role="group" aria-label="Global autonomy cap">
        {[0, 1, 2, 3, 4, 5].map((l) => (
          <button key={l} disabled={act.busy} onClick={() => act.run(() => calls.put('/api/policy/dial', { global_cap: l }))} title={names[String(l)]} className={clsx('rounded-md border px-1 py-1.5 text-center text-xs', cap === l ? 'border-accent bg-accent/15 text-accent' : 'border-line bg-panel2 text-mute hover:text-ink')}>
            <div className="font-semibold">L{l}</div>
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] text-mute">L{cap}: {names[String(cap)] ?? '…'}. The cap is enforced in the supervisor for every decision class.</p>
      <div className="mt-2 flex items-center gap-2">
        {snap.kill_switch ? (
          <Button tone="primary" size="sm" disabled={act.busy} onClick={() => act.run(() => calls.post('/api/policy/kill', { on: false, reason: 'released from control tower' }))}>Release kill switch</Button>
        ) : (
          <Button tone="danger" size="sm" disabled={act.busy} onClick={() => act.run(() => calls.post('/api/policy/kill', { on: true, reason: 'operator pressed the kill switch' }))}>⏻ KILL SWITCH</Button>
        )}
        <span className="text-[11px] text-mute">{snap.kill_switch ? `Agents halted${snap.kill_info?.by ? ` by ${snap.kill_info.by}` : ''}. Only the protective safety stop still acts.` : 'Halts every agent action at once.'}</span>
      </div>
      {act.error && <p role="alert" className="mt-1 text-xs text-bad">{act.error}</p>}
    </Card>
  )
}

export function Feed({ items, max = 40, onPick }: { items: FeedItem[]; max?: number; onPick?: (asset: string) => void }) {
  if (!items.length) return <Empty>Quiet night shift. Inject a fault or wait for the next random disruption.</Empty>
  return (
    <ul className="space-y-1.5" aria-label="Agent activity">
      {items.slice(0, max).map((f) => (
        <li key={f.seq} className="rounded-md border border-line/60 bg-panel2/50 px-2.5 py-1.5 text-[12px]">
          <div className="flex items-center gap-1.5 text-[10px] text-mute">
            <span className="tabnum">{simTime(f.sim_time)}</span>
            <Badge tone="violet">{f.agent}</Badge>
            <Badge tone={outcomeTone(f.outcome)}>{f.kind}{f.outcome && f.outcome !== f.kind ? ` · ${f.outcome}` : ''}</Badge>
            {f.asset && (
              <button className="rounded bg-white/5 px-1 font-mono hover:text-accent" onClick={() => onPick?.(f.asset)}>{f.asset}</button>
            )}
            <span className="ml-auto tabnum">#{f.seq}</span>
          </div>
          <div className="mt-0.5 leading-snug text-ink/90">{f.summary}</div>
        </li>
      ))}
    </ul>
  )
}

export function InboxMini() {
  const inbox = usePApi<{ items: InboxItemT[]; stats: { pending: number } }>('/api/inbox', { interval: 2500 })
  const pending = (inbox.data?.items ?? []).filter((i) => i.status === 'pending')
  return (
    <Card title="Approvals inbox" right={<Badge tone={pending.length ? 'warn' : 'mute'}>{pending.length} pending</Badge>}>
      {pending.length === 0 ? (
        <Empty>No decisions waiting. Plans within the autonomy dial execute automatically; the rest land here.</Empty>
      ) : (
        <div className="space-y-2">
          {pending.slice(0, 3).map((i) => (
            <ApprovalCard key={i.id} item={i} compact onDone={() => void inbox.reload()} />
          ))}
          {pending.length > 3 && <a href="/inbox" className="text-xs text-accent">+{pending.length - 3} more in the inbox →</a>}
        </div>
      )}
    </Card>
  )
}

export function AssetCard({ asset, onClose, onFault }: { asset: AssetT; onClose: () => void; onFault: (id: string) => void }) {
  const detail = usePApi<{ sensors?: Record<string, number>; series?: Record<string, (number | null)[]>; queue_ops?: { order: string; op: number }[] }>(`/api/sim/assets/${asset.id}`, { interval: 3000 })
  const calls = usePlantCalls()
  const act = useAction()
  return (
    <Card title={`${asset.id} · ${asset.name}`} right={<button onClick={onClose} className="text-mute hover:text-ink" aria-label="Close asset panel">✕</button>}>
      <div className="mb-2 flex items-center gap-2"><StateBadge state={asset.state} /><span className="text-[11px] text-mute">{asset.reason}</span></div>
      <Kv k="type / zone" v={`${asset.type} · ${asset.zone}`} />
      <Kv k="power" v={`${asset.power_kw.toFixed(1)} kW`} />
      <Kv k="speed" v={`${Math.round(asset.speed * 100) || asset.speed}%`} />
      <Kv k="queue" v={asset.queue} />
      <Kv k="running" v={asset.current ? asset.current.join(' / ') : '-'} />
      {Object.entries(detail.data?.sensors ?? asset.sensors ?? {}).map(([k, v]) => (
        <Kv key={k} k={k.replace(/_/g, ' ')} v={typeof v === 'number' ? v.toFixed(2) : String(v)} />
      ))}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" tone="danger" onClick={() => onFault(asset.id)}>Inject bearing wear</Button>
        <Button size="sm" disabled={act.busy} onClick={() => act.run(() => calls.post('/api/maintenance/work-orders', { asset: asset.id, start_in_min: 30, reason: 'manual from control tower' }))}>Schedule maintenance</Button>
      </div>
      {act.error && <p role="alert" className="mt-1 text-xs text-bad">{act.error}</p>}
      {act.result ? <p className="mt-1 text-[11px] text-ok">Work order requested (goes through policy).</p> : null}
    </Card>
  )
}

type Cite = { ref?: string; id?: string; type?: string }

export function CopilotMini() {
  const { plantId } = usePlantCalls()
  const [q, setQ] = useState('Why is the plant running this way right now?')
  const [answer, setAnswer] = useState('')
  const [cites, setCites] = useState<Cite[]>([])
  const [tools, setTools] = useState<string[]>([])
  const [mode, setMode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ctl = useRef<AbortController | null>(null)
  useEffect(() => () => ctl.current?.abort(), [])
  const ask = async () => {
    ctl.current?.abort()
    ctl.current = new AbortController()
    setBusy(true)
    setAnswer('')
    setCites([])
    setTools([])
    setError('')
    try {
      await postSSE(withPlant('/api/copilot/chat', plantId), { messages: [{ role: 'user', content: q }] }, (ev, d) => {
        if (ev === 'token') setAnswer((a) => a + d.text)
        else if (ev === 'citations') setCites(d.citations)
        else if (ev === 'tool_call') setTools((t) => [...t, d.name])
        else if (ev === 'done') setMode(`${d.mode}${d.model ? ' · ' + d.model : ''}`)
        else if (ev === 'error') setError(d.message)
      }, ctl.current.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card title="Ask the Factory" right={mode ? <Badge tone="info">{mode}</Badge> : undefined}>
      <div className="flex gap-2">
        <input aria-label="Question for the factory copilot" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && !busy && void ask()} className="min-w-0 flex-1 rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm" />
        <Button tone="primary" size="sm" disabled={busy || !q.trim()} onClick={() => void ask()}>{busy ? '…' : 'Ask'}</Button>
      </div>
      {tools.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{tools.map((t, i) => <Mono key={i}>{t}()</Mono>)}</div>}
      {answer && <p className="mt-2 whitespace-pre-wrap text-[13px] leading-snug">{answer}</p>}
      {cites.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{cites.map((c, i) => <Badge key={i} tone="info">{c.ref ?? c.id ?? JSON.stringify(c)}</Badge>)}</div>}
      {error && <p role="alert" className="mt-1 text-xs text-bad">{error}</p>}
    </Card>
  )
}

type WhatIf = { accept: boolean; explanation: string; delta: Record<string, number>; counterfactual: { failure_avoided: boolean; avoided_loss_eur: number; avoided_downtime_min: number } }

export function WhatIfMini({ assets, t }: { assets: AssetT[]; t: number }) {
  const calls = usePlantCalls()
  const act = useAction<WhatIf>()
  const [asset, setAsset] = useState('CNC-04')
  const ids = useMemo(() => assets.filter((a) => ['CNC', 'PRESS', 'ASM', 'TEST', 'CNV', 'COMP', 'CHILL'].some((p) => a.id.startsWith(p))).map((a) => a.id), [assets])
  const r = act.result
  return (
    <Card title="What-if (digital-twin fork)">
      <div className="flex items-end gap-2">
        <Field label="Maintenance on" className="flex-1">
          <Select aria-label="What-if asset" value={asset} onChange={(e) => setAsset(e.target.value)}>
            {(ids.length ? ids : [asset]).map((i) => <option key={i}>{i}</option>)}
          </Select>
        </Field>
        <Button size="sm" tone="primary" disabled={act.busy} onClick={() => act.run(() => calls.post<WhatIf>('/api/twin/whatif', { actions: [{ kind: 'schedule_maintenance', asset, start_t: t + 15, duration: 45 }], horizon_min: 240 }))}>
          {act.busy ? 'Simulating…' : 'Simulate 4 h'}
        </Button>
      </div>
      {act.error && <p role="alert" className="mt-1 text-xs text-bad">{act.error}</p>}
      {r && (
        <div className="mt-2 text-[12px]">
          <div className="flex items-center gap-2">
            <Badge tone={r.accept ? 'ok' : 'warn'}>{r.accept ? 'worth doing' : 'not worth it'}</Badge>
            <span>net <b className={r.delta.net_value_eur >= 0 ? 'text-ok' : 'text-bad'}>{fmt.eur(r.delta.net_value_eur)}</b></span>
            <span className="text-mute">downtime {fmt.n(r.delta.downtime_min)} min · late {fmt.n(r.delta.late_orders)}</span>
          </div>
          <p className="mt-1 text-mute">{r.explanation}</p>
        </div>
      )}
    </Card>
  )
}

export function KpiStrip({ snap }: { snap: Snap }) {
  const k = snap.kpi
  const tile = (label: string, value: string, tone: string = 'text-ink', sub?: string) => (
    <div className="min-w-0 rounded-lg border border-line bg-panel px-3 py-2">
      <div className="truncate text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={clsx('tabnum text-xl font-semibold leading-tight', tone)}>{value}</div>
      {sub && <div className="truncate text-[10px] text-mute">{sub}</div>}
    </div>
  )
  const oee = k.oee ?? 0
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8" aria-label="Plant KPIs (rolling 8 h)">
      {tile('OEE', fmt.pct(oee, 1), oee > 0.7 ? 'text-ok' : oee > 0.5 ? 'text-warn' : 'text-bad', `A ${fmt.pct(k.availability, 0)} · P ${fmt.pct(k.performance, 0)} · Q ${fmt.pct(k.quality, 0)}`)}
      {tile('Throughput', `${fmt.n(k.throughput_uph, 1)} u/h`, 'text-ink', `${fmt.n(k.units_good)} good units`)}
      {tile('OTIF', fmt.pct(k.otif, 0), (k.otif ?? 1) > 0.85 ? 'text-ok' : 'text-warn', `${snap.open_orders} open · ${k.overdue_orders ?? 0} overdue`)}
      {tile('Downtime', `${fmt.n(k.downtime_min)} min`, (k.downtime_min ?? 0) > 120 ? 'text-warn' : 'text-ink', `${k.failures ?? 0} failures`)}
      {tile('Scrap', fmt.pct(k.scrap_pct, 2), 'text-ink', 'of units, rolling 8 h')}
      {tile('Energy', `${fmt.n(snap.total_kw, 0)} kW`, 'text-ink', `${fmt.n(k.kwh_per_unit, 2)} kWh/unit · €${snap.price_eur_kwh.toFixed(3)}/kWh`)}
      {tile('CO₂', `${fmt.n(k.co2_per_unit_kg, 2)} kg/u`, 'text-ink', `${snap.carbon_g_kwh} g/kWh grid`)}
      {tile('Decisions', `${snap.supervisor.executed ?? 0} done`, 'text-ink', `${snap.supervisor.auto ?? 0} auto · ${snap.supervisor.approvals ?? 0} to humans · ${snap.supervisor.vetoed ?? 0} vetoed`)}
    </div>
  )
}

export function LedgerTail({ limit = 6 }: { limit?: number }) {
  const led = usePApi<{ items: { seq: number; sim_time: string; kind: string; agent: string; summary: string; outcome: string; hash?: string }[] }>(`/api/ledger?limit=${limit}`, { interval: 4000 })
  const ver = usePApi<{ ok: boolean; length: number }>('/api/ledger/verify', { interval: 10000 })
  return (
    <Card title="Decision ledger (tamper-evident)" right={<Badge tone={ver.data?.ok ? 'ok' : ver.data ? 'bad' : 'mute'}>{ver.data ? (ver.data.ok ? `chain valid · ${ver.data.length}` : 'CHAIN BROKEN') : '…'}</Badge>}>
      <ul className="space-y-1 text-[12px]">
        {(led.data?.items ?? []).map((e) => (
          <li key={e.seq} className="flex gap-2"><span className="tabnum text-mute">#{e.seq}</span><span className="text-mute">{simTime(e.sim_time)}</span><span className="truncate">{e.summary}</span></li>
        ))}
      </ul>
      <a href="/ledger" className="mt-2 block text-xs text-accent">Open the ledger →</a>
    </Card>
  )
}

export function RightTabs({ children }: { children: Record<string, React.ReactNode> }) {
  const keys = Object.keys(children)
  const [tab, setTab] = useState(keys[0])
  return (
    <div>
      <Tabs tabs={keys.map((k) => ({ id: k, label: k }))} value={tab} onChange={setTab} />
      <div className="pt-3">{children[tab]}</div>
    </div>
  )
}

export { FEED_KINDS }
