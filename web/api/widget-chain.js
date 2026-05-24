// GET /api/widget-chain — read the live widget chain.
//
// SHAPE
//   GET (no body); ?max=N to limit
//   Returns: 200 { ok:true, count, entries: [{hash,intent,ts,signature,previous_hash,signer}, ...] }
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
  let max = storage.MAX_CHAIN_LEN;
  if (req.query && req.query.max) {
    const n = parseInt(req.query.max, 10);
    if (!isNaN(n) && n > 0 && n <= storage.MAX_CHAIN_LEN) max = n;
  }
  try {
    const entries = await storage.listChain({ max });
    return res.status(200).json({ ok: true, count: entries.length, entries });
  } catch (e) {
    console.error(`/api/widget-chain: read failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "read_failed" });
  }
};

module.exports.default = module.exports;
