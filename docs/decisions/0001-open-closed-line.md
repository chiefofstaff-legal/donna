# 0001. The Open/Closed Line — what we give away, what we keep

- Status: proposed
- Date: 2026-06-16

## The one sentence

**We open the service. We keep the substrate.** Anyone can clone, run, and
build on the part of DONNA that listens, understands, and acts. The part
underneath that *proves* every decision is trustworthy — and the factory that
builds DONNA — stay ours. That is the deal. (The repo's shorthand for this is
*"Inverted Red Hat"*: the classic open-source company gives away the software
and sells the service on top; we give away the service and sell the substrate
beneath it.)

## Why we do it this way

Two facts decide everything:

1. **Law firms pay for proof, not for plumbing.** The thing a regulated legal
   practice will actually pay for is a tamper-proof, audit-ready record that
   every delegated decision can be traced and verified. That is the IDR engine.
   So the IDR engine is what we keep.
2. **Secrecy is a weak lock; a standard is a strong position.** Keeping the
   plumbing secret would only slow people adopting us — it would not protect
   the real value. If instead the whole legal-AI world builds on our open
   rails, we become the standard everyone speaks, and every project built on
   us is a doorway to our paid proof-engine.

So: give away the rails to grow the field and set the standard; keep the proof
engine because that is the part worth paying for.

## The line — in plain English

A simple test decides each piece:

> **Is it part of the running service, or is it the substrate underneath?**
> Service → open. Substrate (the proof engine + the factory that builds DONNA)
> → ours.

| Part | What it actually is | Open or ours |
|------|---------------------|--------------|
| Voice surface | DONNA listening and understanding what you say | **Open** (AGPL-3.0) |
| Skill files | The task playbooks DONNA runs | **Open** |
| MCP server | The connector that plugs DONNA into Claude Desktop, Cursor, IDEs | **Open** |
| HAL (provider router) | The switchboard sending each request to the best/cheapest AI provider | **Open** |
| AGORA | Several AIs independently check each change | **Open** |
| HAPPI/1.1 protocol | The shared "language" for AI audit records — an open spec anyone can implement | **Open** (public spec) |
| **IDR engine** | The tamper-proof signing, chaining and verifying that proves every decision — *what firms pay for* | **Ours** (NEXUS tier) |
| HAPPI 1.2 memory-context chain | *(new, not yet shipped)* how DONNA proves what it remembered and when | **Ours** — joins the IDR engine, *if it is substrate-grade proof* (decision pending) |
| GRIP | The self-improving engine that *builds and verifies* DONNA — our private factory, never shipped inside the product | **Private** — not part of the open project at all |

## What is settled, and what is still a live choice

- **Settled (already published open):** the voice surface, skills, MCP server,
  HAL, AGORA, and the HAPPI/1.1 protocol. Important: *a version we have already
  published as open can be copied and continued by anyone forever.* We can
  close future versions, but we cannot recall what is already out. So for these
  pieces the line only ever moves **outward** (more open), never back.
- **Settled (already private):** GRIP (the factory) and the IDR engine. These
  were never in the open product. Keeping them is the status quo, not a change.
- **Still a live choice — decide before it ships:** the new HAPPI 1.2
  memory-context chain, and any future component. New pieces are decided at the
  line *before* they are published, never after.

## What this gives us, and what we accept

**Easier:** anyone can clone, run, self-host and contribute; we set the
standard; every open deployment is a path to the paid proof-engine.

**Harder:** we live with the rails being public — competitors can build on
them too. We win not by hiding the plumbing but by being the trusted original
with the proof engine and the best finished product.

**We accept:** the open rails are a gift to the field on purpose. Our moat is
not their secrecy — it is the proof engine (IDR), the firm's trust, the audit
trail that builds up over time, and the whole thing working together.

---

*Owner: V>>. Status moves to `accepted` on review. The licence mechanism for
each open piece (AGPL-3.0 alone vs AGPL + a commercial option) is a separate
decision and needs legal sign-off, because licensing a legal product's code
interacts with its own liability story.*
