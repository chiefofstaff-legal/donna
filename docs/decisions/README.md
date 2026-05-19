# Decision records

This directory holds short ADR-style decision records — what the ROADMAP
calls a *journey-vector update*.

If your contribution touches a roadmap waypoint (W1–W5) or changes a
direction the project has committed to, open a decision record here
*before* writing the code. The maintainers will respond on the pull
request or the linked issue.

## When to add one

- A contribution that changes or reorders a ROADMAP waypoint.
- A change to the open / proprietary boundary (what ships under AGPL-3.0
  versus the NEXUS tier).
- A protocol change to `happi.md` or the IDR record shape.
- Any architectural choice a future contributor would otherwise have to
  reverse-engineer from the diff.

Small, focused contributions that do not move the vector do not need a
decision record — just open a pull request.

## Format

One Markdown file per decision. Name it `NNNN-short-title.md` (zero-padded
sequence number, then a hyphenated slug). Keep it short:

```
# NNNN. Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context

What is the situation that forces a decision? One or two paragraphs.

## Decision

What we are going to do, stated plainly.

## Consequences

What becomes easier, what becomes harder, what we are accepting.
```

Status starts at `proposed`. The maintainers move it to `accepted` (or
ask for changes) on the pull request.
