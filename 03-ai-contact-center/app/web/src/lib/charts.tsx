import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useI18n } from '../i18n'

export const PALETTE = ['#2563eb', '#7c3aed', '#0891b2', '#16a34a', '#d97706', '#dc2626', '#db2777', '#4f46e5', '#0d9488', '#64748b']

type Row = Record<string, string | number | null | undefined>
interface Serie {
  key: string
  /** already translated legend / tooltip name */
  name?: string
  color?: string
  dashed?: boolean
}
interface Ref {
  y: number
  /** already translated */
  label: string
  color?: string
}

const axis = { stroke: '#94a3b8', fontSize: 11, tickLine: false } as const
const grid = <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
const tip = { borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }

/** Tooltip / tick formatting follows the UI language (decimal comma, NBSP thousands in Polish). */
function useFormats(yFmt?: (v: number) => string, xFmt?: (v: string | number) => string, fullKey?: string) {
  const { fmt } = useI18n()
  const value = (v: unknown) => (typeof v === 'number' ? (yFmt ? yFmt(v) : fmt.plain(v)) : (v as string))
  // `fullKey` names a row field that holds the untruncated category name for the tooltip
  const label = xFmt || fullKey
    ? (l: unknown, payload?: readonly { payload?: Row }[]) => {
        const full = fullKey ? payload?.[0]?.payload?.[fullKey] : undefined
        return typeof full === 'string' ? full : xFmt ? xFmt(l as string | number) : (l as string)
      }
    : undefined
  return { value, label, tick: xFmt ? (v: unknown) => xFmt(v as string | number) : undefined }
}

/** Y-axis width that fits the longest tick label ("30,0 mln USD" is much wider than "$30.0M"), never narrower than `base`. */
function yAxisWidth(data: Row[], keys: string[], yFmt: ((v: number) => string) | undefined, base: number): number {
  if (!yFmt) return base
  let lo = 0
  let hi = 0
  for (const r of data) for (const k of keys) {
    const v = r[k]
    if (typeof v === 'number' && Number.isFinite(v)) {
      lo = Math.min(lo, v)
      hi = Math.max(hi, v)
    }
  }
  const longest = Math.max(yFmt(lo).length, yFmt(hi).length, yFmt((lo + hi) / 2).length)
  return Math.max(base, Math.ceil(longest * 6.3) + 12)
}

export function LineSeries({ data, x, lines, height = 220, yFmt, xFmt, refs, area }: { data: Row[]; x: string; lines: Serie[]; height?: number; yFmt?: (v: number) => string; xFmt?: (v: string | number) => string; refs?: Ref[]; area?: boolean }) {
  const f = useFormats(yFmt, xFmt)
  const Chart = area ? AreaChart : LineChart
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Chart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        {grid}
        <XAxis dataKey={x} {...axis} minTickGap={24} tickFormatter={f.tick} />
        <YAxis {...axis} width={yAxisWidth(data, lines.map((l) => l.key), yFmt, 48)} tickFormatter={yFmt} />
        <Tooltip formatter={f.value} labelFormatter={f.label} contentStyle={tip} />
        {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {refs?.map((r) => <ReferenceLine key={r.label} y={r.y} stroke={r.color ?? '#dc2626'} strokeDasharray="4 4" label={{ value: r.label, fontSize: 10, fill: r.color ?? '#dc2626', position: 'insideTopRight' }} />)}
        {lines.map((l, i) =>
          area ? (
            <Area key={l.key} type="monotone" dataKey={l.key} name={l.name ?? l.key} stroke={l.color ?? PALETTE[i % PALETTE.length]} fill={l.color ?? PALETTE[i % PALETTE.length]} fillOpacity={0.15} strokeWidth={2} dot={false} isAnimationActive={false} />
          ) : (
            <Line key={l.key} type="monotone" dataKey={l.key} name={l.name ?? l.key} stroke={l.color ?? PALETTE[i % PALETTE.length]} strokeWidth={2} strokeDasharray={l.dashed ? '5 4' : undefined} dot={false} isAnimationActive={false} />
          ),
        )}
      </Chart>
    </ResponsiveContainer>
  )
}

export function BarSeries({ data, x, bars, height = 220, stacked, horizontal, yFmt, xFmt, refs, labelWidth = 150 }: { data: Row[]; x: string; bars: Serie[]; height?: number; stacked?: boolean; horizontal?: boolean; yFmt?: (v: number) => string; xFmt?: (v: string | number) => string; refs?: Ref[]; labelWidth?: number }) {
  const f = useFormats(yFmt, xFmt)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 6, right: 12, left: horizontal ? 24 : 0, bottom: 0 }}>
        {grid}
        {horizontal ? <XAxis type="number" {...axis} tickFormatter={yFmt} /> : <XAxis dataKey={x} {...axis} minTickGap={12} tickFormatter={f.tick} />}
        {horizontal ? <YAxis type="category" dataKey={x} {...axis} width={labelWidth} tickFormatter={f.tick} /> : <YAxis {...axis} width={yAxisWidth(data, bars.map((b) => b.key), yFmt, 48)} tickFormatter={yFmt} />}
        <Tooltip formatter={f.value} labelFormatter={f.label} contentStyle={tip} />
        {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {refs?.map((r) => <ReferenceLine key={r.label} y={r.y} stroke={r.color ?? '#dc2626'} strokeDasharray="4 4" label={{ value: r.label, fontSize: 10, fill: r.color ?? '#dc2626' }} />)}
        {bars.map((b, i) => (
          <Bar key={b.key} dataKey={b.key} name={b.name ?? b.key} fill={b.color ?? PALETTE[i % PALETTE.length]} stackId={stacked ? 's' : undefined} radius={stacked ? 0 : [4, 4, 0, 0]} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Bars + lines on one axis (e.g. requirement vs schedule coverage, volumes vs forecast). */
export function ComboSeries({ data, x, bars, lines, height = 240, yFmt, xFmt, fullKey }: { data: Row[]; x: string; bars: Serie[]; lines: Serie[]; height?: number; yFmt?: (v: number) => string; xFmt?: (v: string | number) => string; fullKey?: string }) {
  const f = useFormats(yFmt, xFmt, fullKey)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        {grid}
        <XAxis dataKey={x} {...axis} minTickGap={14} tickFormatter={f.tick} />
        <YAxis {...axis} width={yAxisWidth(data, [...bars, ...lines].map((s) => s.key), yFmt, 44)} tickFormatter={yFmt} />
        <Tooltip formatter={f.value} labelFormatter={f.label} contentStyle={tip} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {bars.map((b, i) => (
          <Bar key={b.key} dataKey={b.key} name={b.name ?? b.key} fill={b.color ?? PALETTE[i % PALETTE.length]} fillOpacity={0.55} isAnimationActive={false} />
        ))}
        {lines.map((l, i) => (
          <Line key={l.key} type="stepAfter" dataKey={l.key} name={l.name ?? l.key} stroke={l.color ?? PALETTE[(i + 3) % PALETTE.length]} strokeWidth={2} strokeDasharray={l.dashed ? '5 4' : undefined} dot={false} isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  )
}
