import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-04', '/swarm', 'Agent swarm', 13, () => import('./Swarm'))
