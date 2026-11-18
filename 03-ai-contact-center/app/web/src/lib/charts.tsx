import { Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export const PALETTE = ['#2563eb', '#7c3aed', '#0891b2', '#16a34a', '#d97706', '#dc2626', '#db2777', '#4f46e5', '#0d9488', '#64748b']

type Row = Record<string, string | number | null | undefined>
interface Serie {
  key: string
  name?: string
  color?: string
  dashed?: boolean
}
interface Ref {
  y: number
  label: string
  color?: string
}

const axis = { stroke: '#94a3b8', fontSize: 11, tickLine: false } as const
const grid = <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />

export function LineSeries({ data, x, lines, height = 220, yFmt, refs, area }: { data: Row[]; x: string; lines: Serie[]; height?: number; yFmt?: (v: number) => string; refs?: Ref[]; area?: boolean }) {
  const Chart = area ? AreaChart : LineChart
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Chart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        {grid}
        <XAxis dataKey={x} {...axis} minTickGap={24} />
        <YAxis {...axis} width={48} tickFormatter={yFmt} />
        <Tooltip formatter={(v) => (typeof v === 'number' && yFmt ? yFmt(v) : v)} contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }} />
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

export function BarSeries({ data, x, bars, height = 220, stacked, horizontal, yFmt, refs }: { data: Row[]; x: string; bars: Serie[]; height?: number; stacked?: boolean; horizontal?: boolean; yFmt?: (v: number) => string; refs?: Ref[] }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 6, right: 12, left: horizontal ? 24 : 0, bottom: 0 }}>
        {grid}
        {horizontal ? <XAxis type="number" {...axis} tickFormatter={yFmt} /> : <XAxis dataKey={x} {...axis} minTickGap={12} />}
        {horizontal ? <YAxis type="category" dataKey={x} {...axis} width={150} /> : <YAxis {...axis} width={48} tickFormatter={yFmt} />}
        <Tooltip formatter={(v) => (typeof v === 'number' && yFmt ? yFmt(v) : v)} contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }} />
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
export function ComboSeries({ data, x, bars, lines, height = 240, yFmt }: { data: Row[]; x: string; bars: Serie[]; lines: Serie[]; height?: number; yFmt?: (v: number) => string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        {grid}
        <XAxis dataKey={x} {...axis} minTickGap={14} />
        <YAxis {...axis} width={44} tickFormatter={yFmt} />
        <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12 }} />
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
