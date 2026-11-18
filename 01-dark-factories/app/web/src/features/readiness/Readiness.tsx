import { useEffect, useMemo, useState } from 'react'
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Mono, Select, useAction } from '../../components/bits'
import { Badge, Button, Card, Page, Table, Td } from '../../components/ui'
import { usePApi, usePlant, usePlantCalls, withPlant } from '../../plant'

type Q = { id: string; dim: string; text: string; measured: boolean }
type Questions = { scale: string; dimensions: Record<string, { label: string; weight: number }>; questions: Q[]; measured: Record<string, { score: number; value: number | null; unit: string }> }
type Dim = { label: string; weight: number; score: number; questions: number }
type Result = { overall: number; level: string; level_description: string; dimensions: Record<string, Dim>; gaps: { dim: string; label: string; score: number; target: number; gap: number }[]; roadmap: { dim: string; title: string; effort: string; months: string; azure: string; current: number; priority: number }[]; questions: Record<string, { score: number; basis: string }> }

export default function Readiness() {
  const calls = usePlantCalls()
  const { plantId } = usePlant()
  const qs = usePApi<Questions>('/api/readiness/questions')
  const latest = usePApi<Result>('/api/readiness/latest')
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [target, setTarget] = useState(75)
  const act = useAction<Result>()
  const res = act.result ?? latest.data
  const run = () => act.run(() => calls.post<Result>('/api/readiness/assess', { answers, target }))
  useEffect(() => { void latest.reload() }, [plantId]) // eslint-disable-line react-hooks/exhaustive-deps
  const radar = useMemo(() => Object.values(res?.dimensions ?? {}).map((d) => ({ dim: d.label, score: d.score, target })).concat([]), [res, target])
  const byDim = useMemo(() => {
    const g: Record<string, Q[]> = {}
    for (const q of qs.data?.questions ?? []) (g[q.dim] ??= []).push(q)
    return g
  }, [qs.data])
  return (
    <Page title="Autonomy-readiness assessment" subtitle="Six dimensions, 24 questions. Questions about data coverage, quality, automation and stability are measured from the running plant; the rest you answer (0-4). The output is a maturity level, the gaps against your target and a prioritised roadmap mapped to Azure services." right={
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1 text-xs text-mute">Target {target}<input aria-label="Target score" type="range" min={30} max={100} value={target} onChange={(e) => setTarget(Number(e.target.value))} /></label>
        <Button tone="primary" disabled={act.busy} onClick={run}>{act.busy ? 'Assessing…' : 'Assess readiness'}</Button>
        <a href={withPlant('/api/readiness/export?format=md', plantId)} download="readiness-assessment.md" className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-sm hover:border-accent">Export .md</a>
      </div>}>
      {act.error && <p role="alert" className="text-xs text-bad">{act.error}</p>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_520px]">
        <Card title="Questionnaire" pad={false}>
          <div className="max-h-[720px] space-y-4 overflow-auto p-4">
            <p className="text-[12px] text-mute">Scale: {qs.data?.scale}</p>
            {Object.entries(byDim).map(([dim, list]) => (
              <div key={dim}>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-accent">{qs.data?.dimensions[dim]?.label ?? dim}</div>
                <div className="divide-y divide-line/50">
                  {list.map((q) => {
                    const m = qs.data?.measured[q.id]
                    return (
                      <div key={q.id} className="flex items-center justify-between gap-3 py-1.5 text-[13px]">
                        <div className="min-w-0"><div>{q.text}</div>{m && <div className="text-[11px] text-mute">measured: {m.value != null ? Number(m.value).toFixed(2) : 'n/a'} {m.unit}</div>}</div>
                        {q.measured ? <Badge tone="ok" title="Measured from the live simulated plant">measured · {m ? m.score.toFixed(1) : '-'}</Badge> : (
                          <div className="w-24 shrink-0"><Select aria-label={q.text} value={answers[q.id] ?? ''} onChange={(e) => setAnswers({ ...answers, [q.id]: Number(e.target.value) })}>
                            <option value="">default</option>{[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
                          </Select></div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Result" right={res && <Badge tone="info">{res.level}</Badge>}>
            {res ? (
              <>
                <div className="flex items-end gap-3"><div className="tabnum text-4xl font-semibold">{res.overall.toFixed(0)}</div><div className="pb-1 text-sm text-mute">/ 100 · target {target}</div></div>
                <p className="text-[12px] text-mute">{res.level_description}</p>
                <div className="h-[260px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radar} outerRadius="72%">
                      <PolarGrid stroke="#213245" />
                      <PolarAngleAxis dataKey="dim" tick={{ fill: '#8499ae', fontSize: 11 }} />
                      <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                      <Radar name="target" dataKey="target" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.06} strokeDasharray="4 3" isAnimationActive={false} />
                      <Radar name="score" dataKey="score" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.28} isAnimationActive={false} />
                      <Tooltip contentStyle={{ background: '#101822', border: '1px solid #213245', borderRadius: 8, fontSize: 12 }} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : <p className="text-sm text-mute">Run the assessment.</p>}
          </Card>
          <Card title="Prioritised roadmap" pad={false}>
            <div className="max-h-[360px] overflow-auto">
              <Table head={['Initiative', 'When', 'Effort', 'Azure']}>
                {(res?.roadmap ?? []).slice(0, 8).map((r, i) => <tr key={i}><Td className="max-w-[210px] text-[12px]"><div>{r.title}</div><Mono>{r.dim}</Mono></Td><Td className="text-[12px]">{r.months} mo</Td><Td><Badge tone={r.effort === 'S' ? 'ok' : r.effort === 'M' ? 'warn' : 'bad'}>{r.effort}</Badge></Td><Td className="text-[11px] text-mute">{r.azure}</Td></tr>)}
              </Table>
            </div>
          </Card>
        </div>
      </div>
    </Page>
  )
}
