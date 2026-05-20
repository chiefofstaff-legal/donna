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
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Tuple

CLIO_API_BASE = "https://app.clio.com/api/v4"
RETRY_WINDOW_S = 30.0
_HTTP_TIMEOUT_S = 20.0


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


def load_config(tenant_id: str) -> Optional[ClioConfig]:
    """Resolve Clio config for a tenant. Returns ``None`` if not configured.

    Dev path: macOS Keychain entry ``grip-clio-<tenant_id>`` holding the
    OAuth2 access token. Production (envelope-encrypted per-tenant file) is
    a follow-up commit on this issue — v1 is Keychain-only.

    Fail-CLOSED: anything that isn't a clean read returns ``None`` so the
    caller emits the degraded-mode "Clio not configured" IDR rather than
    fabricating a silent mock-success.
    """
    security_bin = shutil.which("security")
    if not security_bin:
        return None  # Not macOS; production path not in this commit.

    keychain_service = f"grip-clio-{tenant_id}"
    try:
        result = subprocess.run(
            [security_bin, "find-generic-password", "-s", keychain_service, "-w"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    access_token = result.stdout.strip()
    if not access_token:
        return None
    return ClioConfig(tenant_id=tenant_id, access_token=access_token)


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
    ok, _ = _classify_outcome(status)

    decision_id: Optional[str] = None
    if logger is not None and _is_mutation(method):
        decision_id = _emit_mutation_idr(
            logger, method, path, status, tenant_id, ritual_id, step_id, parent_decision_id
        )
    return ClioResult(ok=ok, status=status, body=body_out, decision_id=decision_id)
