# Contributing to DONNA

> *Decision-Oriented Network Notarisation for Attorneys*

Thank you for considering a contribution. This document is short on purpose: most of what you need is in the linked policies.

## The shortest path to a merged PR

1. **Open an issue first.** Describe the problem you want to solve. We respond on a 72-hour SLA during weekdays. This step prevents wasted work — most rejected PRs are rejected because the underlying assumption was wrong, not because the code was bad.
2. **Branch from `main`.** Branch names follow `type/short-description`, e.g. `feat/voice-german-fallback`, `fix/idr-replay-edge-case`, `docs/install-cursor`.
3. **Keep PRs small.** A reviewable PR is one that fits in a single mental session — usually fewer than 400 changed lines. Larger work is decomposed.
4. **Tests for new behaviour.** New features add tests. Bug fixes add a regression test for the exact bug. Refactors keep existing tests passing without weakening them. *Tests must verify behaviour, not implementation details.*
5. **Conventional commit messages.** First line: `type(scope): subject` (≤72 chars). Empty line. Body explains *why*, not *what*. No emojis. No AI attribution unless the contribution is genuinely co-authored.
6. **One PR, one concern.** A PR that fixes a bug *and* adds a feature *and* refactors the surrounding module is rejected on shape — please split.

## Commit message format

```
feat(voice): add German fallback for STT

The Whisper small model occasionally drops German legal terminology that
the medium model handles correctly. This adds a tier escalation: small →
medium on confidence < 0.7, medium → large on confidence < 0.5.

Tested against the BGH transcript corpus (n=120). Confidence-tier
escalation triggered on 18% of utterances; transcription accuracy rose
from 89% to 96% on those utterances.

Refs: #142
```

Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`, `build`, `ci`.

## Co-authorship

If your PR is co-authored, use [GitHub's Co-authored-by trailer](https://docs.github.com/en/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/creating-a-commit-with-multiple-authors):

```
Co-authored-by: Name <email@example.com>
```

## License

By contributing, you agree that your contributions are licensed under the [GNU AGPL-3.0](LICENSE) — the same licence as the project.

The IDR engine (NEXUS tier) is licensed separately and is **not** open to community contributions; PRs that touch the IDR engine boundary (inputs/outputs, protocol compatibility) are welcome, but the engine implementation itself is closed.

## Issue triage labels

| Label | Meaning |
|-------|---------|
| `bug` | Something is broken in shipped code |
| `feature` | New behaviour the project does not yet have |
| `docs` | Documentation gap or error |
| `regression` | Worked before, broken now |
| `discussion` | Open question, no implied action yet |
| `good-first-issue` | Self-contained, well-scoped, suitable for first contribution |
| `help-wanted` | We need a collaborator on this — domain expertise required |
| `wontfix` | Decision recorded; PR addressing this will be closed |

## Communication

- **GitHub issues** — primary channel for technical discussion
- **Security disclosures** — see [SECURITY.md](SECURITY.md), do not open a public issue

## Code of Conduct

This project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Disagree with the argument, never the person. Be precise. Be kind. *Sine ira et studio* — without anger and without favour.

## What not to do

- **Do not** open a PR without an issue when the change is non-trivial.
- **Do not** rebase a long-lived branch against `main` mid-review unless asked. Force-pushing during review breaks the review thread.
- **Do not** add dependencies casually. Every new dependency is a security and supply-chain consideration. Justify it in the PR body.
- **Do not** include marketing language ("revolutionary", "next-gen", "game-changing") in code comments, docs, or commit messages. Specific evidence beats adjectives.

---

*DONNA probat.* — The DONNA team
