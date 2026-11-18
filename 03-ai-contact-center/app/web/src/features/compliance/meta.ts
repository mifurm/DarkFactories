import { Gavel } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-11'], route: '/compliance', title: N_('Compliance & risk guard'), roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: N_('Quality & compliance'), order: 32, icon: Gavel }, load: () => import('./CompliancePage') },
]
