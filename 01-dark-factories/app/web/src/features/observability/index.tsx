import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-24', '/observability', 'Observability & FinOps', 32, () => import('./Observability'))
