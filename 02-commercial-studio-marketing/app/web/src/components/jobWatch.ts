import { api, withLang } from "../api";

/** A job as the API serves it (SSE events and GET /api/jobs/{id} share the shape); only `status` drives the logic here. */
export type JobSnapshot = { status?: string; [field: string]: unknown };

/** The part of EventSource the watcher uses (tests plug in a fake). */
export interface JobStream {
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void;
  close(): void;
}

export const POLL_INTERVAL_MS = 3_000;
export const RECONNECT_FIRST_MS = 1_000;
export const RECONNECT_MAX_MS = 8_000;
export const STALL_AFTER_MS = 60_000;
export const CONNECT_TIMEOUT_MS = 10_000;
export const SILENCE_AFTER_MS = 45_000;

const TERMINAL = ["succeeded", "failed", "cancelled"];
export const isTerminal = (job: { status?: unknown } | null | undefined): boolean => TERMINAL.includes(String(job?.status));

export type JobWatchOptions = {
  jobId: string;
  openStream: (jobId: string) => JobStream;
  fetchJob: (jobId: string) => Promise<JobSnapshot>;
  /** Every update, terminal one included. */
  onJob: (job: JobSnapshot) => void;
  /** Exactly once, with the terminal snapshot. */
  onDone: (job: JobSnapshot) => void;
  /** True once nothing has answered for STALL_AFTER_MS; false again as soon as something does. */
  onStalled: (stalled: boolean) => void;
};

export type JobWatch = {
  /** Closes the stream and cancels every timer; nothing is reported afterwards. */
  stop: () => void;
  /** Reconnects and polls right now (the "Try again" button); resolves when that first poll has answered. */
  retry: () => Promise<void>;
};

type Timer = ReturnType<typeof setTimeout>;

/**
 * Follows a job over Server-Sent Events and survives the connection breaking: a cinematic render takes 8–10 minutes, long enough for proxies, deploys and
 * flaky networks to cut the stream. While the stream is down the job is polled every POLL_INTERVAL_MS (GET /api/jobs/{id}) and the stream is re-opened with an
 * exponential backoff (RECONNECT_FIRST_MS doubling up to RECONNECT_MAX_MS); a stream that delivers again takes over and the polling stops.
 *
 * A connection can also die without any error event (a proxy that keeps the client side open, a network switch): a stream that has not opened after
 * CONNECT_TIMEOUT_MS, or has delivered nothing for SILENCE_AFTER_MS, is treated as lost too. The server's keep-alives are SSE comments, which scripts cannot see,
 * so a healthy but quiet job costs one poll and one reconnect (the server replays the current state on connect) per SILENCE_AFTER_MS.
 *
 * Retrying is silent. `onStalled(true)` is the only sign of trouble, and only after STALL_AFTER_MS without any answer (an open stream counts as an answer).
 * Everything stops on the terminal state and on `stop()`.
 */
export function watchJob({ jobId, openStream, fetchJob, onJob, onDone, onStalled }: JobWatchOptions): JobWatch {
  let stopped = false;
  let done = false;
  let connected = false; // the stream is open: events arrive on their own
  let stalled = false;
  let stream: JobStream | null = null;
  let failures = 0; // stream attempts in a row that delivered nothing; each one doubles the next delay
  let polling = false;
  let pollRun = 0;
  let pollTimer: Timer | undefined;
  let reconnectTimer: Timer | undefined;
  let stallTimer: Timer | undefined;
  let connectTimer: Timer | undefined;
  let silenceTimer: Timer | undefined;

  const alive = () => !stopped && !done;

  // the failure streak runs from the last sign of life: the moment a connected stream drops, or any answer from the server
  const armStall = () => {
    clearTimeout(stallTimer);
    stallTimer = undefined;
    if (!alive() || connected) return;
    stallTimer = setTimeout(() => {
      stallTimer = undefined;
      stalled = true;
      onStalled(true);
    }, STALL_AFTER_MS);
  };
  const answered = () => {
    if (stalled) {
      stalled = false;
      onStalled(false);
    }
    armStall();
  };

  const closeStream = () => {
    const open = stream;
    stream = null;
    connected = false;
    clearTimeout(connectTimer);
    clearTimeout(silenceTimer);
    connectTimer = silenceTimer = undefined;
    open?.close();
  };
  const stopPolling = () => {
    polling = false;
    pollRun += 1;
    clearTimeout(pollTimer);
    pollTimer = undefined;
  };
  const stopReconnecting = () => {
    clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  };
  const teardown = () => {
    closeStream();
    stopPolling();
    stopReconnecting();
    clearTimeout(stallTimer);
    stallTimer = undefined;
  };

  const finish = (job: JobSnapshot) => {
    done = true;
    teardown();
    onJob(job);
    onDone(job);
  };
  const receive = (job: JobSnapshot, via: "stream" | "poll") => {
    if (!alive()) return;
    if (isTerminal(job)) return finish(job);
    if (via === "poll" && connected) return; // a poll that was in flight when the stream came back is older than what the stream has delivered since
    onJob(job);
  };

  const pollOnce = async () => {
    let job: JobSnapshot;
    try {
      job = await fetchJob(jobId);
    } catch {
      return; // counted by the stall window, never shown
    }
    if (!alive() || !job || typeof job !== "object") return;
    answered();
    receive(job, "poll");
  };
  const startPolling = (): Promise<void> => {
    if (polling || !alive() || connected) return Promise.resolve();
    polling = true;
    const run = ++pollRun;
    const tick = async (): Promise<void> => {
      pollTimer = undefined;
      await pollOnce();
      if (run !== pollRun) return; // stopped meanwhile: the stream is back, the job is over or the watch was restarted
      if (!alive() || connected) {
        polling = false;
        return;
      }
      pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    return tick();
  };

  const live = () => {
    connected = true;
    clearTimeout(connectTimer);
    connectTimer = undefined;
    stopPolling();
    answered();
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(streamLost, SILENCE_AFTER_MS);
  };
  const connect = () => {
    if (!alive()) return;
    let es: JobStream;
    try {
      es = openStream(jobId);
    } catch {
      streamLost(); // no SSE support here: polling alone carries on
      return;
    }
    stream = es;
    connectTimer = setTimeout(streamLost, CONNECT_TIMEOUT_MS);
    const onData = (event: { data?: unknown }) => {
      if (stream !== es) return;
      let job: JobSnapshot;
      try {
        job = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (!job || typeof job !== "object") return;
      failures = 0;
      live();
      receive(job, "stream");
    };
    es.addEventListener("open", () => {
      if (stream === es) live();
    });
    es.addEventListener("progress", onData);
    es.addEventListener("done", onData);
    es.addEventListener("error", () => {
      if (stream === es) streamLost();
    });
  };
  const scheduleReconnect = () => {
    if (reconnectTimer !== undefined) return;
    const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_FIRST_MS * 2 ** failures);
    failures += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined;
      connect();
    }, delay);
  };
  const streamLost = () => {
    const wasConnected = connected;
    closeStream();
    if (!alive()) return;
    if (wasConnected) armStall();
    scheduleReconnect();
    void startPolling();
  };

  armStall();
  connect();

  return {
    stop: () => {
      stopped = true;
      teardown();
    },
    retry: async () => {
      if (!alive()) return;
      failures = 0;
      stopReconnecting();
      stopPolling();
      closeStream();
      const firstPoll = startPolling();
      connect();
      await firstPoll;
    },
  };
}

export const openJobStream = (jobId: string): JobStream => new EventSource(withLang(`/api/stream/jobs/${jobId}`));
/** Quiet: a failing poll while the stream is down is retried, never toasted. */
export const fetchJobSnapshot = (jobId: string): Promise<JobSnapshot> => api.get<JobSnapshot>(`/api/jobs/${jobId}`, { quiet: true });
