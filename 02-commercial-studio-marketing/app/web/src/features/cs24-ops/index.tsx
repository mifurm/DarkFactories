/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, KV, PageHeader, Skeleton, StatusBadge, Table } from "../../components/ui";
import { msg, useI18n } from "../../i18n";

function OpsPage() {
  const { t, tOpen, fmt, lang } = useI18n();
  // the ffmpeg probe returns the first line of `ffmpeg -version` ("ffmpeg version 7.1.5 Copyright (c) 2000-2026 the FFmpeg developers"): a Polish UI shows just the version
  const detail = (v: any) => (v.backend ? tOpen("backend", v.backend) : v.version ? (lang === "en" ? String(v.version) : String(v.version).replace(/^ffmpeg version (\S+).*$/i, "ffmpeg $1")) : v.error || "");
  const status = useQuery({ queryKey: ["ops-status"], queryFn: () => api.get("/api/ops/status"), refetchInterval: 15000 });
  const metrics = useQuery({ queryKey: ["ops-metrics"], queryFn: () => api.get("/api/ops/metrics"), refetchInterval: 15000 });
  const ready = useQuery({ queryKey: ["readyz"], queryFn: () => api.get("/readyz?deep=true", { quiet: true }).catch((e) => e), staleTime: 20000 });
  const s = status.data;
  const deps = (ready.data as any)?.dependencies ?? {};
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-24 · Observability, security & IaC")}
        title={t("Operations")}
        subtitle={t("Live health, telemetry configuration, AI usage meter, rate limits and the daily budget guard of this deployment.")}
        actions={
          <Button
            variant="outline"
            onClick={() => {
              status.refetch();
              metrics.refetch();
              ready.refetch();
            }}
          >
            {t("Refresh")}
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("Dependencies (/readyz)")} subtitle={t("Real calls to Cosmos DB, Blob Storage, Azure OpenAI, Content Safety, Speech and ffmpeg")}>
          {ready.isLoading ? (
            <Skeleton h={140} />
          ) : (
            <Table
              head={[t("Dependency"), t("Status"), t("Latency"), t("Detail")]}
              rows={Object.entries(deps).map(([k, v]: any) => [
                tOpen("opsDependency", k),
                <StatusBadge key={k} s={v.ok ? "ok" : "failed"} />,
                t("{n} ms", { n: fmt.number(v.ms, 1) }),
                <span key={k + "d"} className="text-espresso-500">
                  {detail(v)}
                </span>,
              ])}
            />
          )}
        </Card>
        <Card title={t("Deployment")} subtitle={t("Keyless, managed-identity only")}>
          {s ? (
            <KV
              rows={[
                [
                  t("Mode"),
                  <Badge key="m" tone={s.mode === "azure" ? "good" : "warn"}>
                    {tOpen("opsMode", s.mode)}
                  </Badge>,
                ],
                [t("Version / build"), `${s.version} · ${s.build_id}`],
                [t("Region"), s.region],
                [t("Instance"), s.instance],
                [t("Repository"), tOpen("backend", s.backends.repository)],
                [t("Blob storage"), tOpen("backend", s.backends.blob_storage)],
                [t("LLM / image / speech"), `${tOpen("backend", s.backends.llm)} / ${tOpen("backend", s.backends.image)} / ${tOpen("backend", s.backends.speech)}`],
                [t("Telemetry"), s.telemetry_enabled ? t("OpenTelemetry → Application Insights (Entra-authenticated)") : t("disabled (offline)")],
                [t("Uptime"), t("{n} min", { n: fmt.number(Math.round(s.uptime_s / 60)) })],
              ]}
            />
          ) : (
            <Skeleton h={140} />
          )}
        </Card>
        <Card title={t("Guardrails")} subtitle={t("Rate limits, request-size limit, daily AI budget")}>
          {s && (
            <KV
              rows={[
                [t("Daily AI budget cap"), fmt.usd(s.budget.daily_cap_usd)],
                [t("Spent today"), fmt.usd(s.budget.spent_today_usd, 4)],
                [t("Guard refusals"), fmt.number(s.guard_refusals)],
                [t("Rate limit (mutating)"), t("{n}/min per IP", { n: s.limits.rate_per_ip_mutate_per_min })],
                [t("Rate limit (AI spend)"), t("{ip}/min per IP · {global}/min global", { ip: s.limits.rate_per_ip_spend_per_min, global: s.limits.rate_global_spend_per_min })],
                [t("Rate-limit rejections"), JSON.stringify(s.rate_limit_rejections)],
                [t("Max request body"), t("{n} MB", { n: fmt.number(s.limits.max_body_bytes / 1048576, 1) })],
                [t("AI cache"), t("{hits} hits / {misses} misses", { hits: s.cache.hits, misses: s.cache.misses })],
              ]}
            />
          )}
        </Card>
        <Card title={t("Jobs")} subtitle={t("Background job runner (persisted state, SSE progress)")}>
          {s && (
            <KV
              rows={[
                [t("Queued / running"), `${s.jobs.queued} / ${s.jobs.running}`],
                [t("Succeeded / failed"), `${s.jobs.succeeded} / ${s.jobs.failed}`],
                [t("Max concurrent"), s.limits.max_concurrent_jobs],
              ]}
            />
          )}
        </Card>
        <Card title={t("Per-route latency")} subtitle={t("In-process counters since start (full traces in Application Insights)")} className="lg:col-span-2" pad={false}>
          <div className="p-3">
            <Table
              head={[t("Route"), t("Calls"), t("Errors"), t("Avg ms"), t("Max ms")]}
              rows={(metrics.data?.routes ?? []).slice(0, 14).map((r: any) => [
                <code key={r.route} className="text-[12px]">
                  {r.route}
                </code>,
                r.count,
                r.errors,
                r.avg_ms,
                r.max_ms,
              ])}
              empty={t("No API calls recorded yet.")}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-24",
  routes: [{ path: "/ops", element: <OpsPage /> }],
  nav: { group: "Operate", label: msg("Ops & security"), to: "/ops", order: 50, icon: Activity },
};
