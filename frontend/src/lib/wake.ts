// Cold starts: on a free or sleeping server plan the API can take up to a minute to answer the first request, and
// the hosting proxy may answer 502/503/504 meanwhile. Instead of raw errors the app shows "The server is waking
// up" with a retry. Pure decisions here (tested); the store below feeds the banner (components/server-status.tsx).

export type Connection = "ok" | "slow" | "waking" | "down";

/** A request pending longer than this shows "waking up". */
export const SLOW_AFTER_MS = 3000;
/** GETs are retried for at most this long before the app says the server is not responding. */
export const RETRY_BUDGET_MS = 90_000;
const DELAYS_MS = [1000, 2000, 4000, 8000, 15000];

/** True when the failure looks like the server is asleep or starting, not an answer from the app itself.
 * Every response from the app carries X-Request-ID; the hosting proxy's 502/503/504 pages and network errors don't. */
export function isWaking(status: number, hasRequestId: boolean): boolean {
  if (status === 0) return true;  // network error: no response at all
  return !hasRequestId && (status === 502 || status === 503 || status === 504);
}

/** Wait before retry number `attempt` (0-based): 1, 2, 4, 8, then every 15 seconds. */
export function delayFor(attempt: number): number {
  return DELAYS_MS[Math.min(Math.max(attempt, 0), DELAYS_MS.length - 1)];
}

/** Only reads are retried automatically: a POST/PUT/DELETE might have been processed, so the person decides. */
export function shouldRetry(method: string, elapsedMs: number, nextDelayMs: number): boolean {
  return method.toUpperCase() === "GET" && elapsedMs + nextDelayMs <= RETRY_BUDGET_MS;
}

export const WAKING_MESSAGE =
  "The server is waking up (it sleeps when nobody has used it for a while). This usually takes under a minute.";
export const DOWN_MESSAGE =
  "The server is not responding right now. Please try again in a few minutes; if it keeps happening, tell the admin.";

/** The banner's state, from what is going on now. */
export function connectionState(o: { pendingSlow: boolean; retrying: boolean; gaveUp: boolean }): Connection {
  if (o.retrying) return "waking";
  if (o.gaveUp) return "down";
  return o.pendingSlow ? "slow" : "ok";
}

// ---- a tiny store (browser only) ----
type Listener = () => void;
const listeners = new Set<Listener>();
let slow = 0;  // requests pending longer than SLOW_AFTER_MS
let retrying = 0;  // GETs currently waiting to retry
let gaveUp = false;
let wakeNow: (() => void)[] = [];
let state: Connection = "ok";

function emit() {
  const next = connectionState({ pendingSlow: slow > 0, retrying: retrying > 0, gaveUp });
  if (next !== state) {
    state = next;
    listeners.forEach((l) => l());
  }
}

export const connection = {
  get: (): Connection => state,
  subscribe(l: Listener): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  /** Call when a request starts; returns the function to call when it ends. */
  track(): () => void {
    let isSlow = false;
    const t = setTimeout(() => { isSlow = true; slow += 1; emit(); }, SLOW_AFTER_MS);
    return () => {
      clearTimeout(t);
      if (isSlow) slow -= 1;
      emit();
    };
  },
  retryStarted() { retrying += 1; gaveUp = false; emit(); },
  retryEnded() { retrying -= 1; emit(); },
  succeeded() { if (gaveUp) { gaveUp = false; emit(); } },
  failed() { gaveUp = true; emit(); },
  /** Wait `ms`, or less if the person presses "Retry now". */
  wait(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const t = setTimeout(done, ms);
      function done() {
        clearTimeout(t);
        wakeNow = wakeNow.filter((f) => f !== done);
        resolve();
      }
      wakeNow.push(done);
    });
  },
  retryNow(): boolean {
    const pending = wakeNow;
    wakeNow = [];
    pending.forEach((f) => f());
    return pending.length > 0;
  },
};

export class ServerUnavailable extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** Run one request with the cold-start handling: retries GETs while the server wakes up (backoff, within the
 * budget), reports progress to `conn`, and throws ServerUnavailable with a friendly message when it gives up. */
export async function withWake(
  attemptFetch: () => Promise<Response | null>, method: string,
  deps: { now?: () => number; conn?: typeof connection } = {},
): Promise<Response> {
  const now = deps.now ?? Date.now;
  const conn = deps.conn ?? connection;
  const started = now();
  let attempt = 0;
  let retrying = false;
  try {
    for (;;) {
      const done = conn.track();
      let res: Response | null;
      try {
        res = await attemptFetch();
      } catch {
        res = null;
      } finally {
        done();
      }
      const status = res?.status ?? 0;
      if (res && !isWaking(status, res.headers.has("x-request-id"))) {
        conn.succeeded();
        return res;
      }
      const delay = delayFor(attempt++);
      if (!shouldRetry(method, now() - started, delay)) {
        conn.failed();
        throw new ServerUnavailable(method.toUpperCase() === "GET" ? DOWN_MESSAGE
          : `${WAKING_MESSAGE} Your change was probably not saved: check, then try again in a minute.`, status);
      }
      if (!retrying) {
        retrying = true;
        conn.retryStarted();
      }
      await conn.wait(delay);
    }
  } finally {
    if (retrying) conn.retryEnded();
  }
}
