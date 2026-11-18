import { Lock } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-21'], route: '/security', title: N_('Security & RBAC'), roles: ['auditor', 'supervisor', 'admin'], nav: { group: N_('Platform'), order: 80, icon: Lock }, load: () => import('./SecurityPage') },
]
