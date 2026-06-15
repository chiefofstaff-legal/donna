// Endpoint contract tests for the widget READ paths (widget-chain, widget-verify).
//
// These cover the security gates — method guards, the session-required
// validation (a caller can never read a shared/global chain), and the
// verify modes — that were previously untested: only web/lib/widget-storage.js
// had coverage, so the HTTP handlers' control-flow (exactly where the
// security-relevant decisions live) was unverified. Node-native (node --test).

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const crypto = require("node:crypto");

const idr = require("../lib/idr.js");
const storage = require("../lib/widget-storage.js");
const chainHandler = require("../api/widget-chain.js");
const verifyHandler = require("../api/widget-verify.js");

const DEMO_KEY = "donna-public-demo-key-2026-05-08";

// Minimal Vercel-style { req, res } doubles. res is chainable like the real one.
function mockRes() {
  const res = { statusCode: 0, body: null, headers: {} };
  res.setHeader = (k, v) => { res.headers[k] = v; return res; };
  res.status = (c) => { res.statusCode = c; return res; };
  res.json = (j) => { res.body = j; return res; };
  return res;
}

// The handlers read process.env[idr.ENV_KEY] at REQUEST time. Set it for the
// duration of an async handler call, then restore — never leak across tests.
async function withKey(fn) {
  const prev = process.env[idr.ENV_KEY];
  process.env[idr.ENV_KEY] = DEMO_KEY;
  try {
    return await fn();
  } finally {
    if (prev === undefined) delete process.env[idr.ENV_KEY];
    else process.env[idr.ENV_KEY] = prev;
  }
}

// ── widget-chain ─────────────────────────────────────────────────────────────

test("widget-chain: non-GET method → 405", async () => {
  const res = mockRes();
  await chainHandler({ method: "POST", query: {} }, res);
  assert.strictEqual(res.statusCode, 405);
  assert.strictEqual(res.body.error, "method_not_allowed");
});

test("widget-chain: missing sessionId → 400 session_required", async () => {
  const res = mockRes();
  await chainHandler({ method: "GET", query: {} }, res);
  assert.strictEqual(res.statusCode, 400);
  assert.strictEqual(res.body.error, "session_required");
});

test("widget-chain: non-UUID sessionId → 400 (cannot reach a shared/global chain)", async () => {
  const res = mockRes();
  await chainHandler({ method: "GET", query: { sessionId: "../../etc/passwd" } }, res);
  assert.strictEqual(res.statusCode, 400);
  assert.strictEqual(res.body.error, "session_required");
});

test("widget-chain: valid sessionId with no entries → 200, count 0, empty list", async () => {
  const res = mockRes();
  await chainHandler({ method: "GET", query: { sessionId: crypto.randomUUID() } }, res);
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.body.ok, true);
  assert.strictEqual(res.body.count, 0);
  assert.deepStrictEqual(res.body.entries, []);
});

// ── widget-verify ────────────────────────────────────────────────────────────

test("widget-verify: non-POST method → 405", async () => {
  const res = mockRes();
  await verifyHandler({ method: "GET" }, res);
  assert.strictEqual(res.statusCode, 405);
  assert.strictEqual(res.body.error, "method_not_allowed");
});

test("widget-verify: signing key not configured → 500 service_unavailable", async () => {
  const prev = process.env[idr.ENV_KEY];
  delete process.env[idr.ENV_KEY];
  try {
    const res = mockRes();
    await verifyHandler({ method: "POST", body: {} }, res);
    assert.strictEqual(res.statusCode, 500);
    assert.strictEqual(res.body.error, "service_unavailable");
  } finally {
    if (prev !== undefined) process.env[idr.ENV_KEY] = prev;
  }
});

test("widget-verify: record mode verifies a self-contained signed record", async () => {
  await withKey(async () => {
    const { record } = idr.sign({ intent: "demo decision", signer: "s", confidence: 0.9, key: DEMO_KEY });
    const res = mockRes();
    await verifyHandler({ method: "POST", body: { record } }, res);
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(res.body.valid, true, res.body.reason || "should verify");
  });
});

test("widget-verify: record mode rejects a tampered record", async () => {
  await withKey(async () => {
    const { record } = idr.sign({ intent: "demo decision", signer: "s", confidence: 0.9, key: DEMO_KEY });
    const tampered = Object.assign({}, record, { intent: "tampered after signing" });
    const res = mockRes();
    await verifyHandler({ method: "POST", body: { record: tampered } }, res);
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(res.body.valid, false);
  });
});

test("widget-verify: chain text over the size cap → 400 chain_too_large", async () => {
  await withKey(async () => {
    const big = "x".repeat(256 * 1024 + 1);
    const res = mockRes();
    await verifyHandler({ method: "POST", body: { chain: big } }, res);
    assert.strictEqual(res.statusCode, 400);
    assert.strictEqual(res.body.error, "chain_too_large");
  });
});

test("widget-verify: default mode without sessionId → 400 session_required", async () => {
  await withKey(async () => {
    const res = mockRes();
    await verifyHandler({ method: "POST", body: {} }, res);
    assert.strictEqual(res.statusCode, 400);
    assert.strictEqual(res.body.error, "session_required");
  });
});

test("widget-verify: default mode, valid sessionId, empty chain → valid:true count 0", async () => {
  await withKey(async () => {
    const res = mockRes();
    await verifyHandler({ method: "POST", body: { sessionId: crypto.randomUUID() } }, res);
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(res.body.valid, true);
    assert.strictEqual(res.body.count, 0);
  });
});
