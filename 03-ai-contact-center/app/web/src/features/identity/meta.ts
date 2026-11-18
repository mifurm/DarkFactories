import { KeyRound } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-05'], route: '/identity', title: 'Identity & consent', nav: { group: 'Quality & compliance', order: 33, icon: KeyRound }, load: () => import('./IdentityPage') },
  { features: ['CC-05'], route: '/pay/:token', title: 'Secure payment', bare: true, load: () => import('./IdentityPage').then((m) => ({ default: m.PayPage })) },
]
