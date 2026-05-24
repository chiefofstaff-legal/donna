"""Substrate-layer OAuth2 CSRF state primitives — RFC 6749 §10.12 / RFC 6819 §4.4.1.8.

D4(a) deliverable. Lifted from nexus-poc/backend/app/auth.py:189–251 per the
structural mapping #1 in `~/.claude/drafts/clio-cbc-2026-05-24/SPEC.md`.
Gentner SMT scored ≥80/100 on the source→target causal mapping: same RFC
threat model, same HMAC + payload + expiry + user-binding contract.

Framework-agnostic by construction:
- Accepts opaque ``user_id: str`` (no FastAPI ``User`` type)
- Accepts opaque ``signing_key: bytes`` (no module-level cache,
  no I/O — caller owns key derivation)
- Returns ``str`` token / ``bool`` verdict — no ``HTTPException``,
  no ``RedirectResponse``
- Pure: no filesystem, no network, no module state

Token shape (preserved byte-for-byte from nexus auth.py for migration parity):

    base64url(payload).base64url(signature)

where ``payload = json.dumps({"user_id": ..., "exp": ..., "nonce": ...},
separators=(",", ":")).encode("utf-8")`` and ``signature =
hmac.new(signing_key, payload, sha256).digest()``.

Migration sequencing (per Council R5 + R7 in COUNCIL.md):
1. This module ships in the donna OSS PR (self-contained — nexus is unchanged).
2. Nexus follow-up PR: rewrite ``app.auth.sign_oauth_state`` /
   ``verify_oauth_state`` to thin wrappers that inject
   ``signing_key=_get_signing_key()``. Zero behavioural change at the HTTP
   surface; the wire format is identical because this module replicates the
   nexus byte-shape exactly.
3. After nexus follow-up lands, the duplicate implementation in
   nexus/backend/app/auth.py is dead code; remove in a third PR.

Goodhart guard (Rule 14): every test in ``tests/test_clio_oauth_state.py``
names the one-line mutation it catches; weakening the HMAC, dropping the
user-binding check, or removing the expiry check all fail.

Origin: V>> CBC Optimal sprint 2026-05-24. Council verdict
PROCEED_WITH_REVISIONS · Gentner SMT 90/100 on the SPEC mapping.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

#: Default TTL for an OAuth2 state token (10 min — long enough for the human
#: OAuth flow, short enough to bound replay window). Callers override per
#: deployment via the ``ttl_seconds`` kwarg.
OAUTH_STATE_DEFAULT_TTL_S: int = 600


def _b64url(raw: bytes) -> str:
    """base64url encode without padding (token-safe URL parameter shape)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """base64url decode tolerating missing padding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign(
    user_id: str,
    signing_key: bytes,
    *,
    ttl_seconds: int = OAUTH_STATE_DEFAULT_TTL_S,
    now: int | None = None,
) -> str:
    """Sign an OAuth2 ``state`` token bound to ``user_id``.

    Stateless — no server-side store. The token carries
    ``{"user_id": ..., "exp": ..., "nonce": ...}`` signed under ``signing_key``
    via HMAC-SHA256. ``nonce`` is a 16-byte URL-safe random string so two
    tokens minted in the same second for the same user differ.

    Args:
        user_id: Opaque per-tenant identifier the callback must echo.
            Not parsed by this module — treat as a bytestring.
        signing_key: HMAC key bytes (≥32 bytes recommended). The caller
            owns key derivation; nexus uses its session signing key,
            OSS consumers may supply any secret.
        ttl_seconds: Token lifetime in seconds. Default 600 (10 min).
        now: Override for the current time (test seam). Default
            ``int(time.time())``.

    Returns:
        ``base64url(payload).base64url(signature)`` — URL-safe string.
    """
    exp = int(now if now is not None else time.time()) + int(ttl_seconds)
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps(
        {"user_id": user_id, "exp": exp, "nonce": nonce},
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(signing_key, payload, sha256).digest()
    return f"{_b64url(payload)}.{_b64url(signature)}"


def verify(
    token: str,
    expected_user_id: str,
    signing_key: bytes,
    *,
    now: int | None = None,
) -> bool:
    """Return ``True`` iff ``token`` is intact, unexpired, AND bound to ``expected_user_id``.

    The ``expected_user_id`` binding is load-bearing per RFC 6819 §4.4.1.8:
    a valid state token minted for tenant A MUST NOT validate for tenant B's
    session, OR an attacker could mint a state token under their own session
    and replay it against a victim's browser — defeating the point of state.

    Fail-CLOSED on ANY parse / decode / shape / format / signature / binding
    / expiry error. Returns ``False`` for every defect. Never raises.

    Constant-time HMAC compare (``hmac.compare_digest``) — no early-exit
    timing channel.

    Args:
        token: The state token to verify.
        expected_user_id: The user_id the caller expects this token to be
            bound to (typically the currently-authenticated session user).
        signing_key: Same HMAC key used at sign time.
        now: Override for the current time (test seam).
    """
    if not token or token.count(".") != 1:
        return False
    payload_b64, sig_b64 = token.split(".")
    try:
        payload = _b64url_decode(payload_b64)
        provided_sig = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(signing_key, payload, sha256).digest()
    if not hmac.compare_digest(expected, provided_sig):
        return False
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    user_id = data.get("user_id")
    exp = data.get("exp")
    if not isinstance(user_id, str) or not isinstance(exp, int):
        return False
    if user_id != expected_user_id:
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    return True


__all__ = [
    "OAUTH_STATE_DEFAULT_TTL_S",
    "sign",
    "verify",
]
