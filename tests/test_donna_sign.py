"""
Tests for donna-skill/handlers/sign.py

All DocuSeal API calls and file-adapter I/O are mocked — no live API hits.
"""
from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "donna-skill"))

from handlers.sign import handle, _build_submitters, _extract_signing_urls

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "contract.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    return p

@pytest.fixture()
def tmp_docx(tmp_path: Path) -> Path:
    p = tmp_path / "contract.docx"
    p.write_bytes(b"PK\x03\x04docx-stub")
    return p

@pytest.fixture()
def tmp_md(tmp_path: Path) -> Path:
    p = tmp_path / "brief.md"
    p.write_text("# Brief\nSign here.", encoding="utf-8")
    return p

@pytest.fixture()
def tmp_png(tmp_path: Path) -> Path:
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    return p

ONE_SIGNER  = [{"email": "alice@law.com", "name": "Alice"}]
TWO_SIGNERS = [
    {"email": "alice@law.com", "name": "Alice", "role": "Client"},
    {"email": "bob@law.com",   "name": "Bob",   "role": "Counsel"},
]
FAKE_TEMPLATE   = {"id": 42}
FAKE_SUBMISSION = {
    "id": 999,
    "submitters": [
        {"email": "alice@law.com", "name": "Alice", "slug": "aaa111"},
        {"email": "bob@law.com",   "name": "Bob",   "slug": "bbb222"},
    ],
}

def _pdf_adapt_ctx(p: Path):
    @contextmanager
    def _ctx(_p):
        yield (_p, "pdf")
    return _ctx(p)

def _docx_adapt_ctx(p: Path):
    @contextmanager
    def _ctx(_p):
        yield (_p, "docx")
    return _ctx(p)

def _html_adapt_ctx(p: Path):
    @contextmanager
    def _ctx(_p):
        html = _p.parent / (_p.stem + ".html")
        html.write_text("<html></html>", encoding="utf-8")
        yield (html, "html")
    return _ctx(p)

# ── Happy path: PDF + 1 signer ────────────────────────────────────────────────

def test_happy_path_pdf_one_signer(tmp_pdf: Path) -> None:
    single_sub = {"id": 999, "submitters": [{"email": "alice@law.com", "name": "Alice", "slug": "aaa111"}]}
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_pdf_adapt_ctx),
        patch("lib.docuseal.create_template_from_pdf", return_value=FAKE_TEMPLATE),
        patch("lib.docuseal.create_submission", return_value=single_sub) as mock_sub,
        patch("handlers.sign._emit_idr", return_value="sig-abc123"),
    ):
        result = handle({"file_path": str(tmp_pdf), "signers": ONE_SIGNER, "emit_idr": True})

    assert result["submission_id"] == 999
    assert result["template_id"] == 42
    assert result["idr_signature"] == "sig-abc123"
    assert len(result["signing_urls"]) == 1
    assert "aaa111" in result["signing_urls"][0]["signing_url"]
    _, kwargs = mock_sub.call_args
    assert kwargs.get("order") == "preserved"

# ── Multi-signer ordering preserved ──────────────────────────────────────────

def test_multi_signer_order_preserved(tmp_pdf: Path) -> None:
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_pdf_adapt_ctx),
        patch("lib.docuseal.create_template_from_pdf", return_value=FAKE_TEMPLATE),
        patch("lib.docuseal.create_submission", return_value=FAKE_SUBMISSION) as mock_sub,
        patch("handlers.sign._emit_idr", return_value=""),
    ):
        handle({"file_path": str(tmp_pdf), "signers": TWO_SIGNERS, "emit_idr": False})

    submitters_arg = mock_sub.call_args[0][1]
    assert submitters_arg[0]["email"] == "alice@law.com"
    assert submitters_arg[1]["email"] == "bob@law.com"
    assert submitters_arg[0]["role"] == "Client"
    assert submitters_arg[1]["role"] == "Counsel"

# ── Format adaptation: DOCX → DOCX endpoint ──────────────────────────────────

def test_docx_uses_docx_endpoint(tmp_docx: Path) -> None:
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_docx_adapt_ctx),
        patch("lib.docuseal.create_template_from_docx", return_value=FAKE_TEMPLATE) as mock_tpl,
        patch("lib.docuseal.create_submission", return_value={"id": 1, "submitters": [{"email": "a@b.com", "name": "A", "slug": "x"}]}),
        patch("handlers.sign._emit_idr", return_value=""),
    ):
        handle({"file_path": str(tmp_docx), "signers": ONE_SIGNER, "emit_idr": False})
    mock_tpl.assert_called_once()

# ── Format adaptation: MD → HTML endpoint ────────────────────────────────────

def test_md_uses_html_endpoint(tmp_md: Path) -> None:
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_html_adapt_ctx),
        patch("lib.docuseal.create_template_from_html", return_value=FAKE_TEMPLATE) as mock_tpl,
        patch("lib.docuseal.create_submission", return_value={"id": 2, "submitters": [{"email": "a@b.com", "name": "A", "slug": "y"}]}),
        patch("handlers.sign._emit_idr", return_value=""),
    ):
        handle({"file_path": str(tmp_md), "signers": ONE_SIGNER, "emit_idr": False})
    mock_tpl.assert_called_once()

# ── Format adaptation: PNG → PDF endpoint ────────────────────────────────────

def test_png_uses_pdf_endpoint(tmp_png: Path) -> None:
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_pdf_adapt_ctx),
        patch("lib.docuseal.create_template_from_pdf", return_value=FAKE_TEMPLATE) as mock_tpl,
        patch("lib.docuseal.create_submission", return_value={"id": 3, "submitters": [{"email": "a@b.com", "name": "A", "slug": "z"}]}),
        patch("handlers.sign._emit_idr", return_value=""),
    ):
        handle({"file_path": str(tmp_png), "signers": ONE_SIGNER, "emit_idr": False})
    mock_tpl.assert_called_once()

# ── emit_idr=True emits an IDR record ────────────────────────────────────────

def test_emit_idr_true_calls_chain(tmp_pdf: Path, tmp_path: Path) -> None:
    chain = tmp_path / "PROBAT.md"
    with (
        patch("handlers.sign.adapt_ctx", side_effect=_pdf_adapt_ctx),
        patch("lib.docuseal.create_template_from_pdf", return_value=FAKE_TEMPLATE),
        patch("lib.docuseal.create_submission", return_value={"id": 77, "submitters": [{"email": "a@b.com", "name": "A", "slug": "s"}]}),
        patch("handlers.sign.append_to_chain") as mock_chain,
        patch("handlers.sign.event_to_idr", return_value={"signature": "idr-sig-xyz", "intent": "signing_dispatched", "actor": {}}),
        patch.dict("os.environ", {"DONNA_CHAIN_PATH": str(chain), "DONNA_NOTARISE_KEY": "test-key"}),
    ):
        result = handle({"file_path": str(tmp_pdf), "signers": ONE_SIGNER, "emit_idr": True})
    mock_chain.assert_called_once()
    assert isinstance(result["idr_signature"], str)

# ── Plain-language error when file doesn't exist ──────────────────────────────

def test_missing_file_raises_plain_error() -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        handle({"file_path": "/tmp/does-not-exist-donna-sign-test.pdf", "signers": ONE_SIGNER})
    assert "File not found" in str(exc_info.value)

# ── _build_submitters ─────────────────────────────────────────────────────────

def test_build_submitters_no_redirect() -> None:
    result = _build_submitters(TWO_SIGNERS, None)
    assert result[0] == {"email": "alice@law.com", "name": "Alice", "role": "Client"}
    assert "completed_redirect_url" not in result[0]

def test_build_submitters_with_redirect() -> None:
    result = _build_submitters(ONE_SIGNER, "https://example.com/done")
    assert result[0]["completed_redirect_url"] == "https://example.com/done"

def test_build_submitters_no_role() -> None:
    result = _build_submitters([{"email": "a@b.com", "name": "A"}], None)
    assert "role" not in result[0]

# ── _extract_signing_urls ─────────────────────────────────────────────────────

def test_extract_signing_urls_slug_format() -> None:
    urls = _extract_signing_urls(FAKE_SUBMISSION)
    assert urls[0]["signing_url"] == "https://docuseal.com/s/aaa111"
    assert urls[1]["signing_url"] == "https://docuseal.com/s/bbb222"

def test_extract_signing_urls_fallback() -> None:
    sub = {"id": 1, "submitters": [{"email": "x@y.com", "name": "X", "signing_url": "https://custom.link"}]}
    urls = _extract_signing_urls(sub)
    assert urls[0]["signing_url"] == "https://custom.link"

# ── Subprocess entry point ────────────────────────────────────────────────────

def test_subprocess_entry_missing_file() -> None:
    import os as _os
    handler = REPO_ROOT / "donna-skill" / "handlers" / "sign.py"
    payload = json.dumps({"file_path": "/tmp/no-such-donna-sign.pdf", "signers": ONE_SIGNER})
    env = {
        **_os.environ,
        "PYTHONPATH": f"{REPO_ROOT}{_os.pathsep}{REPO_ROOT / 'donna-skill'}",
    }
    proc = subprocess.run(
        [sys.executable, str(handler)],
        input=payload, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
    )
    assert proc.returncode == 1
    err = json.loads(proc.stderr)
    assert "File not found" in err["error"]
