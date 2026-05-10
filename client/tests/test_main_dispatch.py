"""Direct tests for _serialise / _format dispatch dicts in main.py.

These tests provide a Goodhart guard for Wave 2's refactor: if someone removes
an entry from _SERIALISE_KIND or _FORMATTERS, these tests fail. Existing
integration tests (run_voice, run_pipe) wouldn't necessarily catch that.
"""
from __future__ import annotations

import pytest

from donna.models import ClarifyRequest, IntentType, Task, TimeEntry


class TestSerialiseDispatch:
    def test_time_entry_kind(self):
        from main import _serialise
        entry = TimeEntry(matter="Smith", duration_hours=1.5, confidence=0.9)
        result = _serialise(entry)
        assert result["kind"] == "timeentry"
        assert result["matter"] == "Smith"
        assert result["duration_hours"] == 1.5

    def test_task_kind(self):
        from main import _serialise
        task = Task(assignee="Mike", task="Draft brief", confidence=0.9)
        result = _serialise(task)
        assert result["kind"] == "task"
        assert result["assignee"] == "Mike"

    def test_clarify_request_kind(self):
        from main import _serialise
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="Which matter?",
            partial={"matter": None},
        )
        result = _serialise(req)
        assert result["kind"] == "clarify"
        assert result["intent_type"] == "time_entry"
        assert result["question"] == "Which matter?"
        assert result["partial"] == {"matter": None}

    def test_clarify_request_serialises_enum_to_value(self):
        """The IntentType enum must be serialised as its string value, not repr."""
        from main import _serialise
        req = ClarifyRequest(
            intent_type=IntentType.TASK_DELEGATION,
            question="Who?",
            partial={},
        )
        result = _serialise(req)
        # Must be the string "task_delegation", not "<IntentType.TASK_DELEGATION>"
        assert result["intent_type"] == "task_delegation"
        assert isinstance(result["intent_type"], str)

    def test_unknown_dataclass_falls_through_to_asdict(self):
        from dataclasses import dataclass

        from main import _serialise

        @dataclass
        class UnknownModel:
            value: int

        result = _serialise(UnknownModel(value=42))
        # Falls through to is_dataclass branch
        assert result == {"value": 42}

    def test_unknown_object_returns_kind_unknown(self):
        from main import _serialise
        result = _serialise(42)
        assert result == {"kind": "unknown", "value": "42"}

    def test_unknown_string(self):
        from main import _serialise
        result = _serialise("hello")
        assert result == {"kind": "unknown", "value": "hello"}


class TestFormatDispatch:
    def test_time_entry(self):
        from main import _format
        entry = TimeEntry(matter="Smith", duration_hours=1.5, confidence=0.9)
        out = _format(entry)
        assert out.startswith("TIME ENTRY")
        assert "matter=Smith" in out

    def test_task(self):
        from main import _format
        task = Task(assignee="Mike", task="Draft brief", confidence=0.9)
        out = _format(task)
        assert out.startswith("TASK")
        assert "assignee=Mike" in out

    def test_clarify_request(self):
        from main import _format
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="Which matter?",
            partial={},
        )
        out = _format(req)
        assert out.startswith("CLARIFY")
        assert "Which matter?" in out

    def test_unknown_object_returns_str(self):
        from main import _format
        assert _format(42) == "42"
        assert _format("hello") == "hello"


class TestClarifyRequestToDict:
    def test_intent_type_serialised_as_string(self):
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="Q?",
            partial={"k": "v"},
        )
        d = req.to_dict()
        assert d["intent_type"] == "time_entry"
        assert isinstance(d["intent_type"], str)

    def test_includes_question_and_partial(self):
        req = ClarifyRequest(
            intent_type=IntentType.TASK_DELEGATION,
            question="Who?",
            partial={"matter": "Smith"},
        )
        d = req.to_dict()
        assert d["question"] == "Who?"
        assert d["partial"] == {"matter": "Smith"}

    def test_returns_dict_not_dataclass(self):
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="?",
            partial={},
        )
        d = req.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {"intent_type", "question", "partial"}


class TestArgParser:
    def test_repl_default(self):
        from main import _build_arg_parser
        args = _build_arg_parser().parse_args([])
        assert not args.pipe
        assert not args.voice
        assert not args.history
        assert not args.export_today
        assert args.tts_enabled is True
        assert args.format == "csv"

    def test_pipe_flag(self):
        from main import _build_arg_parser
        args = _build_arg_parser().parse_args(["--pipe"])
        assert args.pipe is True

    def test_voice_flag(self):
        from main import _build_arg_parser
        args = _build_arg_parser().parse_args(["--voice"])
        assert args.voice is True

    def test_no_tts_disables_tts(self):
        from main import _build_arg_parser
        args = _build_arg_parser().parse_args(["--voice", "--no-tts"])
        assert args.voice is True
        assert args.tts_enabled is False

    def test_format_json(self):
        from main import _build_arg_parser
        args = _build_arg_parser().parse_args(["--export-today", "--format", "json"])
        assert args.export_today is True
        assert args.format == "json"

    def test_invalid_format_rejected(self):
        from main import _build_arg_parser
        with pytest.raises(SystemExit):
            _build_arg_parser().parse_args(["--format", "yaml"])

    def test_mutually_exclusive_modes(self):
        """Wave 1 side-effect: --history --export-today now errors cleanly."""
        from main import _build_arg_parser
        with pytest.raises(SystemExit):
            _build_arg_parser().parse_args(["--history", "--export-today"])
