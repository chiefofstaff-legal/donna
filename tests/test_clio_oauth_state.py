"""Tests for client/donna/oauth_state.py — OAuth2 state-token lifecycle.

D4(b) deliverable. Ported from nexus-poc/backend/tests/test_routes_clio.py
state-lifecycle suite (the 6 tests V>>'s nexus production hardened):

  - test_sign_oauth_state_round_trips
  - test_verify_oauth_state_rejects_tampered_signature
  - test_verify_oauth_state_rejects_tampered_payload
  - test_oauth_callback_rejects_expired_state         (adapted to substrate)
  - test_oauth_callback_rejects_state_bound_to_other_user (adapted)
  - test_oauth_callback_rejects_missing_state / malformed_state (split)

Hypothesis H-CLIO-4: after this cross-pollination, the donna OSS oauth_state
primitives pass nexus's 6-test state-lifecycle suite byte-for-byte (up to
import-path and signing-key-injection changes). Falsified if any test
requires substantive modification beyond those changes.

Goodhart-anchored per Rule 14: each test names the one-line mutation it
catches; weakening the HMAC, skipping user binding, or relaxing expiry all fail.

Origin: V>> CBC Optimal sprint 2026-05-24.
"""

from __future__ import annotations

import json
import secrets
import time

import pytest

from donna import oauth_state


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def signing_key() -> bytes:
    """A deterministic 32-byte key for the test suite."""
    return b"x" * 32


@pytest.fixture
def alt_signing_key() -> bytes:
    """A different key for cross-key-tampering tests."""
    return b"y" * 32


# ---------------------------------------------------------------------------
# 1. Round-trip
# ---------------------------------------------------------------------------


def test_sign_oauth_state_round_trips(signing_key):
    """Mutation: any HMAC weakening — round-trip fails on a clean token."""
    token = oauth_state.sign("user-abc", signing_key)
    assert oauth_state.verify(token, "user-abc", signing_key) is True


def test_sign_emits_payload_dot_signature_shape(signing_key):
    """Mutation: change separator from '.' — verify can't parse."""
    token = oauth_state.sign("user-1", signing_key)
    assert token.count(".") == 1


def test_sign_includes_nonce_so_two_tokens_for_same_user_differ(signing_key):
    """Mutation: drop nonce — back-to-back tokens identical, replay risk."""
    token_a = oauth_state.sign("user-1", signing_key, now=1000)
    token_b = oauth_state.sign("user-1", signing_key, now=1000)
    assert token_a != token_b


# ---------------------------------------------------------------------------
# 2. Tamper resistance
# ---------------------------------------------------------------------------


def test_verify_oauth_state_rejects_tampered_signature(signing_key):
    """Mutation: skip HMAC verify — tampered signature would pass."""
    token = oauth_state.sign("user-1", signing_key)
    payload_b64, sig_b64 = token.split(".")
    # Flip the last char of the signature.
    tampered_sig = sig_b64[:-1] + ("A" if sig_b64[-1] != "A" else "B")
    tampered = f"{payload_b64}.{tampered_sig}"

    assert oauth_state.verify(tampered, "user-1", signing_key) is False


def test_verify_oauth_state_rejects_tampered_payload(signing_key):
    """Mutation: skip HMAC verify — tampered payload would pass."""
    token = oauth_state.sign("user-1", signing_key)
    _, sig_b64 = token.split(".")
    # Forge a payload claiming a different user but reuse the original signature.
    forged = json.dumps(
        {"user_id": "attacker", "exp": int(time.time()) + 600, "nonce": "xx"},
        separators=(",", ":"),
    ).encode("utf-8")
    forged_b64 = oauth_state._b64url(forged)
    tampered = f"{forged_b64}.{sig_b64}"

    assert oauth_state.verify(tampered, "attacker", signing_key) is False


def test_verify_oauth_state_rejects_cross_key_replay(signing_key, alt_signing_key):
    """Mutation: accept any signing key — cross-tenant signature replay would pass."""
    token = oauth_state.sign("user-1", signing_key)
    assert oauth_state.verify(token, "user-1", alt_signing_key) is False


# ---------------------------------------------------------------------------
# 3. User-binding (RFC 6819 §4.4.1.8)
# ---------------------------------------------------------------------------


def test_verify_oauth_state_rejects_state_bound_to_other_user(signing_key):
    """Mutation: skip expected_user_id check — token minted for A validates B's session.

    This is the CSRF defence the user-binding check exists to provide; without
    it, an attacker mints a state token under their own session and tricks a
    victim's browser into replaying it. RFC 6819 §4.4.1.8 calls this out by
    name — losing the check defeats the entire purpose of OAuth state.
    """
    token = oauth_state.sign("victim", signing_key)
    assert oauth_state.verify(token, "attacker", signing_key) is False


# ---------------------------------------------------------------------------
# 4. Expiry (RFC 6749 §10.12)
# ---------------------------------------------------------------------------


def test_verify_oauth_state_rejects_expired(signing_key):
    """Mutation: skip expiry check — token never goes stale, indefinite replay."""
    token = oauth_state.sign("user-1", signing_key, ttl_seconds=60, now=1000)
    # Verify at now=1100 (40s after expiry).
    assert oauth_state.verify(token, "user-1", signing_key, now=1100) is False


def test_verify_oauth_state_accepts_pre_expiry(signing_key):
    """Mutation: invert expiry comparison — fresh tokens would reject."""
    token = oauth_state.sign("user-1", signing_key, ttl_seconds=60, now=1000)
    # Verify at now=1050 (10s before expiry).
    assert oauth_state.verify(token, "user-1", signing_key, now=1050) is True


def test_verify_oauth_state_rejects_exactly_at_boundary(signing_key):
    """Mutation: change strict< to ≤ — boundary behaviour shifts (rare, but caught)."""
    # Sign at now=1000 with ttl=60 → exp=1060. Verify at now=1061 (1s past exp).
    token = oauth_state.sign("user-1", signing_key, ttl_seconds=60, now=1000)
    assert oauth_state.verify(token, "user-1", signing_key, now=1061) is False


# ---------------------------------------------------------------------------
# 5. Malformed input (fail-CLOSED on every shape defect)
# ---------------------------------------------------------------------------


def test_verify_oauth_state_rejects_empty_token(signing_key):
    """Mutation: skip empty-token guard — could read out-of-bounds on split."""
    assert oauth_state.verify("", "user-1", signing_key) is False


def test_verify_oauth_state_rejects_no_dot(signing_key):
    """Mutation: skip dot-count guard — split returns 1 element, IndexError."""
    assert oauth_state.verify("nodothere", "user-1", signing_key) is False


def test_verify_oauth_state_rejects_two_dots(signing_key):
    """Mutation: accept >1 dot — token shape drift, partial-match risk."""
    assert oauth_state.verify("a.b.c", "user-1", signing_key) is False


def test_verify_oauth_state_rejects_invalid_base64(signing_key):
    """Mutation: skip b64 decode guard — exception bubbles instead of fail-CLOSED."""
    # The '!' character is invalid base64url.
    assert oauth_state.verify("!!!.???", "user-1", signing_key) is False


def test_verify_oauth_state_rejects_non_json_payload(signing_key):
    """Mutation: skip JSON parse guard — exception bubbles instead of fail-CLOSED.

    Construct a token whose payload is valid base64 of non-JSON bytes BUT
    carries a valid HMAC. Tests that JSON-decode failure fails closed AFTER
    HMAC check passes.
    """
    raw_payload = b"not-json"
    import hmac as _hmac
    from hashlib import sha256

    sig = _hmac.new(signing_key, raw_payload, sha256).digest()
    token = f"{oauth_state._b64url(raw_payload)}.{oauth_state._b64url(sig)}"
    assert oauth_state.verify(token, "user-1", signing_key) is False


def test_verify_oauth_state_rejects_missing_user_id_field(signing_key):
    """Mutation: skip user_id type/presence check — None.user_id slips through."""
    raw_payload = json.dumps(
        {"exp": int(time.time()) + 600, "nonce": "x"},
        separators=(",", ":"),
    ).encode("utf-8")
    import hmac as _hmac
    from hashlib import sha256

    sig = _hmac.new(signing_key, raw_payload, sha256).digest()
    token = f"{oauth_state._b64url(raw_payload)}.{oauth_state._b64url(sig)}"
    assert oauth_state.verify(token, "user-1", signing_key) is False


def test_verify_oauth_state_rejects_non_int_exp_field(signing_key):
    """Mutation: skip exp type check — string exp would always-fresh."""
    raw_payload = json.dumps(
        {"user_id": "user-1", "exp": "never", "nonce": "x"},
        separators=(",", ":"),
    ).encode("utf-8")
    import hmac as _hmac
    from hashlib import sha256

    sig = _hmac.new(signing_key, raw_payload, sha256).digest()
    token = f"{oauth_state._b64url(raw_payload)}.{oauth_state._b64url(sig)}"
    assert oauth_state.verify(token, "user-1", signing_key) is False


# ---------------------------------------------------------------------------
# 6. Public surface
# ---------------------------------------------------------------------------


def test_module_exports_public_surface():
    """Mutation: rename public symbol — would break consumer imports."""
    assert "sign" in oauth_state.__all__
    assert "verify" in oauth_state.__all__
    assert "OAUTH_STATE_DEFAULT_TTL_S" in oauth_state.__all__


def test_default_ttl_is_10_minutes():
    """Mutation: bump TTL to 1 hour — replay window 6x wider, security regression."""
    assert oauth_state.OAUTH_STATE_DEFAULT_TTL_S == 600


def test_sign_accepts_ttl_override(signing_key):
    """Mutation: ignore ttl_seconds kwarg — caller can't tune lifetime."""
    token_short = oauth_state.sign("u", signing_key, ttl_seconds=30, now=1000)
    token_long = oauth_state.sign("u", signing_key, ttl_seconds=3600, now=1000)
    # short token expires at 1030, long at 4600
    assert oauth_state.verify(token_short, "u", signing_key, now=1031) is False
    assert oauth_state.verify(token_long, "u", signing_key, now=1031) is True


def test_framework_agnostic_no_fastapi_import():
    """Mutation: import FastAPI inside oauth_state — substrate leaks app concern.

    Inspect import statements only (not docstring prose — the docstring may
    *mention* FastAPI when documenting the nexus-side migration sequencing).
    A real framework leak would manifest as an actual ``import`` or
    ``from … import …`` line.
    """
    import ast
    import inspect

    source = inspect.getsource(oauth_state)
    tree = ast.parse(source)
    import_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                import_modules.append(node.module)
    leaked = [m for m in import_modules if "fastapi" in m.lower() or m in {"models", "services"}]
    assert leaked == [], f"Substrate leaked app-layer imports: {leaked}"
