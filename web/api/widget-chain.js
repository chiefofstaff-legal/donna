// GET /api/widget-chain — read the caller's OWN session chain.
//
// SHAPE
//   GET ?sessionId=<uuid> (required); ?max=N to limit
//   Returns: 200 { ok:true, count, entries: [{hash,intent,ts,signature,previous_hash,signer}, ...] }
//          | 400 session_required (missing/malformed sessionId)
//
// SESSION-PRIVATE (P0.1 reshape): lists ONLY the chain belonging to the
// sessionId in the query. A caller can never list another session's chain or
// a shared/global chain — listChain throws on any non-UUID sessionId.
//
// Public; no auth. CORS-safe (no credentials, idempotent read). All
// internal storage fields (`ip`, `_ts`) are stripped by storage.listChain.

"use strict";

const storage = require("../lib/widget-storage.js");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const sessionId = req.query && req.query.sessionId;
  if (!storage.isValidSessionId(sessionId)) {
    return res.status(400).json({ ok: false, error: "session_required" });
  }
  let max = storage.MAX_CHAIN_LEN;
  if (req.query && req.query.max) {
    const n = parseInt(req.query.max, 10);
    if (!isNaN(n) && n > 0 && n <= storage.MAX_CHAIN_LEN) max = n;
  }
  try {
    const entries = await storage.listChain(sessionId, { max });
    return res.status(200).json({ ok: true, count: entries.length, entries });
  } catch (e) {
    console.error(`/api/widget-chain: read failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "read_failed" });
  }
};

module.exports.default = module.exports;
