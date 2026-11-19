import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import { feature as storyboardFeature } from "../features/cs07-storyboard";
import { feature as spotFeature } from "../features/cs08-spot";
import { feature as provenanceFeature } from "../features/cs14-provenance";
import { normalizeEstimate, normalizeMotionStatus, readSpotMotion, statusRefetchInterval, type SpotMotionInfo } from "./model";
import { MotionPromptEditor } from "./MotionPromptEditor";
import { RenderFailure } from "./RenderFailure";
import { RenderQualityPicker, type RenderQualityPickerProps } from "./RenderQuality";
import { SpotMotionChip, SpotMotionDetails } from "./SpotMotion";

const NB = "\u00A0";

const STATUS = { mode: "azure", available: true, model: "wan2.2-ti2v-5b", license: "Apache-2.0", worker: { state: "cold", age_s: null, queue_depth: 0 }, price_per_gpu_second: 0.00108, est_cold_start_s: 240, max_clip_s: 5.0 };
const ESTIMATE = {
  quality: "cinematic",
  aspect: "16:9",
  shots: [
    { shot_id: "s1", seconds: 3.4, frames: 93, cached: true, est_gpu_seconds: 0, est_cost_usd: 0 },
    { shot_id: "s2", seconds: 4.2, frames: 109, cached: false, est_gpu_seconds: 87.2, est_cost_usd: 0.0942 },
  ],
  cached_shots: 1,
  est_gpu_seconds: 87.2,
  est_cost_usd: 0.0942,
  est_wall_seconds: 420,
  cold_start_seconds: 240,
  budget: { allowed: true, daily_remaining_usd: 4.62, campaign_remaining_usd: 1.74, reason: null },
};
// render.motion as the backend reports it: `shots_generated` counts every shot that carries AI motion (cached ones included), shots_generated + fallbacks = shots_total
const MOTION = { mode: "azure", model: "wan2.2-ti2v-5b", license: "Apache-2.0", shots_total: 4, shots_generated: 4, shots_cached: 0, shots_fallback: [] as { shot_id: string; reason: string; reason_text?: string }[], gpu_seconds: 318.4, cost_usd: 0.3439, cold_start_usd: 0, seed_base: 77 };

const status = (over: Record<string, unknown> = {}) => normalizeMotionStatus({ ...STATUS, ...over });
const workerState = (state: string, queue = 0) => status({ worker: { state, age_s: 12, queue_depth: queue } });
const estimate = (over: Record<string, unknown> = {}) => normalizeEstimate({ ...ESTIMATE, ...over });
const picker = (over: Partial<RenderQualityPickerProps> = {}): RenderQualityPickerProps => ({
  status: status(),
  statusState: "ready",
  quality: "cinematic",
  onQuality: () => undefined,
  estimate: estimate(),
  estimateState: "ready",
  onWarmUp: () => undefined,
  ...over,
});

const render = (node: ReactElement) => renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>);
// text of the markup: block-level boundaries become a space, inline tags (links, badges, icons) vanish; no-break spaces are kept
const plain = (html: string) =>
  html
    .replace(/<\/?(?:div|p|li|ul|ol|tr|td|th|thead|tbody|tfoot|table|caption|h[1-6]|label|button|section|fieldset|legend|dl|dt|dd|textarea|br)\b[^>]*>/g, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/[ \t\r\n]+/g, " ");
// the Polish UI glues one-letter words (w, z, i …) to the next word with a no-break space: wording checks compare with plain spaces, unit checks keep the NBSP
const flat = (s: string) => s.replace(/\u00A0/g, " ");
const tag = (html: string, testId: string) => [...html.matchAll(/<[a-z0-9]+\b[^>]*data-testid="([^"]+)"[^>]*>/g)].find((m) => m[1] === testId)?.[0];
const button = (html: string, name: string) => [...html.matchAll(/<button\b([^>]*)>((?:(?!<\/button>)[\s\S])*)<\/button>/g)].find((m) => plain(m[2]).trim() === name)?.[1];

let warn: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined });
});
afterEach(() => {
  setLang("en");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const missingKeys = () => warn.mock.calls.map((c: unknown[]) => String(c[0])).filter((m: string) => m.startsWith("[i18n] missing"));
const unresolved = (s: string) => s.match(/\{[A-Za-z_]\w*\}/g) ?? [];

describe("RenderQualityPicker — availability", () => {
  it("an unavailable server: Cinematic is disabled with the reason, Preview is the only choice, nothing about a GPU", () => {
    const html = render(<RenderQualityPicker {...picker({ status: status({ mode: "off", available: false }), quality: "preview", estimate: null, estimateState: "idle" })} />);
    expect(tag(html, "quality-cinematic")).toContain('disabled=""');
    expect(tag(html, "quality-cinematic")).toContain("aria-describedby=");
    expect(tag(html, "quality-preview")).toContain('checked=""');
    expect(tag(html, "quality-preview")).not.toContain('disabled=""');
    expect(plain(html)).toContain("AI motion is not available on this server — only Preview can be rendered.");
    expect(html).not.toContain('data-testid="gpu-status"');
    expect(html).not.toContain('data-testid="motion-estimate"');
  });

  it("an older backend without the endpoint (status request failed) is explained the same way", () => {
    const html = render(<RenderQualityPicker {...picker({ status: null, statusState: "error", quality: "preview", estimate: null, estimateState: "idle" })} />);
    expect(plain(html)).toContain("only Preview can be rendered");
    expect(tag(html, "quality-cinematic")).toContain('disabled=""');
  });

  it("a configured but unreachable motion service says so (and recovers by itself: the status keeps being polled)", () => {
    const html = render(<RenderQualityPicker {...picker({ status: status({ available: false, reason: "unreachable" }), quality: "preview", estimate: null, estimateState: "idle" })} />);
    expect(plain(html)).toContain("The motion service cannot be reached right now — only Preview can be rendered.");
    expect(tag(html, "quality-cinematic")).toContain('disabled=""');
    expect(statusRefetchInterval(status({ available: false, reason: "unreachable" })!)).toBe(10_000);
  });

  it("while the status is still loading, nothing is claimed about availability", () => {
    const html = render(<RenderQualityPicker {...picker({ status: null, statusState: "loading", quality: "preview", estimate: null, estimateState: "idle" })} />);
    expect(html).not.toContain('data-testid="cinematic-unavailable"');
    expect(tag(html, "quality-preview")).toContain('checked=""');
  });

  it("when motion is available Cinematic is checked and carries the estimate (cost · minutes) in its label", () => {
    const html = render(<RenderQualityPicker {...picker()} />);
    expect(tag(html, "quality-cinematic")).toContain('checked=""');
    expect(tag(html, "quality-cinematic")).not.toContain('disabled=""');
    expect(tag(html, "quality-preview")).not.toContain('checked=""');
    const t = plain(html);
    expect(t).toContain("Preview stills with camera moves (free, ~30 s)");
    expect(t).toContain("Cinematic AI video, real motion (est. $0.094 · ~7 min)");
  });

  it("whole cents from ten cents up, a third decimal below (a $0.094 estimate is never shown as $0.09)", () => {
    const big = estimate({ est_cost_usd: 0.3768 });
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: big })} />))).toContain("(est. $0.38 · ~7 min)");
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: estimate({ est_cost_usd: 0 }) })} />))).toContain("(est. $0.00 · ~7 min)");
  });

  it("the estimate panel is for Cinematic only; the Cinematic label still shows the estimate while Preview is selected", () => {
    const html = render(<RenderQualityPicker {...picker({ quality: "preview" })} />);
    expect(html).not.toContain('data-testid="motion-estimate"');
    expect(plain(html)).toContain("(est. $0.094 · ~7 min)");
    expect(tag(html, "quality-preview")).toContain('checked=""');
  });
});

describe("RenderQualityPicker — GPU worker states", () => {
  it("cold: badge, an enabled Warm up GPU button, the cold-start note and a per-shot estimate", () => {
    const html = render(<RenderQualityPicker {...picker({ status: workerState("cold") })} />);
    const t = plain(html);
    expect(tag(html, "gpu-status")).toContain('data-worker-state="cold"');
    expect(t).toContain("GPU worker: cold");
    expect(button(html, "Warm up GPU")).toBeDefined();
    expect(button(html, "Warm up GPU")).not.toContain('disabled=""');
    expect(t).toContain("The GPU worker is cold: the first shot also waits for the GPU to start (about 4 min). Warm it up now to skip that wait.");
    expect(t).toContain("Cinematic estimate");
    expect([...html.matchAll(/data-testid="estimate-shot"/g)]).toHaveLength(2);
    expect(t).toContain("Shot 1");
    expect(t).toContain("Shot 2");
    expect(t).toContain("3.4 s");
    expect(t).toContain("4.2 s");
    expect(t).toContain("cached");
    expect(t).toContain("to generate");
    expect(t).toContain("cached: 1/2");
    expect(t).toContain("$0.094");
    expect(t).toContain("$4.62");
    expect(t).toContain("$1.74");
  });

  it("the per-shot rows tell cached clips from clips still to generate", () => {
    const html = render(<RenderQualityPicker {...picker()} />);
    const rows = [...html.matchAll(/<tr[^>]*data-testid="estimate-shot"[^>]*data-cached="(true|false)"/g)].map((m) => m[1]);
    expect(rows).toEqual(["true", "false"]);
  });

  it("a cold GPU adds its own row so the rows add up to the total (the estimate's total includes the cold start)", () => {
    const withCold = estimate({ est_cost_usd: 0.0942 + 0.2592, cold_start_cost_usd: 0.2592 });
    const html = render(<RenderQualityPicker {...picker({ status: workerState("cold"), estimate: withCold })} />);
    const t = plain(html);
    expect(tag(html, "estimate-cold-start")).toBeDefined();
    expect(t).toContain("GPU cold start (~4 min)");
    expect(t).toContain("$0.259");
    expect(html).toMatch(/data-testid="estimate-total">\$0\.353</);
    expect(t).toContain("(est. $0.35 · ~7 min)");
    // a worker that is ready (or nothing left to generate) has no cold-start row
    expect(render(<RenderQualityPicker {...picker({ status: workerState("ready") })} />)).not.toContain("estimate-cold-start");
  });

  it("warming: the badge says so, the button is disabled, the note changes", () => {
    const html = render(<RenderQualityPicker {...picker({ status: workerState("warming") })} />);
    const t = plain(html);
    expect(tag(html, "gpu-status")).toContain('data-worker-state="warming"');
    expect(t).toContain("GPU worker: warming up…");
    expect(button(html, "Warm up GPU")).toContain('disabled=""');
    expect(t).toContain("The GPU worker is warming up — rendering starts as soon as it is ready.");
    expect(t).not.toContain("The GPU worker is cold");
  });

  it("ready: no cold-start note, the warm-up button is disabled", () => {
    const html = render(<RenderQualityPicker {...picker({ status: workerState("ready"), estimate: estimate({ cold_start_seconds: 0, est_wall_seconds: 180 }) })} />);
    const t = plain(html);
    expect(t).toContain("GPU worker: ready");
    expect(button(html, "Warm up GPU")).toContain('disabled=""');
    expect(html).not.toContain('data-testid="cold-start-note"');
    expect(t).toContain("(est. $0.094 · ~3 min)");
  });

  it("a click on Warm up GPU is only possible while the worker is cold (busy state shows the spinner and blocks it)", () => {
    const busy = render(<RenderQualityPicker {...picker({ status: workerState("cold"), warmUpBusy: true })} />);
    expect(button(busy, "Warm up GPU")).toContain('disabled=""');
  });

  it("shows how many jobs are queued on the single GPU, with the right plural", () => {
    expect(plain(render(<RenderQualityPicker {...picker({ status: workerState("ready", 1) })} />))).toContain("1 job in the GPU queue");
    expect(plain(render(<RenderQualityPicker {...picker({ status: workerState("ready", 3) })} />))).toContain("3 jobs in the GPU queue");
    expect(plain(render(<RenderQualityPicker {...picker({ status: workerState("ready", 0) })} />))).not.toContain("in the GPU queue");
  });

  it("the offline simulator has nothing to warm up, and says that its figures are simulated", () => {
    const html = render(<RenderQualityPicker {...picker({ status: status({ mode: "stub" }) })} />);
    expect(plain(html)).toContain("Offline motion simulator");
    expect(plain(html)).toContain("Offline simulator: the motion is procedural (no AI model) and the costs shown are simulated at the same list prices.");
    expect(button(html, "Warm up GPU")).toBeUndefined();
    expect(html).not.toContain('data-testid="cold-start-note"');
    expect(html).toContain('data-testid="motion-estimate"');
    // a real GPU worker has no such note
    expect(render(<RenderQualityPicker {...picker({ status: workerState("ready") })} />)).not.toContain("simulator-note");
  });

  it("the E2E settle check treats [aria-live=polite] as the toast area and [aria-label=loading] as a pending request: neither may appear for a warming GPU", () => {
    const html = render(<RenderQualityPicker {...picker({ status: workerState("warming") })} />);
    expect(html).not.toContain('aria-live="polite"');
    expect(html).not.toContain('aria-label="loading"');
    expect(html).not.toContain("data-spinner");
    expect(html).toContain('role="status"');
  });
});

describe("RenderQualityPicker — estimate states and budget refusal", () => {
  it("loading shows a busy skeleton, an unreachable estimate says so and still lets the user render", () => {
    const loading = render(<RenderQualityPicker {...picker({ estimate: null, estimateState: "loading" })} />);
    expect(loading).toContain('aria-busy="true"');
    expect(loading).toContain("skeleton");
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: null, estimateState: "loading" })} />))).toContain("AI video, real motion");
    const failed = plain(render(<RenderQualityPicker {...picker({ estimate: null, estimateState: "error" })} />));
    expect(failed).toContain("The estimate is not available right now — you can still render.");
    const withReason = plain(render(<RenderQualityPicker {...picker({ estimate: null, estimateState: "error", estimateError: "A spot needs a storyboard with keyframes (CS-07)." })} />));
    expect(withReason).toContain("Estimate unavailable: A spot needs a storyboard with keyframes (CS-07).");
  });

  it("a refused budget is announced inline as an alert, with the reason and the way out", () => {
    const refused = estimate({ budget: { allowed: false, daily_remaining_usd: 0.04, campaign_remaining_usd: 1.74, reason: "daily_budget_exceeded" } });
    const html = render(<RenderQualityPicker {...picker({ estimate: refused })} />);
    expect(tag(html, "budget-refusal")).toContain('role="alert"');
    const t = plain(html);
    expect(t).toContain("Not enough AI budget for a Cinematic render");
    expect(t).toContain("The daily AI budget would be exceeded.");
    expect(t).toContain("Choose Preview, or raise the cap on the cost meter (admin only).");
    expect(html).toContain('href="/cost"');
    expect(t).toContain("$0.04");
  });

  it("a server sentence is shown as received; a campaign code and a missing reason have their own wording", () => {
    const refused = (reason: string | null) => estimate({ budget: { allowed: false, daily_remaining_usd: 1, campaign_remaining_usd: 0, reason } });
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: refused("This campaign has used its $2.00 AI cap.") })} />))).toContain("This campaign has used its $2.00 AI cap.");
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: refused("campaign_budget_exceeded") })} />))).toContain("The AI budget of this campaign would be exceeded.");
    expect(plain(render(<RenderQualityPicker {...picker({ estimate: refused(null) })} />))).toContain("The daily or per-campaign AI cap would be exceeded.");
  });

  it("an allowed budget shows no alert", () => {
    expect(render(<RenderQualityPicker {...picker()} />)).not.toContain('data-testid="budget-refusal"');
  });

  it("when every clip is cached the estimate is free and says so", () => {
    const cached = estimate({
      shots: ESTIMATE.shots.map((s) => ({ ...s, cached: true, est_cost_usd: 0, est_gpu_seconds: 0 })),
      cached_shots: 2,
      est_cost_usd: 0,
      est_gpu_seconds: 0,
      est_wall_seconds: 45,
      cold_start_seconds: 0,
    });
    const t = plain(render(<RenderQualityPicker {...picker({ status: workerState("ready"), estimate: cached })} />));
    expect(t).toContain("cached: 2/2");
    expect(t).toContain("(est. $0.00 · ~1 min)");
    expect(t).not.toContain("to generate");
  });
});

describe("RenderQualityPicker — accessibility", () => {
  const html = render(<RenderQualityPicker {...picker({ status: workerState("cold") })} />);

  it("is a labelled radio group: fieldset + legend, native radios that share a name", () => {
    expect(html).toContain("<fieldset");
    expect(html).toContain("<legend");
    expect(plain(html)).toContain("Render quality");
    const names = [...html.matchAll(/<input type="radio"[^>]*\sname="([^"]+)"/g)].map((m) => m[1]);
    expect(names).toHaveLength(2);
    expect(new Set(names).size).toBe(1);
  });

  it("each radio is named by its visible label (title and description are inside the label)", () => {
    expect(html).toMatch(/<label[^>]*><input type="radio"[^>]*data-testid="quality-preview"[^>]*\/?><span[^>]*><span[^>]*>Preview<\/span> <span[^>]*>stills with camera moves/);
    expect(html).toMatch(/<label[^>]*><input type="radio"[^>]*data-testid="quality-cinematic"[^>]*\/?><span[^>]*><span[^>]*>Cinematic<\/span> <span[^>]*>AI video, real motion/);
  });

  it("the estimate is a labelled region with a captioned table (column and row headers)", () => {
    expect(html).toMatch(/<section aria-labelledby="[^"]+"[^>]*data-testid="motion-estimate"/);
    expect(html).toContain('<caption class="sr-only">Estimate per shot</caption>');
    expect([...html.matchAll(/<th scope="col"/g)].length).toBe(4);
    expect([...html.matchAll(/<th scope="row"/g)].length).toBe(3);
    expect(html).toMatch(/<h4 id="([^"]+)"[^>]*>Cinematic estimate/);
  });

  it("the GPU badge is a status region and decorative icons are hidden from assistive technology", () => {
    expect(html).toMatch(/<span role="status"><span[^>]*>(?:<svg[^>]*aria-hidden="true"[^>]*>[\s\S]*?<\/svg>)GPU worker: cold/);
  });
});

describe("RenderQualityPicker — Polish", () => {
  const cold = () => render(<RenderQualityPicker {...picker({ status: workerState("cold", 2) })} />);

  it("renders every state in Polish with no English, no raw placeholders and no missing keys", () => {
    setLang("pl");
    const states = [
      cold(),
      render(<RenderQualityPicker {...picker({ status: workerState("warming") })} />),
      render(<RenderQualityPicker {...picker({ status: workerState("ready"), estimate: estimate({ cold_start_seconds: 0 }) })} />),
      render(<RenderQualityPicker {...picker({ status: status({ mode: "stub" }) })} />),
      render(<RenderQualityPicker {...picker({ status: null, statusState: "error", quality: "preview", estimate: null, estimateState: "idle" })} />),
      render(<RenderQualityPicker {...picker({ estimate: estimate({ budget: { allowed: false, daily_remaining_usd: 0, campaign_remaining_usd: 1, reason: "daily_budget_exceeded" } }) })} />),
      render(<RenderQualityPicker {...picker({ estimate: null, estimateState: "error" })} />),
    ];
    for (const html of states) {
      const t = plain(html);
      expect(unresolved(t), t).toEqual([]);
      expect(t).not.toMatch(/Render quality|Cinematic estimate|Warm up GPU|GPU worker|Estimate per shot|not available/);
    }
    expect(missingKeys()).toEqual([]);
  });

  it("uses natural Polish wording, Polish number formats and no-break units", () => {
    setLang("pl");
    const html = cold();
    const t = plain(html);
    const w = flat(t);
    expect(w).toContain("Tryb renderu");
    expect(w).toContain("Podgląd");
    expect(t).toContain(`ruch kamery na nieruchomych klatkach (bezpłatnie, ok. 30${NB}s)`);
    expect(t).toContain(`Filmowy wideo AI z${NB}prawdziwym ruchem (szac. 0,094${NB}USD · ok. 7${NB}min)`);
    expect(w).toContain("Serwer GPU: uśpiony");
    expect(w).toContain("Rozgrzej GPU");
    expect(w).toContain("2 zadania w kolejce GPU");
    expect(w).toContain("Szacunek dla trybu filmowego");
    expect(w).toContain("Ujęcie 1");
    expect(t).toContain(`3,4${NB}s`);
    expect(w).toContain("z pamięci podręcznej");
    expect(w).toContain("do wygenerowania");
    expect(w).toContain("z pamięci podręcznej: 1/2");
    expect(w).toContain("Razem");
    expect(t).toContain(`4,62${NB}USD`);
    expect(t).toContain(`0,094${NB}USD`);
    expect(t).toContain(`ok. 7${NB}min`);
    expect(w).toContain("Serwer GPU jest uśpiony: pierwsze ujęcie czeka dodatkowo na uruchomienie GPU (ok. 4 min). Rozgrzej go teraz, aby pominąć to oczekiwanie.");
  });

  it("budget refusal, with the link inside the Polish sentence", () => {
    setLang("pl");
    const refused = estimate({ budget: { allowed: false, daily_remaining_usd: 0, campaign_remaining_usd: 1, reason: "daily_budget_exceeded" } });
    const html = render(<RenderQualityPicker {...picker({ estimate: refused })} />);
    const t = flat(plain(html));
    expect(t).toContain("Za mało budżetu AI na render filmowy");
    expect(t).toContain("Przekroczony zostałby dzienny limit budżetu AI.");
    expect(t).toContain("Wybierz podgląd albo zwiększ limit w liczniku kosztów (tylko administrator).");
    expect(flat(html)).toMatch(/<a [^>]*href="\/cost"[^>]*>liczniku kosztów<\/a>/);
  });

  it("the unavailable reason and the simulator", () => {
    setLang("pl");
    expect(flat(plain(render(<RenderQualityPicker {...picker({ status: null, statusState: "error", quality: "preview", estimate: null, estimateState: "idle" })} />)))).toContain(
      "Ruch AI nie jest dostępny na tym serwerze — można renderować tylko w trybie podglądu.",
    );
    expect(plain(render(<RenderQualityPicker {...picker({ status: status({ mode: "stub" }) })} />))).toContain("Symulator ruchu offline");
    expect(flat(plain(render(<RenderQualityPicker {...picker({ status: status({ mode: "stub" }) })} />)))).toContain(
      "Symulator offline: ruch jest generowany proceduralnie (bez modelu AI), a pokazane koszty są symulowane według tych samych cen katalogowych.",
    );
  });

  it("language switching works on the same component: the markup follows the active language", () => {
    expect(plain(cold())).toContain("Render quality");
    setLang("pl");
    expect(plain(cold())).toContain("Tryb renderu");
    setLang("en");
    expect(plain(cold())).toContain("Render quality");
  });
});

describe("SpotMotionChip / SpotMotionDetails", () => {
  const info = (over: Partial<typeof MOTION> & { shots?: unknown[]; shots_low_motion?: number; retries?: number } = {}, quality: "cinematic" | "preview" | null = "cinematic"): SpotMotionInfo =>
    readSpotMotion({ quality, render: { motion: { ...MOTION, ...over } } });

  it("Cinematic · AI motion 4/4 shots", () => {
    const html = render(<SpotMotionChip info={info()} />);
    expect(plain(html)).toContain("Cinematic · AI motion 4/4 shots");
    expect(html).toContain('data-fallbacks="0"');
    expect(plain(html)).not.toContain("fallback");
  });

  it("3/4 shots · 1 fallback — the chip turns to the warning tone", () => {
    const html = render(<SpotMotionChip info={info({ shots_generated: 3, shots_fallback: [{ shot_id: "s3", reason: "timeout" }] })} />);
    expect(plain(html)).toContain("Cinematic · AI motion 3/4 shots · 1 fallback");
    expect(html).toContain("bg-dawn-300/40");
  });

  it("pluralises fallbacks", () => {
    const two = render(<SpotMotionChip info={info({ shots_generated: 2, shots_fallback: [{ shot_id: "s3", reason: "" }, { shot_id: "s4", reason: "" }] })} />);
    expect(plain(two)).toContain("Cinematic · AI motion 2/4 shots · 2 fallbacks");
  });

  it("cached re-renders count as AI motion too", () => {
    const html = render(<SpotMotionChip info={info({ shots_generated: 4, shots_cached: 4, gpu_seconds: 0, cost_usd: 0 })} />);
    expect(plain(html)).toContain("Cinematic · AI motion 4/4 shots");
  });

  it("a Cinematic spot without a summary shows the bare chip; a Preview a neutral one; an old artifact nothing", () => {
    expect(plain(render(<SpotMotionChip info={readSpotMotion({ quality: "cinematic" })} />))).toContain("Cinematic");
    expect(plain(render(<SpotMotionChip info={readSpotMotion({ quality: "preview" })} />))).toContain("Preview");
    expect(render(<SpotMotionChip info={readSpotMotion({ id: "old", render: { render_seconds: 12 } })} />)).toBe("");
    expect(render(<SpotMotionDetails info={readSpotMotion({ id: "old" })} />)).toBe("");
    expect(render(<SpotMotionDetails info={readSpotMotion({ quality: "preview" })} />)).toBe("");
  });

  it("the model / licence line, the hosting, new vs reused clips, GPU time and cost", () => {
    const t = plain(render(<SpotMotionDetails info={info({ shots_generated: 4, shots_cached: 1 })} />));
    expect(t).toContain("Motion model: wan2.2-ti2v-5b · licence Apache-2.0 · self-hosted on serverless GPU in your Azure environment");
    expect(t).toContain("New clips: 3 · reused from cache: 1 · GPU time: 318 s · $0.34");
    expect(t).not.toContain("cold start");
  });

  it("names the GPU cold start when it is part of the cost", () => {
    const t = plain(render(<SpotMotionDetails info={info({ cost_usd: 0.6031, cold_start_usd: 0.2592 })} />));
    expect(t).toContain("GPU time: 318 s · $0.60 · incl. $0.26 for the GPU cold start");
  });

  it("an all-cached re-render used no GPU time; the offline simulator and a local worker are named honestly", () => {
    const cached = plain(render(<SpotMotionDetails info={info({ shots_generated: 4, shots_cached: 4, gpu_seconds: 0, cost_usd: 0 })} />));
    expect(cached).toContain("New clips: 0 · reused from cache: 4 · no GPU time used");
    expect(plain(render(<SpotMotionDetails info={info({ mode: "stub", model: "procedural-animator", license: "" })} />))).toContain("Motion model: procedural-animator · licence — · offline motion simulator");
    expect(plain(render(<SpotMotionDetails info={info({ mode: "local" })} />))).toContain("local motion worker");
  });

  it("lists the shots that fell back to camera moves on the keyframe: the server's reason text first, the dictionary for a bare code, a new code as received", () => {
    const withText = render(<SpotMotionDetails info={info({ shots_generated: 3, shots_fallback: [{ shot_id: "s3", reason: "timeout", reason_text: "the GPU worker did not answer in time" }, { shot_id: "s4", reason: "some_new_reason" }] })} />);
    expect(plain(withText)).toContain("Fell back to camera moves on the keyframe: Shot 3 (the GPU worker did not answer in time), Shot 4 (some_new_reason)");
    const codeOnly = render(<SpotMotionDetails info={info({ shots_generated: 3, shots_fallback: [{ shot_id: "s3", reason: "timeout" }] })} />);
    expect(plain(codeOnly)).toContain("Fell back to camera moves on the keyframe: Shot 3 (timed out)");
  });

  // the backend's codes (spotlight/motion/models.py FALLBACK_REASONS), then the codes of an earlier revision, which older artifacts still carry
  const BACKEND_REASONS = ["oom", "timeout", "safety", "budget", "worker_unavailable", "bad_request", "internal", "disabled"];
  const EARLIER_REASONS = ["unavailable", "failed", "bad_clip"];
  const listed = (reasons: string[]) => plain(render(<SpotMotionDetails info={info({ shots_total: reasons.length, shots_generated: 0, shots_fallback: reasons.map((reason, i) => ({ shot_id: `s${i + 1}`, reason })) })} />));

  it("labels every backend reason code when only the code arrives, keeps the earlier codes readable, and shows a new code as received", () => {
    expect(listed(BACKEND_REASONS)).toContain(
      "Shot 1 (out of GPU memory), Shot 2 (timed out), Shot 3 (blocked by Content Safety), Shot 4 (budget limit), Shot 5 (GPU unavailable), Shot 6 (invalid request), Shot 7 (internal generation error), Shot 8 (AI motion turned off on the server)",
    );
    expect(listed(EARLIER_REASONS)).toContain("Shot 1 (GPU unavailable), Shot 2 (generation failed), Shot 3 (unreadable clip)");
    expect(listed(["quantum_flux", "internal"])).toContain("Shot 1 (quantum_flux), Shot 2 (internal generation error)");
  });

  it("Polish: the same labels; an unknown code is shown as received and is not a missing key", () => {
    setLang("pl");
    expect(flat(listed(BACKEND_REASONS))).toContain(
      "Ujęcie 1 (brak pamięci GPU), Ujęcie 2 (przekroczono czas), Ujęcie 3 (zablokowane przez Content Safety), Ujęcie 4 (limit budżetu), Ujęcie 5 (GPU niedostępne), Ujęcie 6 (nieprawidłowe żądanie), Ujęcie 7 (błąd wewnętrzny generowania), Ujęcie 8 (ruch AI wyłączony na serwerze)",
    );
    expect(flat(listed(EARLIER_REASONS))).toContain("Ujęcie 1 (GPU niedostępne), Ujęcie 2 (generowanie nie powiodło się), Ujęcie 3 (nieczytelny klip)");
    expect(flat(listed(["quantum_flux"]))).toContain("Ujęcie 1 (quantum_flux)");
    expect(missingKeys()).toEqual([]);
  });

  // the motion-quality gate: render.motion.shots[i].motion = { non_rigid, total, level, attempts }
  const gate = (level: string, over: object = {}) => ({ non_rigid: 2.66, total: 3.1, level, attempts: 1, ...over });
  const gated = [
    { shot_id: "s1", status: "generated", motion: gate("rich") },
    { shot_id: "s2", status: "cached", motion: gate("subtle", { non_rigid: 0.74, total: 0.9 }) },
    { shot_id: "s3", status: "generated", motion: gate("low", { non_rigid: 0.12, total: 0.2, attempts: 2 }) },
    { shot_id: "s4", status: "generated", motion: gate("rich", { non_rigid: 4.1, total: 4.6 }) },
  ];
  const levels = (html: string) => [...html.matchAll(/data-testid="motion-level" data-shot="(\d+)" data-level="(\w+)" data-attempts="(\d+)"/g)].map((m) => [Number(m[1]), m[2], Number(m[3])]);

  it("a level badge per measured clip — Rich, Subtle or Low motion — and no figures in the visible text", () => {
    const html = render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 1, retries: 1 })} />);
    expect(levels(html)).toEqual([[1, "rich", 1], [2, "subtle", 1], [3, "low", 2], [4, "rich", 1]]);
    const t = plain(html);
    expect(t).toContain("Shot 1 Rich motion");
    expect(t).toContain("Shot 2 Subtle motion");
    expect(t).toContain("Shot 3 Low motion");
    expect(t).toContain("Shot 4 Rich motion");
    expect(t).not.toMatch(/2\.66|0\.74|0\.12|4\.1\b|3\.1\b/); // the measurements live in the tooltips
    expect(html).toContain("bg-sage-100"); // rich: good
    expect(html).toContain("bg-sky-100"); // subtle: info
    expect(html).toContain("bg-dawn-300/40"); // low: warn
  });

  it("each badge carries its measurement against the value of a still with camera moves (2 decimals) in a tooltip", () => {
    const html = render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 1 })} />);
    expect(html).toContain('title="Non-rigid motion: 2.66 px per 0.4 s (a still with camera moves: ≈ 0.15)"');
    expect(html).toContain('title="Non-rigid motion: 0.74 px per 0.4 s (a still with camera moves: ≈ 0.15)"');
    expect(html).toContain('title="Non-rigid motion: 0.12 px per 0.4 s (a still with camera moves: ≈ 0.15)"');
    expect(html).toContain('title="Non-rigid motion: 4.10 px per 0.4 s (a still with camera moves: ≈ 0.15)"');
    const unmeasured = render(<SpotMotionDetails info={info({ shots: [{ shot_id: "s1", motion: gate("rich", { non_rigid: null, total: null }) }] })} />);
    expect(plain(unmeasured)).toContain("Shot 1 Rich motion");
    expect(unmeasured).not.toContain("Non-rigid motion");
  });

  it("says 'retried with another seed' next to the shots that needed a second attempt, and only those", () => {
    const html = render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 1, retries: 1 })} />);
    expect(plain(html)).toContain("Shot 3 Low motion (retried with another seed)");
    expect([...html.matchAll(/data-testid="motion-retried"/g)]).toHaveLength(1);
    const unknownRetried = render(<SpotMotionDetails info={info({ shots: [{ shot_id: "s1", motion: gate("unknown", { non_rigid: null, total: null }) }, { shot_id: "s2", motion: gate("unknown", { non_rigid: null, total: null, attempts: 2 }) }] })} />);
    expect(levels(unknownRetried)).toEqual([[2, "unknown", 2]]); // a clip that was not measured shows no badge, but a retry is still worth saying
    expect(plain(unknownRetried)).toContain("Shot 2 (retried with another seed)");
    expect(plain(unknownRetried)).not.toMatch(/motion\b.*motion/i);
  });

  it("the hint appears only when a clip stays almost still: one shot, several shots, none", () => {
    const one = plain(render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 1 })} />));
    expect(one).toContain("Shot 3 has little motion. Edit its motion prompt (Storyboard tab) and render again — only that shot is regenerated.");
    const two = [...gated.slice(0, 1), { shot_id: "s2", motion: gate("low", { non_rigid: 0.2 }) }, ...gated.slice(2)];
    expect(plain(render(<SpotMotionDetails info={info({ shots: two, shots_low_motion: 2 })} />))).toContain(
      "Shots 2 and 3 have little motion. Edit their motion prompts (Storyboard tab) and render again — only those shots are regenerated.",
    );
    const three = gated.map((s) => ({ ...s, motion: { ...s.motion, level: "low" } }));
    expect(plain(render(<SpotMotionDetails info={info({ shots: three, shots_low_motion: 4 })} />))).toContain("Shots 1, 2, 3, and 4 have little motion.");

    const rich = gated.filter((s) => s.motion.level !== "low");
    expect(render(<SpotMotionDetails info={info({ shots: rich, shots_low_motion: 0 })} />)).not.toContain('data-testid="motion-low-hint"');
    expect(render(<SpotMotionDetails info={info({ shots: rich })} />)).not.toContain('data-testid="motion-low-hint"'); // the count is derived from the shots when the report has none
    expect(render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 0 })} />)).not.toContain('data-testid="motion-low-hint"'); // the report's own count decides
  });

  it("the hint comes after the badges and before the fallbacks; fallback shots carry no badge", () => {
    const html = render(<SpotMotionDetails info={info({ shots_generated: 3, shots_fallback: [{ shot_id: "s4", reason: "timeout" }], shots: [...gated.slice(0, 3), { shot_id: "s4", status: "fallback" }], shots_low_motion: 1 })} />);
    const order = ['data-testid="motion-usage-line"', 'data-testid="motion-levels"', 'data-testid="motion-low-hint"', 'data-testid="motion-fallbacks"'].map((s) => html.indexOf(s));
    expect(order.every((i) => i > 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(levels(html).map(([shot]) => shot)).toEqual([1, 2, 3]);
  });

  it("a report from before the gate renders exactly as it did: no badges, no retry note, no hint", () => {
    const html = render(<SpotMotionDetails info={info({ shots_generated: 3, shots_fallback: [{ shot_id: "s4", reason: "timeout" }] })} />);
    expect(html).not.toContain('data-testid="motion-levels"');
    expect(html).not.toContain('data-testid="motion-low-hint"');
    expect(html).not.toContain("title=");
    expect(plain(html)).not.toMatch(/(Rich|Subtle|Low) motion|retried|little motion/);
    // the same report with the gate's entries but no `motion` object in them (a backend that has not got the gate yet)
    const plainShots = info({ shots: [{ shot_id: "s1", status: "generated" }, { shot_id: "s2", status: "cached" }] });
    expect(render(<SpotMotionDetails info={plainShots} />)).toBe(render(<SpotMotionDetails info={info()} />));
  });

  it("Polish: the badges, the retry note, the tooltip with decimal commas, and the hint in the singular and the plural", () => {
    setLang("pl");
    const html = render(<SpotMotionDetails info={info({ shots: gated, shots_low_motion: 1, retries: 1 })} />);
    const t = flat(plain(html));
    expect(t).toContain("Ujęcie 1 Dużo ruchu");
    expect(t).toContain("Ujęcie 2 Subtelny ruch");
    expect(t).toContain("Ujęcie 3 Mało ruchu (ponowiono z innym ziarnem)");
    expect(html).toContain(`title="Ruch niesztywny: 2,66${NB}px na 0,4${NB}s (ruch kamery na nieruchomej klatce: ≈ 0,15)"`);
    expect(html).toContain(`title="Ruch niesztywny: 4,10${NB}px na 0,4${NB}s`);
    expect(t).toContain("Ujęcie 3 ma mało ruchu. Zmień jego opis ruchu (zakładka Storyboard) i wyrenderuj ponownie — od nowa zostanie wygenerowane tylko to ujęcie.");
    const two = [...gated.slice(0, 1), { shot_id: "s2", motion: gate("low", { non_rigid: 0.2 }) }, ...gated.slice(2)];
    const plural = plain(render(<SpotMotionDetails info={info({ shots: two, shots_low_motion: 2 })} />));
    expect(plural).toContain(`Ujęcia 2 i${NB}3 mają mało ruchu.`); // the one-letter conjunction stays with the number after it
    expect(flat(plural)).toContain("Ujęcia 2 i 3 mają mało ruchu. Zmień ich opisy ruchu (zakładka Storyboard) i wyrenderuj ponownie — od nowa zostaną wygenerowane tylko te ujęcia.");
    expect(t).not.toMatch(/Rich motion|Subtle motion|Low motion|retried|little motion|Non-rigid/);
    expect(unresolved(t)).toEqual([]);
    expect(missingKeys()).toEqual([]);
  });

  it("Polish: chip with the right plural forms, model line, fallbacks — no missing keys", () => {
    setLang("pl");
    const forms = (n: number) => plain(render(<SpotMotionChip info={info({ shots_total: 8, shots_generated: 8 - n, shots_fallback: Array.from({ length: n }, (_, i) => ({ shot_id: `s${i + 1}`, reason: "" })) })} />));
    expect(plain(render(<SpotMotionChip info={info()} />))).toContain("Filmowy · ruch AI: 4/4 ujęć");
    expect(forms(1)).toContain("Filmowy · ruch AI: 7/8 ujęć · 1 ujęcie zastępcze");
    expect(forms(2)).toContain("2 ujęcia zastępcze");
    expect(forms(5)).toContain("5 ujęć zastępczych");
    const details = plain(render(<SpotMotionDetails info={info({ shots_generated: 3, shots_cached: 1, cold_start_usd: 0.2592, cost_usd: 0.6031, shots_fallback: [{ shot_id: "s3", reason: "timeout" }] })} />));
    expect(flat(details)).toContain("Model ruchu: wan2.2-ti2v-5b · licencja Apache-2.0 · uruchomiony na bezserwerowym GPU w Twoim środowisku Azure");
    expect(details).toContain(`Nowe klipy: 2 · użyto z${NB}pamięci podręcznej: 1 · Czas GPU: 318${NB}s · 0,60${NB}USD · w${NB}tym 0,26${NB}USD za uruchomienie GPU z${NB}uśpienia`);
    expect(flat(details)).toContain("Zamiast AI zastosowano ruch kamery na klatce kluczowej: Ujęcie 3 (przekroczono czas)");
    expect(unresolved(details)).toEqual([]);
    expect(missingKeys()).toEqual([]);
  });
});

describe("MotionPromptEditor", () => {
  const shot = { id: "s2", idx: 2, motion: { prompt_en: "She lifts the mug and sips.", prompt: "She lifts the mug and sips.", camera: "slow push-in" }, motion_stale: false };
  const editor = (s: object = shot) => render(<MotionPromptEditor campaignId="cmp_1" storyboardId="sb_1" shot={s as never} />);

  it("a labelled 300-character textarea next to the shot, with the opening-frame hint, a counter and a disabled Save", () => {
    const html = editor();
    const area = tag(html, "motion-prompt")!;
    expect(area).toMatch(/maxlength="300"/i); // React writes the attribute as maxLength; HTML attribute names are case-insensitive
    expect(html).toMatch(/<label for="([^"]+)"[^>]*>Motion · shot 2<\/label>/);
    const id = /<label for="([^"]+)"/.exec(html)![1];
    expect(area).toContain(`id="${id}"`);
    expect(area).toContain("aria-describedby=");
    expect(html).toContain(">She lifts the mug and sips.</textarea>");
    const t = plain(html);
    expect(t).toContain("The keyframe is the opening frame. Describe what moves after it: the subject, the camera, steam or light.");
    expect(t).toContain("27/300 characters");
    expect(button(html, "Save motion")).toContain('disabled=""');
    expect(html).not.toContain('data-testid="motion-prompt-en"');
  });

  it("an older storyboard has no motion yet: empty field with an example placeholder", () => {
    const html = editor({ id: "s1", idx: 1 });
    expect(tag(html, "motion-prompt")).toContain('placeholder="e.g. She lifts the mug and sips; slow push-in; steam drifts up."');
    expect(plain(html)).toContain("0/300 characters");
  });

  it("marks a shot whose motion was edited", () => {
    expect(plain(editor({ ...shot, motion_stale: true }))).toContain("motion prompt edited");
    expect(plain(editor())).not.toContain("motion prompt edited");
  });

  it("a non-English campaign shows the English prompt the model reads, flagged as English user content", () => {
    const html = editor({ ...shot, motion: { prompt: "Podnosi kubek i upija łyk.", prompt_en: "She lifts the mug and sips.", camera: "slow push-in" } });
    expect(html).toContain(">Podnosi kubek i upija łyk.</textarea>");
    expect(plain(html)).toContain("Model prompt (EN): She lifts the mug and sips.");
    expect(html).toMatch(/<span lang="en" data-user-content="true">She lifts the mug and sips\.<\/span>/);
  });

  it("Polish: label, hint, counter, placeholder, button", () => {
    setLang("pl");
    const html = editor({ id: "s2", idx: 2, motion_stale: true });
    const t = flat(plain(html));
    expect(t).toContain("Ruch · ujęcie 2");
    expect(t).toContain("Klatka kluczowa jest pierwszą klatką ujęcia. Opisz, co porusza się dalej: postać lub produkt, kamerę, parę albo światło.");
    expect(t).toContain("0/300 znaków");
    expect(t).toContain("opis ruchu zmieniony");
    expect(flat(tag(html, "motion-prompt")!)).toContain('placeholder="np. Podnosi kubek i upija łyk; powolny najazd kamery; unosi się para."');
    expect(button(html, "Zapisz ruch")).toBeDefined();
    expect(unresolved(t)).toEqual([]);
    expect(missingKeys()).toEqual([]);
  });
});

describe("RenderFailure", () => {
  it("a refused budget is a warning: the server's hint is shown, or a pointer to the cost meter when it sent none; any other failure is an error", () => {
    const budget = render(<RenderFailure failure={{ message: "Daily AI budget exceeded ($5.00).", hint: "An Admin can raise the cap.", code: "daily_budget_exceeded" }} onDismiss={() => undefined} />);
    expect(budget).toContain('role="alert"');
    expect(budget).toContain('data-kind="budget"');
    expect(plain(budget)).toContain("Render refused by the AI budget");
    expect(plain(budget)).toContain("Daily AI budget exceeded ($5.00).");
    expect(plain(budget)).toContain("An Admin can raise the cap.");
    expect(budget).not.toContain('href="/cost"'); // the hint already says what to do
    const noHint = render(<RenderFailure failure={{ message: "Campaign AI cap reached.", code: "campaign_budget_exceeded" }} onDismiss={() => undefined} />);
    expect(noHint).toContain('href="/cost"');
    expect(plain(noHint)).toContain("Choose Preview, or raise the cap on the cost meter (admin only).");
    const other = render(<RenderFailure failure={{ message: "Motion worker timed out.", code: "motion_timeout" }} onDismiss={() => undefined} />);
    expect(other).toContain('data-kind="error"');
    expect(plain(other)).toContain("Render failed");
    expect(other).not.toContain('href="/cost"');
  });

  it("can be dismissed with a labelled button; Polish", () => {
    setLang("pl");
    const html = render(<RenderFailure failure={{ message: "Przekroczono dzienny limit.", code: "daily_budget_exceeded" }} onDismiss={() => undefined} />);
    expect(html).toContain('aria-label="Zamknij"');
    expect(plain(html)).toContain("Render odrzucony przez limit budżetu AI");
    expect(missingKeys()).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------------------- the two workspace tabs
const CID = "cmp_1";
const SPOT = {
  id: "sp1",
  version: 2,
  title: "Dawn Roast — 15 s",
  aspect: "16:9",
  duration: 14.9,
  lang: "en",
  lineage_kind: "master",
  assets: { video: "a_video", srt: "a_srt", poster: "a_poster" },
  probe: { video: { codec: "h264", width: 1280, height: 720, fps: 25 }, audio: { codec: "aac" }, duration: 14.9, size_bytes: 3_400_000 },
  loudness: { integrated_lufs: -16.1, true_peak_dbfs: -1.4 },
  guardian: { verdict: "pass", score: 96 },
  provenance_id: "pv1",
  music: { title: "Warm Morning" },
};
const CAMPAIGN = { campaign: { id: CID }, artifacts: [{ id: "sb_1", kind: "storyboard" }, { id: "sc_1", kind: "script" }], recent_jobs: [] as object[] };

function client(entries: [unknown[], unknown][]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  for (const [key, data] of entries) qc.setQueryData(key, data);
  return qc;
}
const tab = (feature: { workspaceTabs?: { Component: (p: { campaign: object; reload: () => void }) => ReactElement | null }[] }, campaign: object, qc: QueryClient) => {
  const Tab = feature.workspaceTabs![0].Component;
  return render(
    <QueryClientProvider client={qc}>
      <Tab campaign={campaign} reload={() => undefined} />
    </QueryClientProvider>,
  );
};
const spots = (items: object[]) => ({ spots: items, provider: { kind: "keyframes+motion compositor", codec: "h264/aac" }, aspects: ["16:9"] });

describe("Video step (CS-08)", () => {
  const cinematicSpot = { ...SPOT, quality: "cinematic", render: { render_seconds: 41, motion: { ...MOTION, shots_generated: 3, shots_fallback: [{ shot_id: "s3", reason: "timeout" }] } } };
  const keys = (state: string) => [
    [["spots", CID], spots([cinematicSpot])],
    [["motion-status"], status({ worker: { state, age_s: 4, queue_depth: 0 } })],
    [["spot-estimate", CID, "16:9", "sb_1", state], estimate()],
  ] as [unknown[], unknown][];

  it("defaults to Cinematic when motion is available, shows the picker, the estimate and the chip + model line on the spot card", () => {
    const html = tab(spotFeature as never, CAMPAIGN, client(keys("cold")));
    const t = plain(html);
    expect(tag(html, "quality-cinematic")).toContain('checked=""');
    expect(t).toContain("GPU worker: cold");
    expect(t).toContain("Cinematic estimate");
    expect(button(html, "Render spot")).toBeDefined();
    expect(button(html, "Render spot")).not.toContain('disabled=""');
    expect(t).toContain("Cinematic · AI motion 3/4 shots · 1 fallback");
    expect(t).toContain("Motion model: wan2.2-ti2v-5b · licence Apache-2.0");
    expect(t).toContain("Download MP4");
    expect(t).toContain("Provider: keyframes+motion compositor · h264/aac");
    expect(t).not.toContain("Sora");
    expect(html).toContain('data-testid="video-player"');
    expect(html).toContain('data-testid="probe"');
    expect(html).not.toContain('data-testid="job-progress"');
  });

  it("falls back to Preview (Cinematic disabled with the reason) when the server cannot do motion; the existing controls are untouched", () => {
    const qc = client([[["spots", CID], spots([SPOT])], [["motion-status"], status({ mode: "off", available: false })]]);
    const html = tab(spotFeature as never, CAMPAIGN, qc);
    expect(tag(html, "quality-preview")).toContain('checked=""');
    expect(tag(html, "quality-cinematic")).toContain('disabled=""');
    expect(plain(html)).toContain("only Preview can be rendered");
    expect(html).not.toContain('data-testid="motion-chip"');
    expect(html).toMatch(/aria-label="aspect"/);
    expect(html).toMatch(/aria-label="loudness"/);
    expect(button(html, "Render spot")).toBeDefined();
  });

  it("the Render spot button is blocked while the estimate says the budget would be exceeded", () => {
    const refused = estimate({ budget: { allowed: false, daily_remaining_usd: 0, campaign_remaining_usd: 0, reason: "daily_budget_exceeded" } });
    const entries: [unknown[], unknown][] = [[["spots", CID], spots([SPOT])], [["motion-status"], workerState("ready")], [["spot-estimate", CID, "16:9", "sb_1", "ready"], refused]];
    const html = tab(spotFeature as never, CAMPAIGN, client(entries));
    expect(button(html, "Render spot")).toContain('disabled=""');
    expect(tag(html, "budget-refusal")).toBeDefined();
  });

  it("a render that is still running on the server (from the campaign's recent jobs) shows its progress again and blocks a second one", () => {
    const campaign = { ...CAMPAIGN, recent_jobs: [{ id: "job_7", kind: "spot.render", status: "running" }, { id: "job_6", kind: "spot.render", status: "succeeded" }, { id: "job_5", kind: "storyboard.frames", status: "running" }] };
    const html = tab(spotFeature as never, campaign, client(keys("ready")));
    expect(plain(html)).toContain("Connecting…");
    expect(button(html, "Render spot")).toContain('disabled=""');
    const idle = tab(spotFeature as never, { ...CAMPAIGN, recent_jobs: [{ id: "job_6", kind: "spot.render", status: "succeeded" }, { id: "job_5", kind: "storyboard.frames", status: "running" }] }, client(keys("ready")));
    expect(plain(idle)).not.toContain("Connecting…");
    expect(button(idle, "Render spot")).not.toContain('disabled=""');
  });

  it("Versions list marks the Cinematic versions", () => {
    const html = tab(spotFeature as never, CAMPAIGN, client([...keys("ready"), [["spots", CID], spots([cinematicSpot, { ...SPOT, id: "sp0", version: 1, quality: "preview" }])]]));
    const versions = html.slice(html.indexOf("Versions"));
    expect([...versions.matchAll(/>Cinematic</g)]).toHaveLength(1);
  });

  it("an older spot (no quality, no motion summary) renders as before: no chip, no model line", () => {
    const html = tab(spotFeature as never, CAMPAIGN, client([[["spots", CID], spots([SPOT])], [["motion-status"], status({ mode: "off", available: false })]]));
    expect(html).not.toContain('data-testid="motion-chip"');
    expect(html).not.toContain('data-testid="motion-details"');
    expect(html).toContain('data-testid="video-player"');
  });

  it("Polish: the whole step has no English, no raw placeholders and no missing keys", () => {
    setLang("pl");
    const html = tab(spotFeature as never, CAMPAIGN, client(keys("cold")));
    const t = plain(html);
    expect(unresolved(t)).toEqual([]);
    expect(t).toContain("Dwa tryby renderu");
    expect(t).toContain("Tryb renderu");
    expect(t).toContain("Renderuj spot");
    expect(t).toContain("Filmowy · ruch AI: 3/4 ujęć · 1 ujęcie zastępcze");
    expect(t).toContain("Dostawca: ");
    expect(t).not.toMatch(/Render quality|Cinematic|Sora/);
    expect(missingKeys()).toEqual([]);
  });
});

describe("Provenance step (CS-14): the generative_video assertion", () => {
  const manifest = (assertions: object) => ({
    manifest_hash: "ab".repeat(32),
    signature: { alg: "Ed25519", key_id: "k1" },
    sidecar_url: "/api/provenance/assets/vid_1/sidecar",
    verification: { ok: true, checks: [] },
    manifest: { manifest_version: "1.0", title: "Dawn Roast", asset: { sha256: "cd".repeat(32) }, claim_generator: "Spotlight", notice: "", audit_anchor: { chain: "c1", seq: 5 }, assertions },
  });
  const base = { ai_disclosure: { ai_generated: true }, models: [{ deployment: "gpt-image-1.5" }], ingredients: [{}, {}, {}], actions: [{}], approvals: [], rights: [] };
  const tabHtml = (assertions: object) =>
    tab(
      provenanceFeature as never,
      { campaign: { id: CID, markets: ["US"], channels: [] } },
      client([
        [["prov-sum", CID], { coverage: 100, signer: "demo", assets: [{ asset_id: "vid_1", kind: "video", name: "spot.mp4", has_manifest: true }] }],
        [["manifest", "vid_1"], manifest(assertions)],
        [["prov-labels", "US", ""], { jurisdictions: [], platforms: [], badge_text: "AI", burn_in_required: true, metadata: [], notice: "" }],
      ]),
    );

  it("a cinematic spot's manifest shows the model, licence and how many shots carry AI motion; AI clips count as ingredients", () => {
    const t = plain(tabHtml({ ...base, models: [{ deployment: "gpt-image-1.5" }, { deployment: "wan2.2-ti2v-5b" }], generative_video: { model: "wan2.2-ti2v-5b", license: "Apache-2.0", shots: [{}, {}, {}], shots_total: 4 } }));
    expect(t).toContain("Generative video");
    expect(t).toContain("wan2.2-ti2v-5b · licence Apache-2.0 · 3/4 shots with AI motion");
    expect(t).toContain("3 hashed (keyframes, AI clips, voice-over)");
  });

  it("a preview spot's manifest is unchanged", () => {
    const t = plain(tabHtml(base));
    expect(t).not.toContain("Generative video");
    expect(t).toContain("3 hashed (keyframes, voice-over)");
  });

  it("Polish", () => {
    setLang("pl");
    const t = flat(plain(tabHtml({ ...base, generative_video: { model: "wan2.2-ti2v-5b", license: "Apache-2.0", shots: [{}, {}], shots_total: 4 } })));
    expect(t).toContain("Wideo generatywne");
    expect(t).toContain("wan2.2-ti2v-5b · licencja Apache-2.0 · 2/4 ujęć z ruchem AI");
    expect(t).toContain("skróty: 3 (klatki kluczowe, klipy AI, lektor)");
    expect(unresolved(t)).toEqual([]);
    expect(missingKeys()).toEqual([]);
  });
});

describe("Storyboard step (CS-07)", () => {
  const sb = {
    id: "sb_1",
    title: "Storyboard — 15 s",
    guardian: { verdict: "pass", score: 95 },
    style_bible: { look: "Warm editorial photography" },
    shots: [
      { id: "s1", idx: 1, role: "hook", duration: 3.4, description: "A hand reaches for the mug.", framing: "wide establishing shot", movement: "zoom_in", asset_id: "a1", image_status: "ready", cost_usd: 0.013, motion: { prompt_en: "Steam rises; slow push-in.", prompt: "Steam rises; slow push-in.", camera: "slow push-in" }, motion_stale: true },
      { id: "s2", idx: 2, role: "product", duration: 4.2, description: "Close-up of the bag.", framing: "macro", movement: "pan_right", asset_id: "a2", image_status: "ready", cost_usd: 0.013 },
    ],
  };
  const render1 = () => tab(storyboardFeature as never, CAMPAIGN, client([[["storyboard", CID], { latest: sb, versions: [] }]]));

  it("every shot card gets a Motion editor next to its description; keyframes and the existing controls are unchanged", () => {
    const html = render1();
    expect([...html.matchAll(/data-testid="motion-editor-(s\d)"/g)].map((m) => m[1])).toEqual(["s1", "s2"]);
    expect(html).toContain(">Steam rises; slow push-in.</textarea>");
    expect(plain(html)).toContain("motion prompt edited");
    expect(plain(html)).toContain("Motion · shot 1");
    expect(plain(html)).toContain("Motion · shot 2");
    expect([...html.matchAll(/<img\b/g)]).toHaveLength(2); // the editor adds no images: the E2E counts the keyframes inside [data-testid=shots]
    expect(button(html, "Rebuild shot list")).toBeDefined();
    expect(button(html, "Generate keyframes")).toBeDefined();
    expect(html).toContain('data-testid="shots"');
    expect(plain(html)).toContain("2/2 keyframes");
  });

  it("Polish: no English, no raw placeholders, no missing keys", () => {
    setLang("pl");
    const t = plain(render1());
    expect(t).toContain("Ruch · ujęcie 1");
    expect(t).toContain("Zapisz ruch");
    expect(unresolved(t)).toEqual([]);
    expect(missingKeys()).toEqual([]);
  });
});
