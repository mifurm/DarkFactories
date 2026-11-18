import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'
import type { Role } from './api'

export interface PageMeta {
  /** Feature ids (CC-xx) whose UI surface this page is. */
  features: string[]
  route: string
  title: string
  nav?: { group: string; order: number; icon: LucideIcon }
  roles?: Role[]
  bare?: boolean
  load: () => Promise<{ default: ComponentType }>
}

export const NAV_GROUPS = ['Start', 'Customer experience', 'Human collaboration', 'Quality & compliance', 'Insights', 'Operations', 'LLMOps', 'Platform']

type Mod = { pages?: PageMeta[] }

/** Auto-discovery: every src/features/<feature>/meta.ts that exports `pages` is part of the app. */
const modules = import.meta.glob<Mod>('../features/*/meta.ts', { eager: true })

export const PAGES: PageMeta[] = Object.values(modules)
  .flatMap((m) => m.pages ?? [])
  .sort((a, b) => (a.nav?.order ?? 999) - (b.nav?.order ?? 999))

export const pageForRoute = (route: string) => PAGES.find((p) => p.route === route)
export const uiRoutesByFeature = (): Record<string, PageMeta[]> => {
  const map: Record<string, PageMeta[]> = {}
  for (const p of PAGES) for (const f of p.features) (map[f] ??= []).push(p)
  return map
}
