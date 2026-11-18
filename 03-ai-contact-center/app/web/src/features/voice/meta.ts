import { PhoneCall } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-02', 'CC-19'], route: '/call', title: N_('Call us (voice)'), bare: true, nav: { group: N_('Customer experience'), order: 11, icon: PhoneCall }, load: () => import('./CallPage') },
]
