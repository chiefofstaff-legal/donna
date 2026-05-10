"""Tests for donna.confirmation — ConfirmationFormatter."""

from __future__ import annotations

import pytest

from donna.confirmation import ConfirmationFormatter
from donna.models import ClarifyRequest, IntentType, Task, TimeEntry


@pytest.fixture()
def fmt():
    return ConfirmationFormatter()


class TestFormatTimeEntry:
    def test_logged_prefix(self, fmt):
        entry = TimeEntry(matter="Smith", duration_hours=1.5, confidence=0.95)
        assert fmt.format(entry).startswith("Logged.")

    def test_hours_rendered(self, fmt):
        entry = TimeEntry(duration_hours=1.5, confidence=0.9)
        text = fmt.format(entry)
        assert "1 hour" in text
        assert "30 minute" in text

    def test_whole_hours(self, fmt):
        entry = TimeEntry(duration_hours=2.0, confidence=0.9)
        assert "2 hours" in fmt.format(entry)
        assert "minute" not in fmt.format(entry)

    def test_minutes_only(self, fmt):
        entry = TimeEntry(duration_hours=0.5, confidence=0.9)
        assert "30 minutes" in fmt.format(entry)

    def test_one_minute(self, fmt):
        entry = TimeEntry(duration_hours=1 / 60, confidence=0.9)
        assert "1 minute." in fmt.format(entry)

    def test_matter_included(self, fmt):
        entry = TimeEntry(matter="Smith motion", confidence=0.9)
        assert "Matter: Smith motion." in fmt.format(entry)

    def test_activity_included(self, fmt):
        entry = TimeEntry(activity="drafting", confidence=0.9)
        assert "Drafting." in fmt.format(entry)

    def test_narrative_included(self, fmt):
        entry = TimeEntry(narrative="Reviewed the deposition", confidence=0.9)
        assert "Reviewed the deposition." in fmt.format(entry)

    def test_confidence_high(self, fmt):
        entry = TimeEntry(confidence=0.95)
        assert "Confidence high." in fmt.format(entry)

    def test_confidence_good(self, fmt):
        entry = TimeEntry(confidence=0.8)
        assert "Confidence good." in fmt.format(entry)

    def test_confidence_low(self, fmt):
        entry = TimeEntry(confidence=0.6)
        assert "Low confidence" in fmt.format(entry)

    def test_very_low_confidence(self, fmt):
        entry = TimeEntry(confidence=0.3)
        assert "Very low confidence" in fmt.format(entry)

    def test_no_duration_no_duration_phrase(self, fmt):
        entry = TimeEntry(matter="Smith", confidence=0.9)
        text = fmt.format(entry)
        assert "hour" not in text
        assert "minute" not in text


class TestFormatTask:
    def test_task_delegated_prefix(self, fmt):
        task = Task(assignee="Mike", task="Draft the brief", confidence=0.9)
        assert fmt.format(task).startswith("Task delegated.")

    def test_assignee_included(self, fmt):
        task = Task(assignee="Mike", confidence=0.9)
        assert "Assigned to Mike." in fmt.format(task)

    def test_task_description_included(self, fmt):
        task = Task(task="Draft the response brief", confidence=0.9)
        assert "Draft the response brief." in fmt.format(task)

    def test_deadline_included(self, fmt):
        task = Task(deadline="Friday", confidence=0.9)
        assert "Due Friday." in fmt.format(task)

    def test_matter_included(self, fmt):
        task = Task(matter="Smith v Jones", confidence=0.9)
        assert "Matter: Smith v Jones." in fmt.format(task)


class TestFormatClarify:
    def test_time_entry_clarify(self, fmt):
        req = ClarifyRequest(
            intent_type=IntentType.TIME_ENTRY,
            question="How long did that take?",
            partial={},
        )
        text = fmt.format(req)
        assert "time entry" in text
        assert "How long did that take?" in text

    def test_delegation_clarify(self, fmt):
        req = ClarifyRequest(
            intent_type=IntentType.TASK_DELEGATION,
            question="Who should I assign this to?",
            partial={},
        )
        text = fmt.format(req)
        assert "delegation" in text
        assert "Who should I assign this to?" in text


class TestFormatUnknown:
    def test_unknown_type_returns_done(self, fmt):
        assert fmt.format("anything") == "Done."  # type: ignore[arg-type]
