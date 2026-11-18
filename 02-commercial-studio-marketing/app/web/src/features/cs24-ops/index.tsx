/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { api, fmtNum, fmtUsd } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, KV, PageHeader, Skeleton, StatusBadge, Table } from "../../components/ui";

function OpsPage() {
  const status = useQuery({ queryKey: ["ops-status"], queryFn: () => api.get("/api/ops/status"), refetchInterval: 15000 });
  const metrics = useQuery({ queryKey: ["ops-metrics"], queryFn: () => api.get("/api/ops/metrics"), refetchInterval: 15000 });
  const ready = useQuery({ queryKey: ["readyz"], queryFn: () => api.get("/readyz?deep=true", { quiet: true }).catch((e) => e), staleTime: 20000 });
  const s = status.data;
  const deps = (ready.data as any)?.dependencies ?? {};
  return (
    <div>
      <PageHeader
        eyebrow="CS-24 · Observability, security & IaC"
        title="Operations"
        subtitle="Live health, telemetry configuration, AI usage meter, rate limits and the daily budget guard of this deployment."
        actions={
          <Button variant="outline" onClick={() => { status.refetch(); metrics.refetch(); ready.refetch(); }}>
            Refresh
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Dependencies (/readyz)" subtitle="Real calls to Cosmos DB, Blob Storage, Azure OpenAI, Content Safety, Speech and ffmpeg">
          {ready.isLoading ? (
            <Skeleton h={140} />
          ) : (
            <Table
              head={["Dependency", "Status", "Latency", "Detail"]}
              rows={Object.entries(deps).map(([k, v]: any) => [k, <StatusBadge key={k} s={v.ok ? "ok" : "failed"} />, `${v.ms} ms`, <span key={k + "d"} className="text-espresso-500">{v.backend || v.version || v.error || ""}</span>])}
            />
          )}
        </Card>
        <Card title="Deployment" subtitle="Keyless, managed-identity only">
          {s ? (
            <KV
              rows={[
                ["Mode", <Badge key="m" tone={s.mode === "azure" ? "good" : "warn"}>{s.mode}</Badge>],
                ["Version / build", `${s.version} · ${s.build_id}`],
                ["Region", s.region],
                ["Instance", s.instance],
                ["Repository", s.backends.repository],
                ["Blob storage", s.backends.blob_storage],
                ["LLM / image / speech", `${s.backends.llm} / ${s.backends.image} / ${s.backends.speech}`],
                ["Telemetry", s.telemetry_enabled ? "OpenTelemetry → Application Insights (Entra-authenticated)" : "disabled (offline)"],
                ["Uptime", `${Math.round(s.uptime_s / 60)} min`],
              ]}
            />
          ) : (
            <Skeleton h={140} />
          )}
        </Card>
        <Card title="Guardrails" subtitle="Rate limits, request-size limit, daily AI budget">
          {s && (
            <KV
              rows={[
                ["Daily AI budget cap", fmtUsd(s.budget.daily_cap_usd)],
                ["Spent today", fmtUsd(s.budget.spent_today_usd, 4)],
                ["Guard refusals", fmtNum(s.guard_refusals)],
                ["Rate limit (mutating)", `${s.limits.rate_per_ip_mutate_per_min}/min per IP`],
                ["Rate limit (AI spend)", `${s.limits.rate_per_ip_spend_per_min}/min per IP · ${s.limits.rate_global_spend_per_min}/min global`],
                ["Rate-limit rejections", JSON.stringify(s.rate_limit_rejections)],
                ["Max request body", `${fmtNum(s.limits.max_body_bytes / 1048576, 1)} MB`],
                ["AI cache", `${s.cache.hits} hits / ${s.cache.misses} misses`],
              ]}
            />
          )}
        </Card>
        <Card title="Jobs" subtitle="Background job runner (persisted state, SSE progress)">
          {s && (
            <KV
              rows={[
                ["Queued / running", `${s.jobs.queued} / ${s.jobs.running}`],
                ["Succeeded / failed", `${s.jobs.succeeded} / ${s.jobs.failed}`],
                ["Max concurrent", s.limits.max_concurrent_jobs],
              ]}
            />
          )}
        </Card>
        <Card title="Per-route latency" subtitle="In-process counters since start (full traces in Application Insights)" className="lg:col-span-2" pad={false}>
          <div className="p-3">
            <Table
              head={["Route", "Calls", "Errors", "Avg ms", "Max ms"]}
              rows={(metrics.data?.routes ?? []).slice(0, 14).map((r: any) => [<code key={r.route} className="text-[12px]">{r.route}</code>, r.count, r.errors, r.avg_ms, r.max_ms])}
              empty="No API calls recorded yet."
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
  nav: { group: "Operate", label: "Ops & security", to: "/ops", order: 50, icon: Activity },
};
