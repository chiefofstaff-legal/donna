// End-to-end Ed25519 round-trip for the public widget: notarise → store →
// session-verify. This is the regression anchor for the HMAC→Ed25519 switch.
//
// The gold-standard falsifiers here:
//   - a widget-signed record carries a 128-hex Ed25519 signature + scheme
//     "ed25519" (NOT a 64-hex HMAC) — fails if the scheme switch is reverted;
//   - the stored chain verifies against the PUBLIC key alone — fails if the
//     persisted fields (decision_id/confidence/metadata/scheme) drift from the
//     signed payload, or if verify is wired to the wrong key;
//   - a tampered stored entry fails verification — fails if verify is a no-op;
//   - notarise fails LOUD (503) without the private seed — fails if a silent
//     HMAC downgrade is re-introduced.
//
// Node-native (node --test). In-memory storage backend (no KV).

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const crypto = require("node:crypto");

const idr = require("../lib/idr.js");
const storage = require("../lib/widget-storage.js");
const notariseHandler = require("../api/widget-notarise.js");
const verifyHandler = require("../api/widget-verify.js");

// Deterministic test seed — never a production key (32 bytes of 0xaa). Matches
// the mcp-servers + Python parity vectors. Pubkey is DERIVED, never hardcoded.
const TEST_SEED_HEX = "a".repeat(64);
const TEST_PUBKEY_HEX = idr.ed25519PubkeyHex(TEST_SEED_HEX);

function mockRes() {
  const res = { statusCode: 0, body: null, headers: {} };
  res.setHeader = (k, v) => { res.headers[k] = v; return res; };
  res.status = (c) => { res.statusCode = c; return res; };
  res.json = (j) => { res.body = j; return res; };
  return res;
}

// Set the Ed25519 keys (private for sign, public for verify) for the duration
// of an async call, then restore. The widget no longer uses the HMAC key to
// sign, so it is intentionally NOT set here.
async function withEd25519(fn) {
  const prevPriv = process.env[idr.ENV_ED25519_KEY];
  const prevPub = process.env[idr.ENV_ED25519_PUBKEY];
  process.env[idr.ENV_ED25519_KEY] = TEST_SEED_HEX;
  process.env[idr.ENV_ED25519_PUBKEY] = TEST_PUBKEY_HEX;
  try {
    return await fn();
  } finally {
    if (prevPriv === undefined) delete process.env[idr.ENV_ED25519_KEY];
    else process.env[idr.ENV_ED25519_KEY] = prevPriv;
    if (prevPub === undefined) delete process.env[idr.ENV_ED25519_PUBKEY];
    else process.env[idr.ENV_ED25519_PUBKEY] = prevPub;
  }
}

function notariseReq(sessionId, intent) {
  return {
    method: "POST",
    headers: { origin: "https://free.donnaoss.com" },
    body: { sessionId, intent },
    socket: { remoteAddress: "203.0.113.7" },
  };
}

test("widget-notarise signs with Ed25519 (128-hex signature, scheme ed25519)", async () => {
  storage._resetForTests();
  await withEd25519(async () => {
    const res = mockRes();
    await notariseHandler(notariseReq(crypto.randomUUID(), "Approved settlement of demo matter"), res);
    assert.strictEqual(res.statusCode, 200, JSON.stringify(res.body));
    assert.strictEqual(res.body.ok, true);
    assert.match(res.body.record.signature, /^[0-9a-f]{128}$/, "Ed25519 sig is 128 hex chars (HMAC would be 64)");
    assert.strictEqual(res.body.record.scheme, "ed25519");
  });
});

test("widget round-trip: an Ed25519-notarised chain verifies against the PUBLIC key", async () => {
  storage._resetForTests();
  await withEd25519(async () => {
    const sessionId = crypto.randomUUID();
    for (const intent of ["First demo decision", "Second demo decision", "Third demo decision"]) {
      const res = mockRes();
      await notariseHandler(notariseReq(sessionId, intent), res);
      assert.strictEqual(res.statusCode, 200, JSON.stringify(res.body));
    }
    const vres = mockRes();
    await verifyHandler({ method: "POST", body: { sessionId } }, vres);
    assert.strictEqual(vres.statusCode, 200);
    assert.strictEqual(vres.body.valid, true, vres.body.reason || "chain should verify");
    assert.strictEqual(vres.body.count, 3);
  });
});

test("widget round-trip: a single Ed25519 record verifies in record mode", async () => {
  storage._resetForTests();
  await withEd25519(async () => {
    const nres = mockRes();
    await notariseHandler(notariseReq(crypto.randomUUID(), "Self-contained demo record"), nres);
    assert.strictEqual(nres.statusCode, 200);
    const vres = mockRes();
    await verifyHandler({ method: "POST", body: { record: nres.body.record } }, vres);
    assert.strictEqual(vres.statusCode, 200);
    assert.strictEqual(vres.body.valid, true, vres.body.reason || "record should verify");
  });
});

test("widget round-trip: tampering a stored entry breaks Ed25519 verification", async () => {
  storage._resetForTests();
  await withEd25519(async () => {
    const sessionId = crypto.randomUUID();
    const nres = mockRes();
    await notariseHandler(notariseReq(sessionId, "Original intent"), nres);
    assert.strictEqual(nres.statusCode, 200);
    // Tamper the stored intent AFTER signing — the signature no longer matches.
    const chain = await storage.readChain(sessionId);
    chain[0].intent = "Tampered intent";
    storage.__memoryListsForTests().set(storage.chainKeyFor(sessionId), { value: chain, expiresAt: Date.now() + 60000 });
    const vres = mockRes();
    await verifyHandler({ method: "POST", body: { sessionId } }, vres);
    assert.strictEqual(vres.statusCode, 200);
    assert.strictEqual(vres.body.valid, false, "tampered entry must NOT verify");
    assert.strictEqual(vres.body.at, 1);
  });
});

test("widget-notarise fails LOUD (503) without the Ed25519 private seed — never a silent HMAC downgrade", async () => {
  storage._resetForTests();
  const prevPriv = process.env[idr.ENV_ED25519_KEY];
  const prevHmac = process.env[idr.ENV_KEY];
  delete process.env[idr.ENV_ED25519_KEY];
  // Even WITH an HMAC key present, the endpoint must NOT fall back to HMAC.
  process.env[idr.ENV_KEY] = "donna-public-demo-key-2026-05-08";
  try {
    const res = mockRes();
    await notariseHandler(notariseReq(crypto.randomUUID(), "should not sign"), res);
    assert.strictEqual(res.statusCode, 503);
    assert.strictEqual(res.body.error, "service_unavailable");
  } finally {
    if (prevPriv !== undefined) process.env[idr.ENV_ED25519_KEY] = prevPriv;
    if (prevHmac === undefined) delete process.env[idr.ENV_KEY];
    else process.env[idr.ENV_KEY] = prevHmac;
  }
});

test("widget-pubkey publishes the derived PUBLIC key, never the private seed", async () => {
  const pubkeyHandler = require("../api/widget-pubkey.js");
  const prevPriv = process.env[idr.ENV_ED25519_KEY];
  const prevPub = process.env[idr.ENV_ED25519_PUBKEY];
  process.env[idr.ENV_ED25519_KEY] = TEST_SEED_HEX;
  delete process.env[idr.ENV_ED25519_PUBKEY]; // force derivation from the seed
  try {
    const res = mockRes();
    await pubkeyHandler({ method: "GET" }, res);
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(res.body.pubkey, TEST_PUBKEY_HEX);
    assert.strictEqual(res.body.scheme, "ed25519");
    // The private seed must NEVER appear in the response.
    assert.ok(!JSON.stringify(res.body).includes(TEST_SEED_HEX), "private seed must not leak");
  } finally {
    if (prevPriv === undefined) delete process.env[idr.ENV_ED25519_KEY];
    else process.env[idr.ENV_ED25519_KEY] = prevPriv;
    if (prevPub !== undefined) process.env[idr.ENV_ED25519_PUBKEY] = prevPub;
  }
});

test("widget-pubkey: no key configured → 503", async () => {
  const pubkeyHandler = require("../api/widget-pubkey.js");
  const prevPriv = process.env[idr.ENV_ED25519_KEY];
  const prevPub = process.env[idr.ENV_ED25519_PUBKEY];
  delete process.env[idr.ENV_ED25519_KEY];
  delete process.env[idr.ENV_ED25519_PUBKEY];
  try {
    const res = mockRes();
    await pubkeyHandler({ method: "GET" }, res);
    assert.strictEqual(res.statusCode, 503);
    assert.strictEqual(res.body.error, "service_unavailable");
  } finally {
    if (prevPriv !== undefined) process.env[idr.ENV_ED25519_KEY] = prevPriv;
    if (prevPub !== undefined) process.env[idr.ENV_ED25519_PUBKEY] = prevPub;
  }
});
