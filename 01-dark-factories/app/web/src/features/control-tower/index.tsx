import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-20', '/', 'Control Tower', 1, () => import('./ControlTower'))
