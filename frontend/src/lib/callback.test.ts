import assert from "node:assert/strict";
import { test } from "node:test";
import { OTHER_BROWSER, callbackErrorMessage, exchangeOnce, normaliseOtp, urlError, type AuthLike } from "./callback";

function fake(opts: { error?: string; session?: boolean; delayMs?: number }) {
  let exchanges = 0;
  const auth: AuthLike = {
    async exchangeCodeForSession() {
      exchanges += 1;
      await new Promise((r) => setTimeout(r, opts.delayMs ?? 5));
      return { error: opts.error ? { message: opts.error } : null };
    },
    async getSession() { return { data: { session: opts.session ? { user: {} } : null } }; },
  };
  return { auth, count: () => exchanges };
}

test("the code is exchanged exactly once, even when the effect runs twice", async () => {
  const f = fake({});
  const [a, b] = await Promise.all([exchangeOnce(f.auth, "code-1"), exchangeOnce(f.auth, "code-1")]);
  assert.deepEqual(a, { ok: true });
  assert.equal(a, b);
  assert.equal(f.count(), 1);
});

test("verifier not found but a session exists: that is success", async () => {
  const f = fake({ error: "PKCE code verifier not found in storage", session: true });
  assert.deepEqual(await exchangeOnce(f.auth, "code-2"), { ok: true });
});

test("verifier not found and no session: explain the same-browser rule and point to the code", async () => {
  const f = fake({ error: "PKCE code verifier not found in storage. This can happen if the auth flow was initiated in a different browser" });
  const r = await exchangeOnce(f.auth, "code-3");
  assert.deepEqual(r, { ok: false, message: OTHER_BROWSER });
  assert.match(OTHER_BROWSER, /6-digit code/);
});

test("expired links and errors in the redirect URL", () => {
  assert.match(callbackErrorMessage("Email link is invalid or has expired"), /expired or was already used/);
  assert.match(urlError("?error=access_denied&error_description=Email+link+is+invalid+or+has+expired", "") ?? "",
               /expired/);
  assert.match(urlError("", "#error_description=Email%20link%20is%20invalid%20or%20has%20expired") ?? "", /expired/);
  assert.equal(urlError("?code=abc", ""), null);
});

test("one-time code input", () => {
  assert.equal(normaliseOtp(" 123 456 "), "123456");
  assert.equal(normaliseOtp("123-456"), "123456");
  assert.equal(normaliseOtp("12345"), null);
  assert.equal(normaliseOtp("12345a"), null);
  assert.equal(normaliseOtp("12345678"), "12345678");
});
