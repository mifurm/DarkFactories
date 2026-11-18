import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-05', '/maintenance', 'Predictive maintenance', 14, () => import('./Maintenance'))
