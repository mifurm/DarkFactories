/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Layers } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Skeleton, useToast } from "../../components/ui";
import { GuardianBadge, Img, Video, useJobStarter } from "../../components/common";

const ASPECTS = ["9:16", "1:1", "4:5"];
const CUTS = [6, 15, 30];

function FormatsTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const toast = useToast();
  const tree = useQuery({ queryKey: ["fmt-tree", id], queryFn: () => api.get(`/api/campaigns/${id}/formats/tree`) });
  const [aspects, setAspects] = useState<string[]>(["9:16", "1:1"]);
  const [cuts, setCuts] = useState<number[]>([6]);
  const [view, setView] = useState<string | null>(null);
  const job = useJobStarter(() => {
    tree.refetch();
    reload();
  });
  const nodes: any[] = tree.data?.nodes ?? [];
  const roots = nodes.filter((n) => !n.parent_id);
  const kids = (p: string) => nodes.filter((n) => n.parent_id === p);
  const viewing = nodes.find((n) => n.id === view) ?? nodes[0];
  const approve = async (ids: string[]) => {
    const r = await api.post(`/api/campaigns/${id}/formats/versions/approve`, { spot_ids: ids });
    toast({ tone: r.refused.length ? "warn" : "good", title: `${r.approved.length} version(s) approved`, body: r.refused.length ? `${r.refused.length} refused by the Guardian` : undefined });
    tree.refetch();
  };
  const tgl = <T,>(arr: T[], v: T, set: (x: T[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const row = (n: any, depth: number) => (
    <li key={n.id}>
      <div className={`flex flex-wrap items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] hover:bg-cream-100 ${viewing?.id === n.id ? "bg-cream-200" : ""}`} style={{ marginLeft: depth * 22 }}>
        <button className="flex items-center gap-2 text-left font-medium" onClick={() => setView(n.id)}>
          {depth > 0 && <span className="text-espresso-300">└</span>}
          {n.label} <span className="text-espresso-400">v{n.version} · {n.duration.toFixed(1)}s</span>
        </button>
        <Badge tone={n.kind === "master" ? "dark" : "neutral"}>{n.kind}</Badge>
        <GuardianBadge g={n.guardian} />
        <Badge tone={n.status === "approved" ? "good" : "warn"}>{n.status}</Badge>
        {n.status !== "approved" && n.kind !== "master" && (
          <Button size="sm" variant="outline" icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={() => approve([n.id])}>Approve</Button>
        )}
      </div>
      {kids(n.id).length > 0 && <ul>{kids(n.id).map((k) => row(k, depth + 1))}</ul>}
    </li>
  );
  return (
    <div className="space-y-5">
      <Card title="Format factory" subtitle="Reframe the approved master with per-scene focal points + platform safe areas, cut 6/15/30 s versions by scene priority; overlays and end card are re-laid-out from the template.">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2 text-[13px]"><span className="text-espresso-500">Aspect ratios</span>{ASPECTS.map((a) => <label key={a} className="flex items-center gap-1"><input type="checkbox" checked={aspects.includes(a)} onChange={() => tgl(aspects, a, setAspects)} />{a}</label>)}</div>
          <div className="flex items-center gap-2 text-[13px]"><span className="text-espresso-500">Cutdowns</span>{CUTS.map((c) => <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={cuts.includes(c)} onChange={() => tgl(cuts, c, setCuts)} />{c}s</label>)}</div>
          <Button variant="accent" icon={<Layers className="h-4 w-4" />} disabled={!aspects.length && !cuts.length} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/formats/generate`, { aspects, cutdowns: cuts })}>
            Generate versions
          </Button>
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
      </Card>
      {tree.isLoading && <Skeleton h={200} />}
      {!tree.isLoading && !nodes.length && <Empty title="No renders yet" hint="Render the master spot first (Video tab)." />}
      {nodes.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
          <Card title="Version tree" subtitle="master → formats / cutdowns / localizations" testId="version-tree">
            <ul className="space-y-0.5">{roots.map((r) => row(r, 0))}</ul>
          </Card>
          {viewing && (
            <Card title={viewing.label} subtitle={`${viewing.aspect} · ${viewing.duration.toFixed(1)} s`}>
              <div className={viewing.aspect === "9:16" ? "mx-auto max-w-[220px]" : ""}>
                {viewing.video_asset_id ? <Video id={viewing.video_asset_id} poster={viewing.poster_asset_id} /> : <Img id={viewing.poster_asset_id} className="w-full rounded-xl" />}
              </div>
              {viewing.notes?.length > 0 && <ul className="mt-3 list-disc pl-5 text-[12.5px] text-espresso-600">{viewing.notes.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-11", workspaceTabs: [{ id: "formats", label: "Formats & cutdowns", order: 80, Component: FormatsTab }] };
