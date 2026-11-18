/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilePlus2, FileText, ShieldAlert } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Meter, PageHeader, Select, Spinner, Textarea, useToast } from "../../components/ui";
import { FindingList, GuardianBadge, Tag } from "../../components/common";

const CHANNELS = ["youtube", "meta", "tiktok", "ctv", "linkedin", "display"];
const MARKETS = ["US", "DE", "FR", "PL", "ES", "IT", "GB", "NL"];

function Wizard() {
  const nav = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("Dawn Roast — Launch (live demo)");
  const [markets, setMarkets] = useState<string[]>(["US", "DE", "FR", "PL"]);
  const [channels, setChannels] = useState<string[]>(["youtube", "meta", "tiktok", "ctv"]);
  const [text, setText] = useState("");
  const [cid, setCid] = useState<string | null>(null);
  const [brief, setBrief] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [final, setFinal] = useState<any>(null);
  const toggle = (arr: string[], v: string, set: (a: string[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const loadSample = async () => {
    const s = await api.get("/api/campaigns/samples");
    setText(s[0].brief_text);
  };
  const analyze = async () => {
    setBusy(true);
    try {
      let id = cid;
      if (!id) {
        const c = await api.post("/api/campaigns", { name, markets, channels, raw_text: text });
        id = c.id;
        setCid(c.id);
      }
      const b = await api.post(`/api/campaigns/${id}/brief/analyze`, { raw_text: text });
      setBrief(b);
      setStep(3);
    } finally {
      setBusy(false);
    }
  };
  const answer = async () => {
    setBusy(true);
    try {
      const payload: Record<string, any> = {};
      Object.entries(answers).forEach(([k, v]) => v.trim() && (payload[k] = k === "duration_targets" ? v.split(/[ ,]+/).map(Number).filter(Boolean) : v));
      const b = await api.post(`/api/campaigns/${cid}/brief/answers`, { answers: payload });
      setBrief(b);
    } finally {
      setBusy(false);
    }
  };
  const finalize = async () => {
    setBusy(true);
    try {
      const f = await api.post(`/api/campaigns/${cid}/brief/finalize`);
      setFinal(f);
      setStep(4);
      toast({ tone: "good", title: "Brief finalized", body: "Normalized brief saved as a versioned artifact." });
    } finally {
      setBusy(false);
    }
  };
  const comp = brief?.completeness;
  return (
    <div data-testid="brief-wizard">
      <PageHeader eyebrow="CS-04 · Briefing agent" title="New campaign brief" subtitle="Paste a brief or fill the fields. The Briefing agent extracts the structure, checks completeness and asks up to three clarifying questions." />
      <ol className="mb-5 flex gap-2 text-[12.5px] font-semibold">
        {["Campaign", "Brief", "Clarify", "Normalized"].map((s, i) => (
          <li key={s} className={`rounded-full px-3 py-1 ${step === i + 1 ? "bg-espresso-800 text-cream-50" : step > i + 1 ? "bg-sage-100 text-sage-600" : "bg-cream-200 text-espresso-500"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      {step === 1 && (
        <Card title="Campaign" subtitle="Markets and channels drive claims rules, rights checks and disclosure labels.">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Campaign name">
              <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Campaign name" />
            </Field>
            <div />
            <Field label="Markets">
              <div className="flex flex-wrap gap-1.5">
                {MARKETS.map((m) => (
                  <button key={m} onClick={() => toggle(markets, m, setMarkets)} className={`rounded-full border px-3 py-1 text-[12.5px] ${markets.includes(m) ? "border-dawn-500 bg-dawn-300/30 font-semibold" : "border-cream-300 bg-white"}`}>
                    {m}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Channels">
              <div className="flex flex-wrap gap-1.5">
                {CHANNELS.map((m) => (
                  <button key={m} onClick={() => toggle(channels, m, setChannels)} className={`rounded-full border px-3 py-1 text-[12.5px] ${channels.includes(m) ? "border-dawn-500 bg-dawn-300/30 font-semibold" : "border-cream-300 bg-white"}`}>
                    {m}
                  </button>
                ))}
              </div>
            </Field>
          </div>
          <div className="mt-5 flex justify-end">
            <Button onClick={() => setStep(2)} disabled={name.length < 3 || !markets.length}>
              Continue
            </Button>
          </div>
        </Card>
      )}
      {step === 2 && (
        <Card title="Paste the brief" subtitle="Free text, an email, or text from a document. Anything inside is treated as data — Prompt Shields screens it for injection." actions={<Button size="sm" variant="outline" icon={<FileText className="h-3.5 w-3.5" />} onClick={loadSample}>Load sample (Dawn Roast)</Button>}>
          <Textarea rows={13} value={text} onChange={(e) => setText(e.target.value)} placeholder="Objective: … Audience: … Channels: … Mandatories: …" aria-label="Brief text" />
          <div className="mt-4 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>
            <Button variant="accent" loading={busy} onClick={analyze} disabled={text.trim().length < 30}>
              Analyze with the Briefing agent
            </Button>
          </div>
        </Card>
      )}
      {step === 3 && brief && (
        <div className="grid gap-5 lg:grid-cols-5">
          <Card className="lg:col-span-3" title="Extracted brief" subtitle="Normalized fields (editable after finalize via re-analysis)">
            <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-[13px]">
              {Object.entries(brief.fields ?? {}).map(([k, v]: any) => (
                <div key={k} className="contents">
                  <dt className="text-espresso-500">{k.replace(/_/g, " ")}</dt>
                  <dd className={Array.isArray(v) ? v.length ? "" : "text-roast-500" : v ? "" : "text-roast-500"}>
                    {Array.isArray(v) ? (v.length ? v.join(" · ") : "— missing") : v || "— missing"}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
          <div className="space-y-5 lg:col-span-2">
            <Card title="Completeness" subtitle={`${comp?.score}% — need ≥ 80% to finalize`}>
              <Meter value={comp?.score ?? 0} max={100} />
              <div className="mt-2 flex flex-wrap gap-1.5">{(comp?.missing ?? []).map((m: string) => <Badge key={m} tone="warn">{m.replace(/_/g, " ")}</Badge>)}</div>
            </Card>
            {(brief.questions ?? []).length > 0 && (
              <Card title="Clarifying questions" subtitle="The Briefing agent asks at most three" testId="questions">
                <div className="space-y-3">
                  {brief.questions.map((q: any) => (
                    <Field key={q.field} label={q.question} hint={q.field === "duration_targets" ? "e.g. 6, 15, 30" : q.why}>
                      <Input value={answers[q.field] ?? ""} onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} aria-label={q.field} />
                    </Field>
                  ))}
                  <Button loading={busy} variant="outline" onClick={answer}>Apply answers</Button>
                </div>
              </Card>
            )}
            <Button variant="accent" className="w-full" loading={busy} disabled={!comp?.ready} onClick={finalize}>
              Finalize brief
            </Button>
          </div>
        </div>
      )}
      {step === 4 && final && (
        <Card title="Brief finalized" subtitle="Saved as a versioned artifact. The Guardian already reviewed it:" actions={<GuardianBadge g={final.artifact.guardian} />}>
          <FindingList findings={final.guardian_report.findings} />
          <div className="mt-5 flex justify-end">
            <Button variant="accent" onClick={() => nav(`/campaigns/${cid}/strategy`)}>Continue to Strategy →</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function BriefTab({ campaign, reload }: WorkspaceTabProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const brief = campaign.brief;
  const art = campaign.artifacts.find((a: any) => a.kind === "brief");
  useEffect(() => setText(brief?.raw_text ?? ""), [brief?.raw_text]);
  const rerun = async () => {
    setBusy(true);
    try {
      await api.post(`/api/campaigns/${campaign.campaign.id}/brief/analyze`, { raw_text: text });
      const f = await api.post(`/api/campaigns/${campaign.campaign.id}/brief/finalize`);
      toast({ tone: f.artifact.guardian.verdict === "block" ? "warn" : "good", title: "Brief re-analyzed", body: `Guardian: ${f.artifact.guardian.verdict}` });
      reload();
    } finally {
      setBusy(false);
    }
  };
  const fields = brief?.fields ?? {};
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2" title="Normalized brief" subtitle={art ? `Artifact v${art.version}` : "Not finalized yet"} actions={art && <GuardianBadge g={art.guardian} />}>
        {!art && <Empty title="No finalized brief" hint="Use the wizard to paste and finalize the brief." action={<a href="/campaigns/new" className="text-dawn-600 underline">Open wizard</a>} />}
        {art && (
          <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-[13px]">
            {Object.entries(fields).map(([k, v]: any) => (
              <div key={k} className="contents">
                <dt className="text-espresso-500">{k.replace(/_/g, " ")}</dt>
                <dd>{Array.isArray(v) ? v.map((x: string) => <Tag key={x}>{x}</Tag>) : String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>
      <Card title="Source text" subtitle="Edit and re-analyze (new versioned artifact)">
        <Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} />
        <Button className="mt-3" variant="outline" loading={busy} onClick={rerun} icon={busy ? <Spinner /> : <ShieldAlert className="h-4 w-4" />}>
          Re-analyze &amp; re-check
        </Button>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-04",
  routes: [{ path: "/campaigns/new", element: <Wizard /> }],
  nav: { group: "Studio", label: "New brief", to: "/campaigns/new", order: 1, icon: FilePlus2 },
  workspaceTabs: [{ id: "brief", label: "Brief", order: 10, Component: BriefTab }],
};
