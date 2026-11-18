import { Menu, ShieldAlert, X } from 'lucide-react'
import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { ROLES, type Role, getRole, setRole, useApi } from './lib/api'
import { NAV_GROUPS, PAGES, type PageMeta } from './lib/feature'
import { Badge, Spinner, cx } from './lib/ui'

interface Meta {
  version: string
  build_id: string
  mode: string
  region: string
  llm: string
  repository: string
}
interface Usage {
  spent_usd: number
  budget_usd: number
  status: string
}

const lazyCache = new Map<string, ReturnType<typeof lazy>>()
const lazyPage = (p: PageMeta) => {
  if (!lazyCache.has(p.route)) lazyCache.set(p.route, lazy(p.load))
  return lazyCache.get(p.route)!
}

function Forbidden({ role, page }: { role: Role; page: PageMeta }) {
  return (
    <div className="mx-auto mt-16 max-w-lg rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
      <ShieldAlert className="mx-auto mb-2 text-amber-600" aria-hidden />
      <h1 className="text-lg font-semibold text-slate-900">{page.title} is not available to the “{role}” role</h1>
      <p className="mt-1 text-sm text-slate-600">Use the role switcher in the header to act as {page.roles?.join(', ')} (demo role switcher; API enforcement is covered by CC-21).</p>
    </div>
  )
}

function Shell() {
  const [role, setRoleState] = useState<Role>(getRole())
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const meta = useApi<Meta>('/api/meta')
  const usage = useApi<Usage>('/api/usage', { refreshMs: 20000 })

  useEffect(() => {
    const on = (e: Event) => setRoleState((e as CustomEvent<Role>).detail)
    window.addEventListener('concierge:role', on)
    return () => window.removeEventListener('concierge:role', on)
  }, [])
  useEffect(() => {
    setOpen(false)
  }, [loc.pathname])

  const visible = (p: PageMeta) => !p.roles || role === 'admin' || p.roles.includes(role)
  const groups = useMemo(
    () => NAV_GROUPS.map((g) => ({ g, items: PAGES.filter((p) => p.nav?.group === g && visible(p)) })).filter((x) => x.items.length),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [role],
  )
  const bare = PAGES.find((p) => p.route === loc.pathname)?.bare || loc.pathname.startsWith('/pay/')
  if (bare) return <PageRoutes role={role} />

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col overflow-y-auto bg-[var(--color-ink)] px-3 py-4 text-slate-300 scroll-thin">
      <div className="mb-5 flex items-center gap-2.5 px-2">
        <img src="/favicon.svg" alt="" className="h-9 w-9" />
        <div>
          <div className="text-base font-semibold leading-tight text-white">Concierge</div>
          <div className="text-[11px] leading-tight text-slate-300">AI Contact Center · Contoso Home</div>
        </div>
      </div>
      {groups.map(({ g, items }) => (
        <div key={g} className="mb-3">
          <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-300">{g}</div>
          {items.map((p) => {
            const Icon = p.nav!.icon
            return (
              <NavLink
                key={p.route}
                to={p.route}
                end={p.route === '/'}
                className={({ isActive }) => cx('flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition', isActive ? 'bg-white/10 font-medium text-white' : 'hover:bg-white/5 hover:text-white')}
              >
                <Icon size={16} aria-hidden /> {p.title}
              </NavLink>
            )
          })}
        </div>
      ))}
    </nav>
  )

  return (
    <div className="flex h-full">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 flex lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="w-64">{sidebar}</div>
          <button className="flex-1 bg-black/40" aria-label="Close navigation" onClick={() => setOpen(false)} />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
          <button className="rounded-lg p-1.5 hover:bg-slate-100 lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
          <Badge tone="amber" title="Contoso Home Retail is fictional; all data is synthetic; PSTN telephony and SMS/e-mail delivery are simulated.">
            Synthetic data · simulated environment
          </Badge>
          <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-slate-600">
            {meta.data && (
              <Badge tone={meta.data.mode === 'azure' ? 'green' : 'slate'} title={`LLM: ${meta.data.llm} · store: ${meta.data.repository} · region ${meta.data.region}`}>
                mode: {meta.data.mode}
              </Badge>
            )}
            {usage.data && (
              <span title="Daily AI budget (fails closed when exhausted)" className="flex items-center gap-1.5">
                AI spend today{' '}
                <b className="tabular-nums text-slate-900">
                  ${usage.data.spent_usd.toFixed(2)} / ${usage.data.budget_usd.toFixed(0)}
                </b>
                {usage.data.status !== 'ok' && <Badge tone={usage.data.status === 'exhausted' ? 'red' : 'amber'}>{usage.data.status}</Badge>}
              </span>
            )}
            <label className="flex items-center gap-1.5">
              <span className="text-slate-500">Acting as</span>
              <select
                aria-label="Demo role"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-800"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
            <PageRoutes role={role} />
          </div>
        </main>
        <footer className="flex flex-wrap justify-between gap-2 border-t border-slate-200 bg-white px-4 py-1.5 text-[11px] text-slate-500">
          <span>
            Synthetic data only — “Contoso Home Retail” is fictional. PSTN telephony and SMS/e-mail/WhatsApp delivery are simulated; Azure OpenAI, Speech, Language, Content Safety and Cosmos DB are real in azure mode.
          </span>
          <span>
            v{meta.data?.version ?? '…'} · build {meta.data?.build_id ?? '…'}
          </span>
        </footer>
      </div>
    </div>
  )
}

function PageRoutes({ role }: { role: Role }) {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        {PAGES.map((p) => {
          const C = lazyPage(p)
          const allowed = !p.roles || role === 'admin' || p.roles.includes(role)
          return <Route key={p.route} path={p.route} element={allowed ? <C /> : <Forbidden role={role} page={p} />} />
        })}
        <Route path="*" element={<div className="p-10 text-center text-slate-500">Page not found.</div>} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}
