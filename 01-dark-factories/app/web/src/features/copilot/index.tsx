import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-16', '/copilot', 'Ask the Factory', 25, () => import('./Copilot'))
