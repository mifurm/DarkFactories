import { Gavel } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-11'], route: '/compliance', title: 'Compliance & risk guard', roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: 'Quality & compliance', order: 32, icon: Gavel }, load: () => import('./CompliancePage') },
]
