import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { ApiError } from "../api";
import {
  budgetReason,
  canWarmUp,
  coldStartMinutes,
  effectiveQuality,
  isBudgetFailure,
  latestArtifactId,
  needsSpotDetail,
  normalizeEstimate,
  normalizeMotionStatus,
  normalizeWarmup,
  newClips,
  readShotMotion,
  readSpotMotion,
  shotList,
  shotNumber,
  statusRefetchInterval,
  wallMinutes,
  workerView,
} from "./model";
import { MOTION_STATUS_KEY, estimatePath, fetchMotionStatus, fetchSpotEstimate, motionStatusQuery, saveMotionPrompt, warmUpMotion, warmUpMotionQuietly } from "./queries";

// TanStack Query schedules refetch intervals only in a browser (it checks `typeof window` once, when it is imported): give it one for the polling tests.
vi.hoisted(() => {
  (globalThis as { window?: unknown }).window ??= globalThis;
});
afterAll(() => {
  delete (globalThis as { window?: unknown }).window;
});

const STATUS = {
  mode: "azure",
  available: true,
  model: "wan2.2-ti2v-5b",
  license: "Apache-2.0",
  worker: { state: "cold", age_s: null, queue_depth: 0 },
  price_per_gpu_second: 0.00108,
  est_cold_start_s: 240,
  max_clip_s: 5.0,
};

const ESTIMATE = {
  quality: "cinematic",
  aspect: "16:9",
  shots: [
    { shot_id: "s1", seconds: 3.4, frames: 93, cached: true, est_gpu_seconds: 74.4, est_cost_usd: 0.0804 },
    { shot_id: "s2", seconds: 4.2, frames: 109, cached: false, est_gpu_seconds: 87.2, est_cost_usd: 0.0942 },
  ],
  cached_shots: 1,
  est_gpu_seconds: 87.2,
  est_cost_usd: 0.0942,
  est_wall_seconds: 420,
  cold_start_seconds: 240,
  budget: { allowed: true, daily_remaining_usd: 4.62, campaign_remaining_usd: 1.74, reason: null },
};

describe("normalizeMotionStatus", () => {
  it("reads the contract shape", () => {
    expect(normalizeMotionStatus(STATUS)).toEqual({ ...STATUS, reason: null });
  });

  it("keeps the reason an unavailable server gives (off / unreachable) and ignores extra fields", () => {
    expect(normalizeMotionStatus({ ...STATUS, available: false, reason: "unreachable", revision: "b8fff73", host: "x", steps: 20 })).toMatchObject({ available: false, reason: "unreachable" });
    expect(normalizeMotionStatus({ mode: "off", available: false, reason: "off" })).toMatchObject({ mode: "off", reason: "off" });
  });

  it("fills defaults for an older / partial payload instead of throwing", () => {
    const s = normalizeMotionStatus({ available: true, mode: "stub" });
    expect(s).toMatchObject({ mode: "stub", available: true, model: "", license: "", worker: { state: "cold", age_s: null, queue_depth: 0 }, est_cold_start_s: 0, price_per_gpu_second: null, max_clip_s: null });
  });

  it("is never available in mode off or with an unknown mode, and ignores unknown worker states", () => {
    expect(normalizeMotionStatus({ mode: "off", available: true })?.available).toBe(false);
    expect(normalizeMotionStatus({ mode: "something-new", available: true })).toMatchObject({ mode: "off", available: false });
    expect(normalizeMotionStatus({ ...STATUS, worker: { state: "exploding", queue_depth: -3 } })?.worker).toEqual({ state: "cold", age_s: null, queue_depth: 0 });
  });

  it("rejects non-objects and payloads that are not a status (an error body, the SPA's HTML)", () => {
    expect(normalizeMotionStatus(null)).toBeNull();
    expect(normalizeMotionStatus("<html>")).toBeNull();
    expect(normalizeMotionStatus([1])).toBeNull();
    expect(normalizeMotionStatus({ error: { code: "not_found" } })).toBeNull();
    expect(normalizeMotionStatus({ accepted: true })).toBeNull();
  });
});

describe("normalizeEstimate", () => {
  it("reads the contract shape", () => {
    const e = normalizeEstimate(ESTIMATE)!;
    expect(e.shots).toHaveLength(2);
    expect(e.shots[0]).toEqual({ shot_id: "s1", seconds: 3.4, frames: 93, cached: true, est_gpu_seconds: 74.4, est_cost_usd: 0.0804 });
    expect(e).toMatchObject({ cached_shots: 1, est_cost_usd: 0.0942, est_wall_seconds: 420, cold_start_seconds: 240 });
    expect(e.budget).toEqual({ allowed: true, daily_remaining_usd: 4.62, campaign_remaining_usd: 1.74, reason: null });
  });

  it("derives totals and treats an absent budget as no objection", () => {
    const e = normalizeEstimate({ shots: ESTIMATE.shots })!;
    expect(e.cached_shots).toBe(1);
    expect(e.est_cost_usd).toBeCloseTo(0.1746, 4);
    expect(e.cold_start_cost_usd).toBe(0);
    expect(e.budget).toEqual({ allowed: true, daily_remaining_usd: null, campaign_remaining_usd: null, reason: null });
    expect(normalizeEstimate({})!.shots).toEqual([]);
  });

  it("separates the GPU cold start from the shot rows: the server's figure, or what is left of the total", () => {
    const rows = ESTIMATE.shots.reduce((a, s) => a + s.est_cost_usd, 0);
    expect(normalizeEstimate({ ...ESTIMATE, est_cost_usd: rows + 0.2592, cold_start_cost_usd: 0.2592 })!.cold_start_cost_usd).toBeCloseTo(0.2592, 4);
    expect(normalizeEstimate({ ...ESTIMATE, est_cost_usd: rows + 0.2592 })!.cold_start_cost_usd).toBeCloseTo(0.2592, 4);
    expect(normalizeEstimate({ ...ESTIMATE, est_cost_usd: rows })!.cold_start_cost_usd).toBe(0);
    expect(normalizeEstimate({ ...ESTIMATE, est_cost_usd: rows + 0.0001 })!.cold_start_cost_usd).toBe(0); // rounding noise is not a cold start
  });

  it("keeps a refusal and its reason", () => {
    const e = normalizeEstimate({ ...ESTIMATE, budget: { allowed: false, daily_remaining_usd: 0.1, campaign_remaining_usd: 0.05, reason: "daily_budget_exceeded" } })!;
    expect(e.budget).toMatchObject({ allowed: false, reason: "daily_budget_exceeded" });
    expect(normalizeEstimate(undefined)).toBeNull();
  });
});

describe("quality and worker state", () => {
  const status = (over: object) => normalizeMotionStatus({ ...STATUS, ...over });

  it("defaults to Cinematic when motion is available and to Preview when it is not", () => {
    expect(effectiveQuality(null, status({}))).toBe("cinematic");
    expect(effectiveQuality(null, status({ available: false }))).toBe("preview");
    expect(effectiveQuality(null, null)).toBe("preview");
    expect(effectiveQuality(null, status({ mode: "off" }))).toBe("preview");
  });

  it("respects an explicit choice, but never lets an unavailable server render Cinematic", () => {
    expect(effectiveQuality("preview", status({}))).toBe("preview");
    expect(effectiveQuality("cinematic", status({}))).toBe("cinematic");
    expect(effectiveQuality("cinematic", status({ available: false }))).toBe("preview");
  });

  it("maps the status to what the worker row shows", () => {
    expect(workerView(null)).toEqual({ kind: "unavailable" });
    expect(workerView(status({ available: false }))).toEqual({ kind: "unavailable" });
    expect(workerView(status({ mode: "stub" }))).toEqual({ kind: "simulator" });
    expect(workerView(status({ worker: { state: "warming", queue_depth: 2 } }))).toEqual({ kind: "gpu", state: "warming", queueDepth: 2 });
  });

  it("offers the warm-up only for a cold GPU worker", () => {
    expect(canWarmUp(workerView(status({ worker: { state: "cold" } })))).toBe(true);
    expect(canWarmUp(workerView(status({ worker: { state: "warming" } })))).toBe(false);
    expect(canWarmUp(workerView(status({ worker: { state: "ready" } })))).toBe(false);
    expect(canWarmUp(workerView(status({ mode: "stub" })))).toBe(false);
    expect(canWarmUp(workerView(null))).toBe(false);
  });

  it("rounds the minutes shown in the UI (at least one) and prefers the estimate's cold start", () => {
    const e = normalizeEstimate(ESTIMATE)!;
    expect(wallMinutes(e)).toBe(7);
    expect(wallMinutes({ est_wall_seconds: 20 })).toBe(1);
    expect(coldStartMinutes(e, normalizeMotionStatus({ ...STATUS, est_cold_start_s: 120 }))).toBe(4);
    expect(coldStartMinutes({ ...e, cold_start_seconds: 0 }, normalizeMotionStatus({ ...STATUS, est_cold_start_s: 120 }))).toBe(2);
  });
});

describe("helpers", () => {
  it("numbers shots by their id and falls back to the row", () => {
    expect(shotNumber("s3", 0)).toBe(3);
    expect(shotNumber("shot-12", 0)).toBe(12);
    expect(shotNumber("opening", 4)).toBe(5);
    expect(shotNumber("", 0)).toBe(1);
  });

  it("maps a machine reason code to UI wording and passes a sentence through", () => {
    expect(budgetReason("daily_budget_exceeded")).toEqual({ kind: "daily" });
    expect(budgetReason("campaign_budget_exceeded")).toEqual({ kind: "campaign" });
    expect(budgetReason("premium_requires_approval")).toEqual({ kind: "none" });
    expect(budgetReason("Daily AI budget would be exceeded ($5.00)")).toEqual({ kind: "text", text: "Daily AI budget would be exceeded ($5.00)" });
    expect(budgetReason(null)).toEqual({ kind: "none" });
    expect(budgetReason("  ")).toEqual({ kind: "none" });
  });

  it("recognises budget failures by code", () => {
    expect(isBudgetFailure({ code: "daily_budget_exceeded" })).toBe(true);
    expect(isBudgetFailure({ code: "campaign_budget_exceeded" })).toBe(true);
    expect(isBudgetFailure({ code: "premium_requires_approval" })).toBe(true);
    expect(isBudgetFailure({ code: "guardian_blocked" })).toBe(false);
    expect(isBudgetFailure({})).toBe(false);
  });

  it("finds the newest storyboard in the campaign payload", () => {
    const campaign = { artifacts: [{ id: "spot_2", kind: "spot" }, { id: "sb_9", kind: "storyboard" }, { id: "sb_3", kind: "storyboard" }] };
    expect(latestArtifactId(campaign, "storyboard")).toBe("sb_9");
    expect(latestArtifactId({ artifacts: [] }, "storyboard")).toBeNull();
    expect(latestArtifactId({}, "storyboard")).toBeNull();
    expect(latestArtifactId(null, "storyboard")).toBeNull();
  });
});

describe("spot quality and motion summary", () => {
  // what the backend's render.motion report carries: `shots_generated` counts every shot with AI motion (cached ones included), `reason_text` is added to the list/artifact
  const motion = {
    mode: "azure",
    model: "wan2.2-ti2v-5b",
    license: "Apache-2.0",
    shots_total: 4,
    shots_generated: 3,
    shots_cached: 1,
    shots_fallback: [{ shot_id: "s3", reason: "timeout", detail: "no answer", reason_text: "the GPU worker did not answer in time" }],
    gpu_seconds: 241.5,
    cost_usd: 0.52,
    cold_start_s: 240,
    cold_start_usd: 0.2592,
    seed_base: 4242,
  };

  it("reads quality and render.motion of an artifact", () => {
    const info = readSpotMotion({ id: "sp1", quality: "cinematic", render: { render_seconds: 31, motion } });
    expect(info.quality).toBe("cinematic");
    expect(info.motion).toMatchObject({ shots_total: 4, shots_generated: 3, shots_cached: 1, gpu_seconds: 241.5, cost_usd: 0.52, cold_start_usd: 0.2592, model: "wan2.2-ti2v-5b", license: "Apache-2.0", mode: "azure" });
    expect(info.motion?.shots_fallback).toEqual([{ shot_id: "s3", reason: "timeout", reason_text: "the GPU worker did not answer in time" }]);
    expect(newClips(info.motion!)).toBe(2); // generated by this very render: 3 carry AI motion, 1 of them came from the cache
  });

  it("an artifact from before motion existed has neither, and a preview has no summary", () => {
    expect(readSpotMotion({ id: "old", render: { render_seconds: 12 } })).toEqual({ quality: null, motion: null });
    expect(readSpotMotion({ id: "p", quality: "preview" })).toEqual({ quality: "preview", motion: null });
    expect(readSpotMotion(undefined)).toEqual({ quality: null, motion: null });
  });

  it("infers Cinematic from the summary when `quality` is missing, and reads the quality from the spec", () => {
    expect(readSpotMotion({ render: { motion } }).quality).toBe("cinematic");
    expect(readSpotMotion({ spec: { quality: "cinematic" } }).quality).toBe("cinematic");
  });

  it("tolerates fallbacks given as bare shot ids and a missing total", () => {
    const info = readSpotMotion({ quality: "cinematic", render: { motion: { shots_generated: 2, shots_cached: 1, shots_fallback: ["s4"] } } });
    expect(info.motion?.shots_total).toBe(3); // shots_generated + fallbacks: the backend's report counts cached shots in shots_generated
    expect(info.motion?.shots_fallback).toEqual([{ shot_id: "s4", reason: "", reason_text: "" }]);
    expect(info.motion?.cold_start_usd).toBe(0);
  });

  it("asks for the artifact itself only when the list item does not carry what the card needs", () => {
    expect(needsSpotDetail({ id: "a", quality: "cinematic", render: { motion } })).toBe(false);
    expect(needsSpotDetail({ id: "a", quality: "preview" })).toBe(false);
    expect(needsSpotDetail({ id: "a", quality: "cinematic" })).toBe(true); // a list that has the quality but not the summary
    expect(needsSpotDetail({ id: "a" })).toBe(true); // an older list payload (or an artifact from before motion): the artifact decides
    expect(needsSpotDetail(undefined)).toBe(false);
  });

  it("reads a storyboard shot's motion prompt", () => {
    expect(readShotMotion({ id: "s1", motion: { prompt_en: "She lifts the mug.", prompt: "Podnosi kubek.", camera: "slow push-in" } })).toEqual({ prompt_en: "She lifts the mug.", prompt: "Podnosi kubek.", camera: "slow push-in" });
    expect(readShotMotion({ id: "s1", motion: { prompt_en: "Steam rises." } })).toEqual({ prompt_en: "Steam rises.", prompt: "Steam rises.", camera: "" });
    expect(readShotMotion({ id: "s1" })).toBeNull();
    expect(readShotMotion({ id: "s1", motion: "text" })).toBeNull();
  });
});

describe("the motion-quality gate in render.motion", () => {
  const gate = (level: string, over: object = {}) => ({ non_rigid: 2.66, total: 3.1, level, attempts: 1, ...over });
  const report = (shots: unknown[], over: object = {}) => ({ quality: "cinematic", render: { motion: { mode: "azure", shots_total: shots.length, shots_generated: shots.length, shots_cached: 0, shots_fallback: [], shots, ...over } } });

  it("reads the verdict of every shot that has one — level, figures, attempts — in shot order, and the report's counts", () => {
    const info = readSpotMotion(
      report(
        [
          { shot_id: "s1", status: "generated", motion: gate("rich") },
          { shot_id: "s2", status: "cached", motion: gate("subtle", { non_rigid: 0.74, total: 0.9 }) },
          { shot_id: "s3", status: "generated", motion: gate("low", { non_rigid: 0.12, total: 0.2, attempts: 2 }) },
        ],
        { shots_low_motion: 1, retries: 1 },
      ),
    );
    expect(info.motion?.shot_quality).toEqual([
      { shot_id: "s1", number: 1, level: "rich", non_rigid: 2.66, total: 3.1, attempts: 1 },
      { shot_id: "s2", number: 2, level: "subtle", non_rigid: 0.74, total: 0.9, attempts: 1 },
      { shot_id: "s3", number: 3, level: "low", non_rigid: 0.12, total: 0.2, attempts: 2 },
    ]);
    expect(info.motion).toMatchObject({ shots_low_motion: 1, retries: 1 });
  });

  it("an older backend or artifact has no gate: nothing is read and nothing is invented", () => {
    const info = readSpotMotion(report([{ shot_id: "s1", status: "generated" }, { shot_id: "s2", status: "cached" }]));
    expect(info.motion).toMatchObject({ shot_quality: [], shots_low_motion: 0, retries: 0 });
    expect(readSpotMotion({ quality: "cinematic", render: { motion: { shots_total: 2, shots_generated: 2 } } }).motion).toMatchObject({ shot_quality: [], shots_low_motion: 0, retries: 0 });
  });

  it("tolerates a half-written report: unmeasured clips, an unknown level, a missing or odd attempt count, entries that are not shots", () => {
    const info = readSpotMotion(
      report([
        { shot_id: "s1", motion: { non_rigid: null, total: null, level: "unknown", attempts: 1 } },
        { shot_id: "s2", motion: { level: "spectacular", non_rigid: "2.6", attempts: 0 } },
        { shot_id: "s3", motion: "rich" },
        "s4",
        null,
        { shot_id: "s6", motion: { level: "rich", non_rigid: 1.5 } },
        { shot_id: "s7", motion: { level: "low", non_rigid: 0.1, total: 0.2, attempts: 2.4 } },
      ]),
    );
    expect(info.motion?.shot_quality).toEqual([
      { shot_id: "s1", number: 1, level: "unknown", non_rigid: null, total: null, attempts: 1 },
      { shot_id: "s2", number: 2, level: "unknown", non_rigid: null, total: null, attempts: 1 },
      { shot_id: "s6", number: 6, level: "rich", non_rigid: 1.5, total: null, attempts: 1 },
      { shot_id: "s7", number: 7, level: "low", non_rigid: 0.1, total: 0.2, attempts: 2 },
    ]);
  });

  it("numbers a shot by its id, and by its place in the list when the id has no number", () => {
    const info = readSpotMotion(report([{ shot_id: "opening", motion: gate("rich") }, { shot_id: "closing", motion: gate("low") }]));
    expect(info.motion?.shot_quality.map((q) => q.number)).toEqual([1, 2]);
  });

  it("the report's own low-motion and retry counts win; without them they are counted from the shots; nonsense reads as zero", () => {
    const shots = [
      { shot_id: "s1", motion: gate("low") },
      { shot_id: "s2", motion: gate("low", { attempts: 2 }) },
      { shot_id: "s3", motion: gate("rich", { attempts: 2 }) },
    ];
    expect(readSpotMotion(report(shots)).motion).toMatchObject({ shots_low_motion: 2, retries: 2 });
    expect(readSpotMotion(report(shots, { shots_low_motion: 0, retries: 5 })).motion).toMatchObject({ shots_low_motion: 0, retries: 5 });
    expect(readSpotMotion(report(shots, { shots_low_motion: -3, retries: "x" })).motion).toMatchObject({ shots_low_motion: 0, retries: 2 });
  });
});

describe("shotList", () => {
  it("reads naturally in both languages and keeps the Polish conjunction with the number after it", () => {
    expect(shotList([3], "en-US")).toBe("3");
    expect(shotList([2, 4], "en-US")).toBe("2 and 4");
    expect(shotList([1, 2, 5], "en-US")).toBe("1, 2, and 5");
    expect(shotList([3], "pl-PL")).toBe("3");
    expect(shotList([2, 4], "pl-PL")).toBe("2 i\u00A04");
    expect(shotList([1, 2, 5], "pl-PL")).toBe("1, 2 i\u00A05");
  });
});

describe("status polling policy", () => {
  it("polls every 10 s, except for a server that has no motion", () => {
    const azure = normalizeMotionStatus(STATUS)!;
    expect(statusRefetchInterval(azure)).toBe(10_000);
    expect(statusRefetchInterval(undefined)).toBe(10_000);
    expect(statusRefetchInterval({ ...azure, mode: "off", available: false })).toBe(false);
    expect(statusRefetchInterval(undefined, 404)).toBe(false);
    expect(statusRefetchInterval(undefined, 500)).toBe(10_000);
  });
});

// ------------------------------------------------------------------------------------------------------------- API calls (mocked fetch)
interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}
let calls: Call[];
let respond: (call: Call) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>;

beforeEach(() => {
  calls = [];
  respond = () => ({ body: {} });
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const call: Call = { method: init.method ?? "GET", url: String(url), headers: (init.headers ?? {}) as Record<string, string>, body: init.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const r = await respond(call);
      return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("API calls", () => {
  it("GET /api/motion/status goes through the shared client (language headers) and is normalized", async () => {
    respond = () => ({ body: STATUS });
    const s = await fetchMotionStatus();
    expect(s.worker.state).toBe("cold");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "GET", url: "/api/motion/status" });
    expect(calls[0].headers["X-UI-Lang"]).toBe("en");
    expect(calls[0].headers["Accept-Language"]).toBe("en");
  });

  it("a status payload that is not an object is an error (the UI then treats motion as unavailable)", async () => {
    respond = () => ({ body: "<html>" });
    await expect(fetchMotionStatus()).rejects.toThrow();
  });

  it("builds the estimate URL with quality, aspect and the storyboard", () => {
    expect(estimatePath("cmp_1", { quality: "cinematic", aspect: "16:9", storyboardId: "sb_7" })).toBe("/api/campaigns/cmp_1/spot/estimate?quality=cinematic&aspect=16%3A9&storyboard_id=sb_7");
    expect(estimatePath("cmp_1", { quality: "cinematic", aspect: "9:16" })).toBe("/api/campaigns/cmp_1/spot/estimate?quality=cinematic&aspect=9%3A16");
  });

  it("GET …/spot/estimate returns the normalized estimate", async () => {
    respond = () => ({ body: ESTIMATE });
    const e = await fetchSpotEstimate("cmp_1", { quality: "cinematic", aspect: "16:9", storyboardId: "sb_7" });
    expect(e.shots).toHaveLength(2);
    expect(calls[0]).toMatchObject({ method: "GET", url: "/api/campaigns/cmp_1/spot/estimate?quality=cinematic&aspect=16%3A9&storyboard_id=sb_7" });
  });

  it("POST /api/motion/warmup is a plain POST (user-initiated: its errors are shown); the answer carries the worker state and what the cold start costs", async () => {
    respond = () => ({ status: 202, body: { ...STATUS, worker: { state: "warming", age_s: null, queue_depth: 1 }, warmup: { requested: true, est_cost_usd: 0.25920, est_seconds: 240 } } });
    const res = await warmUpMotion();
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/motion/warmup" });
    expect(res.status?.worker.state).toBe("warming");
    expect(res).toMatchObject({ requested: true, est_cost_usd: 0.2592, est_seconds: 240 });
  });

  it("a warm-up answer without the `warmup` block (older backend) says nothing about cost and is not a refusal", async () => {
    respond = () => ({ status: 202, body: { accepted: true } });
    expect(await warmUpMotion()).toEqual({ status: null, requested: null, est_cost_usd: null, est_seconds: null });
    expect(normalizeWarmup({ ...STATUS, warmup: { requested: false, est_cost_usd: 0, est_seconds: 0 } })).toMatchObject({ requested: false, est_cost_usd: 0 });
  });

  it("a warm-up the budget refuses (402) is an error the user sees; the silent variant swallows it", async () => {
    respond = () => ({ status: 402, body: { error: { code: "daily_budget_exceeded", message: "Daily AI budget reached." } } });
    await expect(warmUpMotion()).rejects.toMatchObject({ status: 402, code: "daily_budget_exceeded" });
    await expect(warmUpMotionQuietly()).resolves.toBe(false);
  });

  it("the silent warm-up never throws: an older backend (404), a server error and a dead network are all swallowed", async () => {
    respond = () => ({ status: 404, body: { error: { code: "not_found", message: "Not found" } } });
    await expect(warmUpMotionQuietly()).resolves.toBe(false);
    respond = () => ({ status: 503, body: { error: { code: "provider_unavailable", message: "down" } } });
    await expect(warmUpMotionQuietly()).resolves.toBe(false);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(warmUpMotionQuietly()).resolves.toBe(false);
  });

  it("the silent warm-up posts once when it can, and does nothing when the known status says motion is unavailable", async () => {
    respond = () => ({ status: 202, body: {} });
    await expect(warmUpMotionQuietly()).resolves.toBe(true);
    expect(calls.filter((c) => c.url === "/api/motion/warmup")).toHaveLength(1);

    const off = new QueryClient();
    off.setQueryData(MOTION_STATUS_KEY, normalizeMotionStatus({ mode: "off", available: false }));
    calls.length = 0;
    await expect(warmUpMotionQuietly(off)).resolves.toBe(false);
    expect(calls).toHaveLength(0);

    const on = new QueryClient();
    on.setQueryData(MOTION_STATUS_KEY, normalizeMotionStatus(STATUS));
    await expect(warmUpMotionQuietly(on)).resolves.toBe(true);
    expect(calls).toHaveLength(1);
  });

  it("an ApiError from a quiet request does not reach the toast listeners", async () => {
    const seen: ApiError[] = [];
    const { onApiError } = await import("../api");
    const off = onApiError((e) => seen.push(e));
    respond = () => ({ status: 404, body: { error: { code: "not_found", message: "Not found" } } });
    await warmUpMotionQuietly();
    await expect(fetchMotionStatus()).rejects.toBeInstanceOf(ApiError);
    off();
    expect(seen).toEqual([]);
  });

  it("PATCH …/shots/{id} sends the motion text", async () => {
    respond = () => ({ body: { id: "s2", motion: { prompt: "Steam rises." } } });
    await saveMotionPrompt("cmp_1", "sb_7", "s2", "Steam rises.");
    expect(calls[0]).toMatchObject({ method: "PATCH", url: "/api/campaigns/cmp_1/storyboard/sb_7/shots/s2", body: { motion: "Steam rises." } });
  });
});

describe("status polling while the step is open", () => {
  it("refetches every 10 s while observed and stops as soon as the step is left", async () => {
    vi.useFakeTimers();
    respond = (c) => ({ body: c.url === "/api/motion/status" ? STATUS : {} });
    const client = new QueryClient();
    const observer = new QueryObserver(client, motionStatusQuery());
    const unsubscribe = observer.subscribe(() => undefined);
    const statusCalls = () => calls.filter((c) => c.url === "/api/motion/status").length;

    await vi.advanceTimersByTimeAsync(0);
    expect(statusCalls()).toBe(1);
    await vi.advanceTimersByTimeAsync(9_000);
    expect(statusCalls()).toBe(1);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(statusCalls()).toBe(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(statusCalls()).toBe(3);

    unsubscribe(); // the Video step is closed
    await vi.advanceTimersByTimeAsync(120_000);
    expect(statusCalls()).toBe(3);
    client.clear();
  });

  it("does not poll a server that has no motion endpoint", async () => {
    vi.useFakeTimers();
    respond = () => ({ status: 404, body: { error: { code: "not_found", message: "Not found" } } });
    const client = new QueryClient();
    const observer = new QueryObserver(client, motionStatusQuery());
    const unsubscribe = observer.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.filter((c) => c.url === "/api/motion/status")).toHaveLength(1);
    unsubscribe();
    client.clear();
  });
});
