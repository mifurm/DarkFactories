import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-22', '/fleet', 'Fleet', 30, () => import('./Fleet'))
