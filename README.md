# DONNA

**Decision-Oriented Network Notarisation for Attorneys**

> *DONNA handles the work around the work — so judgement stays with the lawyer.*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-b35e15.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Status: alpha](https://img.shields.io/badge/Status-alpha-grey.svg)](#status)
[![Surface: open](https://img.shields.io/badge/Surface-AGPL--3.0-b35e15.svg)](#what-ships-open)
[![Substrate: NEXUS tier](https://img.shields.io/badge/Substrate-NEXUS%20tier-grey.svg)](#what-ships-proprietary)
[![Roadmap: published](https://img.shields.io/badge/Roadmap-published-b35e15.svg)](ROADMAP.md)
[![Tests](https://github.com/chiefofstaff-legal/donna/actions/workflows/test.yml/badge.svg)](https://github.com/chiefofstaff-legal/donna/actions/workflows/test.yml)

Open-source delegation orchestration for legal practice. The lawyer speaks. DONNA routes. The proof is signed. *Judgement stays with the lawyer.*

> **A note on incompleteness.** DONNA OSS is alpha. We publish the [ROADMAP](ROADMAP.md) before the launch precisely because we are not finished. The journey vector — five waypoints from where we are today to the full delegation orchestration layer — is named, shared, and open to contribution. *"A clear starting point and a clear direction makes being incomplete acceptable."* (CC+|, 2026-05-08)

> **Why this matters now.** *Munir v Secretary of State for the Home Department* [2026] UKUT 81 — the UK Upper Tribunal ruled in November 2025 that uploading client material to a public AI service destroys legal privilege permanently, and explicitly distinguished *"closed-source AI tools which do not place information in the public domain"* as acceptable. The privilege boundary is now judicial authority, not Law Society guidance. Self-hosted, audit-chained, never-leaves-the-firm is no longer a sales pitch — it is a practising-certificate question. DONNA is built for that question. ([Source.](https://caselaw.nationalarchives.gov.uk/ukut/iac/2026/81))

---

## What DONNA is

Senior lawyers spend a day a week *coordinating the work around the work* — arranging inputs, progressing steps, copy-pasting outputs between tools. The AI handles the task. The lawyer still handles the orchestration. That coordination is where billable hours go.

DONNA takes the orchestration. The lawyer speaks the intent — *"send Sarah the M&A precedent we used for Dubrovnik, ask her to redline by Tuesday, copy Marcus when she replies"* — and DONNA routes it: to the right person, the right system, the right tool. Every delegated decision is captured as a structured **IDR (Intent Decision Record)**, signed with HMAC-SHA256, chained, replayable, exportable in regulator-ready formats.

This is not transcription. We do not store voice notes for later interpretation. *Speech is a means, not the product.*

The acronym is the brand. Each letter carries its own meaning:

| Letter | Word | What it means |
|--------|------|---------------|
| **D** | Decision | The unit of work in DONNA is the Decision. Every delegated action produces a structured record — an **IDR (Intent Decision Record)** — not a chat log buried in someone's history. Who decided, on what evidence, with what confidence: captured at the moment it happened. |
| **O** | Oriented | The whole architecture orients around Decisions — not around documents (like Mike, Harvey, Legora) and not around chats (like ChatGPT). The decision itself is the first-class object; documents and conversations are inputs to it. Orientation, not interface, is what makes DONNA a different category. |
| **N** | Network | Two networks at once. **A network of language models** — DONNA routes between providers (cloud, self-hosted, on-device) so the firm is never locked to one vendor or one model's failure mode. **A network of attorneys and matters** — delegated decisions are preserved across the firm and across firms, not a single conversation. |
| **N** | Notarisation | Every delegated decision is signed and linked to the one before it — like a notary's stamp on each page of a logbook. The chain cannot be quietly altered. It replays for audit, for regulators, and for any partner who needs proof of what was decided and when. (Implementation: HMAC-SHA256 signature + `previous_hash` chaining — see [`PROBAT.md`](PROBAT.md) and [`bin/notarise`](bin/notarise) for the live demonstration.) |
| **A** | (for) Attorneys | The legal vertical, exactly. Attorneys are both the audience DONNA serves and the partners who shape what it becomes — not adjacent professions, not generalist agents, and not a finished product without practitioner expertise. We defer to experienced lawyers to tell us what is missing and to help build it. |

The acronym is the **explanation**, not the marketing. The substrate is the IDR, the audit chain, and the multi-party verification model.

> **Look at [`PROBAT.md`](PROBAT.md)** at the root of this repository. Every commit on DONNA's main branch generates an IDR — `decision_id`, `previous_hash`, `commit_sha`, `signer`, `confidence`, HMAC-SHA256 signature. The chain notarises itself. Verify any entry locally with `bin/notarise verify --chain PROBAT.md` (Python stdlib, no dependencies). *DONNA probat* is not a slogan; it is a runtime invariant of this repository. The repo is its own audit-chain demo.

---

## What ships open

Released under **AGPL-3.0**:

- **Voice surface** — speech-to-text, intent extraction, conversation routing
- **MCP server scaffolding** — for Claude Desktop, Cursor, Claude Code, and any MCP-compatible client
- **Skill files** — the conversational behaviours that turn voice into operations work (time entry, task delegation, matter summary)
- **HAPPI/1.1 protocol reference** — the open audit-chain protocol DONNA implements (see [happi.md](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292))

A firm can clone this repository, run it on its own infrastructure, point it at a local model, and never touch our servers.

## What ships proprietary

The **IDR engine** — the implementation that signs, chains, and verifies every model decision — is the substrate of our **NEXUS tier**. The protocol is open ([happi.md v1.1](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292)); the engine is licensed.

Inverted Red Hat: open surface, proprietary substrate. The lawyer can host the surface; the audit chain is what the firm pays for.

---

## First reference implementation

The running MVP at **[free.donnaoss.com](https://free.donnaoss.com)** is open-sourced at **[chiefofstaff-legal/nexus](https://github.com/chiefofstaff-legal/nexus)** under AGPL-3.0. It implements the happi/1.1 protocol from this repository end-to-end: a PROBAT.md chain emitted by nexus verifies via `bin/notarise verify --chain` from this repo, byte-for-byte.

```bash
git clone https://github.com/chiefofstaff-legal/nexus.git
export DONNA_NOTARISE_KEY=nexus-public-demo-key-2026-05-11
python3 bin/notarise verify --chain ../nexus/PROBAT.md
# OK: 3 record(s) verified (HMAC-SHA256)
```

nexus is the public face — full UI, FastAPI backend, document processing, audit chain, 27 OSS services. The 5 NEXUS-tier services (sensitivity router, council, classifier, PII detection, scorer) live in a separate private repository at `CodeTonight-SA/nexus-engine` and are imported only by the hosted deployment. The open-source clone runs with a simpler single-model router.

---

## Install

> **Status:** alpha. Public release `v0.1.0` is **not yet tagged**.

Three paths, depending on how deep you want to go. Each path builds on the one before it.

### 1. The 60-second demo — watch the whole pipeline in one command

You don't need to install anything to see the substance. Clone the repo, run one command, watch a full DONNA workflow end-to-end: three lawyer utterances → intent extraction → signed IDRs → audit-chain verification → replay.

```bash
git clone https://github.com/chiefofstaff-legal/donna.git
cd donna
make demo
# (or: python3 demo/demo.py)
```

The whole pipeline runs in well under a second, with **zero dependencies** (stdlib Python only). You'll see three real lawyer-flavoured utterances pass through:

```
Lawyer says: "Just spent 90 minutes on the Smith motion drafting the indemnity clauses."
  → intent: {category: time_entry, duration_hours: 1.5, matter: Smith}
  → IDR signed: idr_...  sig: 3516328196275e94…
```

…three of those, chained, then verified (`OK: 3 record(s) verified (HMAC-SHA256)`), then replayed in plain English — *exactly what a regulator reads in an audit*.

If you want to spot-check just the static audit chain that ships with the repo:

```bash
export DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08
python3 bin/notarise verify --chain PROBAT.md
# expected: OK: 3 record(s) verified (HMAC-SHA256)
```

That's the entire substrate — about 200 lines of stdlib Python, no dependencies, no servers, no LLM keys required.

### 2. The 5-minute MCP server — talk to DONNA from your AI client

If you have Node.js 18+, you can run the MCP server locally and connect any MCP-compatible client (Claude Desktop, Claude Code, Cursor) to it.

```bash
cd mcp-servers/donna
npm install
npm run build
npm start
# server listens on http://localhost:3102
```

Add it to your AI client and you can ask the assistant to use DONNA's tools.

### 3. The full install — voice surface, Python client, AI-client wiring

For the full path — Python client setup, voice mode, microphone configuration, AI-client config files for Claude Desktop and Claude Code, and troubleshooting — read **[`docs/install.md`](docs/install.md)**. It walks through every step in plain language, with the exact commands for macOS, Linux, and Windows, and a troubleshooting table for the four most common install snags.

If you only read one document beyond this README, read that one.

More about DONNA — including the legal context, the licensing model, and the launch story — at **[donnaoss.com](https://donnaoss.com)**.

## How it fits

```
                     ┌─────────────────────┐
                     │   Voice / phone /   │
                     │      browser        │
                     └──────────┬──────────┘
                                │
                                ▼
              ┌───────────────────────────────────┐
              │  DONNA voice surface (AGPL-3.0)   │
              │  STT · intent · skill routing     │
              └──────────────┬────────────────────┘
                             │
                             ▼
              ┌───────────────────────────────────┐
              │  Any LLM provider (HAPPI/1.1)     │
              │  cloud · self-hosted · on-device  │
              └──────────────┬────────────────────┘
                             │
                             ▼
              ┌───────────────────────────────────┐
              │  IDR engine (NEXUS tier)          │
              │  HMAC-SHA256 · chain · export     │
              └───────────────────────────────────┘
```

The voice surface and MCP server ship in this repository under AGPL-3.0. The model layer is provider-agnostic via the open [HAPPI/1.1 protocol](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292) — point it at any compatible vendor or a self-hosted model. The IDR engine is the one part the firm pays for.

---

## Why we made the licensing axes inverted

In 1993 Red Hat made Linux into a business by giving away the bits and selling the *services* around the bits. DONNA inverts the axes: the **service** (voice, transcription, skill routing) is open; the **substrate** (verifiable decision audit chain) is proprietary.

The voice surface should be hospitality — a thing the firm can clone, run, modify, and self-host. The audit chain is the substantive guarantee — *DONNA probat*, the verb that names the brand. We sell the proof, we give away the listening.

This puts the firm in control of two trade-offs separately: privacy (run the voice locally, no data leaves the firm) and verifiability (subscribe to the audit-chain engine when the matter requires regulator-grade provenance).

---

## Acknowledgements

| Project | Author | What |
|---------|--------|------|
| [Mike](https://github.com/willchen96/mike) | Will Chen | Open-source legal AI for the document layer (29 April 2026, AGPL-3.0). DONNA is the operations-layer sibling. |
| [Mike PR #20](https://github.com/willchen96/mike/pull/20) | Joseph Breda | Local-LLM provider via vLLM — the architectural primitive that makes Mike usable inside firms with hard data-residency requirements. |
| [Omnilex](https://omnilex.ai) | Ismael Seck, Marco Henri | Open Swiss legal-research engine for the DACH region. The knowledge layer of the open legal stack. |
| [happi.md](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292) | @architext1 | The open audit-chain protocol DONNA implements — passport for AI agents. |
| [CloseVector](https://closevector.ai) | Dean Hoffman | On-premises AI document search with cryptographic audit chain (patent pending). Audits retrieval; DONNA audits delegation. Different layers of the same architectural insight. |

---

## Status

- **Release:** alpha. `v0.1.0` tag pending public launch.
- **Voice surface:** scaffolding in `mcp-servers/donna`. STT pipeline, skill registry, intent router on the roadmap.
- **Provider abstraction:** HAPPI/1.1 envelope — any OpenAI-compatible vendor or self-hosted model.
- **IDR substrate:** proprietary engine; protocol reference at [happi.md v1.1](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292).

See [CHANGELOG.md](CHANGELOG.md) for the running record.

---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit-message format, the PR template, and the AGPL-3.0 contribution model.

The shortest path: open an issue describing the problem before writing code. Small, focused PRs against `main`. Tests for new behaviour. We respond on a 72-hour SLA during weekdays.

For security issues, please follow [SECURITY.md](SECURITY.md) — do not open a public issue.

## Code of Conduct

This project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Be precise, be kind, and disagree with the argument rather than the person. *Sine ira et studio.*

---

## License

The voice surface, MCP server, skill files, and provider adapters in this repository ship under the [GNU Affero General Public License, version 3](LICENSE).

The IDR engine — the implementation of the audit chain described in `happi.md` — is licensed separately as part of the NEXUS tier. The protocol is open; the engine is not.

DONNA is built by **the DONNA team** at CodeTonight (Cape Town · Zurich) in collaboration with [chiefofstaff.pro](https://chiefofstaff.pro).

*DONNA probat.*
