// Widget storage tests — Node-native (`node --test`).
//
// Goodhart guard: every assertion below asserts a RETURNED VALUE that
// changes under a real mutation (per Rule 14). No call-count tests. No
// internal mocking of the unit under test. Each test names the mutation
// that would fail it.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const storage = require("../lib/widget-storage.js");

function freshEntry(hash, extra) {
  // Build a syntactically-valid entry shape that pushEntry accepts.
  const baseHash = hash || ("a".repeat(64));
  return Object.assign({ hash: baseHash, intent: "test intent", ts: "2026-05-24T00:00:00Z" }, extra || {});
}

test("blocklistDeny: blocks a slur, allows clean text", () => {
  assert.strictEqual(storage.blocklistDeny("entirely clean text"), null);
  const blocked = storage.blocklistDeny("you fucking faggot");
  assert.ok(blocked, "expected blocklist hit");
  assert.strictEqual(blocked.name, "blocklist");
  // Mutation that would fail this: removing the lowercase normalisation,
  // or shrinking WORD_BLOCKLIST to [].
});

test("piiDeny: blocks SSN/credit-card/IBAN patterns", () => {
  assert.strictEqual(storage.piiDeny("nothing to see here"), null);
  const ssn = storage.piiDeny("My SSN is 555-44-3333 honestly");
  assert.ok(ssn, "expected SSN match");
  assert.strictEqual(ssn.name, "ssn");

  const cc = storage.piiDeny("card 4111 1111 1111 1111");
  assert.ok(cc, "expected credit_card match");
  assert.strictEqual(cc.name, "credit_card");

  const iban = storage.piiDeny("paid via DE89 3704 0044 0532 0130 00");
  assert.ok(iban, "expected iban match");
  assert.strictEqual(iban.name, "iban");
  // Mutation that would fail this: deleting any of the PII_RULES entries
  // or weakening the regex to ^$.
});

test("checkRateLimit: 10 succeed, 11th denies", async () => {
  storage._resetForTests();
  const ip = "10.0.0.1";
  for (let i = 1; i <= 10; i++) {
    const r = await storage.checkRateLimit(ip);
    assert.strictEqual(r.allowed, true, `request ${i} should be allowed; got ${JSON.stringify(r)}`);
  }
  const r11 = await storage.checkRateLimit(ip);
  assert.strictEqual(r11.allowed, false, `11th request should be denied; got ${JSON.stringify(r11)}`);
  // Mutation that would fail this: raising MAX_PER_IP_PER_HOUR to 100,
  // or comparing `>` instead of `<=` in the allowed check.
});

test("checkRateLimit: separate IPs have separate quotas", async () => {
  storage._resetForTests();
  for (let i = 0; i < 10; i++) await storage.checkRateLimit("10.0.0.2");
  const otherIp = await storage.checkRateLimit("10.0.0.3");
  assert.strictEqual(otherIp.allowed, true, "different IP must not inherit prior IP's count");
  // Mutation: using a single global counter (no per-IP keying).
});

test("pushEntry: FIFO evicts oldest at MAX_CHAIN_LEN (=100)", async () => {
  storage._resetForTests();
  // Push 101 entries from rotating IPs (avoid the per-IP cap firing).
  for (let i = 0; i < 101; i++) {
    const hash = i.toString(16).padStart(64, "0");
    const ip = `10.0.${Math.floor(i / 4)}.${i % 4}`; // distinct IPs
    await storage.pushEntry(freshEntry(hash, { intent: `entry ${i}` }), ip);
  }
  const chain = await storage.listChain();
  assert.strictEqual(chain.length, 100, `chain length capped at 100; got ${chain.length}`);
  // The 0th-indexed entry (first pushed, hash 000…000) must be evicted.
  const firstHash = "0".repeat(64);
  assert.ok(!chain.some((e) => e.hash === firstHash),
    "entry 0 should have been FIFO-evicted by the 101st push");
  // Mutation that would fail this: removing the `while (chain.length >= MAX_CHAIN_LEN) chain.shift()` line.
});

test("pushEntry: per-IP cap drops same-IP oldest on the 6th push", async () => {
  storage._resetForTests();
  const ip = "10.1.1.1";
  // Push 6 entries from the same IP. Only 5 should remain visible.
  for (let i = 0; i < 6; i++) {
    const hash = ("b" + i.toString(16)).padEnd(64, "0");
    await storage.pushEntry(freshEntry(hash, { intent: `same-ip ${i}` }), ip);
  }
  const chain = await storage.listChain();
  const sameIp = chain.filter((e) => e.intent && e.intent.startsWith("same-ip"));
  assert.strictEqual(sameIp.length, 5, `per-IP cap should be 5; got ${sameIp.length}`);
  // The first push (intent: "same-ip 0") must be evicted; the last 5 remain.
  assert.ok(!sameIp.some((e) => e.intent === "same-ip 0"),
    "first same-IP entry should have been evicted by the per-IP cap");
  assert.ok(sameIp.some((e) => e.intent === "same-ip 5"),
    "latest same-IP entry should remain");
  // Mutation: removing the per-IP eviction block.
});

test("pushEntry: rejects malformed hash (defence-in-depth on input shape)", async () => {
  storage._resetForTests();
  await assert.rejects(
    () => storage.pushEntry({ hash: "not-hex" }, "10.0.0.4"),
    /entry_hash_invalid/,
    "non-hex hash should be rejected"
  );
  await assert.rejects(
    () => storage.pushEntry({ hash: "a".repeat(63) }, "10.0.0.5"),
    /entry_hash_invalid/,
    "wrong-length hash should be rejected"
  );
  // Mutation: dropping the regex guard at the top of pushEntry.
});

test("listChain: strips internal fields (ip, _ts) before returning", async () => {
  storage._resetForTests();
  const ip = "10.2.2.2";
  await storage.pushEntry(freshEntry("c".repeat(64), { intent: "leak-check" }), ip);
  const chain = await storage.listChain();
  assert.strictEqual(chain.length, 1);
  assert.strictEqual(chain[0].intent, "leak-check");
  assert.ok(!("ip" in chain[0]), `public chain entry leaked 'ip' field: ${JSON.stringify(chain[0])}`);
  assert.ok(!("_ts" in chain[0]), `public chain entry leaked '_ts' field: ${JSON.stringify(chain[0])}`);
  // Mutation: returning the raw chain without stripping privates.
});

test("HARDCODED_SIGNER is the exact council-ratified literal", () => {
  // The widget endpoint is contractually bound to this signer value (per
  // Role 4 vector f). Changing it requires updating every audit and the
  // Goodhart test that asserts impersonation is impossible.
  assert.strictEqual(storage.HARDCODED_SIGNER, "free.donnaoss.com demo visitor");
  // Mutation: relaxing the signer to accept user input would change this
  // constant or remove its use in the endpoint.
});
