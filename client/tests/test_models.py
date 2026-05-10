"""Tests for domain models — id generation, serialisation, error type."""

from __future__ import annotations

from datetime import datetime

from donna.models import ParseError, Task, TimeEntry


def test_time_entry_id_has_te_prefix() -> None:
    assert TimeEntry().id.startswith("te_")


def test_task_id_has_tk_prefix() -> None:
    assert Task().id.startswith("tk_")


def test_time_entry_ids_are_unique_across_instances() -> None:
    ids = {TimeEntry().id for _ in range(50)}
    assert len(ids) == 50


def test_task_ids_are_unique_across_instances() -> None:
    ids = {Task().id for _ in range(50)}
    assert len(ids) == 50


def test_time_entry_to_dict_serialises_created_at_as_iso_string() -> None:
    entry = TimeEntry()
    payload = entry.to_dict()
    assert isinstance(payload["created_at"], str)
    datetime.fromisoformat(payload["created_at"])


def test_task_to_dict_serialises_created_at_as_iso_string() -> None:
    task = Task()
    payload = task.to_dict()
    assert isinstance(payload["created_at"], str)
    datetime.fromisoformat(payload["created_at"])


def test_parse_error_is_value_error_subclass() -> None:
    assert issubclass(ParseError, ValueError)


def test_parse_error_can_be_raised_and_caught_as_value_error() -> None:
    try:
        raise ParseError("boom")
    except ValueError as exc:
        assert str(exc) == "boom"
