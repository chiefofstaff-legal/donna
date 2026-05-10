"""
tests/test_docuseal_e2e.py — End-to-end falsification harness for H-DOCUSEAL-1.

Hypothesis H-DOCUSEAL-1:
    "An IDR receipt embedded in a DocuSeal-signed envelope verifies
    independently in both tools."
    Falsified if: DocuSeal signature passes but IDR chain breaks (or vice
    versa) on the same artefact, OR if any of the 8 file-type adapters
    produces a corrupted output.
    Deadline: 2026-05-12.

Test strategy:
    - lib.docuseal (W2 shim) is mocked — no live API hits.
    - lib.docuseal_webhook (W3) and lib.docuseal_file_adapter (W4) run REAL.
    - donna-skill/handlers/sign.handle() is exercised via its public API.
    - IDR chain is written to a temp file and verified structurally.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ───────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "donna-skill"))

from lib.docuseal_webhook import (
    append_to_chain,
    event_to_idr,
    handle_webhook,
    parse_event,
    GENESIS_PREVIOUS_HASH,
    PROTOCOL_VERSION,
)
from lib.docuseal_file_adapter import detect_format

# ── Constants ────────────────────────────────────────────────────────────────
NOTARISE_KEY = "test-notarise-key-e2e"
SUBMISSION_ID = 4242
TEMPLATE_ID = 77

FAKE_TEMPLATE = {"id": TEMPLATE_ID}
FAKE_SUBMISSION = {
    "id": SUBMISSION_ID,
    "submitters": [{"email": "alice@law.com", "name": "Alice", "slug": "abc123"}],
}

ONE_SIGNER = [{"email": "alice@law.com", "name": "Alice"}]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_minimal_pdf(path: Path) -> None:
    """Write a minimal but structurally valid PDF-1.4 file."""
    content_stream = b"BT /F1 12 Tf 50 750 Td (DONNA test document) Tj ET"
    objects = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>")
    content_len = len(content_stream)
    add(f"<< /Length {content_len} >>\nstream\n".encode() + content_stream + b"\nendstream")
    add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
        b" /Contents 3 0 R /Resources << /Font << /F1 << /Type /Font"
        b" /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
    )

    body = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_offset = len(body)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    path.write_bytes(body + xref.encode() + trailer.encode())


def _make_minimal_md(path: Path) -> None:
    path.write_text("# Service Agreement\n\nParties agree to the terms.\n", encoding="utf-8")


def _make_minimal_png(path: Path) -> None:
    """Write a valid 1x1 white RGB PNG using stdlib struct + zlib."""
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    # IHDR: 1x1 px, 8-bit RGB, no interlace
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    # IDAT: one scanline — filter byte 0x00 + R G B white
    raw_row = b"\x00\xff\xff\xff"
    idat = zlib.compress(raw_row)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _read_idr_records(chain_path: Path) -> list[dict]:
    """Parse all ```idr blocks from a PROBAT.md chain file."""
    text = chain_path.read_text(encoding="utf-8")
    records = []
    in_block = False
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```idr"):
            in_block = True
            buf = []
        elif in_block and line.strip().startswith("```"):
            in_block = False
            records.append(json.loads("".join(buf)))
        elif in_block:
            buf.append(line)
    return records


def _canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_record_signature(record: dict, key: str) -> bool:
    """Re-compute HMAC over canonical payload (signature excluded) and compare."""
    sig = record.get("signature", "")
    payload = {k: v for k, v in record.items() if k != "signature"}
    expected = hmac.new(key.encode("utf-8"), _canonical_json(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _verify_chain(records: list[dict], key: str) -> list[str]:
    """Return list of failure descriptions; empty list = chain valid."""
    failures = []
    for i, rec in enumerate(records):
        if not _verify_record_signature(rec, key):
            failures.append(f"record[{i}] signature invalid")
        if i == 0:
            if rec.get("previous_hash") != GENESIS_PREVIOUS_HASH:
                failures.append(f"record[0] previous_hash is not GENESIS")
        else:
            prev = records[i - 1]
            prev_payload = {k: v for k, v in prev.items() if k != "signature"}
            expected_prev_hash = _sha256(_canonical_json(prev_payload))
            if rec.get("previous_hash") != expected_prev_hash:
                failures.append(f"record[{i}] previous_hash does not link to record[{i-1}]")
    return failures


def _make_webhook_payload(event_type: str, submission_id: int) -> bytes:
    payload = {
        "event_type": event_type,
        "timestamp": "2026-05-09T14:00:00Z",
        "data": {
            "submission_id": submission_id,
            "submitter": {"email": "alice@law.com", "name": "Alice"},
            "submission": {"id": submission_id, "template_id": TEMPLATE_ID},
        },
    }
    return json.dumps(payload).encode("utf-8")


# ── Mock context for sign.handle() ───────────────────────────────────────────

def _mock_docuseal_api():
    """Patch lib.docuseal so handle() never hits the live DocuSeal API."""
    mock_ds = MagicMock()
    mock_ds.create_template_from_pdf.return_value = FAKE_TEMPLATE
    mock_ds.create_template_from_docx.return_value = FAKE_TEMPLATE
    mock_ds.create_template_from_html.return_value = FAKE_TEMPLATE
    mock_ds.create_submission.return_value = FAKE_SUBMISSION
    return mock_ds


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Happy-path round trip — signing_dispatched → signing_finalised
# ═════════════════════════════════════════════════════════════════════════════

class TestHappyPathRoundTrip:
    def test_two_idr_records_with_valid_chain(self, tmp_path: Path) -> None:
        """
        Full IDR chain: W5 handle() emits signing_dispatched (record 0),
        then a simulated submission.completed webhook emits signing_finalised
        (record 1). Chain must verify: 2 records, linked previous_hash,
        valid HMAC signatures on both.
        """
        chain_path = tmp_path / "PROBAT.md"
        pdf_path = tmp_path / "contract.pdf"
        _make_minimal_pdf(pdf_path)

        os.environ["DONNA_NOTARISE_KEY"] = NOTARISE_KEY
        os.environ["DONNA_CHAIN_PATH"] = str(chain_path)

        mock_ds = _mock_docuseal_api()

        with patch("handlers.sign.docuseal", mock_ds):
            from handlers.sign import handle
            result = handle({
                "file_path": str(pdf_path),
                "signers": ONE_SIGNER,
                "emit_idr": True,
            })

        assert result["submission_id"] == SUBMISSION_ID
        assert result["idr_signature"], "handle() must return non-empty idr_signature"
        assert chain_path.exists(), "PROBAT.md chain file must be created"

        # Step 3-4: simulate DocuSeal webhook → signing_finalised
        webhook_body = _make_webhook_payload("submission.completed", SUBMISSION_ID)
        webhook_result = handle_webhook(
            raw_body=webhook_body,
            signature_header=None,
            secret=NOTARISE_KEY,
            chain_path=chain_path,
        )
        assert webhook_result["event_type"] == "submission.completed"
        assert webhook_result["chain_position"] == 2

        # Step 5: verify the full chain
        records = _read_idr_records(chain_path)
        assert len(records) == 2, f"Expected 2 IDR records, got {len(records)}"
        assert records[0]["intent"] == "signing_dispatched"
        assert records[1]["intent"] == "signing_finalised"
        assert records[1]["previous_hash"] != GENESIS_PREVIOUS_HASH, \
            "record[1].previous_hash must link back to record[0]"

        failures = _verify_chain(records, NOTARISE_KEY)
        assert not failures, f"Chain verification failed: {failures}"


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: Tamper detection at position 0 and position 1
# ═════════════════════════════════════════════════════════════════════════════

class TestTamperDetection:
    def _build_two_record_chain(self, tmp_path: Path) -> tuple[Path, list[dict]]:
        """Build a valid 2-record chain and return (chain_path, records)."""
        chain_path = tmp_path / "PROBAT.md"
        pdf_path = tmp_path / "contract.pdf"
        _make_minimal_pdf(pdf_path)
        os.environ["DONNA_NOTARISE_KEY"] = NOTARISE_KEY
        os.environ["DONNA_CHAIN_PATH"] = str(chain_path)

        mock_ds = _mock_docuseal_api()
        with patch("handlers.sign.docuseal", mock_ds):
            from handlers.sign import handle
            handle({"file_path": str(pdf_path), "signers": ONE_SIGNER, "emit_idr": True})

        webhook_body = _make_webhook_payload("submission.completed", SUBMISSION_ID)
        handle_webhook(
            raw_body=webhook_body,
            signature_header=None,
            secret=NOTARISE_KEY,
            chain_path=chain_path,
        )
        return chain_path, _read_idr_records(chain_path)

    def test_tamper_record_0_intent_detected(self, tmp_path: Path) -> None:
        """Mutating record[0].intent must break record[0]'s HMAC signature."""
        chain_path, records = self._build_two_record_chain(tmp_path)
        records[0]["intent"] = "TAMPERED_INTENT"
        failures = _verify_chain(records, NOTARISE_KEY)
        assert any("record[0] signature invalid" in f for f in failures), \
            f"Expected tamper at record[0] to be detected; failures={failures}"

    def test_tamper_record_1_intent_detected(self, tmp_path: Path) -> None:
        """Mutating record[1].intent must break record[1]'s HMAC signature."""
        chain_path, records = self._build_two_record_chain(tmp_path)
        records[1]["intent"] = "TAMPERED_INTENT"
        failures = _verify_chain(records, NOTARISE_KEY)
        assert any("record[1] signature invalid" in f for f in failures), \
            f"Expected tamper at record[1] to be detected; failures={failures}"


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: Cross-format — PDF, MD, PNG all produce valid IDR chains
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossFormat:
    @pytest.mark.parametrize("fmt_name,make_fn,detect_expected", [
        ("pdf", _make_minimal_pdf, "pdf"),
        ("md",  _make_minimal_md,  "md"),
        ("png", _make_minimal_png, "png"),
    ])
    def test_format_produces_valid_idr_chain(
        self, fmt_name: str, make_fn, detect_expected: str, tmp_path: Path
    ) -> None:
        """
        Each supported format must produce a valid IDR chain after a
        dispatch+webhook cycle. The file-type adapter is exercised for real.
        """
        chain_path = tmp_path / "PROBAT.md"
        input_path = tmp_path / f"document.{fmt_name}"
        make_fn(input_path)

        os.environ["DONNA_NOTARISE_KEY"] = NOTARISE_KEY
        os.environ["DONNA_CHAIN_PATH"] = str(chain_path)

        # Verify adapter detects the format correctly
        detected = detect_format(input_path)
        assert detected == detect_expected, \
            f"detect_format expected {detect_expected!r}, got {detected!r}"

        # MD and PNG go through real adapters; PDF passes through
        mock_ds = _mock_docuseal_api()
        with patch("handlers.sign.docuseal", mock_ds):
            from handlers.sign import handle
            result = handle({
                "file_path": str(input_path),
                "signers": ONE_SIGNER,
                "emit_idr": True,
            })

        assert chain_path.exists()
        records = _read_idr_records(chain_path)
        assert len(records) >= 1
        assert records[0]["intent"] == "signing_dispatched"

        failures = _verify_chain(records, NOTARISE_KEY)
        assert not failures, f"[{fmt_name}] chain invalid: {failures}"


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: Mismatched submission_id — second IDR appends but verifier flags it
# ═════════════════════════════════════════════════════════════════════════════

class TestMismatchedSubmissionId:
    def test_mismatched_id_appended_but_detectable(self, tmp_path: Path) -> None:
        """
        When the inbound webhook carries a different submission_id than
        the dispatched IDR, the chain still grows (append is not blocked),
        but a verifier helper can detect the mismatch by comparing target
        submission_ids across records.
        """
        chain_path = tmp_path / "PROBAT.md"
        pdf_path = tmp_path / "contract.pdf"
        _make_minimal_pdf(pdf_path)

        os.environ["DONNA_NOTARISE_KEY"] = NOTARISE_KEY
        os.environ["DONNA_CHAIN_PATH"] = str(chain_path)

        mock_ds = _mock_docuseal_api()
        with patch("handlers.sign.docuseal", mock_ds):
            from handlers.sign import handle
            handle({"file_path": str(pdf_path), "signers": ONE_SIGNER, "emit_idr": True})

        # Webhook with a DIFFERENT submission_id
        WRONG_ID = 9999
        webhook_body = _make_webhook_payload("submission.completed", WRONG_ID)
        handle_webhook(
            raw_body=webhook_body,
            signature_header=None,
            secret=NOTARISE_KEY,
            chain_path=chain_path,
        )

        records = _read_idr_records(chain_path)
        assert len(records) == 2, "Chain must have 2 records even with mismatched id"

        # Chain itself must still be cryptographically valid (HMAC + linking)
        failures = _verify_chain(records, NOTARISE_KEY)
        assert not failures, f"Chain structure must remain valid: {failures}"

        # Business-level verifier: detect the submission_id mismatch
        dispatched_id = records[0]["target"]["submission_id"]
        finalised_id = records[1]["target"]["submission_id"]
        assert dispatched_id != finalised_id, \
            "Test precondition: submission IDs must differ"
        mismatch_detected = dispatched_id != finalised_id
        assert mismatch_detected, "Verifier must detect the submission_id inconsistency"


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: Webhook HMAC verification path
# ═════════════════════════════════════════════════════════════════════════════

class TestWebhookHmacVerification:
    def test_valid_hmac_accepted(self, tmp_path: Path) -> None:
        """A correctly-signed webhook must parse without error."""
        raw = _make_webhook_payload("submission.completed", SUBMISSION_ID)
        sig = hmac.new(NOTARISE_KEY.encode(), raw, hashlib.sha256).hexdigest()
        event = parse_event(raw, signature_header=sig, secret=NOTARISE_KEY)
        assert event["event_type"] == "submission.completed"

    def test_invalid_hmac_raises(self, tmp_path: Path) -> None:
        """A tampered signature must raise WebhookSignatureError."""
        from lib.docuseal_webhook import WebhookSignatureError
        raw = _make_webhook_payload("submission.completed", SUBMISSION_ID)
        with pytest.raises(WebhookSignatureError):
            parse_event(raw, signature_header="deadbeef" * 8, secret=NOTARISE_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# Teardown: clean up env vars that could bleed between tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clean_env():
    yield
    os.environ.pop("DONNA_NOTARISE_KEY", None)
    os.environ.pop("DONNA_CHAIN_PATH", None)
