/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Meter, Skeleton, Table } from "../../components/ui";

const PART_LABEL: Record<string, string> = { hook: "Hook (first 3 s)", brand: "Brand presence", clarity: "Clarity", cta: "Call to action", accessibility: "Accessibility", compliance: "Compliance" };

function ScorecardTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const q = useQuery({ queryKey: ["scorecard", id], queryFn: () => api.get(`/api/campaigns/${id}/scorecard`) });
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await api.post(`/api/campaigns/${id}/scorecard`, {});
      q.refetch();
      reload();
    } finally {
      setBusy(false);
    }
  };
  const latest = q.data?.scorecards?.[0];
  const radar = latest ? Object.entries(latest.parts).map(([k, v]) => ({ k: PART_LABEL[k] ?? k, v })) : [];
  return (
    <div className="space-y-5">
      <Card title="Pre-flight creative scorecard" subtitle={q.data?.label ?? "Predictive / simulated — synthetic audience panel plus heuristics."} actions={<Button variant="accent" icon={<Gauge className="h-4 w-4" />} onClick={run} loading={busy}>Score latest creative</Button>} />
      {q.isLoading && <Skeleton h={220} />}
      {!q.isLoading && !latest && <Empty title="No scorecard yet" hint="Score the latest script or rendered spot before it goes live." />}
      {latest && (
        <div className="grid gap-5 lg:grid-cols-3" data-testid="scorecard">
          <Card title="Predicted score" actions={<Badge tone="warn">simulated</Badge>}>
            <div className="font-display text-[56px] font-semibold leading-none">{latest.predicted_score}<span className="text-[20px] text-espresso-400"> / 100</span></div>
            <div className="mt-1 text-[12.5px] text-espresso-500">heuristics {latest.heuristic_score} · panel appeal {latest.panel_avg_appeal}/10 · {latest.would_click_pct}% would click</div>
            <div className="mt-4 h-52">
              <ResponsiveContainer>
                <RadarChart data={radar} outerRadius="72%">
                  <PolarGrid stroke="#e7dccd" />
                  <PolarAngleAxis dataKey="k" tick={{ fontSize: 11, fill: "#5b4636" }} />
                  <Radar dataKey="v" stroke="#d9822b" fill="#f2a03d" fillOpacity={0.45} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title="Score breakdown" subtitle="Weighted heuristics">
            <ul className="space-y-3 text-[13px]">
              {Object.entries(latest.parts).map(([k, v]: any) => (
                <li key={k}>
                  <div className="flex justify-between"><span>{PART_LABEL[k] ?? k} <span className="text-espresso-400">×{latest.weights[k]}</span></span><b className="tabular-nums">{v}</b></div>
                  <Meter value={v} max={100} tone={v < 50 ? "bad" : v < 70 ? "warn" : undefined} />
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Suggestions" subtitle="Highest-impact fixes first">
            <ul className="list-disc space-y-1.5 pl-5 text-[13px]">{latest.suggestions.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
            {latest.suggestions.length === 0 && <div className="text-[13px] text-sage-600">No improvements suggested.</div>}
          </Card>
          <Card className="lg:col-span-3" title="Synthetic audience panel" subtitle="Persona-based simulated reactions — not a measurement" pad={false}>
            <div className="p-3">
              <Table head={["Persona", "Appeal", "Click?", "Reaction", "Concerns"]} rows={latest.panel.map((v: any) => [v.persona_id, `${v.appeal}/10`, v.would_click ? <Badge key="c" tone="good">yes</Badge> : <Badge key="c">no</Badge>, v.reaction, (v.concerns ?? []).join("; ") || "—"])} />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-16", workspaceTabs: [{ id: "scorecard", label: "Scorecard", order: 120, Component: ScorecardTab }] };
