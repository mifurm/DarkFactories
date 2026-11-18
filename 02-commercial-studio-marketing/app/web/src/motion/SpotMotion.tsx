import { Sparkles } from "lucide-react";
import { Badge } from "../components/ui";
import { useI18n } from "../i18n";
import { newClips, shotNumber, usdLabel, type SpotMotionInfo } from "./model";

/** "Cinematic · AI motion 4/4 shots" (or "3/4 shots · 1 fallback"); an explicit Preview gets a neutral chip, artifacts from before motion existed none. */
export function SpotMotionChip({ info }: { info: SpotMotionInfo }) {
  const { t, tn } = useI18n();
  if (info.quality === "preview")
    return (
      <span data-testid="motion-chip" data-quality="preview">
        <Badge>{t("Preview")}</Badge>
      </span>
    );
  if (info.quality !== "cinematic") return null;
  const m = info.motion;
  if (!m || m.shots_total <= 0)
    return (
      <span data-testid="motion-chip" data-quality="cinematic">
        <Badge tone="dawn" className="gap-1">
          <Sparkles className="h-3 w-3" aria-hidden="true" />
          {t("Cinematic")}
        </Badge>
      </span>
    );
  const fallbacks = m.shots_fallback.length;
  const ai = Math.max(0, m.shots_total - fallbacks);
  const text = t("Cinematic · AI motion {ai}/{total} shots", { ai, total: m.shots_total }) + (fallbacks > 0 ? ` · ${tn(fallbacks, { one: "{n} fallback", other: "{n} fallbacks" })}` : "");
  return (
    <span data-testid="motion-chip" data-quality="cinematic" data-fallbacks={fallbacks}>
      <Badge tone={fallbacks > 0 ? "warn" : "dawn"} className="gap-1">
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        {text}
      </Badge>
    </span>
  );
}

/** Model / licence / hosting line, what was generated vs reused, GPU time and cost, and the shots that fell back to the still. */
export function SpotMotionDetails({ info }: { info: SpotMotionInfo }) {
  const { t, tOpen, fmt } = useI18n();
  const m = info.motion;
  if (info.quality !== "cinematic" || !m) return null;
  const hosting =
    m.mode === "azure" ? t("self-hosted on serverless GPU in your Azure environment") : m.mode === "local" ? t("local motion worker") : m.mode === "stub" ? t("offline motion simulator") : null;
  const used = m.gpu_seconds > 0 || m.cost_usd > 0;
  // the server words each reason in the viewer's language (`reason_text`); the dictionary covers payloads that only carry the code
  const fallbackList = m.shots_fallback
    .map((f, i) => {
      const why = f.reason_text || (f.reason ? tOpen("motionFallback", f.reason) : "");
      return `${t("Shot {n}", { n: shotNumber(f.shot_id, i) })}${why ? ` (${why})` : ""}`;
    })
    .join(", ");
  return (
    <div className="space-y-0.5 text-[12px] text-espresso-500" data-testid="motion-details">
      <p data-testid="motion-model-line">
        {t("Motion model: {model} · licence {license}", { model: m.model || "—", license: m.license || "—" })}
        {hosting ? ` · ${hosting}` : ""}
      </p>
      <p data-testid="motion-usage-line">
        {t("New clips: {fresh} · reused from cache: {cached}", { fresh: newClips(m), cached: m.shots_cached })}
        {" · "}
        {used ? t("GPU time: {n} s · {cost}", { n: fmt.number(m.gpu_seconds, 0), cost: usdLabel(fmt, m.cost_usd) }) : t("no GPU time used")}
        {m.cold_start_usd > 0 ? ` · ${t("incl. {cost} for the GPU cold start", { cost: usdLabel(fmt, m.cold_start_usd) })}` : ""}
      </p>
      {fallbackList && (
        <p className="text-dawn-700" data-testid="motion-fallbacks">
          {t("Fell back to camera moves on the keyframe: {list}", { list: fallbackList })}
        </p>
      )}
    </div>
  );
}
