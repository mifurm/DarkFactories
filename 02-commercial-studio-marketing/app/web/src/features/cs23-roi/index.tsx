/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Calculator, CheckCircle2, Layers } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Card, Input, KV, PageHeader, Skeleton, Stat, Table, cn } from "../../components/ui";
import { msg, useI18n, type I18n } from "../../i18n";

const PALETTE = ["#2b1a12", "#d9822b", "#b5452b", "#5c7a5e", "#7a8fa6", "#a9895f", "#c9a227", "#8b5e83", "#3f7f93", "#e07a5f", "#81b29a", "#6d597a", "#355070", "#b56576"];
const LEVER_COLOR: Record<string, string> = { core: "#2b1a12", breadth: "#2b1a12", e1: "#d9822b", e2: "#5c7a5e", e3: "#7a8fa6", e4: "#b5452b" };
const SCENARIOS = ["conservative", "base", "upside"];
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

// Long English texts the API returns verbatim: shown translated when they are the known constants, otherwise as the server rendered them.
const KNOWN_DISCLAIMER = msg("Illustrative business case: every figure derives from business-case/assumptions.json (sources + labelled assumptions). Validate with customer data.");
const KNOWN_LIVE_NOTE = msg("Metered AI consumption of this demo deployment at list-price estimates; the full ACR model is computed by /api/roi/compute.");

function EnterpriseBreakdown({ tier, labels, i18n }: { tier: any; labels: Record<string, string>; i18n: I18n }) {
  const { t, tEnum, fmt } = i18n;
  const usd = fmt.compactUsd;
  const x = tier.expansion;
  const parts: { k: string; label: string; v: number }[] = [
    { k: "breadth", label: t("Breadth — core studio at {versions} versions/yr, {markets} markets", { versions: fmt.number(tier.versions_per_year), markets: tier.markets }), v: x.core_run_rate_usd },
    ...["e1", "e2", "e3", "e4"].map((k) => ({ k, label: tEnum("roiLever", k, labels[k] ?? k.toUpperCase()), v: x.by_lever_usd[k] as number })),
  ].filter((p) => p.v > 0.5);
  const total = parts.reduce((a, p) => a + p.v, 0) || 1;
  const lp = x.lever_params ?? {};
  return (
    <Card title={t("Enterprise-scale tier — what the run-rate is made of")} subtitle={t("{label}: {amount} Azure ACR a year at full scale", { label: tEnum("roiTier", tier.tier, tier.label), amount: usd(tier.acr_run_rate_usd) })} testId="roi-enterprise">
      <div className="flex h-7 w-full overflow-hidden rounded-lg">
        {parts.map((p) => (
          <div key={p.k} title={`${p.label}: ${fmt.usd(p.v, 0)}`} style={{ width: `${(p.v / total) * 100}%`, background: LEVER_COLOR[p.k] }} />
        ))}
      </div>
      <ul className="mt-3 space-y-1.5 text-[13px]">
        {parts.map((p) => (
          <li key={p.k} className="flex items-center gap-2">
            <span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: LEVER_COLOR[p.k] }} />
            <span className="min-w-0 flex-1">{p.label}</span>
            <b className="tabular-nums">{usd(p.v)}</b>
            <span className="w-12 text-right tabular-nums text-espresso-400">{fmt.number((p.v / total) * 100)}%</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 border-t border-cream-200 pt-2 text-[12px] text-espresso-500">
        {t("Drivers: {skus} SKUs (E2) · personalised variants ×{mult} (E3) · Fabric {cu} CU + {tb} TB OneLake (E4) · generative video on {hero} hero + {adapted} adapted clips (E1).", {
          skus: fmt.number(lp.e2_skus),
          mult: lp.e3_multiplier,
          cu: lp.e4_fabric_cu,
          tb: lp.e4_onelake_tb,
          hero: fmt.number(x.units?.e1?.clips_hero),
          adapted: fmt.number(x.units?.e1?.clips_adapted),
        })}{" "}
        {tEnum("roiTierDesc", tier.tier, tier.description)}
      </div>
    </Card>
  );
}

function RoiPage() {
  const i18n = useI18n();
  const { t, tn, tEnum, fmt } = i18n;
  const usd = fmt.compactUsd;
  const yearLabel = (y: number) => t("Y{n}", { n: String(y) });
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
  const benefitLabel = (k: string) => tEnum("roiBenefit", k, r?.benefits.labels[k] ?? k);
  const costLabel = (k: string) => (k === "azure" ? t("Azure run cost (= ACR at list price)") : tEnum("roiCost", k, r?.costs.labels?.[k] ?? k.replace(/_/g, " ")));
  const leverName = (k: string) => tEnum("roiLever", k, r?.acr.by_lever_labels?.[k] ?? k);

  const cum = useMemo(() => (r ? r.years.map((y: number, i: number) => ({ y: yearLabel(y), net: r.roi.net_benefit_by_year[i], cumulative: r.roi.cumulative[i] })) : []), [r, i18n]); // eslint-disable-line react-hooks/exhaustive-deps
  const benefitKeys: string[] = useMemo(() => (r ? Object.keys(r.benefits.by_category).filter((k) => live(r.benefits.by_category[k])) : []), [r]);
  const benefits = useMemo(
    () => (r ? r.years.slice(1).map((y: number, i: number) => ({ y: yearLabel(y), ...Object.fromEntries(benefitKeys.map((k) => [benefitLabel(k), Math.round(r.benefits.by_category[k][i + 1])])) })) : []),
    [r, benefitKeys, i18n], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const costSeries: { key: string; label: string; vals: number[] }[] = useMemo(() => {
    if (!r) return [];
    const rows = [{ key: "azure", label: costLabel("azure"), vals: r.costs.azure_total_by_year as number[] }, ...Object.entries(r.costs.other_by_category).map(([k, v]: any) => ({ key: k, label: costLabel(k), vals: v as number[] }))];
    return rows.filter((x) => live(x.vals));
  }, [r, i18n]); // eslint-disable-line react-hooks/exhaustive-deps
  const costs = useMemo(() => (r ? r.years.map((y: number, i: number) => ({ y: yearLabel(y), ...Object.fromEntries(costSeries.map((c) => [c.label, Math.round(c.vals[i])])) })) : []), [r, costSeries, i18n]); // eslint-disable-line react-hooks/exhaustive-deps
  const leverKeys: string[] = useMemo(() => (r ? Object.keys(r.acr.by_lever).filter((k) => live(r.acr.by_lever[k])) : []), [r]);
  const byLever = useMemo(() => (r ? r.years.slice(1).map((y: number, i: number) => ({ y: yearLabel(y), ...Object.fromEntries(leverKeys.map((k) => [k, Math.round(r.acr.by_lever[k][i + 1])])) })) : []), [r, leverKeys, i18n]); // eslint-disable-line react-hooks/exhaustive-deps
  const families = useMemo(
    () => (r ? Object.entries(r.acr.by_family).map(([k, v]: any) => ({ k: tEnum("roiFamily", k, r.acr.family_labels?.[k] ?? k.replace(/_/g, " ")), v: Math.round(v[v.length - 1]) })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v) : []),
    [r, i18n], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const tornado = useMemo(() => (r ? [...r.sensitivity].sort((a: any, b: any) => b.swing - a.swing).slice(0, 9).reverse().map((s: any) => ({ k: tEnum("roiSens", s.id, s.label), lo: s.npv_low - s.base_npv, hi: s.npv_high - s.base_npv })) : []), [r, i18n]); // eslint-disable-line react-hooks/exhaustive-deps
  const enterprise = r?.acr.tiers.find((x: any) => x.tier === "enterprise_scale");
  const parity = ref.data;
  const known = (text: string | undefined, source: string) => (text === source ? t(source) : text);

  const field = ([k, s]: [string, any]) => {
    const def = defaultFor(k, s, base.current ?? r);
    const label = tEnum("roiSpec", k, s.label);
    const unit = tEnum("roiUnit", s.unit, s.unit);
    if (s.unit === "fraction[3]") {
      const cur: number[] = ov[k] ?? (def as number[]) ?? [0, 0, 0];
      return (
        <div key={k}>
          <div className="mb-1 text-[12px] font-semibold text-espresso-600">{label}</div>
          <div className="grid grid-cols-3 gap-2">
            {[0, 1, 2].map((i) => (
              <Input
                key={i}
                type="number"
                step={0.05}
                min={s.min}
                max={s.max}
                value={cur[i] ?? ""}
                aria-label={t("{label}: year {n}", { label, n: i + 1 })}
                onChange={(e) => {
                  const n = [...cur];
                  n[i] = e.target.value === "" ? NaN : +e.target.value;
                  setKey(k, n);
                }}
              />
            ))}
          </div>
        </div>
      );
    }
    const masterApplies = /^e[1-4]_scale$/.test(k) && exp > 0; // the master expansion switch sets all four levers unless one is overridden
    const val = ov[k] ?? (masterApplies ? exp : typeof def === "number" ? def : "");
    const pct = s.unit === "fraction";
    return (
      <div key={k}>
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={`ov-${k}`} className="text-[12px] font-semibold text-espresso-600">
            {label}
          </label>
          {ov[k] !== undefined && (
            <button className="shrink-0 text-[11px] text-dawn-700 hover:underline" onClick={() => setKey(k, undefined)}>
              {t("reset")}
            </button>
          )}
        </div>
        <div className="mt-1 flex items-center gap-2">
          {typeof def === "number" && s.max <= 1e7 && <input type="range" min={s.min} max={Math.max(s.max, +def)} step={s.integer ? 1 : (s.max - s.min) / 200} value={val} onChange={(e) => setKey(k, +e.target.value)} className="w-24 shrink-0 accent-dawn-500" aria-label={t("{label} slider", { label })} />}
          <Input id={`ov-${k}`} type="number" min={s.min} max={s.max} step={s.integer ? 1 : "any"} value={typeof val === "number" ? Number(val.toFixed(pct ? 3 : 2)) : val} placeholder={t("default")} onChange={(e) => setKey(k, e.target.value === "" ? undefined : +e.target.value)} />
        </div>
        <div className="mt-0.5 text-[11px] text-espresso-400">
          {unit} · {fmt.number(s.min)} – {fmt.number(s.max)}
        </div>
      </div>
    );
  };

  const seg = (on: boolean) => `rounded-lg border px-3 py-1.5 text-[13px] font-medium ${on ? "border-dawn-500 bg-dawn-300/25" : "border-cream-300 bg-white"}`;
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-23 · ROI & Azure ACR calculator")}
        title={t("Business case calculator")}
        subtitle={
          meta.data
            ? t("{customer} (fictional) · {currency} · model {version}. Adjust any assumption — ROI, NPV, payback and Azure consumption (ACR) by service and by expansion lever recompute instantly from the same model the PRD and the deck quote.", { customer: meta.data.customer, currency: meta.data.currency, version: meta.data.model_version })
            : t("Loading model…")
        }
        actions={
          parity && (
            <Badge tone={parity.parity_ok ? "good" : "bad"}>
              <CheckCircle2 className="h-3 w-3" /> {t("parity with published outputs.json: {state}", { state: parity.parity_ok ? t("OK (±0.5%)") : t("MISMATCH") })}
            </Badge>
          )
        }
      />
      <Card className="mb-5" testId="roi-scope">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-espresso-500">{t("Scenario")}</div>
            <div className="flex gap-1.5" role="tablist" aria-label={t("scenario")}>
              {SCENARIOS.map((id) => (
                <button key={id} role="tab" aria-selected={scenario === id} onClick={() => setScenario(id)} className={seg(scenario === id)}>
                  {tEnum("roiScenario", id)}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-espresso-500">{t("Scope")}</div>
            <div className="flex gap-1.5" role="tablist" aria-label={t("expansion")}>
              <button role="tab" aria-selected={exp === 0} onClick={() => setExp(0)} className={seg(exp === 0)}>
                {t("Expansion off")}
              </button>
              <button role="tab" aria-selected={exp > 0} onClick={() => setExp(1)} className={`inline-flex items-center gap-1 ${seg(exp > 0)}`}>
                <Layers className="h-3.5 w-3.5" />
                {t("Expansion on")}
              </button>
            </div>
          </div>
          <label className="min-w-[260px] flex-1">
            <div className="mb-1 flex justify-between gap-3 text-[11px] font-semibold uppercase tracking-wide text-espresso-500">
              <span>{t("Expansion scale (E1 video · E2 catalog · E3 personalization · E4 data platform)")}</span>
              <span className="tabular-nums text-espresso-800">{fmt.fixed(exp, 2)}</span>
            </div>
            <input type="range" min={0} max={1} step={0.05} value={exp} onChange={(e) => setExp(+e.target.value)} className="w-full accent-dawn-500" aria-label={t("expansion scale")} />
          </label>
        </div>
        <div className="mt-2 text-[11.5px] text-espresso-400">{t("Base = the Release-1 campaign studio. Expansion levers E1–E4 are optional add-ons modelled and metered separately (they are not Release-1 code); scenarios move the sourced low/base/high assumptions together.")}</div>
      </Card>
      <div className="grid gap-5 xl:grid-cols-[340px_1fr]">
        <div className="min-w-0 space-y-5">
          <Card
            title={t("Assumptions")}
            subtitle={Object.keys(ov).length ? tn(Object.keys(ov).length, { one: "{n} override(s) active", other: "{n} override(s) active" }) : t("defaults of the selected scenario")}
            actions={
              Object.keys(ov).length > 0 && (
                <button className="text-[12px] text-dawn-700 hover:underline" onClick={() => setOv({})}>
                  {t("reset all")}
                </button>
              )
            }
          >
            <div className="space-y-3.5" data-testid="roi-inputs">
              {core.map(field)}
            </div>
          </Card>
          <Card title={t("Expansion lever assumptions")} subtitle={t("E1 generative video · E2 catalog content · E3 personalization · E4 data platform")}>
            <div className="space-y-3.5" data-testid="roi-expansion">
              {specs.filter(([k]) => k === "expansion_scale").map(field)}
              {lever.map(field)}
            </div>
            {advanced.length > 0 && (
              <details className="mt-4 border-t border-cream-200 pt-3" data-testid="roi-advanced">
                <summary className="cursor-pointer text-[12.5px] font-semibold text-espresso-700">{t("Advanced assumptions ({n}) — every other validated override key", { n: advanced.length })}</summary>
                <div className="mt-3 space-y-3.5">{advanced.map(field)}</div>
              </details>
            )}
          </Card>
        </div>
        <div className="min-w-0 space-y-5">
          {err && <div className="rounded-xl bg-roast-500/10 px-4 py-2 text-[13px] text-roast-600">{err}</div>}
          {!r ? (
            <Skeleton h={300} />
          ) : (
            <>
              <div className={cn("grid gap-3 md:grid-cols-3", fmt.lang === "pl" ? "xl:grid-cols-3 2xl:grid-cols-6" : "xl:grid-cols-6")} data-testid="roi-kpis"> {/* Polish figures ("15,86 mln USD") need wider tiles */}
                <Stat label={t("3-year ROI")} value={fmt.pct(r.roi.roi_pct, 0)} tone="dawn" hint={t("B/C {n}×", { n: fmt.fixed(r.roi.benefit_cost_ratio, 2) })} />
                <Stat label={t("NPV (3 yr)")} value={usd(r.roi.npv)} tone="good" hint={t("discount {pct}", { pct: fmt.pct(r.roi.discount_rate * 100, 0) })} />
                <Stat label={t("Payback")} value={r.roi.payback_months != null ? t("{n} mo", { n: fmt.fixed(r.roi.payback_months, 1) }) : t("> 36 mo")} />
                <Stat label="IRR" value={r.roi.irr_pct != null ? fmt.pct(r.roi.irr_pct, 0) : "—"} />
                <Stat
                  label={t("Azure ACR · Y3 run-rate")}
                  value={usd(r.acr.run_rate_year3)}
                  tone="dawn"
                  hint={
                    <span data-testid="roi-acr-years">
                      {t("Y1 {a} · Y2 {b} · Y3 {c}", { a: usd(r.acr.by_year[1]), b: usd(r.acr.by_year[2]), c: usd(r.acr.by_year[3]) })}
                    </span>
                  }
                />
                <Stat label={t("Total benefit / cost")} value={usd(r.roi.total_benefit)} hint={t("cost {cost} (Azure {pct})", { cost: usd(r.roi.total_cost), pct: fmt.pct(r.roi.azure_share_of_cost_pct, 0) })} />
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <Card title={t("Cash flow")} subtitle={t("Net benefit per year and cumulative position")}>
                  <div className="h-60" data-testid="roi-cashflow">
                    <ResponsiveContainer>
                      <ComposedChart data={cum}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} width={fmt.lang === "pl" ? 84 : 60} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <ReferenceLine y={0} stroke="#7a6a5d" />
                        <Bar dataKey="net" name={t("Net benefit")} fill="#d9822b" radius={[4, 4, 0, 0]} />
                        <Line dataKey="cumulative" name={t("Cumulative")} stroke="#2b1a12" strokeWidth={2.5} dot={{ r: 4 }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title={t("Benefits by category")} subtitle={t("Risk-adjusted US$ per year · {categories} (zero categories hidden)", { categories: tn(benefitKeys.length, { one: "{n} active category", other: "{n} active categories" }) })}>
                  <div className="h-60" data-testid="roi-benefits">
                    <ResponsiveContainer>
                      <BarChart data={benefits}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} width={fmt.lang === "pl" ? 84 : 60} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        {benefitKeys.map((k, i) => (
                          <Bar key={k} dataKey={benefitLabel(k)} stackId="b" fill={PALETTE[i % PALETTE.length]} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title={t("Costs by category")} subtitle={t("Azure run cost + licence, implementation, change, review and expansion cost (zero categories hidden)")}>
                  <div className="h-60" data-testid="roi-costs">
                    <ResponsiveContainer>
                      <BarChart data={costs}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} width={fmt.lang === "pl" ? 84 : 60} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        {costSeries.map((c, i) => (
                          <Bar key={c.key} dataKey={c.label} stackId="c" fill={PALETTE[(i + 3) % PALETTE.length]} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title={t("Azure ACR by lever")} subtitle={leverKeys.length > 1 ? t("Annual consumption by expansion lever, Years 1–3 (stacked)") : t("Core studio only — switch Expansion on to add E1–E4")} testId="roi-lever">
                  <div className="h-60" data-testid="roi-acr-lever">
                    <ResponsiveContainer>
                      <BarChart data={byLever}>
                        <CartesianGrid stroke="#efe6d8" vertical={false} />
                        <XAxis dataKey="y" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={usd} width={fmt.lang === "pl" ? 84 : 60} />
                        <Tooltip formatter={(v: any, n: any) => [usd(+v), leverName(n)]} />
                        <Legend formatter={(n: any) => leverName(n)} wrapperStyle={{ fontSize: 11 }} />
                        {leverKeys.map((k) => (
                          <Bar key={k} dataKey={k} stackId="l" fill={LEVER_COLOR[k]} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title={t("Azure consumption (ACR) by service")} subtitle={t("Year-3 annual run-rate — what the customer would consume on Azure")}>
                  <div className="h-64" data-testid="roi-acr">
                    <ResponsiveContainer>
                      <BarChart data={families} layout="vertical" margin={{ left: 40 }}>
                        <CartesianGrid stroke="#efe6d8" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <YAxis type="category" dataKey="k" tick={{ fontSize: 11 }} width={fmt.lang === "pl" ? 190 : 150} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <Bar dataKey="v" name={t("Azure ACR / yr")} fill="#5c7a5e" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Card title={t("Sensitivity (tornado)")} subtitle={t("NPV change when each assumption moves across its sourced low–high range")}>
                  <div className="h-64">
                    <ResponsiveContainer>
                      <BarChart data={tornado} layout="vertical" margin={{ left: 40 }} stackOffset="sign">
                        <CartesianGrid stroke="#efe6d8" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={usd} />
                        <YAxis type="category" dataKey="k" tick={{ fontSize: 11 }} width={fmt.lang === "pl" ? 190 : 150} />
                        <Tooltip formatter={(v: any) => usd(+v)} />
                        <ReferenceLine x={0} stroke="#7a6a5d" />
                        <Bar dataKey="lo" name={t("low case")} stackId="t" fill="#b5452b" />
                        <Bar dataKey="hi" name={t("high case")} stackId="t" fill="#5c7a5e" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
              </div>
              <Card title={t("Customer tiers → Azure ACR")} subtitle={t("Annual run-rate consumption at five footprints — the customer's expansion path from pilot to enterprise scale")} pad={false} testId="roi-tiers">
                <div className="p-3">
                  <Table
                    head={[t("Tier"), t("What it means"), t("Versions / yr"), t("Markets"), t("Azure ACR / yr")]}
                    rows={r.acr.tiers.map((x: any) => [
                      <b key="l">{tEnum("roiTier", x.tier, x.label)}</b>,
                      <span key="d" className="text-espresso-500">
                        {tEnum("roiTierDesc", x.tier, x.description)}
                      </span>,
                      fmt.number(x.versions_per_year),
                      x.markets,
                      <b key="a" className="tabular-nums">
                        {fmt.usd(x.acr_run_rate_usd, 0)}
                      </b>,
                    ])}
                  />
                </div>
              </Card>
              {enterprise?.expansion && <EnterpriseBreakdown tier={enterprise} labels={leverLabels} i18n={i18n} />}
              <div className="grid gap-5 lg:grid-cols-2">
                <Card title={t("Measured on this deployment")} subtitle={t("Live Studio vs agency baseline (from the metered Azure calls)")} testId="roi-live">
                  {liveQ.data ? (
                    <KV
                      rows={[
                        [t("AI spend (metered)"), fmt.usd(liveQ.data.kpi.ai_spend_usd, 3)],
                        [t("Approved video assets"), fmt.number(liveQ.data.approved_assets)],
                        [t("Studio cost / approved asset"), liveQ.data.kpi.cost_per_approved_asset_usd != null ? fmt.usd(liveQ.data.kpi.cost_per_approved_asset_usd, 3) : "—"],
                        [t("Agency baseline / adapted asset"), fmt.usd(liveQ.data.kpi.agency_baseline_per_asset_usd, 0)],
                        [t("Saving vs baseline"), liveQ.data.kpi.savings_pct != null ? `${fmt.number(liveQ.data.kpi.savings_pct, 2)}%` : "—"],
                        [t("Variants per campaign"), fmt.number(liveQ.data.variants_per_campaign, 1)],
                        [t("Cycle time (measured)"), liveQ.data.cycle_time_hours_measured != null ? t("{n} h", { n: fmt.number(liveQ.data.cycle_time_hours_measured, 4) }) : t("n/a yet")],
                      ]}
                    />
                  ) : (
                    <Skeleton h={120} />
                  )}
                  <div className="mt-2 text-[11.5px] text-espresso-400">
                    {known(liveQ.data?.note, KNOWN_LIVE_NOTE)} {t("Production review time and licences are not included in the metered cost.")}
                  </div>
                </Card>
                <Card title={t("Model provenance")} subtitle={t("Everything is traceable to business-case/assumptions.json")}>
                  {meta.data && (
                    <KV
                      rows={[
                        [t("Model"), meta.data.model_version],
                        [
                          t("Assumptions sha256"),
                          <code key="h" className="text-[11px]">
                            {meta.data.assumptions_sha256.slice(0, 20)}…
                          </code>,
                        ],
                        [t("Pricing retrieved"), fmt.isoDate(meta.data.pricing_retrieved_at)],
                        [t("Horizon"), tn(r.horizon_years, { one: "{n} years", other: "{n} years" })],
                        [t("Scenario"), tEnum("roiScenario", r.scenario, r.scenario_label)],
                      ]}
                    />
                  )}
                  <div className="mt-2 text-[11.5px] text-espresso-400">{known(meta.data?.disclaimer, KNOWN_DISCLAIMER)}</div>
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
  nav: { group: "Operate", label: msg("ROI & ACR"), to: "/roi", order: 30, icon: Calculator },
};
