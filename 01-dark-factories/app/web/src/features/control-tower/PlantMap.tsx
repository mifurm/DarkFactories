import clsx from 'clsx'
import { STATE_COLOR } from '../../components/bits'

export type AssetT = {
  id: string
  name: string
  type: string
  area: string
  line: string
  cell: string
  zone: string
  index: number
  state: string
  reason: string
  speed: number
  power_kw: number
  queue: number
  current: string[] | null
  safe_stop: boolean
  offset: number
  inline_inspect: boolean
  kit: number
  sensors?: Record<string, number>
  temp?: number
}
export type MapT = { areas: Record<string, { id: string; type: string; zone: string }[]>; zones: Record<string, string[]> }

const W = 118
const H = 58
const GAP = 10
const LAYOUT: { area: string; x: number; y: number; title: string }[] = [
  { area: 'machining', x: 16, y: 26, title: 'MACHINING' },
  { area: 'molding', x: 700, y: 26, title: 'MOLDING' },
  { area: 'assembly-test', x: 16, y: 136, title: 'ASSEMBLY · TEST · PACK' },
  { area: 'utilities', x: 830, y: 136, title: 'UTILITIES' },
  { area: 'logistics', x: 16, y: 246, title: 'LOGISTICS · WAREHOUSE · AMR' },
]

export function PlantMap({ assets, map, zones, selected, onSelect }: { assets: AssetT[]; map: MapT | null; zones: Record<string, { occupied: boolean }>; selected?: string | null; onSelect: (id: string) => void }) {
  const byId = new Map(assets.map((a) => [a.id, a]))
  const areas = map?.areas ?? {}
  return (
    <svg viewBox="0 0 1100 336" className="w-full select-none" role="img" aria-label="Plant map: asset tiles coloured by state">
      {LAYOUT.map(({ area, x, y, title }) => {
        const list = areas[area] ?? []
        const zs = [...new Set(list.map((a) => a.zone))]
        return (
          <g key={area}>
            <text x={x} y={y - 8} fontSize={10} letterSpacing={1.6} fill="#8499ae" fontWeight={600}>{title}</text>
            {zs.map((z, i) => (
              <g key={z} transform={`translate(${x + (area === 'utilities' ? 70 : 200) + i * 92}, ${y - 17})`}>
                <rect width={86} height={13} rx={4} fill={zones[z]?.occupied ? '#f8717133' : '#ffffff0d'} stroke={zones[z]?.occupied ? '#f87171' : 'none'} />
                <text x={43} y={9.5} fontSize={8.5} textAnchor="middle" fill={zones[z]?.occupied ? '#f87171' : '#8499ae'}>{z}{zones[z]?.occupied ? ' · HUMAN' : ''}</text>
              </g>
            ))}
            {list.map((m, i) => {
              const a = byId.get(m.id)
              const col = STATE_COLOR[a?.state ?? 'IDLE'] ?? '#64748b'
              const tx = x + i * (W + GAP)
              const sel = selected === m.id
              return (
                <g key={m.id} transform={`translate(${tx},${y})`} onClick={() => onSelect(m.id)} className="cursor-pointer" role="button" tabIndex={0} aria-label={`${m.id} ${a?.state ?? ''}`} onKeyDown={(e) => e.key === 'Enter' && onSelect(m.id)}>
                  <rect width={W} height={H} rx={8} fill="#162231" stroke={sel ? '#38bdf8' : col} strokeOpacity={sel ? 1 : 0.55} strokeWidth={sel ? 2 : 1} />
                  <rect width={5} height={H} rx={2.5} fill={col} />
                  <text x={14} y={20} fontSize={12.5} fontWeight={600} fill="#d9e4ef">{m.id}</text>
                  <text x={14} y={35} fontSize={10} fill={col}>{a?.state ?? '…'}{a?.reason && a.state !== 'RUN' ? ` · ${a.reason}`.slice(0, 16) : ''}</text>
                  <text x={14} y={49} fontSize={10} fill="#8499ae">{a ? `${a.power_kw.toFixed(1)} kW · q${a.queue}` : ''}</text>
                  {a?.safe_stop && <text x={W - 8} y={16} fontSize={11} textAnchor="end" fill="#f87171">⛔</text>}
                  {a?.state === 'DOWN' && <circle cx={W - 14} cy={H - 14} r={12} fill="none" stroke="#f87171" className="pulse-ring" />}
                  {a?.state === 'RUN' && <circle cx={W - 12} cy={H - 14} r={3} fill={col} className={clsx('pulse-dot')} />}
                </g>
              )
            })}
          </g>
        )
      })}
      <g transform="translate(560,246)">
        {Object.entries(STATE_COLOR).map(([k, c], i) => (
          <g key={k} transform={`translate(${(i % 4) * 120},${Math.floor(i / 4) * 20})`}>
            <rect width={10} height={10} rx={2} fill={c} />
            <text x={16} y={9} fontSize={10} fill="#8499ae">{k}</text>
          </g>
        ))}
        <text y={52} fontSize={9.5} fill="#8499ae">Flow: MACH/MOLD → ASM → TEST → PACK → WH · click a tile for sensors and actions</text>
      </g>
    </svg>
  )
}
