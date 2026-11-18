// Throwaway CDP driver (NOT part of the product; deleted after the check): drives the local headless Chromium against the local Vite dev server + mock API.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const WEB = process.env.WEB ?? "http://127.0.0.1:5199";
const MOCK = process.env.MOCK ?? "http://127.0.0.1:8199";
const CHROME = path.join(os.homedir(), "Library/Caches/ms-playwright/chromium_headless_shell-1254/chrome-headless-shell-mac-arm64/chrome-headless-shell");
const OUT = path.resolve(".scratch/out");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(...a);

// make sure a previous (still shutting down) browser no longer holds the debugging port
for (let i = 0; i < 40; i++) {
  try {
    await fetch("http://127.0.0.1:9333/json/version");
    await sleep(250);
  } catch {
    break;
  }
}

const chrome = spawn(CHROME, ["--remote-debugging-port=9333", `--user-data-dir=${path.resolve(".scratch/profile")}`, "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run", "about:blank"], { stdio: "ignore" });
const stop = () => {
  try {
    chrome.kill("SIGTERM");
  } catch {}
};
process.on("exit", stop);

async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const targets = await (await fetch("http://127.0.0.1:9333/json")).json();
      const page = targets.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(200);
  }
  throw new Error("no CDP page");
}

const wsUrl = await connect();
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pending = new Map();
const consoleLog = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m);
    pending.delete(m.id);
  } else if (m.method === "Runtime.consoleAPICalled") consoleLog.push(`${m.params.type}: ${m.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  else if (m.method === "Runtime.exceptionThrown") consoleLog.push(`EXCEPTION: ${m.params.exceptionDetails.text} ${m.params.exceptionDetails.exception?.description ?? ""}`);
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const i = ++id;
    pending.set(i, (m) => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
    ws.send(JSON.stringify({ id: i, method, params }));
  });
const ev = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
  return r.result.value;
};
const waitFor = async (expr, timeout = 15000, what = expr) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try {
      if (await ev(expr)) return true;
    } catch {}
    await sleep(150);
  }
  throw new Error(`timeout waiting for: ${what}`);
};
const viewport = (w, h) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
const shot = async (name) => {
  const r = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(path.join(OUT, `${name}.png`), Buffer.from(r.data, "base64"));
  log(`  screenshot ${name}.png`);
};
const nav = async (url) => {
  await send("Page.navigate", { url });
  await sleep(300);
  await waitFor("document.readyState === 'complete'", 20000, "load");
};
const mock = async (patch) => (await fetch(`${MOCK}/__mock/set`, { method: "POST", body: JSON.stringify(patch) })).json();
const state = async () => (await fetch(`${MOCK}/__mock/state`)).json();
const q = (sel) => `document.querySelector(${JSON.stringify(sel)})`;
const text = (sel) => ev(`(${q(sel)}?.innerText ?? null)`);
const click = (sel) => ev(`(${q(sel)}.click(), true)`);
const clickButton = (name) => ev(`(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === ${JSON.stringify(name)}); if (!b) throw new Error('no button ' + ${JSON.stringify(name)}); b.click(); return true; })()`);
const overflow = () => ev(`({ docX: document.documentElement.scrollWidth - document.documentElement.clientWidth, mainX: (document.querySelector('main')?.scrollWidth ?? 0) - (document.querySelector('main')?.clientWidth ?? 0), missing: (window.__i18nMissing ?? []).map((m) => m.kind + ':' + m.key) })`);
// the E2E's own "no loading state in a capture" probe (app/e2e/journeys.py SETTLE_JS): '' = the page is settled
const settleReason = () =>
  ev(`(() => {
    const inView = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; };
    if (document.querySelector('.skeleton')) return 'skeleton';
    if (document.querySelector('[aria-label="loading"]')) return 'spinner';
    if (/(Loading|Connecting)…/.test(document.body.innerText)) return 'loading text';
    if (document.querySelector('[aria-live="polite"]')?.children.length) return 'toast';
    for (const i of document.images) if (inView(i) && !(i.complete && i.naturalWidth > 0)) return 'image ' + i.src.slice(-48);
    return '';
  })()`);

await send("Page.enable");
await send("Runtime.enable");
await viewport(1600, 1500);

const results = [];
const scenario = async (name, fn) => {
  log(`\n# ${name}`);
  try {
    await fn();
    results.push([name, "ok"]);
  } catch (e) {
    log(`  FAILED: ${e.message}`);
    results.push([name, `FAILED: ${e.message}`]);
  }
};

const only = process.argv.slice(2);
const run = (name, fn) => (only.length === 0 || only.some((o) => name.startsWith(o)) ? scenario(name, fn) : null);

await run("1 EN video tab, GPU cold", async () => {
  await mock({ mode: "azure", available: true, worker: "cold", budget: "ok", rendered: false, jobStart: 0 });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  await sleep(600);
  log("  cinematic checked:", await ev(`${q("[data-testid=quality-cinematic]")}.checked`));
  log("  gpu badge:", await text("[data-testid=gpu-status]"));
  log("  tile:", (await text("[data-testid=quality-cinematic]")) ?? "(radio has no text)", "|", await ev(`${q("[data-testid=quality-cinematic]")}.closest('label').innerText.replace(/\\n/g,' / ')`));
  log("  overflow:", JSON.stringify(await overflow()));
  await shot("01-en-cold");
});

await run("2 warm up → warming → ready via polling", async () => {
  const before = (await state()).statusCalls;
  await clickButton("Warm up GPU");
  await waitFor(`${q("[data-testid=gpu-status]")}?.dataset.workerState === 'warming'`, 5000, "warming badge after the click");
  log("  warm-ups posted:", (await state()).warmups, "| badge:", await text("[data-testid=gpu-status]"));
  await sleep(500);
  log("  E2E settle probe while the GPU is warming:", JSON.stringify(await settleReason()), "(a toast from the click may still be fading: re-probed below)");
  await sleep(5200);
  log("  E2E settle probe a few seconds later (toast gone):", JSON.stringify(await settleReason()), "| badge:", (await text("[data-testid=gpu-status]"))?.replace(/\n/g, " | "));
  await shot("02-en-warming");
  const t0 = Date.now();
  await waitFor(`${q("[data-testid=gpu-status]")}?.dataset.workerState === 'ready'`, 25000, "ready badge via polling");
  log(`  became ready after ${((Date.now() - t0) / 1000).toFixed(1)} s (polling every 10 s) | status calls so far: ${(await state()).statusCalls - before}`);
  await sleep(800);
  log("  warm button disabled:", await ev(`${q("[data-testid=warm-gpu]")}.disabled`), "| cold note present:", await ev(`!!${q("[data-testid=cold-start-note]")}`));
  log("  tile:", await ev(`${q("[data-testid=quality-cinematic]")}.closest('label').innerText.replace(/\\n/g,' / ')`));
  await shot("03-en-ready");
});

await run("3 polling stops when the step is left", async () => {
  await nav(`${WEB}/campaigns/cmp_1/script?lang=en`);
  await sleep(1500);
  const a = (await state()).statusCalls;
  await sleep(11500);
  const b = (await state()).statusCalls;
  log(`  status calls while on another tab for 11.5 s: ${b - a}`);
  if (b - a !== 0) throw new Error("status is still polled outside the Video step");
});

await run("4 PL video tab", async () => {
  await mock({ worker: "cold", rendered: false, budget: "ok" });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=pl`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  await sleep(600);
  log("  badge:", await text("[data-testid=gpu-status]"));
  log("  tile:", await ev(`${q("[data-testid=quality-cinematic]")}.closest('label').innerText.replace(/\\n/g,' / ')`));
  log("  overflow:", JSON.stringify(await overflow()));
  await shot("04-pl-cold");
});

await run("5 render (PL) → job progress → chip", async () => {
  await mock({ worker: "ready", rendered: false, budget: "ok" });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=pl`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  await clickButton("Renderuj spot");
  await waitFor(`!!${q("[data-testid=job-progress]")}`, 8000, "job progress card");
  await sleep(5500);
  log("  progress text:", (await text("[data-testid=job-progress]"))?.replace(/\n/g, " | "));
  log("  body sent:", JSON.stringify((await state()).posts.filter((p) => p.path.endsWith("/spot/render")).at(-1)?.body));
  await shot("05-pl-progress");
  await waitFor(`!${q("[data-testid=job-progress]")}`, 20000, "job finished");
  await waitFor(`!!${q("[data-testid=motion-chip]")}`, 8000, "chip");
  await sleep(800);
  log("  chip:", await text("[data-testid=motion-chip]"));
  log("  details:", (await text("[data-testid=motion-details]"))?.replace(/\n/g, " | "));
  log("  overflow:", JSON.stringify(await overflow()));
  await shot("06-pl-done");
  await viewport(1600, 900);
  await ev(`document.querySelector('[data-testid=motion-details]').scrollIntoView({ block: 'end' })`);
  await sleep(500);
  await shot("06b-pl-spot-card");
  await viewport(1600, 1500);
});

await run("6 EN: reopening the step shows a render that is still running", async () => {
  await mock({ worker: "ready", rendered: false, budget: "ok", jobStart: Date.now() });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=job-progress]")}`, 15000, "resumed job progress");
  log("  resumed card:", (await text("[data-testid=job-progress]"))?.replace(/\n/g, " | "));
  log("  render button disabled:", await ev(`[...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Render spot').disabled`));
  await waitFor(`!${q("[data-testid=job-progress]")}`, 20000, "resumed job finished");
  await waitFor(`!!${q("[data-testid=motion-chip]")}`, 8000, "chip after the resumed job");
  log("  chip:", await text("[data-testid=motion-chip]"));
});

await run("7 budget refusal: estimate (blocked button) and a late 402 (inline alert)", async () => {
  await mock({ worker: "ready", rendered: false, budget: "refuse", jobStart: 0 });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=budget-refusal]")}`, 20000, "budget refusal in the estimate");
  log("  refusal:", (await text("[data-testid=budget-refusal]"))?.replace(/\n/g, " | "));
  log("  render button disabled:", await ev(`[...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Render spot').disabled`));
  await shot("07-en-refused");
  await mock({ budget: "late" });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate");
  await clickButton("Render spot");
  await waitFor(`!!${q("[data-testid=render-failure]")}`, 8000, "inline failure");
  log("  inline alert:", (await text("[data-testid=render-failure]"))?.replace(/\n/g, " | "));
  await shot("08-en-failure");
});

await run("8 server without motion", async () => {
  await mock({ mode: "off", available: false, worker: "cold", budget: "ok" });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=cinematic-unavailable]")}`, 15000, "unavailable reason");
  log("  reason:", await text("[data-testid=cinematic-unavailable]"));
  log("  cinematic disabled:", await ev(`${q("[data-testid=quality-cinematic]")}.disabled`), "| preview checked:", await ev(`${q("[data-testid=quality-preview]")}.checked`));
  await shot("09-en-off");
  await mock({ mode: "azure", available: true });
});

await run("10 language switch in place + explicit Preview", async () => {
  await mock({ mode: "azure", available: true, worker: "ready", budget: "ok", rendered: false, jobStart: 0 });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  const select = (value) => ev(`(() => { const s = document.querySelector('[data-testid=lang-switcher]'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, ${JSON.stringify(value)}); s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await select("pl");
  await waitFor(`document.querySelector('[data-testid=render-quality] legend')?.innerText.trim().toUpperCase() === 'TRYB RENDERU'`, 8000, "Polish legend after the switch");
  await waitFor(`!!${q("[data-testid=motion-estimate]")} && document.querySelector('[data-testid=motion-estimate]').innerText.includes('Szacunek')`, 8000, "Polish estimate");
  log("  after switch to pl:", (await text("[data-testid=gpu-status]"))?.replace(/\n/g, " | "), "| missing:", JSON.stringify((await overflow()).missing), "| estimate requests carried pl:", JSON.stringify(await ev(`performance.getEntriesByType('resource').filter((r) => r.name.includes('/spot/estimate')).length`)));
  await select("en");
  await waitFor(`document.querySelector('[data-testid=render-quality] legend')?.innerText.trim().toUpperCase() === 'RENDER QUALITY'`, 8000, "English legend after switching back");
  log("  back in English:", await text("[data-testid=gpu-status]"), "| missing:", JSON.stringify((await overflow()).missing));
  // an explicit Preview choice hides the estimate and is what the render request carries
  await ev(`${q("[data-testid=quality-preview]")}.click()`);
  await sleep(300);
  log("  estimate visible after choosing Preview:", await ev(`!!${q("[data-testid=motion-estimate]")}`), "| preview checked:", await ev(`${q("[data-testid=quality-preview]")}.checked`));
  await clickButton("Render spot");
  await sleep(600);
  log("  body sent:", JSON.stringify((await state()).posts.filter((p) => p.path.endsWith("/spot/render")).at(-1)?.body));
  // keyboard: arrow keys move the radio selection natively
  await ev(`${q("[data-testid=quality-preview]")}.focus()`);
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
  await sleep(300);
  log("  after ArrowRight → cinematic checked:", await ev(`${q("[data-testid=quality-cinematic]")}.checked`), "| estimate visible:", await ev(`!!${q("[data-testid=motion-estimate]")}`));
  await mock({ jobStart: 0, rendered: false });
});

await run("11 older spot list without quality/render → the artifact is requested once", async () => {
  await mock({ mode: "azure", available: true, worker: "ready", budget: "ok", rendered: true, jobStart: 0, slim: true, detailCalls: 0, jobFail: false });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-chip]")}`, 15000, "chip from the artifact");
  log("  chip:", await text("[data-testid=motion-chip]"), "| artifact requests:", (await state()).detailCalls);
  await ev(`[...document.querySelectorAll('button')].find((b) => b.innerText.includes('v1 ·')).click()`);
  await sleep(1200);
  log("  after selecting the older v1 → chip:", await text("[data-testid=motion-chip]"), "| artifact requests:", (await state()).detailCalls);
  await mock({ slim: false, rendered: false });
});

await run("12 a render job that FAILS on the budget is shown inline (the job card disappears)", async () => {
  await mock({ mode: "azure", available: true, worker: "ready", budget: "ok", rendered: false, jobStart: 0, slim: false, jobFail: true });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  await clickButton("Render spot");
  await waitFor(`!!${q("[data-testid=job-progress]")}`, 8000, "job card");
  await waitFor(`!!${q("[data-testid=render-failure]")}`, 12000, "inline failure after the failed job");
  log("  job card still there:", await ev(`!!${q("[data-testid=job-progress]")}`));
  log("  inline alert:", (await text("[data-testid=render-failure]"))?.replace(/\n/g, " | "), "| kind:", await ev(`${q("[data-testid=render-failure]")}.dataset.kind`));
  await shot("13-en-job-failed");
  await mock({ jobFail: false, jobStart: 0 });
});

await run("13 silent warm-up after the keyframes finish", async () => {
  await mock({ mode: "azure", available: true, worker: "cold", budget: "ok", rendered: false, jobStart: 0, slim: false, jobFail: false });
  const before = (await state()).posts.filter((p) => p.path === "/api/motion/warmup").length;
  await nav(`${WEB}/campaigns/cmp_1/storyboard?lang=en`);
  await waitFor(`document.querySelectorAll('[data-testid^=motion-editor-]').length === 4`, 20000, "storyboard");
  await clickButton("Generate keyframes");
  await waitFor(`!!${q("[data-testid=job-progress]")}`, 8000, "frames job card");
  await waitFor(`!${q("[data-testid=job-progress]")}`, 15000, "frames job finished");
  await sleep(1500);
  const warm = (await state()).posts.filter((p) => p.path === "/api/motion/warmup");
  log("  warm-up POSTs after the keyframes:", warm.length - before, "| body:", JSON.stringify(warm.at(-1)?.body), "| worker:", (await state()).worker);
  const toastText = await ev(`(document.querySelector('[aria-live=polite]')?.innerText ?? '').trim()`);
  log("  toast area text (must be empty — the warm-up is silent):", JSON.stringify(toastText));
  if (warm.length - before !== 1) throw new Error("expected exactly one silent warm-up");
  if (toastText) throw new Error("the silent warm-up showed a toast");
  // a second keyframe run while the GPU is warming: the endpoint is still called (the backend decides), still silent
  await mock({ worker: "cold" });
});

await run("14 cold-start row + warm-up toast with its cost (EN)", async () => {
  await mock({ mode: "azure", available: true, worker: "cold", budget: "ok", rendered: false, jobStart: 0 });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=estimate-cold-start]")}`, 20000, "cold-start row");
  log("  cold row:", (await text("[data-testid=estimate-cold-start]"))?.replace(/\n/g, " | "), "| total:", await text("[data-testid=estimate-total]"), "| tile:", await ev(`${q("[data-testid=quality-cinematic]")}.closest('label').innerText.replace(/\\n/g,' / ')`));
  await shot("14-en-cold-row");
  await clickButton("Warm up GPU");
  await waitFor(`!!document.querySelector('[aria-live=polite]')?.innerText.trim()`, 5000, "warm-up toast");
  log("  toast:", (await ev(`document.querySelector('[aria-live=polite]').innerText`)).replace(/\n/g, " | "), "| badge:", (await text("[data-testid=gpu-status]"))?.replace(/\n/g, " | "));
  await mock({ worker: "cold" });
});

await run("15 aspect change re-requests the estimate for that aspect (with the storyboard id)", async () => {
  await mock({ mode: "azure", available: true, worker: "ready", budget: "ok", rendered: false, jobStart: 0 });
  await nav(`${WEB}/campaigns/cmp_1/video?lang=en`);
  await waitFor(`!!${q("[data-testid=motion-estimate]")}`, 20000, "estimate panel");
  await ev(`(() => { const s = document.querySelector('select[aria-label=aspect]'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, '9:16'); s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await sleep(1200);
  log("  select value now:", await ev(`document.querySelector('select[aria-label=aspect]').value`), "| spot title aspect:", await ev(`document.body.innerText.includes('Provider')`));
  const urls = await ev(`performance.getEntriesByType('resource').map((r) => r.name).filter((n) => n.includes('/spot/estimate'))`);
  log("  estimate requests:", JSON.stringify(urls.map((u) => u.replace(/^https?:\/\/[^/]+/, ""))));
  if (!urls.some((u) => u.includes("aspect=9%3A16") && u.includes("storyboard_id=sb_1"))) throw new Error("no estimate request for 9:16 with the storyboard id");
});

await run("9 storyboard: motion editor (EN) + PL", async () => {
  await nav(`${WEB}/campaigns/cmp_1/storyboard?lang=en`);
  await waitFor(`document.querySelectorAll('[data-testid^=motion-editor-]').length === 4`, 20000, "4 editors");
  await sleep(600);
  log("  editors:", await ev(`document.querySelectorAll('[data-testid^=motion-editor-]').length`), "| imgs in shots:", await ev(`document.querySelectorAll('[data-testid=shots] img').length`));
  await shot("10-en-storyboard");
  // type into shot 3, save
  await ev(`(() => { const ta = document.querySelector('[data-testid=motion-editor-s3] textarea'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; set.call(ta, 'Coffee pours slowly; the camera tilts down.'); ta.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await sleep(300);
  log("  save enabled after typing:", await ev(`![...document.querySelectorAll('[data-testid=motion-editor-s3] button')].find((b) => b.innerText.trim() === 'Save motion').disabled`));
  log("  counter:", await ev(`document.querySelector('[data-testid=motion-editor-s3]').innerText.match(/\\d+\\/300 characters/)?.[0]`));
  await ev(`(() => { const b = [...document.querySelectorAll('[data-testid=motion-editor-s3] button')].find((x) => x.innerText.trim() === 'Save motion'); b.click(); })()`);
  await waitFor(`(window.__x = 1) && true`, 1000);
  await sleep(800);
  log("  PATCH sent:", JSON.stringify((await state()).patches.at(-1)));
  await shot("11-en-storyboard-saved");
  await nav(`${WEB}/campaigns/cmp_1/storyboard?lang=pl`);
  await waitFor(`document.querySelectorAll('[data-testid^=motion-editor-]').length === 4`, 20000, "4 editors (pl)");
  await sleep(600);
  log("  overflow:", JSON.stringify(await overflow()));
  await shot("12-pl-storyboard");
});

log("\n=== summary ===");
for (const [n, r] of results) log(`${r === "ok" ? "PASS" : "FAIL"}  ${n}${r === "ok" ? "" : "  → " + r}`);
const noisy = consoleLog.filter((l) => !/favicon|Download the React DevTools|\[vite\]/.test(l));
log(`\nconsole messages (${noisy.length}):`);
noisy.slice(0, 25).forEach((l) => log("  " + l));
stop();
process.exit(0);
