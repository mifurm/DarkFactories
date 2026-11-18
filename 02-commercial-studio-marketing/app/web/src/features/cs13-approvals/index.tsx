/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ClipboardCheck, MessageSquare, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api, fmtDate, getRole } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Input, PageHeader, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";
import { GuardianBadge } from "../../components/common";

const SLA_TONE: Record<string, any> = { on_track: "good", due_soon: "warn", overdue: "bad", closed: "neutral" };

function ApprovalCard({ a, onChange, showCampaign }: { a: any; onChange: () => void; showCampaign?: boolean }) {
  const toast = useToast();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [asRole, setAsRole] = useState("");
  const isAdmin = getRole() === "admin";
  const decide = async (decision: string) => {
    setBusy(true);
    try {
      await api.post(`/api/approvals/${a.id}/decide`, { decision, comment, as_role: asRole || null });
      toast({ tone: "good", title: decision === "approve" ? "Approved" : decision === "reject" ? "Rejected" : "Changes requested" });
      setComment("");
      onChange();
    } finally {
      setBusy(false);
    }
  };
  const done = new Set((a.decisions ?? []).filter((d: any) => d.decision === "approve").map((d: any) => d.role));
  return (
    <Card
      title={<span className="flex flex-wrap items-center gap-2">{a.stage_label}: {a.title} <span className="text-[12px] font-normal text-espresso-400">v{a.artifact_version}</span></span>}
      subtitle={<span>{showCampaign && <Link className="text-dawn-700 hover:underline" to={`/campaigns/${a.campaign_id}/approvals`}>{a.campaign_name}</Link>}{showCampaign && " · "}requested by {a.requested_by?.name} · {fmtDate(a.created_at)}</span>}
      actions={<><StatusBadge s={a.state} /><Badge tone={SLA_TONE[a.sla_state]}>{a.sla_state.replace("_", " ")}</Badge></>}
      testId="approval-card"
    >
      <div className="flex flex-wrap items-center gap-3 text-[13px]">
        <GuardianBadge g={a.guardian_snapshot} />
        {a.required_roles.map((r: string) => (
          <span key={r} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] ${done.has(r) ? "border-sage-500 bg-sage-100 text-sage-600" : "border-cream-300"}`}>
            {done.has(r) ? <Check className="h-3 w-3" /> : null}{r.replace("_", " ")}
          </span>
        ))}
        <span className="text-espresso-400">SLA {a.sla_hours} h · due {fmtDate(a.sla_due)}</span>
      </div>
      {(a.comments ?? []).length > 0 && (
        <ul className="mt-3 space-y-1.5 border-l-2 border-cream-300 pl-3 text-[12.5px]">
          {a.comments.map((c: any, i: number) => <li key={i}><MessageSquare className="mr-1 inline h-3 w-3 text-espresso-400" /><b>{c.by}</b> <span className="text-espresso-400">({c.role})</span>: {c.text}</li>)}
        </ul>
      )}
      {a.state === "pending" && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (optional)" aria-label="comment" className="max-w-xs" />
          {isAdmin && a.pending_roles.length > 1 && (
            <select value={asRole} onChange={(e) => setAsRole(e.target.value)} className="rounded-lg border border-cream-300 bg-white px-2 py-2 text-[13px]" aria-label="act as role">
              <option value="">act as {a.pending_roles[0]}</option>
              {a.pending_roles.map((r: string) => <option key={r} value={r}>act as {r}</option>)}
            </select>
          )}
          <Button variant="primary" icon={<Check className="h-4 w-4" />} loading={busy} onClick={() => decide("approve")}>Approve</Button>
          <Button variant="outline" icon={<RotateCcw className="h-4 w-4" />} disabled={busy} onClick={() => decide("request_changes")}>Request changes</Button>
          <Button variant="danger" icon={<X className="h-4 w-4" />} disabled={busy} onClick={() => decide("reject")}>Reject</Button>
          {!a.actionable && a.actionable !== undefined && <span className="text-[12px] text-espresso-400">waiting for {a.pending_roles.join(" + ")}</span>}
        </div>
      )}
    </Card>
  );
}

function Inbox() {
  const [mine, setMine] = useState(false);
  const q = useQuery({ queryKey: ["approvals", mine, getRole()], queryFn: () => api.get(`/api/approvals?mine=${mine}`), refetchInterval: 15000 });
  const d = q.data;
  return (
    <div>
      <PageHeader eyebrow="CS-13 · Approvals & audit" title="Approval inbox" subtitle="Stage gates with role-based approval, SLAs and Guardian enforcement — a request with open blocking findings cannot be approved." actions={<label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> only what I can decide ({getRole().replace("_", " ")})</label>} />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Stat label="Pending" value={d?.counts.pending ?? "—"} tone="dawn" />
        <Stat label="Approved" value={d?.counts.approved ?? "—"} tone="good" />
        <Stat label="Changes requested" value={d?.counts.changes_requested ?? "—"} />
        <Stat label="SLA overdue" value={d?.overdue ?? "—"} tone={d?.overdue ? "bad" : undefined} />
      </div>
      {q.isLoading && <Skeleton h={160} />}
      {d && !d.approvals.length && <Empty title="Nothing waiting" hint="Request an approval from a campaign workspace (Approvals tab)." />}
      <div className="space-y-4" data-testid="approval-inbox">
        {(d?.approvals ?? []).map((a: any) => <ApprovalCard key={a.id} a={a} showCampaign onChange={() => q.refetch()} />)}
      </div>
    </div>
  );
}

function ApprovalsTab({ campaign, reload }: WorkspaceTabProps) {
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
      toast({ tone: "good", title: "Approval requested" });
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
      <Card title="Stage gates" subtitle="Brief → Concept → Script → Storyboard → Final. Earlier gates must be approved first; the Guardian re-runs on every request and decision.">
        {q.isLoading ? <Skeleton h={160} /> : (
          <Table
            head={["Gate", "Artifact", "Guardian", "Required roles", "SLA", "State", ""]}
            rows={pipeline.map((p) => {
              const g = gates.find((x) => x.id === p.gate);
              return [
                <b key="l">{p.label}</b>,
                p.artifact_id ? <span key="a">v{p.version} · {p.artifact_status}</span> : <span key="a" className="text-espresso-400">not created</span>,
                <GuardianBadge key="g" g={p.guardian} />,
                p.roles.map((r: string) => r.replace("_", " ")).join(" + "),
                g ? `${g.sla_hours} h` : "—",
                p.approval_state ? <StatusBadge key="s" s={p.approval_state} /> : p.artifact_status === "approved" ? <StatusBadge key="s" s="approved" /> : <span key="s" className="text-espresso-400">—</span>,
                p.artifact_id && p.approval_state !== "pending" && p.artifact_status !== "approved" ? <Button key="b" size="sm" variant="outline" icon={<ClipboardCheck className="h-3.5 w-3.5" />} loading={busy === p.gate} onClick={() => request(p.gate)}>Request approval</Button> : null,
              ];
            })}
          />
        )}
      </Card>
      <div className="space-y-4" data-testid="campaign-approvals">
        {(q.data?.approvals ?? []).map((a: any) => <ApprovalCard key={a.id} a={a} onChange={refresh} />)}
      </div>
      <Card
        title="Audit trail"
        subtitle="Immutable, hash-chained log: every entry commits to the previous one — any edit or deletion breaks verification."
        actions={ver && <Badge tone={ver.ok ? "good" : "bad"}><ShieldCheck className="h-3 w-3" /> {ver.ok ? `chain verified · ${ver.entries} entries` : `TAMPERED at #${ver.broken_at}`}</Badge>}
        pad={false}
      >
        <div className="p-3">
          <Table
            head={["#", "Time", "Actor", "Action", "Hash"]}
            rows={(audit.data?.entries ?? []).map((e: any) => [e.seq, fmtDate(e.ts), `${e.actor?.name} (${e.actor?.role})`, <code key="a" className="text-[12px]">{e.action}</code>, <code key="h" className="text-[11px] text-espresso-400">{String(e.hash).slice(0, 12)}…</code>])}
          />
        </div>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-13",
  routes: [{ path: "/approvals", element: <Inbox /> }],
  nav: { group: "Review", label: "Approvals", to: "/approvals", order: 20, icon: ClipboardCheck },
  workspaceTabs: [{ id: "approvals", label: "Approvals & audit", order: 100, Component: ApprovalsTab }],
};
