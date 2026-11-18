import { BookOpen } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-03'], route: '/kb', title: 'Knowledge base admin', roles: ['agent', 'supervisor', 'qa', 'auditor', 'admin'], nav: { group: 'Quality & compliance', order: 31, icon: BookOpen }, load: () => import('./KbAdmin') },
]
