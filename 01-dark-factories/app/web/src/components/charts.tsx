import type { ReactNode } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const AXIS = { stroke: '#8499ae', fontSize: 11 }
const GRID = '#213245'
const TIP = { contentStyle: { background: '#101822', border: '1px solid #213245', borderRadius: 8, fontSize: 12 }, labelStyle: { color: '#d9e4ef' } }

export type Line_ = { key: string; color?: string; name?: string; dash?: string; width?: number }
export const PALETTE = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#f472b6', '#22d3ee']

export function Lines({ data, x = 'x', lines, height = 220, refs = [], yDomain, xFormatter, yFormatter, unit, legend }: { data: any[]; x?: string; lines: Line_[]; height?: number; refs?: { y: number; label?: string; color?: string }[]; yDomain?: [number | 'auto' | 'dataMin' | 'dataMax', number | 'auto' | 'dataMin' | 'dataMax']; xFormatter?: (v: any) => string; yFormatter?: (v: any) => string; unit?: string; legend?: boolean }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x} {...AXIS} tickFormatter={xFormatter} minTickGap={32} />
          <YAxis {...AXIS} domain={yDomain ?? ['auto', 'auto']} unit={unit} width={yFormatter ? 64 : 52} tickFormatter={yFormatter} />
          <Tooltip {...TIP} formatter={yFormatter ? ((v: unknown) => yFormatter(v)) as never : undefined} />
          {legend && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {refs.map((r, i) => (
            <ReferenceLine key={i} y={r.y} stroke={r.color ?? '#f87171'} strokeDasharray="4 3" label={{ value: r.label, fill: r.color ?? '#f87171', fontSize: 10, position: 'insideTopRight' }} />
          ))}
          {lines.map((l, i) => (
            <Line key={l.key} type="monotone" dataKey={l.key} name={l.name ?? l.key} stroke={l.color ?? PALETTE[i % PALETTE.length]} strokeWidth={l.width ?? 1.8} strokeDasharray={l.dash} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Areas({ data, x = 'x', keys, height = 200, xFormatter, unit }: { data: any[]; x?: string; keys: Line_[]; height?: number; xFormatter?: (v: any) => string; unit?: string }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x} {...AXIS} tickFormatter={xFormatter} minTickGap={32} />
          <YAxis {...AXIS} unit={unit} width={52} />
          <Tooltip {...TIP} />
          {keys.map((l, i) => (
            <Area key={l.key} type="monotone" dataKey={l.key} name={l.name ?? l.key} stroke={l.color ?? PALETTE[i % PALETTE.length]} fill={l.color ?? PALETTE[i % PALETTE.length]} fillOpacity={0.16} strokeWidth={1.6} isAnimationActive={false} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Bars({ data, x = 'x', bars, height = 220, layout = 'horizontal', stacked, unit, yFormatter, legend }: { data: any[]; x?: string; bars: Line_[]; height?: number; layout?: 'horizontal' | 'vertical'; stacked?: boolean; unit?: string; yFormatter?: (v: any) => string; legend?: boolean }) {
  const vertical = layout === 'vertical'
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout={layout} margin={{ top: 6, right: 12, bottom: 0, left: vertical ? 40 : -8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={!vertical} vertical={vertical} />
          {vertical ? <YAxis type="category" dataKey={x} {...AXIS} width={90} /> : <XAxis dataKey={x} {...AXIS} />}
          {vertical ? <XAxis type="number" {...AXIS} unit={unit} /> : <YAxis {...AXIS} unit={unit} width={yFormatter ? 64 : 52} tickFormatter={yFormatter} />}
          <Tooltip {...TIP} cursor={{ fill: 'rgba(255,255,255,0.04)' }} formatter={yFormatter ? ((v: unknown) => yFormatter(v)) as never : undefined} />
          {legend && <Legend wrapperStyle={{ fontSize: 10 }} />}
          {bars.map((b, i) => (
            <Bar key={b.key} dataKey={b.key} name={b.name ?? b.key} fill={b.color ?? PALETTE[i % PALETTE.length]} stackId={stacked ? 's' : undefined} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ChartCaption({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-[11px] text-mute">{children}</p>
}
