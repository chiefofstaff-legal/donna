// Signup → Slack #donna-signups (two-tier fallback).
// Vercel Hobby serverless. Node 18+ runtime (global fetch).
//
// Delivery tiers (least-privilege first):
//   1. SLACK_WEBHOOK_URL — channel-bound incoming webhook. Preferred.
//   2. SLACK_BOT_TOKEN + SLACK_CHANNEL_ID — chat.postMessage fallback.
//      Channel default = C0B3Q8CD30Q (#donna-signups).
//   3. Log-only — both unset OR both fail. Visitor still sees success;
//      submission preserved in serverless logs.
//
// Behavior:
//   - POST /api/signup with JSON {"email": "user@firm.example"}
//   - 405 non-POST, 400 invalid email, 200 ok:true otherwise.
//   - Never exposes Slack errors to the visitor.
//   - Response includes "via" field ("webhook" | "bot_token") when delivered.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_LEN = 254;
const MAX_HEADER_LEN = 200;
const DEFAULT_CHANNEL_ID = "C0B3Q8CD30Q"; // #donna-signups

function readBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "object") return req.body;
  try {
    return JSON.parse(req.body);
  } catch {
    return {};
  }
}

function clip(s, n) {
  return (s || "").toString().slice(0, n);
}

function buildBlocks(email, meta) {
  return [
    {
      type: "header",
      text: { type: "plain_text", text: "New free.donnaoss.com signup" },
    },
    {
      type: "section",
      fields: [
        { type: "mrkdwn", text: `*Email*\n\`${email}\`` },
        { type: "mrkdwn", text: `*When*\n${meta.ts}` },
      ],
    },
    {
      type: "context",
      elements: [
        {
          type: "mrkdwn",
          text: `_Source:_ free.donnaoss.com  ·  _Referrer:_ ${meta.ref || "(none)"}  ·  _UA:_ ${meta.ua || "(none)"}  ·  _via:_ ${meta.via}`,
        },
      ],
    },
    {
      type: "context",
      elements: [
        {
          type: "mrkdwn",
          text: "_Reply from your own inbox within 24h. Concierge over automation._",
        },
      ],
    },
  ];
}

async function sendViaWebhook(url, email, meta) {
  const blocks = buildBlocks(email, { ...meta, via: "webhook" });
  const payload = { text: `New free.donnaoss.com signup: ${email}`, blocks };
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const txt = await r.text().catch(() => "(no body)");
    throw new Error(`webhook ${r.status}: ${txt.slice(0, 200)}`);
  }
  return true;
}

async function sendViaBotToken(token, channelId, email, meta) {
  const blocks = buildBlocks(email, { ...meta, via: "bot_token" });
  const payload = {
    channel: channelId,
    text: `New free.donnaoss.com signup: ${email}`,
    blocks,
  };
  const r = await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.ok) {
    throw new Error(`chat.postMessage failed: ${data.error || r.status}`);
  }
  return true;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method_not_allowed" });
  }

  const body = readBody(req);
  const email = (body.email || "").toString().trim().toLowerCase();

  if (!email || email.length > MAX_EMAIL_LEN || !EMAIL_RE.test(email)) {
    return res.status(400).json({ ok: false, error: "invalid_email" });
  }

  const meta = {
    ts: new Date().toISOString(),
    ref: clip(req.headers["referer"], MAX_HEADER_LEN),
    ua: clip(req.headers["user-agent"], 120),
  };

  const env = process.env;
  const webhookUrl = env.SLACK_WEBHOOK_URL;
  const botToken = env.SLACK_BOT_TOKEN;
  const channelId = env.SLACK_CHANNEL_ID || DEFAULT_CHANNEL_ID;

  if (webhookUrl) {
    try {
      await sendViaWebhook(webhookUrl, email, meta);
      return res.status(200).json({ ok: true, queued: true, via: "webhook" });
    } catch (err) {
      console.error("[signup] webhook failed, trying bot fallback:", err.message);
    }
  }

  if (botToken) {
    try {
      await sendViaBotToken(botToken, channelId, email, meta);
      return res.status(200).json({ ok: true, queued: true, via: "bot_token" });
    } catch (err) {
      console.error("[signup] bot fallback failed:", err.message);
    }
  }

  console.error("[signup] all delivery paths exhausted — email in logs only:", email);
  return res.status(200).json({ ok: true, queued: false });
}
