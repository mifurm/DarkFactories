import { Route } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-06'], route: '/routing', title: N_('Routing & escalation'), roles: ['supervisor', 'wfm', 'qa', 'auditor', 'admin'], nav: { group: N_('Human collaboration'), order: 22, icon: Route }, load: () => import('./RoutingPage') },
]
