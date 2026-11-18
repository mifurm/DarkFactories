import { TrendingUp } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-13'], route: '/metrics', title: 'CX metrics & ROI', roles: ['supervisor', 'qa', 'wfm', 'auditor', 'admin'], nav: { group: 'Insights', order: 40, icon: TrendingUp }, load: () => import('./MetricsPage') },
]
