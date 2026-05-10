"""SQLite persistence for time entries and tasks. Pure stdlib."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, List, Type, TypeVar

from donna.models import Task, TimeEntry

_TIME_ENTRY_DDL = """
CREATE TABLE IF NOT EXISTS time_entries (
    id TEXT PRIMARY KEY,
    matter TEXT,
    duration_hours REAL,
    activity TEXT,
    narrative TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    raw_transcript TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_TASK_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    assignee TEXT,
    task TEXT,
    deadline TEXT,
    matter TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    confidence REAL NOT NULL DEFAULT 0,
    raw_transcript TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


T = TypeVar("T")


@dataclass(frozen=True)
class _StoreSpec(Generic[T]):
    """Per-table metadata: model class, table name, column order, schema DDL."""
    table: str
    columns: tuple[str, ...]
    ddl: str
    model_cls: Type[T]


_TIME_ENTRY_SPEC: _StoreSpec[TimeEntry] = _StoreSpec(
    table="time_entries",
    columns=("id", "matter", "duration_hours", "activity", "narrative",
             "confidence", "raw_transcript", "created_at"),
    ddl=_TIME_ENTRY_DDL,
    model_cls=TimeEntry,
)

_TASK_SPEC: _StoreSpec[Task] = _StoreSpec(
    table="tasks",
    columns=("id", "assignee", "task", "deadline", "matter",
             "priority", "confidence", "raw_transcript", "created_at"),
    ddl=_TASK_DDL,
    model_cls=Task,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _field_to_db(model: Any, col: str) -> Any:
    """Convert a model attribute to its DB-storable form (datetime → ISO string)."""
    val = getattr(model, col)
    return val.isoformat() if isinstance(val, datetime) else val


class _BaseStore(Generic[T]):
    """Generic single-table store. Subclasses set _SPEC."""
    _SPEC: _StoreSpec[T]

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._initialised = False

    def _ensure_init(self) -> None:
        if self._initialised:
            return
        with _connect(self._db_path) as conn:
            conn.execute(self._SPEC.ddl)
        self._initialised = True

    def _conn(self) -> sqlite3.Connection:
        self._ensure_init()
        return _connect(self._db_path)

    def _row_to_model(self, row: sqlite3.Row) -> T:
        kwargs = {col: row[col] for col in self._SPEC.columns}
        if kwargs.get("created_at"):
            kwargs["created_at"] = datetime.fromisoformat(kwargs["created_at"])
        return self._SPEC.model_cls(**kwargs)

    def add(self, model: T) -> T:
        cols = self._SPEC.columns
        placeholders = ", ".join("?" * len(cols))
        values = tuple(_field_to_db(model, col) for col in cols)
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO {self._SPEC.table} ({', '.join(cols)})"
                f" VALUES ({placeholders})",
                values,
            )
        return model

    def list(self, limit: int = 50) -> List[T]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._SPEC.table}"
                f" ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_model(r) for r in rows]


class TimeEntryStore(_BaseStore[TimeEntry]):
    _SPEC = _TIME_ENTRY_SPEC

    def query(self, date_from: datetime, date_to: datetime) -> List[TimeEntry]:
        """Return entries whose created_at falls within [date_from, date_to]."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._SPEC.table}"
                f" WHERE created_at >= ? AND created_at <= ?"
                f" ORDER BY created_at ASC",
                (date_from.isoformat(), date_to.isoformat()),
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def daily_summary(self, date: datetime | None = None) -> str:
        """Human-readable summary: 'You've logged N hours across M matters today.'"""
        if date is None:
            date = datetime.now()
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        entries = self.query(day_start, day_end)
        if not entries:
            return "No time logged today."
        total_hours = sum(e.duration_hours or 0.0 for e in entries)
        matters = {e.matter for e in entries if e.matter}
        matter_str = "1 matter" if len(matters) == 1 else f"{len(matters)} matters"
        return f"You've logged {total_hours:.1f} hours across {matter_str} today."


class TaskStore(_BaseStore[Task]):
    _SPEC = _TASK_SPEC
