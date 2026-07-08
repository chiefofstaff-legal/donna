"""Shared fixtures for the donna-legal client test suite."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from donna.config import Config
from donna.prompts import PromptLibrary


def pytest_configure(config):  # noqa: ANN001
    config.addinivalue_line("markers", "grasp: tests that exercise GRASP provenance integration")

VOICE_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "voice-prompts"


@pytest.fixture
def fake_grasp():
    """Inject a fake grasp package into sys.modules so bridge functions succeed."""
    _idr = types.ModuleType("grasp.idr")
    _idr.build_idr = MagicMock(return_value="idr-test-001")
    _idr.append_idr = MagicMock(return_value="idr-test-002")
    _idr.content_addr = MagicMock(return_value="addr-abc123")

    _ctx = types.ModuleType("grasp.context_chain")
    _ctx.checkpoint = MagicMock(return_value=None)

    _prov = types.ModuleType("grasp.provenance")
    _prov.record_proveit_provenance = MagicMock(return_value={"ok": True, "receipt": "r1"})

    _grasp = types.ModuleType("grasp")

    mods = {
        "grasp": _grasp,
        "grasp.idr": _idr,
        "grasp.context_chain": _ctx,
        "grasp.provenance": _prov,
    }
    orig = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    # Force bridge module to re-evaluate _GRASP_AVAILABLE with fake package present
    import importlib
    import donna.grasp_provenance as _bridge
    _bridge._GRASP_AVAILABLE = True
    _bridge._idr = _idr
    _bridge._ctx = _ctx
    _bridge._prov = _prov

    yield {"idr": _idr, "ctx": _ctx, "prov": _prov}

    for k, v in orig.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    _bridge._GRASP_AVAILABLE = False


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
