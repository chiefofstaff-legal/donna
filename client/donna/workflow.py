"""Multi-party handoff IDR chain with tamper-evident hash linking.

Each handoff appends a record whose `record_hash` covers its own content
and `prev_hash` (the hash of the preceding record).  `Workflow.verify()`
walks the chain and recomputes every hash — any mutation is detected.

Usage::

    from donna.workflow import Workflow

    wf = Workflow(workflow_id="matter-123")
    r1 = wf.handoff("alice", "bob", {"action": "review", "matter": "Smith"})
    r2 = wf.handoff("bob", "carol", {"action": "sign", "matter": "Smith"})
    assert wf.verify()           # True — chain intact
    assert len(wf.chain()) == 2
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import donna.grasp_provenance as _grasp


_GENESIS = "genesis"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _canonical(seq: int, from_actor: str, to_actor: str,
               idr: dict, timestamp: str, prev_hash: str) -> str:
    """Deterministic JSON string covering all mutable fields."""
    return json.dumps(
        {
            "seq": seq,
            "from_actor": from_actor,
            "to_actor": to_actor,
            "idr": idr,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class HandoffRecord:
    seq: int
    from_actor: str
    to_actor: str
    idr: dict
    timestamp: str
    prev_hash: str
    record_hash: str


class Workflow:
    """Append-only multi-party handoff chain with hash-linked integrity."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self._chain: list[HandoffRecord] = []

    def handoff(self, from_actor: str, to_actor: str, idr: dict) -> HandoffRecord:
        """Append a handoff record and return it."""
        seq = len(self._chain)
        prev_hash = self._chain[-1].record_hash if self._chain else _GENESIS
        timestamp = _utcnow()
        raw = _canonical(seq, from_actor, to_actor, idr, timestamp, prev_hash)
        record = HandoffRecord(
            seq=seq,
            from_actor=from_actor,
            to_actor=to_actor,
            idr=idr,
            timestamp=timestamp,
            prev_hash=prev_hash,
            record_hash=_sha256(raw),
        )
        self._chain.append(record)
        _grasp.record_handoff_provenance({
            "seq": record.seq,
            "from_actor": record.from_actor,
            "to_actor": record.to_actor,
            "record_hash": record.record_hash,
            "timestamp": record.timestamp,
        })
        return record

    def chain(self) -> list[HandoffRecord]:
        """Return a shallow copy of the chain (caller cannot mutate internal state)."""
        return list(self._chain)

    def verify(self) -> bool:
        """Return True iff the hash chain is intact from genesis to head."""
        if not self._chain:
            return True
        expected_prev = _GENESIS
        for record in self._chain:
            if record.prev_hash != expected_prev:
                return False
            raw = _canonical(
                record.seq, record.from_actor, record.to_actor,
                record.idr, record.timestamp, record.prev_hash,
            )
            if _sha256(raw) != record.record_hash:
                return False
            expected_prev = record.record_hash
        return True
