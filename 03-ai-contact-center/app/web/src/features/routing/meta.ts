import { Route } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-06'], route: '/routing', title: 'Routing & escalation', roles: ['supervisor', 'wfm', 'qa', 'auditor', 'admin'], nav: { group: 'Human collaboration', order: 22, icon: Route }, load: () => import('./RoutingPage') },
]
