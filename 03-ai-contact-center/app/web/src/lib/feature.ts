import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'
import { N_ } from '../i18n/mark'
import type { Role } from './api'

export interface PageMeta {
  /** Feature ids (CC-xx) whose UI surface this page is. */
  features: string[]
  route: string
  /** English source text (marked with N_ in meta.ts); render with tr(). */
  title: string
  nav?: { group: string; order: number; icon: LucideIcon }
  roles?: Role[]
  bare?: boolean
  load: () => Promise<{ default: ComponentType }>
}

export const NAV_GROUPS = [N_('Start'), N_('Customer experience'), N_('Human collaboration'), N_('Quality & compliance'), N_('Insights'), N_('Operations'), N_('LLMOps'), N_('Platform')]

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
