"""Configuration loaded from environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

API_KEY_VAR = "LLM_" + "API" + "_KEY"
BASE_URL_VAR = "LLM_BASE_URL"
MODEL_VAR = "LLM_MODEL"
RUNTIME_VAR = "DONNA_RUNTIME_URL"
PROMPT_DIR_VAR = "PROMPT_DIR"
THRESHOLD_VAR = "CONFIDENCE_THRESHOLD"
CACHE_DB_VAR = "CACHE_DB"

# v0.2 voice config env vars
OPENAI_KEY_VAR = "OPENAI_API_KEY"
SAMPLE_RATE_VAR = "DONNA_SAMPLE_RATE"
VAD_AGGRESSIVENESS_VAR = "DONNA_VAD_AGGRESSIVENESS"
STT_BACKEND_VAR = "DONNA_STT_BACKEND"

# v0.6 webhook env var
WEBHOOK_URL_VAR = "DONNA_WEBHOOK_URL"


def _default_prompt_dir() -> Path:
    return (Path(__file__).resolve().parent.parent.parent / "voice-prompts").resolve()


def _default_cache_db() -> Path:
    return Path.home() / ".donna" / "cache.db"


@dataclass
class Config:
    llm_api_key: str
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    runtime_url: Optional[str] = None
    prompt_dir: Path = field(default_factory=_default_prompt_dir)
    confidence_threshold: float = 0.7
    cache_db: Path = field(default_factory=_default_cache_db)
    # v0.2 voice fields
    openai_api_key: str = ""          # falls back to llm_api_key when empty
    sample_rate: int = 16000
    vad_aggressiveness: int = 2
    stt_backend: str = "api"
    # v0.6 webhook
    webhook_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.openai_api_key:
            self.openai_api_key = self.llm_api_key


# Alias so voice_pipeline.py can import DonnaConfig without breaking Config users.
DonnaConfig = Config


def _env_path(name: str, default_factory) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default_factory()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def load_config() -> Config:
    api_key = os.environ.get(API_KEY_VAR, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{API_KEY_VAR} is required. Copy .env.example to .env and set it."
        )
    openai_key = os.environ.get(OPENAI_KEY_VAR, "").strip() or api_key
    return Config(
        llm_api_key=api_key,
        llm_base_url=os.environ.get(BASE_URL_VAR, "").strip() or "https://api.openai.com/v1",
        llm_model=os.environ.get(MODEL_VAR, "").strip() or "gpt-4o-mini",
        runtime_url=os.environ.get(RUNTIME_VAR, "").strip() or None,
        prompt_dir=_env_path(PROMPT_DIR_VAR, _default_prompt_dir),
        confidence_threshold=_env_float(THRESHOLD_VAR, 0.7),
        cache_db=_env_path(CACHE_DB_VAR, _default_cache_db),
        openai_api_key=openai_key,
        sample_rate=_env_int(SAMPLE_RATE_VAR, 16000),
        vad_aggressiveness=_env_int(VAD_AGGRESSIVENESS_VAR, 2),
        stt_backend=os.environ.get(STT_BACKEND_VAR, "api").strip() or "api",
        webhook_url=os.environ.get(WEBHOOK_URL_VAR, "").strip() or None,
    )
