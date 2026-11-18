/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Gauge, ShieldAlert } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Input, Meter, PageHeader, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";
import { msg, useI18n } from "../../i18n";

const KIND_COLOR: Record<string, string> = { llm: "#2b1a12", image: "#d9822b", tts: "#b5452b", embedding: "#5c7a5e", safety: "#7a8fa6", render: "#a9895f", motion: "#7a5c8a" };
// English constant the API returns verbatim; tKnown() translates it in a non-English UI when the server did not localize it.
const KNOWN_SERVER_TEXT = [msg("Estimated list prices (USD, pay-as-you-go, no discounts). Token prices: Azure Retail Prices API; per-image / per-character prices: public price lists. Validate against your Azure invoice.")];

function CostPage() {
  const { t, tn, tEnum, tOpen, fmt, tKnown, lang } = useI18n();
  // spend is attributed to a feature id (jobs: "CS-07") or to the campaign sub-resource that caused it ("guardian", "scorecard"): English keeps the raw value
  const featureName = (k: string) => (lang !== "en" && /^CS-\d\d$/.test(k) ? tEnum("feature", k) : tOpen("costFeature", k));
  const featureLabel = (k: string) => (lang !== "en" && /^CS-\d\d$/.test(k) ? `${k} · ${featureName(k)}` : tOpen("costFeature", k));
  const alertText = (p: any) => {
    const scope = String(p?.scope ?? "");
    const where = scope.startsWith("campaign:") ? t("campaign {id}", { id: scope.slice(9) }) : scope === "daily" ? t("daily cap") : scope;
    return t("{where}: {pct} of the cap reached — {spent} of {cap}", { where, pct: fmt.percent(p?.threshold, 0), spent: fmt.usd(p?.spent_usd, { min: 2, max: 4 }), cap: fmt.usd(p?.cap_usd, { min: 2, max: 4 }) });
  };
  const toast = useToast();
  const q = useQuery({ queryKey: ["budget"], queryFn: () => api.get("/api/budget"), refetchInterval: 10000 });
  const ev = useQuery({ queryKey: ["budget-events"], queryFn: () => api.get("/api/budget/events?limit=14"), refetchInterval: 10000 });
  const [cap, setCap] = useState("");
  const d = q.data;
  const kinds = d ? Object.entries(d.today.by_kind).map(([k, v]: any) => ({ k, label: tEnum("costKind", k), cost: v.cost_usd, calls: v.calls })) : [];
  const pct = d ? (d.caps.spent_today_usd / d.caps.daily_cap_usd) * 100 : 0;
  const saveCap = async () => {
    await api.put("/api/budget/caps", { daily_cap_usd: +cap });
    toast({ tone: "good", title: t("Daily AI cap updated") });
    setCap("");
    q.refetch();
  };
  const campCap = async (id: string, v: number) => {
    await api.put(`/api/campaigns/${id}/budget`, { cap_usd: v });
    q.refetch();
  };
  const premium = async (id: string, approved: boolean) => {
    await api.post(`/api/campaigns/${id}/premium`, { approved, note: "approved from cost meter" });
    toast({ tone: "good", title: approved ? t("Premium (hero-quality) generation approved") : t("Premium generation revoked") });
    q.refetch();
  };
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-15 · Budget & cost guardrails")}
        title={t("Cost meter")}
        subtitle={t("Every token, image, voice-over character and render is metered and priced. Daily and per-campaign caps fail closed — generation stops with a clear message instead of overspending.")}
      />
      {!d ? (
        <Skeleton h={300} />
      ) : (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <Stat
              label={t("AI spend today (UTC)")}
              value={fmt.usd(d.caps.spent_today_usd, 3)}
              hint={
                <>
                  <Meter value={d.caps.spent_today_usd} max={d.caps.daily_cap_usd} />
                  <div className="mt-1">{t("of {cap} daily cap · {pct}", { cap: fmt.usd(d.caps.daily_cap_usd), pct: fmt.pct(pct, 1) })}</div>
                </>
              }
            />
            <Stat label={t("Metered calls")} value={fmt.number(d.today.events)} hint={tn(d.today.cached_hits, { one: "{n} served from prompt cache (no spend)", other: "{n} served from prompt cache (no spend)" })} />
            <Stat
              label={t("Cost per approved asset")}
              value={d.kpi.cost_per_approved_asset_usd != null ? fmt.usd(d.kpi.cost_per_approved_asset_usd, 3) : "—"}
              tone="good"
              hint={t("vs agency baseline {baseline}{saving}", { baseline: fmt.usd(d.kpi.agency_baseline_per_asset_usd, 0), saving: d.kpi.savings_pct != null ? ` · ${fmt.number(d.kpi.savings_pct, 2)}%` : "" })}
            />
            <Stat
              label={t("Guard")}
              value={
                <span className="flex items-center gap-2 text-[22px]">
                  <ShieldAlert className="h-5 w-5 text-sage-600" /> {t("active")}
                </span>
              }
              hint={t("fails closed · {refusals} · hard max {max}/day", { refusals: tn(d.guard.refusals, { one: "{n} refusal(s) since start", other: "{n} refusal(s) since start" }), max: fmt.usd(d.guard.hard_max_daily_usd, 0) })}
            />
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card title={t("Spend by service today")} subtitle={tKnown(d.today.pricing_note)} className="lg:col-span-2">
              <div className="h-56" data-testid="cost-chart">
                <ResponsiveContainer>
                  <BarChart data={kinds}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => fmt.usd(v, { min: 0, max: 3 })} width={fmt.lang === "pl" ? 78 : 60} />
                    <Tooltip formatter={(v: any, _n: any, p: any) => [t("{amount} · {calls}", { amount: fmt.usd(v, 4), calls: tn(p.payload.calls, { one: "{n} call", other: "{n} calls" }) }), t("cost")]} />
                    <Bar dataKey="cost" name={t("cost")} radius={[6, 6, 0, 0]}>
                      {kinds.map((e) => (
                        <Cell key={e.k} fill={KIND_COLOR[e.k] ?? "#a9895f"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-1 text-[11.5px] text-espresso-400">
                {d.simulated_prices ? t("Prices as of {date} — offline stubs record SIMULATED costs at the same list prices.", { date: fmt.isoDate(d.today.prices_as_of) }) : t("Prices as of {date} — real calls, list-price estimates.", { date: fmt.isoDate(d.today.prices_as_of) })}
              </div>
            </Card>
            <Card title={t("Daily cap")} subtitle={t("Admin only — hard maximum $50")}>
              <div className="flex items-center gap-2">
                <Input type="number" min={0.5} max={50} step={0.5} placeholder={`${d.caps.daily_cap_usd}`} value={cap} onChange={(e) => setCap(e.target.value)} aria-label={t("daily cap")} />
                <Button variant="outline" disabled={!cap} onClick={saveCap}>
                  {t("Set")}
                </Button>
              </div>
              <ul className="mt-3 space-y-1 text-[12.5px] text-espresso-600">
                {Object.entries(d.today.by_feature).map(([k, v]: any) => (
                  <li key={k} className="flex justify-between">
                    <span>{featureLabel(k)}</span>
                    <span className="tabular-nums">{fmt.usd(v, 4)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title={t("Campaign budgets")} subtitle={t("Per-campaign cap · premium (hero quality ≈ $0.20/image) needs an explicit approval")} pad={false}>
            <div className="p-3">
              <Table
                head={[t("Campaign"), t("Spent / cap"), "", t("Approved assets"), t("$ / approved asset"), t("Premium"), t("Cap")]}
                rows={d.campaigns.map((c: any) => [
                  <b key="n">{c.name}</b>,
                  `${fmt.usd(c.spent_usd, 3)} / ${fmt.usd(c.cap_usd)}`,
                  <div key="m" className="w-28">
                    <Meter value={c.spent_usd} max={c.cap_usd} />
                  </div>,
                  c.approved_assets,
                  c.cost_per_approved_asset_usd != null ? t("{amount} ({pct}% vs agency)", { amount: fmt.usd(c.cost_per_approved_asset_usd, 3), pct: fmt.number(c.savings_pct, 2) }) : "—",
                  <button key="p" onClick={() => premium(c.campaign_id, !c.premium_approved)} className="hover:opacity-80">
                    <Badge tone={c.premium_approved ? "warn" : "neutral"}>{c.premium_approved ? t("approved — revoke") : t("not approved")}</Badge>
                  </button>,
                  <select key="c" defaultValue="" onChange={(e) => e.target.value && campCap(c.campaign_id, +e.target.value)} className="rounded border border-cream-300 bg-white px-1.5 py-1 text-[12px]" aria-label={t("campaign cap")}>
                    <option value="">{t("change…")}</option>
                    {[1, 2, 3, 5].map((v) => (
                      <option key={v} value={v}>
                        {fmt.usd(v, 0)}
                      </option>
                    ))}
                  </select>,
                ])}
              />
            </div>
          </Card>
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <Card title={t("Recent metered calls")} pad={false}>
              <div className="p-3">
                <Table
                  head={[t("Time"), t("Service"), t("Model"), t("Feature"), t("Cost")]}
                  rows={(ev.data?.events ?? []).map((e: any) => [
                    fmt.dateTime(e.at ?? e.ts),
                    <Badge key="k">{tEnum("costKind", e.kind)}</Badge>,
                    <span key="m" className="text-espresso-500">
                      {e.model}
                    </span>,
                    e.feature ? <span key="f" title={lang !== "en" ? featureName(e.feature) : undefined}>{tOpen("costFeature", e.feature)}</span> : "—",
                    <span key="c" className="tabular-nums">
                      {e.cached ? <Badge tone="good">{t("cached")}</Badge> : fmt.usd(e.cost_usd, 4)}
                    </span>,
                  ])}
                />
              </div>
            </Card>
            <Card title={t("Price table")} subtitle={t("Per 1M tokens / per image / per 1M characters (estimates)")}>
              <div className="max-h-72 overflow-auto text-[12.5px]">
                <table className="w-full">
                  <tbody>
                    {Object.entries(d.pricing.llm_per_mtok).map(([k, v]: any) => (
                      <tr key={k} className="border-b border-cream-200">
                        <td className="py-1">{k}</td>
                        <td className="text-right tabular-nums">{t("in {in} · out {out}", { in: fmt.number(v.input, 4), out: fmt.number(v.output, 4) })}</td>
                      </tr>
                    ))}
                    {Object.entries(d.pricing.image_per_image).map(([k, v]: any) => (
                      <tr key={k} className="border-b border-cream-200">
                        <td className="py-1">{k}</td>
                        <td className="text-right tabular-nums">{fmt.usd(v, { min: 0, max: 4 })}</td>
                      </tr>
                    ))}
                    {Object.entries(d.pricing.tts_per_mchar).map(([k, v]: any) => (
                      <tr key={k} className="border-b border-cream-200">
                        <td className="py-1">{t("tts {name}", { name: tOpen("ttsTier", k) })}</td>
                        <td className="text-right tabular-nums">{fmt.usd(v, { min: 0, max: 4 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 text-[11.5px] text-espresso-400">{tKnown(d.pricing.note)}</div>
            </Card>
          </div>
          {d.alerts.length > 0 && (
            <Card className="mt-5" title={t("Budget alerts")}>
              <ul className="text-[13px]">
                {d.alerts.map((a: any, i: number) => (
                  <li key={i}>
                    <StatusBadge s="warn" /> {lang === "en" ? JSON.stringify(a.payload) : alertText(a.payload)}
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
  id: "CS-15",
  routes: [{ path: "/cost", element: <CostPage /> }],
  nav: { group: "Operate", label: msg("Cost meter"), to: "/cost", order: 10, icon: Gauge },
};
