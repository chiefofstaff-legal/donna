"""Domain models — pure dataclasses, no I/O."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IntentType(str, Enum):
    TIME_ENTRY = "time_entry"
    TASK_DELEGATION = "task_delegation"


class ParseError(ValueError):
    """Raised when a transcript cannot be parsed."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _CreatedAtDictMixin:
    """Shared ``to_dict`` for dataclasses carrying a ``created_at`` datetime.

    Extracted at the third occurrence (TimeEntry, Task, IngestedDocument) per
    the YSH principle — abstract a pattern once it is proven 3×. ``asdict``
    serialises the dataclass fields; only ``created_at`` needs ISO coercion.
    """

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class TimeEntry(_CreatedAtDictMixin):
    matter: Optional[str] = None
    duration_hours: Optional[float] = None
    activity: Optional[str] = None
    narrative: Optional[str] = None
    confidence: float = 0.0
    raw_transcript: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: _new_id("te"))


@dataclass
class Task(_CreatedAtDictMixin):
    assignee: Optional[str] = None
    task: Optional[str] = None
    deadline: Optional[str] = None
    matter: Optional[str] = None
    priority: str = "normal"
    confidence: float = 0.0
    raw_transcript: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: _new_id("tk"))


@dataclass
class IngestedDocument(_CreatedAtDictMixin):
    """A document parsed locally into text, with a provenance hash.

    Produced by ``donna.doc_ingest``. ``sha256`` is computed over the exact
    source bytes so a downstream IDR can notarise *which* document was ingested.
    """

    text: str = ""
    num_pages: int = 0
    sha256: str = ""
    ocr_used: bool = False
    source_kind: str = "bytes"
    created_at: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: _new_id("doc"))


@dataclass
class ParsedDelegation:
    assignee: Optional[str]
    task: Optional[str]
    deadline: Optional[str]
    matter: Optional[str]
    priority: str
    confidence: float


@dataclass
class ClarifyRequest:
    intent_type: IntentType
    question: str
    partial: dict

    def to_dict(self) -> dict:
        return {
            "intent_type": self.intent_type.value,
            "question": self.question,
            "partial": self.partial,
        }
