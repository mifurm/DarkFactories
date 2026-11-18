import { useCallback, useEffect, useRef, useState } from 'react'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

const ROLE_KEY = 'nightshift.role'
export const ROLES = ['operator', 'engineer', 'plant_manager', 'auditor', 'admin'] as const
export type Role = (typeof ROLES)[number]
export const getRole = (): Role => (localStorage.getItem(ROLE_KEY) as Role) || 'plant_manager'
export const setRole = (r: Role) => {
  localStorage.setItem(ROLE_KEY, r)
  window.dispatchEvent(new Event('nightshift-role'))
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Demo-Role': getRole() }
  let body: string | undefined
  if (init.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.body)
  }
  const res = await fetch(path, { method: init.method ?? (body ? 'POST' : 'GET'), headers, body, signal: init.signal })
  const text = await res.text()
  let data: unknown = text
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    /* keep text */
  }
  if (!res.ok) {
    const d = (data as { detail?: unknown })?.detail ?? data
    throw new ApiError(res.status, d)
  }
  return data as T
}

export const post = <T = unknown>(path: string, body: unknown = {}) => api<T>(path, { method: 'POST', body })

export function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (typeof e.detail === 'string') return e.detail
    return JSON.stringify(e.detail)
  }
  return e instanceof Error ? e.message : String(e)
}

export function useApi<T>(path: string | null, opts: { interval?: number } = {}) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(!!path)
  const seq = useRef(0)
  const load = useCallback(async () => {
    if (!path) return
    const id = ++seq.current
    try {
      const d = await api<T>(path)
      if (id === seq.current) {
        setData(d)
        setError(null)
      }
    } catch (e) {
      if (id === seq.current) setError(errText(e))
    } finally {
      if (id === seq.current) setLoading(false)
    }
  }, [path])
  useEffect(() => {
    setLoading(!!path)
    void load()
    if (!opts.interval || !path) return
    const t = setInterval(() => void load(), opts.interval)
    return () => clearInterval(t)
  }, [load, opts.interval, path])
  return { data, error, loading, reload: load, setData }
}

export function useEventSource(url: string | null, handlers: Record<string, (data: any) => void>) {
  const ref = useRef(handlers)
  ref.current = handlers
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    if (!url) return
    const es = new EventSource(url)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    const names = Object.keys(ref.current)
    const fns = names.map((n) => {
      const fn = (ev: MessageEvent) => {
        try {
          ref.current[n]?.(JSON.parse(ev.data))
        } catch {
          /* ignore malformed frame */
        }
      }
      es.addEventListener(n, fn as EventListener)
      return fn
    })
    return () => {
      names.forEach((n, i) => es.removeEventListener(n, fns[i] as EventListener))
      es.close()
      setConnected(false)
    }
  }, [url])
  return connected
}

/** POST + stream Server-Sent Events frames (EventSource cannot POST). */
export async function postSSE(path: string, body: unknown, onEvent: (event: string, data: any) => void, signal?: AbortSignal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Demo-Role': getRole() },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json())?.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i)
      buf = buf.slice(i + 2)
      let ev = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) {
        try {
          onEvent(ev, JSON.parse(data))
        } catch {
          /* ignore */
        }
      }
    }
  }
}
