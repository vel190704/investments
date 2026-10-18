import assert from "node:assert/strict";
import { test } from "node:test";
import { FEEDBACK_NOTE, MAX_FEEDBACK, feedbackPage, feedbackProblem } from "./feedback";

test("the limit is 2,000 characters after trimming", () => {
  assert.equal(MAX_FEEDBACK, 2000);
  assert.equal(feedbackProblem("x".repeat(2000)), null);
  assert.equal(feedbackProblem(`  ${"x".repeat(2000)}  `), null);
  assert.match(feedbackProblem("x".repeat(2001)) ?? "", /2,000 characters \(this is 2,001\)/);
  assert.equal(feedbackProblem("   "), "Write something first.");
});

test("the note warns against account numbers and figures", () => {
  assert.match(FEEDBACK_NOTE, /account numbers/);
  assert.match(FEEDBACK_NOTE, /financial figures/);
});

test("only the page path is sent", () => {
  assert.equal(feedbackPage("/holdings?symbol=LT#x"), "/holdings");
  assert.equal(feedbackPage(""), "/");
});
