/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, ImagePlus, Lock } from "lucide-react";
import { api } from "../../api";
import type { FeatureDef, WorkspaceTabProps } from "../../registry";
import { Badge, Button, Card, Empty, Field, Select, Skeleton } from "../../components/ui";
import { GuardianBadge, Img, Tag, useJobStarter } from "../../components/common";
import { msg, useI18n } from "../../i18n";

function StoryboardTab({ campaign, reload }: WorkspaceTabProps) {
  const { t, tEnum, tOpen, fmt } = useI18n();
  const id = campaign.campaign.id;
  const q = useQuery({ queryKey: ["storyboard", id], queryFn: () => api.get(`/api/campaigns/${id}/storyboard`) });
  const [quality, setQuality] = useState("low");
  const [model, setModel] = useState("image");
  const [anchor, setAnchor] = useState(false);
  const job = useJobStarter(() => {
    q.refetch();
    reload();
  });
  const sb = q.data?.latest;
  const ready = sb?.shots.filter((s: any) => s.image_status === "ready").length ?? 0;
  const premium = quality === "high";
  return (
    <div className="space-y-5">
      <Card title={t("Art Director")} subtitle={t("Shot list + style bible, then keyframes from gpt-image (low quality by default; hero quality needs a premium approval).")}>
        <div className="flex flex-wrap items-end gap-4">
          <Button variant="outline" icon={<Clapperboard className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/storyboard/generate`, {})}>
            {sb ? t("Rebuild shot list") : t("Build shot list")}
          </Button>
          {sb && (
            <>
              <Field label={t("Quality")}>
                <Select value={quality} onChange={(e) => setQuality(e.target.value)} className="w-56" aria-label={t("image quality")}>
                  <option value="low">{t("low (draft)")}</option>
                  <option value="medium">{t("medium")}</option>
                  <option value="high">{t("high (premium — needs approval)")}</option>
                </Select>
              </Field>
              <Field label={t("Image model")}>
                <Select value={model} onChange={(e) => setModel(e.target.value)} className="w-48">
                  <option value="image">gpt-image-1.5</option>
                  <option value="image_draft">gpt-image-1-mini</option>
                </Select>
              </Field>
              <label className="flex items-center gap-2 pb-2 text-[13px]">
                <input type="checkbox" checked={anchor} onChange={(e) => setAnchor(e.target.checked)} /> {t("reference-anchor consistency")}
              </label>
              <Button variant="accent" icon={premium ? <Lock className="h-4 w-4" /> : <ImagePlus className="h-4 w-4" />} loading={job.busy} onClick={() => job.start(`/api/campaigns/${id}/storyboard/${sb.id}/frames`, { quality, model, anchor })}>
                {t("Generate keyframes")}
              </Button>
            </>
          )}
        </div>
        {job.node && <div className="mt-3">{job.node}</div>}
      </Card>
      {q.isLoading && <Skeleton h={240} />}
      {!q.isLoading && !sb && <Empty title={t("No storyboard yet")} hint={t("Write a script first, then build the shot list.")} />}
      {sb && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-[19px] font-semibold">{sb.title}</h3>
            <Badge tone={ready === sb.shots.length ? "good" : "warn"}>{t("{ready}/{total} keyframes", { ready, total: sb.shots.length })}</Badge>
            <GuardianBadge g={sb.guardian} />
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" data-testid="shots">
            {sb.shots.map((s: any) => (
              <Card key={s.id} pad={false}>
                <Img id={s.asset_id} alt={s.description} className="aspect-[3/2] w-full rounded-t-2xl" />
                <div className="space-y-1.5 p-3.5 text-[12.5px]">
                  <div className="flex items-center justify-between gap-2">
                    <Badge tone="dark">
                      #{s.idx} {tOpen("beatRole", s.role)}
                    </Badge>
                    <span className="tabular-nums text-espresso-500">
                      {t("{n}s", { n: s.duration })} · {tOpen("movement", s.movement)}
                    </span>
                  </div>
                  <div className="text-espresso-700">{s.description}</div>
                  {s.super_text && <div className="font-display text-[14px] italic">{t("“{text}”", { text: s.super_text })}</div>}
                  <div className="flex flex-wrap items-center gap-1.5 text-espresso-400">
                    <Tag>{s.framing}</Tag>
                    {s.image_status === "failed" && <Badge tone="bad">{tEnum("status", "failed")}</Badge>}
                    {s.cost_usd != null && <span>{fmt.usd(s.cost_usd, 3)}</span>}
                  </div>
                </div>
              </Card>
            ))}
          </div>
          <Card title={t("Style bible")} subtitle={t("Identical in every frame prompt — consistency by construction")} pad>
            <dl className="grid gap-x-6 gap-y-1.5 text-[13px] md:grid-cols-2">
              {Object.entries(sb.style_bible).map(([k, v]: any) => (
                <div key={k}>
                  <dt className="text-[11px] uppercase tracking-wider text-espresso-500">{tEnum("styleKey", k)}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}

export const feature: FeatureDef = { id: "CS-07", workspaceTabs: [{ id: "storyboard", label: msg("Storyboard"), order: 40, Component: StoryboardTab }] };
