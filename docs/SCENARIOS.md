# Scenarios — what you can build with DONNA

This runbook walks through the five scenarios DONNA supports today, each as a
recipe a downloader can run by cloning the repo and following along. Every
scenario produces a **verifiable IDR** (Intent Decision Record) — the
tamper-evident receipt that is DONNA's defining primitive.

If you want to skip the prose, the **TL;DR** at the bottom of each section is
copy-pasteable.

---

## Prerequisites (once)

```bash
# 1. Clone
git clone https://github.com/chiefofstaff-legal/donna.git
cd donna

# 2. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Set the audit chain key (HMAC-SHA256 — public demo key for OSS)
export DONNA_NOTARISE_KEY="donna-public-demo-key-2026-05-08"

# 4. Sanity-check the audit chain
bin/notarise verify --chain PROBAT.md
# → should print: OK: 3 record(s) verified
```

Pick **one** AI provider for the scenarios that need a model. DONNA is
provider-agnostic — Anthropic, Gemini, OpenAI, or any OpenAI-compatible
endpoint (Groq, DeepSeek, local Llama):

```bash
# Anthropic (default)
export ANTHROPIC_API_KEY=sk-ant-…

# OR OpenAI / OpenAI-compatible
export OPENAI_API_KEY=sk-…
export OPENAI_BASE_URL=https://api.openai.com/v1   # or your provider's base

# OR Gemini
export GEMINI_API_KEY=…
```

That's the once-only setup. Now pick a scenario.

---

## Scenario 1 — Voice notes → action

**Premise.** The lawyer speaks one sentence describing what needs to happen.
DONNA captures the intent, routes the work to the right destination (a
team member, an AI agent, or a note-to-self), and emits an IDR proving the
intent was recorded and dispatched.

**What you need.** Microphone access; a transcription endpoint (any
Whisper-compatible service, OR the local `macos_recorder` script bundled
in `examples/voice/`).

**Recipe.**

```bash
# Record one voice note (default 15s; press q to stop early on macOS)
python3 examples/voice/record_intent.py --out my-intent.wav

# Transcribe + route
python3 examples/voice/route_intent.py \
    --audio my-intent.wav \
    --provider anthropic \
    --emit-idr

# Output:
#   Transcript:      "Ask Sarah to chase the Arnold response by Friday."
#   Routed to:       team_member (sarah@example.com)
#   IDR signature:   3f8a1b2c…
#   IDR chain head:  PROBAT.md (entry 4)
```

**What you get.** An IDR appended to `PROBAT.md` (or your custom chain file)
that records the spoken intent, the transcription model used, the routing
decision, and the chain-link hash. Anyone with the chain can verify it
end-to-end.

**Falsification.** If the IDR signature does not verify, or the chain links
break under `bin/notarise verify`, the scenario has failed. The audit chain
is the source of truth.

**TL;DR.**

```bash
python3 examples/voice/record_intent.py --out i.wav && \
python3 examples/voice/route_intent.py --audio i.wav --emit-idr
```

---

## Scenario 2 — Time entry from voice

**Premise.** "I spent 45 minutes on the Smith matter reviewing discovery."
That sentence becomes a structured time-entry record signed with an IDR.

**What you need.** Same as Scenario 1, plus the `examples/time-entry/`
adapter (ships with the repo).

**Recipe.**

```bash
python3 examples/time-entry/voice_to_entry.py \
    --provider anthropic \
    --matter-list examples/time-entry/sample-matters.json \
    --emit-idr
# Speak when prompted; press q when done.

# Output:
#   Matter:        Smith v. Jones (matter-id: SJ-2024-0341)
#   Duration:      45 minutes
#   Activity:      Document review (discovery)
#   Date:          2026-05-09
#   IDR signature: 7c4d1f8a…
#   Saved to:      time-entries/2026-05-09.jsonl
```

**What works by clone.** Voice → structured time-entry record → IDR.
Sample matter list is included; you can swap it for your own JSON.

**What requires a paid engagement.** Direct push to a billing system
(Aderant, Elite, ProLaw, internal billers). The OSS surface emits the
record locally; the production deployment has the wiring to your billing
backend.

**Falsification.** The structured entry must round-trip through the IDR
verifier. If `bin/notarise verify --chain time-entries/2026-05-09.jsonl`
fails, the scenario has failed.

---

## Scenario 3 — Document ingestion

**Premise.** Drop a PDF, DOCX, or text file into DONNA; get it parsed,
chunked, embedded, and queryable. Each ingestion emits an IDR — so the
senior partner can verify which document the junior asked about, when,
and what the system answered.

**What you need.** The `examples/doc-ingest/` recipe; either a local
embedding model (sentence-transformers ships in `requirements-extra.txt`)
or an API-based one.

**Recipe.**

```bash
# Ingest one document
python3 examples/doc-ingest/ingest.py \
    --file examples/doc-ingest/sample-contract.pdf \
    --emit-idr

# Output:
#   Document:    sample-contract.pdf (43 pages)
#   Chunks:      127
#   Embeddings:  stored in examples/doc-ingest/index.db
#   IDR:         1a2b3c4d…

# Query
python3 examples/doc-ingest/query.py \
    --question "what is the termination clause?" \
    --emit-idr

# Output:
#   Answer:    "The agreement may be terminated by either party with
#               30 days written notice (clause 14.2)."
#   Sources:   sample-contract.pdf, page 31, chunk 89
#   IDR:       4e5f6a7b…
```

**What works by clone.** Local ingestion of PDFs, DOCX, plain text;
local SQLite-backed embedding store; IDR-stamped queries.

**What's on the demo site.** The same flow, with sample documents already
loaded. Visitors can upload a file and ask a question — the IDR is real.

**What requires a paid engagement.** Production-grade DMS connectors
(SharePoint, NetDocuments, iManage), enterprise embedding endpoints
(EU-resident inference, Azure OpenAI, etc.), and the senior-review
console for partners to inspect query trails across the team.

**Falsification.** The query result MUST cite specific chunk-IDs and
the IDR MUST verify against the chain.

---

## Scenario 4 — Matter summaries

**Premise.** Point DONNA at a matter (collection of documents + events
+ communications); get a structured summary, signed with an IDR that
records *which* sources were consulted and *which* model produced the
summary.

**What you need.** A folder of documents representing one matter; the
`examples/matter-summary/` recipe.

**Recipe.**

```bash
# Sample matter ships with the repo (synthetic — contract dispute)
python3 examples/matter-summary/summarise.py \
    --matter examples/matter-summary/sample-matter/ \
    --provider anthropic \
    --emit-idr

# Output:
#   Matter:        Sample contract dispute (synthetic)
#   Sources:       12 documents, 3 emails, 2 attendance notes
#   Summary:       "The dispute centres on clause 14.2 of the
#                   2024-01-15 services agreement…"
#   Key dates:     [2024-01-15, 2024-09-04, 2024-12-20, 2025-03-11]
#   IDR:           9b8c7d6e…
```

**What works by clone.** Local matter summarisation with IDR provenance.
Sample matter included.

**What's on the demo site.** Pre-loaded sample matters; visitors can
read the summaries and verify the IDRs.

**What requires a paid engagement.** Live-matter integration (matter feed
from a practice management system), real-time summary regeneration when
new documents land, and the senior-partner review console.

---

## Scenario 5 — IDR audit chain

**Premise.** Every DONNA scenario emits an IDR. The chain is the family
of these records laid end-to-end, tamper-evident by construction. This
scenario is the audit primitive itself: how to verify a chain, how to
detect tampering, how to export a chain for regulator review.

**What you need.** Just `bin/notarise` (ships in the repo).

**Recipe.**

```bash
# Verify the bootstrap chain
bin/notarise verify --chain PROBAT.md
# → OK: 3 record(s) verified

# Add a manual IDR
bin/notarise sign \
    --chain PROBAT.md \
    --intent "Reviewed Smith disclosure docs (4 files)" \
    --actor partner@example.com

# Verify again — chain extends to 4 records
bin/notarise verify --chain PROBAT.md
# → OK: 4 record(s) verified

# Tamper with one record
sed -i.bak 's/laurie/somebody-else/' PROBAT.md

# Verify — should fail
bin/notarise verify --chain PROBAT.md
# → FAIL at record 4: signature mismatch
```

**What works by clone.** Full audit-chain primitive; HMAC-SHA256
signatures; stdlib-only verifier; tamper detection demonstrated above.

**What's on the demo site.** Live chain visualiser — paste in any
PROBAT.md content and see the chain rendered with verifiable signatures.

**What requires a paid engagement.** The senior-review console (a
multi-user web UI showing every junior's IDR trail with filtering,
search, sign-off workflows), regulator-ready export bundles
(PDF + CSV + cryptographic proof artefact), and the keyed-chain
deployment (your firm's HMAC key, not the OSS demo key).

---

## Scenario 6 — Sign with receipt (DocuSeal-compatible)

**Premise.** DONNA emits a tamper-evident IDR every time a delegated
decision happens — *including* sending a document for signature.
DocuSeal-compatibility means a single signed envelope carries both
the verifiable cryptographic signature *and* the IDR chain, so a
senior partner can check origin (DONNA IDR) **and** authenticity
(DocuSeal signature) from the same artefact.

**What you need.** A DocuSeal account (SaaS at `api.docuseal.com`,
EU at `api.docuseal.eu`, or self-hosted) and the API key. Store it
in the macOS keychain entry `grip-docuseal` or pass `base_url=` /
set `DOCUSEAL_BASE_URL` for self-hosted endpoints.

**Recipe.**

```bash
# Set the DocuSeal API key (one-time)
security add-generic-password -s grip-docuseal -a $USER \
    -w "$YOUR_DOCUSEAL_API_KEY"

# Sign a document with IDR receipt
python3 -m donna_skill.handlers.sign --json '{
    "file_path": "examples/contracts/services-agreement.pdf",
    "signers": [
        {"email": "lawyer@firm.example", "name": "Senior Counsel"},
        {"email": "client@example.com",  "name": "Acme Corp"}
    ],
    "emit_idr": true
}'

# Output:
#   submission_id:   12345
#   template_id:     7890
#   signing_urls:
#     Senior Counsel: https://docuseal.com/s/dsEeWrhRD8yDXT
#     Acme Corp:      https://docuseal.com/s/wQrTyUiOpAsDfG
#   IDR signature:   3c8e2a1d… (intent: signing_dispatched)
#   Chain head:      PROBAT.md (entry 7)
```

**Supported input formats.** DONNA's file-type adapter accepts ten
input formats and converts to a DocuSeal-acceptable upload:

| Input | Adapter | DocuSeal endpoint |
|-------|---------|-------------------|
| PDF | passthrough | `/templates/pdf` |
| DOCX | passthrough | `/templates/docx` |
| DOC | libreoffice → DOCX | `/templates/docx` |
| RTF | libreoffice → DOCX | `/templates/docx` |
| ODT | libreoffice → DOCX | `/templates/docx` |
| HTML | passthrough | `/templates/html` |
| Markdown | stdlib markdown → HTML | `/templates/html` |
| PNG | PIL → single-page PDF | `/templates/pdf` |
| JPG | PIL → single-page PDF | `/templates/pdf` |
| TXT | reportlab/stdlib → PDF | `/templates/pdf` |

**Webhook → IDR.** When DocuSeal sends a webhook back (`submitter.opened`,
`submitter.completed`, `submission.completed`, etc.), DONNA's webhook
handler converts the event to an IDR record and appends it to the chain.
This means the chain captures the *full lifecycle* — dispatch, every
opening, every signature, every decline — not just the dispatch.

```bash
# Verify the chain after signing completes
bin/notarise verify --chain PROBAT.md
# → OK: 9 record(s) verified

# Check what each record represents
bin/notarise inspect --chain PROBAT.md
# → 7  signing_dispatched         (submission #12345 dispatched)
#   8  signing_link_opened        (Acme Corp opened the link)
#   9  signature_recorded         (Acme Corp signed)
```

**What works by clone.** Full DocuSeal-compatibility surface: shim
to the DocuSeal API, file-type adapter for ten formats, webhook
handler converting events to IDR records, end-to-end skill handler.
Your DocuSeal account + DONNA's IDR chain on your laptop.

**What's on the demo site.** A pre-recorded walkthrough showing the
flow end-to-end (signing dispatch → opening → signature → chain
verification). The IDR chain produced is real and verifiable with
`bin/notarise verify` exactly like the bootstrap chain.

**What requires a paid engagement.** Multi-tenant DocuSeal hosting,
custom webhook routing, DocuSeal-EU residency wiring for GDPR,
template library bootstrapping (firm's standard agreements
pre-loaded as DocuSeal templates), and the senior-review console
showing both the DocuSeal audit log *and* the DONNA IDR chain
side-by-side.

**Falsification.** Hypothesis H-DOCUSEAL-1: *"an IDR receipt embedded
in a DocuSeal-signed envelope verifies independently in both tools."*
Falsified if DocuSeal signature passes but IDR chain breaks (or vice
versa) on the same artefact. The end-to-end test in
`tests/test_docuseal_e2e.py` exercises this binding under simulated
DocuSeal events.

**TL;DR.**

```bash
python3 -m donna_skill.handlers.sign --json '{
  "file_path": "doc.pdf",
  "signers": [{"email": "x@y.com", "name": "X"}],
  "emit_idr": true
}'
```

---

## What's next

- **Voice + IDR end-to-end demo:** see [`docs/install.md`](install.md).
- **Provider portability:** any OpenAI-compatible endpoint works. See
  the `--provider` and `--base-url` flags.
- **Custom scenarios:** the `examples/` directory is the template — copy
  any scenario, adapt the prompt + the IDR emission call, and you have
  a new recipe.

If a scenario fails locally and you cannot reproduce, open an issue with
the IDR signature output. The chain is the source of truth — we will
follow the receipts, not the description.

---

## Scope at a glance

| Capability                       | Clone the repo            | Public demo site         | Paid engagement                |
|----------------------------------|---------------------------|--------------------------|--------------------------------|
| Voice notes → action             | Runs locally              | Walkthrough video        | Production wiring              |
| Time entry from voice            | Runs locally              | Walkthrough video        | Billing-system bridge          |
| Document ingestion               | CLI + sample documents    | Upload + query           | SharePoint / DMS connectors    |
| Matter summaries                 | Runs locally              | Sample matters           | Live matter feed               |
| IDR audit chain                  | Verify with stdlib        | Open + verify            | Senior-review console          |
| Sign with receipt (DocuSeal)     | 10 input formats          | Walkthrough + chain      | Multi-tenant + EU residency    |
| Provider portability             | Any OpenAI-compatible     | N/A                      | EU-resident model hosting      |
| Senior-review tooling            | CLI verifier              | Read-only view           | Full multi-user console        |
| Workflow integrations            | Not bundled               | Not bundled              | SharePoint, Teams, etc.        |

---

*If something on this page doesn't run, the failing IDR is the bug
report. Send the chain output, not the screenshot.*
