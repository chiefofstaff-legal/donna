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


@dataclass
class TimeEntry:
    matter: Optional[str] = None
    duration_hours: Optional[float] = None
    activity: Optional[str] = None
    narrative: Optional[str] = None
    confidence: float = 0.0
    raw_transcript: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: _new_id("te"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class Task:
    assignee: Optional[str] = None
    task: Optional[str] = None
    deadline: Optional[str] = None
    matter: Optional[str] = None
    priority: str = "normal"
    confidence: float = 0.0
    raw_transcript: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    id: str = field(default_factory=lambda: _new_id("tk"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


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
