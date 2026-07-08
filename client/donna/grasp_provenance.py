# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024 chiefofstaff-legal contributors
"""Fail-open bridge to the optional ``grasp-provenance`` package.

When ``grasp-provenance`` is not installed every public function returns a
sentinel dict ``{"ok": False, "reason": "grasp-provenance not installed"}``
and **never raises** into the caller.  Behaviour of the rest of DONNA is
byte-identical whether the package is present or absent.

Every public ``record_*`` function shares one return contract:
``{"ok": True, "idr_id": str, "content_addr": str}`` on success, or
``{"ok": False, "reason": str}`` on absence/failure.

Install (optional)::

    pip install "git+https://github.com/CodeTonight-SA/grasp"

Environment
-----------
GRASP_HOME
    Directory for GRASP state files (read by the grasp package itself at
    call time).  Defaults to ``~/.grasp/``.

PII note
--------
GRASP receives only structured decision metadata (counts, hashes, actor
labels).  Raw transcripts and personally identifiable information are
**never** forwarded to this bridge.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Optional import — fail-open
# ---------------------------------------------------------------------------

try:
    import grasp.idr as _idr
    import grasp.context_chain as _ctx
    _GRASP_AVAILABLE = True
except ImportError:
    _GRASP_AVAILABLE = False

#: Exogenous genesis anchor for a fresh DONNA decision ledger: the human
#: operator running the practice (grasp forests root only at exogenous ids).
_GENESIS_ANCHOR = "human:donna-operator"


def _absent() -> dict[str, Any]:
    """Sentinel returned when grasp is absent."""
    return {"ok": False, "reason": "grasp-provenance not installed"}


def _failed() -> dict[str, Any]:
    return {"ok": False, "reason": "grasp call failed"}


def _record(kind: str, what: str, decision: dict, belief: str | None = None) -> dict[str, Any]:
    """Shared fail-open recorder: append one signed IDR, optionally cross-link
    a belief checkpoint citing it.  Every public function routes through this
    so the fail-open contract lives in exactly one place.  Uses the real
    grasp package API: ``build_idr(prompt, fingerprint, decision,
    predecessor_idr, depth, *, kind)`` + ``append_idr`` + ``content_addr`` +
    ``context_chain.checkpoint``."""
    if not _GRASP_AVAILABLE:
        return _absent()
    try:
        from dataclasses import asdict

        chain = _idr.read_idr_chain()
        if chain:
            predecessor, depth = chain[-1].id, chain[-1].depth + 1
        else:
            predecessor, depth = _GENESIS_ANCHOR, 0
        fingerprint = hashlib.sha256(
            json.dumps(decision, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        idr = _idr.build_idr(
            prompt=what,
            fingerprint=fingerprint,
            decision=decision,
            predecessor_idr=predecessor,
            depth=depth,
            kind=kind,
        )
        _idr.append_idr(idr)
        addr = _idr.content_addr(asdict(idr))
        if belief:
            _ctx.checkpoint(next_step=None, summary=belief, records_idr=addr)
        return {"ok": True, "idr_id": idr.id, "content_addr": addr}
    except Exception:  # noqa: BLE001 — fail-open is the contract
        return _failed()


# ---------------------------------------------------------------------------
# Public API — each function is fail-open; shared return contract in the
# module docstring
# ---------------------------------------------------------------------------

def record_export_provenance(entries_idr: list[dict]) -> dict[str, Any]:
    """Record a signed decision record for a Clio export batch of anonymised
    entry metadata dicts (raw transcripts must NOT be included)."""
    return _record(
        kind="donna-export",
        what="export time entries to Clio",
        decision={"action": "donna.export", "subject": "time_entries",
                  "count": len(entries_idr), "entries": entries_idr},
    )


def record_handoff_provenance(record_dict: dict) -> dict[str, Any]:
    """Record a signed decision record for a workflow handoff (anonymised
    HandoffRecord fields, no PII), plus a belief checkpoint cross-linking it."""
    return _record(
        kind="donna-workflow-handoff",
        what="hand off a delegated workflow step",
        decision={"action": "donna.workflow.handoff",
                  "subject": "handoff_record", **record_dict},
        belief=f"workflow handoff recorded (seq={record_dict.get('seq')})",
    )


def record_doc_analysis_provenance(file_sha256: str, path_stem: str) -> dict[str, Any]:
    """Record a signed decision record for a legal document analysis; only the
    file's SHA-256 digest and filename stem are forwarded, never file bytes."""
    return _record(
        kind="donna-legal-doc-analysis",
        what=f"analyse legal document {path_stem}",
        decision={"action": "donna.legal_doc.analyse", "subject": path_stem,
                  "sha256": file_sha256},
    )
