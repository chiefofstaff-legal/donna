"""Load system prompts from the voice-prompts library."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

PROMPT_PATHS = {
    "time_entry": "time-entry/extract.md",
    "task_delegation": "task-delegation/extract.md",
    "matter_unknown": "clarifying-questions/matter-unknown.md",
    "confirmation_time_entry": "confirmation/time-entry.md",
}

_FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.DOTALL)


def _extract_first_block(markdown: str) -> str:
    match = _FENCE.search(markdown)
    if not match:
        raise ValueError("no fenced block found in prompt file")
    return match.group(1).strip()


class PromptLibrary:
    def __init__(self, prompt_dir: Path):
        self._dir = prompt_dir
        self._cache: Dict[str, str] = {}

    def get(self, key: str) -> str:
        if key not in PROMPT_PATHS:
            raise KeyError(f"unknown prompt key: {key}")
        if key in self._cache:
            return self._cache[key]
        path = self._dir / PROMPT_PATHS[key]
        if not path.exists():
            raise FileNotFoundError(f"prompt missing: {path}")
        body = _extract_first_block(path.read_text(encoding="utf-8"))
        self._cache[key] = body
        return body
