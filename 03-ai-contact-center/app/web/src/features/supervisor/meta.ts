import { Users } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-15', 'CC-06'], route: '/supervisor', title: 'Supervisor console', roles: ['supervisor', 'admin'], nav: { group: 'Human collaboration', order: 21, icon: Users }, load: () => import('./Supervisor') },
]
