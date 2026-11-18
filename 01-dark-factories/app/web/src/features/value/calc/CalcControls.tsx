import clsx from 'clsx'
import type { Dispatch, SetStateAction } from 'react'
import { Input, Select } from '../../../components/bits'
import { Badge, Button, Card } from '../../../components/ui'
import { adoptionOf, leverMode, setAllLevers, setOverride, type LeverMode } from './logic'
import type { Meta, Overrides } from './types'

type SetOv = Dispatch<SetStateAction<Overrides>>

export const MODE_LABEL: Record<LeverMode, string> = { off: 'Base · levers off', on: 'Expansion levers on', custom: 'Custom lever mix' }

export default function CalcControls({
  meta, scenario, setScenario, ov, setOv, canUseAb, busyAb, onUseAb, onReset, note, error,
}: {
  meta: Meta | null
  scenario: string
  setScenario: (s: string) => void
  ov: Overrides
  setOv: SetOv
  canUseAb: boolean
  busyAb: boolean
  onUseAb: () => void
  onReset: () => void
  note: { notes: string[]; caveat: string } | null
  error: string
}) {
  const switches = meta?.switches ?? []
  const mode = leverMode(switches, ov, scenario)
  const count = Object.keys(ov).length
  return (
    <Card
      title="Scenario & expansion levers"
      right={
        <div className="flex items-center gap-2">
          <Select aria-label="Scenario" className="w-40" value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {(meta?.scenarios ?? ['conservative', 'base', 'upside']).map((s) => <option key={s}>{s}</option>)}
          </Select>
          <Button size="sm" disabled={!canUseAb || busyAb} title={canUseAb ? 'Replace the downtime / scrap / OEE drivers with the A/B measurement' : 'Run the A/B replay first'} onClick={onUseAb}>Use A/B results</Button>
          <Button size="sm" tone="ghost" disabled={!count} onClick={onReset}>Reset</Button>
        </div>
      }
    >
      <p className="text-[12px] text-mute">
        {meta?.meta.name} · model v{meta?.meta.model_version} · {meta?.meta.currency} · {meta?.meta.horizon_years}-year horizon · reference customer: {meta?.meta.reference_customer}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Expansion levers master toggle" className="inline-flex rounded-lg border border-line bg-panel2 p-0.5">
          {([['off', false], ['on', true]] as const).map(([m, on]) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              disabled={!switches.length}
              onClick={() => setOv((o) => setAllLevers(switches, o, scenario, on))}
              className={clsx('rounded-md px-3 py-1 text-sm font-medium transition-colors', mode === m ? (on ? 'bg-accent/20 text-accent' : 'bg-white/10 text-ink') : 'text-mute hover:text-ink')}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
        {mode === 'custom' && <Badge tone="warn">{MODE_LABEL.custom}</Badge>}
        <span className="text-[12px] text-mute">
          "Levers on" switches the five expansion levers to their Upside adoption on this scenario's other inputs (the model's expansion case). Tune each lever below.
        </span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-5" data-testid="lever-switches">
        {switches.map((s) => {
          const a = adoptionOf(s, ov, scenario)
          const on = a > 0
          return (
            <div key={s.key} className={clsx('rounded-lg border px-3 py-2', on ? 'border-accent/40 bg-accent/5' : 'border-line bg-panel2/40')}>
              <label className="flex cursor-pointer items-start gap-2 text-[12px] font-medium">
                <input type="checkbox" aria-label={`${s.lever} ${s.label}`} className="mt-0.5 accent-sky-400" checked={on} onChange={(e) => setOv((o) => setOverride(o, s.key, e.target.checked ? s.on : 0, s.scenario[scenario as keyof typeof s.scenario]))} />
                <span><span className="text-accent">{s.lever}</span> {s.label}</span>
              </label>
              <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-mute">
                adoption
                <Input aria-label={`${s.lever} adoption %`} type="number" min={0} max={100} step={5} className="w-16 px-1.5 py-0.5" value={Math.round(a * 100)} onChange={(e) => { const n = Number(e.target.value); if (!Number.isNaN(n)) setOv((o) => setOverride(o, s.key, Math.min(s.max, Math.max(s.min, n / 100)), s.scenario[scenario as keyof typeof s.scenario])) }} />
                % of plants
              </div>
            </div>
          )
        })}
      </div>
      {count > 0 && <p className="mt-2 text-[12px] text-accent">{count} override(s) active.</p>}
      {note && <div className="mt-2 rounded-lg border border-accent/30 bg-accent/10 p-2 text-[12px]"><b>Applied from A/B:</b> {note.notes.join('; ')}. <span className="text-warn">{note.caveat}</span></div>}
      {error && <p role="alert" className="mt-2 text-xs text-bad">{error}</p>}
    </Card>
  )
}
