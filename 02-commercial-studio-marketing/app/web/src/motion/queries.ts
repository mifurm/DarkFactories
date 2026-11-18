import { queryOptions, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "../api";
import { useToast } from "../components/ui";
import { useI18n } from "../i18n";
import {
  coldStartMinutes,
  effectiveQuality,
  needsSpotDetail,
  normalizeEstimate,
  normalizeMotionStatus,
  normalizeWarmup,
  readSpotMotion,
  statusRefetchInterval,
  usdLabel,
  type MotionStatus,
  type RenderQuality,
  type SpotEstimate,
  type SpotMotionInfo,
  type WarmupResult,
} from "./model";

export const MOTION_STATUS_KEY = ["motion-status"] as const;

export async function fetchMotionStatus(): Promise<MotionStatus> {
  const status = normalizeMotionStatus(await api.get("/api/motion/status", { quiet: true }));
  if (!status) throw new Error("motion status: unexpected payload");
  return status;
}

/**
 * GET /api/motion/status, refetched every 10 s for as long as a component observes it — i.e. while the Video step is open (TanStack stops the timer on
 * unmount, and pauses it while the browser tab is hidden). Errors are quiet: an older backend without the endpoint simply means "no motion".
 */
export const motionStatusQuery = () =>
  queryOptions({
    queryKey: MOTION_STATUS_KEY,
    queryFn: fetchMotionStatus,
    staleTime: 5_000,
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: (query) => statusRefetchInterval(query.state.data, query.state.error instanceof ApiError ? query.state.error.status : undefined),
  });

/** User-initiated warm-up (errors — e.g. a 402 when the cold start does not fit the budget — surface as the usual toast). */
export async function warmUpMotion(): Promise<WarmupResult> {
  return normalizeWarmup(await api.post("/api/motion/warmup"));
}

/** Silent best-effort warm-up (after the storyboard frames): never throws, never toasts; skipped when the status already known says there is nothing to warm. */
export async function warmUpMotionQuietly(qc?: QueryClient): Promise<boolean> {
  const known = qc?.getQueryData<MotionStatus>(MOTION_STATUS_KEY);
  if (known && !known.available) return false;
  try {
    await api.post("/api/motion/warmup", {}, { quiet: true });
    return true;
  } catch {
    return false;
  }
}

export interface EstimateParams {
  quality: RenderQuality;
  aspect: string;
  storyboardId?: string | null;
}

export function estimatePath(campaignId: string, p: EstimateParams): string {
  const q = new URLSearchParams({ quality: p.quality, aspect: p.aspect });
  if (p.storyboardId) q.set("storyboard_id", p.storyboardId);
  return `/api/campaigns/${encodeURIComponent(campaignId)}/spot/estimate?${q}`;
}

export async function fetchSpotEstimate(campaignId: string, p: EstimateParams): Promise<SpotEstimate> {
  const estimate = normalizeEstimate(await api.get(estimatePath(campaignId, p), { quiet: true }));
  if (!estimate) throw new Error("spot estimate: unexpected payload");
  return estimate;
}

export function saveMotionPrompt(campaignId: string, storyboardId: string, shotId: string, motion: string) {
  return api.patch(`/api/campaigns/${encodeURIComponent(campaignId)}/storyboard/${encodeURIComponent(storyboardId)}/shots/${encodeURIComponent(shotId)}`, { motion });
}

export type StatusState = "loading" | "ready" | "error";
export type EstimateState = "idle" | "loading" | "ready" | "error";

/**
 * Everything the render-quality control needs: the polled worker status, the Preview/Cinematic choice (Cinematic by default when the server can do it),
 * the cinematic estimate (re-requested when the aspect, the storyboard or the worker state changes) and the warm-up action.
 */
export function useRenderQuality(opts: { campaignId: string; aspect: string; storyboardId: string | null }) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const [choice, setChoice] = useState<RenderQuality | null>(null);
  const statusQ = useQuery(motionStatusQuery());
  const status = statusQ.data ?? null;
  const estimateQ = useQuery({
    queryKey: ["spot-estimate", opts.campaignId, opts.aspect, opts.storyboardId, status?.worker.state ?? null],
    queryFn: () => fetchSpotEstimate(opts.campaignId, { quality: "cinematic", aspect: opts.aspect, storyboardId: opts.storyboardId }),
    enabled: !!status?.available,
    staleTime: 3_000,
    retry: false,
    // keep showing the current estimate while it is refreshed because the worker changed state, but never an estimate of another aspect / storyboard
    placeholderData: (previous, previousQuery) => (previousQuery && previousQuery.queryKey[2] === opts.aspect && previousQuery.queryKey[3] === opts.storyboardId ? previous : undefined),
  });
  const warm = useMutation({
    mutationFn: warmUpMotion,
    onSuccess: (res) => {
      if (res.status) qc.setQueryData(MOTION_STATUS_KEY, res.status); // the answer carries the new worker state: the badge changes at once
      qc.invalidateQueries({ queryKey: MOTION_STATUS_KEY });
      if (res.requested === false) {
        toast({ tone: "info", title: t("No warm-up needed"), body: t("The GPU worker is already warming up or ready.") });
        return;
      }
      const minutes = res.est_seconds ? Math.max(1, Math.round(res.est_seconds / 60)) : coldStartMinutes(estimateQ.data, status);
      toast({
        tone: "good",
        title: t("GPU warm-up requested"),
        body: res.est_cost_usd
          ? t("Starting from cold takes about {minutes} min ({cost} of GPU time) — the GPU status on this page updates by itself.", { minutes, cost: usdLabel(fmt, res.est_cost_usd) })
          : t("Starting from cold takes about {minutes} min — the GPU status on this page updates by itself.", { minutes }),
      });
    },
  });
  const estimate = estimateQ.data ?? null;
  const statusState: StatusState = statusQ.isPending ? "loading" : status ? "ready" : "error";
  const estimateState: EstimateState = !status?.available ? "idle" : estimate ? "ready" : estimateQ.isError ? "error" : "loading";
  return {
    quality: effectiveQuality(choice, status),
    choose: setChoice,
    status,
    statusState,
    estimate,
    estimateState,
    estimateError: estimateQ.error instanceof ApiError ? estimateQ.error.message : null,
    warmUp: () => warm.mutate(),
    warmUpBusy: warm.isPending,
  };
}

/**
 * Quality and motion summary of a spot. The spot list may not carry them (older payloads): then the artifact itself is requested once and cached.
 * Old artifacts (rendered before motion existed) simply come back without a summary.
 */
export function useSpotMotion(campaignId: string, spot: { id?: unknown } | null | undefined): SpotMotionInfo {
  const id = typeof spot?.id === "string" ? spot.id : null;
  const need = needsSpotDetail(spot);
  const detail = useQuery({
    queryKey: ["spot-detail", campaignId, id],
    queryFn: () => api.get(`/api/campaigns/${encodeURIComponent(campaignId)}/spot/${encodeURIComponent(id ?? "")}`, { quiet: true }),
    enabled: need && !!id,
    staleTime: 30_000,
    retry: false,
  });
  const base = readSpotMotion(spot);
  if (!detail.data) return base;
  const full = readSpotMotion(detail.data);
  return { quality: full.quality ?? base.quality, motion: full.motion ?? base.motion };
}
