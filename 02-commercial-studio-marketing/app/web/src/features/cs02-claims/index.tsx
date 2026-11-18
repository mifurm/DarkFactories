/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef } from "../../registry";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Skeleton, Stat, StatusBadge, Table, Textarea, useToast } from "../../components/ui";

const EMPTY = { text: "", type: "prohibited", markets: "*", categories: "*", patterns: "", required_disclaimer: "", substantiation_url: "", alternative: "", severity: "block", notes: "" };

function ClaimsPage() {
  const toast = useToast();
  const [type, setType] = useState("");
  const [market, setMarket] = useState("");
  const [qs, setQs] = useState("");
  const list = useQuery({ queryKey: ["claims", type, market, qs], queryFn: () => api.get(`/api/claims?${new URLSearchParams({ ...(type && { type }), ...(market && { market }), ...(qs && { q: qs }) })}`) });
  const [edit, setEdit] = useState<any>(null);
  const [text, setText] = useState("Dawn Roast cures morning anxiety and burns fat. It gives you energy to start the day.");
  const [mk, setMk] = useState("US");
  const [res, setRes] = useState<any>(null);
  const d = list.data;
  const save = async () => {
    const body = { ...edit, markets: String(edit.markets).split(",").map((x: string) => x.trim()).filter(Boolean), categories: String(edit.categories).split(",").map((x: string) => x.trim()).filter(Boolean), patterns: String(edit.patterns).split("\n").map((x: string) => x.trim()).filter(Boolean), required_disclaimer: edit.required_disclaimer || null, substantiation_url: edit.substantiation_url || null, alternative: edit.alternative || null };
    delete body.id; delete body.pk; delete body.brand_id;
    if (edit.id) await api.put(`/api/claims/${edit.id}`, body);
    else await api.post("/api/claims", body);
    toast({ tone: "good", title: "Claim saved" });
    setEdit(null);
    list.refetch();
  };
  const open = (c?: any) => setEdit(c ? { ...c, markets: c.markets.join(", "), categories: c.categories.join(", "), patterns: c.patterns.join("\n"), required_disclaimer: c.required_disclaimer ?? "", substantiation_url: c.substantiation_url ?? "", alternative: c.alternative ?? "" } : { ...EMPTY });
  const check = async () => setRes(await api.post("/api/claims/check", { text, market: [mk], category: "beverage" }));
  const highlight = (t: string, hits: any[]) => {
    if (!hits?.length) return t;
    const spans = hits.filter((h) => h.type !== "approved" || h.required_disclaimer).map((h) => h.span).filter(Boolean);
    if (!spans.length) return t;
    const esc = spans.map((s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return t.split(new RegExp(`(${esc.join("|")})`, "gi")).map((part, i) => (spans.some((s: string) => s.toLowerCase() === part.toLowerCase()) ? <mark key={i} className="rounded bg-roast-500/20 px-0.5 text-roast-600">{part}</mark> : part));
  };
  return (
    <div>
      <PageHeader eyebrow="CS-02 · Claims & compliance library" title="Claims library" subtitle="Approved, prohibited and needs-substantiation claims per market and category, with required disclaimers and regulated-category rule packs. The Brand Guardian enforces exactly this list — deterministic rules first." actions={<Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => open()}>Add claim</Button>} />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Stat label="Approved" value={d?.counts.approved ?? "—"} tone="good" />
        <Stat label="Prohibited" value={d?.counts.prohibited ?? "—"} tone="bad" />
        <Stat label="Needs substantiation" value={d?.counts.needs_substantiation ?? "—"} tone="dawn" />
        <Stat label="Rule packs" value={d?.packs.length ?? "—"} hint={d?.packs.join(", ")} />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
        <Card title="Claims" pad={false} actions={<div className="flex gap-2"><Select value={type} onChange={(e) => setType(e.target.value)} className="w-44" aria-label="type filter"><option value="">all types</option><option value="approved">approved</option><option value="prohibited">prohibited</option><option value="needs_substantiation">needs substantiation</option></Select><Select value={market} onChange={(e) => setMarket(e.target.value)} className="w-28" aria-label="market filter"><option value="">any market</option>{["US", "DE", "FR", "PL", "GB"].map((m) => <option key={m}>{m}</option>)}</Select><Input value={qs} onChange={(e) => setQs(e.target.value)} placeholder="search" className="w-36" aria-label="search claims" /></div>}>
          <div className="p-3" data-testid="claims-table">
            {list.isLoading ? <Skeleton h={200} /> : (
              <Table
                head={["Claim", "Type", "Scope", "Disclaimer / alternative", ""]}
                rows={(d?.claims ?? []).map((c: any) => [
                  <span key="t"><b>{c.text}</b>{c.notes && <div className="text-[11.5px] text-espresso-400">{c.notes}</div>}</span>,
                  <span key="y" className="whitespace-nowrap"><StatusBadge s={c.type} /> {c.severity === "warn" && <Badge>warn</Badge>}</span>,
                  <span key="s" className="text-[12px] text-espresso-500">{c.markets.join(",")} · {c.categories.join(",")}{c.rule_pack ? ` · ${c.rule_pack}` : ""}</span>,
                  <span key="d" className="text-[12.5px]">{c.required_disclaimer && <div>Must show: “{c.required_disclaimer}”</div>}{c.alternative && <div className="text-espresso-500">Instead: “{c.alternative}”</div>}</span>,
                  <span key="a" className="flex gap-1"><Button size="sm" variant="ghost" aria-label="edit claim" onClick={() => open(c)}><Pencil className="h-3.5 w-3.5" /></Button><Button size="sm" variant="ghost" aria-label="delete claim" onClick={async () => { await api.del(`/api/claims/${c.id}`); list.refetch(); }}><Trash2 className="h-3.5 w-3.5" /></Button></span>,
                ])}
              />
            )}
          </div>
        </Card>
        <Card title="Claim checker" subtitle="What the Guardian sees in any line of copy">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} aria-label="text to check" />
          <div className="mt-2 flex items-center gap-2"><Select value={mk} onChange={(e) => setMk(e.target.value)} className="w-28" aria-label="market">{["US", "DE", "FR", "PL", "GB"].map((m) => <option key={m}>{m}</option>)}</Select><Button variant="primary" icon={<Scale className="h-4 w-4" />} onClick={check}>Check</Button></div>
          {res && (
            <div className="mt-4 space-y-3 text-[13px]" data-testid="claim-result">
              <div className="flex items-center gap-2"><b>Verdict</b><StatusBadge s={res.verdict} /></div>
              <div className="rounded-lg bg-cream-100 px-3 py-2 leading-relaxed">{highlight(text, res.hits)}</div>
              <ul className="space-y-1.5">
                {res.hits.map((h: any, i: number) => <li key={i}><StatusBadge s={h.type} /> “{h.span}” → <span className="text-espresso-600">{h.claim}</span>{h.alternative && <div className="text-espresso-500">Suggest: {h.alternative}</div>}</li>)}
                {res.missing_disclaimers.map((m: string, i: number) => <li key={`m${i}`} className="text-roast-600">Missing disclaimer: “{m}”</li>)}
              </ul>
            </div>
          )}
        </Card>
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit claim" : "Add claim"} wide>
        {edit && (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Claim text" className="md:col-span-2"><Input value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} aria-label="claim text" /></Field>
            <Field label="Type"><Select value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value })}><option value="approved">approved</option><option value="prohibited">prohibited</option><option value="needs_substantiation">needs_substantiation</option></Select></Field>
            <Field label="Severity"><Select value={edit.severity} onChange={(e) => setEdit({ ...edit, severity: e.target.value })}><option value="block">block</option><option value="warn">warn</option></Select></Field>
            <Field label="Markets (comma, * = all)"><Input value={edit.markets} onChange={(e) => setEdit({ ...edit, markets: e.target.value })} /></Field>
            <Field label="Categories"><Input value={edit.categories} onChange={(e) => setEdit({ ...edit, categories: e.target.value })} /></Field>
            <Field label="Match patterns (one per line; prefix re: for a regex)" className="md:col-span-2"><Textarea rows={3} value={edit.patterns} onChange={(e) => setEdit({ ...edit, patterns: e.target.value })} aria-label="patterns" /></Field>
            <Field label="Required disclaimer"><Input value={edit.required_disclaimer} onChange={(e) => setEdit({ ...edit, required_disclaimer: e.target.value })} /></Field>
            <Field label="Compliant alternative"><Input value={edit.alternative} onChange={(e) => setEdit({ ...edit, alternative: e.target.value })} /></Field>
            <Field label="Notes" className="md:col-span-2"><Input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></Field>
            <div className="flex justify-end gap-2 md:col-span-2"><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button><Button variant="accent" disabled={edit.text.length < 3} onClick={save}>Save</Button></div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-02",
  routes: [{ path: "/claims", element: <ClaimsPage /> }],
  nav: { group: "Brand Brain", label: "Claims library", to: "/claims", order: 10, icon: Scale },
};
