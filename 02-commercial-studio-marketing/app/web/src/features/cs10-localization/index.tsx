/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Languages } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Skeleton, StatusBadge } from "../../components/ui";
import { GuardianBadge, Video, useJobStarter } from "../../components/common";

function LocalizationTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const langs = useQuery({ queryKey: ["langs", id], queryFn: () => api.get(`/api/campaigns/${id}/localization/languages`), staleTime: 600000 });
  const list = useQuery({ queryKey: ["loc", id], queryFn: () => api.get(`/api/campaigns/${id}/localization`) });
  const [sel, setSel] = useState<string[]>(["de", "fr", "pl"]);
  const [render, setRender] = useState(true);
  const job = useJobStarter(() => {
    list.refetch();
    reload();
  });
  const items: any[] = list.data?.localizations ?? [];
  const latest = Object.values(Object.fromEntries(items.slice().reverse().map((x) => [x.lang, x]))) as any[];
  const toggle = (c: string) => setSel((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]));
  return (
    <div className="space-y-5">
      <Card title="Localizer" subtitle="Transcreation (not literal translation) with glossary + do-not-translate enforcement, back-translation QA, localized voice-over, captions and end card — each version gets its own local-market Guardian review.">
        <div className="flex flex-wrap items-center gap-2">
          {(langs.data?.languages ?? []).filter((l: any) => l.code !== "en").map((l: any) => (
            <button key={l.code} onClick={() => toggle(l.code)} title={l.notes} aria-pressed={sel.includes(l.code)} className={`rounded-full border px-3 py-1 text-[13px] ${sel.includes(l.code) ? "border-dawn-500 bg-dawn-300/25 font-semibold" : "border-cream-300 bg-white"}`}>
              {l.name} <span className="text-espresso-400">· {l.market}</span>
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={render} onChange={(e) => setRender(e.target.checked)} /> also voice + render localized MP4</label>
          <Button variant="accent" icon={<Languages className="h-4 w-4" />} disabled={!sel.length} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/localization/generate`, { langs: sel, render })}>
            Localize ({sel.length})
          </Button>
          <span className="text-[12px] text-espresso-400">Scripts shipped: Latin, Cyrillic, Greek. CJK/Arabic need extra fonts (documented, not shipped).</span>
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
      </Card>
      {list.isLoading && <Skeleton h={200} />}
      {!list.isLoading && !latest.length && <Empty title="No localizations yet" hint="Approve-ready script and a rendered master are recommended first." />}
      <div className="space-y-5" data-testid="localizations">
        {latest.map((l) => (
          <Card key={l.id} title={`${l.title}`} subtitle={`Tagline: “${l.tagline}” · min back-translation similarity ${l.min_similarity}`} actions={<><GuardianBadge g={l.guardian} />{l.needs_review.length ? <Badge tone="warn">{l.needs_review.length} line(s) need review</Badge> : <Badge tone="good">QA passed</Badge>}</>} pad={false}>
            <div className={`grid gap-4 p-4 ${l.video_asset_id ? "lg:grid-cols-[1fr_320px]" : ""}`}>
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead><tr className="border-b border-cream-300 text-[11.5px] uppercase tracking-wider text-espresso-500"><th className="px-2 py-1.5">Line</th><th className="px-2 py-1.5">Source (EN)</th><th className="px-2 py-1.5">{l.lang.toUpperCase()}</th><th className="px-2 py-1.5">Back-translation</th><th className="px-2 py-1.5">Sim.</th></tr></thead>
                  <tbody>
                    {l.lines.map((r: any) => (
                      <tr key={r.id} className="border-b border-cream-200 align-top last:border-0">
                        <td className="px-2 py-1.5 text-espresso-500">{r.id}</td>
                        <td className="px-2 py-1.5">{r.source}</td>
                        <td className="px-2 py-1.5 font-medium">{r.text}</td>
                        <td className="px-2 py-1.5 text-espresso-500">{r.back_translation}</td>
                        <td className="px-2 py-1.5"><StatusBadge s={r.status === "ok" ? "ok" : "warn"} /> <span className="tabular-nums text-espresso-500">{r.similarity}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {l.glossary_issues?.length > 0 && <div className="mt-2 text-[12px] text-espresso-500">Glossary enforcement: {l.glossary_issues.length} issue(s) detected, {l.glossary_issues.filter((i: any) => i.repaired).length} auto-repaired.</div>}
                {l.legal?.length > 0 && <div className="mt-1 text-[12px] text-espresso-500">Legal line: {l.legal.join(" · ")}</div>}
              </div>
              {l.video_asset_id && <div><Video id={l.video_asset_id} /></div>}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-10", workspaceTabs: [{ id: "localization", label: "Localization", order: 70, Component: LocalizationTab }] };
