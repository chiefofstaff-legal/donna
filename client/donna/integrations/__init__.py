"""DONNA integration adapters — one shim per external case-management substrate.

Each integration is a standalone module exposing a uniform contract:

* A ``Config`` dataclass for credentials + tenant scoping
* A ``Result`` dataclass carrying ``ok``, ``status``, ``body``, ``decision_id``
* A ``call()`` entry point that takes an optional ``DecisionLoggerProtocol``
  (dependency-inverted — DONNA OSS does not hard-depend on any specific
  logger implementation; downstream consumers inject theirs)
* Per-mutation IDR emission with ``context.parent_decision_id`` linking back
  to the orchestrator's routing decision (chain-forest semantics)

Council-ratified design — see ``project_donna_clio_adapter_council_synthesis_2026-05-20.md``.
"""

from donna.integrations.clio import (
    ClioConfig,
    ClioResult,
    DecisionLoggerProtocol,
    call,
    load_config,
)

__all__ = [
    "ClioConfig",
    "ClioResult",
    "DecisionLoggerProtocol",
    "call",
    "load_config",
]
