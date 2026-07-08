# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024 chiefofstaff-legal contributors
"""Integration test against the REAL grasp-provenance package.

Skipped automatically when grasp is not installed (CI does not install the
optional dependency).  With ``pip install
"git+https://github.com/CodeTonight-SA/grasp"`` present, this proves the
bridge round-trips against the real engine: a record is appended to a
hermetic ``GRASP_HOME`` ledger, its chain verifies, and the belief
checkpoint cross-link lands.
"""

from __future__ import annotations

import importlib

import pytest

grasp_idr = pytest.importorskip("grasp.idr")


@pytest.mark.grasp
def test_bridge_round_trips_against_real_grasp(tmp_path, monkeypatch):
    monkeypatch.setenv("GRASP_HOME", str(tmp_path / "grasp-home"))
    monkeypatch.setenv("GRASP_SIGNING_KEY", "donna-test-signing-key")

    import donna.grasp_provenance as bridge
    importlib.reload(bridge)
    assert bridge._GRASP_AVAILABLE is True

    first = bridge.record_export_provenance([{"id": "e1", "matter": "Smith"}])
    assert first["ok"] is True, first
    assert first["content_addr"].startswith("sha256:")

    second = bridge.record_handoff_provenance(
        {"seq": 1, "from_actor": "alice", "to_actor": "bob",
         "record_hash": "beef", "timestamp": "2024-01-01T00:00:00+00:00"})
    assert second["ok"] is True, second

    chain = grasp_idr.read_idr_chain()
    assert [r.kind for r in chain] == ["donna-export", "donna-workflow-handoff"]
    assert chain[0].predecessor_idr == "human:donna-operator"
    assert chain[1].predecessor_idr == chain[0].id and chain[1].depth == 1

    from grasp.context_chain import read_context_chain, verify_context_chain
    from grasp.verdict import Verdict
    nodes = read_context_chain()
    assert any(n.decision.get("records_idr") == second["content_addr"] for n in nodes)
    assert verify_context_chain() is Verdict.VERIFIED
