import { useState } from 'react'
import { Md, useAction } from '../../components/bits'
import { Badge, Button, Card, Empty, Page, Stat } from '../../components/ui'
import { fmt } from '../../lib/feature'
import { usePApi, usePlant, usePlantCalls, withPlant } from '../../plant'

type Row = { id: string; shift: string; sim_time: string; source: string; summary: string }
type Report = { id: string; shift: string; sim_time: string; source: string; model: string; summary: string; markdown: string; budget_blocked?: boolean; data: { eur_saved_estimate: number; failures_avoided: number; missed_due_dates: number; auto_decisions: number; human_decisions: number } }

export default function Handover() {
  const calls = usePlantCalls()
  const { plantId } = usePlant()
  const list = usePApi<Row[]>('/api/handover/reports', { interval: 6000 })
  const sched = usePApi<{ boundaries: string[]; next_in_sim_min: number; pending_auto_reports: number; generated: number }>('/api/handover/schedule', { interval: 6000 })
  const [sel, setSel] = useState<string | null>(null)
  const [useLlm, setUseLlm] = useState(true)
  const [hours, setHours] = useState(8)
  const gen = useAction<Report>()
  const one = usePApi<Report>(sel ? `/api/handover/reports/${sel}` : null)
  const rep = (sel && one.data?.id === sel ? one.data : null) ?? gen.result
  return (
    <Page title="Shift handover report" subtitle="At each shift boundary (06:00 / 14:00 / 22:00 simulated) - or on demand - the plant writes the report a night-shift lead would hand over: KPIs, decisions taken, what a human approved, failures avoided, open risks. Numbers come from the ledger and KPI engine; the model only narrates them, and a deterministic template is used when it is unavailable.">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Reports generated" value={sched.data?.generated ?? 0} />
        <Stat label="Next shift boundary" value={sched.data ? fmt.dur(sched.data.next_in_sim_min) : '-'} sub={`boundaries ${sched.data?.boundaries.join(' / ') ?? ''}`} />
        <Stat label="Auto reports queued" value={sched.data?.pending_auto_reports ?? 0} />
        <Stat label="Last source" value={list.data?.[0]?.source ?? '-'} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card title="Generate now">
            <div className="flex items-center gap-3 text-sm">
              <label className="flex items-center gap-1">Window <select aria-label="Window hours" value={hours} onChange={(e) => setHours(Number(e.target.value))} className="rounded-md border border-line bg-panel2 px-1.5 py-1">{[4, 8, 12].map((h) => <option key={h} value={h}>{h} h</option>)}</select></label>
              <label className="flex items-center gap-1 text-[12px] text-mute"><input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> narrate with Azure OpenAI</label>
            </div>
            <Button className="mt-3" tone="primary" disabled={gen.busy} onClick={async () => { const r = await gen.run(() => calls.post<Report>('/api/handover/generate', { window_hours: hours, use_llm: useLlm })); if (r) { setSel(r.id); void list.reload() } }}>{gen.busy ? 'Writing report…' : 'Generate shift report'}</Button>
            {gen.error && <p role="alert" className="mt-2 text-xs text-bad">{gen.error}</p>}
          </Card>
          <Card title="Reports" pad={false}>
            {!list.data?.length ? <div className="p-4"><Empty>No reports yet.</Empty></div> : (
              <ul className="divide-y divide-line/60">
                {list.data.map((r) => (
                  <li key={r.id}><button onClick={() => setSel(r.id)} className={`block w-full px-4 py-2 text-left hover:bg-white/5 ${sel === r.id ? 'bg-accent/10' : ''}`}><div className="flex items-center justify-between"><span className="text-sm font-medium">{r.shift} · {r.sim_time.slice(5, 16).replace('T', ' ')}</span><Badge tone={r.source === 'azure' ? 'info' : 'mute'}>{r.source}</Badge></div><div className="mt-0.5 line-clamp-2 text-[12px] text-mute">{r.summary}</div></button></li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card title={rep ? `${rep.shift} shift · ${rep.sim_time.slice(0, 16).replace('T', ' ')}` : 'Report'} right={rep && <span className="flex items-center gap-2"><Badge tone={rep.source === 'azure' ? 'info' : 'mute'}>{rep.source}{rep.model ? ` · ${rep.model}` : ''}</Badge><a className="text-xs text-accent" href={withPlant(`/api/handover/reports/${rep.id}?format=html`, plantId)} target="_blank" rel="noreferrer">HTML</a><a className="text-xs text-accent" href={withPlant(`/api/handover/reports/${rep.id}?format=md`, plantId)} target="_blank" rel="noreferrer">Markdown</a></span>}>
          {!rep ? <Empty>Generate a report or pick one from the list.</Empty> : (
            <div>
              <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
                <Stat label="Failures avoided" value={rep.data.failures_avoided} tone="ok" />
                <Stat label="Est. saved" value={fmt.eur(rep.data.eur_saved_estimate)} tone="ok" />
                <Stat label="Missed due dates" value={rep.data.missed_due_dates} tone={rep.data.missed_due_dates ? 'warn' : 'ok'} />
                <Stat label="Auto decisions" value={rep.data.auto_decisions} />
                <Stat label="Human decisions" value={rep.data.human_decisions} />
              </div>
              <p className="mb-3 rounded-lg bg-accent/10 p-3 text-sm">{rep.summary}</p>
              <Md text={rep.markdown} />
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
