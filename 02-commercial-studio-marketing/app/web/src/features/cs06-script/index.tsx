/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PenLine, ShieldCheck, Wand2 } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Input, Select, Skeleton, Tabs, useToast } from "../../components/ui";
import { FindingList, GuardianBadge, Tag, useJobStarter } from "../../components/common";
import { msg, useI18n, useOnLangChange } from "../../i18n";

const TONES = ["warm", "playful", "premium", "minimal"];

function ScriptTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tn, tEnum, tOpen, fmt } = useI18n();
  const id = campaign.campaign.id;
  const toast = useToast();
  const q = useQuery({ queryKey: ["scripts", id], queryFn: () => api.get(`/api/campaigns/${id}/script`) });
  const copy = useQuery({ queryKey: ["copy", id], queryFn: () => api.get(`/api/campaigns/${id}/copy`) });
  const [durs, setDurs] = useState<number[]>([15]);
  const [tone, setTone] = useState("warm");
  const [sel, setSel] = useState<string | null>(null);
  const [report, setReport] = useState<any>(null);
  const [iters, setIters] = useState<any[] | null>(null);
  const [edits, setEdits] = useState<Record<string, any>>({});
  const job = useJobStarter(() => {
    q.refetch();
    reload();
  });
  const cjob = useJobStarter(() => copy.refetch());
  const scripts: any[] = q.data?.scripts ?? [];
  const cur = scripts.find((s) => s.id === sel) ?? scripts[0];
  useEffect(() => {
    if (cur) setEdits({});
    setReport(null);
    setIters(null);
  }, [cur?.id]);
  // the findings of the last run are rendered by the server in the request language: fetch the stored report again after a language switch
  useOnLangChange(async () => {
    if (!report || !cur) return;
    const r = await api.get(`/api/campaigns/${id}/guardian/reports?artifact_id=${cur.id}&limit=1`);
    if (r.reports?.[0]) setReport(r.reports[0]);
  });
  const check = async (auto: boolean) => {
    const r = await api.post(`/api/campaigns/${id}/guardian/run`, { artifact_id: cur.id, auto_revise: auto });
    setReport(r.report);
    setIters(r.iterations ?? null);
    if (auto)
      toast({
        tone: r.converged ? "good" : "warn",
        title: r.converged ? t("Auto-revise converged") : t("Auto-revise could not fix everything"),
        body: t("{iterations}, verdict: {verdict}", { iterations: tn(r.iterations.length, { one: "{n} iteration(s)", other: "{n} iteration(s)" }), verdict: tEnum("verdict", r.report.verdict) }),
      });
    q.refetch();
    reload();
  };
  const save = async () => {
    const beats = Object.entries(edits).map(([bid, v]: any) => ({ id: bid, ...v }));
    await api.patch(`/api/campaigns/${id}/script/${cur.id}`, { beats });
    toast({ tone: "good", title: t("Script saved"), body: t("Guardian re-ran on the edited text.") });
    setEdits({});
    q.refetch();
    reload();
  };
  const toggleDur = (d: number) => setDurs(durs.includes(d) ? durs.filter((x) => x !== d) : [...durs, d].sort((a, b) => a - b));
  const th = "px-2 py-2";
  return (
    <div className="space-y-5">
      <Card title={t("Script & Copy agent")} subtitle={t("Beats, voice-over, supers and CTA. Brief mandatories are inserted verbatim — the Brand Guardian decides whether they are allowed.")}>
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Durations")} group>
            <div className="flex gap-1.5">
              {[6, 15, 30, 60].map((d) => (
                <button key={d} onClick={() => toggleDur(d)} aria-pressed={durs.includes(d)} className={`rounded-full border px-3.5 py-1.5 text-[13px] ${durs.includes(d) ? "border-dawn-500 bg-dawn-300/30 font-semibold" : "border-cream-300 bg-white"}`}>
                  {t("{n}s", { n: d })}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t("Tone")}>
            <Select value={tone} onChange={(e) => setTone(e.target.value)} className="w-44">
              {TONES.map((x) => (
                <option key={x} value={x}>
                  {tEnum("tone", x)}
                </option>
              ))}
            </Select>
          </Field>
          <Button variant="accent" icon={<PenLine className="h-4 w-4" />} loading={job.busy} disabled={!durs.length} onClick={() => job.start(`/api/campaigns/${id}/script/generate`, { durations: durs, tone })}>
            {tn(durs.length, { one: "Write {list}s script", other: "Write {list}s scripts" }, { list: durs.join("/") })}
          </Button>
          <Button variant="outline" loading={cjob.busy} onClick={() => cjob.start(`/api/campaigns/${id}/copy/generate`, {})}>
            {t("Channel copy")}
          </Button>
        </div>
        <div className="mt-3 space-y-2">
          {job.node}
          {cjob.node}
        </div>
      </Card>
      {q.isLoading && <Skeleton h={220} />}
      {!q.isLoading && !cur && <Empty title={t("No script yet")} hint={t("Finalize the brief (and pick a territory), then write the script.")} />}
      {cur && (
        <>
          <Tabs
            tabs={scripts.map((s) => ({
              id: s.id,
              label: (
                <span>
                  {t("{n}s · v{version}", { n: s.duration_s, version: String(s.version) })} <span className="text-espresso-400">{tEnum("tone", s.tone)}</span>
                </span>
              ),
              badge: <GuardianBadge g={s.guardian} />,
            }))}
            value={cur.id}
            onChange={setSel}
          />
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2" title={cur.title} subtitle={cur.logline} actions={<span className="text-[12px] text-espresso-500">{t("{count}/{budget} words", { count: cur.word_count, budget: cur.word_budget })}</span>} pad={false}>
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full text-[13px]" data-testid="beats">
                  <thead>
                    <tr className="border-b border-cream-200 text-left text-[11px] uppercase tracking-wider text-espresso-500">
                      <th className="px-4 py-2">{t("Time")}</th>
                      <th className={th}>{t("Beat")}</th>
                      <th className={th}>{t("Visual")}</th>
                      <th className={th}>{t("Voice-over")}</th>
                      <th className={th}>{t("Super")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cur.beats.map((b: any) => (
                      <tr key={b.id} className="border-b border-cream-100 align-top">
                        <td className="whitespace-nowrap px-4 py-2 tabular-nums text-espresso-500">{t("{start}–{end}s", { start: b.t_start, end: b.t_end })}</td>
                        <td className="px-2 py-2">
                          <Badge>{tOpen("beatRole", b.role)}</Badge>
                        </td>
                        <td className="px-2 py-2 text-espresso-600">{b.visual}</td>
                        <td className="px-2 py-2">
                          <Input key={`vo-${b.id}-${b.vo}`} aria-label={t("vo {id}", { id: b.id })} defaultValue={b.vo} onChange={(e) => setEdits({ ...edits, [b.id]: { ...edits[b.id], vo: e.target.value } })} className="min-w-[200px]" />
                          <div className={`mt-0.5 text-[11px] ${b.wps > 2.9 ? "text-roast-500" : "text-espresso-400"}`}>{tn(b.wps, { one: "{n} words/s", other: "{n} words/s" })}</div>
                        </td>
                        <td className="px-2 py-2">
                          <Input key={`super-${b.id}-${b.super_text ?? ""}`} aria-label={t("super {id}", { id: b.id })} defaultValue={b.super_text ?? ""} onChange={(e) => setEdits({ ...edits, [b.id]: { ...edits[b.id], super_text: e.target.value } })} className="min-w-[120px]" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="text-[12.5px] text-espresso-500">
                  {t("CTA:")} <b>{cur.cta}</b> · {t("Music cue:")} <b>{cur.music?.title || "—"}</b> <Badge tone={cur.music?.rights_id ? "good" : "warn"}>{cur.music?.rights_id ? t("licensed") : t("reference")}</Badge>
                  {cur.legal?.length > 0 && (
                    <>
                      {" "}
                      · {t("Legal:")}{" "}
                      {cur.legal.map((l: string) => (
                        <Tag key={l}>{l}</Tag>
                      ))}
                    </>
                  )}
                </div>
                <Button size="sm" variant="outline" disabled={!Object.keys(edits).length} onClick={save}>
                  {t("Save edits")}
                </Button>
              </div>
            </Card>
            <Card title={t("Brand Guardian")} subtitle={t("Deterministic rules + Azure AI Content Safety")} actions={<GuardianBadge g={cur.guardian} />}>
              <div className="mb-3 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" icon={<ShieldCheck className="h-3.5 w-3.5" />} onClick={() => check(false)}>
                  {t("Run checks")}
                </Button>
                <Button size="sm" variant="accent" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => check(true)}>
                  {t("Auto-revise")}
                </Button>
              </div>
              {report ? (
                <FindingList findings={report.findings} />
              ) : (
                <div className="text-[13px] text-espresso-500">
                  {cur.guardian
                    ? t("{blocks}, {warns}. Run checks to see the findings.", {
                        blocks: tn(cur.guardian.blocks, { one: "{n} blocking", other: "{n} blocking" }),
                        warns: tn(cur.guardian.warns, { one: "{n} warning(s)", other: "{n} warning(s)" }),
                      })
                    : t("Not reviewed yet.")}
                </div>
              )}
              {iters && (
                <div className="mt-4 border-t border-cream-200 pt-3 text-[12.5px]" data-testid="iterations">
                  <div className="mb-1 font-semibold">{t("Auto-revise trace")}</div>
                  {iters.map((it: any) => (
                    <div key={it.iteration} className="mb-1.5 rounded-lg bg-cream-100 px-2.5 py-1.5">
                      {t("#{n}: {verdict} ({blocks} · {warns})", { n: it.iteration, verdict: tEnum("verdict", it.verdict), blocks: tn(it.blocks, { one: "{n} block", other: "{n} block" }), warns: tn(it.warns, { one: "{n} warn", other: "{n} warn" }) })}{" "}
                      {it.fixes.length > 0 && <span className="text-espresso-500">→ {it.fixes.map((f: any) => tEnum("fixOp", f.op)).join(", ")}</span>}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}
      {(copy.data?.copy ?? []).length > 0 && (
        <Card title={t("Channel copy")} subtitle={t("Headlines ≤ 40 chars, captions, email — Guardian-reviewed")}>
          <div className="grid gap-3 md:grid-cols-2">
            {copy.data.copy[0].items.map((it: any) => (
              <div key={it.id} className="rounded-xl border border-cream-200 bg-cream-50 px-3.5 py-2.5 text-[13px]">
                <div className="mb-0.5 flex items-center gap-2">
                  <Badge tone="dark">{tOpen("channel", it.channel)}</Badge>
                  <span className="text-[11.5px] uppercase text-espresso-500">{tEnum("copyKind", it.kind)}</span>
                </div>
                {it.text}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-06", workspaceTabs: [{ id: "script", label: msg("Script"), order: 30, Component: ScriptTab }] };
