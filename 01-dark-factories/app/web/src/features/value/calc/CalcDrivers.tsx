import clsx from 'clsx'
import { useState, type Dispatch, type SetStateAction } from 'react'
import { Input } from '../../../components/bits'
import { Badge, Button, Card } from '../../../components/ui'
import { fv, putOverride, scenarioValue } from './logic'
import type { Driver, Group, Meta, Overrides } from './types'

type SetOv = Dispatch<SetStateAction<Overrides>>
const OPEN_BY_DEFAULT = new Set(['customer', 'benefit_lever'])

function DriverRow({ d, scenario, ov, setOv }: { d: Driver; scenario: string; ov: Overrides; setOv: SetOv }) {
  const sv = scenarioValue(d, scenario)
  const cur = ov[d.id]
  const changed = d.id in ov
  const isPrice = d.id.startsWith('price.')
  const label = isPrice ? d.id : d.label
  const bounds = { min: d.min ?? undefined, max: d.max ?? undefined }
  const cls = clsx('w-full', changed && 'border-accent')
  let control
  if (d.kind === 'list') {
    const base = Array.isArray(sv) ? (sv as number[]) : []
    const edit = (k: number, text: string) =>
      setOv((o) => {
        const now = Array.isArray(o[d.id]) ? (o[d.id] as number[]) : base
        const n = Number(text)
        if (text !== '' && Number.isNaN(n)) return o
        const next = now.map((x, i) => (i === k ? (text === '' ? base[k] : n) : x))
        return text === '' && next.every((x, i) => x === base[i]) ? putOverride(o, d.id, undefined) : putOverride(o, d.id, next)
      })
    control = (
      <div className="flex gap-1">
        {base.map((b, k) => (
          <Input key={k} aria-label={`${label} year ${k + 1}`} type="number" step="any" {...bounds} placeholder={fv(b)} value={Array.isArray(cur) ? cur[k] : ''} onChange={(e) => edit(k, e.target.value)} className={clsx('w-full min-w-0 px-1', changed && 'border-accent')} />
        ))}
      </div>
    )
  } else if (d.kind === 'pairs') {
    control = <span className="text-[11px] text-mute" title="Shared-capacity scale curve: [plants, factor] points (read-only here)">{fv(sv)}</span>
  } else {
    control = (
      <Input
        aria-label={label}
        type="number"
        step="any"
        {...bounds}
        placeholder={fv(sv)}
        value={typeof cur === 'number' ? cur : ''}
        onChange={(e) => {
          const t = e.target.value
          const n = Number(t)
          if (t === '') setOv((o) => putOverride(o, d.id, undefined))
          else if (!Number.isNaN(n)) setOv((o) => putOverride(o, d.id, n))
        }}
        className={cls}
      />
    )
  }
  const range = d.scenario_driver ? `cons ${fv(d.scenario.conservative)} / base ${fv(d.scenario.base)} / up ${fv(d.scenario.upside)}` : `value ${fv(sv)}`
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,150px)_20px] items-center gap-2 py-1.5 text-[12px]" title={d.source}>
      <div className="min-w-0">
        <div className="truncate">{isPrice ? `${d.label} · ${d.unit}` : d.label}</div>
        <div className="truncate text-[10px] text-mute">{isPrice ? d.detail : `${d.unit} · ${d.flag} · ${range}`}</div>
      </div>
      <div>{control}</div>
      {changed ? <Button size="sm" tone="ghost" aria-label={`Reset ${label}`} title="Back to the scenario value" className="px-1 py-0" onClick={() => setOv((o) => putOverride(o, d.id, undefined))}>×</Button> : <span />}
    </div>
  )
}

function GroupBox({ g, q, scenario, ov, setOv }: { g: Group; q: string; scenario: string; ov: Overrides; setOv: SetOv }) {
  const [open, setOpen] = useState(OPEN_BY_DEFAULT.has(g.id))
  const needle = q.trim().toLowerCase()
  const rows = needle ? g.drivers.filter((d) => `${d.label} ${d.id} ${d.detail ?? ''}`.toLowerCase().includes(needle)) : g.drivers
  if (needle && !rows.length) return null
  const shown = open || !!needle
  const changed = g.drivers.filter((d) => d.id in ov).length
  return (
    <section className="rounded-lg border border-line/70 bg-panel2/30">
      <button type="button" aria-expanded={shown} onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left">
        <span className="text-[12px] font-semibold">{shown ? '▾' : '▸'} {g.label}</span>
        <span className="flex items-center gap-2 text-[11px] text-mute">{changed > 0 && <Badge tone="info">{changed} changed</Badge>}{rows.length}</span>
      </button>
      {shown && <div className="divide-y divide-line/50 px-3 pb-1">{rows.map((d) => <DriverRow key={d.id} d={d} scenario={scenario} ov={ov} setOv={setOv} />)}</div>}
    </section>
  )
}

const SECTIONS: { kind: Group['kind']; title: string; note: string }[] = [
  { kind: 'core', title: 'Core platform drivers', note: 'Customer, benefit baselines, levers, ramps, customer-side costs and the Azure consumption sizing of the core swarm.' },
  { kind: 'expansion', title: 'Expansion levers E1-E5', note: 'Adoption switches are in the lever controls above; the drivers below size each lever (Azure lines, customer costs, benefits).' },
  { kind: 'prices', title: 'Azure unit prices', note: 'List prices from the Retail Prices API; override a meter to test a discount or a different SKU.' },
]

export default function CalcDrivers({ meta, scenario, ov, setOv }: { meta: Meta; scenario: string; ov: Overrides; setOv: SetOv }) {
  const [q, setQ] = useState('')
  return (
    <Card
      title={`Assumptions - all ${meta.counts.drivers + meta.counts.prices} overridable inputs of the model`}
      right={<Input aria-label="Filter assumptions" type="search" placeholder="Filter by name or id…" className="w-56" value={q} onChange={(e) => setQ(e.target.value)} />}
    >
      <p className="mb-3 text-[12px] text-mute">Generated from the model's own assumption file, so a new model version needs no UI change. Blank = the scenario value (shown as placeholder); every override is validated by the model server-side.</p>
      <div className="space-y-4">
        {SECTIONS.map((sec) => (
          <div key={sec.kind}>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-accent">{sec.title}</div>
            <p className="mb-2 text-[11px] text-mute">{sec.note}</p>
            <div className="grid items-start gap-2 lg:grid-cols-2">
              {meta.groups.filter((g) => g.kind === sec.kind).map((g) => <GroupBox key={g.id} g={g} q={q} scenario={scenario} ov={ov} setOv={setOv} />)}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
