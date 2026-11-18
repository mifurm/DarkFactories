import { LayoutGrid, LayoutDashboard, Settings } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-24'], route: '/', title: N_('Overview & demo guide'), nav: { group: N_('Start'), order: 0, icon: LayoutDashboard }, load: () => import('./Home') },
  { features: ['CC-24'], route: '/features', title: N_('Feature map'), nav: { group: N_('Start'), order: 1, icon: LayoutGrid }, load: () => import('./FeatureMap') },
  { features: ['CC-24', 'CC-21'], route: '/settings', title: N_('Settings & demo data'), nav: { group: N_('Platform'), order: 90, icon: Settings }, load: () => import('./SettingsPage') },
]
