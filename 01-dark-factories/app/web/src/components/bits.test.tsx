import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Md, StateBadge, hhmm, outcomeTone } from './bits'

describe('Md', () => {
  it('renders headings, bullets, bold text and pipe tables', () => {
    render(<Md text={'# Shift report\n- **3** failures avoided\n\n| KPI | Value |\n|---|---|\n| OEE | 85 % |'} />)
    expect(screen.getByText('Shift report')).toBeTruthy()
    expect(screen.getByText('3').tagName).toBe('B')
    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getByText('OEE')).toBeTruthy()
  })
  it('never injects HTML from model output', () => {
    const { container } = render(<Md text={'<img src=x onerror=alert(1)> <script>alert(1)</script>'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
  })
})

describe('helpers', () => {
  it('maps outcomes to tones and renders asset states', () => {
    expect(outcomeTone('executed')).toBe('ok')
    expect(outcomeTone('vetoed')).toBe('bad')
    expect(outcomeTone('pending_approval')).toBe('warn')
    render(<StateBadge state="DOWN" />)
    expect(screen.getByText('DOWN')).toBeTruthy()
    expect(hhmm(135)).toBe('02:15')
  })
})
