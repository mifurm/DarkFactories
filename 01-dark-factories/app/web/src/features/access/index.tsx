import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-23', '/access', 'Access control', 31, () => import('./Access'))
