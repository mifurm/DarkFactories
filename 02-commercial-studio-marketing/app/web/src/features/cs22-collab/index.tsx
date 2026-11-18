/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Send, Trash2, Users } from "lucide-react";
import { ROLES, api, fmtDate, setRole } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, KV, PageHeader, Select, Skeleton, StatusBadge, Table, useToast } from "../../components/ui";

function TeamPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["team-members"], queryFn: () => api.get("/api/team/members") });
  const roles = useQuery({ queryKey: ["team-roles"], queryFn: () => api.get("/api/team/roles") });
  const hooks = useQuery({ queryKey: ["hooks"], queryFn: () => api.get("/api/team/webhooks") });
  const deliveries = useQuery({ queryKey: ["deliveries"], queryFn: () => api.get("/api/team/deliveries?limit=8"), refetchInterval: 10000 });
  const info = useQuery({ queryKey: ["team-api"], queryFn: () => api.get("/api/team/api") });
  const [form, setForm] = useState({ name: "Creative channel", url: "", format: "teams", events: ["approval.requested", "approval.approved", "budget.alert"] });
  const sink = hooks.data?.internal_sink as string | undefined;
  const create = async () => {
    await api.post("/api/team/webhooks", form);
    toast({ tone: "good", title: "Webhook created" });
    hooks.refetch();
  };
  const test = async (id: string) => {
    const r = await api.post(`/api/team/webhooks/${id}/test`);
    toast({ tone: r.ok ? "good" : "warn", title: r.ok ? "Test message delivered" : "Delivery failed", body: r.error ?? `HTTP ${r.status}` });
    deliveries.refetch();
  };
  const del = async (id: string) => {
    await api.del(`/api/team/webhooks/${id}`);
    hooks.refetch();
  };
  const toggleEvt = (e: string) => setForm((f) => ({ ...f, events: f.events.includes(e) ? f.events.filter((x) => x !== e) : [...f.events, e] }));
  const perms: string[] = roles.data?.permissions ?? [];
  return (
    <div>
      <PageHeader eyebrow="CS-22 · Collaboration, roles & integrations" title="Team & integrations" subtitle="Six roles enforced on the API, Teams/Slack-compatible webhook notifications (SSRF-guarded, allow-listed), campaign-pack export and a documented REST API. Demo identities are self-declared; production uses Entra ID app roles." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Roster" subtitle={members.data?.note}>
          {!members.data ? <Skeleton h={140} /> : (
            <ul className="divide-y divide-cream-200 text-[13px]">
              {members.data.members.map((m: any) => (
                <li key={m.name} className="flex items-center justify-between py-2">
                  <span><b>{m.name}</b><br /><span className="text-espresso-500">{m.title}</span></span>
                  <span className="flex items-center gap-2"><Badge tone="dark">{m.role.replace("_", " ")}</Badge><Button size="sm" variant="outline" onClick={() => { setRole(m.role); qc.invalidateQueries(); toast({ tone: "info", title: `Now acting as ${ROLES.find((r) => r.id === m.role)?.label}` }); }}>Act as</Button></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="REST API" subtitle="Everything in the UI is an API call">
          {info.data && (
            <KV rows={[["OpenAPI", <a key="o" className="text-dawn-700 underline" href={info.data.openapi}>{info.data.openapi}</a>], ["Interactive docs", <a key="d" className="text-dawn-700 underline" href={info.data.docs}>{info.data.docs}</a>], ["Auth", info.data.auth], ["Rate limits", `${info.data.rate_limits.spend_per_ip_per_min}/min AI-spending · ${info.data.rate_limits.mutate_per_ip_per_min}/min writes per IP`], ["Streaming", info.data.streaming]]} />
          )}
          {info.data && <ul className="mt-3 list-disc pl-5 text-[12.5px] text-espresso-600">{info.data.examples.map((e: string) => <li key={e}><code>{e}</code></li>)}</ul>}
        </Card>
      </div>
      <Card className="mt-5" title="Roles & permissions" subtitle="Enforced server-side on every mutating endpoint" pad={false}>
        <div className="scroll-thin overflow-x-auto p-3" data-testid="permission-matrix">
          {!roles.data ? <Skeleton h={120} /> : (
            <table className="w-full text-[12.5px]">
              <thead><tr className="border-b border-cream-300 text-left text-[11px] uppercase tracking-wider text-espresso-500"><th className="px-2 py-1.5">Permission</th>{roles.data.roles.map((r: any) => <th key={r.id} className="px-2 py-1.5 text-center">{r.label}</th>)}</tr></thead>
              <tbody>
                {perms.map((p) => (
                  <tr key={p} className="border-b border-cream-200 last:border-0"><td className="px-2 py-1"><code>{p}</code></td>{roles.data.roles.map((r: any) => <td key={r.id} className="px-2 py-1 text-center">{r.permissions.includes(p) ? <Check className="mx-auto h-3.5 w-3.5 text-sage-600" /> : <span className="text-cream-300">·</span>}</td>)}</tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card title="Webhooks" subtitle={`Teams (MessageCard), Slack, or generic JSON · allow-list: ${(hooks.data?.allow_list ?? []).filter((x: string) => x !== sink).join(", ")}`}>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Format"><Select value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })}><option value="teams">Microsoft Teams</option><option value="slack">Slack</option><option value="generic">Generic JSON</option></Select></Field>
            </div>
            <Field label="URL" hint={sink ? <span>Demo sink (always works): <button className="underline" onClick={() => setForm({ ...form, url: sink })}>use internal sink</button></span> : undefined}><Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://contoso.webhook.office.com/…" aria-label="webhook url" /></Field>
            <div className="flex flex-wrap gap-1.5">{(hooks.data?.events ?? []).map((e: string) => <button key={e} onClick={() => toggleEvt(e)} aria-pressed={form.events.includes(e)} className={`rounded-full border px-2 py-0.5 text-[11.5px] ${form.events.includes(e) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300"}`}>{e}</button>)}</div>
            <Button variant="accent" disabled={!form.url} onClick={create}>Add webhook</Button>
          </div>
          <ul className="mt-4 divide-y divide-cream-200 text-[13px]">
            {(hooks.data?.webhooks ?? []).map((h: any) => (
              <li key={h.id} className="flex items-center justify-between gap-2 py-2"><span><b>{h.name}</b> <Badge>{h.format}</Badge><br /><span className="text-[11.5px] text-espresso-400">{h.url.slice(0, 60)}</span></span><span className="flex gap-1.5"><Button size="sm" variant="outline" icon={<Send className="h-3.5 w-3.5" />} onClick={() => test(h.id)}>Test</Button><Button size="sm" variant="ghost" aria-label="delete webhook" onClick={() => del(h.id)}><Trash2 className="h-3.5 w-3.5" /></Button></span></li>
            ))}
          </ul>
        </Card>
        <Card title="Recent deliveries" pad={false}>
          <div className="p-3"><Table head={["Time", "Event", "Webhook", "Result"]} rows={(deliveries.data?.deliveries ?? []).map((d: any) => [fmtDate(d.created_at), <code key="e" className="text-[12px]">{d.event}</code>, d.webhook ?? d.webhook_id, <StatusBadge key="s" s={d.ok ? "ok" : "failed"} />])} empty="Add a webhook and press Test." /></div>
        </Card>
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-22",
  routes: [{ path: "/team", element: <TeamPage /> }],
  nav: { group: "Operate", label: "Team & integrations", to: "/team", order: 20, icon: Users },
};
