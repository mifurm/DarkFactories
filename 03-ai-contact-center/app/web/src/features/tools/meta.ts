import { Wrench } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-04'], route: '/tools', title: N_('Tools, policy & approvals'), roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: N_('Quality & compliance'), order: 34, icon: Wrench }, load: () => import('./ToolsPage') },
]
