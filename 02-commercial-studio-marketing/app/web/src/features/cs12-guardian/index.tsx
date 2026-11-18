/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, Sparkles, Wand2 } from "lucide-react";
import { api, getRole } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Modal, PageHeader, Select, Skeleton, StatusBadge, Textarea, useToast } from "../../components/ui";
import { FindingList, GuardianBadge } from "../../components/common";

const CHECK_LABEL: Record<string, string> = {
  brand_voice: "Brand voice",
  visual_identity: "Visual identity",
  claims: "Claims",
  regulated: "Regulated rules",
  rights: "Rights & consent",
  content_safety: "Content Safety",
  disclosure: "AI disclosure",
  accessibility: "Accessibility",
};

export function ReportView({ report, onWaive, canWaive }: { report: any; onWaive?: (f: any) => void; canWaive?: boolean }) {
  const tone = report.verdict === "block" ? "bg-roast-500 text-white" : report.verdict === "warn" ? "bg-dawn-500 text-white" : "bg-sage-500 text-white";
  return (
    <div className="space-y-4" data-testid="guardian-report">
      <div className="flex flex-wrap items-center gap-6">
        <div className={`rounded-2xl px-5 py-3 ${tone}`}>
          <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">Verdict</div>
          <div className="font-display text-[28px] font-semibold uppercase leading-none" data-testid="verdict">{report.verdict}</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-espresso-500">Compliance score</div>
          <div className="font-display text-[34px] font-semibold leading-none">{report.score}<span className="text-[16px] text-espresso-400"> / 100</span></div>
        </div>
        <div className="text-[12px] text-espresso-500">{report.findings.filter((f: any) => f.severity === "block" && !f.waived).length} blocking · {report.findings.filter((f: any) => f.severity === "warn").length} warning(s)</div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {report.checks.map((c: any) => (
          <div key={c.check} className={`rounded-lg border px-3 py-1.5 text-[12px] ${c.status === "block" ? "border-roast-500/50 bg-roast-500/10" : c.status === "warn" ? "border-dawn-400/60 bg-dawn-300/15" : "border-cream-300 bg-cream-50"}`}>
            <div className="font-semibold">{CHECK_LABEL[c.check] ?? c.check}</div>
            <div className="text-espresso-500">{c.status === "pass" ? "pass" : `${c.findings} finding(s) · ${c.status}`}</div>
          </div>
        ))}
      </div>
      <FindingList findings={report.findings} onWaive={onWaive} canWaive={canWaive} />
      <div className="text-[11.5px] text-espresso-400">Rules {report.rules_version} · deterministic rules first, Azure AI Content Safety on every text, LLM only as an assistant.</div>
    </div>
  );
}

function Iterations({ items }: { items: any[] }) {
  return (
    <ol className="space-y-2" data-testid="iterations">
      {items.map((it) => (
        <li key={it.iteration} className="rounded-xl border border-cream-300 px-3.5 py-2.5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="dark">Iteration {it.iteration}</Badge>
            <GuardianBadge g={{ verdict: it.verdict, score: it.score, blocks: it.blocks }} />
            <span className="text-espresso-500">{it.warns} warning(s)</span>
          </div>
          {it.fixes?.length > 0 && (
            <ul className="mt-1.5 list-disc pl-5 text-espresso-700">
              {it.fixes.map((f: any, i: number) => <li key={i}><code className="rounded bg-cream-200 px-1 text-[11.5px]">{f.rule}</code> → {f.op}{f.detail ? `: ${String(f.detail).slice(0, 120)}` : ""}</li>)}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function SubjectChips({ s }: { s: any }) {
  const chips: string[] = [
    ...s.music.map((m: any) => `♪ ${m.title}`),
    ...s.talent.map((t: any) => `Talent: ${t.name}`),
    ...s.stock.map((t: any) => `Stock: ${t.title}`),
    ...s.visuals.map((v: any) => `${v.kind}: ${(v.colors ?? []).join(" ")}`),
    `AI-generated: ${s.disclosure.ai_generated ? "yes" : "no"} · label ${s.disclosure.label_present ? "present" : "missing"}`,
    `Markets ${s.markets.join(",")}`,
    `Air ${s.air_start ?? "—"} → ${s.air_end ?? "—"}`,
    s.has_video ? (s.captions_present ? "captions on" : "captions off") : "",
  ].filter(Boolean);
  return <div className="flex flex-wrap gap-1.5">{chips.map((c, i) => <span key={i} className="rounded-full border border-cream-300 bg-cream-50 px-2 py-0.5 text-[11.5px] text-espresso-600">{c}</span>)}</div>;
}

function Playground() {
  const toast = useToast();
  const [subject, setSubject] = useState<any>(null);
  const [expected, setExpected] = useState<string[]>([]);
  const [report, setReport] = useState<any>(null);
  const [revision, setRevision] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState("");
  const load = async () => {
    const r = await api.get("/api/guardian/seeded");
    setSubject(r.subject);
    setExpected(r.expected_rules);
    setReport(null);
    setRevision(null);
    setRawText(JSON.stringify(r.subject, null, 2));
  };
  useEffect(() => {
    load();
  }, []);
  const current = () => {
    if (!raw) return subject;
    try {
      return JSON.parse(rawText);
    } catch {
      toast({ tone: "bad", title: "The subject JSON is not valid" });
      return null;
    }
  };
  const run = async (kind: "check" | "revise") => {
    const s = current();
    if (!s) return;
    setBusy(kind);
    try {
      if (kind === "check") {
        setReport(await api.post("/api/guardian/check", { subject: s }));
        setRevision(null);
      } else {
        const r = await api.post("/api/guardian/revise", { subject: s, max_iter: 3 });
        setRevision(r);
        setReport(r.report);
        setSubject(r.subject);
        setRawText(JSON.stringify(r.subject, null, 2));
      }
    } finally {
      setBusy(null);
    }
  };
  const found = new Set((report?.findings ?? []).map((f: any) => f.rule_id));
  return (
    <div>
      <PageHeader
        eyebrow="CS-12 · Brand Guardian"
        title="Guardian playground"
        subtitle="Seven seeded violations — a cure claim, a forbidden word, a missing disclaimer, an unlicensed track, an expired licence, a territory breach, an off-palette colour and a missing AI label. Run the multi-check, then let the auto-revise loop fix what it can."
        actions={<Button variant="outline" onClick={load}>Reset to seeded violations</Button>}
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Subject under review" subtitle="Edit any line — the Guardian re-checks the exact text" actions={<button className="text-[12px] text-dawn-700 hover:underline" onClick={() => { if (!raw && subject) setRawText(JSON.stringify(subject, null, 2)); setRaw(!raw); }}>{raw ? "Form view" : "Raw JSON"}</button>}>
          {!subject && <Skeleton h={220} />}
          {subject && !raw && (
            <div className="space-y-3">
              {subject.texts.map((t: any, i: number) => (
                <Field key={t.id} label={`${t.kind} · ${t.id}`}>
                  <Textarea rows={2} value={t.text} aria-label={`line ${t.id}`} onChange={(e) => setSubject({ ...subject, texts: subject.texts.map((x: any, j: number) => (j === i ? { ...x, text: e.target.value } : x)) })} className="min-h-[56px]" />
                </Field>
              ))}
              <SubjectChips s={subject} />
            </div>
          )}
          {subject && raw && <Textarea value={rawText} onChange={(e) => setRawText(e.target.value)} rows={18} className="font-mono text-[12px]" aria-label="subject json" />}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} loading={busy === "check"} onClick={() => run("check")}>Run Guardian</Button>
            <Button variant="accent" icon={<Wand2 className="h-4 w-4" />} loading={busy === "revise"} onClick={() => run("revise")}>Auto-revise (≤3 iterations)</Button>
          </div>
        </Card>
        <div className="space-y-5">
          <Card title="Report" subtitle="Scored report with fix suggestions">
            {!report ? <Empty title="No report yet" hint="Run the Guardian on the seeded subject." /> : <ReportView report={report} />}
          </Card>
          {report && expected.length > 0 && !revision && (
            <Card title="Seeded violations caught" subtitle="Every seeded rule must fire">
              <ul className="grid gap-1 text-[13px] md:grid-cols-2" data-testid="seeded-coverage">
                {expected.map((r) => <li key={r} className="flex items-center gap-2"><StatusBadge s={found.has(r) ? "ok" : "failed"} /> <code className="text-[12px]">{r}</code></li>)}
              </ul>
            </Card>
          )}
          {revision && (
            <Card title="Auto-revise loop" subtitle={`${revision.fixes_applied} fix(es) applied · ${revision.converged ? "converged — no blocking findings" : "not fully converged — human review needed"}`}>
              <Iterations items={revision.iterations} />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

const REVIEWABLE = ["brief", "strategy", "script", "copy", "storyboard", "spot"];

function GuardianTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const toast = useToast();
  const arts: any[] = (campaign.artifacts ?? []).filter((a: any) => REVIEWABLE.includes(a.kind));
  const latestByKind = REVIEWABLE.map((k) => arts.find((a) => a.kind === k)).filter(Boolean) as any[];
  const [aid, setAid] = useState<string>("");
  useEffect(() => {
    if (!aid && latestByKind.length) setAid((latestByKind.find((a) => a.kind === "script") ?? latestByKind[0]).id);
  }, [campaign]); // eslint-disable-line react-hooks/exhaustive-deps
  const reports = useQuery({ queryKey: ["greports", id, aid], enabled: !!aid, queryFn: () => api.get(`/api/campaigns/${id}/guardian/reports?artifact_id=${aid}&limit=1`) });
  const [fresh, setFresh] = useState<{ aid: string; report: any } | null>(null);
  const [revision, setRevision] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [waive, setWaive] = useState<any>(null);
  const [why, setWhy] = useState("");
  const role = getRole();
  const run = async (auto: boolean) => {
    setBusy(auto ? "revise" : "run");
    try {
      const r = await api.post(`/api/campaigns/${id}/guardian/run`, { artifact_id: aid, auto_revise: auto });
      setFresh({ aid, report: r.report });
      if (auto) toast({ tone: r.converged ? "good" : "warn", title: r.revised ? "Guardian revised the artifact" : "Nothing to revise", body: r.converged ? "No blocking findings remain." : "Open findings need a human decision." });
      reports.refetch();
      reload();
    } finally {
      setBusy(null);
    }
  };
  const doWaive = async () => {
    await api.post(`/api/campaigns/${id}/guardian/waive`, { artifact_id: aid, finding_id: waive.id, justification: why });
    toast({ tone: "good", title: "Finding waived", body: "Recorded in the audit trail with your justification." });
    setWaive(null);
    setWhy("");
    setFresh(null);
    reports.refetch();
    reload();
  };
  const stored = reports.data?.reports?.[0];
  const report = fresh && fresh.aid === aid ? fresh.report : stored;
  const sel = arts.find((a) => a.id === aid);
  return (
    <div className="space-y-5">
      <Card title="Brand Guardian" subtitle="Brand voice, visual identity, claims, regulated rules, rights & consent, Azure AI Content Safety (text, image, protected material, Prompt Shields), AI disclosure, accessibility.">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Artifact">
            <Select value={aid} onChange={(e) => { setAid(e.target.value); setFresh(null); setRevision(null); }} className="w-80" aria-label="artifact">
              {latestByKind.map((a) => <option key={a.id} value={a.id}>{a.kind} v{a.version} · {a.status}{a.guardian ? ` · guardian ${a.guardian.verdict}` : ""}</option>)}
            </Select>
          </Field>
          <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} disabled={!aid} loading={busy === "run"} onClick={() => run(false)}>Run Guardian</Button>
          <Button variant="accent" icon={<Sparkles className="h-4 w-4" />} disabled={!aid} loading={busy === "revise"} onClick={() => run(true)}>Auto-revise</Button>
          {sel && <GuardianBadge g={sel.guardian} />}
        </div>
      </Card>
      {!aid && <Empty title="Nothing to review yet" hint="Create the brief, then run the Guardian at every stage." />}
      {aid && reports.isLoading && <Skeleton h={160} />}
      {aid && !reports.isLoading && !report && <Empty title="No report for this artifact yet" hint="Run the Guardian to produce a scored report." />}
      {report && (
        <Card title="Latest report" subtitle={`Report ${report.id} · ${report.created_at}`}>
          <ReportView report={report} canWaive={role === "legal" || role === "admin"} onWaive={setWaive} />
        </Card>
      )}
      {revision && <Card title="Auto-revise loop"><Iterations items={revision.iterations} /></Card>}
      {(reports.data?.waivers ?? []).length > 0 && (
        <Card title="Waivers" subtitle="Legal/Admin only — justification recorded in the audit trail">
          <ul className="space-y-1.5 text-[13px]">
            {reports.data.waivers.map((w: any) => <li key={w.id}><code className="text-[12px]">{w.finding_id}</code> — {w.justification} <span className="text-espresso-400">· {w.by?.name} ({w.by?.role})</span></li>)}
          </ul>
        </Card>
      )}
      <Modal open={!!waive} onClose={() => setWaive(null)} title="Waive a blocking finding">
        <p className="mb-3 text-[13px] text-espresso-600">{waive?.message}</p>
        <Field label="Justification (min. 10 characters)"><Textarea value={why} onChange={(e) => setWhy(e.target.value)} aria-label="justification" /></Field>
        <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setWaive(null)}>Cancel</Button><Button variant="danger" disabled={why.trim().length < 10} onClick={doWaive}>Waive finding</Button></div>
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-12",
  routes: [{ path: "/guardian", element: <Playground /> }],
  nav: { group: "Review", label: "Brand Guardian", to: "/guardian", order: 10, icon: ShieldCheck },
  workspaceTabs: [{ id: "guardian", label: "Guardian", order: 90, Component: GuardianTab }],
};
