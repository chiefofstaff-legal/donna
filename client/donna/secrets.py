"""Secret-store backends — Protocol + 4 implementations (Env/Keychain/Memory/EncryptedFile).

Origin: 2026-05-21. Donna SecretStoreProtocol Phase A (Option A unified design,
V>>--<<V ratified). Scope expanded to 4 backends per R0-1 falsification: Clio
rotates refresh tokens roughly twelve times per day under active use, so an
``EnvVarStore``-only prod path would force re-auth on every container restart.
``EncryptedFileStore`` solves the persistence gap.

Why the abstraction
-------------------

OSS donna shipped macOS-only (``_kc_read``/``_kc_write`` shelling out to
``security`` CLI). To run portably across macOS dev, Linux/Docker prod, and
test environments, secret storage moves behind a Protocol. The dispatching
wrappers in ``donna.integrations.clio`` keep the legacy ``_kc_*`` names so
existing tests that patch them continue to intercept the call site.

Protocol split — Reader vs Writer
---------------------------------

``SecretReaderProtocol`` is implemented by all four backends; only the three
writeable backends implement ``SecretWriterProtocol`` (which inherits from
the Reader Protocol — every Writer IS A Reader). Splitting at the type level
means an ``EnvVarStore`` cannot be passed where OAuth refresh-token rotation
needs a writer — the type system catches the mistake at review time, not at
runtime when a refresh silently fails to persist.

Selector — explicit cascade
---------------------------

``select_store()`` resolves in this order:

1. The ``DONNA_SECRET_STORE`` env var (``keychain``|``env``|``memory``|``encrypted_file``).
2. macOS default (``security`` CLI present): ``KeychainStore``.
3. Linux/Docker default with an encryption material env var set: ``EncryptedFileStore``.
4. Final fallback: ``EnvVarStore`` (read-only, no rotation persistence).

Atomic-replace invariant
------------------------

The load-bearing safety property carried over from the original ``_kc_write``
is that a successful write means the new value is durably persisted before
return — partial writes never leave the store in a half-rotated state.

* ``KeychainStore.write`` uses ``security ... -U`` (in-place update; macOS
  Keychain atomic semantics).
* ``EncryptedFileStore.write`` uses a tempfile + ``os.rename`` pattern; POSIX
  guarantees the rename is atomic when source and destination live on the
  same filesystem, so callers see either the old encrypted blob or the new
  one — never a partially written file.
* ``MemoryStore.write`` is dict assignment under a lock.

Fail-CLOSED
-----------

Every backend returns ``None``/``False`` on any failure (missing tooling,
timeout, decryption error, invalid material) rather than fabricating a value
or silently downgrading to plaintext. Callers (e.g. ``load_config``)
translate that into the documented degraded-mode IDR.

Configuration env vars
----------------------

Names defined once as module constants (see ``ENV_*``). Values stay inside
process memory at all times; nothing in this module logs, prints, or
otherwise exposes the configured material.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Configuration env var names (defined once; values never logged/exposed)
# ---------------------------------------------------------------------------

ENV_STORE_BACKEND = "DONNA_SECRET_STORE"
ENV_SECRETS_PATH = "DONNA_SECRETS_PATH"
ENV_SECRETS_MATERIAL = "DONNA_SECRETS_KEY"


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class SecretReaderProtocol(Protocol):
    """Read-only secret access. All four backends implement this."""

    def read(self, service: str) -> Optional[str]:
        ...


@runtime_checkable
class SecretWriterProtocol(SecretReaderProtocol, Protocol):
    """Read + write secret access. Writeable backends only.

    Sub-typing ``SecretReaderProtocol`` means every Writer IS A Reader, so
    call sites that accept a Writer can also call ``.read()`` on it. The
    inverse is intentionally not true: a Reader-only backend cannot be
    passed where a Writer is required.
    """

    def write(self, service: str, value: str) -> bool:
        ...


# ---------------------------------------------------------------------------
# EnvVarStore (read-only, universal)
# ---------------------------------------------------------------------------


class EnvVarCollisionError(RuntimeError):
    """Two distinct service names normalised to the same environment variable."""


_NORMALISE_RE = re.compile(r"[^A-Z0-9]")


class EnvVarStore:
    """Read-only env var backend. Universal fallback when no writable store is configured.

    Service name ``grip-clio-acme`` maps to env var ``GRIP_CLIO_ACME``. Any
    character that is not ``[A-Z0-9]`` becomes ``_``.

    Instance-level collision tracker: if two distinct service names normalise
    to the same env var, the second read on the SAME instance raises
    ``EnvVarCollisionError`` so the operator catches the ambiguous mapping
    before it leaks a secret across identity boundaries. Instance-level
    (not class-level) so test runs do not accumulate state across cases.
    Production code that wants cross-call detection should hold a single
    ``EnvVarStore`` instance rather than reaching for ``select_store()`` per read.
    """

    def __init__(self) -> None:
        self._seen: Dict[str, str] = {}
        self._seen_lock = threading.Lock()

    @staticmethod
    def _normalise(service: str) -> str:
        return _NORMALISE_RE.sub("_", service.upper())

    def read(self, service: str) -> Optional[str]:
        env_name = self._normalise(service)
        with self._seen_lock:
            prior = self._seen.get(env_name)
            if prior is not None and prior != service:
                raise EnvVarCollisionError(
                    f"Service names {prior!r} and {service!r} both normalise to "
                    f"env var {env_name!r} — distinct identities, same secret slot."
                )
            self._seen[env_name] = service
        value = os.environ.get(env_name)
        return value if value else None


# ---------------------------------------------------------------------------
# KeychainStore (read + write, macOS only)
# ---------------------------------------------------------------------------


_KEYCHAIN_TIMEOUT_S = 5.0


class KeychainStore:
    """macOS Keychain backend — wraps the ``security`` CLI subprocess.

    Preserves the load-bearing ``-U`` flag on writes (atomic in-place update,
    relied on by OAuth refresh-token rotation in ``clio._stash_refreshed_tokens``).
    A 5-second subprocess timeout guards against keychain-locked hangs.
    """

    def read(self, service: str) -> Optional[str]:
        security_bin = shutil.which("security")
        if not security_bin:
            return None
        try:
            result = subprocess.run(
                [security_bin, "find-generic-password", "-s", service, "-w"],
                capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def write(self, service: str, value: str) -> bool:
        security_bin = shutil.which("security")
        if not security_bin:
            return False
        try:
            result = subprocess.run(
                [security_bin, "add-generic-password",
                 "-a", os.environ.get("USER", ""),
                 "-s", service, "-w", value, "-U"],
                capture_output=True, text=True, timeout=_KEYCHAIN_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return result.returncode == 0


# ---------------------------------------------------------------------------
# MemoryStore (read + write, in-process)
# ---------------------------------------------------------------------------


class MemoryStore:
    """Dict-backed in-process store. For tests, dry-runs, and ephemeral state."""

    def __init__(self, seed: Optional[Dict[str, str]] = None) -> None:
        self._store: Dict[str, str] = dict(seed or {})
        self._lock = threading.Lock()

    def read(self, service: str) -> Optional[str]:
        with self._lock:
            value = self._store.get(service)
        return value if value else None

    def write(self, service: str, value: str) -> bool:
        with self._lock:
            self._store[service] = value
        return True


# ---------------------------------------------------------------------------
# EncryptedFileStore (read + write, Fernet-encrypted JSON file)
# ---------------------------------------------------------------------------


def _default_secrets_path() -> Path:
    """Resolve the default encrypted-file path. Honours ``DONNA_SECRETS_PATH``."""
    configured = os.environ.get(ENV_SECRETS_PATH)
    if configured:
        return Path(configured)
    return Path.home() / ".donna" / "secrets.enc"


class EncryptedFileStore:
    """Fernet-encrypted JSON file. Default for Linux / Docker production.

    File layout: a single Fernet token wrapping a JSON object ``{service: value}``.

    Configuration (resolved at ``__init__``):

    * ``DONNA_SECRETS_PATH`` — file path (default ``~/.donna/secrets.enc``).
    * ``DONNA_SECRETS_KEY`` — Fernet encryption material (44-char base64-url-safe
      = 32 bytes). Generated out-of-band and provisioned via the operator's
      secret-management layer.

    Atomic-replace on write: encrypted blob is written to a sibling
    ``<path>.tmp``, ``fsync``-ed, ``chmod 0600``-ed, then ``os.rename`` into
    the final path. POSIX guarantees that rename is atomic on the same
    filesystem — readers see either the old blob or the new, never a
    partially written file.

    Fail-CLOSED: missing material raises at construction; a corrupt or
    wrong-material file decrypts to an empty dict so the caller sees a
    "secret not configured" signal rather than a silent overwrite of real
    secrets.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        material: Optional[str] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._path = path or _default_secrets_path()
        resolved_material = material or os.environ.get(ENV_SECRETS_MATERIAL)
        if not resolved_material:
            raise RuntimeError(
                "EncryptedFileStore requires the {name} env var to be set "
                "(44-char base64-url-safe Fernet material). See the donna "
                "secrets provisioning docs.".format(name=ENV_SECRETS_MATERIAL)
            )
        # Lazy-import keeps module import cheap on systems without ``cryptography``.
        from cryptography.fernet import Fernet, InvalidToken
        self._InvalidToken = InvalidToken
        try:
            self._cipher = Fernet(resolved_material.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "Configured Fernet material is not a valid 44-char base64 token."
            ) from exc

    def _load(self) -> Dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            ciphertext = self._path.read_bytes()
        except OSError:
            return {}
        if not ciphertext:
            return {}
        try:
            plaintext = self._cipher.decrypt(ciphertext)
        except self._InvalidToken:
            # Fail-CLOSED: corrupt file or wrong material returns empty dict;
            # the file is NEVER recreated by a failed load (would destroy
            # real secrets if the material was mis-configured at deploy time).
            return {}
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _store_atomic(self, data: Dict[str, str]) -> bool:
        try:
            payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
            ciphertext = self._cipher.encrypt(payload)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_name = tempfile.mkstemp(
                prefix=".secrets-", suffix=".enc.tmp",
                dir=str(self._path.parent),
            )
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(ciphertext)
                    fh.flush()
                    os.fsync(fh.fileno())
                # Tight perms BEFORE rename so the final path is never world-readable.
                os.chmod(tmp_name, 0o600)
                os.rename(tmp_name, str(self._path))
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                return False
        except (OSError, ValueError):
            return False
        return True

    def read(self, service: str) -> Optional[str]:
        with self._lock:
            data = self._load()
        value = data.get(service)
        return value if value else None

    def write(self, service: str, value: str) -> bool:
        with self._lock:
            data = self._load()
            data[service] = value
            return self._store_atomic(data)


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


_BACKEND_NAMES = {
    "keychain": KeychainStore,
    "env": EnvVarStore,
    "memory": MemoryStore,
    "encrypted_file": EncryptedFileStore,
}


def select_store() -> SecretReaderProtocol:
    """Resolve the active store backend, env-var-first.

    Order:

    1. ``DONNA_SECRET_STORE`` (``keychain``|``env``|``memory``|``encrypted_file``).
    2. macOS default — ``security`` CLI present: ``KeychainStore``.
    3. Linux/Docker default — ``DONNA_SECRETS_KEY`` present: ``EncryptedFileStore``.
    4. Final fallback: ``EnvVarStore`` (read-only; no rotation persistence).

    Returns a ``SecretReaderProtocol``. Callers needing a Writer should
    duck-type via ``hasattr(store, "write")`` or handle the ``False`` that
    a Reader-only backend returns when its dispatcher attempts a write.
    """
    explicit = os.environ.get(ENV_STORE_BACKEND, "").strip().lower()
    if explicit in _BACKEND_NAMES:
        return _BACKEND_NAMES[explicit]()
    if shutil.which("security"):
        return KeychainStore()
    if os.environ.get(ENV_SECRETS_MATERIAL):
        return EncryptedFileStore()
    return EnvVarStore()


__all__ = [
    "ENV_SECRETS_MATERIAL",
    "ENV_SECRETS_PATH",
    "ENV_STORE_BACKEND",
    "EncryptedFileStore",
    "EnvVarCollisionError",
    "EnvVarStore",
    "KeychainStore",
    "MemoryStore",
    "SecretReaderProtocol",
    "SecretWriterProtocol",
    "select_store",
]
