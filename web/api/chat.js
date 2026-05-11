// Proxies to the HAL backend. POST { message, model? } →
// { text, model, provider, latency_ms, cost_usd, tokens }.
//
// Free-tier default model = Groq llama-3.3-70b-versatile.
// Input is bounded to 4000 chars; non-string payloads rejected.
// No secrets exposed: HAL endpoint is open at the upstream contract.

const HAL_ENDPOINT = "https://hal.grip-web.com/api/chat";
const MAX_MESSAGE_LEN = 4000;
const DEFAULT_MODEL = "groq/llama-3.3-70b-versatile";
const UPSTREAM_TIMEOUT_MS = 30000;

function readBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "object") return req.body;
  try {
    return JSON.parse(req.body);
  } catch {
    return {};
  }
}

function sanitiseModel(m) {
  if (typeof m !== "string") return DEFAULT_MODEL;
  if (!/^[a-z0-9_./-]{1,80}$/i.test(m)) return DEFAULT_MODEL;
  return m;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  const body = readBody(req);
  const message = (body.message || "").toString();

  if (!message || message.length > MAX_MESSAGE_LEN) {
    return res.status(400).json({
      ok: false,
      error: "message_required_and_under_4000_chars",
    });
  }

  const model = sanitiseModel(body.model);
  const start = Date.now();

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  try {
    const r = await fetch(HAL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, model }),
      signal: controller.signal,
    });
    const data = await r.json().catch(() => ({}));
    return res.status(r.status).json({
      ...data,
      latency_ms: Date.now() - start,
    });
  } catch (e) {
    const aborted = e && e.name === "AbortError";
    return res.status(aborted ? 504 : 502).json({
      ok: false,
      error: aborted ? "hal_timeout" : "hal_unreachable",
      latency_ms: Date.now() - start,
    });
  } finally {
    clearTimeout(timer);
  }
}
