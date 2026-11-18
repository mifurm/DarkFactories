import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-07', '/planner', 'Planner / scheduler', 16, () => import('./Planner'))
