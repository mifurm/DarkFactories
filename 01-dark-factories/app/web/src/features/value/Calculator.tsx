import { useEffect, useMemo, useRef, useState } from 'react'
import { useAction } from '../../components/bits'
import { Empty } from '../../components/ui'
import { api, errText, post } from '../../lib/api'
import type { Ab } from './AbPanel'
import CalcControls from './calc/CalcControls'
import CalcDrivers from './calc/CalcDrivers'
import CalcResults from './calc/CalcResults'
import { leverMode, zeroLevers } from './calc/logic'
import type { Calc, Meta, Overrides, SensResult } from './calc/types'

type FromAb = { suggested_overrides: Record<string, number>; notes: string[]; caveat: string }

export default function Calculator({ ab }: { ab: Ab | null }) {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [scenario, setScenario] = useState('base')
  const [ov, setOv] = useState<Overrides>({})
  const [calc, setCalc] = useState<Calc | null>(null)
  const [core, setCore] = useState<Calc | null>(null)
  const [sens, setSens] = useState<SensResult | null>(null)
  const [err, setErr] = useState('')
  const [note, setNote] = useState<{ notes: string[]; caveat: string } | null>(null)
  const act = useAction<FromAb>()
  const seq = useRef(0)
  const sensBusy = useRef(false)
  const sensDone = useRef('')
  const [sensTick, setSensTick] = useState(0)
  useEffect(() => { void api<Meta>('/api/value/calculator/meta').then(setMeta).catch((e) => setErr(errText(e))) }, [])
  const switches = meta?.switches
  const mode = useMemo(() => leverMode(switches ?? [], ov, scenario), [switches, ov, scenario])
  const switchesOnly = useMemo(() => Object.keys(ov).every((k) => switches?.some((s) => s.key === k)), [ov, switches])
  const key = useMemo(() => JSON.stringify([scenario, ov]), [scenario, ov])
  useEffect(() => {
    if (!switches) return
    const id = ++seq.current
    const t = window.setTimeout(async () => {
      try {
        const [main, base] = await Promise.all([
          post<Calc>('/api/value/calculator/compute', { scenario, overrides: ov, sensitivity: false }),
          mode === 'off' ? Promise.resolve(null) : post<Calc>('/api/value/calculator/compute', { scenario, overrides: { ...ov, ...zeroLevers(switches) }, sensitivity: false }),
        ])
        if (id === seq.current) { setCalc(main); setCore(base); setErr('') }
      } catch (e) { if (id === seq.current) setErr(errText(e)) }
    }, 150)
    return () => window.clearTimeout(t)
  }, [scenario, ov, switches, mode])
  useEffect(() => {
    // The tornado re-runs the model hundreds of times (seconds on the small container): idle-debounced, one request in flight, cached server-side.
    if (!switches || sensDone.current === key) return
    const t = window.setTimeout(async () => {
      if (sensBusy.current) return
      sensBusy.current = true
      try {
        const r = await post<Calc>('/api/value/calculator/compute', { scenario, overrides: ov, sensitivity: true })
        setSens({ key, npv: r.roi.npv, acr3: r.acr.by_year[2], npvItems: r.sensitivity ?? [], acrItems: r.acr_sensitivity ?? [] })
      } catch { /* input errors are reported by the fast path; rate limits just keep the previous tornado */ } finally {
        sensDone.current = key
        sensBusy.current = false
        setSensTick((n) => n + 1)
      }
    }, 1200)
    return () => window.clearTimeout(t)
  }, [key, scenario, ov, switches, sensTick])
  const apply = async () => {
    const r = await act.run(() => api<FromAb>('/api/value/calculator/from-ab'))
    if (r) { setOv((o) => ({ ...o, ...r.suggested_overrides })); setNote({ notes: r.notes, caveat: r.caveat }) }
  }
  return (
    <div className="space-y-4">
      <CalcControls meta={meta} scenario={scenario} setScenario={setScenario} ov={ov} setOv={setOv} canUseAb={!!ab} busyAb={act.busy} onUseAb={apply} onReset={() => { setOv({}); setNote(null) }} note={note} error={err || act.error || ''} />
      {!calc || !meta ? <Empty>Computing…</Empty> : <CalcResults calc={calc} core={core} sens={sens} sensStale={sens?.key !== key} meta={meta} scenario={scenario} mode={mode} switchesOnly={switchesOnly} />}
      {meta && <CalcDrivers meta={meta} scenario={scenario} ov={ov} setOv={setOv} />}
    </div>
  )
}
