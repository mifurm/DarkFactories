/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, ExternalLink, Search } from "lucide-react";
import { api } from "../api";
import { Badge, Card, Input, PageHeader, Skeleton, StatusBadge } from "../components/ui";
import { matchesQuery, useI18n } from "../i18n";

export default function FeatureMap() {
  const { t, tEnum } = useI18n();
  const features = useQuery({ queryKey: ["features"], queryFn: () => api.get<any[]>("/api/features") });
  const campaigns = useQuery({ queryKey: ["campaigns", "for-map"], queryFn: () => api.get<any[]>("/api/campaigns", { quiet: true }), retry: false });
  const [filter, setFilter] = useState("");
  const sampleId = campaigns.data?.find((c) => /dawn/i.test(c.name))?.id ?? campaigns.data?.[0]?.id ?? "demo";
  // /api/features stays English (the contract with docs and smoke tests); names, summaries and epics are localized here by feature id / epic letter
  const rows = useMemo(
    () =>
      (features.data ?? []).map((f) => ({
        f,
        name: tEnum("feature", f.id, f.name),
        summary: f.summary ? tEnum("featureSummary", f.id, f.summary) : "",
        epicName: tEnum("epic", f.epic, f.epic_name),
      })),
    [features.data, tEnum],
  );
  const grouped = useMemo(() => {
    const g = new Map<string, typeof rows>();
    rows
      .filter((r) => matchesQuery(`${r.f.id} ${r.name} ${r.summary} ${r.epicName}`, filter))
      .forEach((r) => {
        const k = `${r.f.epic}|${r.epicName}`;
        g.set(k, [...(g.get(k) ?? []), r]);
      });
    return [...g.entries()];
  }, [rows, filter]);
  const implemented = (features.data ?? []).filter((f) => f.status === "implemented").length;
  const total = features.data?.length ?? 0;

  return (
    <div data-testid="feature-map">
      <PageHeader
        eyebrow={t("Everything in the PRD is real")}
        title={t("Feature map")}
        subtitle={t("Release-1 catalog (CS-01 … CS-25), rendered live from /api/features. Each feature module self-registers; status reflects what is deployed on this instance.")}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={implemented === total && total > 0 ? "good" : "warn"}>{t("{implemented} / {total} implemented", { implemented, total })}</Badge>
            <a href="/docs" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-cream-300 bg-white px-3 py-1.5 text-[13px] font-medium hover:bg-cream-100">
              OpenAPI <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        }
      />
      <div className="relative mb-5 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-espresso-400" />
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("Filter features…")} aria-label={t("Filter features")} className="pl-9" data-testid="feature-filter" />
      </div>
      {features.isLoading && <Skeleton h={240} />}
      {features.data && !grouped.length && <div className="rounded-2xl border border-dashed border-cream-300 bg-cream-50 px-6 py-8 text-center text-[13px] text-espresso-500">{t("No feature matches “{query}”.", { query: filter })}</div>}
      <div className="space-y-6">
        {grouped.map(([key, items]) => {
          const [epic, name] = key.split("|");
          return (
            <Card key={key} title={<span>{t("Epic {epic} — {name}", { epic, name })}</span>} pad={false}>
              <ul className="divide-y divide-cream-200">
                {items.map(({ f, name: fname, summary }) => {
                  const route = f.ui_route.replace(":id", sampleId);
                  return (
                    <li key={f.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3" data-testid={`feature-${f.id}`}>
                      {f.status === "implemented" ? <CheckCircle2 className="h-4 w-4 text-sage-600" /> : <CircleDashed className="h-4 w-4 text-espresso-400" />}
                      <span className="w-14 font-mono text-[12.5px] font-semibold text-espresso-600">{f.id}</span>
                      <Link to={route} className="min-w-[220px] flex-1 text-[14px] font-medium text-espresso-900 hover:text-dawn-600">
                        {fname}
                        {summary && <span className="block text-[12px] font-normal text-espresso-500">{summary}</span>}
                      </Link>
                      <Badge tone={f.priority === "P0" ? "dark" : f.priority === "P1" ? "dawn" : "neutral"}>{f.priority}</Badge>
                      <StatusBadge s={f.status} />
                      <code className="hidden rounded bg-cream-100 px-2 py-0.5 text-[11.5px] text-espresso-600 md:inline">{f.api_prefix}</code>
                    </li>
                  );
                })}
              </ul>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
