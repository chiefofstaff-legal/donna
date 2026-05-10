---
name: donna
version: 0.1.0
commands: ["/donna analyse", "/donna draft", "/donna review", "/donna export"]
mcp_surface: donna-mcp
---

# /donna — Legal Document Skill

## When to use

- User pastes a contract clause and asks what it means, what risks it carries, or how it compares to a standard
- User needs a first draft of a specific document type (NDA, service agreement, IP assignment, settlement letter)
- User has a document and wants clause-by-clause redline comments before signing or sending
- User has completed analysis or a draft and needs it exported to PDF, DOCX, or plain markdown for handoff

Do NOT invoke for general legal questions without a document. This skill operates on documents, not abstract queries.

## Dispatch matrix

| Subcommand | Input | Handler | Output artefact |
|------------|-------|---------|-----------------|
| `/donna analyse <doc>` | Document text or file path | `handlers/analyse.py::analyse` | Structured clause report (JSON + markdown summary) |
| `/donna draft <type>` | Document type + optional context | `handlers/draft.py::draft` | Draft document text (markdown) |
| `/donna review <doc>` | Document text or file path | `handlers/review.py::review` | Redline comments list (JSON + inline annotations) |
| `/donna export <format>` | Prior analyse/draft/review output + format | `handlers/export.py::export` | File at requested format (pdf, docx, md) |

All handlers call the donna-mcp tool surface. No logic runs in-process.

## Primary actions

### analyse

**Input**: Document text (string) or file path (resolved to text before dispatch).

**Output**: `{"clauses": [...], "risks": [...], "summary": "..."}` — each clause entry names the clause, cites the specific text span, and flags risk level (low/medium/high) with a one-line rationale.

**Falsifier**: Output cites no clause text spans → handler did not read the document. Output contains only generic risk categories with no document-specific content → MCP call returned a hallucinated response.

### draft

**Input**: Document type (e.g. `nda`, `service-agreement`, `ip-assignment`) plus optional context dict (parties, jurisdiction, key terms).

**Output**: Full document text in markdown with section headers. Each substantive clause labelled with its legal purpose.

**Falsifier**: Output contains placeholder text (`[PARTY A]`, `[DATE]`) without being given party names → context was not passed to MCP. Output is fewer than 200 words for a full agreement type → MCP returned a stub, not a draft.

### review

**Input**: Document text or file path.

**Output**: `{"comments": [{"clause": "...", "text_span": "...", "issue": "...", "suggestion": "..."}]}` — each comment anchored to a specific text span with a concrete suggestion, not a generic observation.

**Falsifier**: Comments contain no specific text spans → review did not process the document. Suggestions say "consider revising" with no proposed alternative text → redline is non-actionable.

### export

**Input**: Prior action output (analyse/draft/review result dict) plus `format` string (`pdf`, `docx`, `md`).

**Output**: File path of exported document.

**Falsifier**: Returned path does not exist on disk → export failed silently. Format of file at path does not match requested format → wrong renderer was invoked.

## Falsifiers (skill level)

- Skill fires but no MCP tool call is made → handler is broken or MCP surface is unreachable
- `/donna analyse` returns output with no clause references → document was not passed through
- `/donna draft nda` produces a document with no party-binding obligations → draft is a template stub, not a usable draft
- `/donna export pdf` returns a `.md` file → export handler ignored the format argument
- Any handler raises an exception other than `NotImplementedError` before W2b wires MCP → stub was modified incorrectly
