"""Tests for TimeEntryStore and TaskStore — real sqlite, no mocks."""

from __future__ import annotations

import time

from donna.models import Task, TimeEntry
from donna.store import TaskStore, TimeEntryStore


def test_time_entry_store_round_trip(tmp_db) -> None:
    store = TimeEntryStore(tmp_db)
    entry = TimeEntry(matter="Smith", duration_hours=1.5, activity="drafting", confidence=0.9)
    store.add(entry)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].id == entry.id
    assert rows[0].matter == "Smith"
    assert rows[0].duration_hours == 1.5
    assert rows[0].confidence == 0.9


def test_time_entry_store_lists_newest_first(tmp_db) -> None:
    store = TimeEntryStore(tmp_db)
    first = TimeEntry(matter="Acme")
    store.add(first)
    time.sleep(0.01)
    second = TimeEntry(matter="Smith")
    store.add(second)
    rows = store.list()
    assert [r.matter for r in rows] == ["Smith", "Acme"]


def test_task_store_round_trip(tmp_db) -> None:
    store = TaskStore(tmp_db)
    task = Task(assignee="Mike", task="Draft brief", priority="urgent", confidence=0.95)
    store.add(task)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].id == task.id
    assert rows[0].assignee == "Mike"
    assert rows[0].priority == "urgent"


def test_time_entry_store_lazy_initialises_schema(tmp_db) -> None:
    assert not tmp_db.exists()
    store = TimeEntryStore(tmp_db)
    assert store.list() == []
    assert tmp_db.exists()


def test_task_store_lazy_initialises_schema(tmp_db) -> None:
    assert not tmp_db.exists()
    store = TaskStore(tmp_db)
    assert store.list() == []
    assert tmp_db.exists()


def test_both_stores_share_one_database_file(tmp_db) -> None:
    time_store = TimeEntryStore(tmp_db)
    task_store = TaskStore(tmp_db)
    time_store.add(TimeEntry(matter="Smith"))
    task_store.add(Task(assignee="Mike"))
    assert len(time_store.list()) == 1
    assert len(task_store.list()) == 1


# ---------------------------------------------------------------------------
# query() — date-range filtering
# ---------------------------------------------------------------------------

def test_query_returns_entries_in_range(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    jan = TimeEntry(matter="Jan", duration_hours=1.0,
                    created_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc))
    feb = TimeEntry(matter="Feb", duration_hours=2.0,
                    created_at=datetime(2024, 2, 15, 10, 0, tzinfo=timezone.utc))
    mar = TimeEntry(matter="Mar", duration_hours=0.5,
                    created_at=datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc))
    for e in (jan, feb, mar):
        store.add(e)

    results = store.query(
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 28, tzinfo=timezone.utc),
    )
    assert [r.matter for r in results] == ["Jan", "Feb"]


def test_query_excludes_entries_outside_range(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    store.add(TimeEntry(matter="Old",
                        created_at=datetime(2023, 12, 1, tzinfo=timezone.utc)))
    store.add(TimeEntry(matter="New",
                        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc)))

    results = store.query(
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 12, 31, tzinfo=timezone.utc),
    )
    assert len(results) == 1
    assert results[0].matter == "New"


def test_query_empty_range_returns_nothing(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    store.add(TimeEntry(matter="Smith",
                        created_at=datetime(2024, 3, 1, tzinfo=timezone.utc)))

    results = store.query(
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 12, 31, tzinfo=timezone.utc),
    )
    assert results == []


# ---------------------------------------------------------------------------
# daily_summary()
# ---------------------------------------------------------------------------

def test_daily_summary_no_entries(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    summary = store.daily_summary(datetime(2024, 5, 1, tzinfo=timezone.utc))
    assert summary == "No time logged today."


def test_daily_summary_single_matter(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    store.add(TimeEntry(matter="Smith", duration_hours=2.5,
                        created_at=datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)))
    store.add(TimeEntry(matter="Smith", duration_hours=1.0,
                        created_at=datetime(2024, 5, 1, 14, 0, tzinfo=timezone.utc)))

    summary = store.daily_summary(datetime(2024, 5, 1, tzinfo=timezone.utc))
    assert "3.5 hours" in summary
    assert "1 matter" in summary


def test_daily_summary_multiple_matters(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    store.add(TimeEntry(matter="Smith", duration_hours=1.0,
                        created_at=datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)))
    store.add(TimeEntry(matter="Acme", duration_hours=1.0,
                        created_at=datetime(2024, 5, 1, 11, 0, tzinfo=timezone.utc)))
    store.add(TimeEntry(matter="Jones", duration_hours=0.5,
                        created_at=datetime(2024, 5, 1, 15, 0, tzinfo=timezone.utc)))

    summary = store.daily_summary(datetime(2024, 5, 1, tzinfo=timezone.utc))
    assert "2.5 hours" in summary
    assert "3 matters" in summary


def test_daily_summary_excludes_other_days(tmp_db) -> None:
    from datetime import datetime, timezone
    store = TimeEntryStore(tmp_db)
    store.add(TimeEntry(matter="Yesterday", duration_hours=5.0,
                        created_at=datetime(2024, 4, 30, 10, 0, tzinfo=timezone.utc)))
    store.add(TimeEntry(matter="Today", duration_hours=1.0,
                        created_at=datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)))

    summary = store.daily_summary(datetime(2024, 5, 1, tzinfo=timezone.utc))
    assert "1.0 hours" in summary
    assert "1 matter" in summary
