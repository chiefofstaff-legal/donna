// GET /api/widget-pubkey — publish the demo's Ed25519 PUBLIC key.
//
// WHY THIS ENDPOINT EXISTS
//   The widget signs with Ed25519. The whole point of an asymmetric scheme is
//   that a visitor can verify a record WITHOUT holding anything that could forge
//   one — they need only the PUBLIC key. So the page must publish that public
//   key, and it must be the key actually in use on this deployment (never a
//   hard-coded literal that could drift from the live signing key). This
//   endpoint derives the public key from the live signing seed (or returns the
//   explicitly-configured public key), so the value the page shows always
//   matches the key the server signs with.
//
//   ONLY the public half is ever emitted. The 32-byte private seed
//   (DONNA_NOTARISE_ED25519_PRIVKEY) never leaves the server: ed25519PubkeyHex
//   derives the public key from it in-process and returns only the public bytes.
//
// SHAPE
//   GET → 200 { ok:true, scheme:"ed25519", algorithm:"Ed25519", pubkey:"<hex>" }
//       | 503 service_unavailable  (no key configured)
//       | 405 method_not_allowed

"use strict";

const idr = require("../lib/idr.js");

module.exports = function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  // Prefer an explicitly-published public key if the deploy sets one; otherwise
  // derive it from the signing seed. Either way only the public half is exposed.
  let pubkey = process.env[idr.ENV_ED25519_PUBKEY];
  if (!pubkey) {
    const seed = process.env[idr.ENV_ED25519_KEY];
    if (!seed) {
      console.error(`/api/widget-pubkey: no Ed25519 key configured`);
      return res.status(503).json({ ok: false, error: "service_unavailable" });
    }
    try {
      pubkey = idr.ed25519PubkeyHex(seed);
    } catch (e) {
      console.error(`/api/widget-pubkey: pubkey derivation failed: ${e.message}`);
      return res.status(503).json({ ok: false, error: "service_unavailable" });
    }
  }

  // Public key — safe to cache at the edge for an hour.
  res.setHeader("Cache-Control", "public, max-age=3600");
  return res.status(200).json({
    ok: true,
    scheme: idr.SCHEME_ED25519,
    algorithm: "Ed25519",
    pubkey,
  });
};

module.exports.default = module.exports;
