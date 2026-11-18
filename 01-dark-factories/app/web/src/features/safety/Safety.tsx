import { useState } from 'react'
import { Field, Input, Json, Meter, Mono, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Kv, Page, Stat, Table, Td } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlantCalls } from '../../plant'

type Zone = { zone: string; members: string[]; occupied: boolean; occupied_min: number; restart_wait_min: number; locked_out: boolean }
type Check = { check: string; domain: string; weight: number; status: string }
type Sum = { zones: Zone[]; intrusions: { t: number; zone: string; sim_time?: string }[]; vetoes: { t?: number; sim_time?: string; plan?: string; reason?: string; agent?: string; detail?: string }[]; cyber: { score: number; checks: Check[]; simulated: boolean; note: string }; rules: { forbidden: Record<string, number[]>; protected_assets: string[]; exempt_from_kill_switch: string[] } }

const statusTone = (s: string) => (s === 'pass' ? 'ok' : s === 'warn' ? 'warn' : 'bad') as 'ok' | 'warn' | 'bad'

export default function Safety() {
  const calls = usePlantCalls()
  const sum = usePApi<Sum>('/api/safety/summary', { interval: 3000 })
  const [kind, setKind] = useState('set_speed')
  const [asset, setAsset] = useState('CNC-01')
  const [pct, setPct] = useState(240)
  const chk = useAction<{ allowed: boolean; needs_human: boolean; violations: { rule: string; severity: string; detail: string }[] }>()
  const intr = useAction()
  const s = sum.data
  const r = chk.result
  return (
    <Page title="Safety & cybersecurity" subtitle="Safety is a hard constraint, not an objective: the Safety agent holds a veto over every other agent, a protective stop always works (even under the kill switch), forbidden setpoints are rejected in code, and restart after an intrusion needs verified-clear. Cyber posture is a simulated checklist.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Zones occupied" value={(s?.zones ?? []).filter((z) => z.occupied).length} tone={(s?.zones ?? []).some((z) => z.occupied) ? 'bad' : 'ok'} />
        <Stat label="Intrusions handled" value={s?.intrusions.length ?? 0} />
        <Stat label="Vetoes issued" value={s?.vetoes.length ?? 0} />
        <Stat label="Cyber posture" value={`${s?.cyber.score ?? '-'}/100`} sub="simulated checklist" tone={(s?.cyber.score ?? 0) > 80 ? 'ok' : 'warn'} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
        <div className="space-y-4">
          <Card title="Safety zones" pad={false} right={<Button size="sm" tone="danger" disabled={intr.busy} onClick={() => intr.run(() => calls.post('/api/sim/faults', { kind: 'human_intrusion', zone: 'Z-MACH-A' }))}>Simulate human intrusion · Z-MACH-A</Button>}>
            <Table head={['Zone', 'Members', 'State', 'Occupied', 'Restart wait']}>
              {(s?.zones ?? []).map((z) => (
                <tr key={z.zone}>
                  <Td className="font-medium">{z.zone}</Td><Td className="text-[12px] text-mute">{z.members.join(', ')}</Td>
                  <Td><Badge tone={z.locked_out ? 'bad' : z.occupied ? 'warn' : 'ok'}>{z.locked_out ? 'locked out' : z.occupied ? 'human present' : 'clear'}</Badge></Td>
                  <Td className="tabnum">{z.occupied ? fmt.dur(z.occupied_min) : '-'}</Td><Td className="tabnum">{z.restart_wait_min ? fmt.dur(z.restart_wait_min) : '-'}</Td>
                </tr>
              ))}
            </Table>
            {intr.error && <p role="alert" className="p-3 text-xs text-bad">{intr.error}</p>}
          </Card>
          <Card title="Vetoes & protective actions" pad={false}>
            {!s?.vetoes.length ? <div className="p-4"><Empty>No vetoes yet. Try the rule tester on the right, or run the "perfect-storm" scenario.</Empty></div> : (
              <Table head={['When', 'Agent', 'Plan', 'Reason']}>{s.vetoes.slice().reverse().slice(0, 8).map((v, i) => <tr key={i}><Td className="tabnum text-mute">{v.sim_time?.slice(11, 16) ?? v.t}</Td><Td>{v.agent}</Td><Td className="font-mono text-[11px]">{v.plan}</Td><Td className="text-[12px]">{v.reason ?? v.detail}</Td></tr>)}</Table>
            )}
          </Card>
          <Card title="Cyber posture (simulated checklist)" right={<Badge tone="warn">simulated</Badge>}>
            <div className="mb-3 flex items-center gap-3"><div className="tabnum text-3xl font-semibold">{s?.cyber.score ?? '-'}</div><div className="flex-1"><Meter value={s?.cyber.score ?? 0} max={100} tone={(s?.cyber.score ?? 0) > 80 ? 'ok' : 'warn'} /><div className="mt-1 text-[11px] text-mute">{s?.cyber.note}</div></div></div>
            <div className="grid gap-x-6 md:grid-cols-2">{(s?.cyber.checks ?? []).map((c) => <Kv key={c.check} k={<span><Mono>{c.domain}</Mono> {c.check}</span>} v={<Badge tone={statusTone(c.status)}>{c.status}</Badge>} />)}</div>
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Safety rule tester (is this action allowed?)">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Action"><Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Action kind"><option value="set_speed">set speed</option><option value="safe_stop">safe stop</option><option value="resume">resume</option></Select></Field>
              <Field label="Asset"><Input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} aria-label="Asset id" /></Field>
              {kind === 'set_speed' && <Field label="Speed %"><Input type="number" value={pct} onChange={(e) => setPct(Number(e.target.value))} aria-label="Speed percent" /></Field>}
            </div>
            <Button className="mt-3" size="sm" tone="primary" disabled={chk.busy} onClick={() => chk.run(() => calls.post('/api/safety/check', { kind, asset, params: kind === 'set_speed' ? { pct } : {} }))}>Check against safety rules</Button>
            {chk.error && <p role="alert" className="mt-2 text-xs text-bad">{chk.error}</p>}
            {r && (
              <div className="mt-3 rounded-lg border border-line bg-panel2/50 p-2 text-[13px]">
                <Badge tone={r.allowed ? 'ok' : 'bad'}>{r.allowed ? 'allowed' : 'DENIED'}</Badge>{r.needs_human && <Badge tone="warn" className="ml-2">needs human</Badge>}
                <ul className="mt-1 list-disc pl-5 text-[12px] text-mute">{r.violations.map((v, i) => <li key={i}><b className="text-bad">{v.rule}</b> ({v.severity}): {v.detail}</li>)}</ul>
              </div>
            )}
          </Card>
          <Card title="Hard rules enforced in code">
            <Kv k="Forbidden setpoint ranges" v={<span className="text-[12px]">{Object.entries(s?.rules.forbidden ?? {}).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v[0]}…${v[1]}`).join(' · ')}</span>} />
            <Kv k="Protected assets (human approval for disruptive actions)" v={(s?.rules.protected_assets ?? []).join(', ')} />
            <Kv k="Exempt from kill switch" v={(s?.rules.exempt_from_kill_switch ?? []).join(', ')} />
            <details className="mt-2 text-[12px]"><summary className="cursor-pointer text-mute">Raw rules</summary><Json data={s?.rules} max={160} /></details>
          </Card>
        </div>
      </div>
    </Page>
  )
}
