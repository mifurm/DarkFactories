import { MessageSquare } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-01', 'CC-19', 'CC-24'], route: '/widget', title: 'Customer widget (chat)', bare: true, nav: { group: 'Customer experience', order: 10, icon: MessageSquare }, load: () => import('./Widget') },
]
