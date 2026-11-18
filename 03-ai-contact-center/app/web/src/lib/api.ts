import { useCallback, useEffect, useRef, useState } from 'react'

export const ROLE_KEY = 'concierge.role'
export const ROLES = ['customer', 'agent', 'supervisor', 'qa', 'wfm', 'admin', 'auditor'] as const
export type Role = (typeof ROLES)[number]

export function getRole(): Role {
  const r = (typeof localStorage !== 'undefined' && localStorage.getItem(ROLE_KEY)) as Role | null
  return r && (ROLES as readonly string[]).includes(r) ? r : 'admin'
}
export function setRole(role: Role) {
  localStorage.setItem(ROLE_KEY, role)
  window.dispatchEvent(new CustomEvent('concierge:role', { detail: role }))
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown) {
    const msg =
      typeof body === 'object' && body && 'message' in body
        ? String((body as { message: unknown }).message)
        : typeof body === 'object' && body && 'detail' in body
          ? JSON.stringify((body as { detail: unknown }).detail)
          : `HTTP ${status}`
    super(msg)
    this.status = status
    this.body = body
  }
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; signal?: AbortSignal; headers?: Record<string, string>; role?: Role } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'X-Demo-Role': opts.role ?? getRole(), ...(opts.headers ?? {}) }
  let body: BodyInit | undefined
  if (opts.body instanceof FormData) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await fetch(path, { method: opts.method ?? (opts.body !== undefined ? 'POST' : 'GET'), headers, body, signal: opts.signal })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { message: text.slice(0, 300) }
  }
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export function useApi<T>(path: string | null, opts: { refreshMs?: number; deps?: unknown[] } = {}) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState<boolean>(!!path)
  const seq = useRef(0)
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  const depKey = JSON.stringify(opts.deps ?? [])

  useEffect(() => {
    const onRole = () => reload()
    window.addEventListener('concierge:role', onRole)
    return () => window.removeEventListener('concierge:role', onRole)
  }, [reload])

  useEffect(() => {
    if (!path) return
    const id = ++seq.current
    const ctl = new AbortController()
    const run = async (first: boolean) => {
      if (first) setLoading(true)
      try {
        const d = await api<T>(path, { signal: ctl.signal })
        if (id === seq.current) {
          setData(d)
          setError(null)
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError' && id === seq.current) setError(e as ApiError)
      } finally {
        if (id === seq.current) setLoading(false)
      }
    }
    void run(true)
    const timer = opts.refreshMs ? setInterval(() => void run(false), opts.refreshMs) : undefined
    return () => {
      ctl.abort()
      if (timer) clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, opts.refreshMs, depKey])

  return { data, error, loading, reload, setData }
}

export function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

/** Subscribe to the server event bus (/ws/events) with auto-reconnect. */
export function useEventStream(topics: string[], onEvent: (ev: Record<string, unknown>) => void) {
  const handler = useRef(onEvent)
  handler.current = onEvent
  const key = topics.join(',')
  useEffect(() => {
    if (!key) return
    let ws: WebSocket | null = null
    let closed = false
    let retry = 0
    const connect = () => {
      ws = new WebSocket(wsUrl(`/ws/events?topics=${encodeURIComponent(key)}&role=${getRole()}`))
      ws.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data))
        } catch {
          /* ignore malformed */
        }
      }
      ws.onopen = () => {
        retry = 0
      }
      ws.onclose = () => {
        if (!closed) setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000))
      }
    }
    connect()
    return () => {
      closed = true
      ws?.close()
    }
  }, [key])
}

export const fmt = {
  usd: (n: number | null | undefined, d = 2) => (n == null ? '—' : `$${n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`),
  eur: (n: number | null | undefined, d = 2) => (n == null ? '—' : `€${n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`),
  pct: (n: number | null | undefined, d = 1) => (n == null ? '—' : `${(n * 100).toFixed(d)}%`),
  num: (n: number | null | undefined, d = 0) => (n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: d })),
  ms: (n: number | null | undefined) => (n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`),
  time: (ts: number | null | undefined) => (ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'),
  dt: (ts: number | null | undefined) => (ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—'),
  dur: (s: number | null | undefined) => {
    if (s == null) return '—'
    const m = Math.floor(s / 60)
    return m > 0 ? `${m}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`
  },
}
