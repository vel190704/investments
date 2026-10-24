import assert from "node:assert/strict";
import { test } from "node:test";
import { apiUrlProblem, buildEnvProblem, missingSupabaseVars, notConfiguredMessage, publicConfigProblems,
         supabaseUrlProblem } from "./buildenv";

const URL_ = "https://abcref123.supabase.co";
const KEY = "anon-" + "value-never-printed";
const API = "https://investments-api.onrender.com";
const ok = { NEXT_PUBLIC_SUPABASE_URL: URL_, NEXT_PUBLIC_SUPABASE_ANON_KEY: KEY, NEXT_PUBLIC_API_URL: API };

test("missing, empty and whitespace-only values are named", () => {
  assert.deepEqual(missingSupabaseVars({ url: URL_, anonKey: KEY }), []);
  assert.deepEqual(missingSupabaseVars({ url: URL_ }), ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]);
  assert.deepEqual(missingSupabaseVars({ url: "  ", anonKey: KEY }), ["NEXT_PUBLIC_SUPABASE_URL"]);
});

test("NEXT_PUBLIC_SUPABASE_URL must be exactly https://<ref>.supabase.co", () => {
  assert.equal(supabaseUrlProblem(URL_), null);
  const bad: [string, RegExp][] = [
    [`${URL_}/`, /ends with a slash/],
    [` ${URL_}`, /contains a space/],
    [`${URL_}\n`, /line break/],
    [`${URL_},https://x.supabase.co`, /comma/],
    [`${URL_}/rest/v1`, /must not contain a path/],
    ["http://abcref123.supabase.co", /must start with https/],
    ["https://abcref123.supabase.co.evil.example", /not a supabase\.co project/],
    ["https://supabase.co", /not a supabase\.co project/],
    ["https://abcref123.supabase.co:8443", /port/],
    ["abcref123.supabase.co", /not a valid URL/],
    [`${URL_}?x=1`, /\? or #/],
  ];
  for (const [v, re] of bad) {
    const p = supabaseUrlProblem(v) ?? "";
    assert.match(p, re, JSON.stringify(v));
    assert.ok(p.startsWith("NEXT_PUBLIC_SUPABASE_URL"));
    assert.ok(!p.includes("abcref123"), "never the value");
  }
});

test("NEXT_PUBLIC_API_URL must be a public https origin", () => {
  assert.equal(apiUrlProblem(API), null);
  const bad: [string | undefined, RegExp][] = [
    [undefined, /missing or empty/],
    ["http://investments-api.onrender.com", /https/],
    ["https://localhost:8000", /this computer/],
    ["https://127.0.0.1:8000", /this computer/],
    ["http://127.0.0.1:8000", /https/],
    [`${API}/`, /slash/],
    [`${API}/api`, /without a path/],
  ];
  for (const [v, re] of bad) {
    const p = apiUrlProblem(v) ?? "";
    assert.match(p, re, String(v));
    assert.ok(!p.includes("investments-api"), "never the value");
  }
});

test("the build fails listing every problem, never a value", () => {
  assert.equal(buildEnvProblem(ok), null);
  const p = buildEnvProblem({ ...ok, NEXT_PUBLIC_SUPABASE_URL: `${URL_}/`, NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000",
                              VERCEL_ENV: "production" }) ?? "";
  assert.match(p, /^next build refused for the Vercel "production" environment:/);
  assert.match(p, /NEXT_PUBLIC_SUPABASE_URL ends with a slash/);
  assert.match(p, /NEXT_PUBLIC_API_URL must start with https/);
  assert.ok(!p.includes("abcref123") && !p.includes(KEY));
  assert.match(buildEnvProblem({ ...ok, NEXT_PUBLIC_SUPABASE_ANON_KEY: "" }) ?? "", /NEXT_PUBLIC_SUPABASE_ANON_KEY is missing/);
  assert.equal(buildEnvProblem({ NEXT_PUBLIC_DEV_AUTH: "1" }), null);
  assert.notEqual(buildEnvProblem({ ...ok, NEXT_PUBLIC_DEV_AUTH: "true", NEXT_PUBLIC_API_URL: "" }), null);
});

test("local dev (not a production build) may leave the API URL empty", () => {
  assert.deepEqual(publicConfigProblems({ ...ok, NEXT_PUBLIC_API_URL: "" }, false), []);
  assert.equal(publicConfigProblems({ ...ok, NEXT_PUBLIC_API_URL: "" }, true).length, 1);
});

test("the /login message says which one and where", () => {
  assert.match(notConfiguredMessage(["NEXT_PUBLIC_SUPABASE_ANON_KEY"], "preview"),
    /^Sign-in is not configured: NEXT_PUBLIC_SUPABASE_ANON_KEY is missing or empty in this build \(this is a preview/);
});
