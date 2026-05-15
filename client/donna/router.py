"""Route a transcript to the right extractor and persist the result."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Union

from donna.config import Config
from donna.extractor import Extractor
from donna.models import (
    ClarifyRequest,
    IntentType,
    ParseError,
    Task,
    TimeEntry,
)
from donna.pii_shield import LocalLLMEntityDetector, PiiSession
from donna.prompts import PromptLibrary
from donna.store import TaskStore, TimeEntryStore


def build_pii_session(config: Config) -> PiiSession | None:
    """Construct the default-on PII shield for the production path.

    Returns a PiiSession wired with the regex layer AND the local-inference
    detector unless the operator explicitly set DONNA_PII_SHIELD=0. The
    detector only ever talks to a local host (enforced in its constructor,
    fail-closed) — raw transcript never reaches a cloud provider.
    """
    if not config.pii_shield_enabled:
        return None
    detector = LocalLLMEntityDetector(
        base_url=config.pii_local_llm_base_url,
        model=config.pii_local_llm_model,
    )
    return PiiSession(detector=detector)


RouterResult = Union[TimeEntry, Task, ClarifyRequest]

_NAME_COMMA = re.compile(r"^[A-Z][a-z]{1,20},\s+", re.UNICODE)
_THIRD_PARTY_REQUEST = re.compile(
    r"\b(?:ask|tell|get|have|need|someone needs|the\s+\w+\s+(?:should|needs|to))\b",
    re.IGNORECASE,
)
_FIRST_PERSON_PAST = re.compile(
    r"\b(?:i|just|spent|did|finished|completed|was|been|had a)\b",
    re.IGNORECASE,
)
_DURATION_FRAGMENT = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:hour|hr|minute|min|h|m)s?|"
    r"an?\s+hour|half\s+an?\s+hour)\b",
    re.IGNORECASE,
)


def classify_intent(transcript: str) -> IntentType:
    """Heuristic intent classifier — runs before any LLM call.

    Delegation requires a second-person addressee (name + comma, or third-party
    request marker). Time-entry narration is first-person past-tense with a
    duration. Ambiguous cases fall through to time-entry — the LLM corrects.
    """
    text = transcript.strip()
    if not text:
        return IntentType.TIME_ENTRY
    if _NAME_COMMA.match(text):
        return IntentType.TASK_DELEGATION
    if _THIRD_PARTY_REQUEST.search(text):
        return IntentType.TASK_DELEGATION
    if _DURATION_FRAGMENT.search(text) or _FIRST_PERSON_PAST.search(text):
        return IntentType.TIME_ENTRY
    return IntentType.TIME_ENTRY


class Router:
    def __init__(
        self,
        config: Config,
        extractor: Extractor = None,
        time_store: TimeEntryStore = None,
        task_store: TaskStore = None,
        prompts: PromptLibrary = None,
    ):
        self._config = config
        self._prompts = prompts or PromptLibrary(config.prompt_dir)
        # PII Shield is wired DEFAULT-ON in the runtime path. A caller can
        # still inject its own extractor (tests do), but the production
        # construction always attaches the shield unless DONNA_PII_SHIELD=0.
        self._extractor = extractor or Extractor(
            config, self._prompts, pii_session=build_pii_session(config)
        )
        self._time_store = time_store or TimeEntryStore(config.cache_db)
        self._task_store = task_store or TaskStore(config.cache_db)

    def handle(self, transcript: str) -> RouterResult:
        clean = (transcript or "").strip()
        if not clean:
            raise ParseError("Transcript is empty.")
        intent = classify_intent(clean)
        if intent == IntentType.TASK_DELEGATION:
            return self._handle_delegation(clean)
        return self._handle_time_entry(clean)

    def _handle_time_entry(self, transcript: str) -> Union[TimeEntry, ClarifyRequest]:
        entry = self._extractor.extract_time_entry(transcript)
        if self._needs_clarification(entry.confidence, entry.matter):
            return self._make_clarify(
                IntentType.TIME_ENTRY, entry.to_dict(), entry.to_dict(),
            )
        self._time_store.add(entry)
        return entry

    def _handle_delegation(self, transcript: str) -> Union[Task, ClarifyRequest]:
        parsed = self._extractor.extract_delegation(transcript)
        if self._needs_clarification(parsed.confidence, parsed.assignee):
            return self._make_clarify(
                IntentType.TASK_DELEGATION,
                {"assignee": parsed.assignee, "task": parsed.task,
                 "matter": parsed.matter},
                asdict(parsed),
            )
        task = Task(**asdict(parsed), raw_transcript=transcript)
        self._task_store.add(task)
        return task

    def _make_clarify(
        self,
        intent_type: IntentType,
        clarify_input: dict,
        partial: dict,
    ) -> ClarifyRequest:
        """Build a ClarifyRequest by asking the extractor for a follow-up question."""
        question = self._extractor.clarify(clarify_input, intent_type.value)
        return ClarifyRequest(
            intent_type=intent_type, question=question, partial=partial,
        )

    def _needs_clarification(self, confidence: float, key_field) -> bool:
        return confidence < self._config.confidence_threshold or not key_field
