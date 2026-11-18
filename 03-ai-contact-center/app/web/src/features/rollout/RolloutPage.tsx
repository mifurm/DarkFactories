import { GitBranch, Rocket, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import { api, describeError, useApi } from '../../lib/api'
import { localizeGateReason } from '../evals/checks'
import { Badge, Button, Card, DataTable, Empty, ErrorBox, Field, PageHeader, Spinner, Stat, Tabs, inputCls } from '../../lib/ui'

interface Cfg { id: string; name: string; version: number; status: string; canary_pct: number; created_at: number; created_by: string; parent: string | null; notes: string; gate: { passed: boolean; reasons: string[] } | null }
interface Ab { versions: { config: string; conversations: number; containment: number | null; escalation_rate: number | null; qa_avg: number | null; cost_per_conversation?: number | null; eval?: { pass_rate: number } | null; eval_pass_rate?: number | null }[]; canary: { config: string | null; pct: number }; active: string }
interface Diff { a: string; b: string; prompts: Record<string, string[]>; policy: Record<string, { from: unknown; to: unknown }>; tools: Record<string, { added: string[]; removed: string[] }>; identical: boolean }
interface Log { id: string; ts: number; action: string; config: string; actor: string; detail: Record<string, unknown> }
interface Full { id: string; prompts: Record<string, string>; policy: Record<string, unknown> }

const TONE: Record<string, string> = { active: 'green', canary: 'violet', candidate: 'blue', draft: 'slate', retired: 'slate' }

export default function RolloutPage() {
  const i18n = useI18n()
  const { t, te, tl, ts, fmt } = i18n
  const [tab, setTab] = useState('versions')
  const cfgs = useApi<Cfg[]>('/api/rollout/configs', { refreshMs: 8000 })
  const ab = useApi<Ab>('/api/rollout/ab', { refreshMs: 8000 })
  const log = useApi<Log[]>('/api/rollout/log', { refreshMs: 8000 })
  const [sel, setSel] = useState<Cfg | null>(null)
  const [pct, setPct] = useState(20)
  const [msg, setMsg] = useState<{ tone: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setMsg({ tone: 'green', text: ok })
      cfgs.reload()
      ab.reload()
      log.reload()
    } catch (e) {
      setMsg({ tone: 'red', text: describeError(e) })
    } finally {
      setBusy(false)
    }
  }
  const active = cfgs.data?.find((c) => c.status === 'active')
  const pass = (c: Cfg) => (c.gate ? <Badge tone={c.gate.passed ? 'green' : 'red'}>{te('evalResult', c.gate.passed ? 'passed' : 'failed')}</Badge> : <span className="text-slate-400">—</span>)
  return (
    <div>
      <PageHeader icon={GitBranch} title={t('Prompt, policy & knowledge management')} subtitle={t('Versioned agent configurations: draft → eval gate → canary % → promote, A/B on live metrics, one-click rollback and a full audit trail.')}
        actions={<Button icon={Undo2} busy={busy} onClick={() => act(() => api('/api/rollout/rollback', { method: 'POST' }), t('Rolled back - new conversations use the previous version; in-flight ones finish on theirs.'))}>{t('Rollback')}</Button>} />
      {msg && <div role="status" className={`mb-3 rounded-xl px-3 py-2 text-sm ring-1 ${msg.tone === 'green' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-rose-50 text-rose-700 ring-rose-200'}`}>{msg.text}</div>}
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Stat label={t('Active version')} value={ab.data?.active ?? '…'} tone="green" />
        <Stat label={t('Canary')} value={ab.data?.canary.config ? `${ab.data.canary.config} · ${fmt.plain(ab.data.canary.pct)}%` : t('none')} tone={ab.data?.canary.config ? 'violet' : undefined} />
        <Stat label={t('Versions')} value={cfgs.data?.length ?? '…'} />
      </div>
      <Tabs tabs={[{ id: 'versions', label: t('Versions & promotion') }, { id: 'ab', label: t('A/B comparison') }, { id: 'diff', label: t('Diff') }, { id: 'log', label: t('Audit trail') }]} value={tab} onChange={setTab} />
      {tab === 'versions' && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card title={t('Configurations')} pad={false}>
            {cfgs.loading && !cfgs.data ? <Spinner /> : cfgs.error ? <ErrorBox error={cfgs.error} /> : (
              <DataTable dense rows={cfgs.data ?? []} rowKey={(c) => c.id} selected={sel?.id} onRowClick={setSel} cols={[
                { key: 'i', header: t('Version'), render: (c) => <span className="font-mono text-xs">{c.id}</span> },
                { key: 'n', header: t('Name'), render: (c) => <span className="font-medium">{ts(c.name)}</span> },
                { key: 's', header: t('Status'), render: (c) => <Badge tone={TONE[c.status]}>{te('configStatus', c.status)}{c.status === 'canary' ? ` ${fmt.plain(c.canary_pct)}%` : ''}</Badge> },
                { key: 'g', header: t('Eval gate'), render: pass },
                { key: 'c', header: t('By'), render: (c) => <span className="text-xs text-slate-500">{c.created_by} · {fmt.dt(c.created_at)}</span> },
              ]} />
            )}
          </Card>
          <Card title={sel ? t('Promote {id}', { id: sel.id }) : t('Promotion workflow')} subtitle={t('draft → eval gate → canary → promote')}>
            {!sel ? <Empty>{t('Select a version.')}</Empty> : (
              <div className="space-y-3 text-sm">
                <p className="text-slate-600">{ts(sel.notes) || '—'}</p>
                {sel.gate && !sel.gate.passed && <ul className="list-disc pl-4 text-xs text-rose-700">{sel.gate.reasons.map((r, i) => <li key={i}>{localizeGateReason(r, i18n)}</li>)}</ul>}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/gate?suite=gate`, { method: 'POST' }), t('Gate suite started - see the result in a moment.'))}>{t('1 · Run eval gate')}</Button>
                  <Button size="sm" busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/canary`, { body: { pct } }), t('Canary {pct}% started (deterministic hash of the conversation id).', { pct }))}>{t('2 · Canary {pct}%', { pct })}</Button>
                  <Button size="sm" variant="primary" icon={Rocket} busy={busy} onClick={() => act(() => api(`/api/rollout/configs/${sel.id}/promote`, { method: 'POST' }), t('{id} promoted to active.', { id: sel.id }))}>{t('3 · Promote')}</Button>
                </div>
                <input type="range" min={5} max={100} step={5} value={pct} onChange={(e) => setPct(Number(e.target.value))} aria-label={t('Canary percentage')} className="w-full accent-violet-600" />
                <p className="text-xs text-slate-500">{t('Promotion is blocked unless the candidate has a passing eval gate.')} {active && t('Active now: {id}.', { id: active.id })}</p>
              </div>
            )}
          </Card>
        </div>
      )}
      {tab === 'ab' && (
        <Card title={t('Live metrics by configuration version')} subtitle={t('conversations split by the version they started on')} pad={false}>
          <DataTable dense rows={ab.data?.versions ?? []} rowKey={(v) => v.config} empty={t('No conversations yet.')} cols={[
            { key: 'c', header: t('Version'), render: (v) => <span className="font-mono text-xs">{v.config}</span> },
            { key: 'n', header: t('Conversations'), align: 'right', render: (v) => v.conversations },
            { key: 'k', header: t('Containment'), align: 'right', render: (v) => (v.containment != null ? fmt.percent(v.containment, 0) : '—') },
            { key: 'e', header: t('Escalation'), align: 'right', render: (v) => (v.escalation_rate != null ? fmt.percent(v.escalation_rate, 0) : '—') },
            { key: 'q', header: t('QA avg'), align: 'right', render: (v) => (v.qa_avg != null ? fmt.plain(v.qa_avg) : '—') },
            { key: 'p', header: t('Eval pass rate'), align: 'right', render: (v) => (v.eval?.pass_rate != null ? fmt.percent(v.eval.pass_rate, 0) : v.eval_pass_rate != null ? fmt.percent(v.eval_pass_rate, 0) : '—') },
          ]} />
        </Card>
      )}
      {tab === 'diff' && <DiffTab cfgs={cfgs.data ?? []} />}
      {tab === 'log' && (
        <Card title={t('Audit trail')} subtitle={t('who changed what, when')} pad={false}>
          <DataTable dense rows={log.data ?? []} rowKey={(l) => l.id} empty={t('No changes yet.')} cols={[
            { key: 't', header: t('Time'), render: (l) => fmt.dt(l.ts) },
            { key: 'a', header: t('Action'), render: (l) => <Badge tone="violet">{te('rolloutAction', l.action)}</Badge> },
            { key: 'c', header: t('Config'), render: (l) => <span className="font-mono text-xs">{l.config}</span> },
            { key: 'u', header: t('Actor'), render: (l) => tl('role', l.actor, l.actor) },
            { key: 'd', header: t('Detail'), render: (l) => <span data-user-content className="text-xs text-slate-500">{JSON.stringify(l.detail).slice(0, 90)}</span> },
          ]} />
        </Card>
      )}
      <NewDraft cfgs={cfgs.data ?? []} onDone={() => { cfgs.reload(); log.reload() }} />
    </div>
  )
}

function DiffTab({ cfgs }: { cfgs: Cfg[] }) {
  const { t, te, ts } = useI18n()
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [d, setD] = useState<Diff | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setErr(null)
    try {
      setD(await api<Diff>(`/api/rollout/diff?a=${a}&b=${b}`))
    } catch (e) {
      setErr(describeError(e))
    }
  }
  return (
    <Card title={t('Compare two versions')} actions={<Button size="sm" variant="primary" disabled={!a || !b} onClick={run}>{t('Diff')}</Button>}>
      <div className="mb-3 grid grid-cols-2 gap-3">
        <select aria-label={t('From')} value={a} onChange={(e) => setA(e.target.value)} className={inputCls}><option value="">{t('from…')}</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {ts(c.name)}</option>)}</select>
        <select aria-label={t('To')} value={b} onChange={(e) => setB(e.target.value)} className={inputCls}><option value="">{t('to…')}</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {ts(c.name)}</option>)}</select>
      </div>
      {err && <p role="alert" className="mb-2 text-sm text-rose-700">{err}</p>}
      {d && (d.identical ? <p className="text-sm text-slate-500">{t('Identical.')}</p> : (
        <div className="space-y-3 text-xs">
          {Object.entries(d.prompts).map(([role, lines]) => <div key={role}><div className="mb-1 font-semibold text-slate-700">{t('prompt · {role}', { role: te('agentRole', role) })}</div><pre data-i18n-skip className="scroll-thin max-h-56 overflow-auto rounded-lg bg-slate-900 p-2 text-[11px] leading-relaxed text-slate-100">{lines.map((l, i) => <div key={i} className={l.startsWith('+') ? 'text-emerald-300' : l.startsWith('-') ? 'text-rose-300' : ''}>{l}</div>)}</pre></div>)}
          {Object.entries(d.policy).map(([k, v]) => <p key={k}><b>{t('policy {key}', { key: te('policyParam', k) })}</b>: <span data-user-content className="text-rose-700">{JSON.stringify(v.from)}</span> → <span data-user-content className="text-emerald-700">{JSON.stringify(v.to)}</span></p>)}
          {Object.entries(d.tools).map(([ag, tl]) => <p key={ag}><b>{t('tools · {agent}', { agent: te('agentRole', ag) })}</b>: +{tl.added.join(', ') || '—'} / −{tl.removed.join(', ') || '—'}</p>)}
        </div>
      ))}
    </Card>
  )
}

function NewDraft({ cfgs, onDone }: { cfgs: Cfg[]; onDone: () => void }) {
  const { t, ts } = useI18n()
  const [base, setBase] = useState('')
  const [name, setName] = useState(() => t('Candidate: stricter refund wording'))
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const create = async () => {
    setBusy(true)
    setErr(null)
    try {
      const baseCfg = base ? await api<Full>(`/api/rollout/configs/${base}`) : null
      const prompts = prompt.trim() ? { ...(baseCfg?.prompts ?? {}), resolution: `${baseCfg?.prompts?.resolution ?? ''}\n${prompt}`.trim() } : undefined
      await api('/api/rollout/configs', { body: { base_id: base || null, name, prompts, notes: t('created from the UI') } })
      onDone()
      setPrompt('')
    } catch (e) {
      setErr(describeError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="mt-4" title={t('New draft version')} subtitle={t('published versions are immutable - changes always create a new version')}>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('Based on')}><select value={base} onChange={(e) => setBase(e.target.value)} className={inputCls}><option value="">{t('active')}</option>{cfgs.map((c) => <option key={c.id} value={c.id}>{c.id} · {ts(c.name)}</option>)}</select></Field>
        <Field label={t('Name')}><input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} /></Field>
        <Field label={t('Append to the resolution prompt')}><input value={prompt} onChange={(e) => setPrompt(e.target.value)} className={inputCls} placeholder={t('e.g. Always read back the refund amount.')} /></Field>
      </div>
      <div className="mt-3 flex items-center gap-3"><Button variant="primary" busy={busy} disabled={name.length < 3} onClick={create}>{t('Create draft')}</Button>{err && <span role="alert" className="text-xs text-rose-700">{err}</span>}</div>
    </Card>
  )
}
