/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ClipboardCheck, MessageSquare, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api, getRole } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Input, PageHeader, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";
import { GuardianBadge, useActorName, useAuditLabel } from "../../components/common";
import { msg, useI18n } from "../../i18n";

const SLA_TONE: Record<string, any> = { on_track: "good", due_soon: "warn", overdue: "bad", closed: "neutral" };

function ApprovalCard({ a, onChange, showCampaign }: { a: any; onChange: () => void; showCampaign?: boolean }) {
  const { t, tEnum, fmt } = useI18n();
  const actorName = useActorName();
  const toast = useToast();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [asRole, setAsRole] = useState("");
  const isAdmin = getRole() === "admin";
  const decide = async (decision: string) => {
    setBusy(true);
    try {
      await api.post(`/api/approvals/${a.id}/decide`, { decision, comment, as_role: asRole || null });
      toast({ tone: "good", title: decision === "approve" ? t("Approved") : decision === "reject" ? t("Rejected") : t("Changes requested") });
      setComment("");
      onChange();
    } catch {
      /* refused (e.g. open Guardian blocks): the API error is already shown as a toast */
    } finally {
      setBusy(false);
    }
  };
  const done = new Set((a.decisions ?? []).filter((d: any) => d.decision === "approve").map((d: any) => d.role));
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {tEnum("gate", a.stage, a.stage_label)}: <span data-user-content>{a.title}</span> <span className="text-[12px] font-normal text-espresso-400">v{a.artifact_version}</span>
        </span>
      }
      subtitle={
        <span>
          {showCampaign && (
            <Link className="text-dawn-700 hover:underline" to={`/campaigns/${a.campaign_id}/approvals`}>
              {a.campaign_name}
            </Link>
          )}
          {showCampaign && " · "}
          {t("requested by {name} · {date}", { name: actorName(a.requested_by), date: fmt.dateTime(a.created_at) })}
        </span>
      }
      actions={
        <>
          <StatusBadge s={a.state} />
          <Badge tone={SLA_TONE[a.sla_state]}>{tEnum("sla", a.sla_state)}</Badge>
        </>
      }
      testId="approval-card"
    >
      <div className="flex flex-wrap items-center gap-3 text-[13px]">
        <GuardianBadge g={a.guardian_snapshot} />
        {a.required_roles.map((r: string) => (
          <span key={r} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] ${done.has(r) ? "border-sage-500 bg-sage-100 text-sage-600" : "border-cream-300"}`}>
            {done.has(r) ? <Check className="h-3 w-3" /> : null}
            {tEnum("roleChip", r)}
          </span>
        ))}
        <span className="text-espresso-400">{t("SLA {hours} h · due {date}", { hours: a.sla_hours, date: fmt.dateTime(a.sla_due) })}</span>
      </div>
      {(a.comments ?? []).length > 0 && (
        <ul className="mt-3 space-y-1.5 border-l-2 border-cream-300 pl-3 text-[12.5px]">
          {a.comments.map((c: any, i: number) => (
            <li key={i}>
              <MessageSquare className="mr-1 inline h-3 w-3 text-espresso-400" />
              <b>{actorName({ name: c.by, role: c.role })}</b> <span className="text-espresso-400">({tEnum("roleId", c.role)})</span>: <span data-user-content>{c.text}</span>
            </li>
          ))}
        </ul>
      )}
      {a.state === "pending" && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("Comment (optional)")} aria-label={t("comment")} className="w-64" />
          {isAdmin && a.pending_roles.length > 1 && (
            <select value={asRole} onChange={(e) => setAsRole(e.target.value)} className="rounded-lg border border-cream-300 bg-white px-2 py-2 text-[13px]" aria-label={t("act as role")}>
              <option value="">{t("act as {role}", { role: tEnum("roleChip", a.pending_roles[0]) })}</option>
              {a.pending_roles.map((r: string) => (
                <option key={r} value={r}>
                  {t("act as {role}", { role: tEnum("roleChip", r) })}
                </option>
              ))}
            </select>
          )}
          <Button variant="primary" icon={<Check className="h-4 w-4" />} loading={busy} onClick={() => decide("approve")}>
            {t("Approve")}
          </Button>
          <Button variant="outline" icon={<RotateCcw className="h-4 w-4" />} disabled={busy} onClick={() => decide("request_changes")}>
            {t("Request changes")}
          </Button>
          <Button variant="danger" icon={<X className="h-4 w-4" />} disabled={busy} onClick={() => decide("reject")}>
            {t("Reject")}
          </Button>
          {!a.actionable && a.actionable !== undefined && <span className="text-[12px] text-espresso-400">{t("waiting for {roles}", { roles: a.pending_roles.map((r: string) => tEnum("roleChip", r)).join(" + ") })}</span>}
        </div>
      )}
    </Card>
  );
}

function Inbox() {
  const { t, tEnum } = useI18n();
  const [mine, setMine] = useState(false);
  const q = useQuery({ queryKey: ["approvals", mine, getRole()], queryFn: () => api.get(`/api/approvals?mine=${mine}`), refetchInterval: 15000 });
  const d = q.data;
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-13 · Approvals & audit")}
        title={t("Approval inbox")}
        subtitle={t("Stage gates with role-based approval, SLAs and Guardian enforcement — a request with open blocking findings cannot be approved.")}
        actions={
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> {t("only what I can decide ({role})", { role: tEnum("roleChip", getRole()) })}
          </label>
        }
      />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Stat label={t("Pending")} value={d?.counts.pending ?? "—"} tone="dawn" />
        <Stat label={t("Approved")} value={d?.counts.approved ?? "—"} tone="good" />
        <Stat label={t("Changes requested")} value={d?.counts.changes_requested ?? "—"} />
        <Stat label={t("SLA overdue")} value={d?.overdue ?? "—"} tone={d?.overdue ? "bad" : undefined} />
      </div>
      {q.isLoading && <Skeleton h={160} />}
      {d && !d.approvals.length && <Empty title={t("Nothing waiting")} hint={t("Request an approval from a campaign workspace (Approvals tab).")} />}
      <div className="space-y-4" data-testid="approval-inbox">
        {(d?.approvals ?? []).map((a: any) => (
          <ApprovalCard key={a.id} a={a} showCampaign onChange={() => q.refetch()} />
        ))}
      </div>
    </div>
  );
}

function ApprovalsTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tn, tEnum, fmt, lang } = useI18n();
  const auditLabel = useAuditLabel();
  const actorName = useActorName();
  const id = campaign.campaign.id;
  const toast = useToast();
  const q = useQuery({ queryKey: ["capprovals", id, getRole()], queryFn: () => api.get(`/api/campaigns/${id}/approvals`) });
  const audit = useQuery({ queryKey: ["audit", id], queryFn: () => api.get(`/api/campaigns/${id}/audit?limit=40`) });
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = () => {
    q.refetch();
    audit.refetch();
    reload();
  };
  const request = async (stage: string) => {
    setBusy(stage);
    try {
      await api.post(`/api/campaigns/${id}/approvals`, { stage });
      toast({ tone: "good", title: t("Approval requested") });
      refresh();
    } finally {
      setBusy(null);
    }
  };
  const pipeline: any[] = q.data?.pipeline ?? [];
  const gates: any[] = q.data?.gates ?? [];
  const ver = audit.data?.verification;
  return (
    <div className="space-y-5">
      <Card title={t("Stage gates")} subtitle={t("Brief → Concept → Script → Storyboard → Final. Earlier gates must be approved first; the Guardian re-runs on every request and decision.")}>
        {q.isLoading ? (
          <Skeleton h={160} />
        ) : (
          <Table
            head={[t("Gate"), t("Artifact"), t("Guardian"), t("Required roles"), t("SLA"), t("State"), ""]}
            rows={pipeline.map((p) => {
              const g = gates.find((x) => x.id === p.gate);
              return [
                <b key="l">{tEnum("gate", p.gate, p.label)}</b>,
                p.artifact_id ? (
                  <span key="a">{t("v{version} · {status}", { version: String(p.version), status: tEnum("status", p.artifact_status) })}</span>
                ) : (
                  <span key="a" className="text-espresso-400">
                    {t("not created")}
                  </span>
                ),
                <GuardianBadge key="g" g={p.guardian} />,
                p.roles.map((r: string) => tEnum("roleChip", r)).join(" + "),
                g ? t("{n} h", { n: g.sla_hours }) : "—",
                p.approval_state ? (
                  <StatusBadge key="s" s={p.approval_state} />
                ) : p.artifact_status === "approved" ? (
                  <StatusBadge key="s" s="approved" />
                ) : (
                  <span key="s" className="text-espresso-400">
                    —
                  </span>
                ),
                p.artifact_id && p.approval_state !== "pending" && p.artifact_status !== "approved" ? (
                  <Button key="b" size="sm" variant="outline" icon={<ClipboardCheck className="h-3.5 w-3.5" />} loading={busy === p.gate} onClick={() => request(p.gate)}>
                    {t("Request approval")}
                  </Button>
                ) : null,
              ];
            })}
          />
        )}
      </Card>
      <div className="space-y-4" data-testid="campaign-approvals">
        {(q.data?.approvals ?? []).map((a: any) => (
          <ApprovalCard key={a.id} a={a} onChange={refresh} />
        ))}
      </div>
      <Card
        title={t("Audit trail")}
        subtitle={t("Immutable, hash-chained log: every entry commits to the previous one — any edit or deletion breaks verification.")}
        actions={
          ver && (
            <Badge tone={ver.ok ? "good" : "bad"}>
              <ShieldCheck className="h-3 w-3" /> {ver.ok ? tn(ver.entries, { one: "chain verified · {n} entries", other: "chain verified · {n} entries" }) : t("TAMPERED at #{n}", { n: ver.broken_at })}
            </Badge>
          )
        }
        pad={false}
      >
        <div className="p-3">
          <Table
            head={["#", t("Time"), t("Actor"), t("Action"), t("Hash")]}
            rows={(audit.data?.entries ?? []).map((e: any) => [
              e.seq,
              fmt.dateTime(e.ts),
              `${actorName(e.actor)} (${tEnum("roleId", e.actor?.role)})`,
              lang === "en" ? (
                <code key="a" className="text-[12px]">
                  {e.action}
                </code>
              ) : (
                <span key="a">
                  {auditLabel(e)} <code className="text-[11px] text-espresso-400">{e.action}</code>
                </span>
              ),
              <code key="h" className="text-[11px] text-espresso-400">
                {String(e.hash).slice(0, 12)}…
              </code>,
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-13",
  routes: [{ path: "/approvals", element: <Inbox /> }],
  nav: { group: "Review", label: msg("Approvals"), to: "/approvals", order: 20, icon: ClipboardCheck },
  workspaceTabs: [{ id: "approvals", label: msg("Approvals & audit"), order: 100, Component: ApprovalsTab }],
};
