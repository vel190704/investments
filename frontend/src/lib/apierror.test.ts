import assert from "node:assert/strict";
import { test } from "node:test";
import { BACKEND_DOWN, messageFromBody, messageFromText, parseErrorText, withSuffix } from "./apierror";

test("string detail is shown as is", () => {
  assert.equal(messageFromBody(409, { detail: "Privacy toggle is off", request_id: "abc" }), "Privacy toggle is off");
});

test("FastAPI validation list becomes field: message, not JSON", () => {
  const body = { detail: [{ loc: ["body", "amount"], msg: "Input should be a valid integer", type: "int_parsing" },
                          { loc: ["query", "kind"], msg: "Field required", type: "missing" }] };
  assert.equal(messageFromBody(422, body), "amount: Input should be a valid integer; kind: Field required");
});

test("importer errors and unknown shapes are readable", () => {
  assert.equal(messageFromBody(422, { detail: { errors: [{ field: "date", message: "bad date" }, { message: "x" }] } }), "date: bad date; x");
  const m = messageFromBody(500, { detail: { weird: [1, 2] } });
  assert.equal(m, "Server error (HTTP 500)");
  assert.ok(!m.includes("{"));
});

test("non-JSON 5xx from the proxy means the backend is down", () => {
  assert.equal(messageFromText(500, "Internal Server Error"), BACKEND_DOWN);
  assert.equal(messageFromText(404, "<html>…</html>"), "Request failed (HTTP 404)");
});

test("suffix round-trips status and request id", () => {
  const t = withSuffix("Privacy toggle is off", 409, "a1b2c3d4e5f6");
  assert.equal(t, "Privacy toggle is off [HTTP 409 · request a1b2c3d4e5f6]");
  assert.deepEqual(parseErrorText(t), { message: "Privacy toggle is off", status: 409, requestId: "a1b2c3d4e5f6" });
  assert.deepEqual(parseErrorText("plain"), { message: "plain", status: null, requestId: null });
  assert.deepEqual(parseErrorText(withSuffix("x", 502, null)), { message: "x", status: 502, requestId: null });
});
