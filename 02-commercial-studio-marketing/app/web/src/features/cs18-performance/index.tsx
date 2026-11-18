/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, Lightbulb, RefreshCw, Upload } from "lucide-react";
import { api, fmtNum, fmtPct, fmtUsd } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, PageHeader, Select, Skeleton, Stat, Table, useToast } from "../../components/ui";

const GROUPS = ["platform", "variant_id", "date", "hook", "cta", "visual", "source"];

function PerformancePage() {
  const toast = useToast();
  const camps = useQuery({ queryKey: ["campaigns"], queryFn: () => api.get("/api/campaigns") });
  const [campaign, setCampaign] = useState("");
  const [group, setGroup] = useState("platform");
  const metrics = useQuery({ queryKey: ["perf", campaign, group], queryFn: () => api.get(`/api/performance?group_by=${group}${campaign ? `&campaign_id=${campaign}` : ""}`) });
  const insights = useQuery({ queryKey: ["perf-insights", campaign], queryFn: () => api.get(`/api/performance/insights${campaign ? `?campaign_id=${campaign}` : ""}`) });
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: () => api.get("/api/performance/connectors"), staleTime: 600000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [fresh, setFresh] = useState<any[] | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const target = campaign || camps.data?.[0]?.id || "";
  const m = metrics.data;
  const t = m?.totals;
  const refresh = () => {
    metrics.refetch();
    insights.refetch();
  };
  const sync = async (platform: string) => {
    setBusy(platform);
    try {
      const r = await api.post(`/api/performance/connectors/${platform}/sync`, { campaign_id: target, days: 7 });
      toast({ tone: "good", title: `${platform}: ${r.ingested} rows ingested`, body: "Simulated connector — same interface as the real platform APIs." });
      refresh();
    } finally {
      setBusy(null);
    }
  };
  const upload = async (f: File) => {
    setBusy("csv");
    try {
      const fd = new FormData();
      fd.append("campaign_id", target);
      fd.append("file", f);
      const r = await api.upload("/api/performance/ingest/csv", fd);
      toast({ tone: r.errors.length ? "warn" : "good", title: `${r.ingested} rows ingested`, body: r.errors.length ? `${r.errors.length} row(s) rejected: ${r.errors[0]}` : undefined });
      refresh();
    } finally {
      setBusy(null);
      if (file.current) file.current.value = "";
    }
  };
  const gen = async () => {
    setBusy("insights");
    try {
      const r = await api.post("/api/performance/insights/generate", { campaign_id: campaign || null });
      setFresh(r.insights);
      toast({ tone: "good", title: `${r.insights.length} insight(s) from ${fmtNum(r.rows_analysed)} rows`, body: `${r.written_to_brand_brain} new learning(s) written to the Brand Brain` });
      refresh();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div>
      <PageHeader eyebrow="CS-18 · Performance ingestion & insights" title="Performance insights" subtitle="Upload an ad-platform export or sync a connector (simulated, same interface as the real APIs), see CTR / VTR / CVR / CPA / ROAS by variant and platform, then turn statistically significant findings into Brand Brain learnings." />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Campaign"><Select value={campaign} onChange={(e) => setCampaign(e.target.value)} className="w-64" aria-label="campaign"><option value="">All campaigns</option>{(camps.data ?? []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
          <Field label="Group by"><Select value={group} onChange={(e) => setGroup(e.target.value)} className="w-40" aria-label="group by">{GROUPS.map((g) => <option key={g}>{g}</option>)}</Select></Field>
          <div className="flex flex-wrap items-center gap-2">
            {(connectors.data?.connectors ?? []).map((c: any) => <Button key={c.platform} size="sm" variant="outline" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === c.platform} onClick={() => sync(c.platform)}>Sync {c.platform}</Button>)}
            <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="csv file" />
            <Button size="sm" variant="outline" icon={<Upload className="h-3.5 w-3.5" />} loading={busy === "csv"} onClick={() => file.current?.click()}>Upload CSV</Button>
          </div>
          <Button variant="accent" icon={<Lightbulb className="h-4 w-4" />} loading={busy === "insights"} onClick={gen} disabled={!m?.rows}>Generate insights</Button>
        </div>
        <div className="mt-2 text-[11.5px] text-espresso-400">CSV columns: {(connectors.data?.csv_columns ?? []).join(", ")} · connectors run against a deterministic simulator — all numbers are synthetic.</div>
      </Card>
      {metrics.isLoading && <Skeleton h={260} />}
      {m && !m.rows && <Empty title="No performance data yet" hint="Sync a connector or upload a CSV to see metrics." />}
      {t && (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="perf-stats">
            <Stat label="Impressions" value={fmtNum(t.impressions)} />
            <Stat label="CTR" value={fmtPct(t.ctr * 100, 2)} />
            <Stat label="VTR" value={t.vtr != null ? fmtPct(t.vtr * 100, 1) : "—"} />
            <Stat label="CVR" value={t.cvr != null ? fmtPct(t.cvr * 100, 2) : "—"} />
            <Stat label="CPA" value={fmtUsd(t.cpa)} />
            <Stat label="ROAS" value={t.roas != null ? `${t.roas.toFixed(2)}×` : "—"} tone="dawn" />
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2" title="Daily trend" subtitle={`${fmtNum(m.rows)} rows · sources: ${m.sources.join(", ")}`}>
              <div className="h-60">
                <ResponsiveContainer>
                  <LineChart data={m.by_day}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="key" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="l" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} />
                    <Tooltip />
                    <Line yAxisId="l" type="monotone" dataKey="impressions" stroke="#2b1a12" dot={false} strokeWidth={2} />
                    <Line yAxisId="l" type="monotone" dataKey="conversions" stroke="#5c7a5e" dot={false} strokeWidth={2} />
                    <Line yAxisId="r" type="monotone" dataKey="ctr" stroke="#d9822b" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="What works" subtitle="Written back to the Brand Brain" testId="insights">
              <ul className="space-y-2.5 text-[13px]">
                {(insights.data?.insights ?? []).slice(0, 6).map((i: any) => (
                  <li key={i.id} className="rounded-lg bg-cream-100 px-3 py-2">
                    {i.statement}
                    <div className="mt-0.5 text-[11.5px] text-espresso-400">confidence {Math.round(i.confidence * 100)}% · {i.evidence?.synthetic_history ? "synthetic history" : "from this data"}</div>
                  </li>
                ))}
                {!(insights.data?.insights ?? []).length && <li className="text-espresso-400">Generate insights to see significant lifts.</li>}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title={`By ${m.group_by}`} pad={false}>
            <div className="p-3">
              <Table
                head={[m.group_by, "Impr.", "CTR", "VTR", "CVR", "CPA", "ROAS", "Spend"]}
                rows={m.groups.map((g: any) => [<b key="k">{g.key}</b>, fmtNum(g.impressions), fmtPct((g.ctr ?? 0) * 100, 2), g.vtr != null ? fmtPct(g.vtr * 100, 1) : "—", g.cvr != null ? fmtPct(g.cvr * 100, 2) : "—", fmtUsd(g.cpa), g.roas != null ? `${g.roas.toFixed(2)}×` : "—", fmtUsd(g.spend, 0)])}
              />
            </div>
          </Card>
          {fresh && fresh.length > 0 && (
            <Card className="mt-5" title="Fresh insights" subtitle="Each carries its statistics">
              <ul className="space-y-2 text-[13px]">{fresh.map((i, k) => <li key={k}><Badge tone={i.confidence > 0.8 ? "good" : "warn"}>{Math.round(i.confidence * 100)}%</Badge> {i.statement}</li>)}</ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-18",
  routes: [{ path: "/performance", element: <PerformancePage /> }],
  nav: { group: "Performance", label: "Insights", to: "/performance", order: 20, icon: BarChart3 },
};
