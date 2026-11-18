import { Wrench } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-04'], route: '/tools', title: 'Tools, policy & approvals', roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: 'Quality & compliance', order: 34, icon: Wrench }, load: () => import('./ToolsPage') },
]
