"""Tests for classify_intent — heuristic intent classifier (no LLM)."""

from __future__ import annotations

import pytest

from donna.models import IntentType
from donna.router import classify_intent

TIME_ENTRY_CASES = [
    "Just spent 90 minutes on the Smith motion.",
    "About two hours reviewing contracts for Acme, the indemnity clauses.",
    "Quick call with the client, maybe 20 minutes.",
    "Three hours in court this morning.",
]

TASK_DELEGATION_CASES = [
    "Mike, draft the response brief by Friday.",
    "Ask the paralegal to file the Acme affidavit today, it's urgent.",
    "Someone needs to review the Smith discovery documents, not urgent.",
]


@pytest.mark.parametrize("transcript", TIME_ENTRY_CASES)
def test_classifies_first_person_with_duration_as_time_entry(transcript: str) -> None:
    assert classify_intent(transcript) is IntentType.TIME_ENTRY


@pytest.mark.parametrize("transcript", TASK_DELEGATION_CASES)
def test_classifies_addressee_or_third_party_request_as_delegation(transcript: str) -> None:
    assert classify_intent(transcript) is IntentType.TASK_DELEGATION


def test_empty_string_defaults_to_time_entry() -> None:
    assert classify_intent("") is IntentType.TIME_ENTRY


def test_whitespace_only_defaults_to_time_entry() -> None:
    assert classify_intent("   \n\t  ") is IntentType.TIME_ENTRY


def test_name_comma_prefix_routes_to_delegation() -> None:
    assert classify_intent("Sarah, please file this.") is IntentType.TASK_DELEGATION


def test_first_person_past_routes_to_time_entry() -> None:
    assert classify_intent("I finished the brief.") is IntentType.TIME_ENTRY
