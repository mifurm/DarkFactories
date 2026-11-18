import { describe, expect, it } from 'vitest'
import { fmt } from './feature'

describe('fmt', () => {
  it('formats numbers, percentages, EUR and durations', () => {
    expect(fmt.n(1234.5, 1)).toBe('1,234.5')
    expect(fmt.n(null)).toBe('-')
    expect(fmt.pct(0.8567, 1)).toBe('85.7%')
    expect(fmt.eur(1500)).toBe('€1,500')
    expect(fmt.dur(45)).toBe('45 min')
    expect(fmt.dur(150)).toBe('2.5 h')
    expect(fmt.dur(60 * 72)).toBe('3.0 d')
    expect(fmt.dur(undefined)).toBe('-')
  })
})
