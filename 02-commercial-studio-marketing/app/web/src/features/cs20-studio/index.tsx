/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { LayoutDashboard, Plus, PackageOpen, Clock } from "lucide-react";
import { api, fmtDate, fmtUsd } from "../../api";
import { workspaceTabs, type FeatureDef } from "../../registry";
import { Badge, Button, Card, Empty, PageHeader, Skeleton, Stat, StatusBadge, Tabs, useToast } from "../../components/ui";
import { PipelineStepper, Tag, useCampaign, useJobStarter } from "../../components/common";

const GATE_TAB: Record<string, string> = { brief: "brief", concept: "strategy", script: "script", storyboard: "storyboard", final: "video" };

function Dashboard() {
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api.get("/api/studio/overview"), refetchInterval: 10000 });
  const act = useQuery({ queryKey: ["activity"], queryFn: () => api.get("/api/studio/activity?limit=8"), refetchInterval: 10000 });
  const d = ov.data;
  const k = d?.kpis;
  return (
    <div data-testid="dashboard">
      <PageHeader
        eyebrow="Spotlight · Commercial Studio"
        title="Brief to broadcast"
        subtitle="An AI crew — Strategist, Copywriter, Art Director, Director, Sound Designer, Localizer, Brand Guardian, Media Analyst — turns a brief into brand-safe, localized, measurable spots."
        actions={
          <Link to="/campaigns/new">
            <Button variant="accent" icon={<Plus className="h-4 w-4" />}>
              New brief
            </Button>
          </Link>
        }
      />
      {!d ? (
        <Skeleton h={110} />
      ) : (
        <div className="grid gap-4 md:grid-cols-5">
          <Stat label="Campaigns" value={k.campaigns} hint={`${k.pending_approvals} approval(s) pending`} />
          <Stat label="Spots rendered" value={k.spots_rendered} hint={`${k.approved_videos} approved videos`} />
          <Stat label="AI spend today" value={fmtUsd(k.ai_spend_today_usd, 3)} hint={`${fmtUsd(k.ai_spend_total_usd, 3)} all-time`} tone="dawn" />
          <Stat label="$ / approved asset" value={k.cost_cost_per_approved_asset_usd != null ? fmtUsd(k.cost_cost_per_approved_asset_usd, 3) : "—"} hint={`vs agency ${fmtUsd(k.cost_agency_baseline_per_asset_usd, 0)} (assumption)`} tone="good" />
          <Stat label="Open Guardian blocks" value={k.guardian_blocks_open} hint="Approval is blocked until resolved" tone={k.guardian_blocks_open ? "bad" : undefined} />
        </div>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <h2 className="font-display text-[20px] font-semibold">Campaigns</h2>
          {(d?.campaigns ?? []).map((c: any) => (
            <Card key={c.id} className="transition-shadow hover:shadow-md">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <Link to={`/campaigns/${c.id}`} className="font-display text-[19px] font-semibold text-espresso-900 hover:text-dawn-600">
                    {c.name}
                  </Link>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <StatusBadge s={c.status} />
                    {c.history && <Badge>history</Badge>}
                    {c.markets.map((m: string) => (
                      <Tag key={m}>{m}</Tag>
                    ))}
                    {c.channels.map((m: string) => (
                      <Tag key={m}>{m}</Tag>
                    ))}
                  </div>
                </div>
                <div className="text-right text-[12.5px] text-espresso-500">
                  <div>{c.spots} spot(s)</div>
                  <div>AI spend {fmtUsd(c.spent_usd, 3)}</div>
                </div>
              </div>
              <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3">
                <ol className="flex items-center gap-1" aria-label="pipeline">
                  {c.pipeline.map((p: any) => (
                    <li key={p.gate} title={`${p.label}: ${p.state}${p.verdict ? " · guardian " + p.verdict : ""}`} className={`h-2.5 w-9 rounded-full ${p.state === "approved" ? "bg-sage-500" : p.verdict === "block" ? "bg-roast-500" : p.state === "pending" ? "bg-dawn-500" : p.state === "empty" ? "bg-cream-200" : "bg-cream-300"}`} />
                  ))}
                </ol>
                <Link to={`/campaigns/${c.id}`} className="text-[13px] font-medium text-dawn-600 hover:underline">
                  Open workspace →
                </Link>
              </div>
            </Card>
          ))}
          {d && !d.campaigns.length && <Empty title="No campaigns yet" hint="Create one from a pasted brief." />}
        </div>
        <div className="space-y-4">
          <Card title="Rights alerts" subtitle="Consent & licence expiry (CS-03)">
            {(d?.rights_alerts ?? []).length === 0 && <div className="text-[13px] text-espresso-500">Nothing expiring in 45 days.</div>}
            <ul className="space-y-2">
              {(d?.rights_alerts ?? []).map((a: any) => (
                <li key={a.id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span>
                    <b>{a.title}</b> <span className="text-espresso-500">({a.kind})</span>
                  </span>
                  <Badge tone={a.state === "expired" ? "bad" : "warn"}>{a.state === "expired" ? `expired ${-a.days_left}d ago` : `${a.days_left}d left`}</Badge>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Recent activity" subtitle="Hash-chained audit trail (CS-13)">
            <ul className="space-y-2 text-[12.5px]">
              {(act.data?.activity ?? []).map((a: any, i: number) => (
                <li key={i} className="flex gap-2">
                  <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-espresso-400" />
                  <div>
                    <span className="font-medium text-espresso-800">{a.action}</span> <span className="text-espresso-500">· {a.actor?.name}</span>
                    <div className="text-espresso-400">
                      {a.campaign ?? "studio"} · {fmtDate(a.ts)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Experiments" subtitle="Bandit allocation (CS-17)">
            {(d?.experiments ?? []).length === 0 && (
              <div className="text-[13px] text-espresso-500">
                None yet —{" "}
                <Link className="text-dawn-600 underline" to="/experiments">
                  start one
                </Link>
                .
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
  const { id = "", tab } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const c = useCampaign(id);
  const exporter = useJobStarter((j) => {
    if (j.status === "succeeded") toast({ tone: "good", title: "Campaign pack ready", body: `${j.result.files.length} files — download from the Library` });
    c.reload();
  });
  const first = workspaceTabs[0]?.id;
  if (!tab && first) return <Navigate to={`/campaigns/${id}/${first}`} replace />;
  if (c.isLoading) return <Skeleton h={300} />;
  if (c.error || !c.data) return <Empty title="Campaign not found" action={<Link to="/" className="text-dawn-600 underline">Back to dashboard</Link>} />;
  const camp = c.data.campaign;
  const active = workspaceTabs.find((t) => t.id === tab) ?? workspaceTabs[0];
  const Active = active?.Component;
  return (
    <div data-testid="workspace">
      <PageHeader
        eyebrow="Creative workspace"
        title={camp.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge s={camp.status} />
            {camp.markets?.map((m: string) => (
              <Tag key={m}>{m}</Tag>
            ))}
            {camp.channels?.map((m: string) => (
              <Tag key={m}>{m}</Tag>
            ))}
            <span className="text-espresso-500">
              · AI spend {fmtUsd(c.data.summary.ai_spend_usd, 3)} of {fmtUsd(camp.budget_cap_usd, 2)} cap
            </span>
          </span>
        }
        actions={
          <Button variant="outline" icon={<PackageOpen className="h-4 w-4" />} loading={exporter.busy} onClick={() => exporter.start(`/api/campaigns/${id}/export`)}>
            Export campaign pack
          </Button>
        }
      />
      {exporter.node && <div className="mb-4">{exporter.node}</div>}
      <div className="mb-5">
        <PipelineStepper pipeline={c.data.pipeline} onPick={(g) => nav(`/campaigns/${id}/${GATE_TAB[g] ?? "approvals"}`)} />
      </div>
      <Tabs tabs={workspaceTabs.map((t) => ({ id: t.id, label: t.label }))} value={active?.id ?? ""} onChange={(v) => nav(`/campaigns/${id}/${v}`)} />
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
  nav: { group: "Studio", label: "Dashboard", to: "/", order: 0, icon: LayoutDashboard },
};
