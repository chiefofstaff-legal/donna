# MIGRATION — `web/` surface for free.donnaoss.com

**Source plan:** `~/.claude/drafts/free-donnaoss-mvp-gap-analysis-2026-05-11.md`
**Architecture lock:** Option 3b (stub IDR + NEXUS callout, on AGPL primitives)
**Sprint plan:** `~/.claude/plans/free-donnaoss-mvp-sprint-2026-05-11.md`

## Source surfaces

| Layer | Source | Treatment under W2 |
|-------|--------|--------------------|
| Visual + UI flows | `~/nexus-poc/` (Next.js 16 App Router, 14 pages) | **Concept-port only** — no nexus-poc files copied in W2; W3 lifts specific page shapes (time, tasks, idr, drafting) and re-implements as static HTML |
| Engine | `hal.grip-web.com/api/chat` | Used directly via `web/api/chat.js`. No separate LLM infrastructure inside the repo. Free public tier defaults to Groq llama-3.3-70b. |
| Audit-chain primitive | `~/donna-legal/bin/notarise` | Already-OSS substrate. W3+ may shell out to `bin/notarise` for the IDR demo. W2 ships only the explainer stub. |
| DocuSeal shim | `~/donna-legal/lib/docuseal.py` | Available; W5 may surface it via `/api/docuseal/*`. Not in W2. |
| Voice pipeline | `~/donna-legal/client/donna/voice_pipeline.py` | Available; W3 may add a voice-prompt demo. EN-only today (DE deferred). |
| Signup → Slack | `~/CodeTonight/donnaoss.com/api/signup.js` (apex) | **Ported into `web/api/signup.js`** with two-tier fallback (`SLACK_WEBHOOK_URL` → `SLACK_BOT_TOKEN`+`SLACK_CHANNEL_ID`). Default channel ID `C0B3Q8CD30Q` (#donna-signups, CodeTonight workspace). |

## Branding

- Canonical brand line in every public title / OG / Twitter card / og:image:alt:
  **"DONNA — Decision-Oriented Network Notarisation for Attorneys"**.
- "Delegation Orchestration Layer" appears only as a positioning descriptor
  in body text — never replaces the brand line.
- DONNA backronym block on `index.html` shows the full D-O-N-N-A expansion
  with a per-letter rationale.
- Copper accent (`#b35e15`) and dark cover (`#0a0a0a`) mirror the apex
  `donnaoss.com` palette so the surfaces feel like one product.

## License inheritance

`web/` is governed by the AGPL-3.0 of the parent `donna-legal` repository.
No additional licence file inside `web/`. The footer of every public page
links to the OSS repo and surfaces the licence note.

## Channel scope (PARAMOUNT)

`web/api/signup.js` posts ONLY to a CodeTonight Slack channel
(`C0B3Q8CD30Q` = #donna-signups). It NEVER posts to Sudonum (#grip-news
is GRIP/HAL/happi.md-only) and NEVER to #ff-chat (Slack Connect external).
Per `feedback_codetonight_workspace_only_for_donna_announcements.md`.

## What is NOT in W2

| Wave | Deferred work |
|------|---------------|
| W3 | nexus-poc UI flows (time entry, tasks, IDR page, NDA drafting) re-implemented as static HTML in `web/demo/*` |
| W5 | Backend wiring + per-tenant isolation + (optional) `/api/notarise` shell-out to `bin/notarise` |
| W8 | E2E smoke + WCAG AA audit (light + dark) + mobile audit (320px viewport) + Craig's GoDaddy A-record DNS confirmation |
| W13 | Polish + Vercel custom domain alias + launch announcement (CodeTonight channels only) |

## Falsifiers carried forward from the gap analysis

- **F1** — visitor analytics show >50% bounce on `/try/` within 30s with
  qualitative feedback "the IDR engine isn't actually here". Would force
  reconsideration of 3b → 3a.
- **F2** — legal-tech press writes "DONNA isn't really open source because
  the brain is closed". Forces counter-narrative or 3a Phase 2.
- **F3** — Craig Miller messages "where's the actual decision-recording
  in the demo?". Forces 3a.
- **F4** — community PR ports nexus-poc-style IDR compute and gets >5
  thumbs-up in 48h. 3b under-delivered.

Track all four through W13 launch + first 7 days post-launch. Reframe
H448 at W3 dispatch ("AGPL-published surfaces work identically on
free.donnaoss.com to local CLI") so the hypothesis is testable under 3b.
