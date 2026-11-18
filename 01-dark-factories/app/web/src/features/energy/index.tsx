import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-09', '/energy', 'Energy & sustainability', 18, () => import('./Energy'))
