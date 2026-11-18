/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Send, Trash2, Users } from "lucide-react";
import { api, setRole } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, KV, PageHeader, Select, Skeleton, StatusBadge, Table, useToast } from "../../components/ui";
import { msg, useI18n, useLocalizedDefault } from "../../i18n";

// English constants the API returns verbatim; tKnown() shows their translation in a non-English UI when the server did not localize them.
const KNOWN_SERVER_TEXT = [
  msg("Fictional roster. In an Entra-protected deployment roles come from app-role claims (X-MS-CLIENT-PRINCIPAL)."),
  msg("Demo: X-Studio-Role / X-Studio-User headers. Production: Entra ID (Container Apps built-in auth) + app roles."),
  msg("Studio administrator"),
  msg("Brand Manager, Northwind"),
  msg("Creative Director"),
  msg("Senior creative"),
  msg("Legal & compliance reviewer"),
  msg("Agency partner (guest)"),
];

function TeamPage() {
  const { t, tEnum, tOpen, tx, fmt, tKnown } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["team-members"], queryFn: () => api.get("/api/team/members") });
  const roles = useQuery({ queryKey: ["team-roles"], queryFn: () => api.get("/api/team/roles") });
  const hooks = useQuery({ queryKey: ["hooks"], queryFn: () => api.get("/api/team/webhooks") });
  const deliveries = useQuery({ queryKey: ["deliveries"], queryFn: () => api.get("/api/team/deliveries?limit=8"), refetchInterval: 10000 });
  const info = useQuery({ queryKey: ["team-api"], queryFn: () => api.get("/api/team/api") });
  const [hookName, setHookName] = useLocalizedDefault((i) => i.t("Creative channel"));
  const [form, setForm] = useState({ url: "", format: "teams", events: ["approval.requested", "approval.approved", "budget.alert"] });
  const sink = hooks.data?.internal_sink as string | undefined;
  const create = async () => {
    await api.post("/api/team/webhooks", { name: hookName, ...form });
    toast({ tone: "good", title: t("Webhook created") });
    hooks.refetch();
  };
  const test = async (id: string) => {
    const r = await api.post(`/api/team/webhooks/${id}/test`);
    toast({ tone: r.ok ? "good" : "warn", title: r.ok ? t("Test message delivered") : t("Delivery failed"), body: r.error ?? `HTTP ${r.status}` });
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
      <PageHeader
        eyebrow={t("CS-22 · Collaboration, roles & integrations")}
        title={t("Team & integrations")}
        subtitle={t("Six roles enforced on the API, Teams/Slack-compatible webhook notifications (SSRF-guarded, allow-listed), campaign-pack export and a documented REST API. Demo identities are self-declared; production uses Entra ID app roles.")}
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("Roster")} subtitle={tKnown(members.data?.note)}>
          {!members.data ? (
            <Skeleton h={140} />
          ) : (
            <ul className="divide-y divide-cream-200 text-[13px]">
              {members.data.members.map((m: any) => (
                <li key={m.name} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0">
                    <b>{m.name}</b>
                    <br />
                    <span className="text-espresso-500">{tKnown(m.title)}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge tone="dark">{tEnum("roleChip", m.role)}</Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setRole(m.role);
                        qc.invalidateQueries();
                        toast({ tone: "info", title: t("Now acting as {role}", { role: tEnum("role", m.role) }) });
                      }}
                    >
                      {t("Act as")}
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={t("REST API")} subtitle={t("Everything in the UI is an API call")}>
          {info.data && (
            <KV
              rows={[
                [
                  "OpenAPI",
                  <a key="o" className="text-dawn-700 underline" href={info.data.openapi}>
                    {info.data.openapi}
                  </a>,
                ],
                [
                  t("Interactive docs"),
                  <a key="d" className="text-dawn-700 underline" href={info.data.docs}>
                    {info.data.docs}
                  </a>,
                ],
                [t("Auth"), tKnown(info.data.auth)],
                [t("Rate limits"), t("{ai}/min AI-spending · {writes}/min writes per IP", { ai: info.data.rate_limits.spend_per_ip_per_min, writes: info.data.rate_limits.mutate_per_ip_per_min })],
                [t("Streaming"), info.data.streaming],
              ]}
            />
          )}
          {info.data && (
            <ul className="mt-3 list-disc pl-5 text-[12.5px] text-espresso-600">
              {info.data.examples.map((e: string) => (
                <li key={e}>
                  <code>{e}</code>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card className="mt-5" title={t("Roles & permissions")} subtitle={t("Enforced server-side on every mutating endpoint")} pad={false}>
        <div className="scroll-thin overflow-x-auto p-3" data-testid="permission-matrix">
          {!roles.data ? (
            <Skeleton h={120} />
          ) : (
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b border-cream-300 text-left text-[11px] uppercase tracking-wider text-espresso-500">
                  <th className="px-2 py-1.5">{t("Permission")}</th>
                  {roles.data.roles.map((r: any) => (
                    <th key={r.id} className="px-2 py-1.5 text-center">
                      {tEnum("role", r.id, r.label)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {perms.map((p) => (
                  <tr key={p} className="border-b border-cream-200 last:border-0">
                    <td className="px-2 py-1">
                      <code>{p}</code>
                    </td>
                    {roles.data.roles.map((r: any) => (
                      <td key={r.id} className="px-2 py-1 text-center">
                        {r.permissions.includes(p) ? <Check className="mx-auto h-3.5 w-3.5 text-sage-600" /> : <span className="text-cream-300">·</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card title={t("Webhooks")} subtitle={t("Teams (MessageCard), Slack, or generic JSON · allow-list: {list}", { list: (hooks.data?.allow_list ?? []).filter((x: string) => x !== sink).join(", ") })}>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Name")}>
                <Input value={hookName} onChange={(e) => setHookName(e.target.value)} />
              </Field>
              <Field label={t("Format")}>
                <Select value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })}>
                  <option value="teams">Microsoft Teams</option>
                  <option value="slack">Slack</option>
                  <option value="generic">{t("Generic JSON")}</option>
                </Select>
              </Field>
            </div>
            <Field
              label="URL"
              hint={
                sink ? (
                  <span>
                    {tx("Demo sink (always works): <use>use internal sink</use>", {
                      use: (chunks) => (
                        <button className="underline" onClick={() => setForm({ ...form, url: sink })}>
                          {chunks}
                        </button>
                      ),
                    })}
                  </span>
                ) : undefined
              }
            >
              <Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://contoso.webhook.office.com/…" aria-label={t("webhook url")} />
            </Field>
            <div className="flex flex-wrap gap-1.5">
              {(hooks.data?.events ?? []).map((e: string) => (
                <button key={e} onClick={() => toggleEvt(e)} aria-pressed={form.events.includes(e)} className={`rounded-full border px-2 py-0.5 text-[11.5px] ${form.events.includes(e) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300"}`}>
                  {e}
                </button>
              ))}
            </div>
            <Button variant="accent" disabled={!form.url} onClick={create}>
              {t("Add webhook")}
            </Button>
          </div>
          <ul className="mt-4 divide-y divide-cream-200 text-[13px]">
            {(hooks.data?.webhooks ?? []).map((h: any) => (
              <li key={h.id} className="flex items-center justify-between gap-2 py-2">
                <span className="min-w-0">
                  <b>{h.name}</b> <Badge>{tOpen("webhookFormat", h.format)}</Badge>
                  <br />
                  <span className="break-all text-[11.5px] text-espresso-400">{h.url.slice(0, 60)}</span>
                </span>
                <span className="flex gap-1.5">
                  <Button size="sm" variant="outline" icon={<Send className="h-3.5 w-3.5" />} onClick={() => test(h.id)}>
                    {t("Test")}
                  </Button>
                  <Button size="sm" variant="ghost" aria-label={t("delete webhook")} onClick={() => del(h.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={t("Recent deliveries")} pad={false}>
          <div className="p-3">
            <Table
              head={[t("Time"), t("Event"), t("Webhook"), t("Result")]}
              rows={(deliveries.data?.deliveries ?? []).map((d: any) => [
                fmt.dateTime(d.created_at),
                <code key="e" className="text-[12px]">
                  {d.event}
                </code>,
                d.webhook ?? d.webhook_id,
                <StatusBadge key="s" s={d.ok ? "ok" : "failed"} />,
              ])}
              empty={t("Add a webhook and press Test.")}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-22",
  routes: [{ path: "/team", element: <TeamPage /> }],
  nav: { group: "Operate", label: msg("Team & integrations"), to: "/team", order: 20, icon: Users },
};
