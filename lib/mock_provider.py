"""
lib/mock_provider.py — zero-cost AI provider mock for smoke testing.

When MOCK_PROVIDER=1 is set, any scenario that would call an LLM instead
returns a deterministic canned response without hitting any API endpoint.

Usage:
    from lib.mock_provider import maybe_mock, is_mock

    if is_mock():
        result = maybe_mock("route_intent", text="Ask Sarah to chase Arnold.")
    else:
        result = real_llm_call(...)

Public API:
    is_mock() -> bool
    maybe_mock(scenario: str, **kwargs) -> dict
"""
from __future__ import annotations
import os
from typing import Any

_CANNED: dict[str, dict[str, Any]] = {
    "route_intent": {
        "transcript": "Ask Sarah to chase the Arnold response by Friday.",
        "route": "team_member",
        "destination": "sarah@example.com",
        "confidence": 0.95,
    },
    "time_entry": {
        "matter": "Smith v. Jones",
        "matter_id": "SJ-2024-0341",
        "duration_minutes": 45,
        "activity": "Document review (discovery)",
        "confidence": 0.97,
    },
    "doc_ingest": {
        "document": "sample-contract.pdf",
        "chunks": 12,
        "confidence": 0.99,
    },
    "doc_query": {
        "answer": "The agreement may be terminated by either party with 30 days written notice (clause 14.2).",
        "sources": [{"file": "sample-contract.pdf", "chunk": 3}],
        "confidence": 0.93,
    },
    "matter_summary": {
        "summary": "The dispute centres on clause 14.2 of the 2024-01-15 services agreement.",
        "key_dates": ["2024-01-15", "2024-09-04"],
        "sources": 3,
        "confidence": 0.91,
    },
}


def is_mock() -> bool:
    """Return True when MOCK_PROVIDER=1 is set in the environment."""
    return os.environ.get("MOCK_PROVIDER", "0").strip() in ("1", "true", "yes")


def maybe_mock(scenario: str, **_kwargs: Any) -> dict[str, Any]:
    """Return canned response for *scenario*.

    Raises KeyError if the scenario name is unknown — that is intentional:
    an unknown scenario name is a harness bug, not a provider failure.
    """
    if scenario not in _CANNED:
        raise KeyError(
            f"No mock canned for scenario {scenario!r}. "
            f"Known: {list(_CANNED)}"
        )
    return dict(_CANNED[scenario])
