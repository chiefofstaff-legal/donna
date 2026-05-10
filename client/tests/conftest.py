"""Shared fixtures for the donna-legal client test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from donna.config import Config
from donna.prompts import PromptLibrary

VOICE_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "voice-prompts"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "donna-test.db"


@pytest.fixture
def config(tmp_db: Path) -> Config:
    return Config(
        llm_api_key="test-key",
        llm_base_url="http://localhost:9999",
        confidence_threshold=0.7,
        cache_db=tmp_db,
        prompt_dir=VOICE_PROMPTS_DIR,
    )


@pytest.fixture
def prompt_lib(config: Config) -> PromptLibrary:
    return PromptLibrary(config.prompt_dir)
