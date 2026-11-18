import clsx from 'clsx'
import { useCallback, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { errText } from '../lib/api'
import { Badge, type Tone } from './ui'

export const STATE_COLOR: Record<string, string> = {
  RUN: '#34d399',
  IDLE: '#64748b',
  SETUP: '#38bdf8',
  DOWN: '#f87171',
  MAINT: '#a78bfa',
  BLOCKED: '#fbbf24',
  STARVED: '#f59e0b',
}

export const stateTone = (s: string): Tone => ({ RUN: 'ok', DOWN: 'bad', MAINT: 'violet', SETUP: 'info', BLOCKED: 'warn', STARVED: 'warn' }[s] as Tone) ?? 'mute'

export const StateBadge = ({ state }: { state: string }) => <Badge tone={stateTone(state)}>{state}</Badge>

export const outcomeTone = (o: string | null | undefined): Tone => {
  const v = (o ?? '').toLowerCase()
  if (/(executed|approved|auto|ok|done|pass|valid|applied|accepted)/.test(v)) return 'ok'
  if (/(veto|denied|reject|fail|breach|error|blocked|expired|kill)/.test(v)) return 'bad'
  if (/(pending|approval|escalat|defer|warn|arbitrat)/.test(v)) return 'warn'
  return 'mute'
}

/** Runs an async action and tracks busy / error state (for buttons and forms). */
export function useAction<T = unknown>() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<T | null>(null)
  const run = useCallback(async (fn: () => Promise<T>) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      setResult(r)
      return r
    } catch (e) {
      setError(errText(e))
      return null
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, result, run, setError, setResult }
}

export function Field({ label, children, hint, className }: { label: ReactNode; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={clsx('block text-sm', className)}>
      <span className="mb-1 block text-[11px] font-medium uppercase tracking-wider text-mute">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-mute">{hint}</span>}
    </label>
  )
}

const inputCls = 'rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm text-ink placeholder:text-mute/60 focus:border-accent focus:outline-none'
const widthOf = (c?: string) => (c && /(^|\s)w-/.test(c) ? '' : 'w-full')
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input className={clsx(inputCls, widthOf(className), className)} {...p} />
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select className={clsx(inputCls, widthOf(className), className)} {...p} />
export const TextArea = ({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className={clsx(inputCls, widthOf(className), 'font-mono text-xs', className)} {...p} />

export function Meter({ value, max = 1, tone = 'info', label }: { value: number; max?: number; tone?: 'ok' | 'warn' | 'bad' | 'info'; label?: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100))
  const color = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', info: 'bg-accent' }[tone]
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label={label} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={clsx('rounded bg-white/5 px-1 py-0.5 font-mono text-[12px]', className)}>{children}</code>
}

export function Json({ data, max = 400 }: { data: unknown; max?: number }) {
  return <pre className="max-h-[400px] overflow-auto rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-snug text-ink/90" style={{ maxHeight: max }}>{JSON.stringify(data, null, 2)}</pre>
}

export const simTime = (iso?: string | null) => (iso ? iso.replace('T', ' ').slice(5, 16) : '-')
export const hhmm = (t: number) => `${String(Math.floor(t / 60) % 24).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`

/** Minimal, safe Markdown renderer (headings, lists, bold, pipe tables) - no HTML injection. */
export function Md({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] => s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => (p.startsWith('**') ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith('`') ? <code key={i} className="rounded bg-white/5 px-1 font-mono text-[12px]">{p.slice(1, -1)}</code> : p))
  const lines = text.split('\n')
  const out: ReactNode[] = []
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    if (l.startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        if (!/^\|[\s:|-]+\|$/.test(lines[i])) rows.push(lines[i].split('|').slice(1, -1).map((c) => c.trim()))
        i++
      }
      i--
      out.push(
        <table key={i} className="my-2 w-full border-collapse text-[12px]"><thead><tr>{rows[0]?.map((c, k) => <th key={k} className="border-b border-line px-2 py-1 text-left text-mute">{inline(c)}</th>)}</tr></thead><tbody>{rows.slice(1).map((r, k) => <tr key={k} className="border-b border-line/40">{r.map((c, j) => <td key={j} className="px-2 py-1">{inline(c)}</td>)}</tr>)}</tbody></table>,
      )
    } else if (/^#{1,3} /.test(l)) {
      const lvl = l.match(/^#+/)![0].length
      out.push(<div key={i} className={clsx('mt-3 font-semibold', lvl === 1 ? 'text-lg' : lvl === 2 ? 'text-base text-accent' : 'text-sm')}>{inline(l.replace(/^#+ /, ''))}</div>)
    } else if (/^\s*[-*] /.test(l)) {
      out.push(<div key={i} className="flex gap-2 pl-2 text-[13px]"><span className="text-mute">•</span><span>{inline(l.replace(/^\s*[-*] /, ''))}</span></div>)
    } else if (l.trim()) {
      out.push(<p key={i} className="my-1 text-[13px] leading-snug">{inline(l)}</p>)
    }
  }
  return <div>{out}</div>
}
