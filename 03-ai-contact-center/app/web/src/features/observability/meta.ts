import { Activity } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-22', 'CC-13'], route: '/observability', title: 'Observability & FinOps', roles: ['supervisor', 'wfm', 'auditor', 'admin'], nav: { group: 'Operations', order: 52, icon: Activity }, load: () => import('./ObservabilityPage') },
]
