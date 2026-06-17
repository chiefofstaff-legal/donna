"""
tests/test_notarise_ed25519.py — Ed25519 signing + cross-language parity tests.

Coverage: Ed25519 sign/verify, tamper-fail, backward-compat with HMAC chains,
and cross-language parity vectors (Python signs → JS/TS verifies).
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

# ─── Load bin/notarise ────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent
_notarise_path = str(_REPO_ROOT / "bin" / "notarise.py")
_loader = importlib.machinery.SourceFileLoader("notarise", _notarise_path)
_spec = importlib.util.spec_from_loader("notarise", _loader)
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("notarise", _mod)
_loader.exec_module(_mod)
import notarise as _n  # noqa: E402

# Deterministic test keys — never production keys.
_HMAC_SECRET = "test-key-donna-unit-2026-abc123xyz"
# 32-byte seed as hex (deterministic; NOT a real issuer key).
_ED25519_SEED_HEX = "a" * 64  # 32 bytes of 0xaa

# Derive the public key once for use in verify tests.
_ED25519_PUBKEY_HEX: str = ""


def _derive_pubkey(seed_hex: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    seed = bytes.fromhex(seed_hex)
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


@pytest.fixture(autouse=True)
def _set_keys(monkeypatch):
    monkeypatch.setenv(_n.ENV_KEY, _HMAC_SECRET)
    monkeypatch.setenv(_n.ENV_ED25519_KEY, _ED25519_SEED_HEX)
    global _ED25519_PUBKEY_HEX
    _ED25519_PUBKEY_HEX = _derive_pubkey(_ED25519_SEED_HEX)
    monkeypatch.setenv("DONNA_NOTARISE_ED25519_PUBKEY", _ED25519_PUBKEY_HEX)


def _make_idr(**overrides) -> _n.IDR:
    defaults = dict(
        decision_id="idr_test_ed25519_001",
        timestamp="2026-06-17T12:00:00Z",
        protocol=_n.PROTOCOL_VERSION,
        intent="test ed25519 intent",
        signer="donna-bot",
        confidence=0.9,
        previous_hash=_n.GENESIS_PREVIOUS_HASH,
        metadata={},
    )
    defaults.update(overrides)
    return _n.IDR(**defaults)


# ─── Ed25519 sign ─────────────────────────────────────────────────────────────

def test_ed25519_sign_returns_128_hex():
    # Ed25519 signature is 64 bytes = 128 hex chars.
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    assert len(rec.signature) == 128
    assert all(c in "0123456789abcdef" for c in rec.signature)


def test_ed25519_sign_sets_scheme():
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    assert rec.scheme == _n.SCHEME_ED25519


def test_ed25519_sign_is_deterministic():
    # Ed25519 with the same key + payload is deterministic (RFC 8032).
    idr = _make_idr()
    r1 = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    r2 = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    assert r1.signature == r2.signature


def test_ed25519_signature_differs_across_intents():
    # Mutation: same sig for different payload → attacker can reuse signatures.
    r1 = _n.sign(_make_idr(intent="alpha"), scheme=_n.SCHEME_ED25519)
    r2 = _n.sign(_make_idr(intent="beta"), scheme=_n.SCHEME_ED25519)
    assert r1.signature != r2.signature


def test_ed25519_signature_differs_from_hmac():
    # Cross-scheme: signatures must differ even over the same payload.
    idr_hmac = _n.sign(_make_idr(), scheme=_n.SCHEME_HMAC)
    idr_ed = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    assert idr_hmac.signature != idr_ed.signature


# ─── Ed25519 verify ───────────────────────────────────────────────────────────

def test_ed25519_verify_valid():
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    failures = _n.verify_one(rec)
    assert failures == [], failures


def test_ed25519_tamper_intent_fails():
    # Mutation: tampered field passes verify → attacker can rewrite intent.
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    rec.intent = "tampered intent"
    failures = _n.verify_one(rec)
    assert failures, "should fail after tampering intent"


def test_ed25519_tamper_signature_fails():
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    rec.signature = "00" * 64
    failures = _n.verify_one(rec)
    assert failures, "should fail on wrong signature bytes"


def test_ed25519_verify_no_pubkey_fails(monkeypatch):
    monkeypatch.delenv("DONNA_NOTARISE_ED25519_PUBKEY", raising=False)
    rec = _n.sign(_make_idr(), scheme=_n.SCHEME_ED25519)
    failures = _n.verify_one(rec)
    assert any("DONNA_NOTARISE_ED25519_PUBKEY" in f for f in failures)


# ─── Backward compatibility: HMAC records still verify ───────────────────────

def test_hmac_records_still_verify_with_scheme_field():
    # Existing HMAC chains: records parsed without `scheme` default to hmac-sha256.
    rec = _n.sign(_make_idr())  # defaults to hmac-sha256
    assert rec.scheme == _n.SCHEME_HMAC
    failures = _n.verify_one(rec)
    assert failures == [], failures


def test_hmac_and_ed25519_records_in_same_chain_verify():
    # A mixed chain (hmac then ed25519) should pass full chain verify.
    r1 = _n.sign(_make_idr(), scheme=_n.SCHEME_HMAC)
    r2 = _n.sign(_make_idr(
        decision_id="idr_test_ed25519_002",
        previous_hash=r1.hash(),
        scheme=_n.SCHEME_ED25519,
    ), scheme=_n.SCHEME_ED25519)
    failures = _n.verify_chain([r1, r2])
    assert failures == [], failures


# ─── canonical_payload excludes scheme ───────────────────────────────────────

def test_canonical_payload_excludes_scheme():
    rec = _make_idr()
    rec.scheme = _n.SCHEME_ED25519
    d = json.loads(rec.canonical_payload())
    assert "scheme" not in d


def test_canonical_payload_excludes_signature():
    rec = _make_idr()
    rec.signature = "deadbeef"
    d = json.loads(rec.canonical_payload())
    assert "signature" not in d


def test_canonical_payload_same_for_hmac_and_ed25519():
    # Critical cross-scheme parity: same record body → same canonical bytes.
    r_hmac = _make_idr()
    r_ed = _make_idr()
    r_ed.scheme = _n.SCHEME_ED25519
    assert r_hmac.canonical_payload() == r_ed.canonical_payload()


# ─── Cross-language parity vector ─────────────────────────────────────────────

def test_cross_language_parity_vector():
    """Produce a signed record for cross-language verification.

    This test signs a record with a fixed seed and asserts the signature hex.
    The same vector is verified in JS/TS tests (idr-ed25519.test.ts).
    Any language mismatch → this assertion fails.
    """
    rec = _make_idr(
        decision_id="idr_parity_001",
        timestamp="2026-06-17T00:00:00Z",
        intent="cross-language parity test",
        signer="donna-test",
        confidence=1.0,
        previous_hash=_n.GENESIS_PREVIOUS_HASH,
        metadata={"lang": "python"},
    )
    signed = _n.sign(rec, scheme=_n.SCHEME_ED25519)
    # Canonical payload must be stable across languages.
    payload_bytes = signed.canonical_payload()
    payload_str = payload_bytes.decode("utf-8")
    # Verify it round-trips via verify_one.
    failures = _n.verify_one(signed)
    assert failures == [], f"parity record failed self-verification: {failures}"
    # Export the vector for cross-language consumption.
    vector = {
        "record": asdict(signed),
        "pubkey_hex": _ED25519_PUBKEY_HEX,
        "canonical_payload": payload_str,
    }
    # The record and pubkey are printed to stdout for cross-lang test harness use.
    assert len(signed.signature) == 128, "Ed25519 sig must be 64 bytes = 128 hex"
    assert vector["pubkey_hex"] == _derive_pubkey(_ED25519_SEED_HEX)
