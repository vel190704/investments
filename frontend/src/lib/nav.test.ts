import assert from "node:assert/strict";
import { test } from "node:test";
import { ADVANCED, ALWAYS_VISIBLE, GROUPS, isAdvanced, visibleGroups } from "./nav";

const hrefs = (simple: boolean, isAdmin = false) =>
  visibleGroups(GROUPS, { isAdmin, simple }).flatMap((g) => g.links.map((l) => l.href));

test("simple mode hides exactly the advanced pages", () => {
  const full = hrefs(false);
  const simple = hrefs(true);
  assert.deepEqual(full.filter((h) => !simple.includes(h)).sort(), [...ADVANCED].sort());
  for (const a of ADVANCED) assert.ok(full.includes(a), `${a} exists in the full menu`);
});

test("the core pages stay visible in every mode", () => {
  for (const simple of [true, false]) for (const isAdmin of [true, false]) {
    const shown = hrefs(simple, isAdmin);
    for (const h of ALWAYS_VISIBLE) assert.ok(shown.includes(h), `${h} visible (simple=${simple}, admin=${isAdmin})`);
  }
});

test("admin-only links are for admins only", () => {
  assert.ok(!hrefs(false).includes("/admin") && hrefs(false, true).includes("/admin"));
});

test("isAdvanced", () => {
  assert.ok(isAdvanced("/valuation") && isAdvanced("/macro") && !isAdvanced("/") && !isAdvanced("/allocation"));
});
