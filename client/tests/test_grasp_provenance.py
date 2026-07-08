# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024 chiefofstaff-legal contributors
"""Unit tests for donna.grasp_provenance — the fail-open GRASP bridge.

Tests cover:
- absent grasp package → sentinel dict returned, never raises
- present (fake) grasp package → calls delegated, receipt returned
"""

from __future__ import annotations

import pytest

import donna.grasp_provenance as _bridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _absent():
    return {"ok": False, "reason": "grasp-provenance not installed"}


# ---------------------------------------------------------------------------
# Absent-package tests (no fake_grasp fixture — grasp NOT in sys.modules)
# ---------------------------------------------------------------------------

class TestAbsentGrasp:
    """All public bridge functions return the sentinel dict when grasp is absent."""

    def setup_method(self):
        # Ensure _GRASP_AVAILABLE is False for these tests
        self._orig = _bridge._GRASP_AVAILABLE
        _bridge._GRASP_AVAILABLE = False

    def teardown_method(self):
        _bridge._GRASP_AVAILABLE = self._orig

    def test_record_export_provenance_absent(self):
        result = _bridge.record_export_provenance([{"id": "e1", "matter": "Smith"}])
        assert result == _absent()

    def test_record_handoff_provenance_absent(self):
        result = _bridge.record_handoff_provenance({"seq": 0, "from_actor": "alice"})
        assert result == _absent()

    def test_record_doc_analysis_provenance_absent(self):
        result = _bridge.record_doc_analysis_provenance("abc123", "agreement")
        assert result == _absent()

    def test_never_raises_on_absent(self):
        """Confirm fail-open: no exception even if called with empty args."""
        assert _bridge.record_export_provenance([]).get("ok") is False
        assert _bridge.record_handoff_provenance({}).get("ok") is False
        assert _bridge.record_doc_analysis_provenance("", "").get("ok") is False


# ---------------------------------------------------------------------------
# Present (fake) grasp tests
# ---------------------------------------------------------------------------

@pytest.mark.grasp
class TestPresentGrasp:
    """Bridge delegates to fake grasp and returns ok=True receipts."""

    def test_record_export_provenance(self, fake_grasp):
        result = _bridge.record_export_provenance([{"id": "e1", "matter": "Smith"}])
        assert result["ok"] is True
        assert "idr_id" in result
        assert "receipt" in result
        fake_grasp["idr"].build_idr.assert_called_once()
        fake_grasp["prov"].record_proveit_provenance.assert_called_once()

    def test_record_handoff_provenance(self, fake_grasp):
        payload = {"seq": 1, "from_actor": "alice", "to_actor": "bob",
                   "record_hash": "dead", "timestamp": "2024-01-01T00:00:00+00:00"}
        result = _bridge.record_handoff_provenance(payload)
        assert result["ok"] is True
        fake_grasp["idr"].build_idr.assert_called_once()
        fake_grasp["ctx"].checkpoint.assert_called_once()
        fake_grasp["prov"].record_proveit_provenance.assert_called_once()

    def test_record_doc_analysis_provenance(self, fake_grasp):
        result = _bridge.record_doc_analysis_provenance("sha256hex", "agreement")
        assert result["ok"] is True
        assert result["content_addr"] == "addr-abc123"
        fake_grasp["idr"].content_addr.assert_called_once_with("sha256hex", home=_bridge._grasp_home())
        fake_grasp["idr"].build_idr.assert_called_once()

    def test_grasp_exception_returns_failed_sentinel(self, fake_grasp):
        """If grasp raises unexpectedly, bridge returns failed sentinel, never re-raises."""
        fake_grasp["idr"].build_idr.side_effect = RuntimeError("boom")
        result = _bridge.record_export_provenance([])
        assert result == {"ok": False, "reason": "grasp call failed"}
