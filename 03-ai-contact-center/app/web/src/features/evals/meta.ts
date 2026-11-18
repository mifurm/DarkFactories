import { FlaskConical } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-16', 'CC-11'], route: '/evals', title: 'Evaluation harness', roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: 'LLMOps', order: 60, icon: FlaskConical }, load: () => import('./EvalPage') },
]
