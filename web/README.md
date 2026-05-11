# web/ — free.donnaoss.com surface

Thin Vercel-hosted landing for `free.donnaoss.com`. Stub-IDR + NEXUS-callout
architecture: this surface exposes the AGPL primitives in `donna-legal`
(audit-chain notarisation, DocuSeal integration, voice prompts, MCP server)
without bundling the proprietary IDR engine. A "Want the full IDR? →
chiefofstaff.pro" callout sits on every demo page.

## Layout

```
web/
  index.html        landing — DONNA backronym, 60s overview, signup, NEXUS callout
  vercel.json       security headers + rewrites
  robots.txt
  sitemap.xml
  og.png            social card
  api/
    chat.js         POST → proxy to hal.grip-web.com/api/chat (free Groq tier)
    signup.js       POST → Slack webhook/bot fallback (Tier 3 log-only by default)
    health.js       GET  → liveness probe
    notarise.js     POST → HMAC-SHA256 IDR signer (parity with bin/notarise)
    verify.js       POST → IDR record/chain verifier
    voice.js        POST → 503 + Retry-After (Whisper integration deferred)
  idr-stub/
    index.html      plain-language IDR explainer + NEXUS callout
  try/
    index.html      interactive HAL chat demo
  demo/
    voice-time-entry.html        voice + text-mode time-entry parsing
    voice-task-delegation.html   voice + text-mode task delegation
    draft-nda.html               5-field NDA drafting + alt-phrasing
    audit-chain.html             live notarise + verify + chain visualisation
  lib/
    idr.js          Node port of bin/notarise (HMAC-SHA256, stdlib crypto)
  tests/
    idr-parity.test.js   5 tests including PROBAT.md gold-standard parity
  MIGRATION.md      port plan + boundary docs
```

## Local preview

This is plain static HTML + Vercel-style serverless functions. To preview
the static surface alone:

```bash
cd web && python3 -m http.server 4000
# open http://127.0.0.1:4000/
```

The `/api/*` routes are Vercel serverless and only run under the Vercel
runtime (or a local Vercel dev server: `npx vercel dev`).

## Test the IDR parity locally

```bash
cd web
node --test tests/idr-parity.test.js
# Expect: 5 pass / 0 fail (incl. PROBAT.md verification + Python↔JS cross-validation)
```

## Deploy (Vercel)

```bash
cd web
vercel link --yes              # link to a Vercel project (any team)
vercel --prod                  # production deploy
```

Custom domain `free.donnaoss.com` is aliased to the project after the
GoDaddy A record (`free → 76.76.21.21`) propagates:

```bash
vercel domains add free.donnaoss.com
```

## Required env vars (Vercel project settings)

| Var | Purpose | Required? |
|-----|---------|-----------|
| `DONNA_NOTARISE_KEY` | HMAC signing key for `/api/notarise` and `/api/verify` (use the published demo key from `../PROBAT.md` for a public free-tier demo) | yes |
| `SLACK_WEBHOOK_URL` | Tier 1 signup delivery (channel-bound webhook) | optional |
| `SLACK_BOT_TOKEN`   | Tier 2 signup delivery (chat.postMessage) | optional fallback |
| `SLACK_CHANNEL_ID`  | Channel for Tier 2 | optional |

`api/chat.js` requires no env vars — `hal.grip-web.com/api/chat` is the
public LLM contract used by the demo (free Groq tier, no key needed).

If both Slack vars are unset, `/api/signup` falls through to a Tier 3
log-only path: the visitor sees success and the email lands in Vercel
serverless logs. This is the safe default for a public demo.

## What is intentionally NOT here yet

- Voice transcription endpoint (`/api/voice` returns 503 with `Retry-After`
  so the demo pages render their graceful-degrade banner; real Whisper
  integration is a follow-up).
- Per-IP rate limiting on `/api/chat` (recommend 30 req/min/IP at the
  edge before public launch).

## Branding rules

- DONNA backronym uses the FULL canonical expansion in every `<title>`,
  `og:title`, `twitter:title`, and `og:image:alt`:
  **"DONNA — Decision-Oriented Network Notarisation for Attorneys"**.
- "Delegation Orchestration Layer" only appears in body copy as a
  positioning descriptor — never as a substitute for the brand line.
- Copper accent `#b35e15` mirrors apex `donnaoss.com`.
- WCAG AA contrast verified for both `prefers-color-scheme: light` and
  `prefers-color-scheme: dark` variants. Touch targets ≥48×48px on
  320px viewport.

## Licence

Inherits AGPL-3.0 from the parent `donna-legal` repository.
See `../LICENSE` and `../NOTICE`.
