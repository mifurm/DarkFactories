import { UserRound } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-20'], route: '/customers', title: N_('Customer 360 & CRM'), roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: N_('Human collaboration'), order: 23, icon: UserRound }, load: () => import('./CustomersPage') },
]
