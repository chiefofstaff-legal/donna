// POST /api/voice — Whisper transcription stub.
//
// Voice transcription is wired and waiting for the Whisper backend (Phase 2).
// Returns 503 with Retry-After so demo pages can render the graceful-degrade
// banner instead of 404ing.

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  res.setHeader("Retry-After", "86400");
  return res.status(503).json({
    ok: false,
    error: "service_unavailable",
    detail: "Voice transcription is wired and waiting for Whisper backend (planned Phase 2). Use text mode in the meantime.",
  });
};

module.exports.default = module.exports;
