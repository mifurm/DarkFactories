import { Megaphone } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-18'], route: '/outbound', title: N_('Proactive outreach'), roles: ['supervisor', 'wfm', 'auditor', 'admin'], nav: { group: N_('Operations'), order: 51, icon: Megaphone }, load: () => import('./OutboundPage') },
]
