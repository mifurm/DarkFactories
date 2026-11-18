import { PhoneCall } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-02', 'CC-19'], route: '/call', title: 'Call us (voice)', bare: true, nav: { group: 'Customer experience', order: 11, icon: PhoneCall }, load: () => import('./CallPage') },
]
