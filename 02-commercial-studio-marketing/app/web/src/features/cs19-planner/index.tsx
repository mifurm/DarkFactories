/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Compass } from "lucide-react";
import { api, fmtNum, fmtPct, fmtUsd } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, PageHeader, Select, Skeleton, Stat, Table } from "../../components/ui";

const COLORS = ["#2b1a12", "#d9822b", "#b5452b", "#5c7a5e", "#7a8fa6", "#a9895f", "#c9a227", "#8b5e83"];

function PlannerPage() {
  const ch = useQuery({ queryKey: ["planner-channels"], queryFn: () => api.get("/api/planner/channels"), staleTime: 600000 });
  const [budget, setBudget] = useState(400000);
  const [objective, setObjective] = useState("roas");
  const [minShare, setMinShare] = useState(0);
  const [picked, setPicked] = useState<string[]>([]);
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const channels = Object.keys(ch.data?.channels ?? {});
  useEffect(() => {
    if (channels.length && !picked.length) setPicked(channels);
  }, [channels.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setBusy(true);
    try {
      setPlan(await api.post("/api/planner/plan", { budget_usd: budget, objective, channels: picked, min_share: minShare }));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (picked.length && !plan) run();
  }, [picked.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const alloc: any[] = plan?.allocation ?? [];
  return (
    <div>
      <PageHeader eyebrow="CS-19 · Campaign planner & media-mix hints" title="Media planner" subtitle="Recommended channel split from diminishing-returns response curves: spend moves to the channel with the highest marginal ROAS until marginal returns equalise. Ranges come from Monte-Carlo over the curve parameters." />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Media budget (USD)"><Input type="number" min={5000} step={5000} value={budget} onChange={(e) => setBudget(+e.target.value)} className="w-40" aria-label="budget" /></Field>
          <Field label="Objective"><Select value={objective} onChange={(e) => setObjective(e.target.value)} className="w-40" aria-label="objective"><option value="roas">Max ROAS</option><option value="reach">Max reach</option><option value="conversions">Max conversions</option></Select></Field>
          <Field label={`Min. share per channel: ${Math.round(minShare * 100)}%`}><input type="range" min={0} max={0.15} step={0.01} value={minShare} onChange={(e) => setMinShare(+e.target.value)} aria-label="min share" /></Field>
          <div className="flex flex-wrap gap-1.5">{channels.map((c) => <button key={c} aria-pressed={picked.includes(c)} onClick={() => setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]))} className={`rounded-full border px-2.5 py-0.5 text-[12px] ${picked.includes(c) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300 bg-white"}`}>{c}</button>)}</div>
          <Button variant="accent" icon={<Compass className="h-4 w-4" />} loading={busy} disabled={picked.length < 1} onClick={run}>Recommend split</Button>
        </div>
      </Card>
      {!plan && <Skeleton h={260} />}
      {plan && (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4" data-testid="plan-stats">
            <Stat label="Expected ROAS (p50)" value={`${plan.ranges.roas_p50}×`} hint={`p10–p90: ${plan.ranges.roas_p10}× – ${plan.ranges.roas_p90}×`} tone="dawn" />
            <Stat label="Expected revenue" value={fmtUsd(plan.totals.revenue, 0)} hint={`on ${fmtUsd(plan.totals.spend, 0)}`} />
            <Stat label="Conversions" value={fmtNum(plan.totals.conversions)} hint={`p10–p90: ${fmtNum(plan.ranges.conversions_p10)} – ${fmtNum(plan.ranges.conversions_p90)}`} />
            <Stat label="vs uniform split" value={plan.vs_uniform_split.uplift_pct != null ? `${plan.vs_uniform_split.uplift_pct > 0 ? "+" : ""}${plan.vs_uniform_split.uplift_pct}%` : "—"} tone="good" hint="revenue uplift of the optimised mix" />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Recommended budget split">
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={alloc} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid stroke="#efe6d8" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Math.round(v / 1000)}k`} />
                    <YAxis type="category" dataKey="channel" tick={{ fontSize: 12 }} width={90} />
                    <Tooltip formatter={(v: any) => fmtUsd(v, 0)} />
                    <Bar dataKey="spend" radius={[0, 6, 6, 0]}>{alloc.map((a, i) => <Cell key={a.channel} fill={COLORS[i % COLORS.length]} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Marginal ROAS" subtitle="At the optimum the marginal return is roughly equal across channels with spend">
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={alloc}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="channel" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="roas" name="avg ROAS" fill="#2b1a12" radius={[6, 6, 0, 0]} />
                    <Bar dataKey="marginal_roas" name="marginal ROAS" fill="#d9822b" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
          <Card className="mt-5" title="Allocation detail" pad={false}>
            <div className="p-3">
              <Table
                head={["Channel", "Spend", "Share", "Impressions", "Reach", "Conversions", "Revenue", "ROAS", "Saturation"]}
                rows={alloc.map((a) => [<b key="c">{a.channel}</b>, fmtUsd(a.spend, 0), fmtPct(a.share * 100, 1), `${a.impressions_m} M`, `${a.reach_m} M`, fmtNum(a.conversions), fmtUsd(a.revenue, 0), a.roas != null ? `${a.roas}×` : "—", fmtPct(a.saturation * 100, 0)])}
              />
            </div>
          </Card>
          <div className="mt-3 flex items-start gap-2 text-[12px] text-espresso-500"><Badge tone="warn">illustrative</Badge> {plan.note}</div>
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-19",
  routes: [{ path: "/planner", element: <PlannerPage /> }],
  nav: { group: "Performance", label: "Media planner", to: "/planner", order: 30, icon: Compass },
};
