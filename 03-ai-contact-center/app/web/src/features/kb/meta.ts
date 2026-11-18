import { BookOpen } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-03'], route: '/kb', title: N_('Knowledge base admin'), roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: N_('Quality & compliance'), order: 31, icon: BookOpen }, load: () => import('./KbAdmin') },
]
