import { lazy } from 'react'
import type { FeatureUi } from '../../lib/feature'

export const feature: FeatureUi = {
  id: 'platform-feature-map',
  route: '/features',
  title: 'Feature Map',
  order: 90,
  element: lazy(() => import('./FeatureMap')),
}
