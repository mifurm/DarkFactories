import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-03', '/twin', 'Digital twin & what-if', 12, () => import('./Twin'))
