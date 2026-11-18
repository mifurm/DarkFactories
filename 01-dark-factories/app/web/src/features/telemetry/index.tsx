import { defineFeature } from '../../lib/define'

export const feature = defineFeature('DF-02', '/telemetry', 'Telemetry & UNS', 11, () => import('./Telemetry'))
