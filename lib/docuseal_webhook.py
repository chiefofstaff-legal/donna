"""
DONNA · docuseal_webhook — DocuSeal webhook event → IDR chain adapter.

Stdlib only. No dependencies. Verifies HMAC-SHA256 webhook signatures,
maps DocuSeal event_type values to DONNA IDR intent strings, and appends
signed IDR records to PROBAT.md (or any chain file).

Public API:
    parse_event(raw_body, signature_header, secret) -> dict
    event_to_idr(event) -> dict
    append_to_chain(idr, chain_path) -> str
    handle_webhook(raw_body, signature_header, secret, chain_path) -> dict
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────
PROTOCOL_VERSION = "donna/idr/1"
GENESIS_PREVIOUS_HASH = "0" * 64
ENV_NOTARISE_KEY = "DONNA_NOTARISE_KEY"

# DocuSeal event_type → DONNA IDR intent
EVENT_INTENT_MAP: dict[str, str] = {
    "submission.created":   "signing_dispatched",
    "submitter.sent":       "signing_invitation_sent",
    "submitter.opened":     "signing_link_opened",
    "submitter.completed":  "signature_recorded",
    "submission.completed": "signing_finalised",
    "submission.declined":  "signing_declined",
    "submission.expired":   "signing_expired",
}

# Default chain path (relative to CWD; callers may pass an absolute Path)
DEFAULT_CHAIN_PATH = Path("PROBAT.md")


# ─── Exceptions ───────────────────────────────────────────────────────
class WebhookSignatureError(ValueError):
    """Raised when HMAC verification of an incoming webhook fails."""


class UnknownEventTypeError(KeyError):
    """Raised when the event_type is not in EVENT_INTENT_MAP."""


# ─── Internal helpers ─────────────────────────────────────────────────
def _notarise_key(secret: Optional[str]) -> bytes:
    raw = secret or os.environ.get(ENV_NOTARISE_KEY)
    if not raw:
        raise EnvironmentError(
            f"No signing key: pass secret= or set ${ENV_NOTARISE_KEY}"
        )
    return raw.encode("utf-8")


def _hmac_hex(key: bytes, body: bytes) -> str:
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _last_chain_hash(chain_path: Path) -> str:
    """Return the SHA-256 hash of the last IDR in chain_path, or GENESIS."""
    if not chain_path.exists():
        return GENESIS_PREVIOUS_HASH
    text = chain_path.read_text(encoding="utf-8")
    blocks: list[str] = []
    in_block = False
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```idr"):
            in_block = True
            buf = []
        elif in_block and line.strip().startswith("```"):
            in_block = False
            blocks.append("".join(buf))
        elif in_block:
            buf.append(line)
    if not blocks:
        return GENESIS_PREVIOUS_HASH
    last = json.loads(blocks[-1])
    # Re-derive hash of last record's canonical payload (signature excluded)
    last.pop("signature", None)
    return _sha256(_canonical_json(last))


# ─── Public API ───────────────────────────────────────────────────────
def parse_event(
    raw_body: bytes,
    signature_header: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict:
    """Parse a DocuSeal webhook payload, optionally verifying HMAC-SHA256.

    Args:
        raw_body: Raw request body bytes as received from DocuSeal.
        signature_header: Value of the X-Docuseal-Signature header (hex digest).
        secret: Webhook signing secret. Falls back to DONNA_NOTARISE_KEY env var.

    Returns:
        Parsed event dict.

    Raises:
        WebhookSignatureError: If signature_header is provided and verification fails.
        json.JSONDecodeError: If raw_body is not valid JSON.
    """
    if signature_header is not None:
        key = _notarise_key(secret)
        expected = _hmac_hex(key, raw_body)
        if not hmac.compare_digest(expected, signature_header.lower()):
            raise WebhookSignatureError(
                "DocuSeal webhook HMAC-SHA256 verification failed. "
                "Possible tampering or wrong secret."
            )
    return json.loads(raw_body)


def event_to_idr(event: dict) -> dict:
    """Convert a parsed DocuSeal event dict into a DONNA IDR record dict.

    The returned dict is unsigned (signature field is empty string).
    Call append_to_chain() to sign and persist it.

    Args:
        event: Parsed webhook payload from parse_event().

    Returns:
        IDR record dict with v, intent, actor, target, timestamp,
        previous_hash (GENESIS placeholder), signature (empty).

    Raises:
        UnknownEventTypeError: If event_type is not in EVENT_INTENT_MAP.
    """
    event_type = event.get("event_type", "")
    if event_type not in EVENT_INTENT_MAP:
        raise UnknownEventTypeError(
            f"Unknown DocuSeal event_type {event_type!r}. "
            f"Known types: {list(EVENT_INTENT_MAP)}"
        )

    data = event.get("data", {})
    submitter = data.get("submitter", {})
    submission = data.get("submission", {})

    return {
        "v": PROTOCOL_VERSION,
        "intent": EVENT_INTENT_MAP[event_type],
        "actor": {
            "type": "docuseal",
            "submitter_email": submitter.get("email", ""),
            "submitter_name": submitter.get("name", ""),
        },
        "target": {
            "type": "submission",
            "submission_id": data.get("submission_id") or submission.get("id"),
            "template_id": submission.get("template_id"),
        },
        "timestamp": event.get("timestamp") or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
        "previous_hash": GENESIS_PREVIOUS_HASH,  # overwritten by append_to_chain
        "signature": "",
    }


def append_to_chain(
    idr: dict,
    chain_path: Path = DEFAULT_CHAIN_PATH,
    secret: Optional[str] = None,
) -> str:
    """Sign idr, append it to chain_path, return the new record's hash.

    Args:
        idr: IDR dict from event_to_idr() (mutated in-place with previous_hash
             and signature before writing).
        chain_path: Path to the PROBAT.md chain file.
        secret: Signing secret. Falls back to DONNA_NOTARISE_KEY env var.

    Returns:
        SHA-256 hex digest of the newly appended IDR (usable as previous_hash
        for the next record).
    """
    key = _notarise_key(secret)
    idr["previous_hash"] = _last_chain_hash(chain_path)

    # Build canonical payload (everything except signature)
    payload_dict = {k: v for k, v in idr.items() if k != "signature"}
    canonical = _canonical_json(payload_dict)
    idr["signature"] = _hmac_hex(key, canonical)

    # Compute the record hash (SHA-256 of canonical payload, same as bin/notarise)
    record_hash = _sha256(canonical)

    # Append to chain file as a markdown fenced ```idr block
    chain_path = Path(chain_path)
    block = f"\n```idr\n{json.dumps(idr, indent=2, sort_keys=True)}\n```\n"
    with chain_path.open("a", encoding="utf-8") as fh:
        fh.write(block)

    return record_hash


def handle_webhook(
    raw_body: bytes,
    signature_header: Optional[str],
    secret: Optional[str],
    chain_path: Optional[Path] = None,
) -> dict:
    """End-to-end: parse → convert → append. Returns summary dict.

    Args:
        raw_body: Raw webhook request body.
        signature_header: X-Docuseal-Signature header value (or None to skip verify).
        secret: Signing/verification secret.
        chain_path: Chain file path (defaults to PROBAT.md in CWD).

    Returns:
        {"event_type": str, "idr_signature": str, "chain_position": int}

    Raises:
        WebhookSignatureError: On HMAC failure.
        UnknownEventTypeError: On unmapped event_type.
    """
    resolved_path = chain_path if chain_path is not None else DEFAULT_CHAIN_PATH
    event = parse_event(raw_body, signature_header, secret)
    idr = event_to_idr(event)
    record_hash = append_to_chain(idr, resolved_path, secret)

    # Count chain entries for chain_position
    chain_position = 1
    if resolved_path.exists():
        text = resolved_path.read_text(encoding="utf-8")
        chain_position = text.count("```idr")

    return {
        "event_type": event.get("event_type"),
        "idr_signature": idr["signature"],
        "chain_position": chain_position,
    }
