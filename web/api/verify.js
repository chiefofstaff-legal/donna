// POST /api/verify — verify an IDR or a full PROBAT.md-style chain.
//
// Body: { chain?: string, record?: object }
// Returns: 200 { valid, count? } | 400 missing | 405 method | 500 internal.

const idr = require("../lib/idr.js");

const MAX_CHAIN_BYTES = 256 * 1024; // 256 KB cap on inbound chain text

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
    console.error(`/api/verify: signing key not configured`);
    return res.status(500).json({ ok: false, error: "service_unavailable", detail: "Server misconfigured" });
  }
  const body = readBody(req);
  if (body === null) return res.status(400).json({ ok: false, error: "invalid_json" });
  if (!body || typeof body !== "object") return res.status(400).json({ ok: false, error: "invalid_body" });

  const hasChain = typeof body.chain === "string" && body.chain.length > 0;
  const hasRecord = body.record && typeof body.record === "object";
  if (!hasChain && !hasRecord) {
    return res.status(400).json({ ok: false, error: "missing_input", detail: "Provide chain (string) or record (object)." });
  }

  try {
    if (hasChain) {
      if (body.chain.length > MAX_CHAIN_BYTES) {
        return res.status(400).json({ ok: false, error: "chain_too_large" });
      }
      const result = idr.verifyChain(body.chain, key);
      return res.status(200).json(Object.assign({ ok: true }, result));
    }
    const result = idr.verifyRecord(body.record, key);
    return res.status(200).json(Object.assign({ ok: true }, result));
  } catch (e) {
    console.error(`/api/verify: verification failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "verify_failed" });
  }
};

module.exports.default = module.exports;
