/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, RefreshCw } from "lucide-react";
import { ApiError, api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, JobProgress, KV, Select, Skeleton } from "../../components/ui";
import { GuardianBadge, Video, mediaUrl, useJobStarter } from "../../components/common";
import { msg, useI18n } from "../../i18n";
import { latestArtifactId, readSpotMotion, type RenderFailureInfo } from "../../motion/model";
import { useRenderQuality, useSpotMotion } from "../../motion/queries";
import { RenderFailure } from "../../motion/RenderFailure";
import { RenderQualityPicker } from "../../motion/RenderQuality";
import { SpotMotionChip, SpotMotionDetails } from "../../motion/SpotMotion";

const RENDER_KINDS = ["spot.render", "spot.rerender"];

function VideoTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tEnum, tOpen, fmt } = useI18n();
  const qc = useQueryClient();
  const id = campaign.campaign.id;
  const q = useQuery({ queryKey: ["spots", id], queryFn: () => api.get(`/api/campaigns/${id}/spot`) });
  const [aspect, setAspect] = useState("16:9");
  const [lufs, setLufs] = useState(-16);
  const [sel, setSel] = useState<string | null>(null);
  const [failure, setFailure] = useState<RenderFailureInfo | null>(null);
  const [ended, setEnded] = useState<ReadonlySet<string>>(new Set()); // render jobs whose end this step has already handled
  const mq = useRenderQuality({ campaignId: id, aspect, storyboardId: latestArtifactId(campaign, "storyboard") });
  const onJobDone = (j: any) => {
    if (j?.id) setEnded((s) => new Set(s).add(j.id));
    q.refetch();
    reload();
    qc.invalidateQueries({ queryKey: ["spot-estimate", id] }); // the clips just generated are cache hits now
    setFailure(j?.status === "failed" ? { message: j.error || j.message || "", hint: j.error_hint, code: j.error_code } : null);
  };
  const job = useJobStarter(onJobDone);
  // a render started earlier (or in another window) keeps running on the server: show its live progress again when the step is reopened
  const running = job.busy ? null : (campaign.recent_jobs ?? []).find((j: any) => RENDER_KINDS.includes(j.kind) && (j.status === "running" || j.status === "queued") && !ended.has(j.id));
  const busy = job.busy || !!running;
  const startJob = async (path: string, body?: any) => {
    setFailure(null);
    try {
      await job.start(path, body);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      setFailure({ message: e.message, hint: e.hint, code: e.code }); // the toast fades; the refusal stays on the page
    }
  };
  const spots: any[] = q.data?.spots ?? [];
  const masters = spots.filter((s) => (s.lineage_kind ?? "master") === "master");
  const cur = spots.find((s) => s.id === sel) ?? masters[0];
  const motion = useSpotMotion(id, cur);
  const budgetBlocked = mq.quality === "cinematic" && mq.estimate?.budget.allowed === false;
  return (
    <div className="space-y-5">
      <Card
        title={t("Director · spot compositor")}
        subtitle={t(
          "Two render qualities: Preview moves the keyframes with Ken-Burns/parallax camera moves; Cinematic turns each keyframe into an AI-generated clip with real motion. Either way: dissolves, voice-over, burned-in captions + SRT, music bed, logo, AI-disclosure badge and brand end card — assembled by ffmpeg behind a pluggable VideoProvider.",
        )}
      >
        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("Aspect")}>
            <Select value={aspect} onChange={(e) => setAspect(e.target.value)} className="w-32" aria-label={t("aspect")}>
              {["16:9", "9:16", "1:1", "4:5"].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </Select>
          </Field>
          <Field label={t("Loudness target")}>
            <Select value={lufs} onChange={(e) => setLufs(+e.target.value)} className="w-60" aria-label={t("loudness")}>
              <option value={-16}>{t("−16 LUFS (digital / social)")}</option>
              <option value={-14}>{t("−14 LUFS (streaming)")}</option>
              <option value={-23}>{t("−23 LUFS (EBU R128 broadcast)")}</option>
            </Select>
          </Field>
        </div>
        <div className="mt-4">
          <RenderQualityPicker
            status={mq.status}
            statusState={mq.statusState}
            quality={mq.quality}
            onQuality={mq.choose}
            estimate={mq.estimate}
            estimateState={mq.estimateState}
            estimateError={mq.estimateError}
            onWarmUp={mq.warmUp}
            warmUpBusy={mq.warmUpBusy}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="accent" icon={<Film className="h-4 w-4" />} loading={busy} disabled={budgetBlocked} onClick={() => startJob(`/api/campaigns/${id}/spot/render`, { aspect, loudness_lufs: lufs, quality: mq.quality })}>
            {t("Render spot")}
          </Button>
          {cur?.needs_rerender && (
            <Button variant="outline" icon={<RefreshCw className="h-4 w-4" />} loading={busy} onClick={() => startJob(`/api/campaigns/${id}/spot/${cur.id}/rerender`)}>
              {t("Re-render with Guardian fixes")}
            </Button>
          )}
        </div>
        {failure && <RenderFailure failure={failure} onDismiss={() => setFailure(null)} />}
        {(job.node || running) && <div className="mt-3">{job.node ?? <JobProgress key={running.id} jobId={running.id} onDone={onJobDone} />}</div>}
        <div className="mt-2 text-[12px] text-espresso-400">{t("Provider: {kind} · {codec}", { kind: tOpen("providerKind", q.data?.provider?.kind ?? "compositor"), codec: q.data?.provider?.codec ?? "" })}</div>
      </Card>
      {q.isLoading && <Skeleton h={300} />}
      {!q.isLoading && !cur && <Empty title={t("No spot rendered yet")} hint={t("You need a script, storyboard keyframes and a voice-over first.")} />}
      {cur && (
        <div className="grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-2" title={cur.title} subtitle={t("{aspect} · {n}s", { aspect: cur.aspect, n: cur.duration })} actions={<GuardianBadge g={cur.guardian} />}>
            <div className={`mx-auto ${cur.aspect === "9:16" ? "max-w-[300px]" : cur.aspect === "1:1" || cur.aspect === "4:5" ? "max-w-[460px]" : ""}`}>
              <Video id={cur.assets.video} poster={cur.assets.poster} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
              <a className="text-dawn-600 underline" href={mediaUrl(cur.assets.video, true)}>
                {t("Download MP4")}
              </a>
              <a className="text-dawn-600 underline" href={mediaUrl(cur.assets.srt, true)}>
                {t("Download SRT")}
              </a>
              {cur.provenance_id && <Badge tone="good">{t("provenance signed")}</Badge>}
              {cur.needs_rerender && <Badge tone="warn">{t("revised — re-render needed")}</Badge>}
              <SpotMotionChip info={motion} />
            </div>
            <div className="mt-2">
              <SpotMotionDetails info={motion} />
            </div>
          </Card>
          <div className="space-y-5">
            <Card title={t("Delivery specs (ffprobe)")} testId="probe">
              <KV
                rows={[
                  [t("Container / codec"), `MP4 · ${cur.probe.video.codec} / ${cur.probe.audio.codec}`],
                  [t("Resolution"), t("{width}×{height} @ {fps} fps", { width: cur.probe.video.width, height: cur.probe.video.height, fps: fmt.number(cur.probe.video.fps, 2) })],
                  [t("Duration"), t("{n} s", { n: fmt.fixed(cur.probe.duration, 2) })],
                  [t("Loudness"), t("{lufs} LUFS · TP {tp} dBFS", { lufs: fmt.number(cur.loudness.integrated_lufs, 2), tp: fmt.number(cur.loudness.true_peak_dbfs, 2) })],
                  [t("Size"), t("{n} MB", { n: fmt.fixed(cur.probe.size_bytes / 1048576, 2) })],
                  [t("Music"), cur.music?.title ?? "—"],
                ]}
              />
            </Card>
            <Card title={t("Versions")} subtitle={t("Click to preview")}>
              <ul className="space-y-1.5 text-[13px]">
                {spots.map((s) => (
                  <li key={s.id}>
                    <button onClick={() => setSel(s.id)} className={`w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-cream-100 ${cur.id === s.id ? "bg-cream-200 font-medium" : ""}`}>
                      {t("v{version} · {aspect} · {n}s", { version: String(s.version), aspect: s.aspect, n: s.duration })} <Badge>{tEnum("lineage", s.lineage_kind ?? "master")}</Badge> {s.lang !== "en" && <Badge tone="dark">{s.lang}</Badge>}{" "}
                      {readSpotMotion(s).quality === "cinematic" && <Badge tone="dawn">{t("Cinematic")}</Badge>}
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

export const feature: FeatureDef = { id: "CS-08", workspaceTabs: [{ id: "video", label: msg("Video"), order: 60, Component: VideoTab }] };
