import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useState } from 'react'
import { useI18n } from '../i18n'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

export function PageHeader({ title, subtitle, actions, icon: Icon }: { title: string; subtitle?: ReactNode; actions?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        {Icon && (
          <span className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 text-white shadow-sm">
            <Icon size={20} aria-hidden />
          </span>
        )}
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          {subtitle && <p className="mt-0.5 max-w-3xl text-sm text-slate-600">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Card({ title, subtitle, actions, children, className, pad = true }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

const TONES: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  red: 'bg-rose-50 text-rose-700 ring-rose-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
  cyan: 'bg-cyan-50 text-cyan-800 ring-cyan-200',
}
export function Badge({ children, tone = 'slate', title, className }: { children: ReactNode; tone?: keyof typeof TONES | string; title?: string; className?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset', TONES[tone] ?? TONES.slate, className)}>
      {children}
    </span>
  )
}

export function Stat({ label, value, hint, tone, icon: Icon, delta }: { label: string; value: ReactNode; hint?: ReactNode; tone?: string; icon?: LucideIcon; delta?: ReactNode }) {
  const color = tone === 'good' ? 'text-emerald-600' : tone === 'bad' ? 'text-rose-600' : tone === 'warn' ? 'text-amber-600' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
      <div className="flex items-center justify-between text-xs font-medium text-slate-500">
        <span>{label}</span>
        {Icon && <Icon size={14} aria-hidden className="text-slate-400" />}
      </div>
      <div className={cx('mt-1 text-2xl font-semibold tabular-nums', color)}>{value}</div>
      {(hint || delta) && (
        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
          {delta}
          {hint}
        </div>
      )}
    </div>
  )
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'success'; size?: 'sm' | 'md'; busy?: boolean; icon?: LucideIcon }
export function Button({ variant = 'secondary', size = 'md', busy, icon: Icon, children, className, disabled, ...rest }: BtnProps) {
  const base = 'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50'
  const sz = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm'
  const v = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm',
    secondary: 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50',
    danger: 'bg-rose-600 text-white hover:bg-rose-700',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700',
    ghost: 'text-slate-700 hover:bg-slate-100',
  }[variant]
  return (
    <button className={cx(base, sz, v, className)} disabled={disabled || busy} {...rest}>
      {busy ? <Loader2 size={14} className="animate-spin" aria-hidden /> : Icon ? <Icon size={14} aria-hidden /> : null}
      {children}
    </button>
  )
}

export function Spinner({ label }: { label?: string }) {
  const { t } = useI18n()
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Loader2 className="animate-spin" size={16} aria-hidden /> {label ?? t('Loading…')}
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n()
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="flex-1">{msg}</div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          {t('Retry')}
        </Button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{children}</div>
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: ReactNode }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 rounded-xl bg-slate-200/60 p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx('rounded-lg px-3 py-1.5 text-sm font-medium transition', value === t.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900')}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function useTab(initial: string) {
  return useState(initial)
}

export interface Col<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  className?: string
  align?: 'right' | 'left' | 'center'
}
export function DataTable<T>({ rows, cols, rowKey, onRowClick, empty, selected, dense }: { rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; onRowClick?: (r: T) => void; empty?: ReactNode; selected?: string | null; dense?: boolean }) {
  const { t } = useI18n()
  if (!rows.length) return <Empty>{empty ?? t('No data')}</Empty>
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
            {cols.map((c) => (
              <th key={c.key} scope="col" className={cx('px-3 py-2 font-medium', c.align === 'right' && 'text-right', c.align === 'center' && 'text-center')}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = rowKey(r)
            return (
              <tr
                key={k}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={cx('border-b border-slate-100 last:border-0', onRowClick && 'cursor-pointer hover:bg-blue-50/50', selected === k && 'bg-blue-50')}
              >
                {cols.map((c) => (
                  <td key={c.key} className={cx(dense ? 'px-3 py-1.5' : 'px-3 py-2.5', 'align-middle', c.align === 'right' && 'text-right tabular-nums', c.align === 'center' && 'text-center', c.className)}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function Progress({ value, max = 1, tone = 'blue', label }: { value: number; max?: number; tone?: string; label?: string }) {
  const { t } = useI18n()
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100))
  const bar = { blue: 'bg-blue-600', green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-rose-500' }[tone] ?? 'bg-blue-600'
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-label={label ?? t('Progress')} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx('h-full rounded-full', bar)} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-slate-400">{hint}</span>}
    </label>
  )
}

export const inputCls = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-blue-500'

export function Slider({ label, value, min, max, step = 1, onChange, format }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 flex justify-between text-xs font-medium text-slate-600">
        <span>{label}</span>
        <span className="tabular-nums text-slate-900">{format ? format(value) : value}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-blue-600" />
    </label>
  )
}

export function Json({ data, max = 360 }: { data: unknown; max?: number }) {
  return (
    <pre data-i18n-skip className="scroll-thin overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100" style={{ maxHeight: max }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export function Dot({ tone = 'green', pulse }: { tone?: 'green' | 'amber' | 'red' | 'slate' | 'blue'; pulse?: boolean }) {
  const c = { green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-rose-500', slate: 'bg-slate-400', blue: 'bg-blue-500' }[tone]
  return <span className={cx('inline-block h-2 w-2 rounded-full', c, pulse && 'animate-pulse')} aria-hidden />
}

export const sentimentTone = (s: number | null | undefined) => (s == null ? 'slate' : s <= -0.5 ? 'red' : s < -0.15 ? 'amber' : s > 0.25 ? 'green' : 'slate')
export const sentimentBg = (s: number) => (s <= -0.6 ? '#fecaca' : s <= -0.25 ? '#fde68a' : s < 0.2 ? '#e2e8f0' : '#bbf7d0')
