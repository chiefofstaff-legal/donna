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
import shutil  # noqa: F401 — retained so tests can patch clio.shutil.which
import subprocess  # noqa: F401 — retained so tests can patch clio.subprocess.run
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Tuple

from donna.secrets import select_store

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
    """Read a secret value via the configured store backend. Returns ``None`` on failure.

    Despite the legacy ``_kc_`` name (kept so existing tests that patch
    ``clio._kc_read`` continue to intercept), this dispatches to
    ``donna.secrets.select_store()``: ``KeychainStore`` on macOS, otherwise
    ``EncryptedFileStore`` (when ``DONNA_SECRETS_KEY`` is configured) or
    ``EnvVarStore`` (read-only fallback). Centralised so ``load_config`` +
    ``refresh_access_token`` share one well-tested code path.

    Tests can patch ``clio._kc_read`` directly OR set ``DONNA_SECRET_STORE``
    to pick a backend explicitly.
    """
    return select_store().read(service)


def _kc_write(service: str, value: str) -> bool:
    """Atomically write/update a secret via the configured store backend.

    Despite the legacy ``_kc_`` name (kept so existing tests that patch
    ``clio._kc_write`` continue to intercept), this dispatches to
    ``select_store()``. Returns ``True`` on success.

    Atomic-replace semantics are preserved by each writeable backend:
    ``KeychainStore`` uses ``security ... -U``; ``EncryptedFileStore`` uses
    a tempfile + ``os.rename``; ``MemoryStore`` is dict-assignment-under-lock.
    A successful write means the new value is durably persisted before this
    function returns — the OAuth refresh flow depends on this.

    If the configured backend is read-only (``EnvVarStore``), returns
    ``False`` — refresh-token rotation cannot persist through a Reader-only
    store, and the caller falls through to the fail-CLOSED 401 path.
    """
    store = select_store()
    write_fn = getattr(store, "write", None)
    if write_fn is None:
        return False
    return bool(write_fn(service, value))


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


# ---------------------------------------------------------------------------
# D4(d) — OAuth2 grant orchestration with IDR-on-grant
# ---------------------------------------------------------------------------
#
# Lifts the W3 nexus pattern (intent IDR → token-grant POST → outcome IDR)
# into the substrate so a single source of truth emits OAuth grant IDRs.
# Nexus follow-up PR rewrites ``routes_clio.oauth_callback`` to call
# ``grant_oauth_tokens`` directly — at which point the in-app duplication
# of `_token_grant_post + _persist_oauth_tokens` is dead code.
#
# Council R8 (defensive): every IDR emitter below carries Goodhart-resistant
# tests that fail if intent is renamed, outcome is mis-mapped, or the
# predecessor chain breaks (see ``tests/test_clio_grant.py``).


# Public alias so consumers can import the documented name without the
# leading underscore. Per Council R5 / PLAN §2.4: the underscore-prefixed
# form is kept indefinitely for nexus and any downstream consumer already
# importing it; the public ``token_grant_post`` is the documented entry
# point going forward.
token_grant_post = _token_grant_post


# Canonical IDR intent labels — replay tooling filters on these exact
# strings, so they are mutation-anchored constants (test_clio_grant.py
# fails if either is renamed).
OAUTH_GRANT_INTENT_INTENT = "oauth_grant_intent"
OAUTH_GRANT_OUTCOME_INTENT = "oauth_grant_outcome"


def _emit_oauth_grant_idr(
    logger: DecisionLoggerProtocol,
    *,
    tenant_id: str,
    grant_type: str,
    phase: str,  # "intent" | "outcome"
    outcome: str,  # "intent" | "success" | "failure"
    status_hint: int = 0,
    ritual_id: str = "oauth",
    step_id: str = "oauth_grant",
    parent_decision_id: Optional[str] = None,
) -> Optional[str]:
    """Emit one IDR for an OAuth2 grant — intent (pre-POST) OR outcome (post-POST).

    Called twice per ``grant_oauth_tokens`` invocation: once with
    ``phase="intent"`` before the network call (records "we are about to
    request a token"), once with ``phase="outcome"`` after (records
    success / failure). Both IDRs chain via ``parent_decision_id``: the
    outcome IDR's parent is the intent IDR, giving the audit chain a
    paired before/after entry per grant attempt.

    Args:
        logger: Caller's :class:`DecisionLoggerProtocol` instance.
        tenant_id: Per-tenant scoping.
        grant_type: ``"authorization_code"`` or ``"refresh_token"`` (RFC 6749 §4).
        phase: ``"intent"`` (pre-POST) or ``"outcome"`` (post-POST).
        outcome: ``"intent"`` for the pre-call IDR; ``"success"`` /
            ``"failure"`` for the post-call IDR.
        status_hint: HTTP status from the grant POST (only meaningful when
            ``phase="outcome"``); 0 for the intent phase.
        ritual_id / step_id: IDR association labels.
        parent_decision_id: Predecessor decision (the orchestrator's
            routing decision for the intent IDR; the intent IDR's
            ``decision_id`` for the outcome IDR).

    Returns:
        The ``decision_id`` from ``logger.log_decision`` (the caller threads
        the intent IDR's id into the outcome IDR as its parent).
    """
    intent_label = (
        OAUTH_GRANT_INTENT_INTENT if phase == "intent" else OAUTH_GRANT_OUTCOME_INTENT
    )
    context: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "intent": intent_label,
        "grant_type": grant_type,
        "phase": phase,
        "outcome": outcome,
        "status": status_hint,
    }
    if parent_decision_id:
        context["parent_decision_id"] = parent_decision_id
    confidence = 1.0 if outcome in ("intent", "success") else 0.0
    why_str = f"OAuth2 {grant_type} grant {phase}"
    if phase == "outcome":
        why_str += f" status={status_hint}"
    what_str = f"{intent_label}:tenant={tenant_id}:grant={grant_type}"
    # NOTE on kwarg order: deliberately distinct from `_emit_mutation_idr` /
    # `_emit_not_configured_idr` to keep each emitter a single semantically
    # cohesive call site. The Protocol contract permits any order; this site
    # is structured (context first, then routing fields) so per-intent
    # emitters remain individually inspectable rather than collapsing into a
    # shared helper that hides the per-emitter intent / confidence / context
    # construction in indirection.
    return logger.log_decision(
        context=context,
        what=what_str,
        why=why_str,
        confidence=confidence,
        ritual_id=ritual_id,
        step_id=step_id,
    )


def grant_oauth_tokens(
    tenant_id: str,
    *,
    grant_type: str,
    code: Optional[str] = None,
    refresh_token: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    logger: Optional[DecisionLoggerProtocol] = None,
    parent_decision_id: Optional[str] = None,
    ritual_id: str = "oauth",
    step_id: str = "oauth_grant",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Orchestrate an OAuth2 grant: intent IDR → POST → outcome IDR.

    Single public coordinator for both grant flows Clio supports:

    * ``grant_type="authorization_code"`` — initial token exchange. Requires
      ``code`` (from the OAuth callback), ``client_id``, ``client_secret``,
      and typically ``redirect_uri``. The application layer (nexus's
      ``routes_clio.oauth_callback``) becomes a thin caller after this PR.
    * ``grant_type="refresh_token"`` — token refresh. Requires
      ``refresh_token``, ``client_id``, ``client_secret``. Internal callers
      (donna's :func:`refresh_access_token`) may opt in to this orchestrator
      in a follow-up commit; for now it ships as net-new public surface.

    Emits TWO IDRs per call when ``logger`` is provided:

    * Intent IDR (pre-POST) — records that a grant attempt is starting.
      Chains to ``parent_decision_id`` if the caller passed one (typically
      the routing decision that produced the grant request).
    * Outcome IDR (post-POST) — records ``success`` (HTTP 200 + parsed
      payload) OR ``failure`` (non-200 / transport error / non-JSON).
      Chains to the intent IDR's ``decision_id``.

    Returns:
        ``(payload, outcome_decision_id)``. ``payload`` is ``None`` on
        failure; on success it is the parsed JSON dict from Clio's
        ``/oauth/token`` response. ``outcome_decision_id`` is the IDR id
        from the outcome IDR (or ``None`` when ``logger`` is ``None``).

    Per Council R3: required grant params enumerated explicitly. Other
    flows (e.g. PKCE) are out of scope until a real caller appears (YAGNI
    + N=2 per ``rules/knowledge-maturation-functor.md``).

    Per Council R5: this substrate addition is self-contained — the nexus
    follow-up PR replaces its inline ``_token_grant_post + persist`` flow
    with a single call to ``grant_oauth_tokens`` + ``_stash_refreshed_tokens``.

    Fail-CLOSED: any defect (missing required field for the grant type, HTTP
    error, non-JSON response, non-200 status) returns ``(None, decision_id)``.
    The outcome IDR is STILL emitted on failure — a chain hole on failed
    grants would defeat the forensic value the chain exists to provide.
    """
    # Intent IDR — record the attempt BEFORE network I/O.
    intent_id: Optional[str] = None
    if logger is not None:
        intent_id = _emit_oauth_grant_idr(
            logger,
            tenant_id=tenant_id,
            grant_type=grant_type,
            phase="intent",
            outcome="intent",
            status_hint=0,
            ritual_id=ritual_id,
            step_id=step_id,
            parent_decision_id=parent_decision_id,
        )

    # Build the grant params per grant_type. Missing required params fail
    # CLOSED (returns None payload + emits a failure outcome IDR).
    params: Dict[str, str] = {"grant_type": grant_type}
    if client_id:
        params["client_id"] = client_id
    if client_secret:
        params["client_secret"] = client_secret
    if grant_type == "authorization_code":
        if not code:
            return _grant_outcome(logger, tenant_id, grant_type, 0, intent_id,
                                  ritual_id, step_id, payload=None)
        params["code"] = code
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
    elif grant_type == "refresh_token":
        if not refresh_token:
            return _grant_outcome(logger, tenant_id, grant_type, 0, intent_id,
                                  ritual_id, step_id, payload=None)
        params["refresh_token"] = refresh_token
    else:
        # Unknown grant_type — fail-CLOSED.
        return _grant_outcome(logger, tenant_id, grant_type, 0, intent_id,
                              ritual_id, step_id, payload=None)

    payload = _token_grant_post(params)
    # _token_grant_post returns dict on HTTP 200 + valid JSON; None otherwise.
    # We hint status=200 on success, 0 on failure — the underlying error class
    # (HTTP error vs JSON decode vs non-200) is preserved in the audit-chain
    # via the outcome=failure label even when the precise status is opaque.
    status_hint = 200 if payload is not None else 0
    return _grant_outcome(logger, tenant_id, grant_type, status_hint, intent_id,
                          ritual_id, step_id, payload=payload)


def _grant_outcome(
    logger: Optional[DecisionLoggerProtocol],
    tenant_id: str,
    grant_type: str,
    status_hint: int,
    intent_id: Optional[str],
    ritual_id: str,
    step_id: str,
    *,
    payload: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Emit the outcome IDR and return (payload, outcome_decision_id).

    Extracted helper so ``grant_oauth_tokens`` keeps a low cyclomatic
    complexity number — each early-return path in the orchestrator funnels
    through one outcome-IDR emission point (DRY + KISS).
    """
    outcome_label = "success" if payload is not None else "failure"
    outcome_id: Optional[str] = None
    if logger is not None:
        outcome_id = _emit_oauth_grant_idr(
            logger,
            tenant_id=tenant_id,
            grant_type=grant_type,
            phase="outcome",
            outcome=outcome_label,
            status_hint=status_hint,
            ritual_id=ritual_id,
            step_id=step_id,
            parent_decision_id=intent_id,
        )
    return payload, outcome_id


__all__ = [
    # Existing public surface — preserved byte-for-byte
    "CLIO_API_BASE",
    "ClioConfig",
    "ClioResult",
    "DecisionLoggerProtocol",
    "call",
    "load_config",
    "refresh_access_token",
    # D4(d) additions — NEW public surface
    "OAUTH_GRANT_INTENT_INTENT",
    "OAUTH_GRANT_OUTCOME_INTENT",
    "grant_oauth_tokens",
    "token_grant_post",
]
