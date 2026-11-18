import clsx from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Card({ title, right, children, className, pad = true }: { title?: ReactNode; right?: ReactNode; children?: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx('rounded-xl border border-line bg-panel shadow-[0_1px_0_rgba(255,255,255,0.02)_inset]', className)}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mute">{title}</h2>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

const tones = {
  ok: 'bg-ok/15 text-ok ring-ok/30',
  warn: 'bg-warn/15 text-warn ring-warn/30',
  bad: 'bg-bad/15 text-bad ring-bad/30',
  info: 'bg-accent/15 text-accent ring-accent/30',
  violet: 'bg-violet/15 text-violet ring-violet/30',
  mute: 'bg-white/5 text-mute ring-white/10',
} as const
export type Tone = keyof typeof tones

export function Badge({ tone = 'mute', children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset', tones[tone], className)}>
      {children}
    </span>
  )
}

export function Stat({ label, value, sub, tone, className }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; className?: string }) {
  const color = tone === 'ok' ? 'text-ok' : tone === 'warn' ? 'text-warn' : tone === 'bad' ? 'text-bad' : tone === 'info' ? 'text-accent' : 'text-ink'
  return (
    <div className={clsx('rounded-lg border border-line bg-panel2/60 px-3 py-2', className)}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mute">{label}</div>
      <div className={clsx('tabnum mt-0.5 text-xl font-semibold leading-tight', color)}>{value}</div>
      {sub != null && <div className="tabnum mt-0.5 text-[11px] text-mute">{sub}</div>}
    </div>
  )
}

export function Button({ tone = 'default', size = 'md', className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'default' | 'primary' | 'danger' | 'ghost' | 'ok'; size?: 'sm' | 'md' }) {
  const t = {
    default: 'border-line bg-panel2 hover:bg-[#1c2c3f] text-ink',
    primary: 'border-accent/50 bg-accent/15 hover:bg-accent/25 text-accent',
    danger: 'border-bad/50 bg-bad/15 hover:bg-bad/25 text-bad',
    ok: 'border-ok/50 bg-ok/15 hover:bg-ok/25 text-ok',
    ghost: 'border-transparent hover:bg-white/5 text-mute hover:text-ink',
  }[tone]
  return (
    <button
      {...rest}
      className={clsx('inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40', size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm', t, className)}
    />
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={clsx('-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors', value === t.id ? 'border-accent text-accent' : 'border-transparent text-mute hover:text-ink')}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-mute" role="status">
      <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-accent" />
      <span className="text-sm">{label}…</span>
    </div>
  )
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null
  return <div role="alert" className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>
}

export function Page({ title, subtitle, right, children }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1500px] p-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-0.5 max-w-3xl text-sm text-mute">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">{right}</div>
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

export function Spark({ data, w = 120, h = 28, color = '#38bdf8', fill = true }: { data: number[]; w?: number; h?: number; color?: string; fill?: boolean }) {
  if (!data || data.length < 2) return <svg width={w} height={h} />
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => [(i / (data.length - 1)) * (w - 2) + 1, h - 2 - ((v - min) / span) * (h - 4)] as const)
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} role="img" aria-label="trend">
      {fill && <path d={`${d} L${w - 1} ${h} L1 ${h} Z`} fill={color} opacity={0.12} />}
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={clsx('overflow-x-auto', className)}>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line text-[11px] uppercase tracking-wider text-mute">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/60">{children}</tbody>
      </table>
    </div>
  )
}

export const Td = ({ children, className }: { children?: ReactNode; className?: string }) => <td className={clsx('px-3 py-2 align-top', className)}>{children}</td>

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-mute">{children}</div>
}

export function Kv({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/50 py-1.5 text-sm last:border-0">
      <span className="text-mute">{k}</span>
      <span className="tabnum text-right">{v}</span>
    </div>
  )
}
