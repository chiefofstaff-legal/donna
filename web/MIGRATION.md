# MIGRATION — `web/` surface for free.donnaoss.com

**Architecture:** thin Vercel-hosted web surface that exercises donna-legal's
AGPL primitives (notarise + DocuSeal + voice prompts + MCP) without
requiring the proprietary NEXUS tier. The full IDR engine lives in NEXUS
(chiefofstaff.pro) per the Inverted Red Hat licensing model. A prominent
"Want the full IDR? → chiefofstaff.pro" callout sits on every demo page.

## Source surfaces

| Layer | Source | Treatment |
|-------|--------|-----------|
| Visual + UI flows | reference patterns (Next.js App Router) | **Concept-port only** — no proprietary code copied. Page shapes (time, tasks, IDR, drafting) re-implemented as static HTML. |
| LLM engine | `hal.grip-web.com/api/chat` | Used directly via `web/api/chat.js`. No separate LLM infrastructure inside the repo. Free public tier defaults to Groq llama-3.3-70b. |
| Audit-chain primitive | `bin/notarise` (this repo) | Already-OSS substrate. `web/lib/idr.js` is a byte-level Node port of the Python implementation, with parity tests against `PROBAT.md`. |
| DocuSeal shim | `lib/docuseal.py` (this repo) | Available; future waves may surface it via `/api/docuseal/*`. |
| Voice pipeline | `client/donna/voice_pipeline.py` (this repo) | Available; voice transcription endpoint is currently a 503 stub (Whisper integration deferred to a later wave). |
| Signup → Slack | (concept-ported pattern) | `web/api/signup.js` posts with two-tier fallback (`SLACK_WEBHOOK_URL` → `SLACK_BOT_TOKEN`+`SLACK_CHANNEL_ID`), with a Tier 3 log-only fallback so the visitor experience never breaks even when no Slack creds are configured. |

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

## Signup channel scope

`web/api/signup.js` deliberately leaves `SLACK_WEBHOOK_URL`,
`SLACK_BOT_TOKEN`, and `SLACK_CHANNEL_ID` unset by default. The endpoint
falls through to a log-only Tier 3 so a self-hoster who has not configured
Slack still gets a working signup flow (visitor sees success, email lands
in Vercel logs). Operators self-hosting `free.donnaoss.com` MUST set their
own Slack delivery target — there is no upstream default.

## Wave delivery

| Wave | Deliverable |
|------|-------------|
| W2 | `web/` scaffold (landing, vercel.json, chat/signup/health API stubs, /try/ chat demo, /idr-stub/ explainer) |
| W3 | Four interactive demo pages (`/demo/voice-time-entry`, `/demo/voice-task-delegation`, `/demo/draft-nda`, `/demo/audit-chain`) — voice degrades gracefully to text mode until W5 wires Whisper |
| W5 | `web/lib/idr.js` Node port of `bin/notarise` + `/api/notarise` + `/api/verify` + `/api/voice` (503 stub) + parity test |
| W8 | Vercel preview deploy + 7-endpoint smoke + a11y + brand audit + DNS confirmation |
| W13 | Polish (iOS HIG defensive, `og.png` parity, `trailingSlash` normalisation) + PR + custom-domain wire-up |

## Falsifiers carried forward

- **F1** — visitor analytics show >50% bounce on `/try/` within 30s with
  qualitative feedback "the IDR engine isn't actually here". Would force
  reconsideration of the stub-plus-callout pattern in favour of porting
  the full engine.
- **F2** — legal-tech press writes "DONNA isn't really open source because
  the brain is closed". Forces counter-narrative or full-port.
- **F3** — early adopters consistently ask "where's the actual decision-
  recording in the demo?" rather than engaging with the audit-chain page.
  Forces full-port.
- **F4** — community PR ports a full IDR compute path and gets significant
  positive reception in 48h. Indicates the stub under-delivered.

The hypothesis "AGPL-published surfaces work identically on free.donnaoss.com
to the local CLI" is testable today: PROBAT.md verifies end-to-end through
both Python (`bin/notarise verify`) and JavaScript (`web/lib/idr.js`
`verifyChain`), with byte-level cross-validation in
`web/tests/idr-parity.test.js`.
