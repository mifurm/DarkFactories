import type { Driver, Overrides, OverrideValue, Scenario, Switch } from './types'

export const usd = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return '-'
  const a = Math.abs(v)
  const body = a >= 1e6 ? `$${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `$${(a / 1e3).toFixed(0)}k` : `$${a.toFixed(0)}`
  return v < 0 && a >= 0.5 ? `−${body}` : body
}

/** Compact number for driver values and placeholders (4 significant digits, no trailing zeros). */
export function fv(v: unknown): string {
  if (v == null) return 'derived'
  if (Array.isArray(v)) return v.map((x) => (Array.isArray(x) ? `${x[0]}→${x[1]}` : fv(x))).join(' · ')
  if (typeof v !== 'number') return String(v)
  if (Math.abs(v) >= 1e9) return `${+(v / 1e9).toPrecision(4)}B`
  if (Math.abs(v) >= 1e6) return `${+(v / 1e6).toPrecision(4)}M`
  return String(+v.toPrecision(4))
}

export const sameValue = (a: unknown, b: unknown): boolean =>
  Array.isArray(a) && Array.isArray(b) ? a.length === b.length && a.every((x, i) => sameValue(x, b[i])) : a === b

/** Sets an override, or removes it again when it equals what the selected scenario already uses. */
export function setOverride(ov: Overrides, key: string, value: OverrideValue | undefined, scenarioValue: unknown): Overrides {
  const next = { ...ov }
  if (value === undefined || (value !== null && sameValue(value, scenarioValue)) || (value === null && scenarioValue === null)) delete next[key]
  else next[key] = value
  return next
}

/** Free-typed inputs keep their override even when it equals the scenario value (so typing "0.2" never blanks the field). */
export function putOverride(ov: Overrides, key: string, value: OverrideValue | undefined): Overrides {
  const next = { ...ov }
  if (value === undefined) delete next[key]
  else next[key] = value
  return next
}

export const scenarioValue = (d: Driver, scenario: Scenario | string): unknown => d.scenario[scenario as Scenario] ?? d.base

export type LeverMode = 'off' | 'on' | 'custom'

export const adoptionOf = (s: Switch, ov: Overrides, scenario: string): number => {
  const v = ov[s.key]
  return typeof v === 'number' ? v : s.scenario[scenario as Scenario]
}

/** "off" = every lever at 0, "on" = every lever at its Upside adoption (the model's expansion case), anything else is a custom mix. */
export function leverMode(switches: Switch[], ov: Overrides, scenario: string): LeverMode {
  const v = switches.map((s) => adoptionOf(s, ov, scenario))
  if (v.every((x) => x === 0)) return 'off'
  if (v.every((x, i) => x === switches[i].on)) return 'on'
  return 'custom'
}

export function setAllLevers(switches: Switch[], ov: Overrides, scenario: string, on: boolean): Overrides {
  return switches.reduce((acc, s) => setOverride(acc, s.key, on ? s.on : 0, s.scenario[scenario as Scenario]), ov)
}

export const zeroLevers = (switches: Switch[]): Overrides => Object.fromEntries(switches.map((s) => [s.key, 0]))

/** Rows for a stacked "Year 1-3 + run-rate" chart; series that are zero everywhere are dropped. */
export function stackedRows(byYear: Record<string, number[]>, runRate: Record<string, number>, years = 3) {
  const keys = Object.keys(byYear).filter((k) => byYear[k].some((v) => v >= 0.5) || (runRate[k] ?? 0) >= 0.5)
  const row = (x: string, get: (k: string) => number) => ({ x, ...Object.fromEntries(keys.map((k) => [k, Math.round(get(k))])) })
  return {
    keys,
    rows: [...Array.from({ length: years }, (_, i) => row(`Year ${i + 1}`, (k) => byYear[k][i] ?? 0)), row('Run-rate', (k) => runRate[k] ?? 0)],
  }
}

export const nonZero = (rec: Record<string, number[]>) => Object.keys(rec).filter((k) => rec[k].some((v) => Math.abs(v) >= 0.5))

export const FAMILY_COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#f472b6', '#22d3ee', '#fb923c', '#84cc16', '#e879f9', '#2dd4bf', '#94a3b8']
export const LEVER_COLORS: Record<string, string> = { core: '#38bdf8', E1: '#34d399', E2: '#fbbf24', E3: '#a78bfa', E4: '#f472b6', E5: '#fb923c' }
