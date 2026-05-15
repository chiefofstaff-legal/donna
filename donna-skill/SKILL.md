---
name: donna
description: Open-source delegation orchestration for legal practice. The lawyer speaks the intent, DONNA routes the work to the right person or system, every delegated decision becomes a structured IDR (Intent Decision Record) signed with HMAC-SHA256 and chained for audit. Voice surface, MCP server, and skill files ship under AGPL-3.0. The IDR engine ships proprietary under the NEXUS tier. Protocol is open (happi.md v1.1).
---

# /donna — Delegation Orchestration for Legal Practice

DONNA takes the **coordination overhead** — the routing, the follow-up, the
cryptographic proof of delegation — and leaves the lawyer's judgement in
place. The lawyer speaks the intent, DONNA routes the work. Every delegated
decision is captured as a structured **IDR (Intent Decision Record)**, signed
with HMAC-SHA256, chained, replayable, exportable in regulator-ready formats.

This skill wires the DONNA client and MCP server (`github.com/chiefofstaff-legal/donna`,
AGPL-3.0) into Claude Desktop / Claude Code. Drop the MCP server and this
skill into your AI client, speak your delegations, get a verifiable audit
trail.

The brand is the verb: *DONNA probat* — DONNA proves it. The substrate is the
audit chain (see [`PROBAT.md`](../PROBAT.md) at the repo root for the live
demonstration).

## What you can do

| You say | What happens |
|---------|--------------|
| *"Send Sarah the M&A precedent we used for Dubrovnik, ask her to redline by Tuesday, copy Marcus when she replies."* | Intent extracted, recipient routed, deadline captured, IDR signed and chained |
| *"Mike, draft the response brief by Friday."* | Delegation logged: assignee=Mike, deadline=Fri, IDR signed |
| *"Just spent ninety minutes on the Smith motion."* | Time entry logged: matter=Smith, duration=1.5h, category=Drafting |
| *"Show me what I delegated this week."* | IDR chain queried; replay surfaces every delegated decision with timestamps |
| *"Export today as a regulator packet."* | Chain segment exported in regulator-ready JSON + CSV |

The lawyer never sees a form. No context switch. No memory required. The
audit trail accrues as a side-effect of doing the work.

## Invocation

The skill activates automatically when the user's message contains:

- A delegation phrase: a recipient (a person or a system) plus a verb
  (`draft`, `review`, `file`, `send`, `escalate`) plus optional deadline
- An intent phrase: an instruction that maps to a downstream system (calendar,
  email, document store, messaging platform, legal-AI tool)
- A time-entry phrase: durations like *90 minutes*, *an hour and a half*,
  followed by a matter or activity
- A query phrase: *what did I delegate this week*, *show today's IDRs*,
  *replay the Müller chain*
- An export phrase: *export today as a regulator packet*, *CSV*, *Clio
  export*

When activated, this skill calls the `donna_*` tools exposed by the MCP
server in `mcp-servers/donna/`.

## Tools exposed by the MCP server

| Tool | Purpose |
|------|---------|
| `donna_analyse(transcript)` | Extract intent + constraints + recipients from natural language |
| `donna_draft(intent)` | Compose the delegation message and return a confirmable draft |
| `donna_review(idr)` | Replay an IDR with provenance, signer, confidence, and previous-hash |
| `donna_export(format, date_from?, date_to?)` | Export the IDR chain segment in JSON, CSV, or regulator packet |

The server is a TypeScript scaffold at `mcp-servers/donna/src/server.ts` (the
MCP server name is `donna-legal`). Install it once via `npm install && npm
run build && npm start`; this skill above tells the AI client when to use
the tools.

## How the audit chain works

```
┌─────────────────────────────┐
│ Claude Desktop / Code       │
│ (this skill activates)      │
└──────────────┬──────────────┘
               │
       ┌───────┴────────┐
       │  donna-legal   │  MCP server, stdio + http transports
       │  (TypeScript)  │
       └───────┬────────┘
               │
       ┌───────┴────────┐
       │ DONNA client   │  Voice pipeline, intent extractor, PII shield
       │ (AGPL-3.0)     │
       └───────┬────────┘
               │
       ┌───────┴────────┐
       │ Any LLM        │  Provider-agnostic via HAPPI/1.1
       │ (HAPPI/1.1)    │  cloud · self-hosted · on-device
       └───────┬────────┘
               │
       ┌───────┴────────┐
       │ IDR engine     │  HMAC-SHA256 signing, chain, replay
       │ (NEXUS tier)   │
       └────────────────┘
```

The voice surface, MCP server, and skill files all ship open under
AGPL-3.0. The model layer is provider-agnostic via the open HAPPI/1.1
protocol — point it at any compatible vendor or a self-hosted model.
The IDR engine — the implementation that signs, chains, and verifies —
is the substrate of the proprietary NEXUS tier.

## Privacy posture

The PII Shield (`client/donna/pii_shield.py`) is **wired default-on in the
runtime path** — `Router.__init__` constructs it for every extraction unless
the operator explicitly sets `DONNA_PII_SHIELD=0`. It runs **before any
cloud LLM call**, in two layers (defence-in-depth):

- **Layer 1 — regex** (fast, deterministic): org names with a legal suffix
  (Acme Corp, Smith LLP, Foundation Trust) → `ORG_1`; two/three-token person
  names (John Smith) → `PERSON_1`; case references (ABC-2024-0123) → `CASE_1`.
- **Layer 2 — local inference** (catches what regex cannot): an
  OpenAI-compatible model running **on the firm's own machine** (default
  `http://localhost:11434/v1`, e.g. Ollama) flags single/informal names
  ("Mike", "Smith"), suffix-less orgs ("Acme"), street addresses, monetary
  amounts, and account numbers. Its spans are merged with the regex hits and
  anonymised with the same stable-placeholder scheme.

Mappings are session-stable: the same entity maps to the same placeholder
across every utterance in one session. The narrative is de-anonymised before
it lands in the local SQLite cache, so stored entries keep the real names.

**Local-only, fail-closed — by construction.** The layer-2 detector refuses
any non-local `base_url` (a cloud endpoint is rejected at construction). If
the local model is unreachable the shield raises rather than forwarding
partially-redacted text — the cloud call does **not** proceed. There is no
cloud fallback for the redaction pass by design.

**Honest scope.** Layer 1 + layer 2 substantially reduce what a cloud
provider can see, but no client-side redaction is provably exhaustive
against free-form dictation. The **ultimate** guarantee is to run the model
layer itself locally: point `LLM_BASE_URL` at Ollama / local Whisper and no
transcript — redacted or not — leaves the firm's infrastructure. The audit
chain still works because the IDR engine signs at the local-host boundary.

## Configuration (`client/.env`)

| Var | Default | Purpose |
|-----|---------|---------|
| `OPENAI_API_KEY` | — | OpenAI-compatible API key |
| `LLM_BASE_URL` | OpenAI | Override for DeepSeek, Ollama, any OpenAI-compat endpoint |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for whichever provider |
| `CONFIDENCE_THRESHOLD` | `0.7` | Below this, DONNA asks a clarifying question instead of locking the IDR |
| `CACHE_DB` | platform default | SQLite path for local cache |
| `DONNA_PII_SHIELD` | on | Set `0`/`false`/`off` to disable the PII Shield (ON otherwise) |
| `PII_LOCAL_LLM_BASE_URL` | `http://localhost:11434/v1` | Layer-2 detector endpoint — **must be a local host** (cloud URLs are refused) |
| `PII_LOCAL_LLM_MODEL` | `llama3.2` | Local model name for the layer-2 redaction pass |
| `DONNA_NOTARISE_KEY` | — | HMAC signing key for the audit chain |
| `DONNA_WEBHOOK_URL` | — | Optional: POST every IDR to your own backend |

## When this skill should NOT activate

- Pure document drafting (use the document-layer tooling — DONNA routes to
  it, does not replace it; manifesto Rule of Non-Replication)
- Long-form contract review (use the firm's existing legal-AI tooling)
- Anything not connected to delegation, time entry, IDR query, or export

If the user's request is ambiguous, ask: *"Delegation, time entry, query,
or export?"* — DONNA confirms intent before locking an IDR.

## Falsification

This skill is wrong if:

- The MCP server's tool surface drifts from the Python client's CLI flags
  (keep them aligned; the test suite covers this)
- Lawyers prefer typing over speaking after week 2 of usage — typed:voice
  ratio above 70:30 means voice is not the right modality
- The two-layer PII Shield (regex + local inference) misses a client-name
  entity in real transcripts at >2% rate, OR a fresh clone shows the shield
  unwired (Router building an Extractor with `pii_session=None`), OR the
  layer-2 detector can be pointed at a cloud endpoint — any of these breaks
  the "real names stay local before the cloud call" promise
  (regression-guarded by `tests/test_pii_shield.py`)
- The IDR chain rejects valid IDRs at >0.1% rate — chain integrity is the
  brand promise; any failure rate above noise breaks the verb

Track these via the project's hypothesis registry (deadline 2026-06-04 for
the post-launch pilot).

## See also

- Repo: `github.com/chiefofstaff-legal/donna`
- Audit chain demonstration: [`PROBAT.md`](../PROBAT.md)
- Five-waypoint journey: [`ROADMAP.md`](../ROADMAP.md)
- Open audit-chain protocol: [happi.md v1.1](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292)
