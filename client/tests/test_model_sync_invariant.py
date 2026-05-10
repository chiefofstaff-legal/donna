"""Sync-invariant tests for the model relationships my refactors depend on.

Wave 4 in PR #7 introduced `Task(**asdict(parsed), raw_transcript=transcript)`,
which silently assumes that every field on ParsedDelegation is also a field on
Task (and that `raw_transcript` is the only Task-only field that needs splicing).

If a future contributor adds a field to ParsedDelegation without adding it to
Task, the runtime crashes with TypeError. This module tests pin the invariant
explicitly so the failure mode surfaces in the test suite, not at the first
delegation a real user fires.
"""
from __future__ import annotations

from dataclasses import fields

from donna.models import ParsedDelegation, Task, TimeEntry


class TestParsedDelegationTaskSync:
    """Wave 4's asdict spread depends on this structural relationship."""

    def test_parsed_delegation_fields_are_subset_of_task_fields(self):
        parsed_fields = {f.name for f in fields(ParsedDelegation)}
        task_fields = {f.name for f in fields(Task)}
        leak = parsed_fields - task_fields
        assert not leak, (
            f"ParsedDelegation has fields {sorted(leak)} that Task does not. "
            f"This breaks router._handle_delegation's "
            f"`Task(**asdict(parsed), raw_transcript=transcript)` pattern."
        )

    def test_task_has_raw_transcript(self):
        """raw_transcript is the only field _handle_delegation splices in by hand."""
        task_fields = {f.name for f in fields(Task)}
        assert "raw_transcript" in task_fields

    def test_parsed_delegation_does_not_have_raw_transcript(self):
        """If ParsedDelegation gained raw_transcript, the splice would be redundant."""
        parsed_fields = {f.name for f in fields(ParsedDelegation)}
        assert "raw_transcript" not in parsed_fields, (
            "ParsedDelegation has raw_transcript — remove the splice in "
            "router._handle_delegation since asdict() already includes it."
        )


class TestTaskAndTimeEntryHaveToDict:
    """Wave 2's _SERIALISE_KIND dispatch dict assumes every registered type has to_dict."""

    def test_time_entry_has_to_dict(self):
        assert callable(getattr(TimeEntry(), "to_dict", None))

    def test_task_has_to_dict(self):
        assert callable(getattr(Task(), "to_dict", None))

    def test_clarify_request_has_to_dict(self):
        from donna.models import ClarifyRequest, IntentType
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="?", partial={},
        )
        assert callable(getattr(req, "to_dict", None))


class TestStoreSpecColumnsMatchModelFields:
    """Wave 3's _StoreSpec dict depends on column names matching model field names."""

    def test_time_entry_spec_columns_subset_of_model_fields(self):
        from donna.store import _TIME_ENTRY_SPEC
        model_fields = {f.name for f in fields(TimeEntry)}
        spec_cols = set(_TIME_ENTRY_SPEC.columns)
        leak = spec_cols - model_fields
        assert not leak, (
            f"_TIME_ENTRY_SPEC has columns {sorted(leak)} that TimeEntry does not. "
            f"_BaseStore._row_to_model would pass unknown kwargs to TimeEntry()."
        )

    def test_task_spec_columns_subset_of_model_fields(self):
        from donna.store import _TASK_SPEC
        model_fields = {f.name for f in fields(Task)}
        spec_cols = set(_TASK_SPEC.columns)
        leak = spec_cols - model_fields
        assert not leak, (
            f"_TASK_SPEC has columns {sorted(leak)} that Task does not."
        )

    def test_time_entry_spec_covers_required_columns(self):
        """The DDL writes id+created_at as NOT NULL; spec must include both."""
        from donna.store import _TIME_ENTRY_SPEC
        cols = set(_TIME_ENTRY_SPEC.columns)
        assert "id" in cols
        assert "created_at" in cols

    def test_task_spec_covers_required_columns(self):
        from donna.store import _TASK_SPEC
        cols = set(_TASK_SPEC.columns)
        assert "id" in cols
        assert "created_at" in cols
