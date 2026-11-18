import type { ComponentType } from 'react'

export type FeatureUi = {
  id: string
  route: string
  title: string
  element: ComponentType
  order?: number
}

export type FeatureSpec = {
  id: string
  name: string
  epic: string
  priority: string
  status: string
  ui_route: string
  api_prefix: string
  summary: string
  depth: string
  tags: string[]
}

/** Every folder under src/features/<name>/index.tsx self-registers a page; the shell builds routes and navigation from them. */
const mods = import.meta.glob<{ feature: FeatureUi }>('../features/*/index.tsx', { eager: true })
export const featureUis: FeatureUi[] = Object.values(mods)
  .map((m) => m.feature)
  .filter(Boolean)
  .sort((a, b) => (a.order ?? 100) - (b.order ?? 100) || a.route.localeCompare(b.route))

export const fmt = {
  n: (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(v) ? '-' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })),
  pct: (v: number | null | undefined, d = 1) => (v == null || Number.isNaN(v) ? '-' : `${(v * 100).toFixed(d)}%`),
  eur: (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(v) ? '-' : `€${v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`),
  dur: (min: number | null | undefined) => {
    if (min == null || Number.isNaN(min)) return '-'
    const m = Math.round(min)
    if (m < 90) return `${m} min`
    const h = m / 60
    return h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} d`
  },
  time: (iso: string | null | undefined) => (iso ? iso.replace('T', ' ').slice(0, 16) : '-'),
  clock: (iso: string | null | undefined) => (iso ? iso.slice(11, 16) : '--:--'),
}
