import { Users } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-15', 'CC-06'], route: '/supervisor', title: N_('Supervisor console'), roles: ['supervisor', 'admin'], nav: { group: N_('Human collaboration'), order: 21, icon: Users }, load: () => import('./Supervisor') },
]
