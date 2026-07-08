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
    """Inject a fake grasp package whose callables enforce the REAL grasp API
    signatures — a bridge regression to a fabricated call shape (e.g. the
    2026-07-08 ``build_idr(action=..., home=...)``) raises TypeError here and
    fails the suite instead of passing against a shape-agnostic mock."""
    from dataclasses import dataclass, field

    @dataclass
    class _FakeIDR:
        """Mirrors the fields of grasp.idr.PrecogIDR that the bridge touches."""
        id: str
        predecessor_idr: str | None
        depth: int
        fingerprint: str
        kind: str
        decision: dict
        prompt: str
        inputs: dict = field(default_factory=dict)

    def _build_idr(prompt, fingerprint, decision, predecessor_idr, depth,
                   *, kind="precog-decision", inputs=None, decision_anatomy=None):
        return _FakeIDR(id="precog-test-0001", predecessor_idr=predecessor_idr,
                        depth=depth, fingerprint=fingerprint, kind=kind,
                        decision=decision, prompt=prompt, inputs=inputs or {})

    def _checkpoint(next_step, summary="", *, title=None, tier="feedback",
                    paramount=False, records_idr=None, path=None,
                    head_pointer=None, model_versions=None):
        return None

    _idr = types.ModuleType("grasp.idr")
    _idr.build_idr = MagicMock(side_effect=_build_idr)
    _idr.append_idr = MagicMock(return_value=None)
    _idr.content_addr = MagicMock(return_value="sha256:addr-abc123")
    _idr.read_idr_chain = MagicMock(return_value=[])

    _ctx = types.ModuleType("grasp.context_chain")
    _ctx.checkpoint = MagicMock(side_effect=_checkpoint)

    _grasp = types.ModuleType("grasp")

    mods = {
        "grasp": _grasp,
        "grasp.idr": _idr,
        "grasp.context_chain": _ctx,
    }
    orig = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    import donna.grasp_provenance as _bridge
    _bridge._GRASP_AVAILABLE = True
    _bridge._idr = _idr
    _bridge._ctx = _ctx

    yield {"idr": _idr, "ctx": _ctx}

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
