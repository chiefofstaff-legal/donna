"""Clio integration adapter — per-tenant OAuth2 client with IDR emission.

Council-ratified design (chiefofstaff-legal/donna#18, synthesis 2026-05-20):

* **Adapter shape**: standalone module + thin dataclasses. Defer ABC to N=3.
* **OAuth2 lifecycle**: dev = macOS Keychain ``grip-clio-<tenant_id>``.
  Production = per-tenant file with envelope-encrypted token (follow-up commit).
* **IDR granularity**: per *user-visible decision*. Mutations (POST/PATCH/PUT/
  DELETE) emit one ``log_decision`` IDR. Pure-read GETs do not chain — they
  live in returned ``ClioResult.body`` only. (Council verdict #3.)
* **Failure modes**: transparent retry for transient 5xx within a 30s window,
  single IDR. Persistent failures emit a failure IDR (caller may follow up
  with ``supersede_decision()``). (Council verdict #4.)
* **Mock toggle**: when ``load_config`` returns ``None`` (no Keychain entry),
  the call enters degraded mode — emits a ``"Clio not configured"`` IDR and
  returns a graceful error result. Fail-CLOSED, never silent mock success.
  (Council verdict #6.)

Tightening on top of the council outline (this commit adds):

* **``DecisionLoggerProtocol``** via ``typing.Protocol`` — donna OSS does not
  hard-depend on any specific logger. Downstream consumers (GRIP private's
  ``lib.copilot.decision_logger.DecisionLogger``, or a future
  ``donna.audit.NotariseLogger`` wrapping ``bin/notarise``) inject theirs.
* **``context.parent_decision_id``** — when the orchestrator passes the
  routing decision_id through, the Clio mutation IDR links back to it.
  Chain replay can reconstruct the forest (routing -> mutation) even though
  each entry is its own ``log_decision`` call.

This module ships with NO real Clio HTTP calls performed — v1 is the
adapter scaffold + Goodhart-resistant tests. The first real ``call()``
against Clio's sandbox happens when V>> pastes a dev access token into
the macOS Keychain entry ``grip-clio-<tenant_id>``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Tuple

CLIO_API_BASE = os.environ.get("CLIO_API_BASE", "https://eu.app.clio.com/api/v4")
RETRY_WINDOW_S = 30.0
_HTTP_TIMEOUT_S = 20.0


def _oauth_token_url() -> str:
    """Derive the OAuth2 ``/oauth/token`` endpoint from ``CLIO_API_BASE``.

    Works for both regions: EU base ``https://eu.app.clio.com/api/v4`` and
    US base ``https://app.clio.com/api/v4`` both produce the matching
    ``…/oauth/token``. If a non-standard base is set (no ``/api/v4``
    segment), falls back to scheme+host + ``/oauth/token``.
    """
    if "/api/v4" in CLIO_API_BASE:
        return CLIO_API_BASE.replace("/api/v4", "/oauth/token")
    # Non-standard base — derive from scheme+host only.
    from urllib.parse import urlparse
    p = urlparse(CLIO_API_BASE)
    return f"{p.scheme}://{p.netloc}/oauth/token"


# ---------------------------------------------------------------------------
# Dependency-inverted logger contract
# ---------------------------------------------------------------------------


class DecisionLoggerProtocol(Protocol):
    """Minimal protocol the adapter requires of any injected decision logger.

    Concrete implementations:

    * ``lib.copilot.decision_logger.DecisionLogger`` (GRIP private) — wired by
      the orchestrator's intent handlers in round 4.
    * Any future ``donna.audit.NotariseLogger`` that wraps ``bin/notarise``
      for OSS users without GRIP private.
    * Tests inject ``unittest.mock.MagicMock(spec=DecisionLoggerProtocol)``.
    """

    def log_decision(
        self,
        what: str,
        why: str,
        alternatives: Optional[list] = None,
        confidence: float = 0.8,
        ritual_id: str = "",
        step_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        ...  # pragma: no cover  # Protocol stubs are never called directly


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClioConfig:
    """Per-tenant Clio OAuth2 config. Resolved by ``load_config``."""

    tenant_id: str
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0


@dataclass
class ClioResult:
    """Result of a single Clio API call. ``decision_id`` is set only on mutations
    AND only when a logger was provided to ``call``."""

    ok: bool
    status: int
    body: Dict[str, Any]
    decision_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Config loading (macOS Keychain — dev path)
# ---------------------------------------------------------------------------


def _kc_read(service: str) -> Optional[str]:
    """Read a value from the macOS Keychain. Returns ``None`` on any failure.

    Centralised so ``load_config`` + ``refresh_access_token`` share one
    well-tested code path; tests patch this single function.
    """
    security_bin = shutil.which("security")
    if not security_bin:
        return None
    try:
        result = subprocess.run(
            [security_bin, "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _kc_write(service: str, value: str) -> bool:
    """Atomically write/update a Keychain entry. Returns ``True`` on success.

    Uses ``-U`` so existing entries are overwritten in place — this is the
    atomic-replace semantics that the refresh flow depends on: a successful
    write means the new tokens are durably persisted before the function
    returns. ``$USER`` is read from the environment (Keychain account
    field; non-secret).
    """
    security_bin = shutil.which("security")
    if not security_bin:
        return False
    try:
        result = subprocess.run(
            [security_bin, "add-generic-password",
             "-a", os.environ.get("USER", ""),
             "-s", service, "-w", value, "-U"],
            capture_output=True, text=True, timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def load_config(tenant_id: str) -> Optional[ClioConfig]:
    """Resolve Clio config for a tenant. Returns ``None`` if not configured.

    Dev path: macOS Keychain triple:
    - ``grip-clio-<tenant_id>`` — OAuth2 access token (REQUIRED)
    - ``grip-clio-refresh-<tenant_id>`` — refresh token (optional; enables
      automatic 401-retry-with-refresh)
    - ``grip-clio-expires-<tenant_id>`` — ISO-8601 timestamp or Unix epoch
      string when the access token expires (optional; not load-bearing —
      reactive 401-retry handles expiry without it)

    Production (envelope-encrypted per-tenant file) is a follow-up commit;
    v1 is Keychain-only.

    Fail-CLOSED: anything that isn't a clean read returns ``None`` so the
    caller emits the degraded-mode "Clio not configured" IDR rather than
    fabricating a silent mock-success.
    """
    access_token = _kc_read(f"grip-clio-{tenant_id}")
    if not access_token:
        return None
    # Refresh + expiry are best-effort; absence is fine for legacy single-
    # token tenants and gracefully degrades to no-refresh-on-401.
    refresh_token = _kc_read(f"grip-clio-refresh-{tenant_id}") or ""
    expires_raw = _kc_read(f"grip-clio-expires-{tenant_id}") or ""
    expires_at = 0.0
    if expires_raw:
        try:
            expires_at = float(expires_raw)
        except ValueError:
            # Tolerate ISO-8601 strings too.
            import datetime
            try:
                expires_at = datetime.datetime.fromisoformat(
                    expires_raw.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                expires_at = 0.0
    return ClioConfig(
        tenant_id=tenant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def _token_grant_post(params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """POST to the OAuth ``/oauth/token`` endpoint with the given grant params.

    Returns the parsed JSON payload on HTTP 200, ``None`` on any failure
    (HTTP error, transport error, non-200, non-JSON). Centralises the
    refresh + authorization_code grant logic; today only refresh uses it,
    but the authorization_code grant we ran in-session is a natural
    second caller when we automate the initial token flow.
    """
    body = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        _oauth_token_url(), data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode() or 0
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None
    if status != 200:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _stash_refreshed_tokens(
    tenant_id: str, payload: Dict[str, Any], prev_refresh: str
) -> Optional[ClioConfig]:
    """Atomic-replace the per-tenant tokens after a successful refresh grant.

    Order matters: access first, then refresh, then expiry. A partial
    failure mid-stash returns ``None`` — the caller falls through to the
    fail-CLOSED 401 path. The OLD refresh_token remains valid in Keychain
    until the new one writes successfully (Clio honours the previous
    refresh_token for a short window per OAuth2 BCP).
    """
    new_access = payload.get("access_token", "")
    new_refresh = payload.get("refresh_token", "")
    expires_in = payload.get("expires_in", 0)
    if not new_access:
        return None
    if not _kc_write(f"grip-clio-{tenant_id}", new_access):
        return None
    if new_refresh and not _kc_write(f"grip-clio-refresh-{tenant_id}", new_refresh):
        return None
    new_expires_at = time.time() + float(expires_in) if expires_in else 0.0
    if new_expires_at:
        _kc_write(f"grip-clio-expires-{tenant_id}", str(new_expires_at))
    return ClioConfig(
        tenant_id=tenant_id,
        access_token=new_access,
        refresh_token=new_refresh or prev_refresh,
        expires_at=new_expires_at,
    )


def refresh_access_token(tenant_id: str) -> Optional[ClioConfig]:
    """Exchange the stored refresh_token for a fresh access_token (+ new
    refresh_token, since Clio rotates refresh tokens on every grant).

    Reads client_id + client_secret from Keychain entries
    ``grip-clio-app-id`` and ``grip-clio-app-secret`` (the OAuth2 app
    credentials, NOT the per-tenant access token). Secrets stay inside
    this Python process scope — never become shell env vars or argv.

    Atomic-replace via ``_stash_refreshed_tokens``: on success, BOTH
    ``grip-clio-<tenant_id>`` AND ``grip-clio-refresh-<tenant_id>`` are
    updated before this function returns. ``grip-clio-expires-<tenant_id>``
    is set to ``now + expires_in`` so future ``load_config`` reads see
    the new expiry.

    Fail-CLOSED: any failure (no refresh_token, no app creds, HTTP error,
    invalid_grant, partial Keychain write) returns ``None``. Caller
    surfaces this as a 401 + the existing degraded-mode IDR path.
    ``invalid_grant`` specifically means the refresh_token chain is broken
    — operator must re-authorise.
    """
    cfg = load_config(tenant_id)
    if cfg is None or not cfg.refresh_token:
        return None
    client_id = _kc_read("grip-clio-app-id")
    client_secret = _kc_read("grip-clio-app-secret")
    if not client_id or not client_secret:
        return None
    payload = _token_grant_post({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": cfg.refresh_token,
    })
    if payload is None:
        return None
    return _stash_refreshed_tokens(tenant_id, payload, cfg.refresh_token)


# ---------------------------------------------------------------------------
# HTTP layer (pure stdlib — patched by tests)
# ---------------------------------------------------------------------------


def _http(
    method: str, path: str, cfg: ClioConfig, body: Optional[Dict[str, Any]] = None
) -> Tuple[int, Dict[str, Any]]:
    """Single HTTP call to Clio. Returns ``(status, body_dict)``.

    A network error or non-JSON response surfaces as ``(0, {"error": "..."})``
    so callers can branch on ``status`` uniformly. Tests patch this whole
    function; no real Clio calls happen in CI.
    """
    url = f"{CLIO_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {cfg.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode() or 0
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        status = exc.code or 0
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": f"transport: {exc}"}

    if not raw:
        return status, {}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw[:500]}


def _http_with_retry(
    method: str, path: str, cfg: ClioConfig, body: Optional[Dict[str, Any]] = None
) -> Tuple[int, Dict[str, Any]]:
    """Transparent retry for transient 5xx within ``RETRY_WINDOW_S``. Single IDR.

    Per council verdict #4: option (a) for transient, option (c) supersede
    semantics are caller-side (the caller observes the failure IDR and may
    decide to call ``supersede_decision()`` after a retry of its own).
    """
    started = time.monotonic()
    status, body_out = _http(method, path, cfg, body)
    while status >= 500 and (time.monotonic() - started) < RETRY_WINDOW_S:
        time.sleep(1.0)
        status, body_out = _http(method, path, cfg, body)
    return status, body_out


# ---------------------------------------------------------------------------
# Outcome classification + IDR emission
# ---------------------------------------------------------------------------


_MUTATION_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _is_mutation(method: str) -> bool:
    """Mutations chain; reads do not (council verdict #3)."""
    return method.upper() in _MUTATION_METHODS


def _classify_outcome(status: int) -> Tuple[bool, str]:
    """Map HTTP status to (ok, outcome_label) used in the IDR ``context``."""
    if 200 <= status < 300:
        return True, "success"
    if status == 0:
        return False, "transport_failure"
    return False, "failure"


def _emit_mutation_idr(
    logger: DecisionLoggerProtocol,
    method: str,
    path: str,
    status: int,
    tenant_id: str,
    ritual_id: str,
    step_id: str,
    parent_decision_id: Optional[str],
) -> Optional[str]:
    """Record one outcome IDR for a Clio mutation. ``context.parent_decision_id``
    threads the chain-forest link back to the orchestrator's routing decision."""
    ok, outcome_label = _classify_outcome(status)
    context: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "method": method.upper(),
        "path": path,
        "status": status,
        "outcome": outcome_label,
        "clio_calls": [{"method": method.upper(), "path": path, "status": status}],
    }
    if parent_decision_id:
        context["parent_decision_id"] = parent_decision_id
    return logger.log_decision(
        what=f"clio_call:{method.upper()}:{path}",
        why=f"Clio mutation outcome status={status} ({outcome_label})",
        confidence=1.0 if ok else 0.0,
        ritual_id=ritual_id,
        step_id=step_id,
        context=context,
    )


def _emit_not_configured_idr(
    logger: DecisionLoggerProtocol,
    method: str,
    path: str,
    tenant_id: str,
    ritual_id: str,
    step_id: str,
    parent_decision_id: Optional[str],
) -> Optional[str]:
    """Degraded-mode IDR — Clio is not configured for this tenant.

    Fail-CLOSED per council verdict #6: the chain records that DONNA *would
    have* called Clio but couldn't, rather than silently lying about success.
    """
    context: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "method": method.upper(),
        "path": path,
        "outcome": "not_configured",
    }
    if parent_decision_id:
        context["parent_decision_id"] = parent_decision_id
    return logger.log_decision(
        what=f"clio_call:{method.upper()}:{path}",
        why="Clio not configured for tenant (no Keychain entry)",
        confidence=0.0,
        ritual_id=ritual_id,
        step_id=step_id,
        context=context,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def call(
    tenant_id: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    logger: Optional[DecisionLoggerProtocol] = None,
    ritual_id: str = "orchestrator",
    step_id: str = "clio_call",
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """Single entry point. Mutations emit one outcome IDR; reads emit none.

    Args:
        tenant_id: Per-tenant scoping. Resolves Keychain entry ``grip-clio-<tenant_id>``.
        method: HTTP method (GET / POST / PATCH / PUT / DELETE).
        path: Clio API path, e.g. ``/time_entries``.
        body: JSON-encodable request body (mutations only).
        logger: Optional DecisionLogger-compatible instance. When omitted,
            no IDR is emitted (the result still returns; chain just doesn't
            extend). Dependency-inverted per Protocol.
        ritual_id: IDR ritual association (default ``"orchestrator"``).
        step_id: IDR step association (default ``"clio_call"``).
        parent_decision_id: Optional link to the orchestrator's routing
            decision. When present, lands in IDR ``context.parent_decision_id``
            so chain replay can reconstruct the routing -> mutation forest.

    Returns:
        ``ClioResult`` with ``ok`` set per HTTP status, ``body`` from Clio
        (or an error dict), and ``decision_id`` set only when a mutation +
        a logger combine to extend the chain.
    """
    cfg = load_config(tenant_id)
    if cfg is None:
        decision_id = None
        if logger is not None and _is_mutation(method):
            decision_id = _emit_not_configured_idr(
                logger, method, path, tenant_id, ritual_id, step_id, parent_decision_id
            )
        return ClioResult(ok=False, status=0, body={"error": "not_configured"}, decision_id=decision_id)

    status, body_out = _http_with_retry(method, path, cfg, body)
    # Reactive 401-retry: if Clio rejected the access_token AND we have a
    # refresh_token, exchange it for a new access_token and retry the
    # request ONCE. A second 401 falls through to the existing fail path.
    if status == 401 and cfg.refresh_token:
        new_cfg = refresh_access_token(tenant_id)
        if new_cfg is not None:
            status, body_out = _http_with_retry(method, path, new_cfg, body)
    ok, _ = _classify_outcome(status)

    decision_id: Optional[str] = None
    if logger is not None and _is_mutation(method):
        decision_id = _emit_mutation_idr(
            logger, method, path, status, tenant_id, ritual_id, step_id, parent_decision_id
        )
    return ClioResult(ok=ok, status=status, body=body_out, decision_id=decision_id)
