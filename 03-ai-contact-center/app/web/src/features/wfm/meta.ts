import { CalendarClock } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-14'], route: '/wfm', title: 'Workforce forecast & staffing', roles: ['wfm', 'supervisor', 'auditor', 'admin'], nav: { group: 'Operations', order: 50, icon: CalendarClock }, load: () => import('./WfmPage') },
]
