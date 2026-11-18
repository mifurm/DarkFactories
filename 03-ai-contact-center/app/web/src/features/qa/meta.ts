import { ClipboardCheck } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-10'], route: '/qa', title: 'QA workbench', roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: 'Quality & compliance', order: 30, icon: ClipboardCheck }, load: () => import('./QaWorkbench') },
]
