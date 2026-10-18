import assert from "node:assert/strict";
import { test } from "node:test";
import { previewProblem, supabaseRef } from "./envguard";

test("a preview signs in only against an allowed project", () => {
  assert.equal(previewProblem("preview", "https://prevref.supabase.co", "prevref"), null);
  assert.match(previewProblem("preview", "https://prodref.supabase.co", "prevref") ?? "", /not on/);
  assert.match(previewProblem("preview", "https://prevref.supabase.co", "") ?? "", /no NEXT_PUBLIC_PREVIEW/);
  assert.match(previewProblem("preview", "https://prevref.supabase.co.evil.example", "prevref") ?? "", /not on/);
});

test("production and local builds are not affected", () => {
  for (const env of ["production", "development", undefined]) assert.equal(previewProblem(env, "https://prodref.supabase.co", ""), null);
});

test("ref parsing", () => {
  assert.equal(supabaseRef("https://AbC.supabase.co/"), "abc");
  assert.equal(supabaseRef("http://abc.supabase.co"), null);
});
