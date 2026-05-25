"""Clio domain-method wrappers — thin shims over ``donna.integrations.clio.call``.

D2 deliverable of feat/clio-cbc-tests-wrappers-vincent.

Design discipline (SOLID/GRASP/DRY/KISS/YAGNI/BIG-O):

* **SRP** — each wrapper invokes one Clio endpoint.
* **DRY** — every read verb funnels through one ``_list_resource`` /
  ``_get_resource`` helper; the canonical mutation has its own seam.
  No repeated wrapper bodies.
* **KISS** — wrappers are 1-3 lines each; the parametrised helpers are
  the only place wrapper-shaped code lives.
* **YAGNI** — only the verbs the spec names, not every Clio endpoint.
* **BIG-O** — O(1) per wrapper; list-pagination is the caller's loop.
* **DIP** — ``logger`` is the same ``DecisionLoggerProtocol`` ``call()`` accepts.

Why a separate module
---------------------

``clio.py`` already carries OAuth lifecycle + HTTP transport + IDR
emission + ``call()`` dispatch (526 LOC, approaching CC threshold).
This module is the domain-verb layer that consumes the transport:

* ``clio.py`` — transport, auth, IDR mechanics.
* ``clio_domain.py`` — per-resource verbs that consume the transport.

Cross-pollination note: the seven verbs below are what nexus's
``backend/app/routes_clio.py`` currently inlines — substrate ownership
means future nexus routes can replace inline ``donna_clio.call(
method="POST", path="/time_entries", ...)`` with a single
``donna_clio_domain.create_time_entry(...)`` and the per-resource
intent is visible at the call site.

Origin: 2026-05-24, V>> CBC Optimal sprint.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from donna.integrations.clio import (
    ClioResult,
    DecisionLoggerProtocol,
    call,
)


# ---------------------------------------------------------------------------
# Shared seams — the only place wrapper-shaped code lives
# ---------------------------------------------------------------------------


def _query(
    *,
    page: Optional[int] = None,
    limit: Optional[int] = None,
    matter_id: Optional[str] = None,
) -> str:
    """Build the ``?k=v&k=v`` query string for the three supported params.

    Empty string when nothing set. The three params are the only filters
    our wrappers expose (YAGNI — extend when a real caller needs more).
    """
    parts = []
    if page is not None:
        parts.append(f"page={int(page)}")
    if limit is not None:
        parts.append(f"limit={int(limit)}")
    if matter_id is not None:
        parts.append(f"matter_id={matter_id}")
    return ("?" + "&".join(parts)) if parts else ""


def _dispatch(
    tenant_id: str,
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    logger: Optional[DecisionLoggerProtocol] = None,
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """The single seam every wrapper passes through. KISS + DRY.

    If call()'s contract evolves, only this function changes.
    """
    return call(
        tenant_id=tenant_id, method=method, path=path, body=body,
        logger=logger, parent_decision_id=parent_decision_id,
    )


def _list_resource(
    tenant_id: str,
    resource: str,
    *,
    matter_id: Optional[str] = None,
    page: Optional[int] = None,
    limit: Optional[int] = None,
    logger: Optional[DecisionLoggerProtocol] = None,
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """Parametrised list-resource GET. Every list_* wrapper is one call here.

    ``resource`` is the URL path segment (``matters`` / ``contacts`` /
    ``activities`` / ``documents``). The matter_id filter is silently
    ignored for resources where Clio does not honour it (matters,
    contacts) — Clio simply ignores unknown query params, which keeps
    the helper signature uniform without leaking per-resource branches.
    """
    return _dispatch(
        tenant_id, "GET",
        f"/{resource}{_query(page=page, limit=limit, matter_id=matter_id)}",
        logger=logger, parent_decision_id=parent_decision_id,
    )


def _get_resource(
    tenant_id: str,
    resource: str,
    resource_id: str,
    *,
    logger: Optional[DecisionLoggerProtocol] = None,
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """Parametrised single-resource GET. Every get_* wrapper is one call here.

    ``resource`` is the collection path segment; ``resource_id`` is
    interpolated into the path per Clio's REST convention.
    """
    return _dispatch(
        tenant_id, "GET", f"/{resource}/{resource_id}",
        logger=logger, parent_decision_id=parent_decision_id,
    )


# ---------------------------------------------------------------------------
# Named entry points — one line each, no duplication
# ---------------------------------------------------------------------------


def list_matters(tenant_id: str, **kw) -> ClioResult:
    """GET ``/matters`` — list Clio matters. No IDR (council verdict #3)."""
    return _list_resource(tenant_id, "matters", **kw)


def get_matter(tenant_id: str, matter_id: str, **kw) -> ClioResult:
    """GET ``/matters/<id>`` — fetch a single matter. No IDR."""
    return _get_resource(tenant_id, "matters", matter_id, **kw)


def list_contacts(tenant_id: str, **kw) -> ClioResult:
    """GET ``/contacts`` — list Clio contacts. No IDR."""
    return _list_resource(tenant_id, "contacts", **kw)


def get_contact(tenant_id: str, contact_id: str, **kw) -> ClioResult:
    """GET ``/contacts/<id>`` — fetch a single contact. No IDR."""
    return _get_resource(tenant_id, "contacts", contact_id, **kw)


def list_activities(tenant_id: str, **kw) -> ClioResult:
    """GET ``/activities`` — optionally scoped to a matter. No IDR."""
    return _list_resource(tenant_id, "activities", **kw)


def list_documents(tenant_id: str, **kw) -> ClioResult:
    """GET ``/documents`` — optionally scoped to a matter. No IDR.

    Upload/download/delete deferred per YAGNI; first caller wanting
    them extracts the verbs in a follow-up PR.
    """
    return _list_resource(tenant_id, "documents", **kw)


# ---------------------------------------------------------------------------
# Time entries — the canonical mutation verb (one IDR per call)
# ---------------------------------------------------------------------------


def create_time_entry(
    tenant_id: str,
    *,
    matter_id: str,
    duration_minutes: int,
    description: str,
    activity_description_id: Optional[str] = None,
    logger: Optional[DecisionLoggerProtocol] = None,
    parent_decision_id: Optional[str] = None,
) -> ClioResult:
    """POST ``/time_entries`` — create a billable time entry.

    Mutation → one IDR emitted by ``call()`` automatically (council
    verdict #3). Clio's underlying field is ``quantity`` in SECONDS;
    we accept human-friendly ``duration_minutes`` and convert at the
    substrate seam (belongs here, not at every caller).
    """
    body: Dict[str, Any] = {
        "matter_id": matter_id,
        "quantity": int(duration_minutes) * 60,
        "description": description,
    }
    if activity_description_id is not None:
        body["activity_description_id"] = activity_description_id
    return _dispatch(
        tenant_id, "POST", "/time_entries", body=body,
        logger=logger, parent_decision_id=parent_decision_id,
    )


__all__ = [
    "create_time_entry",
    "get_contact",
    "get_matter",
    "list_activities",
    "list_contacts",
    "list_documents",
    "list_matters",
]
