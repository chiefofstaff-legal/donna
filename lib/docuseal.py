"""
lib/docuseal.py — DocuSeal API syscall shim for DONNA.

Syscall doctrine: the call site never references the API token.
Keychain entry: grip-docuseal (X-Auth-Token header).
Base URL: DOCUSEAL_BASE_URL env var or https://api.docuseal.com

Public API:
  post(action, *, payload=None, file_path=None, base_url=None) -> dict
  get(action, *, params=None, base_url=None) -> dict
  delete(action, *, base_url=None) -> dict
  create_template_from_pdf(pdf_path, name, fields=None) -> dict
  create_template_from_docx(docx_path, name) -> dict
  create_template_from_html(html, name) -> dict
  create_submission(template_id, submitters, **kwargs) -> dict
  get_submission(submission_id) -> dict
  list_submissions(*, template_id=None, status=None, limit=10, after=None) -> dict
  get_submission_documents(submission_id) -> list
  archive_submission(submission_id) -> dict
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ── Logging ────────────────────────────────────────────────────────────────────

_LOG_PATH = Path.home() / ".claude" / "logs" / "docuseal.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_log = logging.getLogger("docuseal")
if not _log.handlers:
    _handler = RotatingFileHandler(
        _LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3
    )
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "https://api.docuseal.com"
_KEYCHAIN_ENTRY = "grip-docuseal"


# ── Auth ───────────────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Read API key from macOS keychain. Token never logged or exported."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_ENTRY, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key = result.stdout.strip()
        if not key:
            raise KeyError("empty")
        return key
    except (subprocess.TimeoutExpired, FileNotFoundError, KeyError):
        raise RuntimeError(
            f"DocuSeal API key not found in keychain entry {_KEYCHAIN_ENTRY} — "
            "set it via /activate-grip or pass `base_url=` for a self-hosted instance"
        )


def _base_url(override: str | None) -> str:
    return (override or os.environ.get("DOCUSEAL_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")


# ── HTTP primitives ────────────────────────────────────────────────────────────

def _log_request(method: str, action: str, args_repr: str, status: int, shape: str) -> None:
    _log.info("%s %s args=%s status=%d shape=%s", method, action, args_repr, status, shape)


def _response_shape(data: Any) -> str:
    if isinstance(data, dict):
        return "{" + ",".join(list(data.keys())[:6]) + "}"
    if isinstance(data, list):
        return f"[{len(data)} items]"
    return type(data).__name__


def _json_request(method: str, url: str, key: str, payload: dict | None = None,
                  params: dict | None = None) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "X-Auth-Token": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            _log_request(method, url, repr(payload or params or {}), resp.status, _response_shape(data))
            return data
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        _log_request(method, url, repr(payload or {}), exc.code, body_text[:120])
        raise RuntimeError(
            f"DocuSeal API error {exc.code} on {method} {url}: {body_text[:200]}"
        ) from exc


def _multipart_request(url: str, key: str, fields: dict, file_field: str,
                       file_path: Path, content_type: str) -> dict:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    file_data = file_path.read_bytes()
    filename = file_path.name
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        + file_data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "X-Auth-Token": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            _log_request("POST", url, f"file={filename}", resp.status, _response_shape(data))
            return data
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        _log_request("POST", url, f"file={filename}", exc.code, body_text[:120])
        raise RuntimeError(
            f"DocuSeal upload error {exc.code} on {url}: {body_text[:200]}"
        ) from exc


# ── Generic verbs ──────────────────────────────────────────────────────────────

def post(action: str, *, payload: dict | None = None,
         file_path: Path | None = None, base_url: str | None = None) -> dict:
    """Generic POST. Use file_path for binary uploads (multipart)."""
    key = _api_key()
    url = f"{_base_url(base_url)}/{action.lstrip('/')}"
    if file_path is not None:
        file_path = Path(file_path)
        ct = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return _multipart_request(url, key, payload or {}, "file", file_path, ct)
    return _json_request("POST", url, key, payload)


def get(action: str, *, params: dict | None = None, base_url: str | None = None) -> dict:
    """Generic GET."""
    key = _api_key()
    url = f"{_base_url(base_url)}/{action.lstrip('/')}"
    return _json_request("GET", url, key, params=params)


def delete(action: str, *, base_url: str | None = None) -> dict:
    """Generic DELETE."""
    key = _api_key()
    url = f"{_base_url(base_url)}/{action.lstrip('/')}"
    return _json_request("DELETE", url, key)


# ── Template helpers ───────────────────────────────────────────────────────────

def create_template_from_pdf(pdf_path: Path, name: str,
                              fields: list | None = None) -> dict:
    """Upload a PDF and define field tags. fields is a list of field dicts."""
    pdf_path = Path(pdf_path)
    key = _api_key()
    url = f"{_base_url(None)}/templates/pdf"
    form_fields: dict = {"name": name}
    if fields:
        form_fields["fields"] = json.dumps(fields)
    return _multipart_request(url, key, form_fields, "file", pdf_path, "application/pdf")


def create_template_from_docx(docx_path: Path, name: str) -> dict:
    """Upload a DOCX with {{signature}} / [[variable]] tags."""
    docx_path = Path(docx_path)
    key = _api_key()
    url = f"{_base_url(None)}/templates/docx"
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return _multipart_request(url, key, {"name": name}, "file", docx_path, ct)


def create_template_from_html(html: str, name: str) -> dict:
    """Upload HTML string as a template."""
    key = _api_key()
    url = f"{_base_url(None)}/templates/html"
    return _json_request("POST", url, key, {"html": html, "name": name})


# ── Submission helpers ─────────────────────────────────────────────────────────

def create_submission(template_id: int, submitters: list, **kwargs) -> dict:
    """Create a signing submission from a template."""
    key = _api_key()
    url = f"{_base_url(None)}/submissions"
    payload = {"template_id": template_id, "submitters": submitters, **kwargs}
    return _json_request("POST", url, key, payload)


def get_submission(submission_id: int) -> dict:
    """Retrieve full submission state."""
    key = _api_key()
    url = f"{_base_url(None)}/submissions/{submission_id}"
    return _json_request("GET", url, key)


def list_submissions(*, template_id: int | None = None, status: str | None = None,
                     limit: int = 10, after: int | None = None) -> dict:
    """List submissions with optional filters."""
    params: dict = {"limit": limit}
    if template_id is not None:
        params["template_id"] = template_id
    if status is not None:
        params["status"] = status
    if after is not None:
        params["after"] = after
    key = _api_key()
    url = f"{_base_url(None)}/submissions"
    return _json_request("GET", url, key, params=params)


def get_submission_documents(submission_id: int) -> list:
    """Return list of signed-document download URLs."""
    key = _api_key()
    url = f"{_base_url(None)}/submissions/{submission_id}/documents"
    data = _json_request("GET", url, key)
    if isinstance(data, list):
        return data
    return data.get("documents", data.get("data", []))


def archive_submission(submission_id: int) -> dict:
    """Archive (soft-delete) a submission."""
    key = _api_key()
    url = f"{_base_url(None)}/submissions/{submission_id}"
    return _json_request("DELETE", url, key)
