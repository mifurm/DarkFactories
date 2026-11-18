import { GitBranch } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-17'], route: '/rollout', title: N_('Prompt & policy rollout'), roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: N_('LLMOps'), order: 61, icon: GitBranch }, load: () => import('./RolloutPage') },
]
