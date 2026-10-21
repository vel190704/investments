import assert from "node:assert/strict";
import { test } from "node:test";
import { buildEnvProblem, missingSupabaseVars, notConfiguredMessage } from "./buildenv";

const URL_ = "https://abc.supabase.co";
const KEY = "anon-" + "value-never-printed";

test("missing, empty and whitespace-only values are named", () => {
  assert.deepEqual(missingSupabaseVars({ url: URL_, anonKey: KEY }), []);
  assert.deepEqual(missingSupabaseVars({ url: URL_ }), ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]);
  assert.deepEqual(missingSupabaseVars({ url: "  ", anonKey: KEY }), ["NEXT_PUBLIC_SUPABASE_URL"]);
  assert.deepEqual(missingSupabaseVars({}), ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"]);
});

test("the build fails naming the variable, never printing a value", () => {
  const p = buildEnvProblem({ NEXT_PUBLIC_SUPABASE_URL: URL_, NEXT_PUBLIC_SUPABASE_ANON_KEY: "", VERCEL_ENV: "production" });
  assert.match(p ?? "", /NEXT_PUBLIC_SUPABASE_ANON_KEY is missing or empty for the Vercel "production" environment/);
  assert.ok(!(p ?? "").includes(URL_));
  const both = buildEnvProblem({}) ?? "";
  assert.match(both, /NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are missing/);
  const ok = buildEnvProblem({ NEXT_PUBLIC_SUPABASE_URL: URL_, NEXT_PUBLIC_SUPABASE_ANON_KEY: KEY });
  assert.equal(ok, null);
  assert.equal(buildEnvProblem({ NEXT_PUBLIC_DEV_AUTH: "1" }), null);  // local build without sign-in
  assert.notEqual(buildEnvProblem({ NEXT_PUBLIC_DEV_AUTH: "true" }), null);  // only exactly "1"
});

test("the /login message says which one and where", () => {
  assert.equal(notConfiguredMessage(["NEXT_PUBLIC_SUPABASE_ANON_KEY"], "preview"),
    "Sign-in is not configured: NEXT_PUBLIC_SUPABASE_ANON_KEY is missing or empty in this build (this is a preview " +
    "deployment: set it in that Vercel scope). Set the value and redeploy; NEXT_PUBLIC_* values are fixed when the " +
    "site is built.");
  assert.match(notConfiguredMessage(["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"]),
    /NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are missing or empty in this build\. Set/);
});
