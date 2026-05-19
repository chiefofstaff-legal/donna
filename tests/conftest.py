"""
tests/conftest.py — shared pytest fixtures + collection-time setup.

The notarise audit-chain test suites (test_notarise.py,
test_notarise_mutations.py) load bin/notarise *in process* via a
SourceFileLoader so that:

  1. mutmut can mutate the file and have coverage trace map correctly
     (mutmut's `paths_to_mutate=bin/notarise.py` in setup.cfg), and
  2. the dataclass `__module__` resolves under the name "notarise".

That requires the source to be importable as `bin/notarise.py`. The
`.py` form is a *generated tracing artefact*, not a second source of
truth — it is gitignored on purpose (.gitignore line: `bin/notarise.py`)
so the canonical, executable `bin/notarise` stays the single source.

Without this hook the symlink only ever exists if someone created it by
hand, so the suite silently collected zero tests in CI (no CI job ran
the root suite either). This fixture makes the symlink self-heal at
collection time: deterministic, idempotent, no duplication across the
two test modules.
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CANONICAL = _REPO_ROOT / "bin" / "notarise"
_PY_ALIAS = _REPO_ROOT / "bin" / "notarise.py"


def _ensure_notarise_py_alias() -> None:
    """Create bin/notarise.py → notarise as a relative symlink (idempotent).

    Fail-closed: if the canonical source is missing, do nothing and let
    the test module's loader raise the real error (a fabricated empty
    alias would mask a genuinely broken tree — verify-canonical).
    """
    if not _CANONICAL.is_file():
        return
    if _PY_ALIAS.is_symlink() or _PY_ALIAS.exists():
        # Already present (symlink, or a real file from a prior mutmut run).
        # If it is a stale/broken symlink, replace it.
        if _PY_ALIAS.is_symlink() and not _PY_ALIAS.resolve().is_file():
            _PY_ALIAS.unlink()
        else:
            return
    try:
        # Relative target keeps the alias valid regardless of checkout path.
        _PY_ALIAS.symlink_to(Path("notarise"))
    except OSError:
        # Filesystems without symlink support (rare on CI Linux/macOS):
        # fall back to a hardlink, then a copy. Content stays identical.
        try:
            os.link(_CANONICAL, _PY_ALIAS)
        except OSError:
            _PY_ALIAS.write_bytes(_CANONICAL.read_bytes())


# Runs at conftest import — before test modules are collected, so the
# SourceFileLoader in test_notarise.py finds the alias.
_ensure_notarise_py_alias()
