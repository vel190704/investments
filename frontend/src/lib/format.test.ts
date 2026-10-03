import { test } from "node:test";
import assert from "node:assert/strict";
import { formatINR, formatPct, formatPrice, formatQty, groupIndian } from "./format";

test("Indian digit grouping", () => {
  assert.equal(groupIndian("123"), "123");
  assert.equal(groupIndian("1234"), "1,234");
  assert.equal(groupIndian("123456"), "1,23,456");
  assert.equal(groupIndian("1234567"), "12,34,567");
});

test("formatINR matches backend money.format_inr", () => {
  const cases: [number, string][] = [
    [0, "₹0.00"], [5, "₹0.05"], [12345600, "₹1,23,456.00"], [1234567890, "₹1,23,45,678.90"],
    [-24230, "-₹242.30"], [123456789012345, "₹12,34,56,78,90,123.45"],
  ];
  for (const [p, s] of cases) assert.equal(formatINR(p), s);
  assert.equal(formatINR(12345650, { decimals: false }), "₹1,23,457");
  assert.equal(formatINR(500, { signed: true }), "+₹5.00");
  assert.equal(formatINR(null), "Data unavailable");
});

test("percent, price and quantity", () => {
  assert.equal(formatPct("0.379951"), "38.0%");
  assert.equal(formatPct("-0.00001"), "0.0%");
  assert.equal(formatPct(null), "N/A");
  assert.equal(formatPrice("3693.4"), "₹3,693.40");
  assert.equal(formatPrice("228.4148", 4), "₹228.4148");
  assert.equal(formatPrice("3768.0000"), "₹3,768.00");
  assert.equal(formatPrice("1193.805"), "₹1,193.81");
  assert.equal(formatQty("72.377"), "72.377");
});
