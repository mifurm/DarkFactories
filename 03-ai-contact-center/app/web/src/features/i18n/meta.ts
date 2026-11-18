import { Languages } from 'lucide-react'
import type { PageMeta } from '../../lib/feature'

export const pages: PageMeta[] = [
  { features: ['CC-19'], route: '/i18n', title: 'Multilingual', roles: ['agent', 'supervisor', 'qa', 'admin'], nav: { group: 'Human collaboration', order: 24, icon: Languages }, load: () => import('./I18nPage') },
]
