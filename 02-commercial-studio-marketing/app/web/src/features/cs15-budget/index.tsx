/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Gauge, ShieldAlert } from "lucide-react";
import { api, fmtDate, fmtUsd } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Input, Meter, PageHeader, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";

const KIND_COLOR: Record<string, string> = { llm: "#2b1a12", image: "#d9822b", tts: "#b5452b", embedding: "#5c7a5e", safety: "#7a8fa6", render: "#a9895f" };

function CostPage() {
  const toast = useToast();
  const q = useQuery({ queryKey: ["budget"], queryFn: () => api.get("/api/budget"), refetchInterval: 10000 });
  const ev = useQuery({ queryKey: ["budget-events"], queryFn: () => api.get("/api/budget/events?limit=14"), refetchInterval: 10000 });
  const [cap, setCap] = useState("");
  const d = q.data;
  const kinds = d ? Object.entries(d.today.by_kind).map(([k, v]: any) => ({ k, cost: v.cost_usd, calls: v.calls })) : [];
  const pct = d ? (d.caps.spent_today_usd / d.caps.daily_cap_usd) * 100 : 0;
  const saveCap = async () => {
    await api.put("/api/budget/caps", { daily_cap_usd: +cap });
    toast({ tone: "good", title: "Daily AI cap updated" });
    setCap("");
    q.refetch();
  };
  const campCap = async (id: string, v: number) => {
    await api.put(`/api/campaigns/${id}/budget`, { cap_usd: v });
    q.refetch();
  };
  const premium = async (id: string, approved: boolean) => {
    await api.post(`/api/campaigns/${id}/premium`, { approved, note: "approved from cost meter" });
    toast({ tone: "good", title: approved ? "Premium (hero-quality) generation approved" : "Premium generation revoked" });
    q.refetch();
  };
  return (
    <div>
      <PageHeader eyebrow="CS-15 · Budget & cost guardrails" title="Cost meter" subtitle="Every token, image, voice-over character and render is metered and priced. Daily and per-campaign caps fail closed — generation stops with a clear message instead of overspending." />
      {!d ? <Skeleton h={300} /> : (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <Stat label="AI spend today (UTC)" value={fmtUsd(d.caps.spent_today_usd, 3)} hint={<><Meter value={d.caps.spent_today_usd} max={d.caps.daily_cap_usd} /><div className="mt-1">of {fmtUsd(d.caps.daily_cap_usd)} daily cap · {pct.toFixed(1)}%</div></>} />
            <Stat label="Metered calls" value={d.today.events} hint={`${d.today.cached_hits} served from prompt cache (no spend)`} />
            <Stat label="Cost per approved asset" value={d.kpi.cost_per_approved_asset_usd != null ? fmtUsd(d.kpi.cost_per_approved_asset_usd, 3) : "—"} tone="good" hint={`vs agency baseline ${fmtUsd(d.kpi.agency_baseline_per_asset_usd, 0)}${d.kpi.savings_pct != null ? ` · ${d.kpi.savings_pct}%` : ""}`} />
            <Stat label="Guard" value={<span className="flex items-center gap-2 text-[22px]"><ShieldAlert className="h-5 w-5 text-sage-600" /> active</span>} hint={`fails closed · ${d.guard.refusals} refusal(s) since start · hard max ${fmtUsd(d.guard.hard_max_daily_usd, 0)}/day`} />
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card title="Spend by service today" subtitle={d.today.pricing_note} className="lg:col-span-2">
              <div className="h-56" data-testid="cost-chart">
                <ResponsiveContainer>
                  <BarChart data={kinds}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="k" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                    <Tooltip formatter={(v: any, _n: any, p: any) => [`${fmtUsd(v, 4)} · ${p.payload.calls} calls`, "cost"]} />
                    <Bar dataKey="cost" radius={[6, 6, 0, 0]}>{kinds.map((e) => <Cell key={e.k} fill={KIND_COLOR[e.k] ?? "#a9895f"} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-1 text-[11.5px] text-espresso-400">Prices as of {d.today.prices_as_of}{d.simulated_prices ? " — offline stubs record SIMULATED costs at the same list prices" : " — real calls, list-price estimates"}.</div>
            </Card>
            <Card title="Daily cap" subtitle="Admin only — hard maximum $50">
              <div className="flex items-center gap-2">
                <Input type="number" min={0.5} max={50} step={0.5} placeholder={`${d.caps.daily_cap_usd}`} value={cap} onChange={(e) => setCap(e.target.value)} aria-label="daily cap" />
                <Button variant="outline" disabled={!cap} onClick={saveCap}>Set</Button>
              </div>
              <ul className="mt-3 space-y-1 text-[12.5px] text-espresso-600">
                {Object.entries(d.today.by_feature).map(([k, v]: any) => <li key={k} className="flex justify-between"><span>{k}</span><span className="tabular-nums">{fmtUsd(v, 4)}</span></li>)}
              </ul>
            </Card>
          </div>
          <Card className="mt-5" title="Campaign budgets" subtitle="Per-campaign cap · premium (hero quality ≈ $0.20/image) needs an explicit approval" pad={false}>
            <div className="p-3">
              <Table
                head={["Campaign", "Spent / cap", "", "Approved assets", "$ / approved asset", "Premium", "Cap"]}
                rows={d.campaigns.map((c: any) => [
                  <b key="n">{c.name}</b>,
                  `${fmtUsd(c.spent_usd, 3)} / ${fmtUsd(c.cap_usd)}`,
                  <div key="m" className="w-28"><Meter value={c.spent_usd} max={c.cap_usd} /></div>,
                  c.approved_assets,
                  c.cost_per_approved_asset_usd != null ? `${fmtUsd(c.cost_per_approved_asset_usd, 3)} (${c.savings_pct}% vs agency)` : "—",
                  <button key="p" onClick={() => premium(c.campaign_id, !c.premium_approved)} className="hover:opacity-80"><Badge tone={c.premium_approved ? "warn" : "neutral"}>{c.premium_approved ? "approved — revoke" : "not approved"}</Badge></button>,
                  <select key="c" defaultValue="" onChange={(e) => e.target.value && campCap(c.campaign_id, +e.target.value)} className="rounded border border-cream-300 bg-white px-1.5 py-1 text-[12px]" aria-label="campaign cap">
                    <option value="">change…</option>{[1, 2, 3, 5].map((v) => <option key={v} value={v}>${v}</option>)}
                  </select>,
                ])}
              />
            </div>
          </Card>
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <Card title="Recent metered calls" pad={false}>
              <div className="p-3">
                <Table head={["Time", "Service", "Model", "Feature", "Cost"]} rows={(ev.data?.events ?? []).map((e: any) => [fmtDate(e.at ?? e.ts), <Badge key="k">{e.kind}</Badge>, <span key="m" className="text-espresso-500">{e.model}</span>, e.feature ?? "—", <span key="c" className="tabular-nums">{e.cached ? <Badge tone="good">cached</Badge> : fmtUsd(e.cost_usd, 4)}</span>])} />
              </div>
            </Card>
            <Card title="Price table" subtitle="Per 1M tokens / per image / per 1M characters (estimates)">
              <div className="max-h-72 overflow-auto text-[12.5px]">
                <table className="w-full"><tbody>
                  {Object.entries(d.pricing.llm_per_mtok).map(([k, v]: any) => <tr key={k} className="border-b border-cream-200"><td className="py-1">{k}</td><td className="text-right tabular-nums">in {v.input} · out {v.output}</td></tr>)}
                  {Object.entries(d.pricing.image_per_image).map(([k, v]: any) => <tr key={k} className="border-b border-cream-200"><td className="py-1">{k}</td><td className="text-right tabular-nums">${v}</td></tr>)}
                  {Object.entries(d.pricing.tts_per_mchar).map(([k, v]: any) => <tr key={k} className="border-b border-cream-200"><td className="py-1">tts {k}</td><td className="text-right tabular-nums">${v}</td></tr>)}
                </tbody></table>
              </div>
              <div className="mt-2 text-[11.5px] text-espresso-400">{d.pricing.note}</div>
            </Card>
          </div>
          {d.alerts.length > 0 && <Card className="mt-5" title="Budget alerts"><ul className="text-[13px]">{d.alerts.map((a: any, i: number) => <li key={i}><StatusBadge s="warn" /> {JSON.stringify(a.payload)}</li>)}</ul></Card>}
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-15",
  routes: [{ path: "/cost", element: <CostPage /> }],
  nav: { group: "Operate", label: "Cost meter", to: "/cost", order: 10, icon: Gauge },
};
