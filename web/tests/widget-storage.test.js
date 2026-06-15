// Widget storage tests — Node-native (`node --test`).
//
// Goodhart guard: every assertion below asserts a RETURNED VALUE that
// changes under a real mutation (per Rule 14). No call-count tests. No
// internal mocking of the unit under test. Each test names the mutation
// that would fail it.
//
// API NOTE (P0.1 reshape): the chain is now PER-SESSION. pushEntry/readChain/
// listChain all take a sessionId. pushEntry signs INSIDE its lock via a
// buildEntry(prevHash) callback (TOCTOU-safe). The `pushSigned` helper below
// wraps that callback so push-and-assert tests stay readable.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const crypto = require("node:crypto");

const storage = require("../lib/widget-storage.js");

// A well-formed UUID per test (real shape, so isValidSessionId accepts it).
function freshSession() {
  return crypto.randomUUID();
}

// Push a pre-shaped entry into a session chain. `extra` lets a test set
// intent / override fields. Returns the pushEntry result ({position, entry,
// previousHash, ...}). The buildEntry callback ignores prevHash for the
// fixed-hash tests (FIFO/per-IP/concurrency don't need a real signature) —
// the TOCTOU test below DOES use prevHash to build a real signed chain.
async function pushSigned(sessionId, ip, hash, extra) {
  const baseHash = hash || ("a".repeat(64));
  return storage.pushEntry(sessionId, ip, function () {
    return Object.assign(
      { hash: baseHash, intent: "test intent", ts: "2026-05-24T00:00:00Z" },
      extra || {},
    );
  });
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
  const sid = freshSession();
  // Push 101 entries from rotating IPs (avoid the per-IP cap firing).
  for (let i = 0; i < 101; i++) {
    const hash = i.toString(16).padStart(64, "0");
    const ip = `10.0.${Math.floor(i / 4)}.${i % 4}`; // distinct IPs
    await pushSigned(sid, ip, hash, { intent: `entry ${i}` });
  }
  const chain = await storage.listChain(sid);
  assert.strictEqual(chain.length, 100, `chain length capped at 100; got ${chain.length}`);
  // The 0th-indexed entry (first pushed, hash 000…000) must be evicted.
  const firstHash = "0".repeat(64);
  assert.ok(!chain.some((e) => e.hash === firstHash),
    "entry 0 should have been FIFO-evicted by the 101st push");
  // Mutation that would fail this: removing the `while (chain.length >= MAX_CHAIN_LEN) chain.shift()` line.
});

test("pushEntry: per-IP cap drops same-IP oldest on the 6th push", async () => {
  storage._resetForTests();
  const sid = freshSession();
  const ip = "10.1.1.1";
  // Push 6 entries from the same IP. Only 5 should remain visible.
  for (let i = 0; i < 6; i++) {
    const hash = ("b" + i.toString(16)).padEnd(64, "0");
    await pushSigned(sid, ip, hash, { intent: `same-ip ${i}` });
  }
  const chain = await storage.listChain(sid);
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
  const sid = freshSession();
  await assert.rejects(
    () => pushSigned(sid, "10.0.0.4", "not-hex"),
    /entry_hash_invalid/,
    "non-hex hash should be rejected"
  );
  await assert.rejects(
    () => pushSigned(sid, "10.0.0.5", "a".repeat(63)),
    /entry_hash_invalid/,
    "wrong-length hash should be rejected"
  );
  // Mutation: dropping the regex guard inside pushEntry.
});

test("listChain: strips internal fields (ip, _ts) before returning", async () => {
  storage._resetForTests();
  const sid = freshSession();
  const ip = "10.2.2.2";
  await pushSigned(sid, ip, "c".repeat(64), { intent: "leak-check" });
  const chain = await storage.listChain(sid);
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

test("pushEntry: 10 concurrent pushes all become verifiable chain entries (race-lock guard)", async () => {
  storage._resetForTests();
  const sid = freshSession();
  // Simulate 10 concurrent POSTs hitting pushEntry simultaneously.
  // Without the chain-tail lock, read-modify-write races silently drop
  // entries and break the chain's previous_hash invariant (grip-anywhere
  // §6d). Use distinct IPs to avoid the per-IP cap firing.
  const promises = [];
  for (let i = 0; i < 10; i++) {
    const hash = ("d" + i.toString(16)).padEnd(64, "0");
    const ip = `10.4.0.${i}`;
    promises.push(pushSigned(sid, ip, hash, { intent: `concurrent ${i}` }));
  }
  await Promise.all(promises);
  const chain = await storage.listChain(sid);
  assert.strictEqual(chain.length, 10, `all 10 concurrent pushes should land; got ${chain.length}`);
  const uniqueHashes = new Set(chain.map((e) => e.hash));
  assert.strictEqual(uniqueHashes.size, 10, `expected 10 unique hashes; got ${uniqueHashes.size} (race lost an entry)`);
  // Mutation that would fail this: removing acquireChainLock / try-finally /
  // releaseChainLock wrapping in pushEntry → concurrent read-modify-write
  // race; entries overwrite each other; some hashes missing from chain.
});

test("piiDeny: IBAN regex terminates under 50ms on adversarial input (ReDoS guard)", () => {
  // Per grip-anywhere P1-B: the previous IBAN regex
  // /\b[A-Z]{2}\d{2}[ -]?(?:[A-Z0-9][ -]?){11,30}\b/ is catastrophic-
  // backtracking-prone. Fixed shape flattens the alternation to
  // /\b[A-Z]{2}\d{2}[A-Z0-9 -]{11,30}\b/ which is linear-time.
  const adversarial = "DE89 " + "1 ".repeat(500) + "x";
  const start = Date.now();
  storage.piiDeny(adversarial);
  const elapsed = Date.now() - start;
  assert.ok(elapsed < 50, `IBAN regex should terminate <50ms; took ${elapsed}ms (ReDoS regression)`);
  // Mutation that would fail this: reintroducing the
  // /\b[A-Z]{2}\d{2}[ -]?(?:[A-Z0-9][ -]?){11,30}\b/ catastrophic-backtracking
  // shape, OR any other regex with an `(a+)+`-class signature on the IBAN rule.
});

// ─────────────────────────────────────────────────────────────────────
// RESHAPE (P0.1) — session-private chains, TTL enforcement, TOCTOU fix
// ─────────────────────────────────────────────────────────────────────

test("isValidSessionId: accepts a real UUID, rejects everything else", () => {
  assert.strictEqual(storage.isValidSessionId(crypto.randomUUID()), true);
  assert.strictEqual(storage.isValidSessionId("not-a-uuid"), false);
  assert.strictEqual(storage.isValidSessionId(""), false);
  assert.strictEqual(storage.isValidSessionId(null), false);
  assert.strictEqual(storage.isValidSessionId(undefined), false);
  // A shared-key smuggling attempt must be rejected (no path/global key).
  assert.strictEqual(storage.isValidSessionId("widget:chain"), false);
  assert.strictEqual(storage.isValidSessionId("../../etc/passwd"), false);
  // Mutation that would fail this: loosening UUID_RE to .* or accepting any string.
});

test("chainKeyFor: throws invalid_session on a non-UUID (no silent global-key coercion)", () => {
  const sid = crypto.randomUUID();
  assert.strictEqual(storage.chainKeyFor(sid), `widget:chain:${sid}`);
  assert.throws(() => storage.chainKeyFor("global"), /invalid_session/);
  assert.throws(() => storage.chainKeyFor(""), /invalid_session/);
  // Mutation that would fail this: returning a fixed "widget:chain" key when
  // sessionId is missing — i.e. reverting to a single shared chain.
});

test("per-session chain isolation: session A cannot see session B's chain", async () => {
  storage._resetForTests();
  const sidA = freshSession();
  const sidB = freshSession();
  await pushSigned(sidA, "10.5.0.1", "a".repeat(64), { intent: "A-secret" });
  await pushSigned(sidB, "10.5.0.2", "b".repeat(64), { intent: "B-secret" });

  const chainA = await storage.listChain(sidA);
  const chainB = await storage.listChain(sidB);

  assert.strictEqual(chainA.length, 1, "session A sees only its own 1 entry");
  assert.strictEqual(chainB.length, 1, "session B sees only its own 1 entry");
  assert.strictEqual(chainA[0].intent, "A-secret");
  assert.strictEqual(chainB[0].intent, "B-secret");
  // The killing assertion: A's chain must NOT contain B's entry and vice-versa.
  assert.ok(!chainA.some((e) => e.intent === "B-secret"),
    "session A leaked session B's entry — chain is not session-private");
  assert.ok(!chainB.some((e) => e.intent === "A-secret"),
    "session B leaked session A's entry — chain is not session-private");
  // Mutation that would fail this: keying readChain/writeChain on a single
  // shared "widget:chain" key instead of per-session — both chains would
  // contain BOTH entries.
});

test("readChain rejects a missing/invalid sessionId (cannot read a global chain)", async () => {
  storage._resetForTests();
  await assert.rejects(() => storage.readChain(undefined), /invalid_session/);
  await assert.rejects(() => storage.readChain("global"), /invalid_session/);
  await assert.rejects(() => storage.listChain("global"), /invalid_session/);
  // Mutation: defaulting an absent sessionId to a shared key would let these
  // resolve instead of throwing.
});

test("TTL is set on every write (memory parity for EX ENTRY_TTL_SEC)", async () => {
  storage._resetForTests();
  const sid = freshSession();
  const before = Date.now();
  await pushSigned(sid, "10.6.0.1", "e".repeat(64), { intent: "ttl-check" });
  const after = Date.now();

  // Reach into the memory backend's record to assert an expiresAt was stamped.
  // (KV path stamps it via SET ... EX; this asserts the parity invariant on
  // the in-memory floor that tests run against.)
  const lists = storage.__memoryListsForTests
    ? storage.__memoryListsForTests()
    : null;
  assert.ok(lists, "test hook __memoryListsForTests must be exposed");
  const rec = lists.get(`widget:chain:${sid}`);
  assert.ok(rec, "session chain record must exist after a write");
  assert.ok(typeof rec.expiresAt === "number", "write must stamp a numeric expiresAt (TTL)");
  // Expiry must be ~24h ahead — within the window the write happened.
  const ttlMs = storage.ENTRY_TTL_SEC * 1000;
  assert.ok(rec.expiresAt >= before + ttlMs, `expiresAt too early: ${rec.expiresAt} < ${before + ttlMs}`);
  assert.ok(rec.expiresAt <= after + ttlMs, `expiresAt too late: ${rec.expiresAt} > ${after + ttlMs}`);
  // Mutation that would fail this: writing the chain WITHOUT the EX/expiresAt
  // (the original bug — ENTRY_TTL_SEC declared but never applied) → rec.expiresAt
  // would be undefined.
});

test("expired session chain reads as empty (TTL is honoured on read)", async () => {
  storage._resetForTests();
  const sid = freshSession();
  await pushSigned(sid, "10.6.0.2", "f".repeat(64), { intent: "will-expire" });

  // Force-expire the record by rewinding its expiresAt into the past.
  const lists = storage.__memoryListsForTests();
  const rec = lists.get(`widget:chain:${sid}`);
  rec.expiresAt = Date.now() - 1;

  const chain = await storage.listChain(sid);
  assert.strictEqual(chain.length, 0, "an expired session chain must read as empty");
  // Mutation that would fail this: readChain ignoring expiresAt → the stale
  // entry would still be returned.
});

test("TOCTOU: real signed chain stays verifiable under concurrent appends (prev_hash inside lock)", async () => {
  // This is the integrity heart of the reshape. Sign REAL records inside the
  // lock via buildEntry(prevHash), concurrently. Each entry's previous_hash
  // must equal the running tail hash — a serial, unbroken chain. If
  // previous_hash were computed OUTSIDE the lock (the old code), a concurrent
  // append would land between read+sign and the chain would break.
  const idr = require("../lib/idr.js");
  storage._resetForTests();
  const sid = freshSession();
  const KEY = "toctou-test-key";

  // Capture the FULL signed record each push produced, keyed by hash, so we
  // can re-verify the exact bytes that were signed (the stored chain entry is
  // a subset that omits decision_id/metadata, so reconstruction must use the
  // captured full record, not a guessed one).
  const signedByHash = new Map();

  // 8 concurrent notarise-style pushes, each signing under the locked prev.
  const promises = [];
  for (let i = 0; i < 8; i++) {
    promises.push(storage.pushEntry(sid, `10.7.0.${i}`, function (prevHash) {
      const out = idr.sign({
        intent: `toctou ${i}`,
        signer: storage.HARDCODED_SIGNER,
        confidence: 1.0,
        previousHash: prevHash,
        metadata: { source: "widget" },
        key: KEY,
      });
      signedByHash.set(out.hash, out.record);
      return {
        hash: out.hash,
        intent: `toctou ${i}`,
        ts: out.record.timestamp,
        signature: out.record.signature,
        previous_hash: out.record.previous_hash,
        signer: out.record.signer,
      };
    }));
  }
  await Promise.all(promises);

  const chain = await storage.listChain(sid);
  assert.strictEqual(chain.length, 8, `all 8 signed pushes should land; got ${chain.length}`);

  // Walk the chain: entry[i].previous_hash MUST equal entry[i-1].hash, and the
  // first must be GENESIS. This is the invariant the TOCTOU fix guarantees.
  let expectedPrev = storage.GENESIS_PREVIOUS_HASH;
  for (let i = 0; i < chain.length; i++) {
    assert.strictEqual(
      chain[i].previous_hash, expectedPrev,
      `entry ${i} previous_hash broken: expected ${expectedPrev.slice(0, 8)}…, got ${(chain[i].previous_hash || "").slice(0, 8)}… (TOCTOU race produced a broken chain)`,
    );
    // Each entry's stored signature must verify against the exact record that
    // was signed under the lock (looked up by hash) — proving the prev used to
    // sign equals the prev now in the chain.
    const fullRecord = signedByHash.get(chain[i].hash);
    assert.ok(fullRecord, `no captured signed record for entry ${i} hash`);
    assert.strictEqual(fullRecord.previous_hash, expectedPrev,
      `entry ${i} was SIGNED with a stale previous_hash (${(fullRecord.previous_hash || "").slice(0, 8)}…) ≠ chain prev ${expectedPrev.slice(0, 8)}… — TOCTOU window open`);
    assert.strictEqual(idr.verifyRecord(fullRecord, KEY).valid, true, `entry ${i} failed signature verify`);
    expectedPrev = chain[i].hash;
  }
  // Mutation that would fail this: computing previous_hash from an UNLOCKED
  // read in the handler (the old widget-notarise.js) → under concurrency two
  // entries get the same previous_hash, the signed-prev ≠ chain-prev assertion
  // (or the chain walk) breaks.
});
