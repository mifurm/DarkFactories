import { describe, expect, it } from 'vitest'
import { fv, leverMode, nonZero, setAllLevers, setOverride, stackedRows, usd } from './logic'
import type { Switch } from './types'

const sw = (key: string, lever: string, up: number): Switch => ({ lever, key, group: 'g', label: lever, off: 0, on: up, scenario: { conservative: 0, base: 0, upside: up }, min: 0, max: 1 })
const SWITCHES = [sw('exp_vision_adoption', 'E1', 0.5), sw('exp_dp_adoption', 'E4', 1)]

describe('lever switches', () => {
  it('master toggle sets every adoption to its Upside value and back to zero', () => {
    const on = setAllLevers(SWITCHES, {}, 'base', true)
    expect(on).toEqual({ exp_vision_adoption: 0.5, exp_dp_adoption: 1 })
    expect(leverMode(SWITCHES, on, 'base')).toBe('on')
    expect(leverMode(SWITCHES, setAllLevers(SWITCHES, on, 'base', false), 'base')).toBe('off')
  })
  it('reports a custom mix and treats the Upside scenario as "on" without overrides', () => {
    expect(leverMode(SWITCHES, { exp_dp_adoption: 0.25 }, 'base')).toBe('custom')
    expect(leverMode(SWITCHES, {}, 'upside')).toBe('on')
    expect(setAllLevers(SWITCHES, {}, 'upside', true)).toEqual({})
  })
})

describe('overrides', () => {
  it('drops an override that equals the scenario value and keeps list overrides intact', () => {
    expect(setOverride({ a: 1 }, 'a', 0.3, 0.3)).toEqual({})
    expect(setOverride({}, 'benefit_ramp', [0.4, 0.8, 1], [0.35, 0.75, 0.95])).toEqual({ benefit_ramp: [0.4, 0.8, 1] })
    expect(setOverride({ benefit_ramp: [0.4, 0.8, 1] }, 'benefit_ramp', [0.35, 0.75, 0.95], [0.35, 0.75, 0.95])).toEqual({})
    expect(setOverride({ x: 5 }, 'x', undefined, 1)).toEqual({})
  })
})

describe('chart helpers', () => {
  it('stacks Year 1-3 plus run-rate and hides all-zero series', () => {
    const { keys, rows } = stackedRows({ core: [10, 20, 30], E1: [0, 0, 0], E2: [0, 0, 1] }, { core: 40, E1: 0, E2: 5 })
    expect(keys).toEqual(['core', 'E2'])
    expect(rows.map((r) => r.x)).toEqual(['Year 1', 'Year 2', 'Year 3', 'Run-rate'])
    expect(rows[3]).toEqual({ x: 'Run-rate', core: 40, E2: 5 })
    expect(nonZero({ a: [0, 0], b: [0, 2] })).toEqual(['b'])
  })
  it('formats dollars and driver values compactly', () => {
    expect(usd(1_279_328)).toBe('$1.28M')
    expect(usd(113_752)).toBe('$114k')
    expect(usd(-1_047_000)).toBe('−$1.05M')
    expect(usd(-0.2)).toBe('$0')
    expect(fv(0.12)).toBe('0.12')
    expect(fv([0.35, 0.75, 0.95])).toBe('0.35 · 0.75 · 0.95')
    expect(fv(null)).toBe('derived')
  })
})
