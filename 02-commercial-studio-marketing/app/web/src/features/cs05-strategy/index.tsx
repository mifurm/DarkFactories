/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from "@tanstack/react-query";
import { Lightbulb, Sparkles, Target, Users } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Skeleton, useToast } from "../../components/ui";
import { GuardianBadge, Tag, useJobStarter } from "../../components/common";

function StrategyTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const toast = useToast();
  const q = useQuery({ queryKey: ["strategy", id], queryFn: () => api.get(`/api/campaigns/${id}/strategy`) });
  const job = useJobStarter(() => {
    q.refetch();
    reload();
  });
  const s = q.data?.latest;
  const select = async (tid: string) => {
    await api.post(`/api/campaigns/${id}/strategy/select`, { territory_id: tid });
    toast({ tone: "good", title: "Territory selected", body: "The Script agent will write to this big idea." });
    q.refetch();
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-[13.5px] text-espresso-500">The Strategist turns the brief into insights, audience segments, a positioning line and 3–5 big-idea territories — grounded in the Brand Brain (cited) and what performance data has taught us.</p>
        <Button variant="accent" icon={<Sparkles className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/strategy/generate`, { n: 3, variation: s ? s.version : 0 })}>
          {s ? "Regenerate territories" : "Generate strategy"}
        </Button>
      </div>
      {job.node}
      {q.isLoading && <Skeleton h={200} />}
      {!q.isLoading && !s && <Empty title="No strategy yet" hint="Finalize the brief, then generate the strategy." />}
      {s && (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card title="Insights" className="lg:col-span-2" actions={<GuardianBadge g={s.guardian} />}>
              <ul className="space-y-2.5 text-[13.5px]">
                {s.insights.map((i: any, k: number) => (
                  <li key={k} className="flex gap-2.5">
                    <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-dawn-600" />
                    <div>
                      {i.text} <span className="text-[12px] text-espresso-400">— {i.source}</span>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="mt-4 rounded-xl bg-espresso-800 px-4 py-3 text-cream-100">
                <div className="text-[11px] uppercase tracking-widest text-dawn-300">Positioning</div>
                <div className="font-display text-[18px]">{s.positioning}</div>
              </div>
            </Card>
            <Card title="Segments" actions={<Users className="h-4 w-4 text-espresso-400" />}>
              <ul className="space-y-3 text-[13px]">
                {s.segments.map((g: any) => (
                  <li key={g.name}>
                    <div className="font-semibold">{g.name}</div>
                    <div className="text-espresso-500">{g.motivation}</div>
                  </li>
                ))}
              </ul>
              {s.citations?.length > 0 && (
                <div className="mt-4 border-t border-cream-200 pt-3">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-espresso-500">Grounded in (Brand Brain)</div>
                  <div className="flex flex-wrap gap-1.5">{s.citations.map((c: any) => <Tag key={c.chunk_id}>{c.title}</Tag>)}</div>
                </div>
              )}
            </Card>
          </div>
          <h3 className="font-display text-[19px] font-semibold">Big-idea territories</h3>
          <div className="grid gap-4 lg:grid-cols-3" data-testid="territories">
            {s.territories.map((t: any) => {
              const sel = s.selected_territory_id === t.id;
              return (
                <Card key={t.id} className={sel ? "ring-2 ring-dawn-500" : ""}>
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="font-display text-[19px] font-semibold leading-tight">{t.name}</h4>
                    {sel && <Badge tone="dawn">selected</Badge>}
                  </div>
                  <p className="mt-1.5 font-display text-[15px] italic text-espresso-700">“{t.big_idea}”</p>
                  <p className="mt-2 text-[13px] text-espresso-600">{t.rationale}</p>
                  <div className="mt-3 text-[11.5px] font-semibold uppercase tracking-wider text-espresso-500">Proof points</div>
                  <div className="mt-1 flex flex-wrap gap-1.5">{t.proof_points.map((p: string) => <Tag key={p}>{p}</Tag>)}</div>
                  <div className="mt-3 text-[11.5px] font-semibold uppercase tracking-wider text-roast-600">Risk notes</div>
                  <ul className="mt-1 list-disc pl-4 text-[12.5px] text-espresso-600">{t.risks.map((r: string) => <li key={r}>{r}</li>)}</ul>
                  <div className="mt-3 text-[12.5px] text-espresso-500"><Target className="mr-1 inline h-3.5 w-3.5" />Hook: {t.hook_examples[0]}</div>
                  <Button className="mt-4 w-full" variant={sel ? "ghost" : "primary"} onClick={() => select(t.id)} disabled={sel}>
                    {sel ? "Selected" : "Pick this territory"}
                  </Button>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-05", workspaceTabs: [{ id: "strategy", label: "Strategy", order: 20, Component: StrategyTab }] };
