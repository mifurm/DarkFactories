import { MessageSquare } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-01', 'CC-19', 'CC-24'], route: '/widget', title: N_('Customer widget (chat)'), bare: true, nav: { group: N_('Customer experience'), order: 10, icon: MessageSquare }, load: () => import('./Widget') },
]
