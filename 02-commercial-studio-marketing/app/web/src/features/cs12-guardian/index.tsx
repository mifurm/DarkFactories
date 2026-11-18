/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, Sparkles, Wand2 } from "lucide-react";
import { api, getRole } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Modal, PageHeader, Select, Skeleton, StatusBadge, Textarea, useToast } from "../../components/ui";
import { FindingList, GuardianBadge, useActorName } from "../../components/common";
import { msg, useI18n, useOnLangChange } from "../../i18n";

export function ReportView({ report, onWaive, canWaive }: { report: any; onWaive?: (f: any) => void; canWaive?: boolean }) {
  const { t, tn, tEnum, fmt } = useI18n();
  const tone = report.verdict === "block" ? "bg-roast-500 text-white" : report.verdict === "warn" ? "bg-dawn-500 text-white" : "bg-sage-500 text-white";
  const blocking = report.findings.filter((f: any) => f.severity === "block" && !f.waived).length;
  const warnings = report.findings.filter((f: any) => f.severity === "warn").length;
  return (
    <div className="space-y-4" data-testid="guardian-report">
      <div className="flex flex-wrap items-center gap-6">
        <div className={`rounded-2xl px-5 py-3 ${tone}`}>
          <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">{t("Verdict")}</div>
          <div className="font-display text-[28px] font-semibold uppercase leading-none" data-testid="verdict">
            {tEnum("verdict", report.verdict)}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-espresso-500">{t("Compliance score")}</div>
          <div className="font-display text-[34px] font-semibold leading-none">
            {fmt.number(report.score)}
            <span className="text-[16px] text-espresso-400"> / 100</span>
          </div>
        </div>
        <div className="text-[12px] text-espresso-500">{t("{blocking} · {warnings}", { blocking: tn(blocking, { one: "{n} blocking", other: "{n} blocking" }), warnings: tn(warnings, { one: "{n} warning(s)", other: "{n} warning(s)" }) })}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {report.checks.map((c: any) => (
          <div key={c.check} className={`rounded-lg border px-3 py-1.5 text-[12px] ${c.status === "block" ? "border-roast-500/50 bg-roast-500/10" : c.status === "warn" ? "border-dawn-400/60 bg-dawn-300/15" : "border-cream-300 bg-cream-50"}`}>
            <div className="font-semibold">{tEnum("guardianCheck", c.check, c.check)}</div>
            <div className="text-espresso-500">{c.status === "pass" ? tEnum("verdict", "pass") : t("{findings} · {status}", { findings: tn(c.findings, { one: "{n} finding(s)", other: "{n} finding(s)" }), status: tEnum("verdict", c.status) })}</div>
          </div>
        ))}
      </div>
      <FindingList findings={report.findings} onWaive={onWaive} canWaive={canWaive} />
      <div className="text-[11.5px] text-espresso-400">{t("Rules {version} · deterministic rules first, Azure AI Content Safety on every text, LLM only as an assistant.", { version: String(report.rules_version) })}</div>
    </div>
  );
}

function Iterations({ items }: { items: any[] }) {
  const { t, tn, tEnum } = useI18n();
  return (
    <ol className="space-y-2" data-testid="iterations">
      {items.map((it) => (
        <li key={it.iteration} className="rounded-xl border border-cream-300 px-3.5 py-2.5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="dark">{t("Iteration {n}", { n: it.iteration })}</Badge>
            <GuardianBadge g={{ verdict: it.verdict, score: it.score, blocks: it.blocks }} />
            <span className="text-espresso-500">{tn(it.warns, { one: "{n} warning(s)", other: "{n} warning(s)" })}</span>
          </div>
          {it.fixes?.length > 0 && (
            <ul className="mt-1.5 list-disc pl-5 text-espresso-700">
              {it.fixes.map((f: any, i: number) => (
                <li key={i}>
                  <code className="rounded bg-cream-200 px-1 text-[11.5px]">{f.rule}</code> → {tEnum("fixOp", f.op)}
                  {f.detail ? `: ${String(f.detail).slice(0, 120)}` : ""}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function SubjectChips({ s }: { s: any }) {
  const { t, tOpen, fmt } = useI18n();
  const chips: string[] = [
    ...s.music.map((m: any) => `♪ ${m.title}`),
    ...s.talent.map((x: any) => t("Talent: {name}", { name: x.name })),
    ...s.stock.map((x: any) => t("Stock: {title}", { title: x.title })),
    ...s.visuals.map((v: any) => `${tOpen("visualKind", v.kind)}: ${(v.colors ?? []).join(" ")}`),
    t("AI-generated: {ai} · label {label}", { ai: s.disclosure.ai_generated ? t("yes") : t("no"), label: s.disclosure.label_present ? t("present") : t("missing") }),
    t("Markets {list}", { list: s.markets.join(",") }),
    t("Air {from} → {to}", { from: s.air_start ? fmt.isoDate(s.air_start) : "—", to: s.air_end ? fmt.isoDate(s.air_end) : "—" }),
    s.has_video ? (s.captions_present ? t("captions on") : t("captions off")) : "",
  ].filter(Boolean);
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((c, i) => (
        <span key={i} className="rounded-full border border-cream-300 bg-cream-50 px-2 py-0.5 text-[11.5px] text-espresso-600">
          {c}
        </span>
      ))}
    </div>
  );
}

function Playground() {
  const { t, tn, tOpen } = useI18n();
  const toast = useToast();
  const [subject, setSubject] = useState<any>(null);
  const [expected, setExpected] = useState<string[]>([]);
  const [report, setReport] = useState<any>(null);
  const [revision, setRevision] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState("");
  const [dirty, setDirty] = useState(false); // edited by the user or revised: no longer the pristine seeded subject
  const load = async () => {
    const r = await api.get("/api/guardian/seeded");
    setSubject(r.subject);
    setExpected(r.expected_rules);
    setReport(null);
    setRevision(null);
    setDirty(false);
    setRawText(JSON.stringify(r.subject, null, 2));
    return r.subject;
  };
  useEffect(() => {
    load();
  }, []);
  const current = () => {
    if (!raw) return subject;
    try {
      return JSON.parse(rawText);
    } catch {
      toast({ tone: "bad", title: t("The subject JSON is not valid") });
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
        setDirty(true);
        setRawText(JSON.stringify(r.subject, null, 2));
      }
    } finally {
      setBusy(null);
    }
  };
  // seeded subject and report messages are language-specific: reload the pristine subject (and re-check it), or just re-check what the user edited
  useOnLangChange(async () => {
    const had = !!report;
    if (!dirty) {
      const s = await load();
      if (had) setReport(await api.post("/api/guardian/check", { subject: s }));
    } else if (had && !revision) {
      await run("check");
    } else if (revision) {
      setRevision(null);
      await run("check");
    }
  });
  const found = new Set((report?.findings ?? []).map((f: any) => f.rule_id));
  return (
    <div>
      <PageHeader
        eyebrow={t("CS-12 · Brand Guardian")}
        title={t("Guardian playground")}
        subtitle={t("Seven seeded violations — a cure claim, a forbidden word, a missing disclaimer, an unlicensed track, an expired licence, a territory breach, an off-palette colour and a missing AI label. Run the multi-check, then let the auto-revise loop fix what it can.")}
        actions={
          <Button variant="outline" onClick={load}>
            {t("Reset to seeded violations")}
          </Button>
        }
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card
          title={t("Subject under review")}
          subtitle={t("Edit any line — the Guardian re-checks the exact text")}
          actions={
            <button
              className="text-[12px] text-dawn-700 hover:underline"
              onClick={() => {
                if (!raw && subject) setRawText(JSON.stringify(subject, null, 2));
                setRaw(!raw);
              }}
            >
              {raw ? t("Form view") : t("Raw JSON")}
            </button>
          }
        >
          {!subject && <Skeleton h={220} />}
          {subject && !raw && (
            <div className="space-y-3">
              {subject.texts.map((x: any, i: number) => (
                <Field key={x.id} label={`${tOpen("textKind", x.kind)} · ${x.id}`}>
                  <Textarea
                    rows={2}
                    value={x.text}
                    aria-label={t("line {id}", { id: x.id })}
                    onChange={(e) => {
                      setDirty(true);
                      setSubject({ ...subject, texts: subject.texts.map((y: any, j: number) => (j === i ? { ...y, text: e.target.value } : y)) });
                    }}
                    className="min-h-[56px]"
                  />
                </Field>
              ))}
              <SubjectChips s={subject} />
            </div>
          )}
          {subject && raw && (
            <Textarea
              value={rawText}
              onChange={(e) => {
                setDirty(true);
                setRawText(e.target.value);
              }}
              rows={18}
              className="font-mono text-[12px]"
              aria-label={t("subject json")}
            />
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} loading={busy === "check"} onClick={() => run("check")}>
              {t("Run Guardian")}
            </Button>
            <Button variant="accent" icon={<Wand2 className="h-4 w-4" />} loading={busy === "revise"} onClick={() => run("revise")}>
              {t("Auto-revise (≤3 iterations)")}
            </Button>
          </div>
        </Card>
        <div className="space-y-5">
          <Card title={t("Report")} subtitle={t("Scored report with fix suggestions")}>
            {!report ? <Empty title={t("No report yet")} hint={t("Run the Guardian on the seeded subject.")} /> : <ReportView report={report} />}
          </Card>
          {report && expected.length > 0 && !revision && (
            <Card title={t("Seeded violations caught")} subtitle={t("Every seeded rule must fire")}>
              <ul className="grid gap-1 text-[13px] md:grid-cols-2" data-testid="seeded-coverage">
                {expected.map((r) => (
                  <li key={r} className="flex items-center gap-2">
                    <StatusBadge s={found.has(r) ? "ok" : "failed"} /> <code className="text-[12px]">{r}</code>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {revision && (
            <Card title={t("Auto-revise loop")} subtitle={t("{fixes} · {state}", { fixes: tn(revision.fixes_applied, { one: "{n} fix(es) applied", other: "{n} fix(es) applied" }), state: revision.converged ? t("converged — no blocking findings") : t("not fully converged — human review needed") })}>
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
  const { t, tEnum, fmt } = useI18n();
  const actorName = useActorName();
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
  const [revision] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [waive, setWaive] = useState<any>(null);
  const [why, setWhy] = useState("");
  const role = getRole();
  useOnLangChange(() => setFresh(null)); // the stored report is re-read (and re-rendered by the server) in the new language
  const run = async (auto: boolean) => {
    setBusy(auto ? "revise" : "run");
    try {
      const r = await api.post(`/api/campaigns/${id}/guardian/run`, { artifact_id: aid, auto_revise: auto });
      setFresh({ aid, report: r.report });
      if (auto) toast({ tone: r.converged ? "good" : "warn", title: r.revised ? t("Guardian revised the artifact") : t("Nothing to revise"), body: r.converged ? t("No blocking findings remain.") : t("Open findings need a human decision.") });
      reports.refetch();
      reload();
    } finally {
      setBusy(null);
    }
  };
  const doWaive = async () => {
    await api.post(`/api/campaigns/${id}/guardian/waive`, { artifact_id: aid, finding_id: waive.id, justification: why });
    toast({ tone: "good", title: t("Finding waived"), body: t("Recorded in the audit trail with your justification.") });
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
      <Card title={t("Brand Guardian")} subtitle={t("Brand voice, visual identity, claims, regulated rules, rights & consent, Azure AI Content Safety (text, image, protected material, Prompt Shields), AI disclosure, accessibility.")}>
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Artifact")}>
            <Select
              value={aid}
              onChange={(e) => {
                setAid(e.target.value);
                setFresh(null);
              }}
              className="w-96 max-w-full"
              aria-label={t("artifact")}
            >
              {latestByKind.map((a) => (
                <option key={a.id} value={a.id}>
                  {`${tEnum("artifactKind", a.kind)} v${a.version} · ${tEnum("status", a.status)}${a.guardian ? ` · ${t("guardian {verdict}", { verdict: tEnum("verdict", a.guardian.verdict) })}` : ""}`}
                </option>
              ))}
            </Select>
          </Field>
          <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} disabled={!aid} loading={busy === "run"} onClick={() => run(false)}>
            {t("Run Guardian")}
          </Button>
          <Button variant="accent" icon={<Sparkles className="h-4 w-4" />} disabled={!aid} loading={busy === "revise"} onClick={() => run(true)}>
            {t("Auto-revise")}
          </Button>
          {sel && <GuardianBadge g={sel.guardian} />}
        </div>
      </Card>
      {!aid && <Empty title={t("Nothing to review yet")} hint={t("Create the brief, then run the Guardian at every stage.")} />}
      {aid && reports.isLoading && <Skeleton h={160} />}
      {aid && !reports.isLoading && !report && <Empty title={t("No report for this artifact yet")} hint={t("Run the Guardian to produce a scored report.")} />}
      {report && (
        <Card title={t("Latest report")} subtitle={t("Report {id} · {date}", { id: report.id, date: fmt.dateTime(report.created_at) })}>
          <ReportView report={report} canWaive={role === "legal" || role === "admin"} onWaive={setWaive} />
        </Card>
      )}
      {revision && (
        <Card title={t("Auto-revise loop")}>
          <Iterations items={revision.iterations} />
        </Card>
      )}
      {(reports.data?.waivers ?? []).length > 0 && (
        <Card title={t("Waivers")} subtitle={t("Legal/Admin only — justification recorded in the audit trail")}>
          <ul className="space-y-1.5 text-[13px]">
            {reports.data.waivers.map((w: any) => (
              <li key={w.id}>
                <code className="text-[12px]">{w.finding_id}</code> — {w.justification}{" "}
                <span className="text-espresso-400">
                  · {actorName(w.by)} ({tEnum("roleId", w.by?.role)})
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Modal open={!!waive} onClose={() => setWaive(null)} title={t("Waive a blocking finding")}>
        <p className="mb-3 text-[13px] text-espresso-600">{waive?.message}</p>
        <Field label={t("Justification (min. 10 characters)")}>
          <Textarea value={why} onChange={(e) => setWhy(e.target.value)} aria-label={t("justification")} />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setWaive(null)}>
            {t("Cancel")}
          </Button>
          <Button variant="danger" disabled={why.trim().length < 10} onClick={doWaive}>
            {t("Waive finding")}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-12",
  routes: [{ path: "/guardian", element: <Playground /> }],
  nav: { group: "Review", label: msg("Brand Guardian"), to: "/guardian", order: 10, icon: ShieldCheck },
  workspaceTabs: [{ id: "guardian", label: msg("Guardian"), order: 90, Component: GuardianTab }],
};
