import { Sparkles } from "lucide-react";
import { Badge } from "../components/ui";
import { useI18n } from "../i18n";
import { STILL_NON_RIGID_PX, newClips, shotList, shotNumber, usdLabel, type ShotMotionQuality, type SpotMotionInfo } from "./model";

const LEVEL_TONE = { rich: "good", subtle: "info", low: "warn" } as const;

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

/** Model / licence / hosting line, what was generated vs reused, GPU time and cost, how much real motion each clip has, and the shots that fell back to the still. */
export function SpotMotionDetails({ info }: { info: SpotMotionInfo }) {
  const { t, tEnum, tOpen, fmt } = useI18n();
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
  // the quality gate: a level badge per clip that was measured (or retried); the figures stay in its tooltip, against what a still with camera moves measures
  const graded = m.shot_quality.filter((q) => q.level !== "unknown" || q.attempts > 1);
  const measured = (q: ShotMotionQuality) =>
    q.non_rigid === null ? undefined : t("Non-rigid motion: {value} px per 0.4 s (a still with camera moves: ≈ {still})", { value: fmt.fixed(q.non_rigid, 2), still: fmt.fixed(STILL_NON_RIGID_PX, 2) });
  const low = m.shots_low_motion > 0 ? m.shot_quality.filter((q) => q.level === "low") : [];
  const lowList = shotList(low.map((q) => q.number), fmt.locale);
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
      {graded.length > 0 && (
        <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 py-0.5" data-testid="motion-levels">
          {graded.map((q, i) => (
            <li key={q.shot_id || i} className="inline-flex items-center gap-1.5" data-testid="motion-level" data-shot={q.number} data-level={q.level} data-attempts={q.attempts}>
              <span>{t("Shot {n}", { n: q.number })}</span>
              {q.level !== "unknown" && (
                <>
                  {" "}
                  <span title={measured(q)}>
                    <Badge tone={LEVEL_TONE[q.level]}>{tEnum("motionLevel", q.level)}</Badge>
                  </span>
                </>
              )}
              {q.attempts > 1 && (
                <>
                  {" "}
                  <span className="text-espresso-400" data-testid="motion-retried">
                    ({t("retried with another seed")})
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {low.length > 0 && (
        <p className="text-dawn-700" data-testid="motion-low-hint">
          {low.length === 1
            ? t("Shot {list} has little motion. Edit its motion prompt (Storyboard tab) and render again — only that shot is regenerated.", { list: lowList })
            : t("Shots {list} have little motion. Edit their motion prompts (Storyboard tab) and render again — only those shots are regenerated.", { list: lowList })}
        </p>
      )}
      {fallbackList && (
        <p className="text-dawn-700" data-testid="motion-fallbacks">
          {t("Fell back to camera moves on the keyframe: {list}", { list: fallbackList })}
        </p>
      )}
    </div>
  );
}
