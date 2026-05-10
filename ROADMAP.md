# DONNA · Roadmap

> **Decision-Oriented Network Notarisation for Attorneys**
>
> *We start small on purpose. We are not the finished thing. We are the public starting point of a journey we are openly describing — so contributors and users can see where we are, where we are going, and join us at the rung that matches their interest.*

---

## TL;DR — for the impatient

| Question | Answer |
|----------|--------|
| **What is DONNA today?** | An open-source MCP server + voice intent capture + IDR audit-chain primitive. Alpha. |
| **What is DONNA becoming?** | A **Delegation Orchestration Layer** for legal practice — the layer that absorbs the day-a-week of coordination overhead so the lawyer's judgement stays in the loop and the routing does not. |
| **Why open source?** | The voice surface, the skill files, and the MCP server should be hospitable — clone, run, modify, self-host. The cryptographic substrate (IDR engine) is licensed separately under the **NEXUS** tier. *Inverted Red Hat.* |
| **What can I contribute today?** | Skill files, voice-language coverage (DE, FR, IT), MCP-client integrations (Claude Desktop, Cursor, Claude Code, IDEs), `happi.md` protocol implementations, and — increasingly — AI-agent-authored PRs that the maintainers triage. |
| **When is `v0.1.0`?** | The public launch tag is gated on the maintainer launch sequence. Once the repo flips public, `v0.1.0` is cut from the bootstrap commit. |

---

## ELI5 (for non-engineers)

A senior lawyer's day looks like this: a lot of *deciding what should happen*, a lot of *making sure it happens*, and a lot of *checking that it happened*. The lawyer's actual judgement — the bit that earns the bill — is spread thinly across all that coordination work. Tools like Mike, Harvey, and Legora are great at the *task itself* (drafting, summarising, redlining), but the lawyer still spends a day a week stitching the inputs and outputs together by hand.

DONNA is the open-source piece that takes the stitching. The lawyer speaks the intent — *"send me the M&A precedent we used for the Dubrovnik matter, ask Sarah to redline by Tuesday, copy Marcus when she replies"* — and DONNA routes it. To the right person. The right system. The right tool. With a tamper-evident receipt that says *what was delegated, by whom, when, and what came back*.

We are not finished. The full vision is a Delegation Orchestration Layer that absorbs all the coordination friction in a legal practice. What you see in this repository today is the open part of that vision — the voice surface, the routing primitive, the audit-chain protocol. The proprietary substrate (the engine that signs and verifies every delegated decision) is what funds the project. That is the deal.

---

## The journey vector

> *"A clear starting point and a clear direction makes being incomplete acceptable."*
> — Craig Miller (CC+|), 2026-05-08

We are publishing the roadmap *before* the launch so the incompleteness is intentional, named, and shared. Five waypoints, in order. Each one is an invitation, not a promise — the order can change if a user need pulls a later waypoint forward.

```
                                  THE JOURNEY VECTOR
                                  ──────────────────
NOW                                                                          TARGET
─────────                                                                  ──────────
W1 ───→ W2 ───→ W3 ───→ W4 ───→ W5
voice    skill    audit    AI-agent  full
intent   routing  chain    PR review orchestration
```

### W1 · Voice intent surface (current → published)

**Status**: alpha · scaffold present in `mcp-servers/donna`

**What this does**: captures unstructured spoken intent — *"draft a memo on the Müller arbitration, send it to Klaus by Friday, copy Sabine if he replies"* — and structures it into intent + constraints + recipients + success criteria.

**What this explicitly is *not***: a transcription tool. We do not store voice notes for later interpretation. Speech is a means, not the product. (Manifesto Law 5: Context Preservation Over Transcription.)

**Where to contribute**:
- Speech-to-text quality fixes (German legal terminology, French Swiss-Romand idioms, Italian-Swiss canton-specific terms)
- MCP server integrations beyond Claude Desktop (Cursor, Claude Code, IDE plug-ins)
- Skill-file authoring for new operational verbs (delegation, follow-up, status check, escalation)

### W2 · Skill orchestration layer (next 3 months)

**What this does**: takes a structured intent and routes it to the right destination — a person via Slack/Teams/email, a system via API, a document workflow via existing legal-tech tooling. DONNA does not *replace* those tools. DONNA *orchestrates* them.

**The Rule of Non-Replication** (manifesto): if a mature tool already exists for a function, we do not rebuild it. We orchestrate it. Replication is strategic failure.

**Open protocols we orchestrate, not replace**:
- Email (IMAP/SMTP)
- Calendar (CalDAV)
- Document management (any system with a stable API — iManage, NetDocuments, SharePoint, Box)
- Messaging (Slack, Teams, IMessage, WhatsApp)
- Search (clio, ddocs, plus self-hosted vector stores)
- Legal AI tools that already work (Mike, Harvey, Legora, Omnilex)

**Where to contribute**:
- Connector packages (one per destination — small, focused, testable)
- Routing-rule DSL (declare *what kind of intent* goes *where*)
- Rate-limit and back-pressure handling for high-volume firms

### W3 · IDR audit chain (in flight, protocol open, engine NEXUS-tier)

**What this does**: every delegated decision DONNA makes is captured as a structured record — an **IDR (Intent Decision Record)** — and signed into a tamper-evident chain. HMAC-SHA256. `previous_hash`. Replayable. Exportable in regulator-ready formats.

**Why this matters for a 2026 legal practice**: the EU AI Act's high-risk obligations bind from 2 August 2026. *Show your work* is becoming the rule, not the aspiration. DONNA's IDR primitive is the proof DONNA assigns to itself — every delegated decision leaves a paper trail an auditor can follow line by line.

**Manifesto Law 4**: Delegation Proof Over Task Storage. We record *what was delegated and what happened*. We do not create a workspace to manage tasks. We create evidence that delegation occurred and completed.

**Open / proprietary boundary**:
- The **protocol** is open: `happi.md` v1.1 — [public Gist](https://gist.github.com/architext1/808548dd25cfac5cc47fb6e910b79292). Any AI runtime can read this and produce IDR-compatible records.
- The **engine** (the implementation that signs, chains, and verifies) is licensed under the NEXUS tier. The protocol is open; the engine is not. (See README "Why we made the licensing axes inverted" for the reasoning.)

**Where to contribute**:
- `happi.md` protocol implementations in other languages (Python ✓, TypeScript ✓, Go, Rust, Java, .NET pending)
- Test vectors for tamper-detection and replay
- Compliance mappings (EU AI Act, ISO 27001, SOC 2 Type II)

### W4 · AI-agent PR review (novel IP, building)

**What this does**: as the project scales, increasing PR volume will come from AI agents — Claude, GPT, Gemini, Llama, and others — operating on behalf of contributors. Reviewing those PRs by hand does not scale. DONNA includes a substrate for AI-agent-authored PR review where the maintainers' role becomes triage and judgement, not line-by-line review.

**The novel IP**: the AGORA pattern. Multiple models review the same PR independently against the same falsification criteria. The model verdicts are reconciled — agreement raises confidence, disagreement raises a flag for human review. Every review is itself an IDR — signed, chained, replayable.

**This is what DONNA eats first**: the project's own PR queue is the first production deployment of the AGORA pattern. We use what we ship. Every PR merged into DONNA leaves an AGORA trail. Contributors who are skeptical of AI-agent review can follow the trail and see exactly what was decided, by which model, against which criterion.

**Where to contribute**:
- Model-router connectors (HAL — Harness Abstraction Layer)
- Falsification-criterion templates for legal-domain PR types (skill files, connectors, protocol changes, IDR boundary)
- Disagreement-resolution heuristics (when do you escalate to human? When do you re-run the council?)

### W5 · Full Delegation Orchestration Layer (the destination)

**What this does**: the full vision — a Delegation Orchestration Layer that sits between intent and execution, captures unstructured intent, converts it to structured delegation, routes work to humans or systems, verifies completion, and preserves proof. The user does not "use" software — the user *delegates*, and the system handles the rest.

**What ships open at W5**: the voice surface, the skill files, the connector packs, the routing engine, the AGORA pattern, the protocol reference, and the AI-agent PR review substrate. All AGPL-3.0.

**What remains proprietary**: the IDR engine (the cryptographic substrate that signs, chains, and verifies every delegated decision) under the NEXUS tier. The protocol is open. The engine pays for the project.

**The sound bite candidates** (to be picked by the maintainers at launch):

| Candidate | What it captures | Strength |
|-----------|------------------|----------|
| **"DONNA handles the work around the work — so judgement stays with the lawyer."** | Craig's exact framing from his LinkedIn response to Will Chen | Memorable, anchored, legal-audience-native |
| **"From intent to outcome. Without managing software."** | Manifesto Buyer Clarity Test compressed | Structural claim, not feature claim |
| **"You speak. DONNA handles. Judgement stays yours."** | Terse, three-beat, lawyer-in-the-loop preserved | Quotable, self-contained |

---

## What this roadmap is *not*

Per DONNA's positioning discipline, this roadmap explicitly does NOT include:

| Out of scope | Why not |
|--------------|---------|
| A messaging platform | Slack, Teams, Email already exist. We orchestrate, we do not replicate. (Law 1) |
| A task manager | Asana, Notion, Linear already exist. We preserve delegation proof, we do not store tasks. (Law 4) |
| A note-taking app | Roam, Obsidian, OneNote already exist. We extract intent, we do not transcribe speech. (Law 5) |
| A productivity dashboard | Anything that demands routine attention is suspect. (Law 2) |
| A replacement for the lawyer's judgement | We absorb coordination friction, we do not absorb judgement. (Law 3) |

**The discipline**: every roadmap item is checked against these. If a feature replaces an existing tool, it is rejected. If it connects systems and people, it is considered.

---

## How we work

### Core principles (load-bearing for every PR)

1. **Falsifiability** — every claim, feature, and roadmap item names what would prove it wrong. PRs without a falsification anchor are sent back. (See [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).)
2. **Plain language** — code comments, error messages, and docs are readable by a non-engineer at a law firm. If a senior lawyer cannot read the README and explain DONNA to a colleague in five minutes, the README is wrong, not the lawyer.
3. **No marketing language** — "revolutionary", "next-gen", "game-changing" are absent from code, docs, and commit messages. Specific evidence beats adjectives.
4. **Tests verify behaviour, not implementation** — Goodhart-proof. A test that always passes is worse than no test.
5. **One PR, one concern** — large changes decompose into reviewable shapes. Each PR fits a single mental session.

### Triage cadence

- **Weekday PRs**: 72-hour SLA for first response.
- **Weekend PRs**: triaged on the next weekday — feel free to ping if urgent.
- **Security disclosures**: see [SECURITY.md](SECURITY.md). Do not open a public issue.

### Where to start as a new contributor

1. Read the [README](README.md) and this ROADMAP.
2. Pick a `good-first-issue` label.
3. Open an issue *before* writing code if your contribution touches a waypoint above (W1–W5).
4. For larger work, propose a *journey-vector update* in `docs/decisions/` — small ADR-style proposal. The maintainers will respond.

---

## What this asks of you

Craig Miller's directive on the day this ROADMAP shipped:

> *We should invite people to "join us" and be part of the story we write together with their input — so as to better serve their needs.*

We do not have all the answers. The roadmap above is a **vector**, not a contract. If your firm needs something earlier, tell us. If something here is missing, tell us. If we got the framing wrong, tell us — *with specific evidence, please*. The point of an open project is that the path is shared.

---

## A note on what is not here

This roadmap covers the **OSS surface only**. The full Delegation Orchestration Layer — the substrate that some firms will subscribe to as an enterprise tier — is the proprietary cousin of DONNA OSS. It lives in a different repository, ships under a different licence, and is not the focus of this document. The boundary is documented at the IDR engine line: the protocol is open here, the engine is licensed there.

If you are evaluating DONNA for a firm-scale deployment with managed audit chain, contact us via the channel in [SECURITY.md](SECURITY.md) for the enterprise conversation.

---

## Versioning the roadmap

This file is itself an artefact under change control. Material updates are tagged with a date in the table below. The waypoints survive across updates; their order, language, and inclusion criteria evolve.

| Date | Change | Author |
|------|--------|--------|
| 2026-05-08 | Initial roadmap published. Five-waypoint journey vector (voice → skill → IDR → AI-agent PR review → full DOL). | The DONNA team |

---

*DONNA probat.* DONNA proves it. The verb names the brand and constrains the work.
