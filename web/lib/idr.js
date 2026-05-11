// DONNA · IDR (Intent Decision Record) — Node port of bin/notarise (Python).
//
// Stdlib only. CommonJS. Mirrors the canonical Python signer/verifier byte-for-byte:
// HMAC-SHA256 over canonical JSON (sort_keys=True, separators=(",", ":")), with
// signature field excluded from the canonical payload (signature signs the rest).
//
// Public API:
//   sign({ intent, signer, confidence, previousHash, metadata, decisionId, timestamp, key })
//     -> { record, hash }
//   verifyRecord(record, key) -> { valid: true } | { valid: false, reason }
//   verifyChain(chainText, key) -> { valid: true, count } | { valid: false, reason, at }
//   parseChain(text) -> [record, ...]
//
// Protocol reference: happi.md v1.1 · Python source: ../../bin/notarise

"use strict";

const crypto = require("crypto");

const GENESIS_PREVIOUS_HASH = "0".repeat(64);
const PROTOCOL_VERSION = "happi/1.1";
const SIGNATURE_ALGORITHM = "HMAC-SHA256";
const ENV_KEY = "DONNA_NOTARISE_KEY";

// Canonical JSON: recursive sort_keys, no whitespace separators, ASCII-only.
// Matches Python's json.dumps(d, sort_keys=True, separators=(",", ":")) which
// has ensure_ascii=True by default — non-ASCII chars become \uXXXX literals.
// Without this, the em-dash in PROBAT entry 3 (and any future non-ASCII
// content) breaks signature parity with bin/notarise.
function escapeAscii(s) {
  // Start from JSON.stringify so quotes, backslashes, control chars, and
  // surrogate pairs are already encoded; then re-encode any code unit > 0x7E
  // as \uXXXX. Surrogate pairs come through as two halves which are each
  // > 0x7E and emitted as 👍 — matching Python's output exactly.
  const json = JSON.stringify(s);
  let out = "";
  for (let i = 0; i < json.length; i++) {
    const cu = json.charCodeAt(i);
    if (cu > 0x7E) {
      out += "\\u" + cu.toString(16).padStart(4, "0");
    } else {
      out += json[i];
    }
  }
  return out;
}

function stableStringify(val) {
  if (val === null || val === undefined) return "null";
  if (typeof val === "string") return escapeAscii(val);
  if (typeof val !== "object") return JSON.stringify(val);
  if (Array.isArray(val)) return "[" + val.map(stableStringify).join(",") + "]";
  const keys = Object.keys(val).sort();
  return "{" + keys.map((k) => escapeAscii(k) + ":" + stableStringify(val[k])).join(",") + "}";
}

function canonicalPayload(record) {
  const copy = Object.assign({}, record);
  delete copy.signature;
  return stableStringify(copy);
}

function hashRecord(record) {
  return crypto.createHash("sha256").update(canonicalPayload(record), "utf8").digest("hex");
}

function hmacSign(payloadStr, key) {
  return crypto.createHmac("sha256", key).update(payloadStr, "utf8").digest("hex");
}

function isoTimestamp(when) {
  const d = when instanceof Date ? when : new Date(when || Date.now());
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

function defaultDecisionId() {
  // Mirrors Python's "idr_<unix_nanos>" shape closely enough for parity (we use ms*1e6).
  return `idr_${Date.now() * 1_000_000}`;
}

// Build + sign an IDR. Returns { record, hash }.
function sign(opts) {
  const opts_ = opts || {};
  const key = opts_.key || process.env[ENV_KEY];
  if (!key) {
    const err = new Error(`${ENV_KEY} not set`);
    err.code = "missing_key";
    throw err;
  }
  if (typeof opts_.intent !== "string" || !opts_.intent) throw new Error("intent required");
  if (typeof opts_.signer !== "string" || !opts_.signer) throw new Error("signer required");
  const confidence = typeof opts_.confidence === "number" ? opts_.confidence : 1.0;
  if (!(confidence >= 0.0 && confidence <= 1.0)) throw new Error("confidence out of [0,1]");

  // Field order does NOT matter on the wire (canonical sort handles it),
  // but we mirror the Python dataclass order for human readability.
  const record = {
    decision_id: opts_.decisionId || defaultDecisionId(),
    timestamp: opts_.timestamp || isoTimestamp(),
    protocol: PROTOCOL_VERSION,
    intent: opts_.intent,
    signer: opts_.signer,
    confidence,
    previous_hash: opts_.previousHash || GENESIS_PREVIOUS_HASH,
    metadata: opts_.metadata && typeof opts_.metadata === "object" ? opts_.metadata : {},
    signature: "",
  };
  record.signature = hmacSign(canonicalPayload(record), key);
  return { record, hash: hashRecord(record) };
}

function verifyRecord(record, key) {
  if (!record || typeof record !== "object") return { valid: false, reason: "record not object" };
  const k = key || process.env[ENV_KEY];
  if (!k) return { valid: false, reason: "missing key" };
  if (typeof record.signature !== "string" || !record.signature) {
    return { valid: false, reason: "signature missing" };
  }
  const expected = hmacSign(canonicalPayload(record), k);
  // Constant-time compare via Buffer; lengths must match.
  const a = Buffer.from(expected, "hex");
  const b = Buffer.from(record.signature, "hex");
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return { valid: false, reason: `signature mismatch (expected ${expected.slice(0, 8)}..., got ${record.signature.slice(0, 8)}...)` };
  }
  if (record.protocol !== PROTOCOL_VERSION) {
    return { valid: false, reason: `unexpected protocol ${JSON.stringify(record.protocol)} (expected ${JSON.stringify(PROTOCOL_VERSION)})` };
  }
  if (!(record.confidence >= 0.0 && record.confidence <= 1.0)) {
    return { valid: false, reason: `confidence ${record.confidence} out of [0.0, 1.0]` };
  }
  return { valid: true };
}

// Parse a PROBAT.md-style chain: ```idr ... ``` fenced JSON blocks.
function parseChain(text) {
  if (typeof text !== "string") throw new Error("chain text required");
  const out = [];
  const lines = text.split(/\r?\n/);
  let inBlock = false;
  let buf = [];
  let blockStart = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!inBlock && trimmed.startsWith("```idr")) {
      inBlock = true;
      buf = [];
      blockStart = i + 1;
      continue;
    }
    if (inBlock && trimmed.startsWith("```")) {
      inBlock = false;
      let parsed;
      try {
        parsed = JSON.parse(buf.join("\n"));
      } catch (e) {
        throw new Error(`malformed IDR JSON near line ${blockStart}: ${e.message}`);
      }
      out.push(parsed);
      continue;
    }
    if (inBlock) buf.push(line);
  }
  if (inBlock) throw new Error(`unclosed \`\`\`idr block starting at line ${blockStart}`);
  return out;
}

function verifyChain(chainText, key) {
  let records;
  try {
    records = parseChain(chainText);
  } catch (e) {
    return { valid: false, reason: e.message, at: 0 };
  }
  let expectedPrev = GENESIS_PREVIOUS_HASH;
  for (let i = 0; i < records.length; i++) {
    const r = records[i];
    const single = verifyRecord(r, key);
    if (!single.valid) {
      return { valid: false, reason: `entry ${i + 1}: ${single.reason}`, at: i + 1 };
    }
    if (r.previous_hash !== expectedPrev) {
      return {
        valid: false,
        reason: `entry ${i + 1}: chain break: previous_hash expected ${expectedPrev.slice(0, 8)}..., got ${(r.previous_hash || "").slice(0, 8)}...`,
        at: i + 1,
      };
    }
    expectedPrev = hashRecord(r);
  }
  return { valid: true, count: records.length };
}

module.exports = {
  GENESIS_PREVIOUS_HASH,
  PROTOCOL_VERSION,
  SIGNATURE_ALGORITHM,
  ENV_KEY,
  sign,
  verifyRecord,
  verifyChain,
  parseChain,
  // Internal helpers exposed for tests + cross-validation.
  canonicalPayload,
  hashRecord,
  stableStringify,
};
