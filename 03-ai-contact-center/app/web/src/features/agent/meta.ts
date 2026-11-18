import { Headphones } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-07', 'CC-08', 'CC-09', 'CC-19'], route: '/agent', title: 'Human-agent console', roles: ['agent', 'supervisor', 'admin'], nav: { group: 'Human collaboration', order: 20, icon: Headphones }, load: () => import('./AgentConsole') },
]
