"""Tests for lib/docuseal.py — Goodhart-proof.

Mocks the urllib request layer (no live API calls). Each test would FAIL
if the corresponding implementation behaviour were broken.

Tests target the W2-shipped public API:
    post(action, *, payload=None, file_path=None, base_url=None)
    get(action, *, params=None, base_url=None)
    delete(action, *, base_url=None)
    create_template_from_pdf|docx|html(...)
    create_submission(template_id, submitters, **kwargs)
    get_submission|list_submissions|get_submission_documents|archive_submission
"""
from __future__ import annotations

import io
import json
import logging
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make repo root importable as `lib.*`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import docuseal


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _capture_log(monkeypatch, tmp_path):
    """Redirect docuseal log to a tmp file so tests can grep it for token leaks."""
    log_path = tmp_path / "docuseal.log"
    handler = logging.FileHandler(log_path)
    handler.setLevel(logging.DEBUG)
    docuseal._log.handlers = [handler]
    docuseal._log.setLevel(logging.DEBUG)
    yield log_path
    handler.close()


@pytest.fixture
def fake_token(monkeypatch):
    """Inject a fake DocuSeal API key without hitting the keychain."""
    monkeypatch.setattr(docuseal, "_api_key", lambda: "fake-token-XYZ")
    return "fake-token-XYZ"


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Return a configurable mock urlopen that captures requests."""
    captured: dict = {"requests": []}

    def _make(payload, status: int = 200):
        body_bytes = (
            json.dumps(payload).encode("utf-8")
            if not isinstance(payload, (bytes, bytearray))
            else payload
        )

        def _urlopen(req, timeout=None):
            captured["requests"].append({
                "method": req.get_method(),
                "url": req.full_url,
                "headers": dict(req.headers),
                "data": req.data,
            })
            mock = MagicMock()
            mock.read.return_value = body_bytes
            mock.status = status
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda *a: None
            return mock

        monkeypatch.setattr(docuseal.urllib.request, "urlopen", _urlopen)
        return captured

    return _make


# ─── Auth + transport ────────────────────────────────────────────────────────

def test_get_sets_x_auth_token_header(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 1})
    docuseal.get("/templates/1")
    assert captured["requests"][0]["headers"]["X-auth-token"] == "fake-token-XYZ"


def test_post_uses_json_content_type(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 42})
    docuseal.post("/templates/html", payload={"name": "t1", "html": "<p>x</p>"})
    req = captured["requests"][0]
    assert req["method"] == "POST"
    assert req["headers"]["Content-type"] == "application/json"
    assert json.loads(req["data"].decode()) == {"name": "t1", "html": "<p>x</p>"}


def test_post_with_file_uses_multipart(fake_token, fake_urlopen, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfake pdf bytes")
    captured = fake_urlopen({"id": 5})
    docuseal.post("/templates/pdf", payload={"name": "t1"}, file_path=pdf)
    req = captured["requests"][0]
    assert req["headers"]["Content-type"].startswith("multipart/form-data")
    assert b"%PDF-1.4" in req["data"]
    assert b'name="file"' in req["data"]
    assert b'name="name"' in req["data"]


def test_get_with_params_encodes_query_string(fake_token, fake_urlopen):
    captured = fake_urlopen({"data": []})
    docuseal.get("/submissions", params={"status": "completed", "limit": 50})
    url = captured["requests"][0]["url"]
    assert "status=completed" in url
    assert "limit=50" in url


def test_delete_sends_delete_method(fake_token, fake_urlopen):
    captured = fake_urlopen({})
    docuseal.delete("/submissions/123")
    assert captured["requests"][0]["method"] == "DELETE"


def test_base_url_env_override(monkeypatch, fake_token, fake_urlopen):
    monkeypatch.setenv("DOCUSEAL_BASE_URL", "https://api.docuseal.eu")
    captured = fake_urlopen({"id": 1})
    docuseal.get("/templates/1")
    assert captured["requests"][0]["url"].startswith("https://api.docuseal.eu/")


def test_base_url_arg_overrides_env(monkeypatch, fake_token, fake_urlopen):
    monkeypatch.setenv("DOCUSEAL_BASE_URL", "https://api.docuseal.eu")
    captured = fake_urlopen({"id": 1})
    docuseal.get("/templates/1", base_url="https://custom.example.com")
    assert captured["requests"][0]["url"].startswith("https://custom.example.com/")


def test_base_url_strips_trailing_slash(monkeypatch, fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 1})
    docuseal.get("/templates/1", base_url="https://x.example.com/")
    assert captured["requests"][0]["url"] == "https://x.example.com/templates/1"


# ─── Token never leaks to logs ──────────────────────────────────────────────

def test_token_never_appears_in_log(fake_token, fake_urlopen, _capture_log):
    fake_urlopen({"id": 1})
    docuseal.get("/templates/1")
    docuseal._log.handlers[0].flush()
    log_text = _capture_log.read_text()
    assert "fake-token-XYZ" not in log_text, (
        f"Token leaked to log: {log_text!r}"
    )


def test_token_never_appears_in_log_on_post(fake_token, fake_urlopen, _capture_log):
    fake_urlopen({"id": 1})
    docuseal.post("/test", payload={"name": "x"})
    docuseal._log.handlers[0].flush()
    log_text = _capture_log.read_text()
    assert "fake-token-XYZ" not in log_text


def test_token_never_appears_in_log_on_error(fake_token, monkeypatch, _capture_log):
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"error":"invalid token"}')
        )
    monkeypatch.setattr(docuseal.urllib.request, "urlopen", _urlopen)
    with pytest.raises(RuntimeError):
        docuseal.get("/templates/1")
    docuseal._log.handlers[0].flush()
    log_text = _capture_log.read_text()
    assert "fake-token-XYZ" not in log_text


# ─── Plain-language errors ───────────────────────────────────────────────────

def test_keychain_missing_yields_plain_message(monkeypatch):
    """Missing keychain entry → actionable error message."""
    def _run(*args, **kwargs):
        # Simulate keychain miss returning empty stdout
        m = MagicMock()
        m.stdout = ""
        return m
    monkeypatch.setattr(docuseal.subprocess, "run", _run)
    with pytest.raises(RuntimeError) as exc:
        docuseal._api_key()
    msg = str(exc.value)
    assert "DocuSeal API key not found" in msg
    assert "/activate-grip" in msg


def test_http_404_raises_plain_message(fake_token, monkeypatch):
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {},
            io.BytesIO(json.dumps({"error": "template not found"}).encode())
        )
    monkeypatch.setattr(docuseal.urllib.request, "urlopen", _urlopen)
    with pytest.raises(RuntimeError) as exc:
        docuseal.get("/templates/9999")
    assert "404" in str(exc.value)
    assert "template not found" in str(exc.value)


def test_http_500_raises_plain_message(fake_token, monkeypatch):
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Server Error", {},
            io.BytesIO(b'{"error":"db down"}')
        )
    monkeypatch.setattr(docuseal.urllib.request, "urlopen", _urlopen)
    with pytest.raises(RuntimeError) as exc:
        docuseal.post("/submissions", payload={"x": "y"})
    assert "500" in str(exc.value)


# ─── Typed wrappers — Templates ─────────────────────────────────────────────

def test_create_template_from_pdf(fake_token, fake_urlopen, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    captured = fake_urlopen({"id": 100, "name": "Contract"})
    res = docuseal.create_template_from_pdf(
        pdf, "Contract", fields=[{"name": "Full Name", "role": "Signer1"}]
    )
    assert res["id"] == 100
    req = captured["requests"][0]
    assert "/templates/pdf" in req["url"]
    assert b'name="fields"' in req["data"]
    # Field tags JSON-encoded into the multipart body
    assert b"Signer1" in req["data"]


def test_create_template_from_pdf_no_fields(fake_token, fake_urlopen, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    captured = fake_urlopen({"id": 100})
    docuseal.create_template_from_pdf(pdf, "Simple")
    req = captured["requests"][0]
    # No fields → 'fields' form field NOT present
    assert b'name="fields"' not in req["data"]
    assert b'name="name"' in req["data"]


def test_create_template_from_docx(fake_token, fake_urlopen, tmp_path):
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"PK\x03\x04fakedocx")
    captured = fake_urlopen({"id": 101})
    res = docuseal.create_template_from_docx(docx, "DocxTemplate")
    assert res["id"] == 101
    req = captured["requests"][0]
    # Correct DOCX MIME type sent in multipart
    assert b"openxmlformats-officedocument.wordprocessingml" in req["data"]


def test_create_template_from_html(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 102})
    res = docuseal.create_template_from_html("<h1>Test</h1>", "HtmlTemplate")
    assert res["id"] == 102
    body = json.loads(captured["requests"][0]["data"].decode())
    assert body["html"] == "<h1>Test</h1>"
    assert body["name"] == "HtmlTemplate"


# ─── Typed wrappers — Submissions ───────────────────────────────────────────

def test_create_submission_canonical_payload(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 200, "slug": "abc"})
    docuseal.create_submission(
        template_id=42,
        submitters=[{"email": "a@b.com", "name": "Alice"}],
        send_email=True,
        message={"subject": "Sign please", "body": "Link {{submitter.link}}"},
    )
    body = json.loads(captured["requests"][0]["data"].decode())
    assert body["template_id"] == 42
    assert body["submitters"][0]["email"] == "a@b.com"
    assert body["message"]["subject"] == "Sign please"


def test_create_submission_passes_through_kwargs(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 200})
    docuseal.create_submission(
        template_id=1,
        submitters=[{"email": "x@y.com"}],
        completed_redirect_url="https://example.com/done",
        bcc_completed="legal@example.com",
        order="random",
    )
    body = json.loads(captured["requests"][0]["data"].decode())
    assert body["completed_redirect_url"] == "https://example.com/done"
    assert body["bcc_completed"] == "legal@example.com"
    assert body["order"] == "random"


def test_get_submission(fake_token, fake_urlopen):
    captured = fake_urlopen({"id": 5, "status": "completed"})
    res = docuseal.get_submission(5)
    assert res["status"] == "completed"
    assert "/submissions/5" in captured["requests"][0]["url"]


def test_list_submissions_pagination(fake_token, fake_urlopen):
    captured = fake_urlopen({"data": [], "pagination": {"next": 100}})
    docuseal.list_submissions(template_id=1, status="completed", limit=50, after=42)
    url = captured["requests"][0]["url"]
    assert "after=42" in url
    assert "status=completed" in url
    assert "limit=50" in url


def test_list_submissions_omits_unset_filters(fake_token, fake_urlopen):
    """Optional filter args must not appear in URL when None."""
    captured = fake_urlopen({"data": []})
    docuseal.list_submissions(limit=10)
    url = captured["requests"][0]["url"]
    assert "template_id" not in url
    assert "status" not in url
    assert "after" not in url


def test_get_submission_documents_returns_list(fake_token, fake_urlopen):
    fake_urlopen([{"name": "x", "url": "https://..."}])
    docs = docuseal.get_submission_documents(7)
    assert isinstance(docs, list)
    assert docs[0]["name"] == "x"


def test_get_submission_documents_handles_dict_documents_wrapper(fake_token, fake_urlopen):
    """DocuSeal sometimes wraps the documents list in a `documents` key."""
    fake_urlopen({"documents": [{"name": "y", "url": "https://..."}]})
    docs = docuseal.get_submission_documents(8)
    assert docs[0]["name"] == "y"


def test_get_submission_documents_handles_dict_data_wrapper(fake_token, fake_urlopen):
    """Or in a `data` key."""
    fake_urlopen({"data": [{"name": "z", "url": "https://..."}]})
    docs = docuseal.get_submission_documents(9)
    assert docs[0]["name"] == "z"


def test_archive_submission(fake_token, fake_urlopen):
    captured = fake_urlopen({})
    docuseal.archive_submission(99)
    req = captured["requests"][0]
    assert req["method"] == "DELETE"
    assert "/submissions/99" in req["url"]


# ─── Internal helpers ──────────────────────────────────────────────────────

def test_response_shape_dict():
    assert docuseal._response_shape({"id": 1, "name": "x"}).startswith("{")
    assert "id" in docuseal._response_shape({"id": 1, "name": "x"})


def test_response_shape_list():
    assert docuseal._response_shape([1, 2, 3]) == "[3 items]"


def test_response_shape_scalar():
    assert docuseal._response_shape(42) == "int"
    assert docuseal._response_shape("hello") == "str"


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("DOCUSEAL_BASE_URL", raising=False)
    assert docuseal._base_url(None) == "https://api.docuseal.com"


def test_base_url_strips_trailing_slash_in_helper(monkeypatch):
    monkeypatch.delenv("DOCUSEAL_BASE_URL", raising=False)
    assert docuseal._base_url("https://x.example/") == "https://x.example"
