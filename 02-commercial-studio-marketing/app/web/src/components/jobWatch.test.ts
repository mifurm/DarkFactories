import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, onApiError } from "../api";
import { setLang } from "../i18n";
import { fetchJobSnapshot, isTerminal, openJobStream, watchJob, type JobSnapshot, type JobStream } from "./jobWatch";

/** An EventSource as browsers have it: nothing is delivered after close() (`leaky` models a misbehaving one, to prove the watcher does not rely on that). */
class FakeStream implements JobStream {
  closed = false;
  leaky = false;
  private listeners = new Map<string, ((event: { data?: unknown }) => void)[]>();
  addEventListener(type: string, listener: (event: { data?: unknown }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
  }
  private fire(type: string, data?: unknown) {
    if (this.closed && !this.leaky) return;
    for (const listener of this.listeners.get(type) ?? []) listener({ data });
  }
  open() {
    this.fire("open");
  }
  emit(type: "progress" | "done", job: JobSnapshot) {
    this.fire(type, JSON.stringify(job));
  }
  fail() {
    this.fire("error");
  }
}

const job = (status: string, progress = 0): JobSnapshot => ({ id: "job_1", kind: "spot.render", status, progress, message: `Ujęcie 2/4: generowanie ruchu AI (${Math.round(progress * 100)}%)` });
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
};

/** A watcher on fake timers with a scripted server: `streams` are the EventSources it opened, `fetchJob` answers the polls ("running" unless told otherwise).
 *  `failStreams`: every connection breaks at once; `replay`: every connection opens and replays the current state at once, like the real server. */
function setup(opts: { failStreams?: boolean; replay?: boolean } = {}) {
  const t0 = Date.now();
  const streams: FakeStream[] = [];
  const openedAt: number[] = [];
  const polledAt: number[] = [];
  const fetchJob = vi.fn(async (): Promise<JobSnapshot> => job("running", 0.5));
  const seen = { jobs: [] as JobSnapshot[], done: [] as JobSnapshot[], stalled: [] as boolean[] };
  const watch = watchJob({
    jobId: "job_1",
    openStream: () => {
      const stream = new FakeStream();
      streams.push(stream);
      openedAt.push(Date.now() - t0);
      // the connection breaks, or opens, as soon as the watcher has attached its listeners
      if (opts.failStreams) void Promise.resolve().then(() => stream.fail());
      if (opts.replay)
        void Promise.resolve().then(() => {
          stream.open();
          stream.emit("progress", job("running", 0.1));
        });
      return stream;
    },
    fetchJob: () => {
      polledAt.push(Date.now() - t0);
      return fetchJob();
    },
    onJob: (j) => seen.jobs.push(j),
    onDone: (j) => seen.done.push(j),
    onStalled: (stalled) => seen.stalled.push(stalled),
  });
  return { watch, streams, fetchJob, seen, openedAt, polledAt };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setLang("en");
});

describe("watchJob — the stream", () => {
  it("follows the job over one stream and finishes on the terminal event, leaving nothing behind", async () => {
    const h = setup();
    const [stream] = h.streams;
    stream.open();
    stream.emit("progress", job("running", 0.3));
    expect(h.seen.jobs.map((j) => j.progress)).toEqual([0.3]);
    expect(h.seen.done).toEqual([]);
    stream.emit("done", job("succeeded", 1));
    expect(h.seen.done).toEqual([job("succeeded", 1)]);
    expect(h.seen.jobs.at(-1)).toEqual(job("succeeded", 1));
    expect(stream.closed).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(h.streams).toHaveLength(1);
    expect(h.fetchJob).not.toHaveBeenCalled();
  });

  it("a quiet open stream is not a failure: after 45 s of silence one poll and a re-open confirm it (the server's keep-alives are invisible to scripts)", async () => {
    const h = setup();
    h.streams[0].open();
    h.streams[0].emit("progress", job("running", 0.1));
    await vi.advanceTimersByTimeAsync(44_999);
    expect(h.fetchJob).not.toHaveBeenCalled();
    expect(h.streams).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams[0].closed).toBe(true);
    expect(h.fetchJob).toHaveBeenCalledTimes(1); // straight away
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.streams).toHaveLength(2); // and the stream is back after the first backoff step
    expect(h.seen.stalled).toEqual([]);
  });

  it("a healthy job that stays quiet for ten minutes never shows a failure and is never lost", async () => {
    const h = setup({ replay: true });
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(h.seen.stalled).toEqual([]);
    expect(h.streams.length).toBeGreaterThanOrEqual(12); // re-checked about every 46 s
    expect(h.streams.slice(0, -1).every((s) => s.closed)).toBe(true);
    expect(h.streams.at(-1)?.closed).toBe(false);
    expect(h.seen.done).toEqual([]);
  });

  it("a stream that never opens is abandoned after 10 s: polling starts at once and the connection is retried", async () => {
    const h = setup();
    await vi.advanceTimersByTimeAsync(9_999);
    expect(h.streams[0].closed).toBe(false);
    expect(h.fetchJob).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams[0].closed).toBe(true);
    expect(h.fetchJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.streams).toHaveLength(2);
    expect(h.seen.stalled).toEqual([]);
  });
});

describe("watchJob — the stream breaks mid-job", () => {
  it("polling picks up the terminal state", async () => {
    const h = setup();
    h.fetchJob.mockResolvedValueOnce(job("running", 0.5)).mockResolvedValueOnce(job("succeeded", 1));
    const [first] = h.streams;
    first.open();
    first.emit("progress", job("running", 0.3));
    first.fail();
    expect(first.closed).toBe(true);
    expect(h.fetchJob).toHaveBeenCalledTimes(1); // straight away, not after the first interval
    await vi.advanceTimersByTimeAsync(0);
    expect(h.seen.jobs.map((j) => j.progress)).toEqual([0.3, 0.5]);
    expect(h.seen.done).toEqual([]);

    await vi.advanceTimersByTimeAsync(3000);
    expect(h.seen.done).toEqual([job("succeeded", 1)]);
    expect(h.streams.every((s) => s.closed)).toBe(true); // the stream re-opened in the meantime is closed too
    expect(vi.getTimerCount()).toBe(0);

    const before = [h.streams.length, h.fetchJob.mock.calls.length];
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect([h.streams.length, h.fetchJob.mock.calls.length]).toEqual(before);
  });

  it("polls every 3 s while the stream is down and re-opens it with a 1 s → 8 s exponential backoff", async () => {
    const h = setup({ failStreams: true });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(h.polledAt).toEqual(Array.from({ length: 11 }, (_, i) => i * 3000));
    expect(h.openedAt).toEqual([0, 1000, 3000, 7000, 15000, 23000]); // +1 s, +2 s, +4 s, +8 s, +8 s
    expect(h.seen.stalled).toEqual([]);
  });

  it("a stream that delivers again takes over: polling stops and the backoff starts from 1 s again", async () => {
    const h = setup();
    h.streams[0].fail();
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.streams).toHaveLength(2);
    h.streams[1].open();
    h.streams[1].emit("progress", job("running", 0.6));
    const polls = h.fetchJob.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(h.fetchJob).toHaveBeenCalledTimes(polls);
    expect(vi.getTimerCount()).toBe(1); // the silence guard of the open stream, nothing else

    h.streams[1].fail();
    await vi.advanceTimersByTimeAsync(999);
    expect(h.streams).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams).toHaveLength(3);
  });

  it("an older poll answer never overwrites what the reconnected stream has delivered, but a terminal one is honoured", async () => {
    const h = setup();
    const stale = deferred<JobSnapshot>();
    h.fetchJob.mockImplementationOnce(() => stale.promise);
    h.streams[0].fail(); // the poll is now in flight
    await vi.advanceTimersByTimeAsync(1000);
    h.streams[1].open();
    h.streams[1].emit("progress", job("running", 0.7));
    stale.resolve(job("running", 0.4));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.seen.jobs.map((j) => j.progress)).toEqual([0.7]);

    const late = deferred<JobSnapshot>();
    h.fetchJob.mockImplementationOnce(() => late.promise);
    h.streams[1].fail();
    late.resolve(job("succeeded", 1));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.seen.done).toEqual([job("succeeded", 1)]);
  });
});

describe("watchJob — completion is handled once", () => {
  it("the stream and a poll that was in flight both report the end", async () => {
    const h = setup();
    const poll = deferred<JobSnapshot>();
    h.fetchJob.mockImplementationOnce(() => poll.promise);
    h.streams[0].fail();
    await vi.advanceTimersByTimeAsync(1000);
    h.streams[1].emit("done", job("succeeded", 1));
    poll.resolve(job("succeeded", 1));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(h.seen.done).toHaveLength(1);
    expect(h.seen.jobs.filter((j) => j.status === "succeeded")).toHaveLength(1);
  });

  it("a terminal progress event followed by the done event (even from a stream that ignores close()) completes once", () => {
    const h = setup();
    const [stream] = h.streams;
    stream.leaky = true;
    stream.emit("progress", job("failed", 0.4));
    stream.emit("done", job("failed", 0.4));
    stream.fail();
    expect(h.seen.done).toHaveLength(1);
    expect(h.seen.done[0].status).toBe("failed");
    expect(h.streams).toHaveLength(1);
    expect(h.fetchJob).not.toHaveBeenCalled();
  });

  it("failed and cancelled jobs are terminal too", () => {
    expect(["succeeded", "failed", "cancelled"].map((status) => isTerminal({ status }))).toEqual([true, true, true]);
    expect(["queued", "running", undefined].map((status) => isTerminal({ status }))).toEqual([false, false, false]);
  });
});

describe("watchJob — unmounting", () => {
  it("stop() closes every stream, cancels every timer and silences a poll that is still in flight", async () => {
    const h = setup();
    const inflight = deferred<JobSnapshot>();
    h.fetchJob.mockImplementationOnce(() => inflight.promise);
    h.streams[0].fail(); // poll in flight, reconnect timer, stall timer
    await vi.advanceTimersByTimeAsync(1000);
    h.streams[1].fail(); // a second reconnect timer is pending now
    h.watch.stop();
    expect(h.streams.every((s) => s.closed)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);

    inflight.resolve(job("succeeded", 1));
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(h.seen).toEqual({ jobs: [], done: [], stalled: [] });
    expect(h.streams).toHaveLength(2);
    expect(h.fetchJob).toHaveBeenCalledTimes(1);

    await h.watch.retry(); // a retry after unmounting is a no-op
    expect(h.streams).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("an event that still arrives from a closed stream is ignored", () => {
    const h = setup();
    const [stream] = h.streams;
    stream.leaky = true;
    h.watch.stop();
    stream.emit("done", job("succeeded", 1));
    stream.fail();
    expect(h.seen).toEqual({ jobs: [], done: [], stalled: [] });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("watchJob — failures are silent until a minute of them", () => {
  it("reports nothing before 60 s without an answer, then once; keeps trying; clears itself when the server answers", async () => {
    const h = setup({ failStreams: true });
    h.fetchJob.mockRejectedValue(new Error("offline"));
    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.seen.stalled).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.seen.stalled).toEqual([true]);

    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(h.seen.stalled).toEqual([true]);
    expect(h.streams.length).toBeGreaterThan(30);

    h.fetchJob.mockResolvedValue(job("running", 0.8));
    await vi.advanceTimersByTimeAsync(3000);
    expect(h.seen.stalled).toEqual([true, false]);
    expect(h.seen.jobs.at(-1)?.progress).toBe(0.8);
  });

  it("polls that keep answering keep the failure away, however long the stream stays down", async () => {
    const h = setup({ failStreams: true });
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(h.seen.stalled).toEqual([]);
    expect(h.polledAt.length).toBeGreaterThan(190);
    expect(h.seen.jobs.length).toBe(h.polledAt.length);
  });

  it("an unreadable answer (a proxy's HTML page, a bare null) does not count as an answer", async () => {
    const h = setup({ failStreams: true });
    h.fetchJob.mockResolvedValue("<html>502</html>" as unknown as JobSnapshot);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.seen.stalled).toEqual([true]);
    expect(h.seen.jobs).toEqual([]);
  });

  it("when nothing answers at all — the stream never opens, the polls fail — the failure shows after the same minute", async () => {
    const h = setup();
    h.fetchJob.mockRejectedValue(new Error("offline"));
    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.seen.stalled).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.seen.stalled).toEqual([true]);
  });

  it("a stream that goes silent while the network is dead is reported a minute after the silence was noticed", async () => {
    const h = setup();
    h.fetchJob.mockRejectedValue(new Error("offline"));
    h.streams[0].open();
    h.streams[0].emit("progress", job("running", 0.1));
    await vi.advanceTimersByTimeAsync(45_000 + 59_999);
    expect(h.seen.stalled).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.seen.stalled).toEqual([true]);
  });

  it("retry() tries again right now — a new stream and a poll without waiting for the backoff — and clears the failure when the server answers", async () => {
    const h = setup({ failStreams: true });
    h.fetchJob.mockRejectedValue(new Error("offline"));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.seen.stalled).toEqual([true]);
    const streams = h.streams.length;
    const polls = h.fetchJob.mock.calls.length;

    h.fetchJob.mockResolvedValue(job("running", 0.9));
    const attempt = h.watch.retry();
    expect(h.streams).toHaveLength(streams + 1);
    expect(h.fetchJob).toHaveBeenCalledTimes(polls + 1);
    await attempt;
    expect(h.seen.stalled).toEqual([true, false]);
    expect(h.seen.jobs.at(-1)?.progress).toBe(0.9);
  });

  it("retry() while the server is still down leaves the failure showing and the retrying going", async () => {
    const h = setup({ failStreams: true });
    h.fetchJob.mockRejectedValue(new Error("offline"));
    await vi.advanceTimersByTimeAsync(60_000);
    await h.watch.retry();
    expect(h.seen.stalled).toEqual([true]);
    const polls = h.fetchJob.mock.calls.length;
    await vi.advanceTimersByTimeAsync(9000);
    expect(h.fetchJob.mock.calls.length).toBeGreaterThanOrEqual(polls + 3);
  });
});

describe("the real stream and poll", () => {
  const stubSession = () => vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined });

  it("the stream carries the UI language, on every (re)connection", () => {
    stubSession();
    const urls: string[] = [];
    vi.stubGlobal(
      "EventSource",
      class {
        constructor(url: string) {
          urls.push(url);
        }
      },
    );
    openJobStream("job_1");
    setLang("pl");
    openJobStream("job_1");
    expect(urls).toEqual(["/api/stream/jobs/job_1?lang=en", "/api/stream/jobs/job_1?lang=pl"]);
  });

  it("the poll is the job GET the UI already uses, with the language headers", async () => {
    stubSession();
    setLang("pl");
    const fetchStub = vi.fn(async () => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => job("running", 0.2) }));
    vi.stubGlobal("fetch", fetchStub);
    await expect(fetchJobSnapshot("job_1")).resolves.toEqual(job("running", 0.2));
    const [path, init] = fetchStub.mock.calls[0] as unknown as [string, { method: string; headers: Record<string, string> }];
    expect(path).toBe("/api/jobs/job_1");
    expect(init.method).toBe("GET");
    expect(init.headers["X-UI-Lang"]).toBe("pl");
  });

  it("a failing poll rejects without raising the global error toast", async () => {
    stubSession();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 503, headers: { get: () => "application/json" }, json: async () => ({ error: { message: "unavailable", code: "unavailable" } }) })),
    );
    const toast = vi.fn();
    const off = onApiError(toast);
    await expect(fetchJobSnapshot("job_1")).rejects.toBeInstanceOf(ApiError);
    off();
    expect(toast).not.toHaveBeenCalled();
  });
});
