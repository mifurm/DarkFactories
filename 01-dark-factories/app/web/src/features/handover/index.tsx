import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-17', '/handover', 'Shift handover report', 26, () => import('./Handover'))
