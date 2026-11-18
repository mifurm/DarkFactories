import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-13', '/inbox', 'Approvals inbox', 22, () => import('./Inbox'))
