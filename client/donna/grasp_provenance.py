# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024 chiefofstaff-legal contributors
"""Fail-open bridge to the optional ``grasp-provenance`` package.

When ``grasp-provenance`` is not installed every public function returns a
sentinel dict ``{"ok": False, "reason": "grasp-provenance not installed"}``
and **never raises** into the caller.  Behaviour of the rest of DONNA is
byte-identical whether the package is present or absent.

Install (optional)::

    pip install "git+https://github.com/CodeTonight-SA/grasp"

Environment
-----------
GRASP_HOME
    Directory for GRASP state files.  Defaults to ``~/.grasp/``.

PII note
--------
GRASP receives only structured IDR dicts (anonymised metadata).  Raw
transcripts and personally identifiable information are **never** forwarded
to this bridge.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Optional import — fail-open
# ---------------------------------------------------------------------------

try:
    import grasp.idr as _idr
    import grasp.context_chain as _ctx
    import grasp.provenance as _prov
    _GRASP_AVAILABLE = True
except ImportError:
    _GRASP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _grasp_home() -> Path:
    return Path(os.environ.get("GRASP_HOME", str(Path.home() / ".grasp")))


def _absent() -> dict[str, Any]:
    """Sentinel returned when grasp is absent."""
    return {"ok": False, "reason": "grasp-provenance not installed"}


def _failed() -> dict[str, Any]:
    return {"ok": False, "reason": "grasp call failed"}


def _guarded(call: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    """Run ``call(home)`` fail-open: absent sentinel when the package is
    missing, failure sentinel on any exception — never raise into DONNA."""
    if not _GRASP_AVAILABLE:
        return _absent()
    try:
        return call(_grasp_home())
    except Exception:  # noqa: BLE001
        return _failed()


# ---------------------------------------------------------------------------
# Public API — each function is fail-open
# ---------------------------------------------------------------------------

def record_export_provenance(entries_idr: list[dict]) -> dict[str, Any]:
    """Record a GRASP provenance receipt for a Clio export batch.

    Args:
        entries_idr: Anonymised IDR dicts (one per time entry).
            Raw transcripts must NOT be included.

    Returns:
        ``{"ok": True, "idr_id": str, "receipt": dict}`` on success,
        or ``{"ok": False, "reason": str}`` on absence/failure.
    """
    def _call(home: Path) -> dict[str, Any]:
        idr_id = _idr.build_idr(
            action="donna.export",
            subject="time_entries",
            data={"count": len(entries_idr), "entries": entries_idr},
            home=home,
        )
        receipt = _prov.record_proveit_provenance(idr_id, home=home)
        return {"ok": True, "idr_id": idr_id, "receipt": receipt}

    return _guarded(_call)


def record_handoff_provenance(record_dict: dict) -> dict[str, Any]:
    """Record a GRASP provenance receipt for a workflow handoff record.

    Args:
        record_dict: Anonymised HandoffRecord fields (seq, from_actor,
            to_actor, record_hash, timestamp).  No PII.

    Returns:
        ``{"ok": True, "idr_id": str, "receipt": dict}`` on success,
        or ``{"ok": False, "reason": str}`` on absence/failure.
    """
    def _call(home: Path) -> dict[str, Any]:
        idr_id = _idr.build_idr(
            action="donna.workflow.handoff",
            subject="handoff_record",
            data=record_dict,
            home=home,
        )
        _ctx.checkpoint(idr_id, home=home)
        receipt = _prov.record_proveit_provenance(idr_id, home=home)
        return {"ok": True, "idr_id": idr_id, "receipt": receipt}

    return _guarded(_call)


def record_doc_analysis_provenance(file_sha256: str, path_stem: str) -> dict[str, Any]:
    """Record a GRASP provenance receipt for a legal document analysis.

    Args:
        file_sha256: SHA-256 hex digest of the analysed file.
            No file bytes are forwarded to GRASP.
        path_stem: Filename stem (no directory, no extension) for labelling.

    Returns:
        ``{"ok": True, "idr_id": str, "content_addr": str}`` on success,
        or ``{"ok": False, "reason": str}`` on absence/failure.
    """
    def _call(home: Path) -> dict[str, Any]:
        content_addr = _idr.content_addr(file_sha256, home=home)
        idr_id = _idr.build_idr(
            action="donna.legal_doc.analyse",
            subject=path_stem,
            data={"sha256": file_sha256, "content_addr": content_addr},
            home=home,
        )
        return {"ok": True, "idr_id": idr_id, "content_addr": content_addr}

    return _guarded(_call)
