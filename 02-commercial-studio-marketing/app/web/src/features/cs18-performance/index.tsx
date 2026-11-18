/* eslint-disable @typescript-eslint/no-explicit-any */
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, Lightbulb, RefreshCw, Upload } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, PageHeader, Select, Skeleton, Stat, Table, useToast } from "../../components/ui";
import { msg, useI18n, useOnLangChange } from "../../i18n";

const GROUPS = ["platform", "variant_id", "date", "hook", "cta", "visual", "source"];

function PerformancePage() {
  const { t, tn, tEnum, tOpen, fmt } = useI18n();
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
  const tot = m?.totals;
  useOnLangChange(() => setFresh(null)); // the fresh statements were written in the previous language; the "What works" list is re-read in the new one
  const refresh = () => {
    metrics.refetch();
    insights.refetch();
  };
  const sync = async (platform: string) => {
    setBusy(platform);
    try {
      const r = await api.post(`/api/performance/connectors/${platform}/sync`, { campaign_id: target, days: 7 });
      toast({ tone: "good", title: t("{platform}: {rows}", { platform: tOpen("platform", platform), rows: tn(r.ingested, { one: "{n} row ingested", other: "{n} rows ingested" }) }), body: t("Simulated connector — same interface as the real platform APIs.") });
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
      toast({ tone: r.errors.length ? "warn" : "good", title: tn(r.ingested, { one: "{n} row ingested", other: "{n} rows ingested" }), body: r.errors.length ? t("{rows}: {first}", { rows: tn(r.errors.length, { one: "{n} row(s) rejected", other: "{n} row(s) rejected" }), first: r.errors[0] }) : undefined });
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
      toast({
        tone: "good",
        title: t("{insights} from {rows}", { insights: tn(r.insights.length, { one: "{n} insight(s)", other: "{n} insight(s)" }), rows: tn(r.rows_analysed, { one: "{n} row", other: "{n} rows" }) }),
        body: tn(r.written_to_brand_brain, { one: "{n} new learning(s) written to the Brand Brain", other: "{n} new learning(s) written to the Brand Brain" }),
      });
      refresh();
    } finally {
      setBusy(null);
    }
  };
  /** group keys are ids: platforms, variant option labels, ISO dates, connector sources */
  const groupKey = (g: string, key: string) => {
    if (g === "platform") return tOpen("platform", key);
    if (g === "date") return fmt.isoDate(key);
    if (g === "hook" || g === "cta" || g === "visual") return tOpen("variantOption", key);
    if (g === "source") return sourceLabel(key);
    return key;
  };
  const sourceLabel = (s: string) => (s.startsWith("connector:") ? t("connector: {name}", { name: tOpen("platform", s.slice(10)) }) : tOpen("perfSource", s));
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-18 · Performance ingestion & insights")}
        title={t("Performance insights")}
        subtitle={t("Upload an ad-platform export or sync a connector (simulated, same interface as the real APIs), see CTR / VTR / CVR / CPA / ROAS by variant and platform, then turn statistically significant findings into Brand Brain learnings.")}
      />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Campaign")}>
            <Select value={campaign} onChange={(e) => setCampaign(e.target.value)} className="w-64" aria-label={t("campaign")}>
              <option value="">{t("All campaigns")}</option>
              {(camps.data ?? []).map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("Group by")}>
            <Select value={group} onChange={(e) => setGroup(e.target.value)} className="w-44" aria-label={t("group by")}>
              {GROUPS.map((g) => (
                <option key={g} value={g}>
                  {tEnum("groupBy", g)}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            {(connectors.data?.connectors ?? []).map((c: any) => (
              <Button key={c.platform} size="sm" variant="outline" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === c.platform} onClick={() => sync(c.platform)}>
                {t("Sync {platform}", { platform: tOpen("platform", c.platform) })}
              </Button>
            ))}
            <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label={t("csv file")} />
            <Button size="sm" variant="outline" icon={<Upload className="h-3.5 w-3.5" />} loading={busy === "csv"} onClick={() => file.current?.click()}>
              {t("Upload CSV")}
            </Button>
          </div>
          <Button variant="accent" icon={<Lightbulb className="h-4 w-4" />} loading={busy === "insights"} onClick={gen} disabled={!m?.rows}>
            {t("Generate insights")}
          </Button>
        </div>
        <div className="mt-2 text-[11.5px] text-espresso-400">{t("CSV columns: {columns} · connectors run against a deterministic simulator — all numbers are synthetic.", { columns: (connectors.data?.csv_columns ?? []).join(", ") })}</div>
      </Card>
      {metrics.isLoading && <Skeleton h={260} />}
      {m && !m.rows && <Empty title={t("No performance data yet")} hint={t("Sync a connector or upload a CSV to see metrics.")} />}
      {tot && (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="perf-stats">
            <Stat label={t("Impressions")} value={fmt.number(tot.impressions)} />
            <Stat label="CTR" value={fmt.pct(tot.ctr * 100, 2)} />
            <Stat label="VTR" value={tot.vtr != null ? fmt.pct(tot.vtr * 100, 1) : "—"} />
            <Stat label="CVR" value={tot.cvr != null ? fmt.pct(tot.cvr * 100, 2) : "—"} />
            <Stat label="CPA" value={fmt.usd(tot.cpa)} />
            <Stat label="ROAS" value={tot.roas != null ? `${fmt.fixed(tot.roas, 2)}×` : "—"} tone="dawn" />
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2" title={t("Daily trend")} subtitle={t("{rows} · sources: {sources}", { rows: tn(m.rows, { one: "{n} row", other: "{n} rows" }), sources: m.sources.map(sourceLabel).join(", ") })}>
              <div className="h-60">
                <ResponsiveContainer>
                  <LineChart data={m.by_day}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="key" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.isoDate(v)} />
                    <YAxis yAxisId="l" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.number(+v)} />
                    <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.percent(+v, 1)} />
                    <Tooltip formatter={(v: any, name: any) => (name === "CTR" ? fmt.percent(+v, 2) : fmt.number(+v))} labelFormatter={(l: any) => fmt.isoDate(String(l))} />
                    <Line yAxisId="l" type="monotone" dataKey="impressions" name={t("Impressions")} stroke="#2b1a12" dot={false} strokeWidth={2} />
                    <Line yAxisId="l" type="monotone" dataKey="conversions" name={t("Conversions")} stroke="#5c7a5e" dot={false} strokeWidth={2} />
                    <Line yAxisId="r" type="monotone" dataKey="ctr" name="CTR" stroke="#d9822b" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title={t("What works")} subtitle={t("Written back to the Brand Brain")} testId="insights">
              <ul className="space-y-2.5 text-[13px]">
                {(insights.data?.insights ?? []).slice(0, 6).map((i: any) => (
                  <li key={i.id} className="rounded-lg bg-cream-100 px-3 py-2">
                    {i.statement}
                    <div className="mt-0.5 text-[11.5px] text-espresso-400">{t("confidence {pct}% · {basis}", { pct: String(Math.round(i.confidence * 100)), basis: i.evidence?.synthetic_history ? t("synthetic history") : t("from this data") })}</div>
                  </li>
                ))}
                {!(insights.data?.insights ?? []).length && <li className="text-espresso-400">{t("Generate insights to see significant lifts.")}</li>}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title={t("By {group}", { group: tEnum("groupBy", m.group_by) })} pad={false}>
            <div className="p-3">
              <Table
                head={[tEnum("groupBy", m.group_by), t("Impr."), "CTR", "VTR", "CVR", "CPA", "ROAS", t("Spend")]}
                rows={m.groups.map((g: any) => [<b key="k">{groupKey(m.group_by, g.key)}</b>, fmt.number(g.impressions), fmt.pct((g.ctr ?? 0) * 100, 2), g.vtr != null ? fmt.pct(g.vtr * 100, 1) : "—", g.cvr != null ? fmt.pct(g.cvr * 100, 2) : "—", fmt.usd(g.cpa), g.roas != null ? `${fmt.fixed(g.roas, 2)}×` : "—", fmt.usd(g.spend, 0)])}
              />
            </div>
          </Card>
          {fresh && fresh.length > 0 && (
            <Card className="mt-5" title={t("Fresh insights")} subtitle={t("Each carries its statistics")}>
              <ul className="space-y-2 text-[13px]">
                {fresh.map((i, k) => (
                  <li key={k}>
                    <Badge tone={i.confidence > 0.8 ? "good" : "warn"}>{fmt.pct(i.confidence * 100, 0)}</Badge> {i.statement}
                  </li>
                ))}
              </ul>
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
  nav: { group: "Performance", label: msg("Insights"), to: "/performance", order: 20, icon: BarChart3 },
};
