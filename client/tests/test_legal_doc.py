"""Tests for legal_doc.py — legal document-understanding primitives.

Goodhart-resistant (Rule 14): each test asserts concrete output values.
LLM client is injected via a mock to avoid network calls.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from donna.legal_doc import (
    DocAnalysis,
    DocAnalysisError,
    _detect_handwriting,
    _detect_signature,
    analyse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(clauses: list[str]) -> MagicMock:
    """Return an LLM client stub that yields a JSON clause list."""
    client = MagicMock()
    msg = SimpleNamespace(content=json.dumps(clauses))
    choice = SimpleNamespace(message=msg)
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])
    return client


def _docx(tmp_path: Path, text: str) -> Path:
    """Build a minimal .docx fixture with the given text in word/document.xml."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        f'<?xml version="1.0"?>'
        f'<root xmlns:w="{ns}">'
        f'<w:t>{text}</w:t>'
        f'</root>'
    )
    p = tmp_path / "test.docx"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return p


# ---------------------------------------------------------------------------
# Text extraction — .txt
# ---------------------------------------------------------------------------

def test_analyse_txt_extracts_text(tmp_path, config):
    doc = tmp_path / "agreement.txt"
    doc.write_text("Party A agrees to pay Party B.\nSignature: ________", encoding="utf-8")
    client = _mock_client(["Payment obligation between A and B"])
    result = analyse(doc, config, MagicMock(), client=client)
    assert "Party A" in result.text
    assert result.page_count == 1
    assert isinstance(result.clauses, list)


def test_analyse_md_treated_as_txt(tmp_path, config):
    doc = tmp_path / "brief.md"
    doc.write_text("# Terms\n\nIndemnity clause here.", encoding="utf-8")
    client = _mock_client(["Indemnity clause"])
    result = analyse(doc, config, MagicMock(), client=client)
    assert "Indemnity" in result.text


# ---------------------------------------------------------------------------
# Text extraction — .docx
# ---------------------------------------------------------------------------

def test_analyse_docx_extracts_text(tmp_path, config):
    p = _docx(tmp_path, "This Agreement is made between Buyer and Seller.")
    client = _mock_client(["Sale agreement between Buyer and Seller"])
    result = analyse(p, config, MagicMock(), client=client)
    assert "Buyer" in result.text
    assert result.page_count == 1


# ---------------------------------------------------------------------------
# Signature and handwriting heuristics
# ---------------------------------------------------------------------------

def test_signature_detected_slash_s(tmp_path, config):
    doc = tmp_path / "signed.txt"
    doc.write_text("Agreed. /s/ John Smith", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.has_signature is True


def test_signature_detected_signature_colon(tmp_path, config):
    doc = tmp_path / "sig.txt"
    doc.write_text("Signature: ___________________", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.has_signature is True


def test_no_signature_when_absent(tmp_path, config):
    doc = tmp_path / "nosig.txt"
    doc.write_text("Plain terms with no signature block.", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.has_signature is False


def test_handwriting_detected(tmp_path, config):
    doc = tmp_path / "hw.txt"
    doc.write_text("This form was completed handwritten by the attorney.", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.has_handwriting is True


def test_no_handwriting_when_absent(tmp_path, config):
    doc = tmp_path / "typed.txt"
    doc.write_text("This is a typed legal document.", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.has_handwriting is False


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def test_confidence_full_when_text_and_clauses(tmp_path, config):
    doc = tmp_path / "full.txt"
    doc.write_text("Indemnity clause applies.", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client(["Indemnity"]))
    assert result.confidence == 1.0


def test_confidence_half_when_text_no_clauses(tmp_path, config):
    doc = tmp_path / "half.txt"
    doc.write_text("Some document text.", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.confidence == 0.5


def test_confidence_zero_on_empty_file(tmp_path, config):
    doc = tmp_path / "empty.txt"
    doc.write_text("", encoding="utf-8")
    result = analyse(doc, config, MagicMock(), client=_mock_client([]))
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_unsupported_extension_raises(tmp_path, config):
    doc = tmp_path / "scan.jpg"
    doc.write_bytes(b"\xff\xd8")
    with pytest.raises(DocAnalysisError, match="Unsupported document type"):
        analyse(doc, config, MagicMock(), client=_mock_client([]))


def test_missing_file_raises(tmp_path, config):
    with pytest.raises(DocAnalysisError, match="File not found"):
        analyse(tmp_path / "ghost.txt", config, MagicMock(), client=_mock_client([]))


# ---------------------------------------------------------------------------
# Unit tests for heuristic detectors (mutation-kill)
# ---------------------------------------------------------------------------

def test_detect_signature_unit():
    assert _detect_signature("/s/ Alice") is True
    assert _detect_signature("Signed: Bob") is True
    assert _detect_signature("__________") is True
    assert _detect_signature("no signature here") is False


def test_detect_handwriting_unit():
    assert _detect_handwriting("handwritten note") is True
    assert _detect_handwriting("signed by hand at the bottom") is True
    assert _detect_handwriting("typed document") is False
