import { Lock } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-21'], route: '/security', title: 'Security & RBAC', roles: ['auditor', 'supervisor', 'admin'], nav: { group: 'Platform', order: 80, icon: Lock }, load: () => import('./SecurityPage') },
]
