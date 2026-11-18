/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FlaskConical, Play, RotateCcw } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Meter, PageHeader, Select, Skeleton, StatusBadge, useToast } from "../../components/ui";
import { msg, useI18n, useLocalizedDefault, useOnLangChange } from "../../i18n";

const TD = "px-1.5 py-[3px]";

// The option values are stable ids sent to the API (the simulator and the scorecard key their effects on them); only their labels are localized.
const DIMS: Record<string, string[]> = {
  hook: ["Human moment first", "Product first", "Question hook", "Sensory close-up"],
  cta: ["Find it near you", "Try it today", "Learn more"],
  visual: ["Warm kitchen", "Macro pour", "Street at dawn"],
};
const DEFAULT_SEL: Record<string, string[]> = { hook: ["Human moment first", "Product first", "Question hook"], cta: ["Find it near you", "Try it today"], visual: ["Warm kitchen", "Macro pour"] };
const COLORS = ["#2b1a12", "#d9822b", "#b5452b", "#5c7a5e", "#7a8fa6", "#a9895f", "#c9a227", "#8b5e83", "#3f7f93", "#e07a5f", "#81b29a", "#9c6644", "#6d597a", "#b56576", "#355070", "#eaac8b"];

function Tile({ label, value, hint, valueClass = "text-[24px] leading-none" }: { label: string; value: ReactNode; hint?: ReactNode; valueClass?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-cream-300 bg-white px-4 py-2.5">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-espresso-500">{label}</div>
      <div className={`mt-1 font-display font-semibold ${valueClass}`}>{value}</div>
      {hint && <div className="mt-1 text-[12px] leading-snug text-espresso-500">{hint}</div>}
    </div>
  );
}

function ExperimentsPage() {
  const { t, tn, tEnum, tOpen, fmt } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const camps = useQuery({ queryKey: ["campaigns"], queryFn: () => api.get("/api/campaigns") });
  const list = useQuery({ queryKey: ["experiments"], queryFn: () => api.get("/api/experiments") });
  const [sel, setSel] = useState<string>("");
  const exp = useQuery({ queryKey: ["experiment", sel], enabled: !!sel, queryFn: () => api.get(`/api/experiments/${sel}`), refetchInterval: false });
  const [campaign, setCampaign] = useState("");
  const [name, setName] = useLocalizedDefault((i) => i.t("Dawn Roast variant test"));
  const [dims, setDims] = useState<Record<string, string[]>>(DEFAULT_SEL);
  const [hours, setHours] = useState(24);
  const [strategy, setStrategy] = useState("thompson");
  const [busy, setBusy] = useState<string | null>(null);
  const [rank, setRank] = useState<any>(null);
  useEffect(() => {
    if (!campaign && camps.data?.length) setCampaign(camps.data[0].id);
  }, [camps.data, campaign]);
  useEffect(() => {
    if (!sel && list.data?.length) setSel(list.data[0].id);
  }, [list.data, sel]);
  const n = Object.values(dims).reduce((a, v) => a * v.length, 1);
  const toggle = (k: string, v: string) => setDims((d) => ({ ...d, [k]: d[k].includes(v) ? d[k].filter((x) => x !== v) : [...d[k], v] }));
  const create = async () => {
    setBusy("create");
    try {
      const e = await api.post("/api/experiments", { campaign_id: campaign, name, dimensions: dims });
      toast({ tone: "good", title: tn(e.variants.length, { one: "Experiment created with {n} variants", other: "Experiment created with {n} variants" }) });
      qc.setQueryData(["experiment", e.id], e); // the create response is the full view: show the new experiment at once, no loading skeleton
      await list.refetch();
      setSel(e.id);
    } finally {
      setBusy(null);
    }
  };
  const act = async (kind: "simulate" | "reset" | "preflight") => {
    setBusy(kind);
    try {
      if (kind === "simulate") await api.post(`/api/experiments/${sel}/simulate`, { hours, strategy });
      if (kind === "reset") await api.post(`/api/experiments/${sel}/reset`);
      if (kind === "preflight") setRank(await api.post(`/api/experiments/${sel}/preflight`));
      await exp.refetch();
      list.refetch();
    } finally {
      setBusy(null);
    }
  };
  useOnLangChange(() => {
    if (rank && sel) act("preflight"); // the ranking texts are rendered by the server in the request language
  });
  const e = exp.data;
  const hist = useMemo(() => (e?.history ?? []).map((h: any) => ({ hour: h.hour, ...h.shares })), [e]);
  const variants: any[] = useMemo(() => [...(e?.variants ?? [])].sort((a, b) => (b.p_best ?? 0) - (a.p_best ?? 0) || b.post_mean_ctr - a.post_mean_ctr), [e]);
  const sigBy: Record<string, any> = useMemo(() => Object.fromEntries((e?.significance ?? []).map((s: any) => [s.variant_id, s])), [e]);
  const leaderSig = e?.leader ? sigBy[e.leader.id] : undefined;
  const pausedHours: number[] = useMemo(() => (e?.variants ?? []).filter((v: any) => v.status === "paused").map((v: any) => v.paused_at_hour), [e]);
  const fmtP = (p: number) => (p < 0.001 ? `< ${fmt.number(0.001, 3)}` : fmt.fixed(p, 3));
  /** "Human moment first · Find it near you · Warm kitchen" in the UI language, composed from the variant's stable option ids */
  const labelOf = (v: any) => (v?.attrs ? ["hook", "cta", "visual"].map((k) => tOpen("variantOption", v.attrs[k])).join(" · ") : v?.label);
  const variantById = (vid: string) => (e?.variants ?? []).find((x: any) => x.id === vid);
  const rationaleOf = (r: any) => {
    const m = /^simulated panel: hook=(.+), cta=(.+), visual=(.+)$/.exec(r.rationale ?? "");
    return m ? t("simulated panel: hook={hook}, cta={cta}, visual={visual}", { hook: tOpen("variantOption", m[1]), cta: tOpen("variantOption", m[2]), visual: tOpen("variantOption", m[3]) }) : r.rationale;
  };
  const head = [t("Variant"), t("Status"), t("Impr."), t("CTR"), t("P(best)"), t("Share"), "z", "p", t("Sig. (5%)")];
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-17 · Variants & experimentation")}
        title={t("Variant engine")}
        subtitle={t("Build a hook × CTA × visual matrix, rank it pre-flight, then let Thompson sampling shift budget to the winners hour by hour against the SIMULATED ad platform — losers are auto-paused, significance is tested.")}
      />
      <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
        <div className="min-w-0 space-y-5">
          <Card title={t("New experiment")} subtitle={tn(n, { one: "{n} variant in the matrix", other: "{n} variants in the matrix" })}>
            <div className="space-y-3">
              <Field label={t("Campaign")}>
                <Select value={campaign} onChange={(x) => setCampaign(x.target.value)} aria-label={t("campaign")}>
                  {(camps.data ?? []).map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("Name")}>
                <Input value={name} onChange={(x) => setName(x.target.value)} />
              </Field>
              {Object.entries(DIMS).map(([k, vals]) => (
                <div key={k}>
                  <div className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-espresso-500">{tEnum("variantDim", k)}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {vals.map((v) => (
                      <button key={v} onClick={() => toggle(k, v)} aria-pressed={dims[k].includes(v)} className={`rounded-full border px-2.5 py-0.5 text-[12px] ${dims[k].includes(v) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300 bg-white"}`}>
                        {tEnum("variantOption", v)}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <Button variant="accent" icon={<FlaskConical className="h-4 w-4" />} disabled={!campaign || n < 2 || n > 48 || Object.values(dims).some((v) => !v.length)} loading={busy === "create"} onClick={create}>
                {tn(n, { one: "Create {n} variants", other: "Create {n} variants" })}
              </Button>
            </div>
          </Card>
          <Card title={t("Experiments")} pad={false}>
            <ul className="divide-y divide-cream-200">
              {(list.data ?? []).map((x: any) => (
                <li key={x.id}>
                  <button
                    onClick={() => {
                      setSel(x.id);
                      setRank(null);
                    }}
                    className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-[13px] hover:bg-cream-50 ${sel === x.id ? "bg-cream-100" : ""}`}
                  >
                    <span className="min-w-0">
                      <b>{x.name}</b>
                      <br />
                      <span className="text-espresso-400">{t("{variants} · {hours} h simulated", { variants: tn(x.variant_count, { one: "{n} variant", other: "{n} variants" }), hours: x.hours_done })}</span>
                    </span>
                    <StatusBadge s={x.status} />
                  </button>
                </li>
              ))}
              {list.data?.length === 0 && <li className="px-4 py-6 text-center text-[13px] text-espresso-400">{t("None yet.")}</li>}
            </ul>
          </Card>
        </div>
        <div className="min-w-0 space-y-5">
          {!sel && <Empty title={t("Create or pick an experiment")} hint={t("Twelve variants by default: 3 hooks × 2 CTAs × 2 visuals.")} />}
          {sel && exp.isLoading && <Skeleton h={300} />}
          {e && (
            <>
              <Card title={e.name} subtitle={t("Simulated ad platform — Beta-Bernoulli bandit on CTR; the true rates are hidden from the allocator")} actions={
                <>
                  <StatusBadge s={e.status} />
                  <Badge tone="warn">{t("simulated")}</Badge>
                </>
              } testId="experiment-card">
                <div className="flex flex-wrap items-end gap-4">
                  <Field label={t("Hours to simulate: {n}", { n: hours })}>
                    <input type="range" min={1} max={48} value={hours} onChange={(x) => setHours(+x.target.value)} className="w-40" aria-label={t("hours")} />
                  </Field>
                  <Field label={t("Allocation")}>
                    <Select value={strategy} onChange={(x) => setStrategy(x.target.value)} className="w-52" aria-label={t("strategy")}>
                      <option value="thompson">{t("Thompson sampling")}</option>
                      <option value="uniform">{t("Uniform split (control)")}</option>
                    </Select>
                  </Field>
                  <Button variant="accent" icon={<Play className="h-4 w-4" />} loading={busy === "simulate"} onClick={() => act("simulate")}>
                    {t("Run simulation")}
                  </Button>
                  <Button variant="outline" loading={busy === "preflight"} onClick={() => act("preflight")}>
                    {t("Pre-flight rank")}
                  </Button>
                  <Button variant="ghost" icon={<RotateCcw className="h-4 w-4" />} onClick={() => act("reset")}>
                    {t("Reset")}
                  </Button>
                </div>
              </Card>
              {e.leader && (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-[1.7fr_1fr_1fr_1fr]" data-testid="experiment-stats">
                    <Tile label={t("Leader")} valueClass="text-[15px] leading-snug text-sage-600" value={labelOf(variantById(e.leader.id)) ?? e.leader.label} hint={t("P(best) {pct} after {hours} h", { pct: fmt.pct(e.leader.p_best * 100, 0), hours: e.hours_done })} />
                    <Tile
                      label={t("Significance")}
                      valueClass={`text-[24px] leading-none ${leaderSig?.significant ? "text-sage-600" : "text-dawn-600"}`}
                      value={leaderSig ? (leaderSig.significant ? t("Significant") : t("Not yet")) : t("Control leads")}
                      hint={leaderSig ? t("p {p} vs control {id}", { p: fmtP(leaderSig.p_value), id: e.variants[0].id }) : t("leader is control {id}", { id: e.variants[0].id })}
                    />
                    <Tile label={t("Clicks vs uniform")} valueClass="text-[24px] leading-none text-dawn-600" value={e.last_run?.uplift_vs_uniform_pct != null ? `${e.last_run.uplift_vs_uniform_pct > 0 ? "+" : ""}${fmt.number(e.last_run.uplift_vs_uniform_pct, 2)}%` : "—"} hint={t("{a} vs {b} expected", { a: fmt.number(e.last_run?.reward_clicks), b: fmt.number(e.last_run?.uniform_expected_clicks) })} />
                    <Tile label={t("Auto-paused losers")} value={t("{n} of {total}", { n: pausedHours.length, total: e.variants.length })} hint={pausedHours.length ? t("first pause at {n} h", { n: Math.min(...pausedHours) }) : t("none paused yet")} />
                  </div>
                  {hist.length > 0 && (
                    <Card title={t("Budget allocation over time")} actions={<span className="text-[12px] text-espresso-500">{t("share of impressions per variant, per hour (stacked to 100%)")}</span>} pad={false}>
                      <div className="h-40 px-3 pb-2 pt-3" data-testid="allocation-chart">
                        <ResponsiveContainer>
                          <AreaChart data={hist} stackOffset="expand">
                            <CartesianGrid stroke="#efe6d8" vertical={false} />
                            <XAxis dataKey="hour" tick={{ fontSize: 11 }} label={{ value: t("hour"), position: "insideBottomRight", offset: -2, fontSize: 11 }} />
                            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt.percent(+v, 0)} />
                            <Tooltip formatter={(v: any) => fmt.percent(+v, 1)} labelFormatter={(h: any) => t("hour {n}", { n: h })} />
                            <Legend wrapperStyle={{ fontSize: 11 }} />
                            {e.variants.map((v: any, i: number) => (
                              <Area key={v.id} type="monotone" dataKey={v.id} stackId="1" stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.85} />
                            ))}
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    </Card>
                  )}
                </>
              )}
              <Card title={t("Variants")} actions={<span className="text-right text-[12px] text-espresso-500">{t("sorted by P(best) · significance = two-proportion z-test on CTR vs control {id}", { id: e.variants[0].id })}</span>} pad={false}>
                <div className="scroll-thin overflow-x-auto px-3 pb-2" data-testid="variants-table">
                  <table className="w-full whitespace-nowrap text-left text-[12px]">
                    <thead>
                      <tr className="border-b border-cream-300 text-[10.5px] uppercase tracking-wider text-espresso-500">
                        <th className="px-1.5 py-1.5 font-semibold" />
                        {head.map((h, i) => (
                          <th key={i} className="px-1.5 py-1.5 font-semibold">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {variants.map((v) => {
                        const s = sigBy[v.id];
                        return (
                          <tr key={v.id} className="border-b border-cream-200 last:border-0 hover:bg-cream-50">
                            <td className={TD}>
                              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: COLORS[e.variants.findIndex((x: any) => x.id === v.id) % COLORS.length] }} />
                            </td>
                            <td className={TD}>
                              <span className="text-espresso-400">{v.id}</span> <span className="text-espresso-700">{labelOf(v)}</span>
                            </td>
                            <td className={TD}>{v.status === "paused" ? <Badge tone="bad">{t("paused {n}h", { n: v.paused_at_hour })}</Badge> : <Badge tone="good">{tEnum("variantStatus", "active")}</Badge>}</td>
                            <td className={`${TD} tabular-nums`}>{fmt.number(v.impressions)}</td>
                            <td className={`${TD} tabular-nums`}>{v.ctr != null ? fmt.pct(v.ctr * 100, 2) : "—"}</td>
                            <td className={TD}>
                              {v.p_best != null ? (
                                <div className="flex items-center gap-1.5">
                                  <div className="w-12">
                                    <Meter value={v.p_best} max={1} />
                                  </div>
                                  <span className="tabular-nums">{fmt.pct(v.p_best * 100, 0)}</span>
                                </div>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className={`${TD} tabular-nums`}>{fmt.pct(v.share * 100, 1)}</td>
                            <td className={`${TD} tabular-nums`}>{s ? fmt.fixed(s.z, 1) : "—"}</td>
                            <td className={`${TD} tabular-nums`}>{s ? fmtP(s.p_value) : "—"}</td>
                            <td className={TD}>{s ? s.significant ? <Badge tone="good">{t("yes")}</Badge> : <Badge>{t("no")}</Badge> : v.p_best != null ? <Badge tone="dark">{t("control")}</Badge> : "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
              {rank && (
                <Card title={t("Pre-flight ranking")} subtitle={rank.label}>
                  <ol className="list-decimal pl-5 text-[13px]">
                    {rank.ranking.slice(0, 6).map((r: any) => (
                      <li key={r.id}>
                        <b>{labelOf(variantById(r.id)) ?? r.label}</b> — {fmt.number(r.predicted_score)}/100 <span className="text-espresso-400">{rationaleOf(r)}</span>
                      </li>
                    ))}
                  </ol>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-17",
  routes: [{ path: "/experiments", element: <ExperimentsPage /> }],
  nav: { group: "Performance", label: msg("Variants & bandit"), to: "/experiments", order: 10, icon: FlaskConical },
};
