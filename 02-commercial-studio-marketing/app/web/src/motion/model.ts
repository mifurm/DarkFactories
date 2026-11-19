/**
 * Cinematic motion (generative image→video) — wire types and pure helpers. No DOM, no React: unit-testable in node.
 *
 * The shapes mirror the backend contract (GET /api/motion/status, GET …/spot/estimate, the spot artifact's `quality` / `render.motion`, the storyboard
 * shot's `motion`). Every normalizer tolerates absent or malformed fields so an older backend (or an artifact rendered before motion existed) still renders.
 */
import { nbspOneLetterWords } from "../i18n/core";
import type { Formatter } from "../i18n/format";

export type MotionMode = "azure" | "local" | "stub" | "off";
export type WorkerState = "cold" | "warming" | "ready";
export type RenderQuality = "preview" | "cinematic";

export interface MotionStatus {
  mode: MotionMode;
  available: boolean;
  /** why it is not available: "off" (not configured) or "unreachable" (configured, but the queue / storage does not answer); null when available */
  reason: string | null;
  model: string;
  license: string;
  worker: { state: WorkerState; age_s: number | null; queue_depth: number };
  price_per_gpu_second: number | null;
  est_cold_start_s: number;
  max_clip_s: number | null;
}

export interface EstimateShot {
  shot_id: string;
  seconds: number;
  frames: number;
  cached: boolean;
  est_gpu_seconds: number;
  est_cost_usd: number;
}

export interface EstimateBudget {
  allowed: boolean;
  daily_remaining_usd: number | null;
  campaign_remaining_usd: number | null;
  /** a sentence (already in the request language) or a machine code such as `daily_budget_exceeded` */
  reason: string | null;
}

export interface SpotEstimate {
  quality: RenderQuality;
  aspect: string;
  shots: EstimateShot[];
  cached_shots: number;
  /** billed GPU seconds: the clips still to generate plus the cold start of a sleeping worker */
  est_gpu_seconds: number;
  /** the clips still to generate plus the cold start (`cold_start_cost_usd`) */
  est_cost_usd: number;
  /** cold start included */
  est_wall_seconds: number;
  cold_start_seconds: number;
  /** part of `est_cost_usd` that is not in a shot row: waking the GPU worker */
  cold_start_cost_usd: number;
  budget: EstimateBudget;
}

/**
 * The motion-quality gate's verdict on a clip. `rich`: real subject or camera motion that a camera move on a still cannot produce; `subtle`: some real motion (steam, light);
 * `low`: close to a still with camera moves (the generator returned an almost static clip, even after one retry); `unknown`: not measured.
 */
export type MotionLevel = "rich" | "subtle" | "low" | "unknown";

/** `render.motion.shots[i].motion` — the gate's measurements of one clip; shots without a clip, and renders from before the gate, have none. */
export interface ShotMotionQuality {
  shot_id: string;
  /** "s3" → 3: the number the UI calls the shot by */
  number: number;
  level: MotionLevel;
  /** px of motion per 0.4 s that no camera move can produce (a still with camera moves measures ≈ STILL_NON_RIGID_PX); null when not measured */
  non_rigid: number | null;
  total: number | null;
  /** 2: the first clip was almost static, so the shot was generated again with another seed */
  attempts: number;
}

/** What a still with camera moves measures on the gate's scale: the reference shown next to a clip's own figure. */
export const STILL_NON_RIGID_PX = 0.15;

export interface SpotMotionSummary {
  mode: string;
  model: string;
  license: string;
  shots_total: number;
  /** shots that carry AI motion in the final video — freshly generated or reused from the cache (`shots_cached` of them) */
  shots_generated: number;
  shots_cached: number;
  shots_fallback: { shot_id: string; reason: string; reason_text: string }[];
  gpu_seconds: number;
  /** includes the cold start (`cold_start_usd`) */
  cost_usd: number;
  cold_start_usd: number;
  /** the quality gate's verdict per shot that has one; empty for renders from before the gate */
  shot_quality: ShotMotionQuality[];
  /** clips that stay close to a still even after the retry (level `low`) */
  shots_low_motion: number;
  /** clips generated a second time with another seed */
  retries: number;
}

export interface SpotMotionInfo {
  quality: RenderQuality | null;
  motion: SpotMotionSummary | null;
}

export interface ShotMotion {
  prompt_en: string;
  prompt: string;
  camera: string;
}

export const MOTION_MAX_PROMPT = 300;

const MODES: readonly MotionMode[] = ["azure", "local", "stub", "off"];
const WORKER_STATES: readonly WorkerState[] = ["cold", "warming", "ready"];
const LEVELS: readonly MotionLevel[] = ["rich", "subtle", "low", "unknown"];

type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec | null => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : null);
const num = (v: unknown, fallback = 0): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);

export function normalizeMotionStatus(raw: unknown): MotionStatus | null {
  const r = rec(raw);
  if (!r || (typeof r.mode !== "string" && typeof r.available !== "boolean")) return null; // not a status payload (an error body, the SPA's HTML …)
  const w = rec(r.worker) ?? {};
  const mode = MODES.find((m) => m === r.mode) ?? "off";
  return {
    mode,
    available: r.available === true && mode !== "off",
    reason: typeof r.reason === "string" && r.reason ? r.reason : null,
    model: str(r.model),
    license: str(r.license),
    worker: {
      state: WORKER_STATES.find((s) => s === w.state) ?? "cold",
      age_s: numOrNull(w.age_s),
      queue_depth: Math.max(0, Math.round(num(w.queue_depth))),
    },
    price_per_gpu_second: numOrNull(r.price_per_gpu_second),
    est_cold_start_s: Math.max(0, num(r.est_cold_start_s)),
    max_clip_s: numOrNull(r.max_clip_s),
  };
}

export function normalizeEstimate(raw: unknown): SpotEstimate | null {
  const r = rec(raw);
  if (!r) return null;
  const shots: EstimateShot[] = (Array.isArray(r.shots) ? r.shots : []).flatMap((s) => {
    const o = rec(s);
    return o
      ? [{ shot_id: str(o.shot_id), seconds: num(o.seconds), frames: num(o.frames), cached: o.cached === true, est_gpu_seconds: num(o.est_gpu_seconds), est_cost_usd: num(o.est_cost_usd) }]
      : [];
  });
  const b = rec(r.budget) ?? {};
  const rowsCost = shots.reduce((a, s) => a + s.est_cost_usd, 0);
  const total = num(r.est_cost_usd, rowsCost);
  // the total also carries the GPU cold start, which is in no shot row: use the server's figure, or what is left of the total after the rows
  const coldCost = Math.max(0, num(r.cold_start_cost_usd, total - rowsCost));
  return {
    quality: r.quality === "preview" ? "preview" : "cinematic",
    aspect: str(r.aspect),
    shots,
    cached_shots: num(r.cached_shots, shots.filter((s) => s.cached).length),
    est_gpu_seconds: num(r.est_gpu_seconds, shots.reduce((a, s) => a + s.est_gpu_seconds, 0)),
    est_cost_usd: total,
    est_wall_seconds: num(r.est_wall_seconds),
    cold_start_seconds: Math.max(0, num(r.cold_start_seconds)),
    cold_start_cost_usd: coldCost < 0.0005 ? 0 : coldCost,
    budget: {
      allowed: b.allowed !== false, // absent = no objection
      daily_remaining_usd: numOrNull(b.daily_remaining_usd),
      campaign_remaining_usd: numOrNull(b.campaign_remaining_usd),
      reason: typeof b.reason === "string" && b.reason.trim() ? b.reason : null,
    },
  };
}

/** Cinematic is the default whenever the server can do it; an unavailable server can only render the preview, whatever was chosen before. */
export function effectiveQuality(choice: RenderQuality | null, status: MotionStatus | null | undefined): RenderQuality {
  if (!status?.available) return "preview";
  return choice ?? "cinematic";
}

export type WorkerView = { kind: "unavailable" } | { kind: "simulator" } | { kind: "gpu"; state: WorkerState; queueDepth: number };

/** What the status row shows: a real GPU worker (azure / local transport), the offline procedural animator (stub), or nothing usable. */
export function workerView(status: MotionStatus | null | undefined): WorkerView {
  if (!status?.available) return { kind: "unavailable" };
  if (status.mode === "stub") return { kind: "simulator" };
  return { kind: "gpu", state: status.worker.state, queueDepth: status.worker.queue_depth };
}

/** The warm-up button only makes sense for a cold GPU worker. */
export const canWarmUp = (view: WorkerView): boolean => view.kind === "gpu" && view.state === "cold";

/** Status polling runs every 10 s while the step is open; it stops for a server without motion (no endpoint / switched off). */
export const MOTION_POLL_MS = 10_000;
export function statusRefetchInterval(data: MotionStatus | undefined, errorStatus?: number): number | false {
  if (errorStatus === 404) return false;
  if (data?.mode === "off") return false;
  return MOTION_POLL_MS;
}

export const wallMinutes = (e: Pick<SpotEstimate, "est_wall_seconds">): number => Math.max(1, Math.round(e.est_wall_seconds / 60));
export const coldStartMinutes = (e: SpotEstimate | null | undefined, s: MotionStatus | null | undefined): number => {
  const seconds = e && e.cold_start_seconds > 0 ? e.cold_start_seconds : (s?.est_cold_start_s ?? 0);
  return Math.max(1, Math.round(seconds / 60));
};

/** "s3" → 3; ids without a number fall back to the row position. */
export function shotNumber(shotId: string, index: number): number {
  const m = /(\d+)$/.exec(shotId);
  return m ? Number(m[1]) : index + 1;
}

export type BudgetReason = { kind: "daily" } | { kind: "campaign" } | { kind: "text"; text: string } | { kind: "none" };
/** `reason` is a sentence in the request language or a machine code; a code is mapped to UI wording, a sentence is shown as received. */
export function budgetReason(reason: string | null | undefined): BudgetReason {
  const r = (reason ?? "").trim();
  if (!r) return { kind: "none" };
  if (/^[a-z][a-z0-9_.]*$/.test(r)) return /campaign/.test(r) ? { kind: "campaign" } : /daily|day/.test(r) ? { kind: "daily" } : { kind: "none" };
  return { kind: "text", text: r };
}

/** Newest artifact of a kind from the campaign payload (`artifacts` is sorted newest first). */
export function latestArtifactId(campaign: unknown, kind: string): string | null {
  const list = rec(campaign)?.artifacts;
  if (!Array.isArray(list)) return null;
  const hit = list.find((a) => rec(a)?.kind === kind);
  const id = rec(hit)?.id;
  return typeof id === "string" ? id : null;
}

/** The gate's verdict per shot, in storyboard order. A shot without a `motion` object (no clip, an older backend) has none; a level the UI does not know reads as `unknown`. */
function normalizeShotQuality(raw: unknown): ShotMotionQuality[] {
  return (Array.isArray(raw) ? raw : []).flatMap((entry, i) => {
    const o = rec(entry);
    const q = rec(o?.motion);
    if (!o || !q) return [];
    const shotId = str(o.shot_id);
    return [
      {
        shot_id: shotId,
        number: shotNumber(shotId, i),
        level: LEVELS.find((l) => l === q.level) ?? "unknown",
        non_rigid: numOrNull(q.non_rigid),
        total: numOrNull(q.total),
        attempts: Math.max(1, Math.round(num(q.attempts, 1))),
      },
    ];
  });
}

/** "2", "2 and 4", "1, 2 and 3" — in Polish "2 i 4", with the one-letter conjunction kept on the line of the number after it. */
export function shotList(numbers: readonly number[], locale: string): string {
  const text = new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(numbers.map(String));
  return locale.startsWith("pl") ? nbspOneLetterWords(text) : text;
}

function normalizeSummary(raw: unknown): SpotMotionSummary | null {
  const r = rec(raw);
  if (!r) return null;
  const fallback = (Array.isArray(r.shots_fallback) ? r.shots_fallback : []).map((f) => {
    const o = rec(f);
    return { shot_id: o ? str(o.shot_id) : str(f), reason: o ? str(o.reason) : "", reason_text: o ? str(o.reason_text) : "" };
  });
  const generated = num(r.shots_generated);
  const cached = num(r.shots_cached);
  const shotQuality = normalizeShotQuality(r.shots);
  return {
    mode: str(r.mode),
    model: str(r.model),
    license: str(r.license),
    shots_total: Math.max(0, Math.round(num(r.shots_total, generated + fallback.length))),
    shots_generated: generated,
    shots_cached: cached,
    shots_fallback: fallback,
    gpu_seconds: num(r.gpu_seconds),
    cost_usd: num(r.cost_usd),
    cold_start_usd: Math.max(0, num(r.cold_start_usd)),
    shot_quality: shotQuality,
    shots_low_motion: Math.max(0, Math.round(num(r.shots_low_motion, shotQuality.filter((s) => s.level === "low").length))),
    retries: Math.max(0, Math.round(num(r.retries, shotQuality.filter((s) => s.attempts > 1).length))),
  };
}

/** Clips generated by this very render: `shots_generated` also counts the ones reused from the cache. */
export const newClips = (m: Pick<SpotMotionSummary, "shots_generated" | "shots_cached">): number => Math.max(0, m.shots_generated - m.shots_cached);

export interface WarmupResult {
  /** the worker status the endpoint answers with (so the badge can change at once) */
  status: MotionStatus | null;
  /** false: the GPU was already warming or ready and nothing was queued; null: the backend did not say */
  requested: boolean | null;
  est_cost_usd: number | null;
  est_seconds: number | null;
}

/** POST /api/motion/warmup answers with the status plus `warmup: {requested, est_cost_usd, est_seconds}`. */
export function normalizeWarmup(raw: unknown): WarmupResult {
  const w = rec(rec(raw)?.warmup);
  return { status: normalizeMotionStatus(raw), requested: typeof w?.requested === "boolean" ? w.requested : null, est_cost_usd: numOrNull(w?.est_cost_usd), est_seconds: numOrNull(w?.est_seconds) };
}

/** `quality` and `render.motion` of a spot (list item or full artifact); old artifacts have neither. */
export function readSpotMotion(spot: unknown): SpotMotionInfo {
  const s = rec(spot);
  if (!s) return { quality: null, motion: null };
  const motion = normalizeSummary(rec(s.render)?.motion ?? s.motion);
  const declared = s.quality ?? rec(s.spec)?.quality;
  const quality: RenderQuality | null = declared === "cinematic" || declared === "preview" ? declared : motion ? "cinematic" : null;
  return { quality, motion };
}

/** The spot list may carry only part of the artifact; ask for the artifact itself when the motion summary (or the quality) is not in it. */
export function needsSpotDetail(spot: unknown): boolean {
  const s = rec(spot);
  if (!s) return false;
  const { quality, motion } = readSpotMotion(s);
  return !motion && quality !== "preview";
}

/** Motion prompt of a storyboard shot; storyboards written before motion existed have none. */
export function readShotMotion(shot: unknown): ShotMotion | null {
  const m = rec(rec(shot)?.motion);
  if (!m) return null;
  const prompt = str(m.prompt) || str(m.prompt_en);
  return { prompt, prompt_en: str(m.prompt_en) || prompt, camera: str(m.camera) };
}

export interface RenderFailureInfo {
  message: string;
  hint?: string | null;
  code?: string | null;
}
export const isBudgetFailure = (f: Pick<RenderFailureInfo, "code">): boolean => /budget/i.test(f.code ?? "") || f.code === "premium_requires_approval";

/** A small AI cost keeps its third decimal ($0.094) so it never rounds to a misleading $0.09 or $0.10; from $0.10 up whole cents are enough ($0.38). */
export const usdLabel = (fmt: Pick<Formatter, "usd">, value: number | null): string => fmt.usd(value, value !== null && Math.abs(value) < 0.1 ? { min: 2, max: 3 } : 2);
