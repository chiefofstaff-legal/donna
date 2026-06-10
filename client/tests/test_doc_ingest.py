"""Tests for donna.doc_ingest — the local document-ingest rung.

Goodhart-resistant: deterministic tests use an injected fake backend (no real
liteparse needed) and assert concrete values — text mapping, the SHA-256
provenance hash, source_kind, and the structural moat (no remote-OCR param). A
real-parse test runs only when liteparse + PyMuPDF are present.
"""

from __future__ import annotations

import hashlib
import inspect

import pytest

from donna.doc_ingest import LiteParseUnavailable, ingest_document
from donna.models import IngestedDocument


class _FakeResult:
    def __init__(self, text: str, num_pages: int) -> None:
        self.text = text
        self.num_pages = num_pages


class _FakeParser:
    def __init__(self, **config) -> None:
        self.config = config
        self.parsed = []

    def parse(self, data):
        self.parsed.append(data)
        return _FakeResult(text="DEED OF LEASE\nClause 1.", num_pages=3)


def _fake_factory(**config):
    return _FakeParser(**config)


def test_ingest_maps_text_and_pages_via_fake_backend():
    doc = ingest_document(b"%PDF-fake-bytes", _parser_factory=_fake_factory)
    assert isinstance(doc, IngestedDocument)
    assert doc.text == "DEED OF LEASE\nClause 1."
    assert doc.num_pages == 3
    assert doc.source_kind == "bytes"
    assert doc.ocr_used is False


def test_ingest_computes_sha256_over_source_bytes():
    payload = b"the exact bytes of a client document"
    doc = ingest_document(payload, _parser_factory=_fake_factory)
    assert doc.sha256 == hashlib.sha256(payload).hexdigest()
    assert len(doc.sha256) == 64  # hex digest


def test_sha256_is_content_addressed_not_random():
    # Same bytes -> same hash (notarisable); different bytes -> different hash.
    a = ingest_document(b"document A", _parser_factory=_fake_factory)
    a2 = ingest_document(b"document A", _parser_factory=_fake_factory)
    b = ingest_document(b"document B", _parser_factory=_fake_factory)
    assert a.sha256 == a2.sha256
    assert a.sha256 != b.sha256


def test_path_source_is_read_to_bytes(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF path-source bytes")
    doc = ingest_document(p, _parser_factory=_fake_factory)
    assert doc.source_kind == "path"
    # Hash is over the file's bytes (provenance survives the path->bytes read).
    assert doc.sha256 == hashlib.sha256(b"%PDF path-source bytes").hexdigest()


def test_config_threaded_to_backend():
    seen = {}

    def factory(**config):
        seen.update(config)
        return _FakeParser(**config)

    ingest_document(b"x", ocr=True, password="pw", tessdata_path="/opt/tess",
                    _parser_factory=factory)
    assert seen == {"ocr_enabled": True, "password": "pw", "tessdata_path": "/opt/tess"}


def test_no_remote_ocr_param_structural_moat():
    # The shim deliberately cannot be told to route a client document to a
    # remote OCR endpoint — no ocr_server_url passthrough exists.
    params = set(inspect.signature(ingest_document).parameters)
    assert "ocr_server_url" not in params
    assert "server_url" not in params


def test_ingested_document_to_dict_iso_timestamp():
    doc = ingest_document(b"x", _parser_factory=_fake_factory)
    d = doc.to_dict()
    assert d["sha256"] == doc.sha256
    assert d["num_pages"] == 3
    assert isinstance(d["created_at"], str)  # ISO string, not a datetime


def test_missing_liteparse_raises_plain_language_error():
    def factory(**_config):
        try:
            raise ImportError("No module named 'liteparse'")
        except ImportError as exc:
            raise LiteParseUnavailable(
                "liteparse is not installed — run `pip install 'donna[ingest]'`."
            ) from exc

    with pytest.raises(LiteParseUnavailable) as ei:
        ingest_document(b"x", _parser_factory=factory)
    assert "donna[ingest]" in str(ei.value)


# --- Real parse: runs only when liteparse + PyMuPDF are installed ---

def _have(mod: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(mod) is not None


@pytest.mark.skipif(not (_have("liteparse") and _have("fitz")),
                    reason="liteparse + PyMuPDF required for the real-parse test")
def test_real_parse_extracts_text_and_hashes(tmp_path):
    import fitz

    doc_pdf = fitz.open()
    page = doc_pdf.new_page()
    page.insert_text((72, 72), "DEED OF LEASE\nClause 1: rent is payable monthly.",
                     fontsize=12)
    out = tmp_path / "lease.pdf"
    doc_pdf.save(str(out))
    doc_pdf.close()

    result = ingest_document(out)  # real liteparse, digital fast path
    assert "rent is payable monthly" in result.text
    assert result.num_pages == 1
    assert result.sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
