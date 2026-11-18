/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Meter, Skeleton, Table } from "../../components/ui";
import { msg, useI18n } from "../../i18n";

// English constant the API returns verbatim; tKnown() translates it in a non-English UI when the server did not localize it.
const KNOWN_SERVER_TEXT = [msg("Predictive / simulated — a synthetic audience panel plus heuristics. Not a measurement; validate with live tests (CS-17).")];

function ScorecardTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tEnum, fmt, tKnown } = useI18n();
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
  const radar = latest ? Object.entries(latest.parts).map(([k, v]) => ({ k: tEnum("scorePart", k, k), v })) : [];
  return (
    <div className="space-y-5">
      <Card
        title={t("Pre-flight creative scorecard")}
        subtitle={q.data?.label ? tKnown(q.data.label) : t("Predictive / simulated — synthetic audience panel plus heuristics.")}
        actions={
          <Button variant="accent" icon={<Gauge className="h-4 w-4" />} onClick={run} loading={busy}>
            {t("Score latest creative")}
          </Button>
        }
      />
      {q.isLoading && <Skeleton h={220} />}
      {!q.isLoading && !latest && <Empty title={t("No scorecard yet")} hint={t("Score the latest script or rendered spot before it goes live.")} />}
      {latest && (
        <div className="grid gap-5 lg:grid-cols-3" data-testid="scorecard">
          <Card title={t("Predicted score")} actions={<Badge tone="warn">{t("simulated")}</Badge>}>
            <div className="font-display text-[56px] font-semibold leading-none">
              {fmt.number(latest.predicted_score)}
              <span className="text-[20px] text-espresso-400"> / 100</span>
            </div>
            <div className="mt-1 text-[12.5px] text-espresso-500">{t("heuristics {h} · panel appeal {a}/10 · {pct}% would click", { h: fmt.number(latest.heuristic_score, 2), a: fmt.number(latest.panel_avg_appeal, 2), pct: fmt.number(latest.would_click_pct, 2) })}</div>
            <div className="mt-4 h-52">
              <ResponsiveContainer>
                <RadarChart data={radar} outerRadius="72%">
                  <PolarGrid stroke="#e7dccd" />
                  <PolarAngleAxis dataKey="k" tick={{ fontSize: 11, fill: "#5b4636" }} />
                  <Radar dataKey="v" name={t("Predicted score")} stroke="#d9822b" fill="#f2a03d" fillOpacity={0.45} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title={t("Score breakdown")} subtitle={t("Weighted heuristics")}>
            <ul className="space-y-3 text-[13px]">
              {Object.entries(latest.parts).map(([k, v]: any) => (
                <li key={k}>
                  <div className="flex justify-between gap-2">
                    <span>
                      {tEnum("scorePart", k, k)} <span className="text-espresso-400">×{fmt.number(latest.weights[k], 3)}</span>
                    </span>
                    <b className="tabular-nums">{fmt.number(v, 2)}</b>
                  </div>
                  <Meter value={v} max={100} tone={v < 50 ? "bad" : v < 70 ? "warn" : undefined} />
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t("Suggestions")} subtitle={t("Highest-impact fixes first")}>
            <ul className="list-disc space-y-1.5 pl-5 text-[13px]">
              {latest.suggestions.map((s: string, i: number) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
            {latest.suggestions.length === 0 && <div className="text-[13px] text-sage-600">{t("No improvements suggested.")}</div>}
          </Card>
          <Card className="lg:col-span-3" title={t("Synthetic audience panel")} subtitle={t("Persona-based simulated reactions — not a measurement")} pad={false}>
            <div className="p-3">
              <Table
                head={[t("Persona"), t("Appeal"), t("Click?"), t("Reaction"), t("Concerns")]}
                rows={latest.panel.map((v: any) => [
                  v.persona_id,
                  `${v.appeal}/10`,
                  v.would_click ? (
                    <Badge key="c" tone="good">
                      {t("yes")}
                    </Badge>
                  ) : (
                    <Badge key="c">{t("no")}</Badge>
                  ),
                  v.reaction,
                  (v.concerns ?? []).join("; ") || "—",
                ])}
              />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-16", workspaceTabs: [{ id: "scorecard", label: msg("Scorecard"), order: 120, Component: ScorecardTab }] };
