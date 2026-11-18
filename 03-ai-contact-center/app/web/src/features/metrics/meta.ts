import { TrendingUp } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-13'], route: '/metrics', title: N_('CX metrics & ROI'), roles: ['supervisor', 'qa', 'wfm', 'auditor', 'admin'], nav: { group: N_('Insights'), order: 40, icon: TrendingUp }, load: () => import('./MetricsPage') },
]
