import { Megaphone } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-18'], route: '/outbound', title: 'Proactive outreach', roles: ['supervisor', 'wfm', 'auditor', 'admin'], nav: { group: 'Operations', order: 51, icon: Megaphone }, load: () => import('./OutboundPage') },
]
