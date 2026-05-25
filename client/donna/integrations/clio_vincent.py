"""Clio Vincent AI wrapper — notarise Vincent invocations via IDR.

D3 deliverable. Closes https://github.com/chiefofstaff-legal/donna/issues/19
("research: Clio Vincent AI wrapping — notarise Vincent invocations via IDR").

What this does
--------------

Vincent is Clio's in-product AI feature (suggestion + ratification on
matters / time entries / documents). DONNA's value proposition is that
**every legally-impactful decision is signed and chained**. A Vincent
invocation IS legally-impactful — "Vincent suggested X, partner ratified
at confidence Y" must enter the audit chain or the chain has holes
exactly where AI-assisted legal work happens.

The wrapper emits **exactly one IDR per ``vincent_call``** with:

* ``intent=vincent_invocation`` — the canonical IDR intent label.
* ``matter_id`` — binds the invocation to its matter (replay scope).
* ``prompt_sha256`` — content-addressable prompt fingerprint. The raw
  prompt is sent to Clio but never stored in the chain (PII discipline).
* ``response_sha256`` — content-addressable response fingerprint.
* ``outcome`` — success / failure / transport_failure (mirrors clio.py).

Chained via ``parent_decision_id`` when the caller's logger has a
current chain head (typically the orchestrator's routing decision OR
the previous Vincent invocation in the matter's chain).

Endpoint assumption (R0 — UNVERIFIED at write-time)
---------------------------------------------------

Public Clio docs (https://docs.clio.com, https://app.clio.com/api/v4/docs)
do not name a Vincent invocation REST endpoint in the publicly-indexed
surface as of 2026-05-24. Vincent is primarily an in-product feature in
newer Clio Manage; a REST surface is not publicly documented at writing
time. Two paths considered:

1. ``POST /vincent/invocations`` (assumed default) — consistent with
   Clio's REST convention (``/matters``, ``/contacts``, ``/activities``,
   ``/time_entries``, ``/documents``).
2. ``POST /matters/<id>/vincent/invocations`` (matter-scoped variant).

We default to (1) and parametrise the path via ``$CLIO_VINCENT_PATH`` so
a follow-up "verify the exact endpoint against Clio's internal docs"
changes one env var without touching wrapper code. The IDR emission
contract is **transport-agnostic** — whichever endpoint Clio actually
exposes, the audit semantics are identical. Correctness is proved by
mutation-resistant test (Goodhart-anchored) regardless of the URL.

TODO (V>>): verify Vincent endpoint path against Clio dev support or
sandbox account; set ``CLIO_VINCENT_PATH`` env var if different. See
``docs/clio-vincent-wrap-feasibility.md`` for the research write-up.

Per Council R2 (2026-05-24): ``model`` parameter dropped — Clio Vincent
does NOT expose model selection to API callers (it's Clio's in-house
AI). Speculative parameter removed before write-time.

Origin: 2026-05-24, V>> CBC Optimal sprint. Issue #19 reference:
``project_donna_clio_filevine_integration_2026-05-20.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional

from donna.integrations.clio import (
    ClioResult,
    DecisionLoggerProtocol,
    _classify_outcome,
    _http_with_retry,
    load_config,
)

# IDR intent label — canonical across all Vincent invocations so
# downstream replay tools can filter the chain to AI-assisted decisions.
VINCENT_INTENT = "vincent_invocation"

# Endpoint path — env-overridable single constant. See "Endpoint
# assumption" in module docstring for the research provenance.
_VINCENT_PATH_DEFAULT = "/vincent/invocations"


def _vincent_path() -> str:
    """Resolve the Vincent endpoint path (env override → default)."""
    return os.environ.get("CLIO_VINCENT_PATH", _VINCENT_PATH_DEFAULT)


def _sha256_hex(text: str) -> str:
    """Content-addressable fingerprint helper.

    Used for both prompt and response so the IDR records *what was sent
    and received* (verifiable post-hoc against the original strings)
    without storing the words themselves in the chain. This is the
    PII-safe pattern for signing prompts that may contain client data.
    """
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_vincent_context(
    *,
    tenant_id: str,
    matter_id: str,
    prompt: str,
    response_body: Dict[str, Any],
    status: int,
    parent_decision_id: Optional[str],
) -> Dict[str, Any]:
    """Build the IDR ``context`` dict for a Vincent invocation.

    Extracted so the IDR shape lives in one place (DRY) — every Vincent
    IDR carries this exact shape, replay tooling depends on it being
    uniform. Per Council R2: no ``model`` field (Vincent doesn't expose
    model selection).
    """
    response_text = json.dumps(response_body, sort_keys=True, separators=(",", ":"))
    _, outcome_label = _classify_outcome(status)
    ctx: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "intent": VINCENT_INTENT,
        "matter_id": matter_id,
        "prompt_sha256": _sha256_hex(prompt),
        "response_sha256": _sha256_hex(response_text),
        "status": status,
        "outcome": outcome_label,
    }
    if parent_decision_id:
        ctx["parent_decision_id"] = parent_decision_id
    return ctx


def _emit_vincent_idr(
    logger: DecisionLoggerProtocol,
    *,
    tenant_id: str,
    matter_id: str,
    prompt: str,
    response_body: Dict[str, Any],
    status: int,
    ritual_id: str,
    step_id: str,
    parent_decision_id: Optional[str],
) -> Optional[str]:
    """Record exactly one IDR for a Vincent invocation.

    Called whether the underlying Clio call succeeded (2xx) or failed
    (4xx/5xx/transport) — a failure IDR is still a chain entry; the
    forensic value of the chain is that it captures BOTH paths.
    """
    ok, outcome_label = _classify_outcome(status)
    context = _build_vincent_context(
        tenant_id=tenant_id,
        matter_id=matter_id,
        prompt=prompt,
        response_body=response_body,
        status=status,
        parent_decision_id=parent_decision_id,
    )
    return logger.log_decision(
        what=f"{VINCENT_INTENT}:matter={matter_id}",
        why=f"Vincent AI invocation outcome status={status} ({outcome_label})",
        confidence=1.0 if ok else 0.0,
        ritual_id=ritual_id,
        step_id=step_id,
        context=context,
    )


def vincent_call(
    tenant_id: str,
    *,
    matter_id: str,
    prompt: str,
    logger: Optional[DecisionLoggerProtocol] = None,
    ritual_id: str = "orchestrator",
    step_id: str = "vincent_call",
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """Invoke Clio Vincent AI on ``matter_id`` with ``prompt``, emit one IDR.

    Args:
        tenant_id: Per-tenant scoping (resolves Keychain entry
            ``grip-clio-<tenant_id>``).
        matter_id: The Clio matter Vincent is being invoked against.
            Binds the IDR to a replay scope.
        prompt: The natural-language prompt sent to Vincent. Hashed
            (SHA-256) into the IDR; the raw text is sent to Clio but
            never stored in the chain (PII discipline).
        logger: Optional ``DecisionLoggerProtocol`` instance. When
            provided, the IDR is emitted and ``decision_id`` is set on
            the result. When ``None``, the call still executes (the
            chain just does not extend).
        ritual_id / step_id: IDR ritual / step association labels.
        parent_decision_id: Optional link to a predecessor decision —
            typically the orchestrator's routing decision OR the prior
            Vincent invocation in the matter's chain. Threaded into
            the IDR context for chain-forest replay.

    Returns:
        ``ClioResult`` with ``ok`` per HTTP status, ``body`` from Vincent
        (or an error dict), and ``decision_id`` set when ``logger`` was
        provided (regardless of success/failure of the Vincent call —
        failure IDRs are signed too).

    Closes issue #19: DONNA can wrap Vincent invocations with IDR
    emission. Vincent's "suggested X" + caller's "ratified at confidence Y"
    enter the chain as one decision record.

    Per Council R2 (2026-05-24): ``model=`` parameter dropped (Clio
    Vincent does not expose model selection to API callers).
    """
    cfg = load_config(tenant_id)
    if cfg is None:
        # Not-configured path: emit IDR if logger present (Vincent
        # invocation IS a mutation; council verdict #6 fail-CLOSED).
        decision_id = None
        if logger is not None:
            decision_id = _emit_vincent_idr(
                logger,
                tenant_id=tenant_id,
                matter_id=matter_id,
                prompt=prompt,
                response_body={"error": "not_configured"},
                status=0,
                ritual_id=ritual_id,
                step_id=step_id,
                parent_decision_id=parent_decision_id,
            )
        return ClioResult(
            ok=False, status=0, body={"error": "not_configured"},
            decision_id=decision_id,
        )

    request_body: Dict[str, Any] = {"matter_id": matter_id, "prompt": prompt}
    status, body_out = _http_with_retry("POST", _vincent_path(), cfg, request_body)

    decision_id: Optional[str] = None
    if logger is not None:
        decision_id = _emit_vincent_idr(
            logger,
            tenant_id=tenant_id,
            matter_id=matter_id,
            prompt=prompt,
            response_body=body_out,
            status=status,
            ritual_id=ritual_id,
            step_id=step_id,
            parent_decision_id=parent_decision_id,
        )
    ok, _ = _classify_outcome(status)
    return ClioResult(ok=ok, status=status, body=body_out, decision_id=decision_id)


__all__ = [
    "VINCENT_INTENT",
    "vincent_call",
]
