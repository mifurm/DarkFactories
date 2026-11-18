import { useId } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Cpu, Flame, Info, Loader2, Snowflake } from "lucide-react";
import { Badge, Button, KV, Skeleton, cn } from "../components/ui";
import { useI18n } from "../i18n";
import { budgetReason, canWarmUp, coldStartMinutes, shotNumber, usdLabel, wallMinutes, workerView, type MotionStatus, type RenderQuality, type SpotEstimate, type WorkerView } from "./model";
import type { EstimateState, StatusState } from "./queries";

export interface RenderQualityPickerProps {
  status: MotionStatus | null;
  statusState: StatusState;
  quality: RenderQuality;
  onQuality: (quality: RenderQuality) => void;
  estimate: SpotEstimate | null;
  estimateState: EstimateState;
  /** message of a failed estimate request, when the server sent one */
  estimateError?: string | null;
  onWarmUp: () => void;
  warmUpBusy?: boolean;
}

function QualityOption(p: { name: string; value: RenderQuality; checked: boolean; disabled?: boolean; onSelect: (v: RenderQuality) => void; title: string; description: string; describedBy?: string }) {
  return (
    <label
      className={cn(
        "flex items-start gap-3 rounded-xl border px-3.5 py-3 text-[13px] transition-colors",
        p.checked ? "border-dawn-500 bg-white shadow-sm" : "border-cream-300 bg-cream-50",
        p.disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-white",
      )}
    >
      <input type="radio" name={p.name} value={p.value} checked={p.checked} disabled={p.disabled} onChange={() => p.onSelect(p.value)} aria-describedby={p.describedBy} data-testid={`quality-${p.value}`} className="mt-0.5 h-4 w-4 shrink-0 accent-dawn-500" />
      <span className="min-w-0">
        <span className="block font-semibold text-espresso-900">{p.title}</span> <span className="block text-espresso-500">{p.description}</span>
      </span>
    </label>
  );
}

/**
 * GPU worker state as a status region (role="status" is a polite live region: it changes cold → warming → ready on its own while the step is open) + the
 * warm-up action. No explicit aria-live attribute and no labelled <Spinner>: the E2E settle check reads `[aria-live=polite]` as the toast area and
 * `[aria-label=loading]` as a pending request, so a long GPU warm-up must not look like either.
 */
export function WorkerStatus({ view, onWarmUp, busy }: { view: WorkerView; onWarmUp: () => void; busy?: boolean }) {
  const { t, tn } = useI18n();
  if (view.kind === "unavailable") return null;
  if (view.kind === "simulator")
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]" data-testid="gpu-status">
        <span role="status">
          <Badge tone="info">
            <Cpu className="h-3 w-3" aria-hidden="true" />
            {t("Offline motion simulator")}
          </Badge>
        </span>
      </div>
    );
  const badge =
    view.state === "ready" ? (
      <Badge tone="good">
        <Cpu className="h-3 w-3" aria-hidden="true" />
        {t("GPU worker: ready")}
      </Badge>
    ) : view.state === "warming" ? (
      <Badge tone="warn">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        {t("GPU worker: warming up…")}
      </Badge>
    ) : (
      <Badge tone="neutral">
        <Snowflake className="h-3 w-3" aria-hidden="true" />
        {t("GPU worker: cold")}
      </Badge>
    );
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]" data-testid="gpu-status" data-worker-state={view.state}>
      <span role="status">{badge}</span>
      {view.queueDepth > 0 && <span className="text-espresso-500">{tn(view.queueDepth, { one: "{n} job in the GPU queue", other: "{n} jobs in the GPU queue" })}</span>}
      <Button size="sm" variant="outline" icon={<Flame className="h-3.5 w-3.5" />} loading={busy} disabled={!canWarmUp(view)} onClick={onWarmUp} data-testid="warm-gpu">
        {t("Warm up GPU")}
      </Button>
    </div>
  );
}

export function EstimatePanel({ estimate, state, error, status }: { estimate: SpotEstimate | null; state: EstimateState; error?: string | null; status: MotionStatus | null }) {
  const { t, tx, tKnown, fmt } = useI18n();
  const headingId = useId();
  if (state === "loading" && !estimate)
    return (
      <div className="mt-3" aria-busy="true" data-testid="motion-estimate-loading">
        <Skeleton h={120} />
      </div>
    );
  if (!estimate)
    return (
      <p role="status" className="mt-3 text-[12.5px] text-espresso-500" data-testid="motion-estimate-error">
        {error ? t("Estimate unavailable: {reason}", { reason: error }) : t("The estimate is not available right now — you can still render.")}
      </p>
    );
  const cost = (v: number | null) => fmt.usd(v, 3); // the app shows AI costs to the tenth of a cent (cost meter, keyframe cards)
  const left = (v: number | null) => fmt.usd(v, 2);
  const view = workerView(status);
  const reason = budgetReason(estimate.budget.reason);
  const reasonText =
    reason.kind === "daily"
      ? t("The daily AI budget would be exceeded.")
      : reason.kind === "campaign"
        ? t("The AI budget of this campaign would be exceeded.")
        : reason.kind === "text"
          ? tKnown(reason.text)
          : t("The daily or per-campaign AI cap would be exceeded.");
  const totalSeconds = estimate.shots.reduce((a, s) => a + s.seconds, 0);
  return (
    <section aria-labelledby={headingId} data-testid="motion-estimate" className="mt-3 space-y-3 rounded-xl border border-cream-300 bg-cream-50 p-4">
      <div>
        <h4 id={headingId} className="font-display text-[15px] font-semibold text-espresso-800">
          {t("Cinematic estimate")}
        </h4>
        <p className="mt-0.5 text-[12.5px] text-espresso-500">{t("One AI clip per shot, generated one at a time on a single GPU. Clips already generated for the same keyframe and motion prompt are reused at no cost.")}</p>
      </div>
      {estimate.shots.length > 0 && (
        <div className="scroll-thin max-w-3xl overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <caption className="sr-only">{t("Estimate per shot")}</caption>
            <thead>
              <tr className="border-b border-cream-300 text-[11.5px] uppercase tracking-wider text-espresso-500">
                <th scope="col" className="px-3 py-2 font-semibold">
                  {t("Shot")}
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  {t("Length")}
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  {t("Status")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  {t("Est. cost")}
                </th>
              </tr>
            </thead>
            <tbody>
              {estimate.shots.map((s, i) => (
                <tr key={s.shot_id || i} className="border-b border-cream-200" data-testid="estimate-shot" data-cached={s.cached ? "true" : "false"}>
                  <th scope="row" className="px-3 py-2 font-medium text-espresso-800">
                    {t("Shot {n}", { n: shotNumber(s.shot_id, i) })}
                  </th>
                  <td className="px-3 py-2 tabular-nums">{t("{n} s", { n: fmt.fixed(s.seconds, 1) })}</td>
                  <td className="px-3 py-2">{s.cached ? <Badge tone="good">{t("cached")}</Badge> : <Badge tone="warn">{t("to generate")}</Badge>}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{cost(s.est_cost_usd)}</td>
                </tr>
              ))}
              {estimate.cold_start_cost_usd > 0 && (
                <tr className="border-b border-cream-200" data-testid="estimate-cold-start">
                  <th scope="row" className="px-3 py-2 font-medium text-espresso-800">
                    {t("GPU cold start (~{minutes} min)", { minutes: coldStartMinutes(estimate, status) })}
                  </th>
                  <td className="px-3 py-2 text-espresso-400">—</td>
                  <td className="px-3 py-2 text-espresso-400">—</td>
                  <td className="px-3 py-2 text-right tabular-nums">{cost(estimate.cold_start_cost_usd)}</td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr className="font-semibold text-espresso-900">
                <th scope="row" className="px-3 py-2">
                  {t("Total")}
                </th>
                <td className="px-3 py-2 tabular-nums">{t("{n} s", { n: fmt.fixed(totalSeconds, 1) })}</td>
                <td className="px-3 py-2">{t("cached: {cached}/{total}", { cached: estimate.cached_shots, total: estimate.shots.length })}</td>
                <td className="px-3 py-2 text-right tabular-nums" data-testid="estimate-total">
                  {cost(estimate.est_cost_usd)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <KV
        rows={[
          [t("GPU time"), t("{n} s", { n: fmt.number(estimate.est_gpu_seconds, 0) })],
          [t("Estimated render time"), t("~{minutes} min", { minutes: wallMinutes(estimate) })],
          [t("Budget left today"), left(estimate.budget.daily_remaining_usd)],
          [t("Budget left for this campaign"), left(estimate.budget.campaign_remaining_usd)],
        ]}
      />
      {view.kind === "gpu" && view.state !== "ready" && (
        <p className="flex items-start gap-2 text-[12.5px] text-espresso-600" data-testid="cold-start-note">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-700" aria-hidden="true" />
          {view.state === "warming"
            ? t("The GPU worker is warming up — rendering starts as soon as it is ready.")
            : t("The GPU worker is cold: the first shot also waits for the GPU to start (about {minutes} min). Warm it up now to skip that wait.", { minutes: coldStartMinutes(estimate, status) })}
        </p>
      )}
      {!estimate.budget.allowed && (
        <div role="alert" data-testid="budget-refusal" className="rounded-xl border border-dawn-400/60 bg-dawn-300/10 px-3.5 py-2.5 text-[13px]">
          <div className="flex items-center gap-2 font-semibold text-dawn-700">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            {t("Not enough AI budget for a Cinematic render")}
          </div>
          <p className="mt-1 text-espresso-700">{reasonText}</p>
          <p className="mt-1 text-espresso-600">
            {tx("Choose Preview, or raise the cap on the <cost>cost meter</cost> (admin only).", {
              cost: (chunks) => (
                <Link className="text-dawn-600 underline" to="/cost">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </div>
      )}
    </section>
  );
}

/** Preview vs Cinematic (Cinematic by default when the server can render it), the GPU worker status + warm-up, and the estimate of a Cinematic render. */
export function RenderQualityPicker(p: RenderQualityPickerProps) {
  const { t, fmt } = useI18n();
  const name = useId();
  const reasonId = useId();
  const available = !!p.status?.available;
  const view = workerView(p.status);
  const cinematicText = p.estimate
    ? t("AI video, real motion (est. {cost} · ~{minutes} min)", { cost: usdLabel(fmt, p.estimate.est_cost_usd), minutes: wallMinutes(p.estimate) })
    : t("AI video, real motion");
  const unavailable = p.statusState !== "loading" && !available;
  return (
    <div data-testid="render-quality">
      <fieldset className="min-w-0">
        <legend className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-espresso-500">{t("Render quality")}</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <QualityOption name={name} value="preview" checked={p.quality === "preview"} onSelect={p.onQuality} title={t("Preview")} description={t("stills with camera moves (free, ~30 s)")} />
          <QualityOption
            name={name}
            value="cinematic"
            checked={p.quality === "cinematic"}
            disabled={!available}
            describedBy={unavailable ? reasonId : undefined}
            onSelect={p.onQuality}
            title={t("Cinematic")}
            description={cinematicText}
          />
        </div>
      </fieldset>
      {unavailable && (
        <p id={reasonId} className="mt-2 text-[12.5px] text-espresso-500" data-testid="cinematic-unavailable">
          {p.status?.reason === "unreachable"
            ? t("The motion service cannot be reached right now — only Preview can be rendered.")
            : t("AI motion is not available on this server — only Preview can be rendered.")}
        </p>
      )}
      <WorkerStatus view={view} onWarmUp={p.onWarmUp} busy={p.warmUpBusy} />
      {p.quality === "cinematic" && available && <EstimatePanel estimate={p.estimate} state={p.estimateState} error={p.estimateError} status={p.status} />}
    </div>
  );
}
