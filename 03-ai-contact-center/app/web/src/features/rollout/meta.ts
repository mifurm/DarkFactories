import { GitBranch } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-17'], route: '/rollout', title: 'Prompt & policy rollout', roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: 'LLMOps', order: 61, icon: GitBranch }, load: () => import('./RolloutPage') },
]
