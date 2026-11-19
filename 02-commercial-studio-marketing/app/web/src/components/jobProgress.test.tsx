import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import { messages as shellMessages } from "../i18n/pl/messages-shell";
import { JobProgress, JobProgressView } from "./ui";

const running = { id: "job_7", kind: "spot.render", status: "running", progress: 0.45, title: "Render spotu (16:9)", message: "Ujęcie 2/4: generowanie ruchu AI (45%)" };
const render = (props: Parameters<typeof JobProgressView>[0]) => renderToStaticMarkup(<JobProgressView {...props} />);
// text of the markup: block boundaries become a space, inline tags vanish; the Polish runtime glues one-letter words with a no-break space, wording checks compare with plain ones
const plain = (html: string) =>
  html
    .replace(/<\/?(?:div|p|li|ul|ol|button|span)\b[^>]*>/g, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/\u00A0/g, " ")
    .replace(/\s+/g, " ");
const tag = (html: string, testId: string) => [...html.matchAll(/<[a-z0-9]+\b[^>]*data-testid="([^"]+)"[^>]*>/g)].find((m) => m[1] === testId)?.[0];

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

describe("JobProgress — what a job looks like", () => {
  it("shows Connecting… until the first update (effects do not run on the server: nothing is opened)", () => {
    const html = renderToStaticMarkup(<JobProgress jobId="job_7" />);
    expect(plain(html)).toContain("Connecting…");
    expect(html).toContain('aria-label="loading"');
    expect(html).not.toContain('data-testid="job-stalled"');
  });

  it("shows the server's localized per-shot message exactly as it came, with the title and the percentage", () => {
    setLang("pl");
    const html = render({ job: running });
    expect(plain(html)).toContain("Render spotu (16:9)");
    expect(plain(html)).toContain("Ujęcie 2/4: generowanie ruchu AI (45%)");
    expect(plain(html)).toContain("45%");
    expect(html).toContain('aria-valuenow="45"');
    expect(html).toContain('data-testid="job-progress"');
    expect(html).toContain('aria-label="ładowanie"'); // the running spinner
    expect(html).not.toContain('data-testid="job-stalled"');
  });

  it("a failed job shows its error, as before", () => {
    const html = render({ job: { ...running, status: "failed", error: "The GPU worker ran out of memory." } });
    expect(plain(html)).toContain("The GPU worker ran out of memory.");
    expect(html).toContain("border-roast-500/40");
    expect(html).not.toContain('data-testid="job-stalled"');
  });
});

describe("JobProgress — the connection is lost for a minute", () => {
  it("keeps the last known progress and adds an inline alert with a retry", () => {
    const html = render({ job: running, stalled: true, onRetry: () => undefined });
    expect(tag(html, "job-stalled")).toContain('role="alert"');
    const t = plain(html);
    expect(t).toContain("Lost connection to the server");
    expect(t).toContain("The job may still be running — we keep trying to reconnect.");
    expect(t).toContain("Try again");
    expect(t).toContain("Ujęcie 2/4: generowanie ruchu AI (45%)"); // the last message stays
    expect(t).toContain("45%");
    expect(tag(html, "job-retry")).toBeDefined();
    expect(tag(html, "job-retry")).not.toContain('disabled=""');
    expect(html).toContain("border-roast-500/40"); // the existing failure look
    expect(html).not.toContain('aria-label="loading"'); // nothing is spinning: the job is not known to progress
  });

  it("while a retry is under way the button is busy", () => {
    const html = render({ job: running, stalled: true, retrying: true });
    expect(tag(html, "job-retry")).toContain('disabled=""');
    expect(html).toContain('aria-label="loading"');
  });

  it("with no update ever received the alert stands alone (no Connecting… spinner)", () => {
    const html = render({ job: null, stalled: true });
    expect(plain(html)).not.toContain("Connecting…");
    expect(plain(html)).toContain("Lost connection to the server");
    expect(html).toContain('data-testid="job-progress"');
    expect(html).not.toContain('aria-label="loading"');
  });

  it("a job that has ended never shows it, whatever the flag says", () => {
    expect(render({ job: { ...running, status: "succeeded", progress: 1 }, stalled: true })).not.toContain('data-testid="job-stalled"');
    expect(render({ job: { ...running, status: "cancelled" }, stalled: true })).not.toContain('data-testid="job-stalled"');
  });

  it("is fully Polish: no English, no raw placeholders, no missing dictionary keys", () => {
    setLang("pl");
    const html = render({ job: running, stalled: true });
    const t = plain(html);
    expect(t).toContain("Utracono połączenie z serwerem");
    expect(t).toContain("Zadanie może nadal trwać — wciąż próbujemy połączyć się ponownie.");
    expect(t).toContain("Spróbuj ponownie");
    expect(t).not.toMatch(/Lost connection|Try again|reconnect/);
    expect(t.match(/\{[A-Za-z_]\w*\}/g) ?? []).toEqual([]);
    expect(warn.mock.calls.map((c: unknown[]) => String(c[0])).filter((m: string) => m.startsWith("[i18n] missing"))).toEqual([]);
  });

  it("the Polish texts follow the glossary typography (spaced em dash, final full stop as in English, no straight quotes)", () => {
    for (const source of ["Lost connection to the server", "The job may still be running — we keep trying to reconnect.", "Try again"]) {
      const text = shellMessages[source];
      expect(text, source).toBeTruthy();
      expect(text, source).not.toMatch(/\.\.\.| - |"| {2,}|\s[,.;:!?]/);
      expect(text.endsWith("."), source).toBe(source.endsWith("."));
      expect(text.includes(" — "), source).toBe(source.includes(" — "));
    }
  });
});
