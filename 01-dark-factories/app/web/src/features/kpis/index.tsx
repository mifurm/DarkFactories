import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-19', '/kpis', 'KPIs & impact', 28, () => import('./Kpis'))
