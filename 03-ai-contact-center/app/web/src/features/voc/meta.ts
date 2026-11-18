import { BrainCircuit } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-12'], route: '/voc', title: 'Voice-of-customer insights', roles: ['supervisor', 'qa', 'wfm', 'auditor', 'admin'], nav: { group: 'Insights', order: 41, icon: BrainCircuit }, load: () => import('./VocPage') },
]
