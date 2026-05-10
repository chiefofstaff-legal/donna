<!-- Thanks for contributing to Donna. Plain language, please. Describe the change, the falsifier, and the tests. -->

## What this PR does

<!-- One or two sentences. The behaviour change, not the file list. -->

## Why now

<!-- The problem this solves, or the waypoint (W1-W5 in ROADMAP.md) it advances. -->

## Falsification anchor

<!-- What observation would prove this PR wrong? Required by ROADMAP "How we work" principle 1. -->

- This PR is wrong if: <!-- e.g. "the audit chain rejects valid IDRs at >0.1% rate" -->

## Tests

- [ ] New behaviour has tests
- [ ] Tests verify behaviour, not implementation details
- [ ] Tests can fail when the logic is wrong (Goodhart-proof)
- [ ] All existing tests still pass

## Checklist

- [ ] Plain-language commit messages, no AI attribution
- [ ] Single concern per PR (split if it touches multiple waypoints)
- [ ] PROBAT chain still verifies locally (`bin/notarise verify --chain PROBAT.md`)
- [ ] Docs updated where positioning, install, or contracts change
