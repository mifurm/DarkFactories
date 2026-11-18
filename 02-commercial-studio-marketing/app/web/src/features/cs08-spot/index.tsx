/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Film, RefreshCw } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, KV, Select, Skeleton } from "../../components/ui";
import { GuardianBadge, Video, useJobStarter } from "../../components/common";

function VideoTab({ campaign, reload }: WorkspaceTabProps) {
  const id = campaign.campaign.id;
  const q = useQuery({ queryKey: ["spots", id], queryFn: () => api.get(`/api/campaigns/${id}/spot`) });
  const [aspect, setAspect] = useState("16:9");
  const [lufs, setLufs] = useState(-16);
  const [sel, setSel] = useState<string | null>(null);
  const job = useJobStarter(() => {
    q.refetch();
    reload();
  });
  const spots: any[] = q.data?.spots ?? [];
  const masters = spots.filter((s) => (s.lineage_kind ?? "master") === "master");
  const cur = spots.find((s) => s.id === sel) ?? masters[0];
  return (
    <div className="space-y-5">
      <Card title="Director · spot compositor" subtitle="Ken-Burns/parallax motion on the keyframes, dissolves, voice-over, burned-in captions + SRT, music bed, logo, AI-disclosure badge and brand end card — rendered by ffmpeg behind a pluggable VideoProvider.">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Aspect">
            <Select value={aspect} onChange={(e) => setAspect(e.target.value)} className="w-32" aria-label="aspect">
              {["16:9", "9:16", "1:1", "4:5"].map((a) => <option key={a}>{a}</option>)}
            </Select>
          </Field>
          <Field label="Loudness target">
            <Select value={lufs} onChange={(e) => setLufs(+e.target.value)} className="w-52" aria-label="loudness">
              <option value={-16}>−16 LUFS (digital / social)</option>
              <option value={-14}>−14 LUFS (streaming)</option>
              <option value={-23}>−23 LUFS (EBU R128 broadcast)</option>
            </Select>
          </Field>
          <Button variant="accent" icon={<Film className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/spot/render`, { aspect, loudness_lufs: lufs })}>
            Render spot
          </Button>
          {cur?.needs_rerender && (
            <Button variant="outline" icon={<RefreshCw className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/spot/${cur.id}/rerender`)}>
              Re-render with Guardian fixes
            </Button>
          )}
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
        <div className="mt-2 text-[12px] text-espresso-400">Provider: {q.data?.provider?.kind ?? "compositor"} · {q.data?.provider?.codec ?? ""} · generative video models plug in via VideoProvider (Sora-2 is deprecated in swedencentral).</div>
      </Card>
      {q.isLoading && <Skeleton h={300} />}
      {!q.isLoading && !cur && <Empty title="No spot rendered yet" hint="You need a script, storyboard keyframes and a voice-over first." />}
      {cur && (
        <div className="grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-2" title={cur.title} subtitle={`${cur.aspect} · ${cur.duration}s`} actions={<GuardianBadge g={cur.guardian} />}>
            <div className={`mx-auto ${cur.aspect === "9:16" ? "max-w-[300px]" : cur.aspect === "1:1" || cur.aspect === "4:5" ? "max-w-[460px]" : ""}`}>
              <Video id={cur.assets.video} poster={cur.assets.poster} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
              <a className="text-dawn-600 underline" href={`/api/library/assets/${cur.assets.video}/content?download=true`}>Download MP4</a>
              <a className="text-dawn-600 underline" href={`/api/library/assets/${cur.assets.srt}/content?download=true`}>Download SRT</a>
              {cur.provenance_id && <Badge tone="good">provenance signed</Badge>}
              {cur.needs_rerender && <Badge tone="warn">revised — re-render needed</Badge>}
            </div>
          </Card>
          <div className="space-y-5">
            <Card title="Delivery specs (ffprobe)" testId="probe">
              <KV rows={[
                ["Container / codec", `MP4 · ${cur.probe.video.codec} / ${cur.probe.audio.codec}`],
                ["Resolution", `${cur.probe.video.width}×${cur.probe.video.height} @ ${cur.probe.video.fps} fps`],
                ["Duration", `${cur.probe.duration.toFixed(2)} s`],
                ["Loudness", `${cur.loudness.integrated_lufs} LUFS · TP ${cur.loudness.true_peak_dbfs} dBFS`],
                ["Size", `${(cur.probe.size_bytes / 1048576).toFixed(2)} MB`],
                ["Music", cur.music?.title ?? "—"],
              ]} />
            </Card>
            <Card title="Versions" subtitle="Click to preview">
              <ul className="space-y-1.5 text-[13px]">
                {spots.map((s) => (
                  <li key={s.id}>
                    <button onClick={() => setSel(s.id)} className={`w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-cream-100 ${cur.id === s.id ? "bg-cream-200 font-medium" : ""}`}>
                      v{s.version} · {s.aspect} · {s.duration}s <Badge>{s.lineage_kind ?? "master"}</Badge> {s.lang !== "en" && <Badge tone="dark">{s.lang}</Badge>}
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-08", workspaceTabs: [{ id: "video", label: "Video", order: 60, Component: VideoTab }] };
