"""Goodhart-resistant tests for ``donna.secrets``.

Each test fails under exactly the 1-line mutation listed in its docstring
(per Rule 14 / mutation-anchored testing). The test name encodes the
production behaviour it asserts, not the mock setup.

Backend coverage:

* ``EnvVarStore`` — 3 tests (env-var read, normalisation, collision raise)
* ``KeychainStore`` — 2 tests (atomic ``-U`` flag, timeout fail-CLOSED)
* ``MemoryStore`` — 1 test (write/read round-trip)
* ``EncryptedFileStore`` — 3 tests (round-trip, atomic rename, fail-CLOSED on missing material)
* ``select_store()`` — 1 test (explicit env var overrides platform default)
* ``clio._kc_read`` legacy shim — 1 test (dispatcher regression anchor)

The EncryptedFileStore tests use ``cryptography.fernet.Fernet.generate_key()``
to produce a real Fernet material at test time; this keeps the test
isolated from any operator's deployed material.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from donna import secrets
from donna.secrets import (
    EncryptedFileStore,
    EnvVarCollisionError,
    EnvVarStore,
    KeychainStore,
    MemoryStore,
    select_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fernet_material() -> str:
    """A fresh Fernet material for each test — never reuse across cases."""
    return Fernet.generate_key().decode("ascii")


@pytest.fixture
def secrets_path(tmp_path: Path) -> Path:
    """Sibling tempfile path for EncryptedFileStore writes."""
    return tmp_path / "secrets.enc"


# ---------------------------------------------------------------------------
# EnvVarStore
# ---------------------------------------------------------------------------


def test_env_store_reads_from_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: replace ``os.environ.get(env_name)`` with literal ``""``."""
    monkeypatch.setenv("GRIP_CLIO_ACME", "ACCESS-XYZ")
    store = EnvVarStore()
    assert store.read("grip-clio-acme") == "ACCESS-XYZ"


def test_env_store_normalises_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: drop ``re.sub(r'[^A-Z0-9]', '_', ...)`` (e.g. literal pass-through).

    Service ``foo.bar-baz`` MUST normalise to env var ``FOO_BAR_BAZ`` —
    every non-alphanumeric becomes ``_``.
    """
    monkeypatch.setenv("FOO_BAR_BAZ", "ok")
    store = EnvVarStore()
    assert store.read("foo.bar-baz") == "ok"
    # And the original literal name does NOT resolve (proves normalisation fires).
    monkeypatch.delenv("FOO_BAR_BAZ", raising=False)
    monkeypatch.setenv("foo.bar-baz", "should-not-resolve")
    assert store.read("foo.bar-baz") is None


def test_env_store_raises_on_collision() -> None:
    """Kill mutation: drop the collision-detection raise (silent secret leak across identities)."""
    store = EnvVarStore()
    # First read for service "alpha-beta" → normalises to "ALPHA_BETA"
    store.read("alpha-beta")
    # Second read for service "alpha.beta" → same normalisation → MUST raise
    with pytest.raises(EnvVarCollisionError):
        store.read("alpha.beta")


# ---------------------------------------------------------------------------
# KeychainStore
# ---------------------------------------------------------------------------


def test_keychain_store_uses_atomic_replace_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: drop ``-U`` from KeychainStore.write subprocess args.

    The ``-U`` flag is the load-bearing atomic in-place update — without it,
    ``security add-generic-password`` errors on existing entries and OAuth
    refresh-token rotation silently fails to persist.
    """
    captured: List[List[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(argv)
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(secrets.shutil, "which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(secrets.subprocess, "run", fake_run)
    store = KeychainStore()
    assert store.write("grip-clio-acme", "NEW-TOKEN") is True
    # Exactly one subprocess invocation, and its argv MUST include "-U".
    assert len(captured) == 1
    assert "-U" in captured[0], f"-U flag missing from argv: {captured[0]!r}"


def test_keychain_store_fails_closed_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: silent-swallow timeout (return ``""`` instead of ``None``).

    A subprocess timeout MUST return ``None`` so callers branch into the
    fail-CLOSED degraded path. Returning ``""`` would let an empty token
    proceed as a valid config.
    """
    monkeypatch.setattr(secrets.shutil, "which", lambda _name: "/usr/bin/security")

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="security", timeout=5.0)

    monkeypatch.setattr(secrets.subprocess, "run", boom)
    assert KeychainStore().read("grip-clio-acme") is None


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------


def test_memory_store_write_then_read_roundtrip() -> None:
    """Kill mutation: drop value on write (``self._store[service] = ""``)."""
    store = MemoryStore()
    assert store.write("svc", "secret-value") is True
    assert store.read("svc") == "secret-value"


# ---------------------------------------------------------------------------
# EncryptedFileStore — scope-expansion suite (R0-1 fix)
# ---------------------------------------------------------------------------


def test_encrypted_file_store_round_trip(secrets_path: Path, fernet_material: str) -> None:
    """Kill mutation: drop value on encrypted write (write empty payload)."""
    store = EncryptedFileStore(path=secrets_path, material=fernet_material)
    assert store.write("svc-alpha", "value-alpha") is True
    assert store.write("svc-beta", "value-beta") is True

    # Fresh instance to prove persistence (not just in-memory dict).
    fresh = EncryptedFileStore(path=secrets_path, material=fernet_material)
    assert fresh.read("svc-alpha") == "value-alpha"
    assert fresh.read("svc-beta") == "value-beta"


def test_encrypted_file_store_atomic_replace_via_rename(
    secrets_path: Path, fernet_material: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutation: replace tempfile + ``os.rename`` with direct write.

    The atomic-replace invariant is that readers see either the old blob or
    the new — never a partially written file. Asserts ``os.rename`` is
    actually called with a ``.tmp`` source that lives in the same directory
    as the destination.
    """
    rename_calls: List[tuple] = []
    real_rename = os.rename

    def tracking_rename(src, dst):  # type: ignore[no-untyped-def]
        rename_calls.append((str(src), str(dst)))
        real_rename(src, dst)

    monkeypatch.setattr(secrets.os, "rename", tracking_rename)
    store = EncryptedFileStore(path=secrets_path, material=fernet_material)
    assert store.write("svc", "v") is True

    assert len(rename_calls) == 1, f"expected exactly one rename, got {rename_calls}"
    src, dst = rename_calls[0]
    # Source must be a sibling tempfile of the destination (same parent dir).
    assert Path(src).parent == Path(dst).parent
    assert ".tmp" in src or src.endswith(".tmp")
    assert dst == str(secrets_path)


def test_encrypted_file_store_fails_closed_on_missing_material(secrets_path: Path) -> None:
    """Kill mutation: silently default to a constant material when env var is unset.

    Without a configured encryption material the store MUST refuse to
    construct — a silent default would re-encrypt every operator's file with
    the same well-known token, destroying confidentiality.
    """
    # Make absolutely sure the env var isn't set in the test process.
    if secrets.ENV_SECRETS_MATERIAL in os.environ:
        del os.environ[secrets.ENV_SECRETS_MATERIAL]
    with pytest.raises(RuntimeError):
        EncryptedFileStore(path=secrets_path)


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


def test_selector_explicit_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: reverse precedence in ``select_store`` (platform default wins over env var).

    The env var MUST win unconditionally — operators on macOS who set
    ``DONNA_SECRET_STORE=memory`` for a test run cannot have their override
    silently downgraded to ``KeychainStore``.
    """
    monkeypatch.setenv(secrets.ENV_STORE_BACKEND, "memory")
    # Even with security CLI present (macOS dev box), memory must win.
    monkeypatch.setattr(secrets.shutil, "which", lambda _name: "/usr/bin/security")
    store = select_store()
    assert isinstance(store, MemoryStore)


# ---------------------------------------------------------------------------
# Legacy compat shim
# ---------------------------------------------------------------------------


def test_legacy_kc_read_shim_delegates_to_select_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutation: ``clio._kc_read`` short-circuits without calling ``select_store``.

    The dispatcher in ``donna.integrations.clio._kc_read`` MUST go through
    ``select_store()`` so the active backend's read path runs (and tests
    that set ``DONNA_SECRET_STORE`` see the expected backend).
    """
    from donna.integrations import clio

    seeded = MemoryStore(seed={"grip-clio-acme": "MEMORY-VALUE"})

    def fake_select() -> MemoryStore:
        return seeded

    monkeypatch.setattr(clio, "select_store", fake_select)
    assert clio._kc_read("grip-clio-acme") == "MEMORY-VALUE"
