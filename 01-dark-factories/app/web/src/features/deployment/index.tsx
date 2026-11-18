import { lazy } from 'react'
import type { FeatureUi } from '../../lib/feature'

export const feature: FeatureUi = {
  id: 'DF-25',
  route: '/deployment',
  title: 'IaC & deployment',
  order: 80,
  element: lazy(() => import('./Deployment')),
}
