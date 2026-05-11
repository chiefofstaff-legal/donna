// POST /api/notarise — sign an IDR (Intent Decision Record).
//
// Body: { intent, signer, confidence, previousHash?, metadata?, decisionId? }
// Returns: 200 { record, hash } | 400 validation | 405 method | 500 internal.

const idr = require("../lib/idr.js");

const MAX_BODY_BYTES = 4096;
const MAX_FIELD_LEN = 500;

function readBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "object") return req.body;
  if (typeof req.body === "string") {
    if (req.body.length > MAX_BODY_BYTES) {
      const e = new Error("body_too_large");
      e.code = "body_too_large";
      throw e;
    }
    try { return JSON.parse(req.body); } catch { return null; }
  }
  return {};
}

function validate(body) {
  if (!body || typeof body !== "object") return "invalid_body";
  if (typeof body.intent !== "string" || !body.intent.trim()) return "intent_required";
  if (body.intent.length > MAX_FIELD_LEN) return "intent_too_long";
  if (typeof body.signer !== "string" || !body.signer.trim()) return "signer_required";
  if (body.signer.length > MAX_FIELD_LEN) return "signer_too_long";
  if (body.confidence !== undefined) {
    if (typeof body.confidence !== "number" || !(body.confidence >= 0 && body.confidence <= 1)) {
      return "confidence_out_of_range";
    }
  }
  if (body.metadata !== undefined && (typeof body.metadata !== "object" || Array.isArray(body.metadata) || body.metadata === null)) {
    return "metadata_must_be_object";
  }
  if (body.previousHash !== undefined && (typeof body.previousHash !== "string" || !/^[0-9a-f]{64}$/i.test(body.previousHash))) {
    return "previous_hash_invalid";
  }
  return null;
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  const key = process.env[idr.ENV_KEY];
  if (!key) {
    console.error(`/api/notarise: signing key not configured`);
    return res.status(500).json({ ok: false, error: "service_unavailable", detail: "Server misconfigured" });
  }
  let body;
  try { body = readBody(req); } catch (e) {
    return res.status(400).json({ ok: false, error: e.code || "bad_body" });
  }
  if (body === null) return res.status(400).json({ ok: false, error: "invalid_json" });
  const err = validate(body);
  if (err) return res.status(400).json({ ok: false, error: err });
  try {
    const out = idr.sign({
      intent: body.intent,
      signer: body.signer,
      confidence: typeof body.confidence === "number" ? body.confidence : 1.0,
      previousHash: body.previousHash,
      metadata: body.metadata || {},
      decisionId: body.decisionId,
      key,
    });
    return res.status(200).json({ ok: true, record: out.record, hash: out.hash });
  } catch (e) {
    console.error(`/api/notarise: sign failed: ${e.message}`);
    return res.status(500).json({ ok: false, error: "sign_failed" });
  }
};

module.exports.default = module.exports;
