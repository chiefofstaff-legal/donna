// Parity tests for web/lib/idr.js — Node-native (node --test).
//
// The gold-standard falsifier is Test 4 (PROBAT.md end-to-end verify) and
// Test 5 (cross-validation with bin/notarise via subprocess).

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const idr = require("../lib/idr.js");

const DEMO_KEY = "donna-public-demo-key-2026-05-08";
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const NOTARISE_BIN = path.join(REPO_ROOT, "bin", "notarise");

function fresh(opts) {
  return idr.sign(Object.assign({
    intent: "test intent",
    signer: "test-signer",
    confidence: 0.9,
    metadata: { test: true },
    key: DEMO_KEY,
  }, opts || {}));
}

// Build a real DEMO_KEY-signed, hash-chained chain of `n` entries. Returns the
// records and the PROBAT-shaped markdown text that idr.verifyChain AND
// bin/notarise both parse. Shared by the gold-standard + cross-validation tests.
function buildDemoChain(n) {
  const recs = [];
  let prev = idr.GENESIS_PREVIOUS_HASH;
  for (let i = 0; i < n; i++) {
    const out = idr.sign({
      intent: `chain entry ${i + 1}`,
      signer: "parity-test",
      confidence: 0.9,
      previousHash: prev,
      metadata: { i },
      key: DEMO_KEY,
    });
    recs.push(out.record);
    prev = out.hash;
  }
  // null replacer + indent=2 — do NOT pass a key whitelist as the 2nd arg; the
  // whitelist also filters NESTED keys, dropping metadata.* and breaking parity.
  const text = recs.map((r) => "```idr\n" + JSON.stringify(r, null, 2) + "\n```\n").join("\n");
  return { recs, text };
}

test("sign() produces a record with all required fields", () => {
  const { record, hash } = fresh();
  for (const f of ["decision_id", "timestamp", "protocol", "intent", "signer",
                    "confidence", "previous_hash", "metadata", "signature"]) {
    assert.ok(Object.prototype.hasOwnProperty.call(record, f), `missing field ${f}`);
  }
  assert.strictEqual(record.protocol, "happi/1.1");
  assert.strictEqual(record.previous_hash, "0".repeat(64));
  assert.match(record.signature, /^[0-9a-f]{64}$/);
  assert.match(hash, /^[0-9a-f]{64}$/);
});

test("verifyRecord() accepts a freshly-signed record", () => {
  const { record } = fresh();
  const r = idr.verifyRecord(record, DEMO_KEY);
  assert.strictEqual(r.valid, true, r.reason || "should be valid");
});

test("verifyRecord() rejects a tampered record", () => {
  const { record } = fresh();
  const tampered = Object.assign({}, record, { intent: "tampered intent" });
  const r = idr.verifyRecord(tampered, DEMO_KEY);
  assert.strictEqual(r.valid, false);
  assert.match(r.reason, /signature mismatch/);
});

test("verifyChain() accepts a freshly-signed 3-entry chain end-to-end (gold-standard parity)", () => {
  // Verify idr.verifyChain end-to-end on a real DEMO_KEY-signed, hash-chained
  // chain. We do NOT verify the live PROBAT.md here: the probat bot appends
  // entries signed with the PRODUCTION key, which a demo-key test structurally
  // cannot verify (it fails at the first production-signed entry). The live
  // PROBAT chain is verified with the production key by the CI "Verify PROBAT
  // chain" workflow; this test owns the demo-key verifyChain round-trip.
  const { text } = buildDemoChain(3);
  const result = idr.verifyChain("# gold-standard parity\n\n" + text, DEMO_KEY);
  assert.strictEqual(result.valid, true,
    `chain verify failed: ${result.reason || ""} (at entry ${result.at || "?"})`);
  assert.strictEqual(result.count, 3, `expected 3 IDRs, got ${result.count}`);
});

test("cross-validation: bin/notarise verifies what web/lib/idr.js signed", { skip: !fs.existsSync(NOTARISE_BIN) }, () => {
  // Sign three chained records in JS, write a PROBAT-shaped chain, then ask
  // the Python signer to verify it. Exit code 0 = byte-identical canonical
  // form on both sides.
  const { text } = buildDemoChain(3);
  const tmp = path.join(os.tmpdir(), `donna-parity-${process.pid}-${Date.now()}.md`);
  fs.writeFileSync(tmp, "# parity\n\n" + text);
  try {
    const proc = spawnSync(NOTARISE_BIN, ["verify", "--chain", tmp], {
      env: Object.assign({}, process.env, { DONNA_NOTARISE_KEY: DEMO_KEY }),
      encoding: "utf8",
    });
    assert.strictEqual(proc.status, 0,
      `bin/notarise verify exited ${proc.status}: stderr=${proc.stderr} stdout=${proc.stdout}`);
  } finally {
    try { fs.unlinkSync(tmp); } catch { /* best-effort */ }
  }
});
