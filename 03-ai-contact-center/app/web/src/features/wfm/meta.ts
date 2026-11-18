import { CalendarClock } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-14'], route: '/wfm', title: N_('Workforce forecast & staffing'), roles: ['wfm', 'supervisor', 'auditor', 'admin'], nav: { group: N_('Operations'), order: 50, icon: CalendarClock }, load: () => import('./WfmPage') },
]
