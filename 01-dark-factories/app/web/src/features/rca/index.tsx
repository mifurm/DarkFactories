import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-18', '/rca', 'Root-cause analysis', 27, () => import('./RcaPage'))
