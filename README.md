# DONNA

**DONNA — Decision-Oriented Network Notarisation for Attorneys**

> *The lawyer speaks. DONNA routes. The proof is signed. Judgment stays with the lawyer.*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-b35e15.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Status: alpha](https://img.shields.io/badge/Status-alpha-grey.svg)](#status)
[![Tests](https://github.com/chiefofstaff-legal/donna/actions/workflows/test.yml/badge.svg)](https://github.com/chiefofstaff-legal/donna/actions/workflows/test.yml)

---

## What this is, in plain words

Senior lawyers lose about a day a week to the work *around* the work — arranging
inputs, chasing the next step, copy-pasting between tools. The AI does the task;
the lawyer still does the coordination. That coordination is where billable hours
quietly go.

DONNA takes the coordination. You say what you want — *"send Sarah the M&A
precedent we used for Dubrovnik, ask her to redline by Tuesday, copy Marcus when
she replies"* — and DONNA routes it to the right person, system, and tool. Every
delegated decision is captured as a signed, tamper-evident receipt: who decided,
on what evidence, with which AI model, when. The receipt replays years later on a
regulator's laptop with nothing but Python's standard library. Judgement stays
with the lawyer; only the coordination is handed over.

**Why now.** In late 2025 a UK tribunal ruled that putting client material into a
public AI service permanently destroys legal privilege — and pointedly treated
*closed, self-hosted* tools as the acceptable alternative. Overnight, "where does
our client data actually go?" stopped being an IT preference and became a
practising-certificate question. DONNA is built to be self-hosted and not bound
to any one AI vendor, so a firm can answer that question for itself.
[Read the legal detail →](#why-now-the-legal-detail)

---

## See it in 60 seconds

You install nothing to see the substance. Clone, run one command, and watch a
full workflow end to end — three lawyer utterances, intent extraction, signed
records, chain verification, plain-English replay:

```bash
git clone https://github.com/chiefofstaff-legal/donna.git
cd donna
make demo          # or: python3 demo/demo.py
```

It runs in well under a second with **zero dependencies** (Python standard
library only):

```
Lawyer says: "Just spent 90 minutes on the Smith motion drafting the indemnity clauses."
  → intent: {category: time_entry, duration_hours: 1.5, matter: Smith}
  → IDR signed: idr_…  sig: 3516328196275e94…
…three of those, chained, then: OK: 3 record(s) verified (HMAC-SHA256)
```

To spot-check just the static chain that ships with the repo:

```bash
export DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08
python3 bin/notarise verify --chain PROBAT.md
# OK: 3 record(s) verified (HMAC-SHA256)
```

That is the whole substrate: roughly 200 lines of standard-library Python — no
servers, no LLM keys, no dependencies.

---

## The name is the explanation

DONNA is an acronym. Each letter carries a load:

| Letter | Word | What it means |
|--------|------|---------------|
| **D** | Decision | The unit of work. Every delegated action produces a structured **IDR (Intent Decision Record)** — not a chat log buried in someone's history. Who decided, on what evidence, with what confidence, captured as it happens. |
| **O** | Oriented | The architecture orients around decisions — not documents (Mike, Harvey, Legora) and not chats (ChatGPT). The decision is the first-class object; documents and conversations are inputs to it. |
| **N** | Network | Two networks. A network of **language models** — one intent routes across many providers via the open HAPPI/1.1 envelope, so switching vendor is config, not code. A network of **attorneys and matters** — decisions persist across the firm, not in one conversation. |
| **N** | Notarisation | Every decision is signed and chained to the one before it, like a notary's stamp on each page of a logbook. The chain cannot be quietly altered; it replays for audit and for any partner who needs proof. (HMAC-SHA256 + `previous_hash` — see [`PROBAT.md`](PROBAT.md).) |
| **A** | (for) Attorneys | The legal vertical, exactly. Attorneys are both the audience DONNA serves and the practitioners who shape what it becomes. We defer to experienced lawyers on what is missing. |

**The repository proves it on itself.** Every merge to `main` appends a signed
IDR to [`PROBAT.md`](PROBAT.md) via the `probat-extend` CI workflow. The chain
notarises its own history — verify any entry with the command above. *DONNA
probat* is not a slogan; it is a runtime invariant of this repo.

---

## Open service, proprietary substrate

In 1993 Red Hat built a business by giving away the bits and selling the services
around them. DONNA inverts the axes: the **service is open**, the **substrate is
licensed**.

- **Open, under [AGPL-3.0](LICENSE)** — the voice surface (speech-to-text, intent
  extraction, routing), the MCP server scaffolding for any MCP-compatible client,
  the skill files, and the [HAPPI/1.1 protocol reference](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292).
  Clone it, run it on your own hardware, point it at a local model, switch
  providers at will, audit every line.
- **Proprietary — the NEXUS tier** — the IDR engine that signs, chains, and
  verifies every model decision. The *protocol* is open; the *engine* is what a
  firm subscribes to when a matter needs regulator-grade provenance.

A firm controls two things separately: privacy (run the voice locally, no data
leaves) and verifiability (subscribe to the audit-chain engine when the matter
warrants it). [Why we built the licence axes this way →](https://about.grip-web.com)

### First reference implementation

The running MVP at **[free.donnaoss.com](https://free.donnaoss.com)** is
open-sourced at **[chiefofstaff-legal/nexus](https://github.com/chiefofstaff-legal/nexus)**
under AGPL-3.0. It implements the HAPPI/1.1 protocol from this repository
end-to-end — a `PROBAT.md` chain emitted by nexus verifies byte-for-byte with
`bin/notarise verify --chain` from this repo. The hosted deployment adds a small
set of NEXUS-tier services from a separate private repository; the open clone
runs with a simpler single-model router.

---

## Install

> **Status:** alpha. Public release `v0.1.0` is **not yet tagged**.

Three paths, each building on the last. Full step-by-step instructions for every
platform — including AI-client config and a troubleshooting table — are in
**[`docs/install.md`](docs/install.md)**. If you read one document beyond this
one, read that.

1. **The 60-second demo** — `git clone` + `make demo`. Nothing to install; see
   the whole pipeline run. (Above.)
2. **The 5-minute MCP server** — Node.js 18+, then `cd mcp-servers/donna && npm
   install && npm run build && npm start`. Connect any MCP-compatible client
   (Claude Desktop, Claude Code, Cursor) and ask it to use DONNA's tools.
3. **The full install** — Python client, voice mode, microphone, AI-client
   wiring for macOS, Linux, and Windows: [`docs/install.md`](docs/install.md).

---

## Go deeper

The long technical and positioning material lives outside this README so the
README stays readable:

| To understand… | Read |
|-----------------|------|
| The architecture and the wider stack (substrate · router · interface · orchestration · verification) | [about.grip-web.com](https://about.grip-web.com) §23 (DONNA), §24 (MIKE), §25 (AGORA) |
| Where DONNA is going (the five-waypoint journey vector) | [ROADMAP.md](ROADMAP.md) |
| Worked end-to-end examples | [docs/SCENARIOS.md](docs/SCENARIOS.md) |
| The open audit-chain protocol | [happi.md v1.1](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292) |
| The legal context, licensing model, and launch story | [donnaoss.com](https://donnaoss.com) |

**The wider stack** — no single layer is load-bearing:

| Layer | Project | Role |
|-------|---------|------|
| Substrate | GRIP | The recursive-self-improvement engine that builds and verifies the stack. |
| Provider router | HAL | Routes one intent across many providers; a price change or outage is a config flip. |
| Interface | MCP | The open Model Context Protocol; DONNA ships an MCP server. |
| Orchestration | **DONNA** (this repo) | Decision-oriented delegation for legal practice. |
| Verification | AGORA | The same intent goes to N models; the agreement score is recorded in the chain. |

**MIKE** (Will Chen; local-LLM path by Joseph Breda) is the document-layer open
project. DONNA is the operations-layer open project. They share the open
[HAPPI/1.1 protocol](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292)
and are designed to interoperate, not compete.

---

## Why now — the legal detail

In November 2025 the UK Upper Tribunal handed down ***Munir v Secretary of State
for the Home Department* [2026] UKUT 81**. It held that uploading client material
to a public AI service destroys legal privilege permanently, and explicitly
distinguished *"closed-source AI tools which do not place information in the
public domain"* as acceptable. The privilege boundary is now judicial authority,
not professional-body guidance. ([Source.](https://caselaw.nationalarchives.gov.uk/ukut/iac/2026/81))

That is the structural reason DONNA exists in its current shape: self-hosted,
audit-chained, and provider-agnostic by construction — so the answer to *"where
does our client data go?"* is decided by the firm, not by a vendor's roadmap.

---

## Status

- **Release:** alpha. `v0.1.0` tag pending public launch.
- **Voice surface:** scaffolding in `mcp-servers/donna`; STT, skill registry, and
  intent router are on the [roadmap](ROADMAP.md).
- **Provider abstraction:** HAPPI/1.1 envelope — any OpenAI-compatible vendor or
  a self-hosted model.
- **IDR substrate:** proprietary engine; open protocol reference at
  [happi.md v1.1](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292).

See [CHANGELOG.md](CHANGELOG.md) for the running record.

---

## Acknowledgements

| Project | Author | What |
|---------|--------|------|
| [Mike](https://github.com/willchen96/mike) | Will Chen | Open-source legal AI for the document layer (AGPL-3.0). DONNA is the operations-layer sibling. |
| [Mike PR #20](https://github.com/willchen96/mike/pull/20) | Joseph Breda | Local-LLM provider via vLLM — the primitive that makes Mike usable inside firms with hard data-residency requirements. |
| [Omnilex](https://omnilex.ai) | Ismael Seck, Marco Henri | Open Swiss legal-research engine for the DACH region — the knowledge layer of the open legal stack. |
| [happi.md](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292) | @architext1 | The open audit-chain protocol DONNA implements. |
| [CloseVector](https://closevector.ai) | Dean Hoffman | On-premises AI document search with a cryptographic audit chain (patent pending). It audits retrieval; DONNA audits delegation — the same insight, different layers. |

---

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
commit-message format, the PR template, and the AGPL-3.0 contribution model. The
shortest path: open an issue describing the problem before writing code; keep PRs
small and focused against `main`; add tests for new behaviour. We respond within
72 hours on weekdays. For security issues, follow [SECURITY.md](SECURITY.md) — do
not open a public issue.

This project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Be
precise, be kind, and disagree with the argument rather than the person.
*Sine ira et studio.*

---

## Licence

The voice surface, MCP server, skill files, and provider adapters in this
repository ship under the [GNU Affero General Public License, version 3](LICENSE).
The IDR engine — the implementation of the audit chain described in `happi.md` —
is licensed separately as part of the NEXUS tier. The protocol is open; the
engine is not.

DONNA is built by the DONNA team at CodeTonight (Cape Town · Zurich) in
collaboration with [chiefofstaff.pro](https://chiefofstaff.pro).

*DONNA probat.*
