import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { Field, Input, Json, Mono, Select, TextArea, useAction } from '../../components/bits'
import { Badge, Button, Card, Kv, Page, Table, Td } from '../../components/ui'
import { usePApi, usePlantCalls } from '../../plant'

type Cls = { level: number; label: string; sim_first: boolean; sla_min: number; rate_per_hour: number; effective_level: number }
type Pol = { version: number; kill_switch: boolean; kill_info: { reason?: string; by?: string }; global_cap: number; levels: Record<string, number>; level_names: Record<string, string>; classes: Record<string, Cls>; thresholds: Record<string, { max_risk: number; max_assets: number; max_cost_eur: number }>; protected_assets: string[]; forbidden: Record<string, number[]>; grants: { break_glass: unknown[]; timeboxes: unknown[] }; changes: { t?: number; sim_time?: string; by?: string; what?: string; detail?: string }[] }
type Matrix = { decision_class: string; outcome_by_level: Record<string, string> }
type Evaluation = Record<string, unknown> & { outcome?: string; reasons?: string[] }

const outcomeTone = (o: string) => (/auto/i.test(o) ? 'ok' : /approval|human|recommend/i.test(o) ? 'warn' : /deny|block|forbid|observe|kill/i.test(o) ? 'bad' : 'mute') as 'ok' | 'warn' | 'bad' | 'mute'

export default function PolicyPage() {
  const calls = usePlantCalls()
  const pol = usePApi<Pol>('/api/policy', { interval: 5000 })
  const rules = usePApi<{ yaml: string }>('/api/policy/rules')
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [yaml, setYaml] = useState('')
  const [cls, setCls] = useState('maintenance.schedule')
  const [risk, setRisk] = useState(0.2)
  const [assets, setAssets] = useState(1)
  const [cost, setCost] = useState(300)
  const matrix = usePApi<Matrix>(`/api/policy/matrix?decision_class=${cls}&risk=${risk}&assets=${assets}&cost_eur=${cost}`)
  const save = useAction()
  const kill = useAction()
  const yamlAct = useAction()
  const bg = useAction()
  const tb = useAction()
  const ev = useAction<Evaluation>()
  const [bgReason, setBgReason] = useState('Emergency override for plant trial')
  const p = pol.data
  useEffect(() => { if (rules.data && !yaml) setYaml(rules.data.yaml) }, [rules.data, yaml])
  const levelOf = (k: string) => draft[k] ?? p?.levels[k] ?? 0
  const dirty = Object.keys(draft).length > 0
  return (
    <Page title="Autonomy dial & policy engine" subtitle="Policy-as-code decides, for every consequential action, whether it is blocked, recommended, sent for approval, or auto-executed - by decision class, risk, blast radius and cost. The dial, the kill switch, the time-box grants and break-glass are enforced in the supervisor, not in the UI." right={
      p && (p.kill_switch ? <Button tone="primary" disabled={kill.busy} onClick={() => kill.run(() => calls.post('/api/policy/kill', { on: false, reason: 'released' }))}>Release kill switch</Button> : <Button tone="danger" disabled={kill.busy} onClick={() => kill.run(() => calls.post('/api/policy/kill', { on: true, reason: 'kill switch from the policy page' }))}>⏻ Kill switch</Button>)
    }>
      {(kill.error || save.error) && <p role="alert" className="text-xs text-bad">{kill.error ?? save.error}</p>}
      <Card title="Autonomy dial per decision class" right={<span className="flex items-center gap-2 text-[11px] text-mute">global cap
        {[0, 1, 2, 3, 4, 5].map((l) => <button key={l} aria-label={`Global cap L${l}`} onClick={async () => { await save.run(() => calls.put('/api/policy/dial', { global_cap: l })); void pol.reload() }} className={clsx('rounded border px-1.5 py-0.5', p?.global_cap === l ? 'border-accent bg-accent/15 text-accent' : 'border-line')}>L{l}</button>)}</span>} pad={false}>
        <Table head={['Decision class', 'Level', 'Effective', 'Twin first', 'SLA', 'Rate limit']}>
          {Object.entries(p?.classes ?? {}).map(([k, c]) => (
            <tr key={k}>
              <Td><div className="font-medium">{c.label}</div><Mono>{k}</Mono></Td>
              <Td><div className="flex gap-1" role="group" aria-label={`Level for ${k}`}>{[0, 1, 2, 3, 4, 5].map((l) => <button key={l} aria-label={`${k} L${l}`} aria-pressed={levelOf(k) === l} onClick={() => setDraft({ ...draft, [k]: l })} title={p?.level_names[String(l)]} className={clsx('h-6 w-8 rounded border text-[11px]', levelOf(k) === l ? 'border-accent bg-accent/20 text-accent' : 'border-line text-mute hover:text-ink')}>L{l}</button>)}</div></Td>
              <Td><Badge tone={c.effective_level < levelOf(k) ? 'warn' : 'info'}>L{c.effective_level}</Badge></Td>
              <Td>{c.sim_first ? '✓' : '-'}</Td><Td className="tabnum text-mute">{c.sla_min} min</Td><Td className="tabnum text-mute">{c.rate_per_hour}/h</Td>
            </tr>
          ))}
        </Table>
        <div className="flex items-center gap-2 border-t border-line p-3"><Button tone="primary" size="sm" disabled={!dirty || save.busy} onClick={async () => { await save.run(() => calls.put('/api/policy/dial', { levels: draft })); setDraft({}); void pol.reload() }}>Apply dial changes</Button>{dirty && <Button size="sm" tone="ghost" onClick={() => setDraft({})}>Discard</Button>}<span className="text-[11px] text-mute">Each change is written to the decision ledger.</span></div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Decision matrix: what happens at each level?">
          <div className="grid grid-cols-4 gap-2">
            <Field label="Class" className="col-span-2"><Select aria-label="Decision class" value={cls} onChange={(e) => setCls(e.target.value)}>{Object.keys(p?.classes ?? {}).map((k) => <option key={k}>{k}</option>)}</Select></Field>
            <Field label="Risk"><Input type="number" step="0.05" min={0} max={1} value={risk} onChange={(e) => setRisk(Number(e.target.value))} aria-label="Risk" /></Field>
            <Field label="Assets"><Input type="number" min={0} max={20} value={assets} onChange={(e) => setAssets(Number(e.target.value))} aria-label="Assets affected" /></Field>
            <Field label="Cost (EUR)"><Input type="number" min={0} value={cost} onChange={(e) => setCost(Number(e.target.value))} aria-label="Cost" /></Field>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 md:grid-cols-6">{Object.entries(matrix.data?.outcome_by_level ?? {}).map(([l, o]) => <div key={l} className="rounded-lg border border-line bg-panel2/50 p-2 text-center"><div className="text-[11px] font-semibold text-mute">{l}</div><Badge tone={outcomeTone(o)} className="mt-1">{o}</Badge></div>)}</div>
          <div className="mt-3 border-t border-line pt-2 text-[12px] text-mute">Auto-execution thresholds: {Object.entries(p?.thresholds ?? {}).map(([l, t]) => `L${l}: risk ≤ ${t.max_risk}, ≤ ${t.max_assets} assets, ≤ €${t.max_cost_eur}`).join(' · ')}</div>
        </Card>
        <Card title="Evaluate an arbitrary action" right={<Button size="sm" tone="primary" disabled={ev.busy} onClick={() => ev.run(() => calls.post<Evaluation>('/api/policy/evaluate', { decision_class: cls, risk, assets, cost_eur: cost }))}>Evaluate</Button>}>
          {ev.error && <p role="alert" className="text-xs text-bad">{ev.error}</p>}
          {ev.result ? <Json data={ev.result} max={220} /> : <p className="text-sm text-mute">Uses the class/risk/assets/cost from the matrix form. The same engine runs on every proposal.</p>}
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Break-glass & time-boxed autonomy">
          <p className="mb-2 text-[12px] text-mute">Break-glass raises the cap temporarily with a mandatory reason and expires automatically; a time-box grants L4+ autonomy for one class under tighter limits.</p>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Reason (break-glass)" className="col-span-2"><Input value={bgReason} onChange={(e) => setBgReason(e.target.value)} aria-label="Break-glass reason" /></Field>
          </div>
          <div className="mt-2 flex gap-2">
            <Button size="sm" tone="danger" disabled={bg.busy} onClick={async () => { await bg.run(() => calls.post('/api/policy/break-glass', { decision_class: cls, level: 5, minutes: 30, reason: bgReason })); void pol.reload() }}>Break glass 30 min (L5, {cls})</Button>
            <Button size="sm" disabled={tb.busy} onClick={async () => { await tb.run(() => calls.post('/api/policy/timebox', { decision_class: cls, minutes: 120, max_cost_eur: 1000, max_risk: 0.4 })); void pol.reload() }}>Time-box 120 min</Button>
          </div>
          {(bg.error || tb.error) && <p role="alert" className="mt-2 text-xs text-bad">{bg.error ?? tb.error}</p>}
          <div className="mt-3"><Kv k="Active break-glass grants" v={p?.grants.break_glass.length ?? 0} /><Kv k="Active time-boxes" v={p?.grants.timeboxes.length ?? 0} /><Kv k="Protected assets" v={(p?.protected_assets ?? []).join(', ')} /></div>
        </Card>
        <Card title="Policy as code (YAML)" right={<Button size="sm" tone="primary" disabled={yamlAct.busy} onClick={async () => { const r = await yamlAct.run(() => calls.put('/api/policy/rules', { yaml_text: yaml })); if (r) void pol.reload() }}>Validate & apply</Button>}>
          <TextArea aria-label="Policy YAML" rows={12} value={yaml} onChange={(e) => setYaml(e.target.value)} spellCheck={false} />
          {yamlAct.error && <p role="alert" className="mt-1 text-xs text-bad">{yamlAct.error}</p>}
          {yamlAct.result ? <p className="mt-1 text-[12px] text-ok">Policy updated (version {String((yamlAct.result as { version?: number }).version ?? '')}). Invalid YAML or out-of-range values are rejected without changing the live policy.</p> : null}
        </Card>
      </div>
      <Card title="Policy change history" pad={false}>
        {(p?.changes ?? []).length === 0 ? <p className="p-4 text-sm text-mute">No changes since start.</p> : <Table head={['When', 'By', 'Change']}>{p!.changes.slice().reverse().slice(0, 10).map((c, i) => <tr key={i}><Td className="tabnum text-mute">{c.sim_time?.slice(11, 16) ?? c.t}</Td><Td>{c.by}</Td><Td className="text-[12px]">{c.what ?? c.detail ?? JSON.stringify(c)}</Td></tr>)}</Table>}
      </Card>
    </Page>
  )
}
