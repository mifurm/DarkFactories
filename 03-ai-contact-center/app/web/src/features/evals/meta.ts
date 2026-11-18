import { FlaskConical } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-16', 'CC-11'], route: '/evals', title: N_('Evaluation harness'), roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: N_('LLMOps'), order: 60, icon: FlaskConical }, load: () => import('./EvalPage') },
]
