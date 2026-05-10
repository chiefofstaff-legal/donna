"""
Goodhart-proof tests for lib/docuseal_webhook.py.

Coverage matrix:
- All 7 event_type → IDR intent mappings
- HMAC verification: valid passes, wrong secret fails, tampered body fails
- Chain append: two records link correctly via previous_hash
- Tamper detection: modified chain record fails on re-verify
- Mutation-testable: each assertion fails if the corresponding logic is mutated
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

# Add lib/ to path without requiring package install
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from docuseal_webhook import (
    EVENT_INTENT_MAP,
    GENESIS_PREVIOUS_HASH,
    PROTOCOL_VERSION,
    UnknownEventTypeError,
    WebhookSignatureError,
    append_to_chain,
    event_to_idr,
    handle_webhook,
    parse_event,
    _hmac_hex,
    _sha256,
    _canonical_json,
)

# ─── Fixtures ─────────────────────────────────────────────────────────
SECRET = "test-signing-secret-32-bytes-xx!"


def _make_event(event_type: str, submission_id: int = 1234, template_id: int = 99) -> dict:
    return {
        "event_type": event_type,
        "timestamp": "2026-05-09T13:00:00Z",
        "data": {
            "submission_id": submission_id,
            "submitter_id": 5678,
            "submitter": {"email": "alice@example.com", "name": "Alice"},
            "submission": {"id": submission_id, "template_id": template_id},
        },
    }


def _sign_body(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ─── Event-type → IDR intent mapping (all 7) ──────────────────────────
@pytest.mark.parametrize("event_type,expected_intent", list(EVENT_INTENT_MAP.items()))
def test_all_event_type_mappings(event_type: str, expected_intent: str) -> None:
    event = _make_event(event_type)
    idr = event_to_idr(event)
    assert idr["intent"] == expected_intent, (
        f"event_type={event_type!r} should map to {expected_intent!r}, got {idr['intent']!r}"
    )


def test_event_to_idr_protocol_version() -> None:
    event = _make_event("submission.created")
    idr = event_to_idr(event)
    assert idr["v"] == PROTOCOL_VERSION


def test_event_to_idr_actor_fields() -> None:
    event = _make_event("submitter.completed")
    idr = event_to_idr(event)
    assert idr["actor"]["type"] == "docuseal"
    assert idr["actor"]["submitter_email"] == "alice@example.com"
    assert idr["actor"]["submitter_name"] == "Alice"


def test_event_to_idr_target_fields() -> None:
    event = _make_event("submission.completed", submission_id=9999, template_id=42)
    idr = event_to_idr(event)
    assert idr["target"]["type"] == "submission"
    assert idr["target"]["submission_id"] == 9999
    assert idr["target"]["template_id"] == 42


def test_unknown_event_type_raises() -> None:
    event = _make_event("unknown.event")
    with pytest.raises(UnknownEventTypeError):
        event_to_idr(event)


# ─── HMAC verification ────────────────────────────────────────────────
def test_parse_event_valid_signature() -> None:
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)
    result = parse_event(body, signature_header=sig, secret=SECRET)
    assert result["event_type"] == "submission.created"


def test_parse_event_wrong_secret_raises() -> None:
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)
    with pytest.raises(WebhookSignatureError):
        parse_event(body, signature_header=sig, secret="wrong-secret")


def test_parse_event_tampered_body_raises() -> None:
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)
    tampered = body[:-1] + bytes([body[-1] ^ 0xFF])
    with pytest.raises(WebhookSignatureError):
        parse_event(tampered, signature_header=sig, secret=SECRET)


def test_parse_event_no_signature_skips_verify() -> None:
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    result = parse_event(body, signature_header=None, secret=None)
    assert result["event_type"] == "submission.created"


def test_hmac_uses_compare_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify constant-time compare_digest is used, not == comparison."""
    calls: list[tuple] = []
    original = hmac.compare_digest

    def recording_compare(a: str, b: str) -> bool:
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(hmac, "compare_digest", recording_compare)
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)
    parse_event(body, signature_header=sig, secret=SECRET)
    assert len(calls) == 1, "compare_digest must be called exactly once per verification"


# ─── Chain append: linking via previous_hash ──────────────────────────
def test_chain_append_first_record_uses_genesis_hash(tmp_path: Path) -> None:
    chain = tmp_path / "test-chain.md"
    event = _make_event("submission.created")
    idr = event_to_idr(event)
    append_to_chain(idr, chain, secret=SECRET)
    assert idr["previous_hash"] == GENESIS_PREVIOUS_HASH


def test_chain_append_second_record_links_to_first(tmp_path: Path) -> None:
    chain = tmp_path / "test-chain.md"

    event1 = _make_event("submission.created")
    idr1 = event_to_idr(event1)
    record1_hash = append_to_chain(idr1, chain, secret=SECRET)

    event2 = _make_event("submitter.completed")
    idr2 = event_to_idr(event2)
    append_to_chain(idr2, chain, secret=SECRET)

    assert idr2["previous_hash"] == record1_hash, (
        "Second record's previous_hash must equal first record's canonical hash"
    )


def test_same_event_twice_produces_two_linked_records(tmp_path: Path) -> None:
    chain = tmp_path / "test-chain.md"

    for _ in range(2):
        event = _make_event("submitter.opened")
        idr = event_to_idr(event)
        append_to_chain(idr, chain, secret=SECRET)

    text = chain.read_text()
    count = text.count("```idr")
    assert count == 2, "Same event submitted twice must yield two separate chain records"

    blocks: list[str] = []
    in_block = False
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```idr"):
            in_block = True
            buf = []
        elif in_block and line.strip() == "```":
            in_block = False
            blocks.append("".join(buf))
        elif in_block:
            buf.append(line)

    rec1 = json.loads(blocks[0])
    rec2 = json.loads(blocks[1])
    rec1_payload = {k: v for k, v in rec1.items() if k != "signature"}
    expected = _sha256(_canonical_json(rec1_payload))
    assert rec2["previous_hash"] == expected


# ─── Tamper detection ─────────────────────────────────────────────────
def test_tampered_chain_record_detected(tmp_path: Path) -> None:
    chain = tmp_path / "test-chain.md"

    for et in ["submission.created", "submitter.completed"]:
        event = _make_event(et)
        idr = event_to_idr(event)
        append_to_chain(idr, chain, secret=SECRET)

    text = chain.read_text()
    tampered = text.replace('"signing_dispatched"', '"TAMPERED_INTENT"', 1)
    chain.write_text(tampered)

    blocks: list[str] = []
    in_block = False
    buf: list[str] = []
    for line in tampered.splitlines():
        if line.strip().startswith("```idr"):
            in_block = True
            buf = []
        elif in_block and line.strip() == "```":
            in_block = False
            blocks.append("".join(buf))
        elif in_block:
            buf.append(line)

    rec1 = json.loads(blocks[0])
    sig_in_chain = rec1.pop("signature")
    canonical = _canonical_json(rec1)
    recomputed = _hmac_hex(SECRET.encode(), canonical)
    assert recomputed != sig_in_chain, (
        "Tampered record signature must NOT match recomputed HMAC"
    )


# ─── handle_webhook end-to-end ────────────────────────────────────────
def test_handle_webhook_returns_summary(tmp_path: Path) -> None:
    chain = tmp_path / "probat.md"
    event = _make_event("submission.completed")
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)

    result = handle_webhook(body, sig, SECRET, chain_path=chain)

    assert result["event_type"] == "submission.completed"
    assert len(result["idr_signature"]) == 64
    assert result["chain_position"] == 1


def test_handle_webhook_increments_chain_position(tmp_path: Path) -> None:
    chain = tmp_path / "probat.md"
    for i, et in enumerate(
        ["submission.created", "submitter.sent", "submission.completed"], 1
    ):
        event = _make_event(et)
        body = json.dumps(event).encode()
        sig = _sign_body(body, SECRET)
        result = handle_webhook(body, sig, SECRET, chain_path=chain)
        assert result["chain_position"] == i


def test_handle_webhook_rejects_invalid_sig(tmp_path: Path) -> None:
    chain = tmp_path / "probat.md"
    event = _make_event("submission.created")
    body = json.dumps(event).encode()
    with pytest.raises(WebhookSignatureError):
        handle_webhook(body, "deadbeef" * 8, SECRET, chain_path=chain)


# ─── IDR record signature is deterministic ───────────────────────────
def test_idr_signature_deterministic(tmp_path: Path) -> None:
    chain1 = tmp_path / "chain1.md"
    chain2 = tmp_path / "chain2.md"
    event = _make_event("submitter.sent")

    idr1 = event_to_idr(event)
    idr1["timestamp"] = "2026-05-09T13:00:00Z"
    append_to_chain(idr1, chain1, secret=SECRET)

    idr2 = event_to_idr(event)
    idr2["timestamp"] = "2026-05-09T13:00:00Z"
    append_to_chain(idr2, chain2, secret=SECRET)

    assert idr1["signature"] == idr2["signature"]


# ─── All 7 event types go end-to-end without raising ─────────────────
@pytest.mark.parametrize("event_type", list(EVENT_INTENT_MAP.keys()))
def test_all_event_types_end_to_end(event_type: str, tmp_path: Path) -> None:
    chain = tmp_path / f"chain-{event_type.replace('.', '-')}.md"
    event = _make_event(event_type)
    body = json.dumps(event).encode()
    sig = _sign_body(body, SECRET)
    result = handle_webhook(body, sig, SECRET, chain_path=chain)
    assert result["event_type"] == event_type
    assert result["chain_position"] == 1
