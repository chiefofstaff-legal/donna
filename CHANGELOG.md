# Changelog

All notable changes to DONNA are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Ed25519 asymmetric IDR signing** (PR #53) — `bin/notarise`, `web/lib/idr.js`,
  and `mcp-servers/donna/src/idr.ts` all gained an `ed25519` signing scheme
  alongside the existing `hmac-sha256`. Ed25519 signs with a private key and
  verifies with a published public key, so a third party can confirm a record
  without holding anything that could forge one — HMAC, by contrast, is
  server-forgeable because verifier and signer share one secret. The canonical
  payload is byte-for-byte identical across both schemes and all three languages
  (`scheme` is excluded from the signed bytes), so a JS- or Python-signed
  Ed25519 chain cross-verifies in the other. Keys: `DONNA_NOTARISE_ED25519_PRIVKEY`
  (32-byte seed hex) to sign, `DONNA_NOTARISE_ED25519_PUBKEY` to verify;
  `bin/notarise pubkey` prints the public key.
- **Public widget now signs with Ed25519** — `web/api/widget-notarise.js` switched
  the free.donnaoss.com widget from HMAC-SHA256 to Ed25519 (the most-visible IDR
  artefact was showcasing its weakest, server-forgeable rung). `web/api/widget-verify.js`
  verifies stored chains against the public key; the notarise endpoint persists
  every signed field (`decision_id`, `confidence`, `metadata`, `scheme`) so the
  session-verify reconstruction reproduces the signed payload exactly. New
  `web/api/widget-pubkey.js` publishes the live public key (only the public half
  is ever emitted), and `web/widget.html` displays it so visitors verify against a
  key they can independently check. Endpoints fail loud (503) when the key is
  unconfigured — never a silent HMAC downgrade.
- **`web/lib/idr.js` Ed25519 sign fix** — removed a dead `createPrivateKey` call
  on the raw 32-byte seed that threw `asn1 ... header too long` before the correct
  PKCS#8-wrapped key was built, so the JS Ed25519 sign path never completed. Now
  proven against `bin/notarise` (a JS-signed Ed25519 chain verifies in Python).
- **`web/tests/widget-notarise-ed25519.test.js`** — end-to-end Ed25519 round-trip
  for the widget (notarise → store → verify), plus mutation anchors: a tampered
  stored entry must fail, the signature must be 128-hex Ed25519 (not 64-hex HMAC),
  notarise must 503 without the private seed (no silent HMAC fallback), and
  widget-pubkey must never leak the private seed.
- **`donna/integrations/clio.py`** — OAuth2 authorize leg (D5):
  `oauth_authorize_url()` derives the user-agent `/oauth/authorize` endpoint
  from `CLIO_API_BASE` (EU/US/non-standard bases, mirroring the token-URL
  derivation via a shared `_oauth_endpoint_url` helper), and
  `build_authorize_redirect(client_id=, redirect_uri=, state=)` composes the
  full authorization_code redirect URL (`response_type=code` added; all
  caller params passed through verbatim, urlencoded). Pure string
  construction — no network I/O, no secret reads. Consumers mint their own
  CSRF `state` and exchange the returned code via `grant_oauth_tokens`.
- **`tests/test_clio_authorize.py`** — mutation-anchored tests for the
  authorize leg: exact-URL region derivations, param completeness,
  verbatim state passthrough, keyword-only signature, export surface.

### Changed

- **`client/tests/test_audio.py` + `test_voice_pipeline.py`** — guard the `numpy`
  import with `pytest.importorskip("numpy")` so a contributor's bare env skips the
  two audio-client test files instead of aborting collection of the WHOLE suite
  (817 tests). CI installs `numpy` (declared in `client/pyproject.toml`) and runs
  these files in full, so no coverage is lost there.
- **Package version `0.1.0` → `0.2.0`** — consumers pinning donna via a git
  URL upgrade on a plain `pip install -r requirements.txt` (name+version
  change defeats pip's installed-requirement short-circuit, which kept
  stale shas installed under `0.1.0`).

- **`donna/integrations/clio.py`** — Clio integration adapter scaffold (issue
  #18). Per-tenant OAuth2 via macOS Keychain (`grip-clio-<tenant_id>`),
  ~250 LOC of pure-stdlib HTTP, per-mutation IDR emission via a
  dependency-inverted `DecisionLoggerProtocol`. Pure-read GETs do not chain;
  POST/PATCH/PUT/DELETE emit exactly one outcome IDR with `context.outcome`
  ∈ {success, failure, transport_failure, not_configured}. Fail-CLOSED when
  Keychain entry is absent (degraded-mode IDR + error result, never silent
  mock success). Council-ratified design — see project memory
  `project_donna_clio_adapter_council_synthesis_2026-05-20.md`.
- **`donna/integrations/__init__.py`** — public surface for the integrations
  sub-package: `ClioConfig`, `ClioResult`, `DecisionLoggerProtocol`, `call`,
  `load_config`.
- **`tests/integrations/test_clio.py`** — 17 Goodhart-resistant tests
  anchoring: per-mutation single-IDR emission, GET emits zero IDRs,
  fail-CLOSED on degraded mode, dependency-inverted logger contract,
  retry loop for transient 5xx, parent_decision_id chain-forest linkage,
  outcome-label partitioning across status codes.

### Tightened (on top of council outline)

- IDR `context.parent_decision_id` — when the orchestrator passes the
  routing decision id through, the Clio mutation IDR explicitly links back.
  Chain replay can reconstruct the routing → mutation forest even though
  each entry is its own `log_decision` call. (Round-3 design tightening
  documented in project memory `feedback_two_linked_idrs_per_orchestrated_task.md`.)

### Out of scope (tracked separately)

- OAuth refresh-token flow + envelope encryption are follow-up commits
  within #18 (acceptance sub-tasks, not v1 blockers per council).
- Bidirectional `donna/export.py` (import + sync) is a separate PR.
- Real Clio sandbox round-trip ships once V>> provisions a dev access
  token in macOS Keychain entry `grip-clio-dev`.

## [0.9.0] — 2026-05-09

Public-launch surface: DONNA backronym, Munir framing, IDR notariser, roadmap, OSS hygiene.

### Added

- **`bin/notarise`** — stdlib Python HMAC-SHA256 IDR (Intent Decision Record)
  signer + verifier. Subcommands: `sign`, `verify`, `demo`. ~200 LOC, no
  dependencies. Verifies `PROBAT.md` chains end-to-end.
- **`PROBAT.md`** — self-notarising chain demo with three seed IDRs. Public
  signing key `donna-public-demo-key-2026-05-08`. Verifiable in 60s with
  `bin/notarise verify --chain PROBAT.md`.
- **`ROADMAP.md`** — 5-waypoint journey vector: voice intent → skill
  orchestration → IDR audit chain → AI-agent PR review → full Delegation
  Orchestration Layer. Published before launch on the principle that
  *"a clear starting point and a clear direction makes being incomplete
  acceptable"* (Craig Miller, 2026-05-08).
- **`CONTRIBUTING.md`**, **`CODE_OF_CONDUCT.md`**, **`SECURITY.md`** — OSS
  hygiene baseline. AGPL-3.0 contribution model, Contributor Covenant 2.1,
  responsible-disclosure protocol.

### Changed

- **`README.md`** rewritten with the DONNA backronym table
  (D-O-N-N-A → Decision-Oriented Network Notarisation for Attorneys),
  the *Munir v SSHD* [2026] UKUT 81 paragraph, and the architectural
  positioning *"open source delegation orchestration for legal practice"*
  superseding the prior *"voice-first time tracker"* framing. The voice
  surface and time-tracking remain — they are now part of a larger
  delegation-orchestration story, not the headline.

## [0.8.0] — 2026-05-05

Claude Desktop drop-in. MCP server + Skill + README inversion.

### Refactoring (5-wave autonomous DRY/KISS/CC sweep across `client/`)

- **Wave 1:** `main.py` arg parser rewritten with `argparse.add_mutually_exclusive_group()`.
  Eliminates the multi-line ternary at the old line 197 and the repetitive
  `mode = "--flag" in args` pattern. Side effect: passing two mode flags
  (e.g. `--history --export-today`) now errors cleanly instead of silently
  dispatching to whichever branch ran first.
- **Wave 2:** `_serialise` and `_format` in `main.py` use module-top dispatch
  dicts keyed on type. `ClarifyRequest` gains `to_dict()` for symmetric
  serialisation across all three result types.
- **Wave 3:** `donna/store.py` introduces `_StoreSpec` + generic `_BaseStore[T]`.
  `add()`, `list()`, `_row_to_model()` are inherited from the base; subclasses
  set `_SPEC` only. Removes parallel duplication across the two stores.
- **Wave 4:** `donna/router.py` extracts `_make_clarify` helper and uses
  `dataclasses.asdict(parsed)` to spread `ParsedDelegation` into `Task()`.
  `_handle_delegation` shrinks from 33 lines to 12.
- **Wave 5:** `voice_pipeline.run_vad` simplified — the previous
  `threading.Event` + daemon-thread sleep was functionally equivalent to
  `time.sleep()` since nothing else could ever set the event. `import threading`
  dropped (no other usage in the module).
- **Wave 6b1:** `confirmation._duration_phrase` extracts a `_plural(n, unit)`
  helper. Drops cyclomatic complexity from 9 to 4.

### Added

- **MCP server** (`client/donna/mcp_server.py`, 255 lines) — Claude Desktop
  drop-in.
- **DONNA skill** (`donna-skill/SKILL.md`, also `skills/donna/`) — analyse /
  draft / review / export stub handlers.
- **TypeScript MCP server** (`mcp-servers/donna/`, ported from
  CodeTonight-SA/donna-legal per PR #10) — node implementation alongside
  the Python one.

### Tests

- 31 new tests added (`tests/test_main_dispatch.py`,
  `tests/test_model_sync_invariant.py`):
  - Direct dispatch coverage for `_serialise` / `_format` / `ClarifyRequest.to_dict`.
  - Argparse coverage for mutual exclusion, defaults, `--no-tts`, `--format`.
  - Sync invariants pinning `ParsedDelegation ⊆ Task` and `_StoreSpec.columns ⊆
    model fields` — catches future drift that would crash refactored code.
- Total: 162 → 193 tests. Suite runtime: 1.47s → 0.55s.

### Docs

- README roadmap refreshed: v0.3-v0.7 marked shipped (was stuck at v0.2).
- Root `CLAUDE.md` repo layout updated to include `export.py`, `webhook.py`,
  `speaker.py`, `confirmation.py`. Stale branch reference replaced. Spurious
  `DONNA_HOURLY_RATE` row removed from config table; replaced with the actual
  `DONNA_WEBHOOK_URL`.
- `client/CLAUDE.md` package table notes `store.py` uses the generic
  `_BaseStore[T]` pattern.

## [0.7.0] — 2025

CLI history + export.

- `python main.py --history` — formatted table of today's time entries with
  totals.
- `python main.py --export-today` — CSV (default) or JSON (`--format json`)
  to stdout.

## [0.6.0] — 2025

Webhook delivery.

- `donna/webhook.py` — POST every intent to `DONNA_WEBHOOK_URL` if set.
- Pure stdlib (`urllib.request`); no extra dependency.

## [0.5.0] — 2025

Session summary TTS.

- Voice mode speaks `daily_summary()` on Ctrl-C / EOF exit.
- `TimeEntryStore.daily_summary()` returns a human-readable string ("You've
  logged N hours across M matters today").

## [0.4.0] — 2025

SQLite query + Clio/CSV export.

- `TimeEntryStore.query(date_from, date_to)` — date-range filter.
- `donna/export.py` — Clio-compatible JSON + CSV exporters.

## [0.3.0] — 2025

DONNA's confirmation voice.

- `donna/speaker.py` — TTS playback via OpenAI `audio.speech.create`.
- `ConfirmationFormatter` — natural-language readback strings.
- `--no-tts` flag to disable spoken confirmations.

## [0.2.0] — 2025

Voice pipeline.

- `donna/audio.py` — microphone capture (sounddevice).
- `donna/vad.py` — voice activity detection (webrtcvad).
- `donna/transcriber.py` — Whisper API (default) and local backend.
- `donna/voice_pipeline.py` — end-to-end orchestration.
- `python main.py --voice` — record an utterance, transcribe, route.

## [0.1.0] — 2025

Text-mode pipeline.

- REPL: type a time entry or delegation, see the parsed result.
- `donna/extractor.py` — LLM intent extraction (OpenAI-compatible chat).
- `donna/router.py` — heuristic intent classifier + routing.
- `donna/store.py` — SQLite persistence for time entries and tasks.
- `donna/models.py` — pure dataclasses for the domain types.
- `python main.py --pipe` — JSON streaming mode for scripting.
