import { lazy, type ComponentType } from 'react'
import type { FeatureUi } from './feature'

// Kept separate from feature.ts: feature.ts eagerly imports every feature index module, and those import this helper.
export const defineFeature = (id: string, route: string, title: string, order: number, load: () => Promise<{ default: ComponentType }>): FeatureUi => ({ id, route, title, order, element: lazy(load) })
