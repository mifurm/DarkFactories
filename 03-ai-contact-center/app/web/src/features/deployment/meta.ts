import { Rocket } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-23'], route: '/deployment', title: N_('Deployment (IaC)'), nav: { group: N_('Platform'), order: 70, icon: Rocket }, load: () => import('./DeploymentPage') },
]
