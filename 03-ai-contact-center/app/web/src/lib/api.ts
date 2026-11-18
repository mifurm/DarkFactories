import { useCallback, useEffect, useRef, useState } from 'react'
import { getLang, translate, translateKeyed } from '../i18n/core'

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

/** Human-readable error text: the server's (already localised) message, else a code-keyed UI text, else a generic one. */
function errorText(status: number, body: unknown): string {
  const lang = getLang()
  const obj = (typeof body === 'object' && body ? (body as Record<string, unknown>) : {}) as Record<string, unknown>
  const detail = obj.detail
  const inner = typeof detail === 'object' && detail && !Array.isArray(detail) ? (detail as Record<string, unknown>) : obj
  const code = typeof inner.error === 'string' ? inner.error : null
  if (typeof inner.message === 'string' && inner.message) return inner.message
  if (typeof detail === 'string' && detail) return detail
  if (code) {
    const known = translateKeyed(lang, 'error', code, '')
    if (known) return known
  }
  if (Array.isArray(detail)) {
    const fields = detail.map((d) => (Array.isArray((d as { loc?: unknown[] }).loc) ? String((d as { loc: unknown[] }).loc.slice(1).join('.')) : '')).filter(Boolean)
    return translate(lang, 'Invalid request ({fields})', { fields: [...new Set(fields)].join(', ') || '?' })
  }
  return translate(lang, 'Request failed (HTTP {status})', { status })
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown) {
    super(errorText(status, body))
    this.status = status
    this.body = body
  }
}

/** The text to show for any caught error (never raw JSON). */
export function describeError(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; signal?: AbortSignal; headers?: Record<string, string>; role?: Role } = {},
): Promise<T> {
  const lang = getLang()
  const headers: Record<string, string> = {
    'X-Demo-Role': opts.role ?? getRole(),
    'X-UI-Lang': lang,
    'Accept-Language': lang === 'pl' ? 'pl-PL,pl;q=0.9' : 'en-US,en;q=0.9',
    ...(opts.headers ?? {}),
  }
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
    // a role or language switch refetches everything so server-side text and permissions follow without a reload
    const onSwitch = () => reload()
    window.addEventListener('concierge:role', onSwitch)
    window.addEventListener('concierge:lang', onSwitch)
    return () => {
      window.removeEventListener('concierge:role', onSwitch)
      window.removeEventListener('concierge:lang', onSwitch)
    }
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

/** Adds ?lang= to a URL that cannot carry headers (WebSocket, downloads opened by a link). */
export function withLang(path: string, lang: string = getLang()): string {
  return `${path}${path.includes('?') ? '&' : '?'}lang=${encodeURIComponent(lang)}`
}

export function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${withLang(path)}`
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
