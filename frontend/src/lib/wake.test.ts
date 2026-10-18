import assert from "node:assert/strict";
import { test } from "node:test";
import { DOWN_MESSAGE, RETRY_BUDGET_MS, ServerUnavailable, WAKING_MESSAGE, connectionState, delayFor, isWaking, shouldRetry, withWake } from "./wake";

test("network errors and the proxy's 502/503/504 mean waking; the app's own errors don't", () => {
  assert.equal(isWaking(0, false), true);
  for (const s of [502, 503, 504]) {
    assert.equal(isWaking(s, false), true, `${s} from the proxy`);
    assert.equal(isWaking(s, true), false, `${s} from the app (it has a request id)`);
  }
  assert.equal(isWaking(500, false), false);
  assert.equal(isWaking(404, false), false);
  assert.equal(isWaking(429, true), false);
});

test("backoff: 1, 2, 4, 8 then 15 seconds", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 20].map(delayFor), [1000, 2000, 4000, 8000, 15000, 15000, 15000]);
});

test("only GETs are retried, within the budget", () => {
  assert.equal(shouldRetry("GET", 0, 1000), true);
  assert.equal(shouldRetry("get", RETRY_BUDGET_MS - 1000, 1000), true);
  assert.equal(shouldRetry("GET", RETRY_BUDGET_MS - 999, 1000), false);
  for (const m of ["POST", "PUT", "DELETE"]) assert.equal(shouldRetry(m, 0, 1000), false);
});

test("banner state", () => {
  assert.equal(connectionState({ pendingSlow: false, retrying: false, gaveUp: false }), "ok");
  assert.equal(connectionState({ pendingSlow: true, retrying: false, gaveUp: false }), "slow");
  assert.equal(connectionState({ pendingSlow: true, retrying: true, gaveUp: true }), "waking");
  assert.equal(connectionState({ pendingSlow: false, retrying: false, gaveUp: true }), "down");
});

function fakeConn() {
  const log: string[] = [];
  return {
    log,
    conn: {
      get: () => "ok" as const, subscribe: () => () => true,
      track: () => () => {}, retryStarted: () => log.push("retrying"), retryEnded: () => log.push("retry ended"),
      succeeded: () => log.push("ok"), failed: () => log.push("gave up"), retryNow: () => false,
      wait: async (ms: number) => { log.push(`wait ${ms}`); clock += ms; },
    },
  };
}
let clock = 0;
const now = () => clock;
const res = (status: number, rid = true) => new Response("{}", { status, headers: rid ? { "x-request-id": "r1" } : {} });

test("a GET is retried while the server wakes up, then succeeds", async () => {
  clock = 0;
  const { conn, log } = fakeConn();
  const answers: (Response | null)[] = [null, res(502, false), res(503, false), res(200)];
  const r = await withWake(async () => answers.shift() ?? null, "GET", { now, conn });
  assert.equal(r.status, 200);
  assert.deepEqual(log, ["retrying", "wait 1000", "wait 2000", "wait 4000", "ok", "retry ended"]);
});

test("a GET gives up after the budget with a friendly message", async () => {
  clock = 0;
  const { conn, log } = fakeConn();
  await assert.rejects(withWake(async () => null, "GET", { now, conn }),
                       (e: Error) => e instanceof ServerUnavailable && e.message === DOWN_MESSAGE);
  assert.equal(log.at(-2), "gave up");
  assert.ok(clock <= RETRY_BUDGET_MS);
});

test("a POST is never retried; the app's own errors pass straight through", async () => {
  clock = 0;
  const { conn, log } = fakeConn();
  let calls = 0;
  await assert.rejects(withWake(async () => { calls += 1; return null; }, "POST", { now, conn }),
                       (e: Error) => e.message.startsWith(WAKING_MESSAGE) && /probably not saved/.test(e.message));
  assert.equal(calls, 1);
  assert.deepEqual(log, ["gave up"]);
  const own = await withWake(async () => res(503), "GET", { now, conn });  // the app's 503 (has a request id)
  assert.equal(own.status, 503);
});
