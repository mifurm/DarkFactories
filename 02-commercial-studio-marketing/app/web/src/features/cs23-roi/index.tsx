/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Calculator, CheckCircle2, Layers } from "lucide-react";
import { api, fmtNum, fmtUsd } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Card, Input, KV, PageHeader, Skeleton, Stat, Table } from "../../components/ui";

const usd = (v: number | null | undefined) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(0)}k` : a.toFixed(0);
  return `${v < 0 ? "−" : ""}$${s}`;
};
const PALETTE = ["#2b1a12", "#d9822b", "#b5452b", "#5c7a5e", "#7a8fa6", "#a9895f", "#c9a227", "#8b5e83", "#3f7f93", "#e07a5f", "#81b29a", "#6d597a", "#355070", "#b56576"];
const LEVER_COLOR: Record<string, string> = { core: "#2b1a12", breadth: "#2b1a12", e1: "#d9822b", e2: "#5c7a5e", e3: "#7a8fa6", e4: "#b5452b" };
const SCEN = [["conservative", "Conservative"], ["base", "Base"], ["upside", "Upside"]];
const sum = (a?: number[]) => (a ?? []).reduce((x, y) => x + Math.abs(y), 0);
const live = (a?: number[]) => sum(a) > 0.5; // categories that are zero in every year are hidden

/** Expansion-lever controls are recognised from the override spec itself (label "E1…E4 …" / "Expansion …") or the lever key families. */
const isExpansionSpec = (k: string, s: any) => /^(E[1-4]\b|Expansion)/.test(s.label ?? "") || /^(e[1-4]_|expansion_|catalog_|personalization_|video_seconds|data_platform)/.test(k);

function defaultFor(key: string, spec: any, r: any): number | number[] | undefined {
  if (!r) return undefined;
  if (key === "adoption_ramp") return r.inputs?.adoption_ramp;
  if (key === "expansion_ramp") return r.inputs?.expansion?.ramp;
  if (key === "media_spend_in_scope_usd") return r.customer?.media_spend_in_scope_usd;
  if (key === "discount_rate") return r.roi?.discount_rate;
  if (["agency_cost_scale", "studio_review_scale", "azure_consumption_scale"].includes(key)) return 1;
  if (key === "expansion_scale") return 0;
  if (spec.maps_to && r.inputs?.resolved?.[spec.maps_to] !== undefined) return r.inputs.resolved[spec.maps_to];
  return undefined;
}

function EnterpriseBreakdown({ tier, labels }: { tier: any; labels: Record<string, string> }) {
  const x = tier.expansion;
  const parts: { k: string; label: string; v: number }[] = [
    { k: "breadth", label: `Breadth — core studio at ${fmtNum(tier.versions_per_year)} versions/yr, ${tier.markets} markets`, v: x.core_run_rate_usd },
    ...["e1", "e2", "e3", "e4"].map((k) => ({ k, label: labels[k] ?? k.toUpperCase(), v: x.by_lever_usd[k] as number })),
  ].filter((p) => p.v > 0.5);
  const total = parts.reduce((a, p) => a + p.v, 0) || 1;
  const lp = x.lever_params ?? {};
  return (
    <Card title="Enterprise-scale tier — what the run-rate is made of" subtitle={`${tier.label}: ${usd(tier.acr_run_rate_usd)} Azure ACR a year at full scale`} testId="roi-enterprise">
      <div className="flex h-7 w-full overflow-hidden rounded-lg">
        {parts.map((p) => <div key={p.k} title={`${p.label}: ${fmtUsd(p.v, 0)}`} style={{ width: `${(p.v / total) * 100}%`, background: LEVER_COLOR[p.k] }} />)}
      </div>
      <ul className="mt-3 space-y-1.5 text-[13px]">
        {parts.map((p) => (
          <li key={p.k} className="flex items-center gap-2">
            <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: LEVER_COLOR[p.k] }} />
            <span className="flex-1">{p.label}</span>
            <b className="tabular-nums">{usd(p.v)}</b>
            <span className="w-12 text-right tabular-nums text-espresso-400">{((p.v / total) * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 border-t border-cream-200 pt-2 text-[12px] text-espresso-500">
        Drivers: {fmtNum(lp.e2_skus)} SKUs (E2) · personalised variants ×{lp.e3_multiplier} (E3) · Fabric {lp.e4_fabric_cu} CU + {lp.e4_onelake_tb} TB OneLake (E4) · generative video on {fmtNum(x.units?.e1?.clips_hero)} hero + {fmtNum(x.units?.e1?.clips_adapted)} adapted clips (E1). {tier.description}
      </div>
    </Card>
  );
}

function RoiPage() {
  const meta = useQuery({ queryKey: ["roi-meta"], queryFn: () => api.get("/api/roi/meta"), staleTime: Infinity });
  const ref = useQuery({ queryKey: ["roi-ref"], queryFn: () => api.get("/api/roi/reference"), staleTime: Infinity });
  const liveQ = useQuery({ queryKey: ["roi-live"], queryFn: () => api.get("/api/roi/live"), refetchInterval: 20000 });
  const [scenario, setScenario] = useState("base");
  const [ov, setOv] = useState<Record<string, any>>({});
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const base = useRef<any>(null);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      try {
        const out = await api.post("/api/roi/compute", { scenario, overrides: Object.keys(ov).length ? ov : null }, { quiet: true });
        if (!Object.keys(ov).length) base.current = out;
        setR(out);
        setErr(null);
      } catch (e: any) {
        setErr(e.message);
      }
    }, 220);
    return () => window.clearTimeout(timer.current);
  }, [scenario, ov]);

  const setKey = (k: string, v: any) =>
    setOv((o) => {
      const n = { ...o };
      if (v === undefined || v === "" || (Array.isArray(v) && v.some((x: any) => x === "" || Number.isNaN(x)))) delete n[k];
      else n[k] = v;
      return n;
    });
  const exp: number = typeof ov.expansion_scale === "number" ? ov.expansion_scale : 0;
  const setExp = (v: number) => setKey("expansion_scale", v <= 0 ? undefined : v);

  const specs: [string, any][] = Object.entries(meta.data?.overrides ?? {});
  const advanced: [string, any][] = Object.entries(meta.data?.advanced ?? {});
  const core = specs.filter(([k, s]) => !isExpansionSpec(k, s));
  const lever = specs.filter(([k, s]) => isExpansionSpec(k, s) && k !== "expansion_scale");
  const leverLabels: Record<string, string> = meta.data?.lever_labels ?? {};

  const cum = useMemo(() => (r ? r.years.map((y: number, i: number) => ({ y: `Y${y}`, net: r.roi.net_benefit_by_year[i], cumulative: r.roi.cumulative[i] })) : []), [r]);
  const benefitKeys: string[] = useMemo(() => (r ? Object.keys(r.benefits.by_category).filter((k) => live(r.benefits.by_category[k])) : []), [r]);
  const benefits = useMemo(() => (r ? r.years.slice(1).map((y: number, i: number) => ({ y: `Y${y}`, ...Object.fromEntries(benefitKeys.map((k) => [r.benefits.labels[k] ?? k, Math.round(r.benefits.by_category[k][i + 1])])) })) : []), [r, benefitKeys]);
  const costSeries: { key: string; label: string; vals: number[] }[] = useMemo(() => {
    if (!r) return [];
    const rows = [{ key: "azure", label: "Azure run cost (= ACR at list price)", vals: r.costs.azure_total_by_year as number[] }, ...Object.entries(r.costs.other_by_category).map(([k, v]: any) => ({ key: k, label: r.costs.labels?.[k] ?? k.replace(/_/g, " "), vals: v as number[] }))];
    return rows.filter((x) => live(x.vals));
  }, [r]);
  const costs = useMemo(() => (r ? r.years.map((y: number, i: number) => ({ y: `Y${y}`, ...Object.fromEntries(costSeries.map((c) => [c.label, Math.round(c.vals[i])])) })) : []), [r, costSeries]);
  const leverKeys: string[] = useMemo(() => (r ? Object.keys(r.acr.by_lever).filter((k) => live(r.acr.by_lever[k])) : []), [r]);
  const byLever = useMemo(() => (r ? r.years.slice(1).map((y: number, i: number) => ({ y: `Y${y}`, ...Object.fromEntries(leverKeys.map((k) => [k, Math.round(r.acr.by_lever[k][i + 1])])) })) : []), [r, leverKeys]);
  const families = useMemo(() => (r ? Object.entries(r.acr.by_family).map(([k, v]: any) => ({ k: r.acr.family_labels?.[k] ?? k.replace(/_/g, " "), v: Math.round(v[v.length - 1]) })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v) : []), [r]);
  const tornado = useMemo(() => (r ? [...r.sensitivity].sort((a: any, b: any) => b.swing - a.swing).slice(0, 9).reverse().map((s: any) => ({ k: s.label, lo: s.npv_low - s.base_npv, hi: s.npv_high - s.base_npv })) : []), [r]);
  const enterprise = r?.acr.tiers.find((t: any) => t.tier === "enterprise_scale");
  const parity = ref.data;

  const field = ([k, s]: [string, any]) => {
    const def = defaultFor(k, s, base.current ?? r);
    if (s.unit === "fraction[3]") {
      const cur: number[] = ov[k] ?? (def as number[]) ?? [0, 0, 0];
      return (
        <div key={k}>
          <div className="mb-1 text-[12px] font-semibold text-espresso-600">{s.label}</div>
          <div className="grid grid-cols-3 gap-2">
            {[0, 1, 2].map((i) => <Input key={i} type="number" step={0.05} min={s.min} max={s.max} value={cur[i] ?? ""} aria-label={`${k} year ${i + 1}`} onChange={(e) => { const n = [...cur]; n[i] = e.target.value === "" ? NaN : +e.target.value; setKey(k, n); }} />)}
          </div>
        </div>
      );
    }
    const masterApplies = /^e[1-4]_scale$/.test(k) && exp > 0; // the master expansion switch sets all four levers unless one is overridden
    const val = ov[k] ?? (masterApplies ? exp : typeof def === "number" ? def : "");
    const pct = s.unit === "fraction";
    return (
      <div key={k}>
        <div className="flex items-baseline justify-between gap-2"><label htmlFor={`ov-${k}`} className="text-[12px] font-semibold text-espresso-600">{s.label}</label>{ov[k] !== undefined && <button className="text-[11px] text-dawn-700 hover:underline" onClick={() => setKey(k, undefined)}>reset</button>}</div>
        <div className="mt-1 flex items-center gap-2">
          {typeof def === "number" && s.max <= 1e7 && <input type="range" min={s.min} max={Math.max(s.max, +def)} step={s.integer ? 1 : (s.max - s.min) / 200} value={val} onChange={(e) => setKey(k, +e.target.value)} className="w-24 shrink-0 accent-dawn-500" aria-label={`${k} slider`} />}
          <Input id={`ov-${k}`} type="number" min={s.min} max={s.max} step={s.integer ? 1 : "any"} value={typeof val === "number" ? Number(val.toFixed(pct ? 3 : 2)) : val} placeholder="default" onChange={(e) => setKey(k, e.target.value === "" ? undefined : +e.target.value)} />
        </div>
        <div className="mt-0.5 text-[11px] text-espresso-400">{s.unit} · {fmtNum(s.min)} – {fmtNum(s.max)}</div>
      </div>
    );
  };

  return (
    <div>
      <PageHeader
        eyebrow="CS-23 · ROI & Azure ACR calculator"
        title="Business case calculator"
        subtitle={meta.data ? `${meta.data.customer} (fictional) · ${meta.data.currency} · model ${meta.data.model_version}. Adjust any assumption — ROI, NPV, payback and Azure consumption (ACR) by service and by expansion lever recompute instantly from the same model the PRD and the deck quote.` : "Loading model…"}
        actions={parity && <Badge tone={parity.parity_ok ? "good" : "bad"}><CheckCircle2 className="h-3 w-3" /> parity with published outputs.json: {parity.parity_ok ? "OK (±0.5%)" : "MISMATCH"}</Badge>}
      />
      <Card className="mb-5" testId="roi-scope">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-espresso-500">Scenario</div>
            <div className="flex gap-1.5" role="tablist" aria-label="scenario">
              {SCEN.map(([id, label]) => <button key={id} role="tab" aria-selected={scenario === id} onClick={() => setScenario(id)} className={`rounded-lg border px-3 py-1.5 text-[13px] font-medium ${scenario === id ? "border-dawn-500 bg-dawn-300/25" : "border-cream-300 bg-white"}`}>{label}</button>)}
            </div>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-espresso-500">Scope</div>
            <div className="flex gap-1.5" role="tablist" aria-label="expansion">
              <button role="tab" aria-selected={exp === 0} onClick={() => setExp(0)} className={`rounded-lg border px-3 py-1.5 text-[13px] font-medium ${exp === 0 ? "border-dawn-500 bg-dawn-300/25" : "border-cream-300 bg-white"}`}>Expansion off</button>
              <button role="tab" aria-selected={exp > 0} onClick={() => setExp(1)} className={`inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-[13px] font-medium ${exp > 0 ? "border-dawn-500 bg-dawn-300/25" : "border-cream-300 bg-white"}`}><Layers className="h-3.5 w-3.5" />Expansion on</button>
            </div>
          </div>
          <label className="min-w-[260px] flex-1">
            <div className="mb-1 flex justify-between text-[11px] font-semibold uppercase tracking-wide text-espresso-500"><span>Expansion scale (E1 video · E2 catalog · E3 personalization · E4 data platform)</span><span className="tabular-nums text-espresso-800">{exp.toFixed(2)}</span></div>
            <input type="range" min={0} max={1} step={0.05} value={exp} onChange={(e) => setExp(+e.target.value)} className="w-full accent-dawn-500" aria-label="expansion scale" />
          </label>
        </div>
        <div className="mt-2 text-[11.5px] text-espresso-400">Base = the Release-1 campaign studio. Expansion levers E1–E4 are optional add-ons modelled and metered separately (they are not Release-1 code); scenarios move the sourced low/base/high assumptions together.</div>
      </Card>
      <div className="grid gap-5 xl:grid-cols-[340px_1fr]">
        <div className="space-y-5">
          <Card title="Assumptions" subtitle={Object.keys(ov).length ? `${Object.keys(ov).length} override(s) active` : "defaults of the selected scenario"} actions={Object.keys(ov).length > 0 && <button className="text-[12px] text-dawn-700 hover:underline" onClick={() => setOv({})}>reset all</button>}>
            <div className="space-y-3.5" data-testid="roi-inputs">{core.map(field)}</div>
          </Card>
          <Card title="Expansion lever assumptions" subtitle="E1 generative video · E2 catalog content · E3 personalization · E4 data platform">
            <div className="space-y-3.5" data-testid="roi-expansion">
              {specs.filter(([k]) => k === "expansion_scale").map(field)}
              {lever.map(field)}
            </div>
            {advanced.length > 0 && (
              <details className="mt-4 border-t border-cream-200 pt-3" data-testid="roi-advanced">
                <summary className="cursor-pointer text-[12.5px] font-semibold text-espresso-700">Advanced assumptions ({advanced.length}) — every other validated override key</summary>
                <div className="mt-3 space-y-3.5">{advanced.map(field)}</div>
              </details>
            )}
          </Card>
        </div>
        <div className="space-y-5">
          {err && <div className="rounded-xl bg-roast-500/10 px-4 py-2 text-[13px] text-roast-600">{err}</div>}
          {!r ? <Skeleton h={300} /> : (
            <>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="roi-kpis">
                <Stat label="3-year ROI" value={`${r.roi.roi_pct.toFixed(0)}%`} tone="dawn" hint={`B/C ${r.roi.benefit_cost_ratio.toFixed(2)}×`} />
                <Stat label="NPV (3 yr)" value={usd(r.roi.npv)} tone="good" hint={`discount ${(r.roi.discount_rate * 100).toFixed(0)}%`} />
                <Stat label="Payback" value={r.roi.payback_months != null ? `${r.roi.payback_months.toFixed(1)} mo` : "> 36 mo"} />
                <Stat label="IRR" value={r.roi.irr_pct != null ? `${r.roi.irr_pct.toFixed(0)}%` : "—"} />
                <Stat label="Azure ACR · Y3 run-rate" value={usd(r.acr.run_rate_year3)} tone="dawn" hint={<span data-testid="roi-acr-years">Y1 {usd(r.acr.by_year[1])} · Y2 {usd(r.acr.by_year[2])} · Y3 {usd(r.acr.by_year[3])}</span>} />
                <Stat label="Total benefit / cost" value={usd(r.roi.total_benefit)} hint={`cost ${usd(r.roi.total_cost)} (Azure ${r.roi.azure_share_of_cost_pct.toFixed(0)}%)`} />
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <Card title="Cash flow" subtitle="Net benefit per year and cumulative position">
                  <div className="h-60" data-testid="roi-cashflow">
                    <ResponsiveContainer>
                      <ComposedChart data={cum}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <ReferenceLine y={0} stroke="#7a6a5d" />
                        <Bar dataKey="net" name="Net benefit" fill="#d9822b" radius={[4, 4, 0, 0]} />
                        <Line dataKey="cumulative" name="Cumulative" stroke="#2b1a12" strokeWidth={2.5} dot={{ r: 4 }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Benefits by category" subtitle={`Risk-adjusted US$ per year · ${benefitKeys.length} active categor${benefitKeys.length === 1 ? "y" : "ies"} (zero categories hidden)`}>
                  <div className="h-60" data-testid="roi-benefits">
                    <ResponsiveContainer>
                      <BarChart data={benefits}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        {benefitKeys.map((k, i) => <Bar key={k} dataKey={r.benefits.labels[k] ?? k} stackId="b" fill={PALETTE[i % PALETTE.length]} />)}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Costs by category" subtitle="Azure run cost + licence, implementation, change, review and expansion cost (zero categories hidden)">
                  <div className="h-60" data-testid="roi-costs">
                    <ResponsiveContainer>
                      <BarChart data={costs}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        {costSeries.map((c, i) => <Bar key={c.key} dataKey={c.label} stackId="c" fill={PALETTE[(i + 3) % PALETTE.length]} />)}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Azure ACR by lever" subtitle={leverKeys.length > 1 ? "Annual consumption by expansion lever, Years 1–3 (stacked)" : "Core studio only — switch Expansion on to add E1–E4"} testId="roi-lever">
                  <div className="h-60" data-testid="roi-acr-lever">
                    <ResponsiveContainer>
                      <BarChart data={byLever}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <Tooltip formatter={(v: any, n: any) => [usd(+v), r.acr.by_lever_labels?.[n] ?? n]} />
                        <Legend formatter={(n: any) => r.acr.by_lever_labels?.[n] ?? n} wrapperStyle={{ fontSize: 11 }} />
                        {leverKeys.map((k) => <Bar key={k} dataKey={k} stackId="l" fill={LEVER_COLOR[k]} />)}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Azure consumption (ACR) by service" subtitle="Year-3 annual run-rate — what the customer would consume on Azure">
                  <div className="h-64" data-testid="roi-acr">
                    <ResponsiveContainer>
                      <BarChart data={families} layout="vertical" margin={{ left: 40 }}>
                        <CartesianGrid stroke="#efe6d8" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <YAxis type="category" dataKey="k" tick={{ fontSize: 11 }} width={150} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <Bar dataKey="v" fill="#5c7a5e" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title="Sensitivity (tornado)" subtitle="NPV change when each assumption moves across its sourced low–high range">
                  <div className="h-64">
                    <ResponsiveContainer>
                      <BarChart data={tornado} layout="vertical" margin={{ left: 40 }} stackOffset="sign">
                        <CartesianGrid stroke="#efe6d8" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <YAxis type="category" dataKey="k" tick={{ fontSize: 11 }} width={150} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <ReferenceLine x={0} stroke="#7a6a5d" />
                        <Bar dataKey="lo" name="low case" stackId="t" fill="#b5452b" />
                        <Bar dataKey="hi" name="high case" stackId="t" fill="#5c7a5e" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
              </div>
              <Card title="Customer tiers → Azure ACR" subtitle="Annual run-rate consumption at five footprints — the customer's expansion path from pilot to enterprise scale" pad={false} testId="roi-tiers">
                <div className="p-3">
                  <Table head={["Tier", "What it means", "Versions / yr", "Markets", "Azure ACR / yr"]} rows={r.acr.tiers.map((t: any) => [<b key="l">{t.label}</b>, <span key="d" className="text-espresso-500">{t.description}</span>, fmtNum(t.versions_per_year), t.markets, <b key="a" className="tabular-nums">{fmtUsd(t.acr_run_rate_usd, 0)}</b>])} />
                </div>
              </Card>
              {enterprise?.expansion && <EnterpriseBreakdown tier={enterprise} labels={leverLabels} />}
              <div className="grid gap-5 lg:grid-cols-2">
                <Card title="Measured on this deployment" subtitle="Live Studio vs agency baseline (from the metered Azure calls)" testId="roi-live">
                  {liveQ.data ? (
                    <KV rows={[
                      ["AI spend (metered)", fmtUsd(liveQ.data.kpi.ai_spend_usd, 3)],
                      ["Approved video assets", String(liveQ.data.approved_assets)],
                      ["Studio cost / approved asset", liveQ.data.kpi.cost_per_approved_asset_usd != null ? fmtUsd(liveQ.data.kpi.cost_per_approved_asset_usd, 3) : "—"],
                      ["Agency baseline / adapted asset", fmtUsd(liveQ.data.kpi.agency_baseline_per_asset_usd, 0)],
                      ["Saving vs baseline", liveQ.data.kpi.savings_pct != null ? `${liveQ.data.kpi.savings_pct}%` : "—"],
                      ["Variants per campaign", String(liveQ.data.variants_per_campaign)],
                      ["Cycle time (measured)", liveQ.data.cycle_time_hours_measured != null ? `${liveQ.data.cycle_time_hours_measured} h` : "n/a yet"],
                    ]} />
                  ) : <Skeleton h={120} />}
                  <div className="mt-2 text-[11.5px] text-espresso-400">{liveQ.data?.note} Production review time and licences are not included in the metered cost.</div>
                </Card>
                <Card title="Model provenance" subtitle="Everything is traceable to business-case/assumptions.json">
                  {meta.data && <KV rows={[["Model", meta.data.model_version], ["Assumptions sha256", <code key="h" className="text-[11px]">{meta.data.assumptions_sha256.slice(0, 20)}…</code>], ["Pricing retrieved", meta.data.pricing_retrieved_at], ["Horizon", `${r.horizon_years} years`], ["Scenario", r.scenario_label]]} />}
                  <div className="mt-2 text-[11.5px] text-espresso-400">{meta.data?.disclaimer}</div>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-23",
  routes: [{ path: "/roi", element: <RoiPage /> }],
  nav: { group: "Operate", label: "ROI & ACR", to: "/roi", order: 30, icon: Calculator },
};
