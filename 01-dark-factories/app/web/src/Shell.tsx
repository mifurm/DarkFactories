import clsx from 'clsx'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Badge } from './components/ui'
import { ROLES, getRole, setRole, useApi, type Role } from './lib/api'
import { featureUis, type FeatureSpec } from './lib/feature'
import { usePlant } from './plant'

type Meta = { mode: string; version: string; build_id: string; ai_budget: { daily_usd: number; blocked: boolean } }
type Usage = { est_cost_usd: number; daily_budget_usd: number; budget_blocked: boolean }

const ROLE_LABEL: Record<Role, string> = { operator: 'Operator', engineer: 'Engineer', plant_manager: 'Plant Manager', auditor: 'Auditor', admin: 'Admin' }

export function Shell({ children }: { children: ReactNode }) {
  const features = useApi<FeatureSpec[]>('/api/features')
  const meta = useApi<Meta>('/api/meta', { interval: 30000 })
  const usage = useApi<Usage>('/api/usage', { interval: 20000 })
  const { plantId, setPlantId, plants } = usePlant()
  const [role, setRoleState] = useState<Role>(getRole())
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const h = () => setRoleState(getRole())
    window.addEventListener('nightshift-role', h)
    return () => window.removeEventListener('nightshift-role', h)
  }, [])

  const groups = useMemo(() => {
    const have = new Set(featureUis.map((f) => f.route))
    const g = new Map<string, FeatureSpec[]>()
    for (const f of features.data ?? []) {
      const k = f.epic
      g.set(k, [...(g.get(k) ?? []), f])
    }
    return { have, groups: [...g.entries()].sort(([a], [b]) => a.localeCompare(b)) }
  }, [features.data])

  const budget = usage.data
  return (
    <div className="flex h-full flex-col">
      <header className="z-20 flex items-center gap-3 border-b border-line bg-panel/95 px-4 py-2 backdrop-blur">
        <button className="rounded-md border border-line px-2 py-1 text-mute lg:hidden" aria-label="Toggle navigation" onClick={() => setOpen((o) => !o)}>☰</button>
        <NavLink to="/" className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Nightshift</div>
            <div className="text-[10px] uppercase tracking-[0.16em] text-mute">SwarmAI Dark Factory</div>
          </div>
        </NavLink>
        <div className="ml-4 hidden items-center gap-2 md:flex">
          <label className="text-[10px] uppercase tracking-wider text-mute" htmlFor="plant-sel">Plant</label>
          <select id="plant-sel" value={plantId} onChange={(e) => setPlantId(e.target.value)} className="rounded-md border border-line bg-panel2 px-2 py-1 text-sm">
            {(plants.length ? plants : [{ id: plantId, name: plantId }]).map((p) => (
              <option key={p.id} value={p.id}>{p.id} · {p.name}</option>
            ))}
          </select>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge tone="warn" title="No real factory, PLC or personal data is connected to this deployment">SYNTHETIC DATA · SIMULATED PLANT</Badge>
          {meta.data && <Badge tone={meta.data.mode === 'azure' ? 'ok' : 'mute'} title="Azure = Azure OpenAI + Cosmos DB + Blob over managed identity; offline = deterministic stubs">{meta.data.mode === 'azure' ? '● Azure live' : '○ offline'}</Badge>}
          {budget && <Badge tone={budget.budget_blocked ? 'bad' : 'info'} title="Estimated Azure OpenAI spend today vs the daily cap (fails closed)">AI ${budget.est_cost_usd.toFixed(3)} / ${budget.daily_budget_usd.toFixed(0)}</Badge>}
          <label className="sr-only" htmlFor="role-sel">Demo role</label>
          <select id="role-sel" value={role} onChange={(e) => setRole(e.target.value as Role)} className="rounded-md border border-line bg-panel2 px-2 py-1 text-sm" title="Demo role switcher (Entra sign-in in production)">
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Features" className={clsx('w-64 shrink-0 overflow-y-auto border-r border-line bg-panel/60 p-3', open ? 'fixed inset-y-12 left-0 z-10 block bg-panel' : 'hidden lg:block')}>
          <NavLink to="/" end onClick={() => setOpen(false)} className={({ isActive }) => clsx('mb-1 flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm font-medium', isActive ? 'bg-accent/15 text-accent' : 'text-ink hover:bg-white/5')}>
            <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-ok" /> Control Tower
          </NavLink>
          {groups.groups.map(([epic, list]) => (
            <div key={epic} className="mt-3">
              <div className="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-mute">{epic}</div>
              {list.filter((f) => f.ui_route !== '/').map((f) => {
                const ready = groups.have.has(f.ui_route)
                return ready ? (
                  <NavLink key={f.id} to={f.ui_route} onClick={() => setOpen(false)} className={({ isActive }) => clsx('flex items-center justify-between gap-2 rounded-lg px-2.5 py-1 text-[13px]', isActive ? 'bg-accent/15 text-accent' : 'text-ink/90 hover:bg-white/5')}>
                    <span className="truncate">{f.name}</span>
                    <span className="tabnum shrink-0 text-[10px] text-mute">{f.id.replace('DF-', '')}</span>
                  </NavLink>
                ) : (
                  <div key={f.id} className="flex items-center justify-between gap-2 px-2.5 py-1 text-[13px] text-mute/60" title="UI not shipped yet">
                    <span className="truncate">{f.name}</span>
                    <span className="text-[10px]">soon</span>
                  </div>
                )
              })}
            </div>
          ))}
          <div className="mt-3 border-t border-line pt-3">
            <NavLink to="/features" className={({ isActive }) => clsx('flex items-center rounded-lg px-2.5 py-1 text-[13px]', isActive ? 'bg-accent/15 text-accent' : 'text-ink/90 hover:bg-white/5')}>Feature Map</NavLink>
            <a href="/docs" className="flex items-center rounded-lg px-2.5 py-1 text-[13px] text-ink/90 hover:bg-white/5">API docs (OpenAPI)</a>
          </div>
        </nav>
        <main className="scan min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <footer className="flex items-center justify-between gap-3 border-t border-line bg-panel px-4 py-1 text-[11px] text-mute">
        <span>Synthetic data / simulated environment · Contoso Precision Components is fictional · nothing here controls a real machine.</span>
        <span className="tabnum">{meta.data ? `v${meta.data.version} · build ${meta.data.build_id}` : ''}</span>
      </footer>
    </div>
  )
}
