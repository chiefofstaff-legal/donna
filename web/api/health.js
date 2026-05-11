// Liveness probe for free.donnaoss.com surface.
// GET /api/health → 200 { ok, ts, version }.

export default function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }
  return res.status(200).json({
    ok: true,
    ts: new Date().toISOString(),
    version: "scaffold-W2",
  });
}
