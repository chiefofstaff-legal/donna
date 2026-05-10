"""Tests for Router — orchestrates classify -> extract -> store / clarify."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from donna.models import (
    ClarifyRequest,
    IntentType,
    ParseError,
    ParsedDelegation,
    Task,
    TimeEntry,
)
from donna.router import Router
from donna.store import TaskStore, TimeEntryStore


def _build_router(config, prompt_lib, extractor: MagicMock) -> tuple[Router, TimeEntryStore, TaskStore]:
    time_store = TimeEntryStore(config.cache_db)
    task_store = TaskStore(config.cache_db)
    router = Router(
        config=config,
        extractor=extractor,
        time_store=time_store,
        task_store=task_store,
        prompts=prompt_lib,
    )
    return router, time_store, task_store


def test_handle_time_entry_stores_entry_and_returns_it(config, prompt_lib) -> None:
    extractor = MagicMock()
    extractor.extract_time_entry.return_value = TimeEntry(
        matter="Smith", duration_hours=1.5, activity="drafting", confidence=0.85,
    )
    router, time_store, _ = _build_router(config, prompt_lib, extractor)
    result = router.handle("Just spent 90 minutes on the Smith motion.")
    assert isinstance(result, TimeEntry)
    assert result.matter == "Smith"
    assert len(time_store.list()) == 1


def test_handle_delegation_stores_task_and_returns_it(config, prompt_lib) -> None:
    extractor = MagicMock()
    extractor.extract_delegation.return_value = ParsedDelegation(
        assignee="Mike", task="Draft brief", deadline="Friday",
        matter=None, priority="normal", confidence=0.95,
    )
    router, _, task_store = _build_router(config, prompt_lib, extractor)
    result = router.handle("Mike, draft the response brief by Friday.")
    assert isinstance(result, Task)
    assert result.assignee == "Mike"
    assert result.task == "Draft brief"
    assert len(task_store.list()) == 1


def test_handle_below_threshold_returns_clarify_and_does_not_store(config, prompt_lib) -> None:
    extractor = MagicMock()
    extractor.extract_time_entry.return_value = TimeEntry(
        matter=None, duration_hours=0.33, activity="call", confidence=0.4,
    )
    extractor.clarify.return_value = "Got the call — which matter?"
    router, time_store, _ = _build_router(config, prompt_lib, extractor)
    result = router.handle("Quick call with the client, maybe 20 minutes.")
    assert isinstance(result, ClarifyRequest)
    assert result.intent_type is IntentType.TIME_ENTRY
    assert result.question
    assert len(time_store.list()) == 0


def test_handle_delegation_without_assignee_returns_clarify(config, prompt_lib) -> None:
    extractor = MagicMock()
    extractor.extract_delegation.return_value = ParsedDelegation(
        assignee=None, task="Review documents", deadline=None,
        matter="Smith", priority="low", confidence=0.6,
    )
    extractor.clarify.return_value = "Who should handle the Smith review?"
    router, _, task_store = _build_router(config, prompt_lib, extractor)
    result = router.handle("Someone needs to review the Smith discovery documents, not urgent.")
    assert isinstance(result, ClarifyRequest)
    assert result.intent_type is IntentType.TASK_DELEGATION
    assert result.question
    assert len(task_store.list()) == 0


def test_handle_empty_transcript_raises_parse_error(config, prompt_lib) -> None:
    extractor = MagicMock()
    router, _, _ = _build_router(config, prompt_lib, extractor)
    with pytest.raises(ParseError):
        router.handle("")


def test_handle_whitespace_transcript_raises_parse_error(config, prompt_lib) -> None:
    extractor = MagicMock()
    router, _, _ = _build_router(config, prompt_lib, extractor)
    with pytest.raises(ParseError):
        router.handle("   \n\t  ")
