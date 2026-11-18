import { LayoutGrid, LayoutDashboard, Settings } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-24'], route: '/', title: 'Overview & demo guide', nav: { group: 'Start', order: 0, icon: LayoutDashboard }, load: () => import('./Home') },
  { features: ['CC-24'], route: '/features', title: 'Feature map', nav: { group: 'Start', order: 1, icon: LayoutGrid }, load: () => import('./FeatureMap') },
  { features: ['CC-24', 'CC-21'], route: '/settings', title: 'Settings & demo data', nav: { group: 'Platform', order: 90, icon: Settings }, load: () => import('./SettingsPage') },
]
