import { BrainCircuit } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-12'], route: '/voc', title: N_('Voice-of-customer insights'), roles: ['supervisor', 'qa', 'wfm', 'auditor', 'admin'], nav: { group: N_('Insights'), order: 41, icon: BrainCircuit }, load: () => import('./VocPage') },
]
