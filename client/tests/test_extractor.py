"""Tests for Extractor — JSON parsing and LLM client orchestration."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from donna.extractor import Extractor, _coerce_float, _safe_load, _strip_to_json
from donna.models import ParseError, ParsedDelegation, TimeEntry


def _fake_client(content: str) -> MagicMock:
    """Build a stub OpenAI client whose chat.completions.create returns content."""
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def test_extract_time_entry_parses_valid_json(config, prompt_lib) -> None:
    payload = {
        "matter": "Smith", "duration_hours": 1.5, "activity": "drafting",
        "narrative": "Drafting motion", "confidence": 0.85,
    }
    client = _fake_client(json.dumps(payload))
    extractor = Extractor(config, prompt_lib, client=client)
    result = extractor.extract_time_entry("90 minutes on Smith motion")
    assert isinstance(result, TimeEntry)
    assert result.matter == "Smith"
    assert result.duration_hours == 1.5
    assert result.confidence == 0.85
    assert result.raw_transcript == "90 minutes on Smith motion"


def test_extract_time_entry_raises_parse_error_on_non_json(config, prompt_lib) -> None:
    client = _fake_client("sorry, I can't help with that")
    extractor = Extractor(config, prompt_lib, client=client)
    with pytest.raises(ParseError):
        extractor.extract_time_entry("some transcript")


def test_extract_delegation_parses_valid_json(config, prompt_lib) -> None:
    payload = {
        "assignee": "Mike", "task": "Draft brief", "deadline": "Friday",
        "matter": None, "priority": "normal", "confidence": 0.95,
    }
    client = _fake_client(json.dumps(payload))
    extractor = Extractor(config, prompt_lib, client=client)
    result = extractor.extract_delegation("Mike, draft the brief by Friday")
    assert isinstance(result, ParsedDelegation)
    assert result.assignee == "Mike"
    assert result.task == "Draft brief"
    assert result.priority == "normal"
    assert result.confidence == 0.95


def test_strip_to_json_unwraps_markdown_fence_with_lang() -> None:
    raw = '```json\n{"matter": "Smith"}\n```'
    assert _strip_to_json(raw) == '{"matter": "Smith"}'


def test_strip_to_json_unwraps_markdown_fence_without_lang() -> None:
    raw = '```\n{"matter": "Smith"}\n```'
    assert _strip_to_json(raw) == '{"matter": "Smith"}'


def test_strip_to_json_handles_bare_object() -> None:
    raw = '{"matter": "Smith", "confidence": 0.9}'
    assert _strip_to_json(raw) == raw


def test_strip_to_json_extracts_object_from_surrounding_prose() -> None:
    raw = 'Sure, here is the result: {"matter": "Smith"} hope this helps.'
    assert _strip_to_json(raw) == '{"matter": "Smith"}'


# ---------------------------------------------------------------------------
# _coerce_float — LLM type-coercion at the boundary
# ---------------------------------------------------------------------------

class TestCoerceFloat:
    """LLMs may return numbers as numeric or string. Coercion must not crash."""

    def test_none_returns_none(self):
        assert _coerce_float(None) is None

    def test_float_passes_through(self):
        assert _coerce_float(1.5) == 1.5

    def test_int_coerces_to_float(self):
        assert _coerce_float(2) == 2.0
        assert isinstance(_coerce_float(2), float)

    def test_numeric_string_coerces(self):
        assert _coerce_float("1.5") == 1.5

    def test_empty_string_returns_none(self):
        assert _coerce_float("") is None

    def test_non_numeric_string_returns_none(self):
        assert _coerce_float("not a number") is None

    def test_dict_returns_none(self):
        assert _coerce_float({}) is None

    def test_list_returns_none(self):
        assert _coerce_float([1.5]) is None


# ---------------------------------------------------------------------------
# _safe_load — JSON loading via _strip_to_json with structured error
# ---------------------------------------------------------------------------

class TestSafeLoad:
    def test_valid_json(self):
        assert _safe_load('{"k": "v"}') == {"k": "v"}

    def test_fenced_json(self):
        assert _safe_load('```json\n{"k": 1}\n```') == {"k": 1}

    def test_non_json_raises_parse_error(self):
        with pytest.raises(ParseError, match="non-JSON"):
            _safe_load("hello world")

    def test_malformed_json_raises_parse_error(self):
        with pytest.raises(ParseError, match="non-JSON"):
            _safe_load('{"unclosed":')
