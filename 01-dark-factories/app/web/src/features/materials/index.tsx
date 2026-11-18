import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-08', '/materials', 'Materials & logistics', 17, () => import('./Materials'))
