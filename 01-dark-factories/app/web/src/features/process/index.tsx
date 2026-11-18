import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-11', '/process', 'Process optimisation', 20, () => import('./Process'))
