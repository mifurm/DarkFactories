import { Languages } from 'lucide-react'
import { N_ } from '../../i18n/mark'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-19'], route: '/i18n', title: N_('Multilingual'), roles: ['agent', 'supervisor', 'qa', 'admin'], nav: { group: N_('Human collaboration'), order: 24, icon: Languages }, load: () => import('./I18nPage') },
]
