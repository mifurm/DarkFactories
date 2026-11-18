import { GitBranch, Rocket, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, fmt, useApi } from '../../lib/api'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, Field, PageHeader, Spinner, Stat, Tabs, inputCls } from '../../lib/ui'

interface Cfg { id: string; name: string; version: number; status: string; canary_pct: number; created_at: number; created_by: string; parent: string | null; notes: string; gate: { passed: boolean; reasons: string[] } | null }
interface Ab { versions: { config: string; conversations: number; containment: number | null; escalation_rate: number | null; qa_avg: number | null; cost_per_conversation?: number | null; eval?: { pass_rate: number } | null; eval_pass_rate?: number | null }[]; canary: { config: string | null; pct: number }; active: string }
interface Diff { a: string; b: string; prompts: Record<string, string[]>; policy: Record<string, { from: unknown; to: unknown }>; tools: Record<string, { added: string[]; removed: string[] }>; identical: boolean }
interface Log { id: string; ts: number; action: string; config: string; actor: string; detail: Record<string, unknown> }
interface Full { id: string; prompts: Record<string, string>; policy: Record<string, unknown> }

const TONE: Record<string, string> = { active: 'green', canary: 'violet', candidate: 'blue', draft: 'slate', retired: 'slate' }

export default function RolloutPage() {
  const [tab, setTab] = useState('versions')
  const cfgs = useApi<Cfg[]>('/api/rollout/configs', { refreshMs: 8000 })
  const ab = useApi<Ab>('/api/rollout/ab', { refreshMs: 8000 })
  const log = useApi<Log[]>('/api/rollout/log', { refreshMs: 8000 })
  const [sel, setSel] = useState<Cfg | null>(null)
  const [pct, setPct] = useState(20)
  const [msg, setMsg] = useState<{ tone: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg({ tone: 'green', text: ok }); cfgs.reload(); ab.reload(); log.reload() } catch (e) { setMsg({ tone: 'red', text: e instanceof ApiError ? JSON.stringify((e.body as any)?.detail ?? e.body) : String(e) }) } finally { setBusy(false) } // eslint-disable-line @typescript-eslint/no-explicit-any
  }
  const active = cfgs.data?.find((c) => c.status === 'active')
  return (
    <div>
      <PageHeader icon={GitBranch} title="Prompt, policy & knowledge management" subtitle="Versioned agent configurations: draft → eval gate → canary % → promote, A/B on live metrics, one-click rollback and a full audit trail."
        actions={<Button icon={Undo2} busy={busy} onClick={() => act(() => api('/api/rollout/rollback', { method: 'POST' }), 'Rolled back - new conversations use the previous version; in-flight ones finish on theirs.')}>Rollback</Button>} />
      {msg && <div role="status" className={`mb-3 rounded-xl px-3 py-2 text-sm ring-1 ${msg.tone === 'green' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-rose-50 text-rose-700 ring-rose-200'}`}>{msg.text}</div>}
      <div className="mb-4 grid grid-cols-3 gap-3"><Stat label="Active version" value={ab.data?.active ?? '…'} tone="green" /><Stat label="Canary" value={ab.data?.canary.config ? `${ab.data.canary.config} · ${ab.data.canary.pct}%` : 'none'} tone={ab.data?.canary.config ? 'violet' : undefined} /><Stat label="Versions" value={cfgs.data?.length ?? '…'} /></div>
      <Tabs tabs={[{ id: 'versions', label: 'Versions & promotion' }, { id: 'ab', label: 'A/B comparison' }, { id: 'diff', label: 'Diff' }, { id: 'log', label: 'Audit trail' }]} value={tab} onChange={setTab} />
      {tab === 'versions' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card title="Configurations" pad={false}>
            {cfgs.loading && !cfgs.data ? <Spinner /> : cfgs.error ? <ErrorBox error={cfgs.error} /> : <DataTable dense rows={cfgs.data ?? []} rowKey={(c) => c.id} selected={sel?.id} onRowClick={setSel} cols={[{ key: 'i', header: 'Version', render: (c) => <span className="font-mono text-xs">{c.id}</span> }, { key: 'n', header: 'Name', render: (c) => <span className="font-medium">{c.name}</span> }, { key: 's', header: 'Status', render: (c) => <Badge tone={TONE[c.status]}>{c.status}{c.status === 'canary' ? ` ${c.canary_pct}%` : ''}</Badge> }, { key: 'g', header: 'Eval gate', render: (c) => (c.gate ? <Badge tone={c.gate.passed ? 'green' : 'red'}>{c.gate.passed ? 'passed' : 'failed'}</Badge> : <span className="text-slate-300">—</span>) }, { key: 'c', header: 'By', render: (c) => <span className="text-xs text-slate-500">{c.created_by} · {fmt.dt(c.created_at)}</span> }]} />}
          </Card>
          <Card title={sel ? `Promote ${sel.id}` : 'Promotion workflow'} subtitle="draft → eval gate → canary → promote">
            {!sel ? <Empty>Select a version.</Empty> : (
              <div className="space-y-3 text-sm">
                <p className="text-slate-600">{sel.notes || '—'}</p>
                {sel.gate && !sel.gate.passed && <ul className="list-disc pl-4 text-xs text-rose-700">{sel.gate.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/gate?suite=gate`, { method: 'POST' }), 'Gate suite started - see the result in a moment.')}>1 · Run eval gate</Button>
                  <Button size="sm" busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/canary`, { body: { pct } }), `Canary ${pct}% started (deterministic hash of the conversation id).`)}>2 · Canary {pct}%</Button>
                  <Button size="sm" variant="primary" icon={Rocket} busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/promote`, { method: 'POST' }), `${sel.id} promoted to active.`)}>3 · Promote</Button>
                </div>
                <input type="range" min={5} max={100} step={5} value={pct} onChange={(e) => setPct(Number(e.target.value))} aria-label="Canary percentage" className="w-full accent-violet-600" />
                <p className="text-xs text-slate-500">Promotion is blocked unless the candidate has a passing eval gate. {active && `Active now: ${active.id}.`}</p>
              </div>
            )}
          </Card>
        </div>
      )}
      {tab === 'ab' && (
        <Card title="Live metrics by configuration version" subtitle="conversations split by the version they started on" pad={false}>
          <DataTable dense rows={ab.data?.versions ?? []} rowKey={(v) => v.config} empty="No conversations yet." cols={[{ key: 'c', header: 'Version', render: (v) => <span className="font-mono text-xs">{v.config}</span> }, { key: 'n', header: 'Conversations', align: 'right', render: (v) => v.conversations }, { key: 'k', header: 'Containment', align: 'right', render: (v) => (v.containment != null ? fmt.pct(v.containment, 0) : '—') }, { key: 'e', header: 'Escalation', align: 'right', render: (v) => (v.escalation_rate != null ? fmt.pct(v.escalation_rate, 0) : '—') }, { key: 'q', header: 'QA avg', align: 'right', render: (v) => v.qa_avg ?? '—' }, { key: 'p', header: 'Eval pass rate', align: 'right', render: (v) => (v.eval?.pass_rate != null ? fmt.pct(v.eval.pass_rate, 0) : v.eval_pass_rate != null ? fmt.pct(v.eval_pass_rate, 0) : '—') }]} />
        </Card>
      )}
      {tab === 'diff' && <DiffTab cfgs={cfgs.data ?? []} />}
      {tab === 'log' && (
        <Card title="Audit trail" subtitle="who changed what, when" pad={false}>
          <DataTable dense rows={log.data ?? []} rowKey={(l) => l.id} empty="No changes yet." cols={[{ key: 't', header: 'Time', render: (l) => fmt.dt(l.ts) }, { key: 'a', header: 'Action', render: (l) => <Badge tone="violet">{l.action}</Badge> }, { key: 'c', header: 'Config', render: (l) => <span className="font-mono text-xs">{l.config}</span> }, { key: 'u', header: 'Actor', render: (l) => l.actor }, { key: 'd', header: 'Detail', render: (l) => <span className="text-xs text-slate-500">{JSON.stringify(l.detail).slice(0, 90)}</span> }]} />
        </Card>
      )}
      <NewDraft cfgs={cfgs.data ?? []} onDone={() => { cfgs.reload(); log.reload() }} />
    </div>
  )
}

function DiffTab({ cfgs }: { cfgs: Cfg[] }) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [d, setD] = useState<Diff | null>(null)
  const run = async () => setD(await api<Diff>(`/api/rollout/diff?a=${a}&b=${b}`))
  return (
    <Card title="Compare two versions" actions={<Button size="sm" variant="primary" disabled={!a || !b} onClick={run}>Diff</Button>}>
      <div className="mb-3 grid grid-cols-2 gap-3"><select aria-label="From" value={a} onChange={(e) => setA(e.target.value)} className={inputCls}><option value="">from…</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}</select><select aria-label="To" value={b} onChange={(e) => setB(e.target.value)} className={inputCls}><option value="">to…</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}</select></div>
      {d && (d.identical ? <p className="text-sm text-slate-500">Identical.</p> : <div className="space-y-3 text-xs">{Object.entries(d.prompts).map(([role, lines]) => <div key={role}><div className="mb-1 font-semibold text-slate-700">prompt · {role}</div><pre className="scroll-thin max-h-56 overflow-auto rounded-lg bg-slate-900 p-2 text-[11px] leading-relaxed text-slate-100">{lines.map((l, i) => <div key={i} className={l.startsWith('+') ? 'text-emerald-300' : l.startsWith('-') ? 'text-rose-300' : ''}>{l}</div>)}</pre></div>)}{Object.entries(d.policy).map(([k, v]) => <p key={k}><b>policy {k}</b>: <span className="text-rose-700">{JSON.stringify(v.from)}</span> → <span className="text-emerald-700">{JSON.stringify(v.to)}</span></p>)}{Object.entries(d.tools).map(([ag, t]) => <p key={ag}><b>tools · {ag}</b>: +{t.added.join(', ') || '—'} / −{t.removed.join(', ') || '—'}</p>)}</div>)}
    </Card>
  )
}

function NewDraft({ cfgs, onDone }: { cfgs: Cfg[]; onDone: () => void }) {
  const [base, setBase] = useState('')
  const [name, setName] = useState('Candidate: stricter refund wording')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const create = async () => {
    setBusy(true); setErr(null)
    try {
      const baseCfg = base ? await api<Full>(`/api/rollout/configs/${base}`) : null
      const prompts = prompt.trim() ? { ...(baseCfg?.prompts ?? {}), resolution: `${baseCfg?.prompts?.resolution ?? ''}\n${prompt}`.trim() } : undefined
      await api('/api/rollout/configs', { body: { base_id: base || null, name, prompts, notes: 'created from the UI' } })
      onDone(); setPrompt('')
    } catch (e) { setErr(e instanceof ApiError ? JSON.stringify(e.body) : String(e)) } finally { setBusy(false) }
  }
  return (
    <Card className="mt-4" title="New draft version" subtitle="published versions are immutable - changes always create a new version">
      <div className="grid gap-3 md:grid-cols-3"><Field label="Based on"><select value={base} onChange={(e) => setBase(e.target.value)} className={inputCls}><option value="">active</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}</select></Field><Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} /></Field><Field label="Append to the resolution prompt"><input value={prompt} onChange={(e) => setPrompt(e.target.value)} className={inputCls} placeholder="e.g. Always read back the refund amount." /></Field></div>
      <div className="mt-3 flex items-center gap-3"><Button variant="primary" busy={busy} disabled={name.length < 3} onClick={create}>Create draft</Button>{err && <span role="alert" className="text-xs text-rose-700">{err}</span>}</div>
    </Card>
  )
}
