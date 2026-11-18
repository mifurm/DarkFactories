import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-14', '/ledger', 'Decision ledger', 23, () => import('./Ledger'))
