# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024 chiefofstaff-legal contributors
"""Unit tests for donna.grasp_provenance — the fail-open GRASP bridge.

Tests cover:
- absent grasp package → sentinel dict returned, never raises
- present (fake, real-signature) grasp package → calls delegated with the
  REAL grasp API shapes, record dict returned
- chain threading: second record links the first (predecessor/depth)
- grasp exception → failed sentinel, never re-raises

The fake package enforces the real ``grasp`` signatures, so a regression to
a fabricated call shape fails these tests with TypeError.
"""

from __future__ import annotations

import pytest

import donna.grasp_provenance as _bridge


def _absent():
    return {"ok": False, "reason": "grasp-provenance not installed"}


class TestAbsentGrasp:
    """All public bridge functions return the sentinel dict when grasp is absent."""

    def setup_method(self):
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


@pytest.mark.grasp
class TestPresentGrasp:
    """Bridge delegates to the fake grasp with real API shapes."""

    def test_record_export_provenance(self, fake_grasp):
        result = _bridge.record_export_provenance([{"id": "e1", "matter": "Smith"}])
        assert result["ok"] is True
        assert result["idr_id"] == "precog-test-0001"
        assert result["content_addr"] == "sha256:addr-abc123"
        kwargs = fake_grasp["idr"].build_idr.call_args.kwargs
        assert kwargs["kind"] == "donna-export"
        assert kwargs["predecessor_idr"] == "human:donna-operator"
        assert kwargs["depth"] == 0
        assert kwargs["decision"]["count"] == 1
        fake_grasp["idr"].append_idr.assert_called_once()

    def test_record_handoff_provenance_cross_links_belief(self, fake_grasp):
        payload = {"seq": 1, "from_actor": "alice", "to_actor": "bob",
                   "record_hash": "dead", "timestamp": "2024-01-01T00:00:00+00:00"}
        result = _bridge.record_handoff_provenance(payload)
        assert result["ok"] is True
        ck = fake_grasp["ctx"].checkpoint.call_args.kwargs
        assert ck["records_idr"] == "sha256:addr-abc123"
        assert "seq=1" in ck["summary"]

    def test_record_doc_analysis_provenance(self, fake_grasp):
        result = _bridge.record_doc_analysis_provenance("sha256hex", "agreement")
        assert result["ok"] is True
        assert result["content_addr"] == "sha256:addr-abc123"
        kwargs = fake_grasp["idr"].build_idr.call_args.kwargs
        assert kwargs["decision"]["sha256"] == "sha256hex"
        # content_addr is computed over the serialised record, never a bare hash
        (arg,), _ = fake_grasp["idr"].content_addr.call_args
        assert isinstance(arg, dict) and arg["kind"] == "donna-legal-doc-analysis"

    def test_second_record_threads_the_chain(self, fake_grasp):
        first = _bridge.record_export_provenance([])
        assert first["ok"] is True
        head = fake_grasp["idr"].build_idr.side_effect(
            prompt="", fingerprint="", decision={},
            predecessor_idr="human:donna-operator", depth=0)
        fake_grasp["idr"].read_idr_chain.return_value = [head]
        second = _bridge.record_doc_analysis_provenance("beef", "brief")
        assert second["ok"] is True
        kwargs = fake_grasp["idr"].build_idr.call_args.kwargs
        assert kwargs["predecessor_idr"] == "precog-test-0001"
        assert kwargs["depth"] == 1

    def test_grasp_exception_returns_failed_sentinel(self, fake_grasp):
        """If grasp raises unexpectedly, bridge returns failed sentinel, never re-raises."""
        fake_grasp["idr"].build_idr.side_effect = RuntimeError("boom")
        result = _bridge.record_export_provenance([])
        assert result == {"ok": False, "reason": "grasp call failed"}
