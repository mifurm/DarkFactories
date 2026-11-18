/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FilePlus2, FileText, ShieldAlert } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Meter, PageHeader, Select, Spinner, Textarea, useToast } from "../../components/ui";
import { FindingList, GuardianBadge, Tag } from "../../components/common";
import { msg, SUPPORTED_LANGS, useI18n, useLocalizedDefault, type Lang } from "../../i18n";

const CHANNELS = ["youtube", "meta", "tiktok", "ctv", "linkedin", "display"];
const MARKETS = ["US", "DE", "FR", "PL", "ES", "IT", "GB", "NL"];

function Wizard() {
  const { t, tEnum, tOpen, fmt } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState(1);
  const [name, setName] = useLocalizedDefault((i) => i.t("Dawn Roast — Launch (live demo)"));
  const [language, setLanguage] = useLocalizedDefault((i) => i.lang); // campaign language: follows the UI language until chosen explicitly
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
    const samples: any[] = await api.get("/api/campaigns/samples");
    const pick = samples.find((s) => (s.language ?? s.lang) === language) ?? samples[0];
    setText(pick.brief_text);
  };
  const analyze = async () => {
    setBusy(true);
    try {
      let id = cid;
      if (!id) {
        const c = await api.post("/api/campaigns", { name, markets, channels, raw_text: text, language });
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
      toast({ tone: "good", title: t("Brief finalized"), body: t("Normalized brief saved as a versioned artifact.") });
    } finally {
      setBusy(false);
    }
  };
  const comp = brief?.completeness;
  const steps = [t("Campaign"), t("Brief"), t("Clarify"), t("Normalized")];
  const chip = (on: boolean) => `rounded-full border px-3 py-1 text-[12.5px] ${on ? "border-dawn-500 bg-dawn-300/30 font-semibold" : "border-cream-300 bg-white"}`;
  return (
    <div data-testid="brief-wizard">
      <PageHeader eyebrow={t("CS-04 · Briefing agent")} title={t("New campaign brief")} subtitle={t("Paste a brief or fill the fields. The Briefing agent extracts the structure, checks completeness and asks up to three clarifying questions.")} />
      <ol className="mb-5 flex flex-wrap gap-2 text-[12.5px] font-semibold">
        {steps.map((s, i) => (
          <li key={i} className={`rounded-full px-3 py-1 ${step === i + 1 ? "bg-espresso-800 text-cream-50" : step > i + 1 ? "bg-sage-100 text-sage-600" : "bg-cream-200 text-espresso-500"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      {step === 1 && (
        <Card title={t("Campaign")} subtitle={t("Markets and channels drive claims rules, rights checks and disclosure labels.")}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={t("Campaign name")}>
              <Input value={name} onChange={(e) => setName(e.target.value)} aria-label={t("Campaign name")} />
            </Field>
            <Field label={t("Campaign language")} hint={t("Language of the creative content (script, voice-over, captions). Defaults to the interface language.")}>
              <Select value={language} onChange={(e) => setLanguage(e.target.value as Lang)} aria-label={t("Campaign language")} data-testid="campaign-language">
                {SUPPORTED_LANGS.map((l) => (
                  <option key={l} value={l}>
                    {fmt.languageName(l)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("Markets")} group>
              <div className="flex flex-wrap gap-1.5">
                {MARKETS.map((m) => (
                  <button key={m} onClick={() => toggle(markets, m, setMarkets)} aria-pressed={markets.includes(m)} className={chip(markets.includes(m))}>
                    {m}
                  </button>
                ))}
              </div>
            </Field>
            <Field label={t("Channels")} group>
              <div className="flex flex-wrap gap-1.5">
                {CHANNELS.map((m) => (
                  <button key={m} onClick={() => toggle(channels, m, setChannels)} aria-pressed={channels.includes(m)} className={chip(channels.includes(m))}>
                    {tOpen("channel", m)}
                  </button>
                ))}
              </div>
            </Field>
          </div>
          <div className="mt-5 flex justify-end">
            <Button onClick={() => setStep(2)} disabled={name.length < 3 || !markets.length}>
              {t("Continue")}
            </Button>
          </div>
        </Card>
      )}
      {step === 2 && (
        <Card
          title={t("Paste the brief")}
          subtitle={t("Free text, an email, or text from a document. Anything inside is treated as data — Prompt Shields screens it for injection.")}
          actions={
            <Button size="sm" variant="outline" icon={<FileText className="h-3.5 w-3.5" />} onClick={loadSample}>
              {t("Load sample (Dawn Roast)")}
            </Button>
          }
        >
          <Textarea rows={13} value={text} onChange={(e) => setText(e.target.value)} placeholder={t("Objective: … Audience: … Channels: … Mandatories: …")} aria-label={t("Brief text")} />
          <div className="mt-4 flex flex-wrap justify-between gap-2">
            <Button variant="ghost" onClick={() => setStep(1)}>
              {t("Back")}
            </Button>
            <Button variant="accent" loading={busy} onClick={analyze} disabled={text.trim().length < 30}>
              {t("Analyze with the Briefing agent")}
            </Button>
          </div>
        </Card>
      )}
      {step === 3 && brief && (
        <div className="grid gap-5 lg:grid-cols-5">
          <Card className="lg:col-span-3" title={t("Extracted brief")} subtitle={t("Normalized fields (editable after finalize via re-analysis)")}>
            <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-[13px]">
              {Object.entries(brief.fields ?? {}).map(([k, v]: any) => (
                <div key={k} className="contents">
                  <dt className="text-espresso-500">{tEnum("briefField", k)}</dt>
                  <dd className={Array.isArray(v) ? (v.length ? "" : "text-roast-500") : v ? "" : "text-roast-500"}>{Array.isArray(v) ? (v.length ? v.join(" · ") : t("— missing")) : v || t("— missing")}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <div className="space-y-5 lg:col-span-2">
            <Card title={t("Completeness")} subtitle={t("{score}% — need ≥ 80% to finalize", { score: String(comp?.score) })}>
              <Meter value={comp?.score ?? 0} max={100} />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(comp?.missing ?? []).map((m: string) => (
                  <Badge key={m} tone="warn">
                    {tEnum("briefField", m)}
                  </Badge>
                ))}
              </div>
            </Card>
            {(brief.questions ?? []).length > 0 && (
              <Card title={t("Clarifying questions")} subtitle={t("The Briefing agent asks at most three")} testId="questions">
                <div className="space-y-3">
                  {brief.questions.map((q: any) => (
                    <Field key={q.field} label={q.question} hint={q.field === "duration_targets" ? t("e.g. 6, 15, 30") : q.why}>
                      <Input value={answers[q.field] ?? ""} onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} aria-label={tEnum("briefField", q.field)} />
                    </Field>
                  ))}
                  <Button loading={busy} variant="outline" onClick={answer}>
                    {t("Apply answers")}
                  </Button>
                </div>
              </Card>
            )}
            <Button variant="accent" className="w-full" loading={busy} disabled={!comp?.ready} onClick={finalize}>
              {t("Finalize brief")}
            </Button>
          </div>
        </div>
      )}
      {step === 4 && final && (
        <Card title={t("Brief finalized")} subtitle={t("Saved as a versioned artifact. The Guardian already reviewed it:")} actions={<GuardianBadge g={final.artifact.guardian} />}>
          <FindingList findings={final.guardian_report.findings} />
          <div className="mt-5 flex justify-end">
            <Button variant="accent" onClick={() => nav(`/campaigns/${cid}/strategy`)}>
              {t("Continue to Strategy →")}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function BriefTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tEnum } = useI18n();
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
      toast({ tone: f.artifact.guardian.verdict === "block" ? "warn" : "good", title: t("Brief re-analyzed"), body: t("Guardian: {verdict}", { verdict: tEnum("verdict", f.artifact.guardian.verdict) }) });
      reload();
    } finally {
      setBusy(false);
    }
  };
  const fields = brief?.fields ?? {};
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2" title={t("Normalized brief")} subtitle={art ? t("Artifact v{version}", { version: String(art.version) }) : t("Not finalized yet")} actions={art && <GuardianBadge g={art.guardian} />}>
        {!art && (
          <Empty
            title={t("No finalized brief")}
            hint={t("Use the wizard to paste and finalize the brief.")}
            action={
              <Link to="/campaigns/new" className="text-dawn-600 underline">
                {t("Open wizard")}
              </Link>
            }
          />
        )}
        {art && (
          <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-[13px]">
            {Object.entries(fields).map(([k, v]: any) => (
              <div key={k} className="contents">
                <dt className="text-espresso-500">{tEnum("briefField", k)}</dt>
                <dd>
                  {Array.isArray(v)
                    ? v.map((x: string) => (
                        <Tag key={x}>{x}</Tag>
                      ))
                    : String(v)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </Card>
      <Card title={t("Source text")} subtitle={t("Edit and re-analyze (new versioned artifact)")}>
        <Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} aria-label={t("Source text")} />
        <Button className="mt-3" variant="outline" loading={busy} onClick={rerun} icon={busy ? <Spinner /> : <ShieldAlert className="h-4 w-4" />}>
          {t("Re-analyze & re-check")}
        </Button>
      </Card>
    </div>
  );
}

export const feature: FeatureDef = {
  id: "CS-04",
  routes: [{ path: "/campaigns/new", element: <Wizard /> }],
  nav: { group: "Studio", label: msg("New brief"), to: "/campaigns/new", order: 1, icon: FilePlus2 },
  workspaceTabs: [{ id: "brief", label: msg("Brief"), order: 10, Component: BriefTab }],
};
