// POST /api/widget-verify — verify widget chain OR inline record.
//
// Modes (verification semantics unchanged from prior; only the default-chain
// mode is now session-scoped per the P0.1 reshape):
//   (1) Body { sessionId: <uuid> } (no record/chain) → verify the caller's
//       OWN session chain stored in widget-storage. Returns
//       { ok:true, valid, count }. A missing/malformed sessionId in this mode
//       → 400 session_required (a caller can never verify a shared/global
//       chain, because there no longer is one).
//   (2) Body { record: {...} } → verify a single record (archive mode for
//       a share-URL whose chain-tail entry has expired). Returns
//       { ok:true, valid, reason? }. SESSION-INDEPENDENT — a posted record is
//       self-contained and verifies against the signing key alone.
//   (3) Body { chain: "..." } → PROBAT-style chain text verify (preserves
//       the terminal-curl rail: any visitor can paste a chain and get the
//       same answer in their terminal as in the widget). SESSION-INDEPENDENT.
//
// Origin check: relaxed — missing Origin (curl) → allow. Same rationale as
// widget-notarise: the terminal rail is part of the demo proof.

"use strict";

const idr = require("../lib/idr.js");
const storage = require("../lib/widget-storage.js");

const MAX_CHAIN_BYTES = 256 * 1024;

function readBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "object") return req.body;
  if (typeof req.body === "string") {
    try { return JSON.parse(req.body); } catch { return null; }
  }
  return {};
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const key = process.env[idr.ENV_KEY];
  if (!key) {
    console.error(`/api/widget-verify: signing key not configured`);
    return res.status(500).json({ ok: false, error: "service_unavailable" });
  }
  const body = readBody(req);
  if (body === null) return res.status(400).json({ ok: false, error: "invalid_json" });
  const hasChainText = body && typeof body.chain === "string" && body.chain.length > 0;
  const hasRecord = body && body.record && typeof body.record === "object";

  try {
    if (hasChainText) {
      if (body.chain.length > MAX_CHAIN_BYTES) {
        return res.status(400).json({ ok: false, error: "chain_too_large" });
      }
      const r = idr.verifyChain(body.chain, key);
      return res.status(200).json(Object.assign({ ok: true }, r));
    }
    if (hasRecord) {
      const r = idr.verifyRecord(body.record, key);
      return res.status(200).json(Object.assign({ ok: true }, r));
    }
    // Default: verify the caller's OWN session chain by re-signing each entry
    // from the stored payload and re-checking the previous_hash chain. The
    // sessionId is required here (modes 1/2 above are self-contained and need
    // no session); a missing/malformed sessionId → 400 session_required.
    if (!storage.isValidSessionId(body && body.sessionId)) {
      return res.status(400).json({ ok: false, error: "session_required" });
    }
    const entries = await storage.readChain(body.sessionId);
    // Strip internal fields BEFORE verifying — they were never signed.
    const cleaned = entries.map((e) => {
      const { ip, _ts, ...pub } = e;
      return pub;
    });
    let prev = idr.GENESIS_PREVIOUS_HASH;
    for (let i = 0; i < cleaned.length; i++) {
      const e = cleaned[i];
      const record = {
        decision_id: e.decision_id || `idr_chain_${i}`,
        timestamp: e.ts,
        protocol: "happi/1.1",
        intent: e.intent,
        signer: e.signer || storage.HARDCODED_SIGNER,
        confidence: typeof e.confidence === "number" ? e.confidence : 1.0,
        previous_hash: e.previous_hash || prev,
        metadata: e.metadata || { source: "widget" },
        signature: e.signature,
      };
      const single = idr.verifyRecord(record, key);
      if (!single.valid) {
        return res.status(200).json({ ok: true, valid: false, reason: `entry ${i + 1}: ${single.reason}`, at: i + 1 });
      }
      if (record.previous_hash !== prev) {
        return res.status(200).json({ ok: true, valid: false, reason: `entry ${i + 1}: chain break`, at: i + 1 });
      }
      prev = e.hash;
    }
    return res.status(200).json({ ok: true, valid: true, count: cleaned.length });
  } catch (e) {
    console.error(`/api/widget-verify: failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "verify_failed" });
  }
};

module.exports.default = module.exports;
