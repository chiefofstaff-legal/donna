# Clio Vincent AI — wrap feasibility research

**Issue**: chiefofstaff-legal/donna#19 — "research: Clio Vincent AI wrapping — notarise Vincent invocations via IDR".
**Date**: 2026-05-24.
**Author**: V>> CBC Optimal sprint (depth-0 main session + ultraplan + broly mesh).
**Verdict**: **PARTIAL** — wrap is *architecturally feasible* with one documented
assumption pending Clio dev support verification. Implementation shipped
behind a single env-overridable constant; the wrapper's IDR semantics are
endpoint-agnostic.

---

## 1. The question issue #19 was created to answer

Verbatim acceptance criterion from issue #19:

> *"Documented answer: Vincent wrap is possible (yes/no/partial). If
> yes: working prototype with one IDR per ratified Vincent suggestion.
> If no/partial: documented limitation + alternative."*

This document is that answer.

## 2. Research trail (verify-canonical)

### 2.1 Public Clio documentation surface

Surveyed:

| Source | What it covers | Vincent endpoint named? |
|---|---|---|
| `https://docs.clio.com` | Public Clio Manage docs (matters, contacts, billing) | NO |
| `https://app.clio.com/api/v4/docs` | API v4 reference (auth, matters, time_entries, activities, documents, payments) | NO |
| `https://developers.clio.com` | Developer portal landing + sandbox onboarding | Marketing mention only — "Vincent AI" feature card, no API surface |
| Public WebSearch | `"clio vincent" api endpoint`, `clio vincent ai REST`, `clio vincent invocations` | ZERO public matches as of 2026-05-24 |

**Conclusion**: as of 2026-05-24, Clio Vincent AI is **primarily an
in-product feature in newer Clio Manage and a REST surface is not
publicly documented**. Vincent's user-facing UX (suggestion +
ratification flow on matters / time entries) is a closed-loop in-app
experience without a published third-party-callable HTTP endpoint.

### 2.2 What this means for DONNA's IDR-everything thesis

Two possibilities Clio's internal surface may permit:

1. **Direct REST endpoint** (e.g. `POST /vincent/invocations`) reachable
   by an authenticated OAuth2 token holder. If this exists, DONNA can
   intercept BEFORE the call and emit an IDR per invocation — the
   classic "wrap the syscall" pattern.

2. **Webhook event surface** (Clio emits a `vincent.suggested` event;
   DONNA subscribes). Different shape — DONNA observes AFTER the
   suggestion lands rather than wrapping the request. Same IDR
   semantics, different transport.

Neither is publicly documented. Both can be verified post-merge against
Clio dev support or a sandbox account with Vincent enabled.

## 3. Verdict: PARTIAL

We ship the **wrap pattern as code** (option 1) behind a single
env-overridable constant. The wrapper is correct-by-construction for
the IDR emission contract:

- Exactly one IDR per `vincent_call` invocation
- `intent=vincent_invocation` (canonical label, mutation-test anchored)
- `matter_id` binding (replay scope)
- Prompt SHA-256 (PII-safe — raw prompt sent to Clio, not stored in chain)
- Response SHA-256 (proof-of-receipt)
- Outcome classification mirrors clio.py's `_classify_outcome`
- `parent_decision_id` chaining to a predecessor IDR
- Failure IDRs emitted on 4xx/5xx/transport (the chain captures both
  paths — forensic value)

The wrapper's HTTP transport is parameterised over `CLIO_VINCENT_PATH`
env var. If Clio confirms a different path (e.g.
`/matters/<id>/vincent/invocations`), one env line changes the binding
without touching any wrapper code or test.

If Clio confirms there is **no** third-party REST surface and Vincent
is webhook-only, the implementation flips to a webhook-listener shape
in a follow-up issue. The IDR emission contract is reusable byte-for-byte.

## 4. Post-merge verification path

| Step | Owner | Anchor |
|---|---|---|
| 1. Open Clio dev support ticket asking: (a) is Vincent invocation reachable via REST? (b) if yes, what is the exact path + auth scope? (c) if no, is there a webhook event surface? | V>> | Anchor #3 of `rules/exogenous-anchor-law.md` — cross-provider verdict; the verifier (Clio dev support) is not the producer (DONNA) |
| 2. If REST: set `CLIO_VINCENT_PATH=<verified>` in deploy config; no code change | V>> | Env override designed-in |
| 3. If webhook: file follow-up issue "Vincent webhook listener" referencing this artefact + the wrap pattern | V>> | Wrapper code remains as the reference shape for the listener's IDR emission |
| 4. If neither: file follow-up issue "Vincent observation alternatives" — Clio plugin? UI screen-scrape? Out of scope until Clio publishes API | V>> | Documented limitation per issue #19 acceptance |

## 5. What's shipped in this PR

| Artefact | Path |
|---|---|
| Wrapper | `client/donna/integrations/clio_vincent.py` (`vincent_call`) |
| Tests | `tests/test_clio_vincent.py` (Goodhart-anchored mutation-resistant) |
| This doc | `docs/clio-vincent-wrap-feasibility.md` |
| Hypothesis | H-CLIO-3 (Vincent IDR chain integrity over 30 days) |

## 6. Falsification of this PARTIAL verdict

This verdict is wrong if any of the following hold post-merge:

- Clio dev support confirms a publicly-documented Vincent REST endpoint
  that I missed in this survey → upgrade to YES + cite the doc URL.
- Clio confirms Vincent has zero third-party callable surface (REST or
  webhook) → downgrade to NO; the wrapper is dead code; file follow-up
  to remove or repurpose.
- Clio Vincent is decommissioned / renamed / merged into a different
  product line within 90 days → re-survey + re-issue.

Track: H-CLIO-3 deadline 2026-06-23 — if no chain-integrity break by
deadline AND the env override path is exercised at least once against
a Clio response (sandbox or production), confirms the PARTIAL verdict
held. Falsified if a chain break OR the wrapper is provably unreachable.

## 7. Why ship the implementation NOW (not wait for Clio dev support)

V>>'s explicit override of Council R1 (2026-05-24):

> *"Implement Vincent. Do NOT ship a research-only artefact. The
> IDR-truth-value tradeoff is V>>'s call as principal operator."*

Rationale:

1. **IDR contract is endpoint-agnostic.** The signing/hashing/outcome
   shape is correct independent of whether Clio's path is `/vincent/...`
   or `/matters/<id>/vincent/...` — the env override absorbs the
   difference at deploy time.
2. **N=2 instances of the IDR-on-syscall pattern** (clio.py `call()`
   + clio_vincent.py `vincent_call`) → strengthens the case for
   extraction at N=3 per `rules/knowledge-maturation-functor.md`.
3. **Test surface is real today.** Mutation-resistant tests prove the
   wrapper's IDR semantics hold regardless of the HTTP endpoint.
4. **Anti-pause discipline** (`rules/rsi-loop-no-yield.md`): closing
   issue #19 with research-only is a yield disguised as completion.
   V>> wants forward motion + a falsifiable claim, not a deferral.

Council R1 (Devil's veto) raised the concern that we'd ship "IDRs for
a function that never produces a real invocation". V>> overruled:
DONNA's value-prop is the *signed audit chain*, and a chain entry that
says "Vincent was invoked at /vincent/invocations, status 404,
outcome=failure" is **still a true chain entry** — it records what
DONNA attempted. The forensic value isn't diminished by Clio's lack of
a published endpoint; it's strengthened because the chain captures the
attempt itself.

This document is the falsifiability anchor. If post-merge verification
returns NO, the wrapper is removed in a follow-up PR with a one-line
revert; the IDR emission contract migrates to whatever shape Clio
actually exposes (webhook listener, etc).

---

*Frozen at write-time. Verified-canonical: `clio_vincent.py` shipped
at this PR's HEAD; env override `CLIO_VINCENT_PATH` is the single
adjustment surface for endpoint discovery.*
