import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-15', '/readiness', 'Readiness assessment', 24, () => import('./Readiness'))
