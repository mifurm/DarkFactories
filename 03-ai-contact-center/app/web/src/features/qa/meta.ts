import { ClipboardCheck } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-10'], route: '/qa', title: N_('QA workbench'), roles: ['qa', 'supervisor', 'auditor', 'admin'], nav: { group: N_('Quality & compliance'), order: 30, icon: ClipboardCheck }, load: () => import('./QaWorkbench') },
]
