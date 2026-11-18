// Throwaway local mock of the Studio API for the motion UI (NOT part of the product; deleted after the check).
import http from "node:http";

const PORT = Number(process.env.MOCK_PORT ?? 8199);
const S = {
  mode: "azure",
  available: true,
  worker: "cold",
  budget: "ok", // ok | refuse
  rendered: false,
  jobStart: 0,
  warmups: 0,
  posts: [],
  patches: [],
  statusCalls: 0,
};

const keyframe = (n) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${["#e9892b", "#5c7a5e", "#b5452b", "#3d2a1f"][n % 4]}"/><stop offset="1" stop-color="#f7f0e6"/></linearGradient></defs><rect width="600" height="400" fill="url(#g)"/><text x="40" y="220" font-size="64" fill="#fff" font-family="sans-serif">Shot ${n}</text></svg>`;

const shots = (cinematic) =>
  [1, 2, 3, 4].map((i) => ({
    id: `s${i}`,
    idx: i,
    beat_id: `b${i}`,
    role: ["hook", "product", "proof", "cta"][i - 1],
    duration: [3.4, 4.2, 3.6, 3.7][i - 1],
    description: ["A hand reaches for a steaming mug at dawn.", "Close-up of the kraft bag with the amber sun mark.", "Coffee pours in a slow macro stream.", "Maya smiles, mug in hand, warm light on her face."][i - 1],
    framing: ["wide establishing shot", "medium close-up", "macro close-up with shallow depth of field", "medium shot"][i - 1],
    movement: ["zoom_in", "pan_right", "parallax", "pan_left"][i - 1],
    super_text: i === 4 ? "Wake up slowly." : null,
    asset_id: `img${i}`,
    image_status: "ready",
    cost_usd: 0.013,
    ...(cinematic || i < 3
      ? { motion: { prompt_en: ["She lifts the mug and sips; slow push-in; steam drifts up.", "Steam rises beside the bag while the product stays still.", "", ""][i - 1], prompt: ["Podnosi kubek i upija łyk; powolny najazd kamery; unosi się para.", "Para unosi się obok torby, a produkt pozostaje nieruchomy.", "", ""][i - 1], camera: "slow push-in" } }
      : {}),
    ...(i === 2 ? { motion_stale: true } : {}),
  }));

const spot = (id, version, cinematic) => ({
  id,
  version,
  status: "draft",
  title: "Dawn Roast — 15 s",
  created_at: "2026-11-18T12:00:00Z",
  assets: { video: "vid1", srt: "srt1", poster: "img1" },
  probe: { video: { codec: "h264", width: 1280, height: 720, fps: 25 }, audio: { codec: "aac" }, duration: 14.92, size_bytes: 3512345 },
  loudness: { integrated_lufs: -16.1, true_peak_dbfs: -1.4 },
  guardian: { verdict: "pass", score: 96, blocks: 0 },
  lineage_kind: "master",
  provenance_id: "pv1",
  needs_rerender: false,
  markets: ["US"],
  duration: 14.92,
  lang: "en",
  aspect: "16:9",
  music: { title: "Warm Morning" },
  ...(cinematic
    ? { quality: "cinematic", render: { render_seconds: 41, motion: { mode: "azure", model: "wan2.2-ti2v-5b", license: "Apache-2.0", shots_total: 4, shots_generated: 3, shots_cached: 1, shots_fallback: [{ shot_id: "s3", reason: "timeout", detail: "no answer", reason_text: process.env.MOCK_LANG === "pl" ? "serwer GPU nie odpowiedział na czas" : "the GPU worker did not answer in time" }], gpu_seconds: 164.1, cost_usd: 0.4349, cold_start_s: 240, cold_start_usd: 0.2592, seed_base: 4242 } } }
    : { quality: "preview", render: { render_seconds: 12 } }),
});

const json = (res, body, status = 200) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

const jobDoc = (elapsed) => {
  const steps = [
    [0, 0.05, "Estimating GPU time…", "render"],
    [2, 0.12, "Warming up the GPU — about 4 min…", "motion"],
    [4, 0.3, "Generating AI motion — shot 1 of 4", "motion-s1"],
    [6, 0.5, "Generating AI motion — shot 2 of 4", "motion-s2"],
    [8, 0.7, "Reused 1 clip from the cache · shot 3 falls back to camera moves", "motion-s3"],
    [10, 0.9, "Compositing the spot…", "guardian"],
  ];
  const cur = [...steps].reverse().find((s) => elapsed >= s[0]) ?? steps[0];
  if (S.jobFail && elapsed >= 3) {
    return {
      id: "job_1",
      kind: "spot.render",
      title: "Rendering spot (16:9, cinematic)",
      status: "failed",
      progress: 0.12,
      message: "Campaign AI cap reached: $1.98 of $2.00 spent on this campaign; this render call (~$0.3) would exceed it.",
      error: "Campaign AI cap reached: $1.98 of $2.00 spent on this campaign; this render call (~$0.3) would exceed it.",
      error_code: "campaign_budget_exceeded",
      error_hint: "A Brand Manager can raise the campaign cap in the Cost Meter.",
      steps: [{ name: "render" }],
      result: null,
    };
  }
  const done = elapsed >= 12;
  if (done) S.rendered = true;
  return {
    id: "job_1",
    kind: "spot.render",
    title: "Rendering spot (16:9, cinematic)",
    status: done ? "succeeded" : "running",
    progress: done ? 1 : cur[1],
    message: done ? "Done" : cur[2],
    steps: steps.filter((s) => elapsed >= s[0]).map((s) => ({ name: s[3] })),
    result: done ? { artifact_id: "sp2" } : null,
  };
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const p = url.pathname;
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    if (req.method !== "GET") S.posts.push({ method: req.method, path: p, body: body ? JSON.parse(body) : null, lang: req.headers["x-ui-lang"] });
    if (p === "/__mock/state") return json(res, S);
    if (p === "/__mock/set") {
      Object.assign(S, JSON.parse(body || "{}"));
      return json(res, S);
    }
    if (p === "/api/meta") return json(res, { mode: "azure", region: "swedencentral", version: "1.1.0" });
    if (p === "/api/usage") return json(res, { budget: { spent_today_usd: 0.42, daily_cap_usd: 5 } });
    if (p === "/api/motion/status") {
      S.statusCalls++;
      return json(res, { mode: S.mode, available: S.available, model: "wan2.2-ti2v-5b", license: "Apache-2.0", worker: { state: S.worker, age_s: S.worker === "ready" ? 7 : null, queue_depth: S.worker === "warming" ? 1 : 0 }, price_per_gpu_second: 0.00108, est_cold_start_s: 240, max_clip_s: 5.0 });
    }
    if (p === "/api/motion/warmup" && req.method === "POST") {
      S.warmups++;
      const wasCold = S.worker === "cold";
      if (wasCold) {
        S.worker = "warming";
        setTimeout(() => (S.worker = "ready"), Number(process.env.MOCK_WARM_MS ?? 6000));
      }
      return json(res, { mode: S.mode, available: S.available, model: "wan2.2-ti2v-5b", license: "Apache-2.0", worker: { state: S.worker, age_s: null, queue_depth: wasCold ? 1 : 0 }, price_per_gpu_second: 0.00108, est_cold_start_s: 240, max_clip_s: 5.0, reason: null, warmup: { requested: wasCold, est_cost_usd: wasCold ? 0.2592 : 0, est_seconds: wasCold ? 240 : 0 } }, 202);
    }
    if (p === "/api/campaigns/cmp_1/storyboard/sb_1/frames" && req.method === "POST") {
      S.framesStart = Date.now();
      return json(res, { id: "job_f", kind: "storyboard.frames", status: "queued", progress: 0, message: "Queued", title: "Generating keyframes", steps: [] });
    }
    if (p === "/api/stream/jobs/job_f") {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      const frames = () => {
        const done = Date.now() - S.framesStart > 2000;
        return { id: "job_f", kind: "storyboard.frames", status: done ? "succeeded" : "running", progress: done ? 1 : 0.4, message: done ? "Done" : "Generating keyframes", title: "Generating keyframes", steps: [], result: done ? { frames: 4 } : null };
      };
      const t = setInterval(() => {
        const j = frames();
        res.write(`event: ${j.status === "running" ? "progress" : "done"}\ndata: ${JSON.stringify(j)}\n\n`);
        if (j.status !== "running") {
          clearInterval(t);
          res.end();
        }
      }, 500);
      res.on("close", () => clearInterval(t));
      return;
    }
    if (p === "/api/campaigns/cmp_1/spot/estimate") {
      const cold = S.worker !== "ready";
      const refuse = S.budget === "refuse";
      const rowCost = (i) => (S.rendered && i === 1 ? 0 : 0.0804);
      const rows = [1, 2, 3, 4].map((i) => rowCost(i)).reduce((a, b) => a + b, 0);
      const coldCost = cold ? 0.2592 : 0;
      return json(res, {
        quality: url.searchParams.get("quality"),
        aspect: url.searchParams.get("aspect"),
        shots: [1, 2, 3, 4].map((i) => ({ shot_id: `s${i}`, seconds: [3.4, 4.2, 3.6, 3.7][i - 1], frames: 93, cached: i === 1 && S.rendered, est_gpu_seconds: S.rendered && i === 1 ? 0 : 74.4, est_cost_usd: rowCost(i) })),
        cached_shots: S.rendered ? 1 : 0,
        est_gpu_seconds: (S.rendered ? 223.2 : 297.6) + (cold ? 240 : 0),
        est_cost_usd: Math.round((rows + coldCost) * 1e5) / 1e5,
        est_wall_seconds: (cold ? 240 : 0) + 360,
        cold_start_seconds: cold ? 240 : 0,
        cold_start_cost_usd: coldCost,
        budget: refuse ? { allowed: false, daily_remaining_usd: 0.04, campaign_remaining_usd: 1.74, reason: "The estimated $0.58 exceeds the remaining AI budget for today ($0.04)." } : { allowed: true, daily_remaining_usd: 4.58, campaign_remaining_usd: 1.74, reason: null },
      });
    }
    if (p === "/api/campaigns/cmp_1/spot" && req.method === "GET") {
      const slim = (s) => (S.slim ? Object.fromEntries(Object.entries(s).filter(([k]) => k !== "quality" && k !== "render")) : s);
      const spots = (S.rendered ? [spot("sp2", 2, true), spot("sp1", 1, false)] : [spot("sp1", 1, false)]).map(slim);
      return json(res, { spots, provider: { kind: "keyframes+motion compositor", codec: "h264/aac" }, aspects: ["16:9", "9:16", "1:1", "4:5"] });
    }
    const detail = /^\/api\/campaigns\/cmp_1\/spot\/(sp\d)$/.exec(p);
    if (detail && req.method === "GET") {
      S.detailCalls = (S.detailCalls ?? 0) + 1;
      return json(res, spot(detail[1], detail[1] === "sp2" ? 2 : 1, detail[1] === "sp2"));
    }
    if (p === "/api/campaigns/cmp_1/spot/render" && req.method === "POST") {
      if (S.budget !== "ok") return json(res, { error: { code: "daily_budget_exceeded", message: "The daily AI budget ($5.00) would be exceeded.", hint: "Raise the cap on the cost meter or choose Preview." } }, 402);
      S.jobStart = Date.now();
      return json(res, jobDoc(0));
    }
    if (p.startsWith("/api/stream/jobs/")) {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      const tick = () => {
        const j = jobDoc((Date.now() - S.jobStart) / 1000);
        res.write(`event: ${j.status === "running" ? "progress" : "done"}\ndata: ${JSON.stringify(j)}\n\n`);
        if (j.status !== "running") {
          clearInterval(t);
          res.end();
        }
      };
      const t = setInterval(tick, 700);
      tick();
      res.on("close", () => clearInterval(t));
      return;
    }
    if (p.startsWith("/api/jobs/")) return json(res, jobDoc((Date.now() - S.jobStart) / 1000));
    if (p === "/api/campaigns/cmp_1/storyboard") return json(res, { latest: { id: "sb_1", title: "Storyboard — 15 s", status: "draft", guardian: { verdict: "pass", score: 95 }, style_bible: { look: "Warm, low-contrast editorial photography", lighting: "Low, warm sunrise light" }, shots: shots(false) }, versions: [] });
    const m = /^\/api\/campaigns\/cmp_1\/storyboard\/sb_1\/shots\/(s\d)$/.exec(p);
    if (m && req.method === "PATCH") {
      S.patches.push({ shot: m[1], body: JSON.parse(body) });
      return json(res, { id: m[1], motion: { prompt: JSON.parse(body).motion, prompt_en: JSON.parse(body).motion }, motion_stale: true });
    }
    if (p === "/api/campaigns/cmp_1") {
      return json(res, {
        campaign: { id: "cmp_1", name: "Dawn Roast — Launch", status: "in_progress", language: process.env.MOCK_LANG ?? "en", markets: ["US", "DE"], channels: ["youtube", "meta"], budget_cap_usd: 2 },
        pipeline: ["brief", "concept", "script", "storyboard", "final"].map((g) => ({ gate: g, label: g, approval_state: null, artifact_status: "draft", guardian: { verdict: "pass" } })),
        summary: { ai_spend_usd: 0.31 },
        recent_jobs: S.jobStart && !S.rendered ? [jobDoc((Date.now() - S.jobStart) / 1000)] : [],
        artifacts: [{ id: "sp1", kind: "spot" }, { id: "sb_1", kind: "storyboard" }, { id: "sc_1", kind: "script" }],
      });
    }
    if (p.startsWith("/api/library/assets/")) {
      const n = Number(/img(\d)/.exec(p)?.[1] ?? 1);
      res.writeHead(200, { "content-type": "image/svg+xml" });
      return res.end(keyframe(n));
    }
    json(res, { error: { code: "not_found", message: `mock: ${p}` } }, 404);
  });
});
server.listen(PORT, "127.0.0.1", () => console.log(`mock api on ${PORT}`));
