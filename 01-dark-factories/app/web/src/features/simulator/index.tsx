import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-01', '/simulator', 'Factory simulator', 10, () => import('./Simulator'))
