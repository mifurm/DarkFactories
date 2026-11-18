import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, Page } from '../../components/ui'
import { useApi, useEventSource } from '../../lib/api'
import { fmt } from '../../lib/feature'
import { usePlant, withPlant } from '../../plant'
import { AssetCard, AutonomyPanel, CopilotMini, FaultConsole, Feed, InboxMini, KpiStrip, LedgerTail, SimControls, WhatIfMini, type FeedItem, type Snap } from './Panels'
import { PlantMap, type MapT } from './PlantMap'

const FEED_KINDS = new Set(['proposal', 'decision', 'action', 'veto', 'arbitration', 'outcome', 'whatif', 'narration', 'override', 'system'])

export default function ControlTower() {
  const { plantId } = usePlant()
  const initial = useApi<Snap>(withPlant('/api/tower/snapshot', plantId))
  const map = useApi<MapT>(withPlant('/api/tower/map', plantId))
  const [snap, setSnap] = useState<Snap | null>(null)
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [alerts, setAlerts] = useState<NonNullable<Snap['alerts']>>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [faultPreset, setFaultPreset] = useState<string | null>(null)
  const faultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setSnap(null)
    setFeed([])
    setAlerts([])
    setSelected(null)
  }, [plantId])
  useEffect(() => {
    if (initial.data && initial.data.plant.id === plantId) {
      setSnap(initial.data)
      setFeed([...(initial.data.activity ?? [])].reverse())
      setAlerts([...(initial.data.alerts ?? [])].reverse())
    }
  }, [initial.data, plantId])

  const live = useEventSource(withPlant('/api/stream/plant', plantId), {
    tick: (d: Snap) => setSnap((prev) => (prev && prev.plant.id !== d.plant.id ? prev : { ...(prev ?? ({} as Snap)), ...d })),
    ledger: (e: FeedItem & { kind: string }) => FEED_KINDS.has(e.kind) && setFeed((f) => (f.some((x) => x.seq === e.seq) ? f : [e, ...f].slice(0, 120))),
    alert: (a) => setAlerts((x) => [a, ...x].slice(0, 40)),
  })

  const asset = snap?.assets.find((a) => a.id === selected) ?? null
  const pick = (id: string) => setSelected((s) => (s === id ? null : id))

  return (
    <Page
      title={<span className="flex items-center gap-2">Control Tower <Badge tone={live ? 'ok' : 'warn'}>{live ? '● live' : 'connecting…'}</Badge></span>}
      subtitle={snap ? `${snap.plant.name} · ${snap.plant.location ?? ''} · simulated time ${snap.sim_time.replace('T', ' ')} · ${snap.in_window ? 'planned maintenance window' : 'production'}` : 'Connecting to the live plant…'}
      right={snap && <SimControls snap={snap} />}
    >
      {!snap ? (
        <div className="py-20 text-center text-mute">Loading the plant…</div>
      ) : (
        <>
          {snap.kill_switch && (
            <div role="alert" className="rounded-lg border border-bad/50 bg-bad/10 px-4 py-2 text-sm text-bad">
              Kill switch is ON: all agent actions are halted{snap.kill_info?.reason ? ` (${snap.kill_info.reason})` : ''}. Only the protective safety stop remains active.
            </div>
          )}
          <KpiStrip snap={snap} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="space-y-4">
              <Card title="Plant floor" right={<span className="text-[11px] text-mute">{snap.assets.filter((a) => a.state === 'RUN').length}/{snap.assets.length} running · {fmt.n(snap.total_kw, 0)} kW</span>} pad={false}>
                <div className="p-3">
                  <PlantMap assets={snap.assets} map={map.data} zones={snap.zones} selected={selected} onSelect={pick} />
                </div>
              </Card>
              <div className="grid gap-4 lg:grid-cols-2">
                <div ref={faultRef}><FaultConsole preset={faultPreset} /></div>
                <AutonomyPanel snap={snap} />
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <WhatIfMini assets={snap.assets} t={snap.t} />
                <CopilotMini />
              </div>
            </div>
            <div className="space-y-4">
              {asset && <AssetCard asset={asset} onClose={() => setSelected(null)} onFault={(id) => { setFaultPreset(id); faultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} />}
              <InboxMini />
              <Card title="Agent activity" right={<Link to="/ledger" className="text-xs text-accent">ledger →</Link>}>
                <div className="max-h-[420px] overflow-y-auto pr-1">
                  <Feed items={feed} onPick={pick} max={30} />
                </div>
              </Card>
              {alerts.length > 0 && (
                <Card title="Alerts">
                  <ul className="space-y-1 text-[12px]">
                    {alerts.slice(0, 6).map((a, i) => (
                      <li key={i} className="flex items-center gap-2">
                        <Badge tone={a.kind === 'failure' ? 'bad' : 'warn'}>{a.kind}</Badge>
                        <span className="text-mute">{a.sim_time.slice(11, 16)}</span>
                        <span>{a.asset ?? a.order}{a.late_min ? ` · ${fmt.dur(a.late_min)} late` : ''}{a.cause ? ` · ${a.cause}` : ''}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
              <LedgerTail />
            </div>
          </div>
        </>
      )}
    </Page>
  )
}
