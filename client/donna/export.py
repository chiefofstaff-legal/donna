"""Export time entries to Clio-compatible JSON and CSV. Pure stdlib."""

from __future__ import annotations

import csv
import io
import json
from typing import List

from donna.models import TimeEntry

# Clio time entry field mapping
# https://app.clio.com/api/v4/documentation#tag/TimeEntries
_CLIO_DATE_FMT = "%Y-%m-%d"


def _entry_to_clio(entry: TimeEntry) -> dict:
    """Map a TimeEntry to Clio time-entry shape."""
    return {
        "date": entry.created_at.strftime(_CLIO_DATE_FMT),
        "quantity": round((entry.duration_hours or 0.0) * 3600),  # seconds
        "note": entry.narrative or "",
        "matter": {"display_number": entry.matter or ""},
        "activity_description": {"name": entry.activity or ""},
    }


def to_clio_json(entries: List[TimeEntry]) -> str:
    """Return Clio bulk-import JSON string for the given entries."""
    payload = {"data": [_entry_to_clio(e) for e in entries]}
    return json.dumps(payload, indent=2)


_CSV_FIELDS = [
    "id", "date", "matter", "activity", "duration_hours", "narrative",
]


def _entry_to_csv_row(entry: TimeEntry) -> dict:
    return {
        "id": entry.id,
        "date": entry.created_at.strftime(_CLIO_DATE_FMT),
        "matter": entry.matter or "",
        "activity": entry.activity or "",
        "duration_hours": f"{entry.duration_hours or 0.0:.2f}",
        "narrative": entry.narrative or "",
    }


def to_csv(entries: List[TimeEntry]) -> str:
    """Return CSV string suitable for spreadsheet import."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow(_entry_to_csv_row(entry))
    return buf.getvalue()


def export_range(
    entries: List[TimeEntry],
    fmt: str = "json",
) -> str:
    """Dispatch to the requested format. fmt: 'json' | 'csv'."""
    dispatch = {"json": to_clio_json, "csv": to_csv}
    if fmt not in dispatch:
        raise ValueError(f"Unknown export format {fmt!r}. Choose 'json' or 'csv'.")
    return dispatch[fmt](entries)
