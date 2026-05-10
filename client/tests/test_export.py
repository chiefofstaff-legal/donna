"""Tests for export.py — Clio JSON and CSV output. No mocks needed."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from donna.export import export_range, to_clio_json, to_csv
from donna.models import TimeEntry


def _entry(
    matter: str = "Smith v Jones",
    hours: float = 1.5,
    activity: str = "drafting",
    narrative: str = "Drafted motion to dismiss",
    created_at: datetime | None = None,
) -> TimeEntry:
    return TimeEntry(
        matter=matter,
        duration_hours=hours,
        activity=activity,
        narrative=narrative,
        created_at=created_at or datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Clio JSON
# ---------------------------------------------------------------------------

def test_clio_json_structure(entry=None) -> None:
    e = _entry()
    result = json.loads(to_clio_json([e]))
    assert "data" in result
    assert len(result["data"]) == 1
    row = result["data"][0]
    assert row["date"] == "2024-05-01"
    assert row["quantity"] == round(1.5 * 3600)  # seconds
    assert row["note"] == "Drafted motion to dismiss"
    assert row["matter"]["display_number"] == "Smith v Jones"
    assert row["activity_description"]["name"] == "drafting"


def test_clio_json_multiple_entries() -> None:
    entries = [_entry(matter=f"Matter{i}", hours=float(i)) for i in range(1, 4)]
    result = json.loads(to_clio_json(entries))
    assert len(result["data"]) == 3
    assert result["data"][2]["matter"]["display_number"] == "Matter3"


def test_clio_json_empty_list() -> None:
    result = json.loads(to_clio_json([]))
    assert result == {"data": []}


def test_clio_json_null_fields_become_empty_strings() -> None:
    e = TimeEntry(
        matter=None,
        duration_hours=None,
        activity=None,
        narrative=None,
        created_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
    )
    result = json.loads(to_clio_json([e]))
    row = result["data"][0]
    assert row["note"] == ""
    assert row["matter"]["display_number"] == ""
    assert row["activity_description"]["name"] == ""
    assert row["quantity"] == 0


def test_clio_json_duration_converts_to_seconds() -> None:
    e = _entry(hours=0.25)
    result = json.loads(to_clio_json([e]))
    assert result["data"][0]["quantity"] == 900  # 0.25 * 3600


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_csv_has_header_row() -> None:
    output = to_csv([_entry()])
    reader = csv.DictReader(io.StringIO(output))
    assert set(reader.fieldnames or []) == {
        "id", "date", "matter", "activity", "duration_hours", "narrative"
    }


def test_csv_data_row_values() -> None:
    e = _entry()
    output = to_csv([e])
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 1
    assert rows[0]["matter"] == "Smith v Jones"
    assert rows[0]["date"] == "2024-05-01"
    assert rows[0]["duration_hours"] == "1.50"
    assert rows[0]["narrative"] == "Drafted motion to dismiss"
    assert rows[0]["id"] == e.id


def test_csv_multiple_entries() -> None:
    entries = [_entry(matter=f"M{i}", hours=float(i)) for i in range(1, 4)]
    output = to_csv(entries)
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 3
    assert rows[2]["matter"] == "M3"


def test_csv_empty_list_returns_header_only() -> None:
    output = to_csv([])
    lines = [l for l in output.strip().splitlines() if l]
    assert len(lines) == 1  # header only
    assert "matter" in lines[0]


# ---------------------------------------------------------------------------
# export_range dispatch
# ---------------------------------------------------------------------------

def test_export_range_json() -> None:
    output = export_range([_entry()], fmt="json")
    result = json.loads(output)
    assert "data" in result


def test_export_range_csv() -> None:
    output = export_range([_entry()], fmt="csv")
    assert "matter" in output  # has header


def test_export_range_invalid_format_raises() -> None:
    with pytest.raises(ValueError, match="Unknown export format"):
        export_range([_entry()], fmt="xml")
