import { KeyRound } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-05'], route: '/identity', title: N_('Identity & consent'), nav: { group: N_('Quality & compliance'), order: 33, icon: KeyRound }, load: () => import('./IdentityPage') },
  { features: ['CC-05'], route: '/pay/:token', title: N_('Secure payment'), bare: true, load: () => import('./IdentityPage').then((m) => ({ default: m.PayPage })) },
]
