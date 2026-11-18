import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, post, useApi } from './lib/api'

export type PlantInfo = { id: string; name: string; location?: string; profile?: string }
type Ctx = { plantId: string; setPlantId: (id: string) => void; plants: PlantInfo[] }

const PlantCtx = createContext<Ctx>({ plantId: 'KAT-1', setPlantId: () => {}, plants: [] })
const KEY = 'nightshift.plant'

export function PlantProvider({ children }: { children: ReactNode }) {
  const meta = useApi<{ plants?: PlantInfo[] }>('/api/meta')
  const plants = useMemo(() => meta.data?.plants ?? [], [meta.data])
  const [plantId, setPlantIdState] = useState<string>(() => localStorage.getItem(KEY) ?? 'KAT-1')
  useEffect(() => {
    if (plants.length && !plants.some((p) => p.id === plantId)) setPlantIdState(plants[0].id)
  }, [plants, plantId])
  const setPlantId = (id: string) => {
    localStorage.setItem(KEY, id)
    setPlantIdState(id)
  }
  return <PlantCtx.Provider value={{ plantId, setPlantId, plants }}>{children}</PlantCtx.Provider>
}

export const usePlant = () => useContext(PlantCtx)

export const withPlant = (path: string, plantId: string) => `${path}${path.includes('?') ? '&' : '?'}plant=${encodeURIComponent(plantId)}`

/** useApi scoped to the plant selected in the shell. */
export function usePApi<T>(path: string | null, opts: { interval?: number } = {}) {
  const { plantId } = usePlant()
  return useApi<T>(path ? withPlant(path, plantId) : null, opts)
}

/** POST/PUT helpers scoped to the selected plant. */
export function usePlantCalls() {
  const { plantId } = usePlant()
  return useMemo(
    () => ({
      post: <T = any,>(path: string, body: unknown = {}) => post<T>(withPlant(path, plantId), body),
      put: <T = any,>(path: string, body: unknown = {}) => api<T>(withPlant(path, plantId), { method: 'PUT', body }),
      get: <T = any,>(path: string) => api<T>(withPlant(path, plantId)),
      plantId,
    }),
    [plantId],
  )
}
