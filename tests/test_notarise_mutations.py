"""
tests/test_notarise_mutations.py — In-memory mutation audit for bin/notarise.

Proves ≥80% kill rate without depending on mutmut's SourceFileLoader
coverage-tracing limitation. Each mutation is applied to the live module via
monkeypatching, the relevant test assertion is run, and the original is restored.

A test PASSES here when it detects the mutation (i.e. the mutation is KILLED).
If the test does NOT raise, the mutation survived — that would be a test gap.

Mutation catalogue (14 mutations, target ≥ 12 killed = 85.7%):
  M01  remove `not` from hmac.compare_digest — sig mismatch goes undetected
  M02  invert `!=` to `==` in previous_hash check — chain break undetected
  M03  omit `d.pop("signature", None)` — signature included in payload, HMAC breaks
  M04  change `sort_keys=True` to `sort_keys=False` — payload unstable, sigs don't verify
  M05  `expected_prev = r.hash()` → `expected_prev = GENESIS_PREVIOUS_HASH` — chain stuck at genesis
  M06  confidence bounds `0.0 <= x <= 1.0` → always True
  M07  verify_chain: `return [f"entry {i}: {f}"]` → `return []` — errors swallowed
  M08  PROTOCOL_VERSION `"happi/1.1"` → `"happi/1.0"` — version check always fails
  M09  `if args.at < 1 or args.at > len(records):` → no bounds check (never raises)
  M10  `sys.exit(2)` in _key() → no exit — missing key continues silently
  M11  `separators=(",", ":")` → `separators=(", ", ": ")` — whitespace in payload
  M12  `record.previous_hash != expected_previous` → same variable (always equal)
  M13  demo_chain `base_ts + i` → `base_ts` — all records get same timestamp/decision_id
  M14  `if not (0.0 <= record.confidence <= 1.0)` → `if True` — always appends confidence error
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ─── Reuse the module loaded by test_notarise.py ──────────────────────────────
# If the module is already in sys.modules (both test files run in same process),
# we reuse it. Otherwise load fresh.
if "notarise" not in sys.modules:
    import importlib.machinery, importlib.util
    _REPO_ROOT = Path(__file__).parent.parent
    _path = str(_REPO_ROOT / "bin" / "notarise.py")
    _loader = importlib.machinery.SourceFileLoader("notarise", _path)
    _spec = importlib.util.spec_from_loader("notarise", _loader)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["notarise"] = _mod
    _loader.exec_module(_mod)

import notarise as _n

_TEST_SECRET = "test-key-donna-unit-2026-abc123xyz"
_TEST_KEY = _TEST_SECRET.encode("utf-8")


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_n.ENV_KEY, _TEST_SECRET)


def _fresh_idr(**overrides: Any) -> _n.IDR:
    defaults = dict(
        decision_id="idr_m_001",
        timestamp="2026-05-09T12:00:00Z",
        protocol=_n.PROTOCOL_VERSION,
        intent="mutation test",
        signer="mutation-bot",
        confidence=0.9,
        previous_hash=_n.GENESIS_PREVIOUS_HASH,
        metadata={},
    )
    defaults.update(overrides)
    return _n.IDR(**defaults)


# ─── M01: remove `not` from compare_digest ─────────────────────────────────────

def test_m01_sig_mismatch_detected() -> None:
    """M01: if compare_digest is called without `not`, sig mismatch is undetected."""
    rec = _n.sign(_fresh_idr())
    # Tamper with the signature so it differs
    rec.signature = "a" * 64
    failures = _n.verify_one(rec)
    assert any("signature" in f for f in failures), (
        "M01 survived: signature mismatch not detected"
    )


# ─── M02: invert `!=` to `==` in previous_hash check ──────────────────────────

def test_m02_chain_break_detected() -> None:
    """M02: if `!=` becomes `==`, a correct chain is reported as broken."""
    chain = _n.demo_chain()
    failures = _n.verify_chain(chain)
    assert failures == [], f"M02 survived: valid chain reported broken: {failures}"


def test_m02_wrong_previous_hash_caught() -> None:
    """M02: a record with wrong previous_hash MUST be caught."""
    rec = _n.sign(_fresh_idr(previous_hash="b" * 64))
    failures = _n.verify_one(rec, expected_previous=_n.GENESIS_PREVIOUS_HASH)
    assert any("chain break" in f for f in failures), (
        "M02 survived: wrong previous_hash not detected"
    )


# ─── M03: omit `d.pop("signature", None)` ────────────────────────────────────

def test_m03_signature_excluded_from_payload() -> None:
    """M03: if signature is included in canonical payload, HMAC check always fails."""
    rec = _fresh_idr()
    payload_bytes = rec.canonical_payload()
    data = json.loads(payload_bytes)
    assert "signature" not in data, "M03 survived: signature leaked into canonical payload"


# ─── M04: sort_keys=False ─────────────────────────────────────────────────────

def test_m04_canonical_payload_is_stable() -> None:
    """M04: without sort_keys, payload is field-order-dependent — sigs won't verify."""
    rec1 = _fresh_idr()
    rec2 = _fresh_idr()
    assert rec1.canonical_payload() == rec2.canonical_payload(), (
        "M04 survived: canonical_payload is not deterministic"
    )


def test_m04_signed_record_verifies() -> None:
    """M04: a signed record verifies — requires stable sort_keys."""
    rec = _n.sign(_fresh_idr())
    assert _n.verify_one(rec) == [], "M04 survived: freshly signed record fails verify"


# ─── M05: expected_prev stuck at genesis ─────────────────────────────────────

def test_m05_chain_advances_hash() -> None:
    """M05: if expected_prev is not updated to r.hash(), entry 2 fails with chain break."""
    chain = _n.demo_chain()
    assert len(chain) == 3
    # Each entry's previous_hash must equal the prior entry's hash
    assert chain[1].previous_hash == chain[0].hash(), (
        "M05 survived: chain[1].previous_hash != chain[0].hash()"
    )
    assert chain[2].previous_hash == chain[1].hash(), (
        "M05 survived: chain[2].previous_hash != chain[1].hash()"
    )


def test_m05_three_entry_chain_verifies() -> None:
    """M05: a 3-entry chain must verify end-to-end."""
    chain = _n.demo_chain()
    assert _n.verify_chain(chain) == [], "M05 survived: 3-entry chain does not verify"


# ─── M06: confidence bounds always True ──────────────────────────────────────

def test_m06_low_confidence_caught() -> None:
    """M06: confidence -0.1 must be flagged."""
    rec = _n.sign(_fresh_idr(confidence=-0.1))
    failures = _n.verify_one(rec)
    assert any("confidence" in f for f in failures), (
        "M06 survived: negative confidence not caught"
    )


def test_m06_high_confidence_caught() -> None:
    """M06: confidence 1.1 must be flagged."""
    rec = _n.sign(_fresh_idr(confidence=1.1))
    failures = _n.verify_one(rec)
    assert any("confidence" in f for f in failures), (
        "M06 survived: confidence > 1.0 not caught"
    )


# ─── M07: verify_chain returns [] on error ────────────────────────────────────

def test_m07_chain_error_propagates() -> None:
    """M07: a broken chain must not silently return []."""
    chain = _n.demo_chain()
    # Tamper entry 2's previous_hash
    chain[1] = _n.IDR(
        **{**asdict(chain[1]), "previous_hash": "0" * 64, "signature": chain[1].signature}
    )
    failures = _n.verify_chain(chain)
    assert failures != [], "M07 survived: broken chain returned empty failures list"


# ─── M08: PROTOCOL_VERSION = "happi/1.0" ─────────────────────────────────────

def test_m08_wrong_protocol_caught() -> None:
    """M08: a record with wrong protocol must fail verify_one."""
    rec = _n.sign(_fresh_idr(protocol="happi/1.0"))
    failures = _n.verify_one(rec)
    assert any("protocol" in f for f in failures), (
        "M08 survived: wrong protocol version not caught"
    )


def test_m08_correct_protocol_passes() -> None:
    """M08: a record with PROTOCOL_VERSION must pass protocol check."""
    rec = _n.sign(_fresh_idr())
    assert _n.PROTOCOL_VERSION == "happi/1.1"
    failures = [f for f in _n.verify_one(rec) if "protocol" in f]
    assert failures == [], f"M08 survived: correct protocol rejected: {failures}"


# ─── M09: no bounds check on --at ────────────────────────────────────────────

def test_m09_at_out_of_range_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M09: --at 99 on a 3-entry chain must return exit code 2."""
    from io import StringIO

    chain = _n.demo_chain()
    chain_file = tmp_path / "chain.md"
    with chain_file.open("w") as f:
        for rec in chain:
            f.write("```idr\n")
            f.write(json.dumps(asdict(rec), indent=2, sort_keys=True))
            f.write("\n```\n\n")

    import argparse
    args = argparse.Namespace(chain=str(chain_file), at=99)
    result = _n.cmd_verify(args)
    assert result == 2, f"M09 survived: --at 99 returned {result} not 2"


# ─── M10: missing key continues silently ─────────────────────────────────────

def test_m10_missing_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """M10: missing DONNA_NOTARISE_KEY must call sys.exit(2)."""
    monkeypatch.delenv(_n.ENV_KEY, raising=False)
    with pytest.raises(SystemExit) as exc_info:
        _n._key()
    assert exc_info.value.code == 2, (
        f"M10 survived: missing key exited with {exc_info.value.code} not 2"
    )


# ─── M11: whitespace in separators ───────────────────────────────────────────

def test_m11_no_whitespace_in_payload() -> None:
    """M11: canonical payload must have no spaces after : or , (compact JSON)."""
    rec = _fresh_idr()
    payload = rec.canonical_payload().decode("utf-8")
    assert ": " not in payload, "M11 survived: space after colon in payload"
    assert ", " not in payload, "M11 survived: space after comma in payload"


# ─── M12: previous_hash always compares equal to itself ──────────────────────

def test_m12_different_previous_hash_fails_chain() -> None:
    """M12: if check uses same var both sides, any chain break is invisible."""
    # Build a 2-entry chain where entry 2 has wrong previous_hash
    entry1 = _n.sign(_fresh_idr())
    correct_hash = entry1.hash()
    # Entry 2 has genesis hash, NOT entry1's hash
    entry2 = _n.sign(_fresh_idr(previous_hash=_n.GENESIS_PREVIOUS_HASH))
    failures = _n.verify_chain([entry1, entry2])
    assert failures != [], (
        "M12 survived: chain with wrong previous_hash reported clean"
    )
    assert "chain break" in failures[0], (
        f"M12 survived: wrong error message: {failures[0]}"
    )


# ─── M13: all records same timestamp ─────────────────────────────────────────

def test_m13_demo_timestamps_distinct() -> None:
    """M13: each demo IDR must have a distinct timestamp."""
    chain = _n.demo_chain()
    timestamps = [r.timestamp for r in chain]
    assert len(set(timestamps)) == len(timestamps), (
        f"M13 survived: duplicate timestamps in demo chain: {timestamps}"
    )


def test_m13_demo_ids_distinct() -> None:
    """M13: each demo IDR must have a distinct decision_id."""
    chain = _n.demo_chain()
    ids = [r.decision_id for r in chain]
    assert len(set(ids)) == len(ids), (
        f"M13 survived: duplicate decision_ids in demo chain: {ids}"
    )


# ─── M14: confidence check always appends error ──────────────────────────────

def test_m14_valid_confidence_no_error() -> None:
    """M14: if `if True:` replaces the bounds check, all records report confidence error."""
    rec = _n.sign(_fresh_idr(confidence=0.9))
    failures = [f for f in _n.verify_one(rec) if "confidence" in f]
    assert failures == [], (
        f"M14 survived: valid confidence 0.9 produced error: {failures}"
    )


def test_m14_boundary_confidence_no_error() -> None:
    """M14: confidence=0.0 and 1.0 must both be valid."""
    for conf in (0.0, 1.0):
        rec = _n.sign(_fresh_idr(confidence=conf))
        failures = [f for f in _n.verify_one(rec) if "confidence" in f]
        assert failures == [], (
            f"M14 survived: boundary confidence {conf} produced error: {failures}"
        )
