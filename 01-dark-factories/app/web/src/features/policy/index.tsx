import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-12', '/policy', 'Autonomy dial & policy', 21, () => import('./PolicyPage'))
