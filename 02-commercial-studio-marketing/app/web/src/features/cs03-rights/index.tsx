/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellRing, FileKey2, Plus, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Skeleton, Stat, StatusBadge, Table, useToast } from "../../components/ui";

const KINDS = ["music", "talent", "stock", "font", "other"];
const EMPTY = { kind: "music", title: "", licensor: "", status: "active", territories: "WW", channels: "", valid_from: "", valid_to: "", ai_voice_consent: false, ai_likeness_consent: false, usage_notes: "" };

function RightsPage() {
  const toast = useToast();
  const [kind, setKind] = useState("");
  const list = useQuery({ queryKey: ["rights", kind], queryFn: () => api.get(`/api/rights${kind ? `?kind=${kind}` : ""}`) });
  const [edit, setEdit] = useState<any>(null);
  const [chk, setChk] = useState<any>({ kind: "music", title: "Sunrise Anthem", markets: "US", channels: "youtube", air_start: "2026-12-01", air_end: "2027-01-31", ai_synthesis: false });
  const [res, setRes] = useState<any>(null);
  const d = list.data;
  const save = async () => {
    const body = { ...edit, territories: edit.territories.split(",").map((x: string) => x.trim().toUpperCase()).filter(Boolean), channels: edit.channels.split(",").map((x: string) => x.trim().toLowerCase()).filter(Boolean), valid_from: edit.valid_from || null, valid_to: edit.valid_to || null, licensor: edit.licensor || null };
    await api.post("/api/rights", body);
    toast({ tone: "good", title: "Rights entry added" });
    setEdit(null);
    list.refetch();
  };
  const check = async () => setRes(await api.post("/api/rights/check", { kind: chk.kind, title: chk.title, markets: chk.markets.split(",").map((x: string) => x.trim().toUpperCase()), channels: chk.channels.split(",").map((x: string) => x.trim().toLowerCase()).filter(Boolean), air_start: chk.air_start || null, air_end: chk.air_end || null, ai_synthesis: chk.ai_synthesis, usage: chk.kind === "talent" ? "voice" : "use" }));
  const notify = async () => {
    const r = await api.post("/api/rights/alerts/notify?days=45");
    toast({ tone: "good", title: `${r.notified} expiry alert(s) sent`, body: "Delivered to configured webhooks (Teams/Slack)." });
  };
  const titles = (d?.entries ?? []).filter((e: any) => e.kind === chk.kind).map((e: any) => e.title);
  return (
    <div>
      <PageHeader eyebrow="CS-03 · Rights, talent & consent registry" title="Rights registry" subtitle="Talent likeness and voice consent, licensed music and stock, windows, territories and channel limits. Out-of-rights use is blocked by the Guardian before it reaches approval; expiry alerts go to Teams/Slack." actions={<><Button variant="outline" icon={<BellRing className="h-4 w-4" />} onClick={notify}>Send expiry alerts</Button><Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit({ ...EMPTY })}>Add entry</Button></>} />
      <div className="mb-5 grid gap-3 md:grid-cols-5">
        {KINDS.map((k) => <button key={k} onClick={() => setKind(kind === k ? "" : k)} className="text-left"><Stat label={k} value={d?.counts[k] ?? "—"} tone={kind === k ? "dawn" : undefined} /></button>)}
      </div>
      {(d?.alerts ?? []).length > 0 && (
        <Card className="mb-5" title="Expiry alerts" subtitle="Within 45 days or already expired" testId="rights-alerts">
          <ul className="grid gap-2 md:grid-cols-2">{d.alerts.map((a: any) => <li key={a.id} className="flex items-center justify-between rounded-lg bg-cream-100 px-3 py-2 text-[13px]"><span><b>{a.title}</b> <span className="text-espresso-500">({a.kind})</span></span><Badge tone={a.state === "expired" ? "bad" : "warn"}>{a.state === "expired" ? `expired ${-a.days_left} d ago` : `${a.days_left} d left`}</Badge></li>)}</ul>
        </Card>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_400px]">
        <Card title="Registry" pad={false}>
          <div className="p-3" data-testid="rights-table">
            {list.isLoading ? <Skeleton h={200} /> : (
              <Table
                head={["Kind", "Title", "Status", "Territories", "Window", "AI consent", ""]}
                rows={(d?.entries ?? []).map((e: any) => [
                  <Badge key="k" tone="dark">{e.kind}</Badge>,
                  <span key="t"><b>{e.title}</b><div className="text-[11.5px] text-espresso-400">{e.licensor}{e.library_track ? " · library track" : ""}</div></span>,
                  <span key="s" className="flex flex-wrap gap-1"><StatusBadge s={e.expiry?.state ?? e.status} />{e.status === "revoked" && <Badge tone="bad">revoked</Badge>}</span>,
                  <span key="r" className="text-[12px]">{e.territories.join(", ")}{e.channels.length ? <div className="text-espresso-400">{e.channels.join(", ")}</div> : null}</span>,
                  <span key="w" className="whitespace-nowrap text-[12px]">{e.valid_from ?? "—"} → {e.valid_to ?? "open"}</span>,
                  <span key="c" className="text-[12px]">{e.kind === "talent" ? <>voice {e.ai_voice_consent ? "✔" : "✘"} · likeness {e.ai_likeness_consent ? "✔" : "✘"}</> : "—"}</span>,
                  e.status !== "revoked" ? <Button key="x" size="sm" variant="ghost" onClick={async () => { await api.post(`/api/rights/${e.id}/revoke`); toast({ tone: "warn", title: `${e.title} revoked` }); list.refetch(); }}>Revoke</Button> : null,
                ])}
              />
            )}
          </div>
        </Card>
        <Card title="Would this use be cleared?" subtitle="The same check the Guardian runs" actions={<FileKey2 className="h-4 w-4 text-espresso-400" />}>
          <div className="space-y-2.5">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Kind"><Select value={chk.kind} onChange={(e) => setChk({ ...chk, kind: e.target.value, title: "" })} aria-label="kind">{KINDS.map((k) => <option key={k}>{k}</option>)}</Select></Field>
              <Field label="Title"><Input list="rights-titles" value={chk.title} onChange={(e) => setChk({ ...chk, title: e.target.value })} aria-label="title" /><datalist id="rights-titles">{titles.map((t: string) => <option key={t} value={t} />)}</datalist></Field>
              <Field label="Markets"><Input value={chk.markets} onChange={(e) => setChk({ ...chk, markets: e.target.value })} aria-label="markets" /></Field>
              <Field label="Channels"><Input value={chk.channels} onChange={(e) => setChk({ ...chk, channels: e.target.value })} aria-label="channels" /></Field>
              <Field label="On air from"><Input type="date" value={chk.air_start} onChange={(e) => setChk({ ...chk, air_start: e.target.value })} /></Field>
              <Field label="On air to"><Input type="date" value={chk.air_end} onChange={(e) => setChk({ ...chk, air_end: e.target.value })} /></Field>
            </div>
            <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={chk.ai_synthesis} onChange={(e) => setChk({ ...chk, ai_synthesis: e.target.checked })} /> synthesised (AI voice / likeness)</label>
            <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} onClick={check}>Check clearance</Button>
          </div>
          {res && (
            <div className="mt-4 space-y-2 text-[13px]" data-testid="rights-result">
              <div className="flex items-center gap-2">{res.cleared ? <ShieldCheck className="h-5 w-5 text-sage-600" /> : <ShieldX className="h-5 w-5 text-roast-500" />}<b>{res.cleared ? "Cleared" : "NOT cleared"}</b></div>
              <ul className="space-y-1">{res.verdicts.filter((v: any) => !v.ok).map((v: any, i: number) => <li key={i} className="rounded-lg bg-roast-500/10 px-3 py-1.5"><code className="text-[11.5px]">{v.code}</code> — {v.message}</li>)}</ul>
              {res.cleared && <div className="text-espresso-500">{res.entry?.title} — all checks passed (status, territory, window, channel{chk.ai_synthesis ? ", AI consent" : ""}).</div>}
            </div>
          )}
        </Card>
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title="Add rights entry" wide>
        {edit && (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Kind"><Select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</Select></Field>
            <Field label="Title / name"><Input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} aria-label="rights title" /></Field>
            <Field label="Licensor"><Input value={edit.licensor} onChange={(e) => setEdit({ ...edit, licensor: e.target.value })} /></Field>
            <Field label="Territories (WW or codes)"><Input value={edit.territories} onChange={(e) => setEdit({ ...edit, territories: e.target.value })} /></Field>
            <Field label="Valid from"><Input type="date" value={edit.valid_from} onChange={(e) => setEdit({ ...edit, valid_from: e.target.value })} /></Field>
            <Field label="Valid to"><Input type="date" value={edit.valid_to} onChange={(e) => setEdit({ ...edit, valid_to: e.target.value })} /></Field>
            <Field label="Channels (empty = all)"><Input value={edit.channels} onChange={(e) => setEdit({ ...edit, channels: e.target.value })} /></Field>
            <div className="flex items-end gap-4 pb-2 text-[13px]"><label className="flex items-center gap-1.5"><input type="checkbox" checked={edit.ai_voice_consent} onChange={(e) => setEdit({ ...edit, ai_voice_consent: e.target.checked })} /> AI voice consent</label><label className="flex items-center gap-1.5"><input type="checkbox" checked={edit.ai_likeness_consent} onChange={(e) => setEdit({ ...edit, ai_likeness_consent: e.target.checked })} /> AI likeness consent</label></div>
            <div className="flex justify-end gap-2 md:col-span-2"><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button><Button variant="accent" disabled={edit.title.length < 2} onClick={save}>Save</Button></div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-03",
  routes: [{ path: "/rights", element: <RightsPage /> }],
  nav: { group: "Brand Brain", label: "Rights registry", to: "/rights", order: 20, icon: FileKey2 },
};
