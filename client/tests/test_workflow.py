"""Goodhart-resistant tests for donna.workflow.

Tamper detection tests mutate internal state directly — if verify() still
returns True after mutation, the test fails (proving the assertion is real).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from donna.workflow import HandoffRecord, Workflow


def _wf() -> Workflow:
    return Workflow(workflow_id="test-matter-001")


IDR_A = {"action": "review", "matter": "Smith v Jones", "confidence": 0.92}
IDR_B = {"action": "sign",   "matter": "Smith v Jones", "confidence": 0.98}


# ---------------------------------------------------------------------------
# 12 Goodhart-resistant test cases
# ---------------------------------------------------------------------------

def test_empty_chain_verify_true():
    assert _wf().verify() is True


def test_genesis_record_prev_hash():
    wf = _wf()
    r = wf.handoff("alice", "bob", IDR_A)
    assert r.prev_hash == "genesis"
    assert r.seq == 0


def test_sequential_handoff_links_hashes():
    wf = _wf()
    r1 = wf.handoff("alice", "bob", IDR_A)
    r2 = wf.handoff("bob", "carol", IDR_B)
    assert r2.prev_hash == r1.record_hash
    assert r2.seq == 1


def test_verify_intact_chain():
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    wf.handoff("bob", "carol", IDR_B)
    assert wf.verify() is True


def test_tamper_idr_breaks_verify():
    """Mutating a record's idr must break the hash chain."""
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    original = wf._chain[0]
    tampered = dataclasses.replace(original, idr={"action": "FORGED"})
    wf._chain[0] = tampered
    assert wf.verify() is False


def test_tamper_from_actor_breaks_verify():
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    original = wf._chain[0]
    tampered = dataclasses.replace(original, from_actor="ATTACKER")
    wf._chain[0] = tampered
    assert wf.verify() is False


def test_tamper_prev_hash_breaks_verify():
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    wf.handoff("bob", "carol", IDR_B)
    original = wf._chain[1]
    tampered = dataclasses.replace(original, prev_hash="0" * 64)
    wf._chain[1] = tampered
    assert wf.verify() is False


def test_tamper_record_hash_breaks_verify():
    """Changing record_hash without recalculating must break verify."""
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    original = wf._chain[0]
    tampered = dataclasses.replace(original, record_hash="deadbeef" * 8)
    wf._chain[0] = tampered
    assert wf.verify() is False


def test_single_record_chain_verifies():
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    assert wf.verify() is True


def test_chain_returns_copy():
    """Mutating the returned list must not affect internal state."""
    wf = _wf()
    wf.handoff("alice", "bob", IDR_A)
    copy = wf.chain()
    copy.clear()
    assert len(wf.chain()) == 1


def test_seq_is_monotonically_increasing():
    wf = _wf()
    records = [wf.handoff("a", "b", {"n": i}) for i in range(5)]
    assert [r.seq for r in records] == list(range(5))


def test_timestamp_is_iso_utc():
    wf = _wf()
    r = wf.handoff("alice", "bob", IDR_A)
    dt = datetime.fromisoformat(r.timestamp)
    assert dt.tzinfo is not None
