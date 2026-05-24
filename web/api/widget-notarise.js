// POST /api/widget-notarise — public widget notarise wrapper.
//
// SHAPE
//   Body: { intent: string }    (no signer — hardcoded per Role 4 vector f)
//   Returns: 200 { ok:true, record, hash, position } | 429 rate_limited
//          | 400 content_blocked | 400 pii_blocked | 403 bad_origin
//          | 405 method | 500 internal
//
// DEFENCE STACK (in order — first failure wins)
//   1. Origin check                  → 403 bad_origin
//   2. Rate limit (10/IP/hr)         → 429 rate_limited
//   3. Body shape + size cap         → 400 invalid_body / body_too_large
//   4. Blocklist                     → 400 content_blocked
//   5. PII regex                     → 400 pii_blocked
//   6. Sign (HARDCODED_SIGNER)       → 200 { record, hash, position }
//
// WHY ORDER MATTERS
//   Cheap checks (Origin → rate) before expensive checks (PII regex → sign)
//   to minimise wasted compute on adversarial traffic. Origin first because
//   it is the cheapest. Rate before body parse so a denied IP cannot bypass
//   the limit by sending malformed bodies that bypass the validator.
//
// SIGNER HARDCODING
//   The widget endpoint NEVER accepts a user-supplied `signer`. The
//   underlying primitive (`web/api/notarise.js`) still allows free-form
//   signers because terminal-CLI users have different threat models.
//   This wrapper bridges the two: it imports `lib/idr.js` directly (not
//   `api/notarise.js`) so the underlying primitive remains untouched.

"use strict";

const idr = require("../lib/idr.js");
const storage = require("../lib/widget-storage.js");

const MAX_BODY_BYTES = 4096;        // matches /api/notarise:8
const MAX_INTENT_LEN = 500;         // matches /api/notarise:9 — DRY tunable

const ALLOWED_ORIGINS = Object.freeze([
  "https://free.donnaoss.com",
  "https://donnaoss.com",
]);

function readBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "object") return req.body;
  if (typeof req.body === "string") {
    if (req.body.length > MAX_BODY_BYTES) {
      const e = new Error("body_too_large"); e.code = "body_too_large"; throw e;
    }
    try { return JSON.parse(req.body); } catch { return null; }
  }
  return {};
}

function clientIp(req) {
  // Vercel-friendly client-IP extraction. Prefer x-forwarded-for first hop.
  const xff = req.headers && req.headers["x-forwarded-for"];
  if (typeof xff === "string" && xff) return xff.split(",")[0].trim();
  if (req.headers && req.headers["x-real-ip"]) return req.headers["x-real-ip"];
  return (req.socket && req.socket.remoteAddress) || "";
}

function originAllowed(req) {
  const origin = req.headers && req.headers.origin;
  // Missing Origin → terminal/curl path; allow (Role 4 vector d explicit).
  if (!origin) return true;
  return ALLOWED_ORIGINS.includes(origin);
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  if (!originAllowed(req)) {
    return res.status(403).json({ ok: false, error: "bad_origin" });
  }

  const ip = clientIp(req);
  const rl = await storage.checkRateLimit(ip);
  if (!rl.allowed) {
    res.setHeader("Retry-After", String(storage.RATE_WINDOW_SEC));
    return res.status(429).json({ ok: false, error: "rate_limited", retry_after_sec: storage.RATE_WINDOW_SEC });
  }

  let body;
  try { body = readBody(req); } catch (e) {
    return res.status(400).json({ ok: false, error: e.code || "bad_body" });
  }
  if (body === null) return res.status(400).json({ ok: false, error: "invalid_json" });
  if (!body || typeof body !== "object") return res.status(400).json({ ok: false, error: "invalid_body" });
  if (typeof body.intent !== "string" || !body.intent.trim()) {
    return res.status(400).json({ ok: false, error: "intent_required" });
  }
  if (body.intent.length > MAX_INTENT_LEN) {
    return res.status(400).json({ ok: false, error: "intent_too_long", max: MAX_INTENT_LEN });
  }

  const blocked = storage.blocklistDeny(body.intent);
  if (blocked) return res.status(400).json({ ok: false, error: "content_blocked", detail: blocked.reason });
  const pii = storage.piiDeny(body.intent);
  if (pii) return res.status(400).json({ ok: false, error: "pii_blocked", detail: pii.reason, kind: pii.name });

  const key = process.env[idr.ENV_KEY];
  if (!key) {
    console.error(`/api/widget-notarise: signing key not configured`);
    return res.status(500).json({ ok: false, error: "service_unavailable" });
  }

  try {
    // Compute previous_hash from the current chain tail (chain shape ratified W6).
    const chain = await storage.readChain();
    const prev = chain.length ? chain[chain.length - 1].hash : idr.GENESIS_PREVIOUS_HASH;
    const out = idr.sign({
      intent: body.intent,
      signer: storage.HARDCODED_SIGNER,       // ← hardcoded; ignores any client-supplied signer
      confidence: 1.0,
      previousHash: prev,
      metadata: { source: "widget" },
      key,
    });
    const push = await storage.pushEntry(
      { hash: out.hash, intent: body.intent, ts: out.record.timestamp, signature: out.record.signature, previous_hash: out.record.previous_hash, signer: out.record.signer },
      ip,
    );
    return res.status(200).json({ ok: true, record: out.record, hash: out.hash, position: push.position });
  } catch (e) {
    console.error(`/api/widget-notarise: sign failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "sign_failed" });
  }
};

module.exports.default = module.exports;
