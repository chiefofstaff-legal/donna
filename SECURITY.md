# Security Policy

## Reporting a vulnerability

> Please **do not** open a public GitHub issue for security vulnerabilities.

DONNA handles legal-practice voice and decision data. A vulnerability in the voice surface, the IDR boundary, or the protocol we implement could expose privileged client information. Treat this seriously, and we will too.

### How to report

Email: `security@codetonight.co.za`

Include:
- A clear description of the vulnerability
- Steps to reproduce, or a proof of concept
- The version, commit SHA, or release tag where you observed it
- Your assessment of severity (informational / low / medium / high / critical)
- Whether you have publicly disclosed any details, and if so, where

Optional: encrypt your email with our PGP key (published at the email contact above on request).

### What to expect

- **Acknowledgement** within 72 hours during weekdays.
- **Triage** within 7 days — we will tell you whether we accept it, contest it, or need more information.
- **Fix timeline** — we will give you our internal target. Critical vulnerabilities target same-week patches; lower severity ones follow our regular release cadence.
- **Public disclosure** — we coordinate the disclosure with you. Default: 90 days from acknowledgement, or earlier if a fix has shipped and 30 days have passed since the patched release.

### Recognition

We are grateful for responsible disclosure. With your permission, we will list you in the project's `SECURITY-HALL-OF-FAME.md` once we have published one.

## Supported versions

| Version | Status |
|---------|--------|
| `main` (HEAD) | Supported |
| `v0.x` (alpha) | Supported until `v1.0` ships |
| Older | Not supported — please upgrade |

## Scope

In scope for this policy:
- Voice surface (`mcp-servers/donna`, skill files, intent router)
- The `happi.md` protocol reference (open)
- IDR engine **boundary** (inputs, outputs, protocol compliance) — even though the engine itself is licensed separately, vulnerabilities at the API boundary affect both sides

Out of scope:
- The IDR engine implementation itself (licensed separately under NEXUS tier — disclosure handled via the licence channel)
- Issues in upstream dependencies (please report those upstream first; we will track and update once patched)
- Theoretical attacks without a working proof of concept (we accept reports, but they do not get the same priority as reproducible findings)

## Threat model summary

We design against:
- **Privileged data exfiltration** — voice transcripts, IDR contents, model decisions
- **Audit chain tampering** — modification of an IDR after signing without detection
- **Replay attacks** — re-submitting old IDRs as if they were new
- **MCP server compromise** — RCE or unauthorized command execution via the MCP boundary
- **Supply chain compromise** — malicious dependencies or build-time injection

We do **not** design (in v0.x) against:
- Nation-state actors with persistent access to firm infrastructure (out of scope; firms must layer their own controls)
- Side-channel attacks on the firm's hardware
- Social engineering of firm staff (process problem, not software)

## Disclosure timeline of past advisories

None yet — public release `v0.1.0` pending.

---

*DONNA probat. Reported issues are taken seriously and fixed precisely.*
