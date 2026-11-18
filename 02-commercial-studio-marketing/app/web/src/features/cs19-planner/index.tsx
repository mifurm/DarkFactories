/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Compass } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, PageHeader, Select, Skeleton, Stat, Table } from "../../components/ui";
import { msg, useI18n, useOnLangChange } from "../../i18n";

const COLORS = ["#2b1a12", "#d9822b", "#b5452b", "#5c7a5e", "#7a8fa6", "#a9895f", "#c9a227", "#8b5e83"];
// English constant the API returns verbatim; tKnown() translates it in a non-English UI when the server did not localize it.
const KNOWN_SERVER_TEXT = [msg("ILLUSTRATIVE: diminishing-returns curves with assumed parameters; calibrate with your own performance data (CS-18) before using for decisions.")];

function PlannerPage() {
  const { t, tOpen, fmt, tKnown } = useI18n();
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
  useOnLangChange(() => {
    if (plan) run(); // the plan note is rendered by the server in the request language
  });
  const alloc: any[] = (plan?.allocation ?? []).map((a: any) => ({ ...a, label: tOpen("channel", a.channel) }));
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-19 · Campaign planner & media-mix hints")}
        title={t("Media planner")}
        subtitle={t("Recommended channel split from diminishing-returns response curves: spend moves to the channel with the highest marginal ROAS until marginal returns equalise. Ranges come from Monte-Carlo over the curve parameters.")}
      />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Media budget (USD)")}>
            <Input type="number" min={5000} step={5000} value={budget} onChange={(e) => setBudget(+e.target.value)} className="w-40" aria-label={t("budget")} />
          </Field>
          <Field label={t("Objective")}>
            <Select value={objective} onChange={(e) => setObjective(e.target.value)} className="w-44" aria-label={t("objective")}>
              <option value="roas">{t("Max ROAS")}</option>
              <option value="reach">{t("Max reach")}</option>
              <option value="conversions">{t("Max conversions")}</option>
            </Select>
          </Field>
          <Field label={t("Min. share per channel: {pct}", { pct: fmt.percent(minShare, 0) })}>
            <input type="range" min={0} max={0.15} step={0.01} value={minShare} onChange={(e) => setMinShare(+e.target.value)} aria-label={t("min share")} />
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {channels.map((c) => (
              <button key={c} aria-pressed={picked.includes(c)} onClick={() => setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]))} className={`rounded-full border px-2.5 py-0.5 text-[12px] ${picked.includes(c) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300 bg-white"}`}>
                {tOpen("channel", c)}
              </button>
            ))}
          </div>
          <Button variant="accent" icon={<Compass className="h-4 w-4" />} loading={busy} disabled={picked.length < 1} onClick={run}>
            {t("Recommend split")}
          </Button>
        </div>
      </Card>
      {!plan && <Skeleton h={260} />}
      {plan && (
        <>
          <div className="mb-5 grid gap-3 md:grid-cols-4" data-testid="plan-stats">
            <Stat label={t("Expected ROAS (p50)")} value={`${fmt.number(plan.ranges.roas_p50, 2)}×`} hint={t("p10–p90: {lo}× – {hi}×", { lo: fmt.number(plan.ranges.roas_p10, 2), hi: fmt.number(plan.ranges.roas_p90, 2) })} tone="dawn" />
            <Stat label={t("Expected revenue")} value={fmt.usd(plan.totals.revenue, 0)} hint={t("on {amount}", { amount: fmt.usd(plan.totals.spend, 0) })} />
            <Stat label={t("Conversions")} value={fmt.number(plan.totals.conversions)} hint={t("p10–p90: {lo} – {hi}", { lo: fmt.number(plan.ranges.conversions_p10), hi: fmt.number(plan.ranges.conversions_p90) })} />
            <Stat label={t("vs uniform split")} value={plan.vs_uniform_split.uplift_pct != null ? `${plan.vs_uniform_split.uplift_pct > 0 ? "+" : ""}${fmt.number(plan.vs_uniform_split.uplift_pct, 2)}%` : "—"} tone="good" hint={t("revenue uplift of the optimised mix")} />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title={t("Recommended budget split")}>
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={alloc} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid stroke="#efe6d8" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.compactUsd(v)} />
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 12 }} width={90} />
                    <Tooltip formatter={(v: any) => fmt.usd(v, 0)} />
                    <Bar dataKey="spend" name={t("Spend")} radius={[0, 6, 6, 0]}>
                      {alloc.map((a, i) => (
                        <Cell key={a.channel} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title={t("Marginal ROAS")} subtitle={t("At the optimum the marginal return is roughly equal across channels with spend")}>
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={alloc}>
                    <CartesianGrid stroke="#efe6d8" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.number(+v, 2)} />
                    <Tooltip formatter={(v: any) => fmt.number(+v, 3)} />
                    <Bar dataKey="roas" name={t("avg ROAS")} fill="#2b1a12" radius={[6, 6, 0, 0]} />
                    <Bar dataKey="marginal_roas" name={t("marginal ROAS")} fill="#d9822b" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
          <Card className="mt-5" title={t("Allocation detail")} pad={false}>
            <div className="p-3">
              <Table
                head={[t("Channel"), t("Spend"), t("Share"), t("Impressions"), t("Reach"), t("Conversions"), t("Revenue"), "ROAS", t("Saturation")]}
                rows={alloc.map((a) => [<b key="c">{a.label}</b>, fmt.usd(a.spend, 0), fmt.pct(a.share * 100, 1), t("{n} M", { n: a.impressions_m }), t("{n} M", { n: a.reach_m }), fmt.number(a.conversions), fmt.usd(a.revenue, 0), a.roas != null ? `${fmt.number(a.roas, 2)}×` : "—", fmt.pct(a.saturation * 100, 0)])}
              />
            </div>
          </Card>
          <div className="mt-3 flex items-start gap-2 text-[12px] text-espresso-500">
            <Badge tone="warn">{t("illustrative")}</Badge> {tKnown(plan.note)}
          </div>
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-19",
  routes: [{ path: "/planner", element: <PlannerPage /> }],
  nav: { group: "Performance", label: msg("Media planner"), to: "/planner", order: 30, icon: Compass },
};
