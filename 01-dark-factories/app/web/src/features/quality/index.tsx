import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-06', '/quality', 'Quality & vision', 15, () => import('./Quality'))
