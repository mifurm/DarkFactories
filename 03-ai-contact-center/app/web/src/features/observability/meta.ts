import { Activity } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-22', 'CC-13'], route: '/observability', title: N_('Observability & FinOps'), roles: ['supervisor', 'wfm', 'auditor', 'admin'], nav: { group: N_('Operations'), order: 52, icon: Activity }, load: () => import('./ObservabilityPage') },
]
