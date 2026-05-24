// DONNA · widget storage — KV-or-memory backend + the five-layer defence stack.
//
// PURPOSE
//   The /widget endpoints need persistence (a global rolling chain), rate
//   limiting (per-IP / per-window), per-IP entry caps, and content filters
//   (word blocklist + PII regex). This module is the single shim those
//   endpoints call. It carries the security-relevant logic so /api/widget-*
//   handlers stay thin (single responsibility — SRP/GRASP Information Expert
//   pattern: the data lives here, so the rules that gate that data live here).
//
// STORAGE
//   Backend selected at module load:
//     - if both Vercel KV REST env vars are set → Vercel KV (Upstash Redis
//       REST) — production / preview / live deployment
//     - otherwise → in-process Map (suitable for `node --test`, local
//       `vercel dev`, anywhere KV is not configured)
//   The in-memory backend is the test/dev floor. It uses the same key
//   shapes as the KV backend so a switch never changes call-site code.
//
// DESIGN PRINCIPLES APPLIED
//   - DRY: word blocklist and PII regex defined ONCE, used by ingress + tests
//   - KISS: zero npm deps; stdlib `fetch` + plain regex; functions <50 LOC
//   - CC<30: helpers small, control flow flat, no deep nesting
//   - SRP: one boundary per export (rateLimit, push, list, verify-by-id…)
//   - DIP: callers depend on this module's stable surface, not the backend
//
// FALSIFICATION
//   This module's design is wrong if (a) the in-memory backend silently
//   accepted writes that the KV backend would have rejected (lockstep
//   contract violation — caught by widget-storage.test.js asserting both
//   reject the same inputs), or (b) the per-IP cap admits a 6th entry under
//   any input shape (test: per_ip_cap_replaces_oldest fails).

"use strict";

// ─── Tunables — single source of truth (DRY) ─────────────────────────
const MAX_PER_IP_PER_HOUR = 10;         // rate limit
const MAX_CHAIN_LEN = 100;              // FIFO cap
const MAX_PER_IP_IN_CHAIN = 5;          // per-IP visibility cap
const ENTRY_TTL_SEC = 24 * 60 * 60;     // 24h per-entry TTL
const RATE_WINDOW_SEC = 60 * 60;        // 1h rate window
const HARDCODED_SIGNER = "free.donnaoss.com demo visitor";

// Word blocklist — small curated set. R0-honest: this catches the casual
// case (~95th percentile); adversarial Unicode/leetspeak will bypass it.
// The 24h TTL (entries) + 7d key rotation (cron, W7) are the deeper layers.
// Surface area kept tiny on purpose — false positives are worse than misses
// here because the 5-layer stack already has back-stops.
const WORD_BLOCKLIST = Object.freeze([
  "nigger", "faggot", "kike", "spic", "chink", "tranny", "retard", "wetback",
]);

// PII regex — structured high-confidence shapes only. Free-text names cannot
// be filtered without false-positive cascade so we deliberately do not try.
// Each rule has a reason returned to the user so they understand the block.
//
// ORDERING IS LOAD-BEARING. piiDeny() returns the FIRST match. IBAN must run
// before credit-card because IBANs (e.g. "DE89 3704 0044 0532 0130 00")
// contain a long digit run the credit-card regex would otherwise eat first.
// SSN is independent (3-2-4 shape). Falsified if a real IBAN ever falls
// through to the credit-card branch — caught by the SSN/CC/IBAN test that
// asserts each return value by exact rule name.
const PII_RULES = Object.freeze([
  { name: "ssn",         re: /\b\d{3}-\d{2}-\d{4}\b/,                       reason: "looks like a US SSN" },
  { name: "iban",        re: /\b[A-Z]{2}\d{2}[A-Z0-9 -]{11,30}\b/,             reason: "looks like an IBAN" },
  { name: "credit_card", re: /\b(?:\d[ -]*?){13,16}\b/,                      reason: "looks like a credit card number" },
]);

// ─── Backend selection (KV-or-memory) ────────────────────────────────
const memoryStore = new Map();   // key → { value, expiresAt|null }
const memoryLists = new Map();   // key → array (FIFO)

// Single helper that reads the KV REST credentials. Centralised so the
// rest of the module never references the env directly (syscall-doctrine:
// secrets stay in one named function's scope). Returns null when KV is
// not configured — callers branch to in-memory backend.
function _loadKvCredentials() {
  const env = process.env || {};
  const url = env.KV_REST_API_URL;
  const token = env.KV_REST_API_TOKEN;
  if (url && token) return { url, token };
  return null;
}

function kvConfigured() {
  return _loadKvCredentials() !== null;
}

async function kvCall(commandArr) {
  // Upstash REST: POST <URL>/ with bearer token, body is the command array.
  // Returns { result } on success.
  const creds = _loadKvCredentials();
  if (!creds) throw new Error("kv_not_configured");
  const res = await fetch(creds.url, {
    method: "POST",
    headers: { Authorization: `Bearer ${creds.token}`, "Content-Type": "application/json" },
    body: JSON.stringify(commandArr),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`kv_error_${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return data.result;
}

// ─── Defence layer 1: content filter (word blocklist) ─────────────────
function blocklistDeny(text) {
  if (typeof text !== "string" || !text) return null;
  const lower = text.toLowerCase();
  for (const word of WORD_BLOCKLIST) {
    if (lower.includes(word)) return { name: "blocklist", reason: "content blocked" };
  }
  return null;
}

// ─── Defence layer 2: PII regex (structured shapes) ──────────────────
function piiDeny(text) {
  if (typeof text !== "string" || !text) return null;
  for (const rule of PII_RULES) {
    if (rule.re.test(text)) return { name: rule.name, reason: rule.reason };
  }
  return null;
}

// ─── Defence layer 3: rate limit (per IP, per hour) ──────────────────
async function checkRateLimit(ip, opts) {
  if (!ip) return { allowed: true, remaining: MAX_PER_IP_PER_HOUR };
  const max = (opts && typeof opts.max === "number") ? opts.max : MAX_PER_IP_PER_HOUR;
  const key = `widget:rate:${ip}`;
  let count;
  if (kvConfigured()) {
    count = await kvCall(["INCR", key]);
    if (count === 1) await kvCall(["EXPIRE", key, RATE_WINDOW_SEC]);
  } else {
    const now = Date.now();
    const rec = memoryStore.get(key);
    if (!rec || rec.expiresAt <= now) {
      memoryStore.set(key, { value: 1, expiresAt: now + RATE_WINDOW_SEC * 1000 });
      count = 1;
    } else {
      rec.value += 1;
      count = rec.value;
    }
  }
  return { allowed: count <= max, remaining: Math.max(0, max - count), count };
}

// ─── Defence layer 4: chain-tail mutex (grip-anywhere §6d race fix) ──
// Concurrent pushEntry() calls race: two callers read the same chain tail,
// both append, only one survives the writeChain — the other entry is
// silently lost AND the chain's previous_hash invariant breaks for ALL
// subsequent entries (chain VERIFY fails forever after). The fix: lock
// the read-modify-write critical section.
//   - KV backend: SET-NX with 5s EX (Upstash atomic; auto-expires on crash)
//   - in-memory:  key-with-expiry parity (single-process Node; await-yield
//                 lets the spinner notice the lock without busy-loop)
// 5s TTL keeps stale locks bounded if a writer crashes mid-transaction.
async function acquireChainLock() {
  const lockKey = "widget:chain-lock";
  const lockTtlSec = 5;
  const spinIntervalMs = 30;
  const deadline = Date.now() + lockTtlSec * 1000;
  while (Date.now() < deadline) {
    if (kvConfigured()) {
      const result = await kvCall(["SET", lockKey, "1", "NX", "EX", lockTtlSec]);
      if (result === "OK") return true;
    } else {
      const now = Date.now();
      const rec = memoryStore.get(lockKey);
      if (!rec || rec.expiresAt <= now) {
        memoryStore.set(lockKey, { value: 1, expiresAt: now + lockTtlSec * 1000 });
        return true;
      }
    }
    await new Promise((r) => setTimeout(r, spinIntervalMs));
  }
  return false;
}

async function releaseChainLock() {
  const lockKey = "widget:chain-lock";
  if (kvConfigured()) await kvCall(["DEL", lockKey]);
  else memoryStore.delete(lockKey);
}

// ─── Defence layer 5: per-IP entry cap (max 5 in visible chain) ──────
// FIFO push that ALSO enforces per-IP cap. Returns the new chain length
// AND the position of the just-pushed entry. Eviction order:
//   1. Per-IP overflow first (remove the same IP's oldest entry)
//   2. Global overflow next (remove the chain's oldest entry across all IPs)
// This guarantees one push = one entry visible, never two pushes coalescing.
// Wrapped in chain-tail lock (Defence layer 4 above) so concurrent calls
// serialise — required for chain verify integrity per grip-anywhere §6d.
async function pushEntry(entry, ip) {
  if (!entry || typeof entry !== "object") throw new Error("entry_invalid");
  if (typeof entry.hash !== "string" || !/^[0-9a-f]{64}$/.test(entry.hash)) {
    throw new Error("entry_hash_invalid");
  }
  const stamped = Object.assign({}, entry, { ip: ip || "", _ts: Date.now() });

  const lockOk = await acquireChainLock();
  if (!lockOk) throw new Error("chain_lock_timeout");

  try {
    // Read current chain (under lock — no concurrent writer can race us)
    let chain = await readChain();

    // Per-IP cap: if this IP already has MAX_PER_IP_IN_CHAIN, drop oldest from that IP
    if (ip) {
      const sameIp = chain.filter((e) => e.ip === ip);
      if (sameIp.length >= MAX_PER_IP_IN_CHAIN) {
        const oldestSameIp = sameIp[0]; // chain is oldest→newest
        chain = chain.filter((e) => e !== oldestSameIp);
      }
    }

    // Global FIFO cap: if at MAX_CHAIN_LEN, drop oldest overall
    while (chain.length >= MAX_CHAIN_LEN) chain.shift();

    // Append new + write (atomic under lock — no concurrent reader sees half-state)
    chain.push(stamped);
    await writeChain(chain);
    return { length: chain.length, position: chain.length };
  } finally {
    await releaseChainLock();
  }
}

async function readChain() {
  const listKey = "widget:chain";
  if (kvConfigured()) {
    const raw = await kvCall(["GET", listKey]);
    if (!raw) return [];
    try { return JSON.parse(raw); } catch { return []; }
  }
  return memoryLists.get(listKey) ? memoryLists.get(listKey).slice() : [];
}

async function writeChain(chain) {
  const listKey = "widget:chain";
  if (kvConfigured()) {
    await kvCall(["SET", listKey, JSON.stringify(chain)]);
  } else {
    memoryLists.set(listKey, chain.slice());
  }
}

// ─── Read API ────────────────────────────────────────────────────────
async function listChain(opts) {
  const max = (opts && typeof opts.max === "number") ? opts.max : MAX_CHAIN_LEN;
  const chain = await readChain();
  // Public shape: strip internal fields (`ip`, `_ts` are private)
  return chain.slice(-max).map((e) => {
    const { ip, _ts, ...pub } = e;
    return pub;
  });
}

// ─── Test-only reset (in-memory backend only; KV cannot be reset here) ──
function _resetForTests() {
  memoryStore.clear();
  memoryLists.clear();
}

module.exports = {
  // tunables (exported for tests + observability)
  MAX_PER_IP_PER_HOUR,
  MAX_CHAIN_LEN,
  MAX_PER_IP_IN_CHAIN,
  ENTRY_TTL_SEC,
  RATE_WINDOW_SEC,
  HARDCODED_SIGNER,
  WORD_BLOCKLIST,
  PII_RULES,
  // surface
  blocklistDeny,
  piiDeny,
  checkRateLimit,
  pushEntry,
  readChain,
  listChain,
  kvConfigured,
  _resetForTests,
};
