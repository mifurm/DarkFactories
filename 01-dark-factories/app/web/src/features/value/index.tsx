import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-21', '/value', 'Value realization', 29, () => import('./Value'))
