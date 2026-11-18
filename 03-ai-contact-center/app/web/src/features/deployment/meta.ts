import { Rocket } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-23'], route: '/deployment', title: 'Deployment (IaC)', nav: { group: 'Platform', order: 70, icon: Rocket }, load: () => import('./DeploymentPage') },
]
