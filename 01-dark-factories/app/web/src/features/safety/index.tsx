import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-10', '/safety', 'Safety & cybersecurity', 19, () => import('./Safety'))
