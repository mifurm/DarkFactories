import { UserRound } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-20'], route: '/customers', title: 'Customer 360 & CRM', roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: 'Human collaboration', order: 23, icon: UserRound }, load: () => import('./CustomersPage') },
]
