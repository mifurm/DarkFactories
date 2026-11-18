import { useState } from 'react'
import { Bars, Lines } from '../../../components/charts'
import { Mono } from '../../../components/bits'
import { Badge, Button, Card, Empty, Stat, Table, Td } from '../../../components/ui'
import { FAMILY_COLORS, LEVER_COLORS, nonZero, stackedRows, usd, type LeverMode } from './logic'
import type { Calc, ExpansionTier, Headline, LeverRow, Meta, SensResult } from './types'

const pct = (v: number | null | undefined, d = 0) => (v == null ? '-' : `${v.toFixed(d)} %`)
const mo = (v: number | null | undefined) => (v == null ? '> horizon' : `${v.toFixed(1)} mo`)
const sgn = (v: number, f: (x: number) => string) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${f(Math.abs(v))}`
const byYear = (rec: Record<string, number[]>, keys: string[], years: number) => Array.from({ length: years }, (_, i) => ({ x: `Year ${i + 1}`, ...Object.fromEntries(keys.map((k) => [k, Math.round(rec[k][i])])) }))

function Tornado({ items, base, label }: { items: { id: string; label: string; low: number; high: number }[]; base: number; label: string }) {
  const top = items.slice(0, 10)
  const span = Math.max(1, ...top.map((s) => Math.max(Math.abs(s.low - base), Math.abs(s.high - base))))
  const W = 820
  const L = 330
  const x = (v: number) => L + ((v - base) / span) * ((W - L - 20) / 2) + (W - L - 20) / 2
  return (
    <svg viewBox={`0 0 ${W} ${top.length * 26 + 30}`} className="w-full" role="img" aria-label={label}>
      <line x1={x(base)} x2={x(base)} y1={4} y2={top.length * 26 + 8} stroke="#8499ae" strokeDasharray="3 3" />
      {top.map((s, i) => {
        const y = 14 + i * 26
        const lo = Math.min(s.low, s.high)
        const hi = Math.max(s.low, s.high)
        return (
          <g key={s.id}>
            <text x={L - 10} y={y + 4} fontSize={10.5} textAnchor="end" fill="#d9e4ef">{s.label.length > 52 ? s.label.slice(0, 50) + '…' : s.label}</text>
            <rect x={x(lo)} y={y - 7} width={Math.max(1, x(base) - x(lo))} height={14} fill="#f87171" opacity={0.75} rx={2} />
            <rect x={x(base)} y={y - 7} width={Math.max(1, x(hi) - x(base))} height={14} fill="#34d399" opacity={0.75} rx={2} />
            <text x={x(lo) - 4} y={y + 4} fontSize={9} textAnchor="end" fill="#8499ae">{usd(lo)}</text>
            <text x={x(hi) + 4} y={y + 4} fontSize={9} fill="#8499ae">{usd(hi)}</text>
          </g>
        )
      })}
    </svg>
  )
}

function Waterfall({ steps }: { steps: Calc['expansion']['path'] }) {
  const W = 820
  const H = 300
  const top = 30
  const bottom = 44
  const peak = Math.max(...steps.map((s) => (s.kind === 'total' ? s.value : 0))) * 1.1 || 1
  const y = (v: number) => top + (1 - v / peak) * (H - top - bottom)
  const bw = W / steps.length
  let run = 0
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="ACR run-rate path from the core platform to the expansion case">
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="#213245" />
      {steps.map((s, i) => {
        const from = s.kind === 'total' ? 0 : run
        const to = s.kind === 'total' ? s.value : run + s.value
        run = to
        const hi = Math.max(from, to)
        const lo = Math.min(from, to)
        const x0 = i * bw + bw * 0.18
        const short = s.id === 'core' ? 'Core' : s.id === 'expansion' ? 'Levers on' : s.id
        return (
          <g key={s.id}>
            <title>{s.label}: {usd(s.value)}</title>
            <rect x={x0} y={y(hi)} width={bw * 0.64} height={Math.max(2, y(lo) - y(hi))} rx={3} fill={s.kind === 'total' ? '#38bdf8' : (LEVER_COLORS[s.id] ?? '#34d399')} opacity={s.kind === 'total' ? 0.85 : 0.9} />
            <text x={i * bw + bw / 2} y={y(hi) - 6} fontSize={13} textAnchor="middle" fill="#d9e4ef">{s.kind === 'delta' ? `+${usd(s.value)}` : usd(s.value)}</text>
            <text x={i * bw + bw / 2} y={H - 18} fontSize={13} textAnchor="middle" fill="#8499ae">{short}</text>
          </g>
        )
      })}
    </svg>
  )
}

type Snap = { npv: number; npv5: number | null; roi: number; payback: number | null; acr3: number; rr: number; perPlant: number }
const snapOf = (c: Calc): Snap => ({ npv: c.roi.npv, npv5: c.memo?.five_year.npv ?? null, roi: c.roi.roi_pct, payback: c.roi.payback_months, acr3: c.acr.by_year[2], rr: c.acr.run_rate_year3, perPlant: c.acr.per_plant_year })

function Comparison({ calc, core, mode }: { calc: Calc; core: Calc | null; mode: LeverMode }) {
  const t = (id: string) => calc.expansion.tiers.find((x) => x.id === id)
  const t25 = t('enterprise_25')
  const fleet = t('fleet')
  const h = calc.expansion.headline
  const base: Snap | null = mode === 'off' ? snapOf(calc) : core ? snapOf(core) : null
  const on: Snap = { npv: h.npv, npv5: h.npv_5yr, roi: h.roi_pct, payback: h.payback_months, acr3: h.acr_year3, rr: h.acr_run_rate, perPlant: h.acr_per_plant_year }
  const cur: Snap | null = mode === 'custom' ? snapOf(calc) : null
  const rows: { k: string; label: string; f: (s: Snap) => string; d: (a: Snap, b: Snap) => string; extra?: [number | undefined, number | undefined] }[] = [
    { k: 'npv', label: 'NPV (3 years)', f: (s) => usd(s.npv), d: (a, b) => sgn(b.npv - a.npv, usd) },
    { k: 'npv5', label: 'NPV (5 years, memo)', f: (s) => usd(s.npv5), d: (a, b) => (a.npv5 != null && b.npv5 != null ? sgn(b.npv5 - a.npv5, usd) : '-') },
    { k: 'roi', label: 'ROI (3 years)', f: (s) => pct(s.roi), d: (a, b) => sgn(b.roi - a.roi, (v) => `${v.toFixed(0)} pts`) },
    { k: 'pb', label: 'Payback', f: (s) => mo(s.payback), d: (a, b) => (a.payback != null && b.payback != null ? sgn(b.payback - a.payback, (v) => `${v.toFixed(1)} mo`) : '-') },
    { k: 'acr3', label: 'Azure ACR year 3', f: (s) => usd(s.acr3), d: (a, b) => `${sgn(b.acr3 - a.acr3, usd)} (${sgn(((b.acr3 - a.acr3) / a.acr3) * 100, (v) => `${v.toFixed(0)} %`)})` },
    { k: 'rr', label: 'ACR run-rate, full roll-out', f: (s) => usd(s.rr), d: (a, b) => `×${(b.rr / a.rr).toFixed(2)}` },
    { k: 'pp', label: 'ACR per plant-year', f: (s) => usd(s.perPlant), d: (a, b) => `×${(b.perPlant / a.perPlant).toFixed(2)}` },
  ]
  const tierRows: { label: string; a?: number; b?: number }[] = [
    { label: '25-plant enterprise run-rate', a: t25?.without_levers.total, b: t25?.with_levers.total },
    { label: '100-plant fleet run-rate (illustrative)', a: fleet?.without_levers.total, b: fleet?.with_levers.total },
  ]
  return (
    <Card title="Base vs expansion levers on" right={<Badge tone={mode === 'on' ? 'info' : mode === 'custom' ? 'warn' : 'mute'}>{mode === 'on' ? 'levers on' : mode === 'custom' ? 'custom mix' : 'levers off'}</Badge>} pad={false}>
      <Table head={['Metric', 'Base · levers off', ...(cur ? ['Your lever mix'] : []), 'Expansion levers on', 'Δ levers on vs base']} className="[&_td:not(:first-child)]:tabnum">
        {rows.map((r) => (
          <tr key={r.k}>
            <Td className="font-medium">{r.label}</Td>
            <Td>{base ? r.f(base) : '…'}</Td>
            {cur && <Td>{r.f(cur)}</Td>}
            <Td>{r.f(on)}</Td>
            <Td className="text-mute">{base ? r.d(base, on) : '…'}</Td>
          </tr>
        ))}
        {tierRows.map((r) => (
          <tr key={r.label}>
            <Td className="font-medium">{r.label}</Td>
            <Td>{usd(r.a)}</Td>
            {cur && <Td className="text-mute">-</Td>}
            <Td>{usd(r.b)}</Td>
            <Td className="text-mute">{r.a && r.b ? `×${(r.b / r.a).toFixed(2)}` : '-'}</Td>
          </tr>
        ))}
      </Table>
      <p className="p-3 text-[11px] text-mute">
        The expansion case is the model's own: all five levers at their Upside adoption on this scenario's other inputs. Levers raise Azure consumption (ACR) and lengthen payback - their benefits arrive later, so the 3-year NPV falls while the 5-year view recovers. The 100-plant fleet figure extrapolates shared capacity beyond the modelled customer and is illustrative only.
      </p>
    </Card>
  )
}

function Tiers({ calc, mode }: { calc: Calc; mode: LeverMode }) {
  const cur = Object.fromEntries(calc.acr.tiers.map((t) => [t.id, t]))
  const custom = mode === 'custom'
  return (
    <Card title="ACR tiers: pilot → 25-plant enterprise → 100-plant fleet (USD / year, run-rate)" pad={false}>
      <Table head={['Tier', 'Plants', 'Assets / plant', 'Core only', 'Levers on', 'Uplift', ...(custom ? ['Your mix'] : []), 'Pull-through']} className="[&_td:not(:first-child)]:tabnum">
        {calc.expansion.tiers.map((t: ExpansionTier) => (
          <tr key={t.id}>
            <Td className="font-medium">
              {t.label} {t.id === 'fleet' && <Badge tone="warn" title="Extrapolates shared capacity beyond the modelled 8-plant customer">illustrative</Badge>}
            </Td>
            <Td>{t.plants}</Td>
            <Td>{t.assets_per_plant}</Td>
            <Td>{usd(t.without_levers.total)}</Td>
            <Td>{usd(t.with_levers.total)}</Td>
            <Td>{t.uplift_multiple.toFixed(2)}×</Td>
            {custom && <Td>{cur[t.id] ? usd(cur[t.id].total) : '-'}</Td>}
            <Td>{cur[t.id] ? `${cur[t.id].pull_through_ratio.toFixed(2)}×` : '-'}</Td>
          </tr>
        ))}
      </Table>
      <p className="p-3 text-[11px] text-mute">Fleet row: shared platform capacity is extrapolated from the modelled scale curve to {calc.expansion.tiers.find((t) => t.id === 'fleet')?.plants} plants - illustrative, not a forecast. Pull-through = adjacent Azure consumption per $ of AI consumption under the current settings.</p>
    </Card>
  )
}

function Levers({ calc, anyOn }: { calc: Calc; anyOn: boolean }) {
  const rows: LeverRow[] = anyOn ? calc.levers : calc.expansion.levers
  return (
    <Card title="Expansion levers E1-E5: economics per deploying plant and at roll-out" pad={false} right={!anyOn && <Badge tone="warn">preview at Upside adoption - levers are off</Badge>}>
      <Table head={['Lever', 'Adoption', 'Start lag', 'Plants', 'Benefit / plant', 'Azure run / plant', 'Net / plant', 'Payback', 'Benefit ÷ run', 'ACR run-rate', '3-y NPV']} className="[&_table]:text-[13px] [&_td:not(:first-child)]:tabnum [&_td:not(:first-child)]:whitespace-nowrap [&_td:first-child]:min-w-[15rem]">
        {rows.map((l) => (
          <tr key={l.id} title={l.note}>
            <Td className="font-medium"><span className="text-accent">{l.id}</span> {l.label}</Td>
            <Td>{(l.adoption * 100).toFixed(0)} %</Td>
            <Td>{l.start_lag_months} mo</Td>
            <Td>{l.deploying_plants_at_full_rollout.toFixed(1)}</Td>
            <Td>{usd(l.per_deploying_plant.benefit)}</Td>
            <Td>{usd(l.per_deploying_plant.azure_run_cost)}</Td>
            <Td>{usd(l.per_deploying_plant.net)}</Td>
            <Td>{mo(l.per_deploying_plant.payback_months)}</Td>
            <Td>{l.per_deploying_plant.benefit_to_run_cost_ratio?.toFixed(1) ?? '-'}×</Td>
            <Td>{usd(l.run_rate.azure)}</Td>
            <Td className={l.npv < 0 ? 'text-bad' : ''}>{usd(l.npv)}</Td>
          </tr>
        ))}
      </Table>
      <p className="p-3 text-[11px] text-mute">Per-plant columns are per deploying plant per year (payback = months after that plant's go-live). Enterprise-fixed platform items (shared capacity, security and data-platform services) are excluded there but included in the ACR run-rate and in the lever's own 3-year NPV. Hover a row for the lever description.</p>
    </Card>
  )
}

function LineItems({ calc }: { calc: Calc }) {
  const [all, setAll] = useState(false)
  const items = [...calc.acr.line_items].sort((a, b) => b.annual - a.annual)
  const shown = all ? items : items.slice(0, 15)
  return (
    <Card title={`ACR line items (${items.length}, steady-state annual)`} pad={false} right={<Button size="sm" onClick={() => setAll(!all)}>{all ? 'Show top 15' : `Show all ${items.length}`}</Button>}>
      <Table head={['Item', 'Service family', 'Lever', 'Quantity / yr', 'Unit price', 'Annual ACR']} className="[&_td:not(:first-child)]:tabnum">
        {shown.map((i) => (
          <tr key={`${i.lever}-${i.id}`}>
            <Td>{i.item}</Td>
            <Td className="text-mute">{calc.costs.family_labels[i.family] ?? i.family}</Td>
            <Td>{i.lever === 'core' ? 'core' : <span className="text-accent">{i.lever}</span>}</Td>
            <Td>{i.quantity.toLocaleString('en-US', { maximumFractionDigits: 1 })} {i.unit}</Td>
            <Td>${i.unit_price.toLocaleString('en-US', { maximumFractionDigits: 4 })}</Td>
            <Td>{usd(i.annual)}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  )
}

export default function CalcResults({ calc, core, sens, sensStale, meta, scenario, mode, switchesOnly }: { calc: Calc; core: Calc | null; sens: SensResult | null; sensStale: boolean; meta: Meta; scenario: string; mode: LeverMode; switchesOnly: boolean }) {
  const years = calc.horizon_years
  const plants = calc.acr.tiers.find((t) => t.id === 'customer')?.plants ?? 8
  const anyOn = Object.values(calc.acr.lever_adoption).some((v) => v > 0)
  const ref: Headline | undefined = meta.reference.headline[scenario as keyof typeof meta.reference.headline]
  const refVals = ref && (mode === 'on' ? { npv: ref.expansion_npv, acr3: ref.expansion_acr_year3, rr: ref.expansion_acr_run_rate } : { npv: ref.npv, acr3: ref.acr_year3, rr: ref.acr_run_rate })
  const parity = refVals && switchesOnly && mode !== 'custom'
  const matches = parity && [[calc.roi.npv, refVals.npv], [calc.acr.by_year[2], refVals.acr3], [calc.acr.run_rate_year3, refVals.rr]].every(([a, b]) => Math.abs(a - b) <= Math.abs(b) * 0.005 + 1e-6)
  const benefitKeys = nonZero(calc.benefits.by_category)
  const fam = stackedRows(calc.acr.by_family, calc.acr.run_rate_by_family, years)
  const lev = stackedRows(calc.acr.by_lever, calc.acr.run_rate_by_lever, years)
  const leverName = (k: string) => (k === 'core' ? 'Core platform' : `${k} ${calc.levers.find((l) => l.id === k)?.label ?? ''}`.trim())
  const path = calc.expansion.path.slice(0, calc.expansion.path.findIndex((p) => p.id === 'expansion') + 1)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5 xl:grid-cols-9" data-testid="calc-headline">
        <Stat label={`NPV (${years} y)`} value={usd(calc.roi.npv)} tone={calc.roi.npv > 0 ? 'ok' : 'bad'} sub={`@ ${(calc.roi.discount_rate * 100).toFixed(0)} %`} />
        <Stat label="ROI" value={pct(calc.roi.roi_pct)} tone={calc.roi.roi_pct > 0 ? 'ok' : 'bad'} />
        <Stat label="Payback" value={mo(calc.roi.payback_months)} />
        <Stat label="IRR" value={pct(calc.roi.irr_pct)} />
        <Stat label="Benefits" value={usd(calc.benefits.total)} sub="risk-adjusted" tone="ok" />
        <Stat label="Costs" value={usd(calc.costs.total)} sub="Azure + other" />
        <Stat label="Azure ACR year 3" value={usd(calc.acr.by_year[2])} sub={anyOn ? 'core + levers' : 'core platform'} tone="info" />
        <Stat label="ACR run-rate" value={usd(calc.acr.run_rate_year3)} sub={`${plants} plants, full roll-out`} tone="info" />
        <Stat label="ACR / plant-year" value={usd(calc.acr.per_plant_year)} sub={`pull-through ${calc.acr.pull_through_ratio.toFixed(2)}×`} />
      </div>
      {parity && refVals && (
        <p className="text-[11px] text-mute" data-testid="calc-parity">
          {matches ? <Badge tone="ok">matches outputs.json</Badge> : <Badge tone="bad">differs from outputs.json</Badge>} Business-case model v{meta.reference.model_version}, {scenario}{mode === 'on' ? ' + expansion levers' : ''}: reference NPV {usd(refVals.npv)}, year-3 ACR {usd(refVals.acr3)}, run-rate {usd(refVals.rr)}. This page runs the same model code (<Mono>model.compute</Mono>).
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Comparison calc={calc} core={core} mode={mode} />
        <Card title={`ACR run-rate path: core → each lever → levers on (${plants} plants)`}>
          <Waterfall steps={path} />
          <p className="mt-1 text-[11px] text-mute">{path.filter((p) => p.kind === 'delta').map((p) => `${p.id} ${p.label}`).join(' · ')}</p>
          <p className="mt-2 text-[11px] text-mute">Each bar is the steady-state annual Azure consumption (ACR) one lever adds on top of the core platform at the Upside adoption of the expansion case; the last bar is the total.</p>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="ACR by service family (USD / year: Year 1-3 and run-rate)">
          <Bars data={fam.rows} x="x" stacked legend yFormatter={usd} bars={fam.keys.map((k, i) => ({ key: k, name: calc.costs.family_labels[k] ?? k, color: FAMILY_COLORS[i % FAMILY_COLORS.length] }))} height={320} />
        </Card>
        <Card title="ACR by lever (USD / year: Year 1-3 and run-rate)">
          <Bars data={lev.rows} x="x" stacked legend yFormatter={usd} bars={lev.keys.map((k) => ({ key: k, name: leverName(k), color: LEVER_COLORS[k] }))} height={320} />
          {!anyOn && <p className="mt-1 text-[11px] text-mute">Levers are off, so only the core platform consumes Azure. Switch "Expansion levers on" to stack E1-E5 on top.</p>}
        </Card>
      </div>
      <Tiers calc={calc} mode={mode} />
      <Levers calc={calc} anyOn={anyOn} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Benefits by category (risk-adjusted, USD / year)">
          <Bars data={byYear(calc.benefits.by_category, benefitKeys, years)} x="x" stacked legend yFormatter={usd} bars={benefitKeys.map((k, i) => ({ key: k, name: calc.benefits.category_labels[k] ?? k, color: FAMILY_COLORS[i % FAMILY_COLORS.length] }))} height={300} />
        </Card>
        <Card title="Net benefit & cumulative cash (USD)">
          <Lines data={calc.roi.net_benefit_by_year.map((v, i) => ({ year: `Y${i + 1}`, net: Math.round(v), cumulative: Math.round(calc.roi.cumulative[i]) }))} x="year" yFormatter={usd} lines={[{ key: 'net', name: 'net benefit', color: '#38bdf8' }, { key: 'cumulative', name: 'cumulative', color: '#34d399' }]} height={300} legend refs={[{ y: 0, label: '', color: '#8499ae' }]} />
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Sensitivity: which assumption moves NPV the most?" right={<Mono>base NPV {usd(sens?.npv ?? calc.roi.npv)}</Mono>}>
          {sens ? <div className={sensStale ? 'opacity-40 transition-opacity' : ''}><Tornado label="Sensitivity tornado of NPV" base={sens.npv} items={sens.npvItems.map((s) => ({ id: s.id, label: s.label, low: s.npv_low, high: s.npv_high }))} /></div> : <Empty>Computing sensitivity…</Empty>}
        </Card>
        <Card title="Sensitivity: which assumption moves year-3 ACR the most?" right={<Mono>base year-3 ACR {usd(sens?.acr3 ?? calc.acr.by_year[2])}</Mono>}>
          {sens ? <div className={sensStale ? 'opacity-40 transition-opacity' : ''}><Tornado label="Sensitivity tornado of year-3 ACR" base={sens.acr3} items={sens.acrItems.map((s) => ({ id: s.id, label: s.label, low: s.acr_year3_low, high: s.acr_year3_high }))} /></div> : <Empty>Computing sensitivity…</Empty>}
        </Card>
      </div>
      <LineItems calc={calc} />
      <p className="text-[11px] text-mute">Prices ({meta.price_basis.currency}, retrieved {meta.price_basis.retrieved_on}): {meta.price_basis.basis}. ACR is an estimate of the Azure consumption this solution drives - not a commitment or a forecast.</p>
    </div>
  )
}
