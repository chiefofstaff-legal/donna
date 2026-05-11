# web/ — free.donnaoss.com surface

Thin Vercel-hosted landing for `free.donnaoss.com`. Built on Option 3b
(stub IDR + NEXUS callout) per
`~/.claude/drafts/free-donnaoss-mvp-gap-analysis-2026-05-11.md` section 10.

## Layout

```
web/
  index.html        landing — DONNA backronym, 60s overview, signup, NEXUS callout
  vercel.json       security headers + rewrites (mirrors apex donnaoss.com)
  robots.txt
  sitemap.xml
  og.png            social card placeholder (replace with brand asset before launch)
  api/
    chat.js         POST → proxy to hal.grip-web.com/api/chat (free Groq tier)
    signup.js       POST → Slack #donna-signups (two-tier fallback)
    health.js       GET  → liveness probe
  idr-stub/
    index.html      plain-language IDR explainer + NEXUS callout
  try/
    index.html      interactive HAL chat demo
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
runtime (or a local Vercel dev server).

## Deploy (Vercel)

```bash
cd web
vercel link                           # link to a Vercel project
vercel --prod                          # production deploy
```

Project name suggestion: `donna-web` under the CodeTonight Vercel team.
Custom domain `free.donnaoss.com` is aliased to this project AFTER the
GoDaddy A record (`free → 76.76.21.21`) has propagated.

## Required env vars (Vercel project settings)

| Var | Purpose | Required? |
|-----|---------|-----------|
| `SLACK_WEBHOOK_URL` | Tier 1 signup delivery (channel-bound webhook) | optional, preferred |
| `SLACK_BOT_TOKEN`   | Tier 2 signup delivery (chat.postMessage) | optional fallback |
| `SLACK_CHANNEL_ID`  | Channel for Tier 2 (default `C0B3Q8CD30Q` = #donna-signups) | optional |

`api/chat.js` requires no env vars — `hal.grip-web.com/api/chat` is the
public LLM contract.

## What is intentionally NOT here yet

- Voice surface ports (W3 will lift the recording UI from nexus-poc).
- NDA drafting demo (W5 will add `web/demo/draft-nda.html`).
- E2E smoke tests + WCAG audit + mobile audit (W8).
- Per-IP rate limiting on `/api/chat` (W8 — start at 30 req/min/IP).
- Custom domain alias + DNS confirmation (W13 launch wave).

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
