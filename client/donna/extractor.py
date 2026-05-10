"""LLM-backed extraction of structured intent from free-form transcript."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from donna.config import Config
from donna.models import ParseError, ParsedDelegation, TimeEntry
from donna.pii_shield import PiiSession
from donna.prompts import PromptLibrary

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_BARE_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    text = raw.strip()
    fence = _FENCE_PATTERN.search(text)
    if fence:
        return fence.group(1).strip()
    bare = _BARE_OBJECT.search(text)
    if bare:
        return bare.group(0)
    return text


def _safe_load(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(_strip_to_json(raw))
    except json.JSONDecodeError as exc:
        raise ParseError(f"LLM returned non-JSON output: {exc}") from exc


class Extractor:
    """Calls the configured OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        config: Config,
        prompts: PromptLibrary,
        client: Optional[Any] = None,
        pii_session: Optional[PiiSession] = None,
    ):
        self._config = config
        self._prompts = prompts
        self._client = client or self._build_client()
        self._pii = pii_session

    def _build_client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed; run `pip install -r requirements.txt`"
            ) from exc
        return OpenAI(api_key=self._config.llm_api_key, base_url=self._config.llm_base_url)

    def _chat(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._config.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    def extract_time_entry(self, transcript: str) -> TimeEntry:
        system = self._prompts.get("time_entry")
        user, _ = self._pii.anonymize(transcript) if self._pii else (transcript, [])
        data = _safe_load(self._chat(system, user))
        # De-anonymize string fields so the stored entry contains real names.
        if self._pii:
            for key in ("matter", "narrative", "activity"):
                if isinstance(data.get(key), str):
                    data[key] = self._pii.deanonymize(data[key])
        return TimeEntry(
            matter=data.get("matter"),
            duration_hours=_coerce_float(data.get("duration_hours")),
            activity=data.get("activity"),
            narrative=data.get("narrative"),
            confidence=_coerce_float(data.get("confidence")) or 0.0,
            raw_transcript=transcript,
        )

    def extract_delegation(self, transcript: str) -> ParsedDelegation:
        from datetime import date as _date
        system = self._prompts.get("task_delegation")
        clean, _ = self._pii.anonymize(transcript) if self._pii else (transcript, [])
        # Voice-prompts spec requires today's date in the user message so the
        # model can resolve relative deadlines ("Friday", "today") correctly.
        user = f"{clean}\n\nToday's date: {_date.today().isoformat()}"
        data = _safe_load(self._chat(system, user))
        if self._pii:
            for key in ("assignee", "task", "matter"):
                if isinstance(data.get(key), str):
                    data[key] = self._pii.deanonymize(data[key])
        return ParsedDelegation(
            assignee=data.get("assignee"),
            task=data.get("task"),
            deadline=data.get("deadline"),
            matter=data.get("matter"),
            priority=str(data.get("priority") or "normal"),
            confidence=_coerce_float(data.get("confidence")) or 0.0,
        )

    def clarify(self, partial: dict, intent_label: str) -> str:
        system = self._prompts.get("matter_unknown")
        user = f"Intent: {intent_label}\nPartial JSON: {json.dumps(partial)}"
        return self._chat(system, user).strip()


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
