/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { LayoutDashboard, Plus, PackageOpen, Clock } from "lucide-react";
import { api } from "../../api";
import { workspaceTabs, type FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, PageHeader, Skeleton, Stat, StatusBadge, Tabs, useToast } from "../../components/ui";
import { PipelineStepper, Tag, useActorName, useAuditLabel, useCampaign, useJobStarter } from "../../components/common";
import { msg, useI18n } from "../../i18n";

const GATE_TAB: Record<string, string> = { brief: "brief", concept: "strategy", script: "script", storyboard: "storyboard", final: "video" };

function Dashboard() {
  const { t, tn, tEnum, tOpen, tx, fmt } = useI18n();
  const auditLabel = useAuditLabel();
  const actorName = useActorName();
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api.get("/api/studio/overview"), refetchInterval: 10000 });
  const act = useQuery({ queryKey: ["activity"], queryFn: () => api.get("/api/studio/activity?limit=8"), refetchInterval: 10000 });
  const langs = useQuery({ queryKey: ["campaigns"], queryFn: () => api.get<any[]>("/api/campaigns", { quiet: true }), select: (r) => Object.fromEntries(r.map((c) => [c.id, c.language])) }); // the overview rows may not carry `language`
  const d = ov.data;
  const k = d?.kpis;
  return (
    <div data-testid="dashboard">
      <PageHeader
        eyebrow="Spotlight · Commercial Studio"
        title={t("Brief to broadcast")}
        subtitle={t("An AI crew — Strategist, Copywriter, Art Director, Director, Sound Designer, Localizer, Brand Guardian, Media Analyst — turns a brief into brand-safe, localized, measurable spots.")}
        actions={
          <Link to="/campaigns/new">
            <Button variant="accent" icon={<Plus className="h-4 w-4" />}>
              {t("New brief")}
            </Button>
          </Link>
        }
      />
      {!d ? (
        <Skeleton h={110} />
      ) : (
        <div className="grid gap-4 md:grid-cols-5">
          <Stat label={t("Campaigns")} value={fmt.number(k.campaigns)} hint={tn(k.pending_approvals, { one: "{n} approval(s) pending", other: "{n} approval(s) pending" })} />
          <Stat label={t("Spots rendered")} value={fmt.number(k.spots_rendered)} hint={tn(k.approved_videos, { one: "{n} approved videos", other: "{n} approved videos" })} />
          <Stat label={t("AI spend today")} value={fmt.usd(k.ai_spend_today_usd, 3)} hint={t("{amount} all-time", { amount: fmt.usd(k.ai_spend_total_usd, 3) })} tone="dawn" />
          <Stat label={t("$ / approved asset")} value={k.cost_cost_per_approved_asset_usd != null ? fmt.usd(k.cost_cost_per_approved_asset_usd, 3) : "—"} hint={t("vs agency {amount} (assumption)", { amount: fmt.usd(k.cost_agency_baseline_per_asset_usd, 0) })} tone="good" />
          <Stat label={t("Open Guardian blocks")} value={fmt.number(k.guardian_blocks_open)} hint={t("Approval is blocked until resolved")} tone={k.guardian_blocks_open ? "bad" : undefined} />
        </div>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <h2 className="font-display text-[20px] font-semibold">{t("Campaigns")}</h2>
          {(d?.campaigns ?? []).map((c: any) => (
            <Card key={c.id} className="transition-shadow hover:shadow-md">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link to={`/campaigns/${c.id}`} className="font-display text-[19px] font-semibold text-espresso-900 hover:text-dawn-600">
                    {c.name}
                  </Link>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <StatusBadge s={c.status} />
                    {c.history && <Badge>{t("history")}</Badge>}
                    {(c.language ?? langs.data?.[c.id]) && (
                      <span title={t("Campaign language")} data-testid="campaign-lang-badge">
                        <Badge tone="dark">{String(c.language ?? langs.data?.[c.id]).toUpperCase()}</Badge>
                      </span>
                    )}
                    {c.markets.map((m: string) => (
                      <Tag key={m}>{tOpen("territory", m)}</Tag>
                    ))}
                    {c.channels.map((m: string) => (
                      <Tag key={m}>{tOpen("channel", m)}</Tag>
                    ))}
                  </div>
                </div>
                <div className="text-right text-[12.5px] text-espresso-500">
                  <div>{tn(c.spots, { one: "{n} spot(s)", other: "{n} spot(s)" })}</div>
                  <div>{t("AI spend {amount}", { amount: fmt.usd(c.spent_usd, 3) })}</div>
                </div>
              </div>
              <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3">
                <ol className="flex items-center gap-1" aria-label={t("pipeline")}>
                  {c.pipeline.map((p: any) => (
                    <li
                      key={p.gate}
                      title={`${tEnum("gate", p.gate, p.label)}: ${tEnum("pipelineState", p.state)}${p.verdict ? " · " + t("guardian {verdict}", { verdict: tEnum("verdict", p.verdict) }) : ""}`}
                      className={`h-2.5 w-9 rounded-full ${p.state === "approved" ? "bg-sage-500" : p.verdict === "block" ? "bg-roast-500" : p.state === "pending" ? "bg-dawn-500" : p.state === "empty" ? "bg-cream-200" : "bg-cream-300"}`}
                    />
                  ))}
                </ol>
                <Link to={`/campaigns/${c.id}`} className="text-[13px] font-medium text-dawn-600 hover:underline">
                  {t("Open workspace →")}
                </Link>
              </div>
            </Card>
          ))}
          {d && !d.campaigns.length && <Empty title={t("No campaigns yet")} hint={t("Create one from a pasted brief.")} />}
        </div>
        <div className="space-y-4">
          <Card title={t("Rights alerts")} subtitle={t("Consent & licence expiry (CS-03)")}>
            {(d?.rights_alerts ?? []).length === 0 && <div className="text-[13px] text-espresso-500">{t("Nothing expiring in 45 days.")}</div>}
            <ul className="space-y-2">
              {(d?.rights_alerts ?? []).map((a: any) => (
                <li key={a.id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span>
                    <b>{a.title}</b> <span className="text-espresso-500">({tEnum("rightsKind", a.kind)})</span>
                  </span>
                  <Badge tone={a.state === "expired" ? "bad" : "warn"}>{a.state === "expired" ? tn(-a.days_left, { one: "expired {n}d ago", other: "expired {n}d ago" }) : tn(a.days_left, { one: "{n}d left", other: "{n}d left" })}</Badge>
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t("Recent activity")} subtitle={t("Hash-chained audit trail (CS-13)")}>
            <ul className="space-y-2 text-[12.5px]">
              {(act.data?.activity ?? []).map((a: any, i: number) => (
                <li key={i} className="flex gap-2">
                  <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-espresso-400" />
                  <div className="min-w-0">
                    <span className="break-words font-medium text-espresso-800">{auditLabel(a)}</span> <span className="text-espresso-500">· {actorName(a.actor)}</span>
                    <div className="text-espresso-400">
                      {a.campaign ?? t("studio")} · {fmt.dateTime(a.ts)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t("Experiments")} subtitle={t("Bandit allocation (CS-17)")}>
            {(d?.experiments ?? []).length === 0 && (
              <div className="text-[13px] text-espresso-500">
                {tx("None yet — <start>start one</start>.", {
                  start: (chunks) => (
                    <Link className="text-dawn-600 underline" to="/experiments">
                      {chunks}
                    </Link>
                  ),
                })}
              </div>
            )}
            {(d?.experiments ?? []).map((e: any) => (
              <Link key={e.id} to="/experiments" className="block text-[13px] hover:text-dawn-600">
                {e.name} <StatusBadge s={e.status} />
              </Link>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Workspace() {
  const { t, tn, tOpen, fmt } = useI18n();
  const { id = "", tab } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const c = useCampaign(id);
  const exporter = useJobStarter((j) => {
    if (j.status === "succeeded") toast({ tone: "good", title: t("Campaign pack ready"), body: t("{files} — download from the Library", { files: tn(j.result.files.length, { one: "{n} files", other: "{n} files" }) }) });
    c.reload();
  });
  const first = workspaceTabs[0]?.id;
  if (!tab && first) return <Navigate to={`/campaigns/${id}/${first}`} replace />;
  if (c.isLoading) return <Skeleton h={300} />;
  if (c.error || !c.data)
    return (
      <Empty
        title={t("Campaign not found")}
        action={
          <Link to="/" className="text-dawn-600 underline">
            {t("Back to dashboard")}
          </Link>
        }
      />
    );
  const camp = c.data.campaign;
  const active = workspaceTabs.find((x) => x.id === tab) ?? workspaceTabs[0];
  const Active = active?.Component;
  return (
    <div data-testid="workspace">
      <PageHeader
        eyebrow={t("Creative workspace")}
        title={camp.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge s={camp.status} />
            {camp.language && (
              <span title={t("Campaign language")} data-testid="campaign-lang-badge">
                <Badge tone="dark">{String(camp.language).toUpperCase()}</Badge>
              </span>
            )}
            {camp.markets?.map((m: string) => (
              <Tag key={m}>{tOpen("territory", m)}</Tag>
            ))}
            {camp.channels?.map((m: string) => (
              <Tag key={m}>{tOpen("channel", m)}</Tag>
            ))}
            <span className="text-espresso-500">· {t("AI spend {spent} of {cap} cap", { spent: fmt.usd(c.data.summary.ai_spend_usd, 3), cap: fmt.usd(camp.budget_cap_usd, 2) })}</span>
          </span>
        }
        actions={
          <Button variant="outline" icon={<PackageOpen className="h-4 w-4" />} loading={exporter.busy} onClick={() => exporter.start(`/api/campaigns/${id}/export`)}>
            {t("Export campaign pack")}
          </Button>
        }
      />
      {exporter.node && <div className="mb-4">{exporter.node}</div>}
      <div className="mb-5">
        <PipelineStepper pipeline={c.data.pipeline} onPick={(g) => nav(`/campaigns/${id}/${GATE_TAB[g] ?? "approvals"}`)} />
      </div>
      <Tabs tabs={workspaceTabs.map((x) => ({ id: x.id, label: t(x.label) }))} value={active?.id ?? ""} onChange={(v) => nav(`/campaigns/${id}/${v}`)} />
      <div className="pt-5" data-testid={`tab-${active?.id}`}>
        {Active && <Active campaign={c.data} reload={c.reload} />}
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-20",
  routes: [
    { path: "/", element: <Dashboard /> },
    { path: "/campaigns/:id", element: <Workspace /> },
    { path: "/campaigns/:id/:tab", element: <Workspace /> },
  ],
  nav: { group: "Studio", label: msg("Dashboard"), to: "/", order: 0, icon: LayoutDashboard },
};
