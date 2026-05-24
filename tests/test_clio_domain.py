"""Goodhart-resistant tests for ``donna.integrations.clio_domain``.

D2 deliverable. Verifies each wrapper invokes ``clio.call`` with the
correct method / path / body / kwargs, that pagination + matter-id
filters render into the URL correctly, and that IDR emission tracks
mutation status (POST/PATCH/PUT/DELETE → one IDR via call()'s gate,
GET → zero).

Each test's docstring names the 1-line mutation it kills (Rule 14).

Test strategy
-------------

Patch ``donna.integrations.clio_domain.call`` and assert on the
kwargs captured. The wrappers are thin — what we verify is the
*shape* of the dispatch (right method, right path, right body),
not the transport (covered by ``test_clio.py``).

Origin: 2026-05-24, V>> CBC Optimal sprint.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_CLIENT = Path(__file__).resolve().parent.parent / "client"
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))

from donna.integrations import clio_domain  # noqa: E402
from donna.integrations.clio import ClioResult, DecisionLoggerProtocol  # noqa: E402


@pytest.fixture
def captured() -> List[Dict[str, Any]]:
    """Storage for kwargs captured from patched ``call`` invocations."""
    return []


@pytest.fixture
def patched_call(captured: List[Dict[str, Any]]):
    """Replace ``clio_domain.call`` with a kwargs-capturing fake.

    Returns a ClioResult shaped per the council contract; wrappers
    propagate the result verbatim so wrapper correctness is proved by
    (a) what kwargs reached call(), (b) result round-tripped unchanged.
    """
    def _fake(**kwargs):
        captured.append(kwargs)
        method = kwargs.get("method", "").upper()
        is_mutation = method in {"POST", "PUT", "PATCH", "DELETE"}
        dec = "sha256:fake-001" if (is_mutation and kwargs.get("logger")) else None
        return ClioResult(ok=True, status=200, body={"echo": True}, decision_id=dec)

    with patch.object(clio_domain, "call", side_effect=_fake) as mock:
        yield mock


@pytest.fixture
def fake_logger() -> MagicMock:
    return MagicMock(spec=DecisionLoggerProtocol)


# ---------------------------------------------------------------------------
# list_matters
# ---------------------------------------------------------------------------


def test_list_matters_renders_no_query_when_unpaginated(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: always append ``?page=1`` even when unpaginated.

    A trailing ``?`` or default page=1 query would silently change
    Clio's response shape (limit defaults to 25, ordering differs);
    the unpaginated path MUST hit ``/matters`` cleanly.
    """
    clio_domain.list_matters("tenant-x")
    assert captured[0]["path"] == "/matters"
    assert captured[0]["method"] == "GET"


def test_list_matters_renders_pagination_into_query_string(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: drop pagination args from path; pass via body.

    Clio uses query params for pagination, not body. Putting page in
    the body would be silently ignored and pagination would never
    advance.
    """
    clio_domain.list_matters("tenant-x", page=3, limit=50)
    assert captured[0]["path"] == "/matters?page=3&limit=50"


def test_list_matters_passes_logger_through_for_dip(
    patched_call, captured: List[Dict[str, Any]], fake_logger: MagicMock
):
    """Kill mutation: drop the logger kwarg in the wrapper.

    Even on a GET (where call() won't emit an IDR), the wrapper MUST
    forward the logger — DIP contract: "we pass what you gave us";
    call() decides whether to use it.
    """
    clio_domain.list_matters("tenant-x", logger=fake_logger)
    assert captured[0]["logger"] is fake_logger


def test_list_matters_does_not_invoke_logger_on_get(
    patched_call, captured: List[Dict[str, Any]], fake_logger: MagicMock
):
    """Kill mutation: emit IDR from wrapper instead of relying on call().

    The wrapper MUST NOT call logger.log_decision itself — that would
    bypass council verdict #3 and double-emit IDRs on mutations.
    """
    clio_domain.list_matters("tenant-x", logger=fake_logger)
    assert fake_logger.log_decision.call_count == 0


# ---------------------------------------------------------------------------
# get_matter / get_contact — single-resource path interpolation
# ---------------------------------------------------------------------------


def test_get_matter_interpolates_matter_id_into_path(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: pass matter_id in query string instead of path.

    Clio's REST convention is path-segment for resource IDs. A query
    param would hit /matters (list endpoint) with a stray query arg,
    returning a list rather than the single resource.
    """
    clio_domain.get_matter("tenant-x", "M-42")
    assert captured[0]["path"] == "/matters/M-42"
    assert captured[0]["method"] == "GET"


def test_get_contact_interpolates_contact_id_into_path(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: hardcode contact_id (path collision regression)."""
    clio_domain.get_contact("tenant-x", "C-99")
    assert captured[0]["path"] == "/contacts/C-99"


# ---------------------------------------------------------------------------
# list_contacts — pagination round-trip
# ---------------------------------------------------------------------------


def test_list_contacts_renders_pagination(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: drop pagination — caller's page never advances."""
    clio_domain.list_contacts("tenant-x", page=2, limit=10)
    assert captured[0]["path"] == "/contacts?page=2&limit=10"


# ---------------------------------------------------------------------------
# list_activities — matter_id filter renders as query param
# ---------------------------------------------------------------------------


def test_list_activities_renders_matter_id_filter(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: drop matter_id from query (silent filter loss).

    Without the filter, the caller gets ALL activities across the
    tenant — a privacy/scope leak across matters. Clio expects
    ``matter_id`` as a query param.
    """
    clio_domain.list_activities("tenant-x", matter_id="M-1")
    assert "matter_id=M-1" in captured[0]["path"]


def test_list_activities_combines_matter_id_with_pagination(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: drop a separator; URL becomes malformed.

    A missing ``&`` between page and matter_id would silently collapse
    them into one mangled param Clio ignores.
    """
    clio_domain.list_activities("tenant-x", matter_id="M-2", page=1, limit=20)
    path = captured[0]["path"]
    assert "page=1" in path
    assert "limit=20" in path
    assert "matter_id=M-2" in path
    assert path.startswith("/activities?")
    assert path.count("&") == 2


def test_list_activities_without_filter_or_pagination(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: always emit a trailing ``?`` even when no filter."""
    clio_domain.list_activities("tenant-x")
    assert captured[0]["path"] == "/activities"


# ---------------------------------------------------------------------------
# create_time_entry — the canonical mutation verb
# ---------------------------------------------------------------------------


def test_create_time_entry_emits_one_idr_via_call(
    patched_call, captured: List[Dict[str, Any]], fake_logger: MagicMock
):
    """Kill mutation: change method from POST to GET (silent audit hole).

    Time-entry creation is the canonical mutation (Clio's billable
    moment). Changing to GET would bypass call()'s _is_mutation gate
    and drop the IDR — the audit-hole the council convened to close.
    """
    result = clio_domain.create_time_entry(
        "tenant-x",
        matter_id="M-1", duration_minutes=30, description="Drafted memo",
        logger=fake_logger,
    )
    assert captured[0]["method"] == "POST"
    assert captured[0]["path"] == "/time_entries"
    assert result.decision_id == "sha256:fake-001"


def test_create_time_entry_converts_minutes_to_clio_seconds(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: pass minutes directly to Clio's ``quantity`` field.

    Clio's quantity field is SECONDS. A 30-minute entry passed as
    ``quantity: 30`` would record as 30 seconds — a billing under-count
    of 60x. The conversion at the substrate seam is load-bearing.
    """
    clio_domain.create_time_entry(
        "tenant-x", matter_id="M-1", duration_minutes=30, description="X",
    )
    assert captured[0]["body"]["quantity"] == 30 * 60


def test_create_time_entry_omits_optional_activity_when_none(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: always include ``activity_description_id`` (as None).

    Clio rejects null activity_description_id as a schema violation.
    Omitting the field entirely when None is the correct shape.
    """
    clio_domain.create_time_entry(
        "tenant-x", matter_id="M-1", duration_minutes=15, description="X",
    )
    assert "activity_description_id" not in captured[0]["body"]


def test_create_time_entry_includes_optional_activity_when_provided(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: silently drop the optional activity field."""
    clio_domain.create_time_entry(
        "tenant-x", matter_id="M-1", duration_minutes=15, description="X",
        activity_description_id="ACT-42",
    )
    assert captured[0]["body"]["activity_description_id"] == "ACT-42"


def test_create_time_entry_threads_parent_decision_id(
    patched_call, captured: List[Dict[str, Any]], fake_logger: MagicMock
):
    """Kill mutation: drop parent_decision_id from the call() kwargs.

    Chain-forest replay depends on the parent_decision_id reaching the
    IDR context; dropping it severs the orchestrator → mutation link.
    """
    clio_domain.create_time_entry(
        "tenant-x", matter_id="M-1", duration_minutes=15, description="X",
        logger=fake_logger, parent_decision_id="sha256:parent",
    )
    assert captured[0]["parent_decision_id"] == "sha256:parent"


# ---------------------------------------------------------------------------
# list_documents — matter_id filter + pagination
# ---------------------------------------------------------------------------


def test_list_documents_renders_matter_id_filter(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: drop matter_id from query — privacy leak."""
    clio_domain.list_documents("tenant-x", matter_id="M-7")
    assert "matter_id=M-7" in captured[0]["path"]


def test_list_documents_without_filter(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: emit trailing ``?`` even with no filter."""
    clio_domain.list_documents("tenant-x")
    assert captured[0]["path"] == "/documents"


# ---------------------------------------------------------------------------
# DRY structural check — every wrapper goes through call() exactly once
# ---------------------------------------------------------------------------


def test_all_wrappers_invoke_call_exactly_once(
    patched_call, captured: List[Dict[str, Any]]
):
    """Kill mutation: inline HTTP in any wrapper.

    The DRY invariant: every wrapper's body is at most one call()
    invocation. A wrapper that doubled the call (e.g. retry logic) or
    skipped it (in-memory cache) would break the single-dispatch
    contract that gives us free IDR emission + 401 retry.
    """
    clio_domain.list_matters("t")
    clio_domain.get_matter("t", "M-1")
    clio_domain.list_contacts("t")
    clio_domain.get_contact("t", "C-1")
    clio_domain.list_activities("t")
    clio_domain.create_time_entry("t", matter_id="M-1", duration_minutes=1, description="x")
    clio_domain.list_documents("t")
    assert len(captured) == 7, (
        f"7 wrappers MUST invoke call() exactly 7 times; got {len(captured)} "
    )
    paths = [c["path"] for c in captured]
    assert len(set(paths)) == 7, f"each wrapper hits a distinct path; got {paths}"
