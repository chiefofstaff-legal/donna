"""
donna-skill/handlers/sign.py — donna_sign skill handler.

Wires lib.docuseal (W2), lib.docuseal_file_adapter (W4), and
lib.docuseal_webhook.event_to_idr / append_to_chain (W3) into a
single signing dispatch that:
  1. Detects + adapts input format to a DocuSeal-acceptable file.
  2. Creates a DocuSeal template.
  3. Creates a signing submission with ordered submitters.
  4. Optionally emits a DONNA IDR record (intent="signing_dispatched").
  5. Returns submission_id, per-signer signing URLs, idr_signature,
     and template_id.

Called as a subprocess by mcp-servers/donna/src/tools/sign.ts.
Reads JSON from stdin, writes JSON to stdout.  Errors exit non-zero
with a plain-language message on stderr (token never appears there).

Public API (for direct Python callers):
    handle(args: dict) -> dict
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from lib.docuseal_file_adapter import adapt_ctx
from lib.docuseal_webhook import event_to_idr, append_to_chain
from lib import docuseal


def handle(args: dict) -> dict:
    """Execute a signing dispatch.

    Args:
        args: {file_path, signers, emit_idr (default True), redirect_url}

    Returns:
        {submission_id, signing_urls, idr_signature, template_id}
    """
    file_path, signers_raw, emit_idr, redirect_url = _parse_args(args)
    template_id, submission = _dispatch_to_docuseal(file_path, signers_raw, redirect_url)
    submission_id: int = submission.get("id") or submission.get("submission_id")
    signing_urls = _extract_signing_urls(submission)
    idr_signature = _emit_idr(submission_id, template_id, signers_raw, file_path) if emit_idr else ""
    return {
        "submission_id": submission_id,
        "signing_urls": signing_urls,
        "idr_signature": idr_signature,
        "template_id": template_id,
    }


def _parse_args(args: dict) -> tuple:
    """Validate and extract typed args. Raises on bad input."""
    file_path = Path(args.get("file_path", ""))
    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: '{file_path}'. Check the path and try again."
        )
    signers_raw: list[dict] = args.get("signers", [])
    if not signers_raw:
        raise ValueError("At least one signer is required.")
    emit_idr: bool = args.get("emit_idr", True)
    redirect_url: str | None = args.get("redirect_url") or args.get("completed_redirect_url")
    return file_path, signers_raw, emit_idr, redirect_url


def _dispatch_to_docuseal(file_path: Path, signers_raw: list[dict],
                           redirect_url: str | None) -> tuple[int, dict]:
    """Adapt file, create template, create submission. Returns (template_id, submission)."""
    with adapt_ctx(file_path) as (adapted_path, endpoint):
        template = _create_template(adapted_path, endpoint, file_path.stem)
        template_id: int = template["id"]
        submitters = _build_submitters(signers_raw, redirect_url)
        submission = docuseal.create_submission(template_id, submitters, order="preserved")
    return template_id, submission


# ── Private helpers ────────────────────────────────────────────────────────────

def _create_template(adapted_path: Path, endpoint: str, name: str) -> dict:
    """Create a DocuSeal template from an adapted file."""
    dispatch = {
        "pdf":  docuseal.create_template_from_pdf,
        "docx": docuseal.create_template_from_docx,
        "html": lambda p, n: docuseal.create_template_from_html(
            p.read_text(encoding="utf-8"), n
        ),
    }
    creator = dispatch.get(endpoint)
    if creator is None:
        raise RuntimeError(f"No template creator for endpoint '{endpoint}'.")
    return creator(adapted_path, name)


def _build_submitters(signers: list[dict], redirect_url: str | None) -> list[dict]:
    """Convert skill signer dicts to DocuSeal submitter format."""
    result = []
    for signer in signers:
        entry: dict[str, Any] = {
            "email": signer["email"],
            "name": signer.get("name", signer["email"]),
        }
        if signer.get("role"):
            entry["role"] = signer["role"]
        if redirect_url:
            entry["completed_redirect_url"] = redirect_url
        result.append(entry)
    return result


def _extract_signing_urls(submission: dict) -> list[dict]:
    """Extract per-signer signing URLs from the submission response."""
    submitters = submission.get("submitters") or []
    return [
        {
            "email": s.get("email", ""),
            "name": s.get("name", ""),
            "signing_url": s.get("slug") and f"https://docuseal.com/s/{s['slug']}" or s.get("signing_url", ""),
        }
        for s in submitters
    ]


def _emit_idr(submission_id: int, template_id: int, signers: list[dict],
              file_path: Path) -> str:
    """Emit a DONNA IDR record for signing_dispatched intent.

    Returns the HMAC signature of the written IDR record, or empty string
    if the notarise key is not configured (non-fatal).
    """
    synthetic_event = {
        "event_type": "submission.created",
        "timestamp": _utc_now(),
        "data": {
            "submission_id": submission_id,
            "submitter": {
                "email": signers[0].get("email", "") if signers else "",
                "name":  signers[0].get("name", "")  if signers else "",
            },
            "submission": {
                "id": submission_id,
                "template_id": template_id,
            },
        },
    }

    idr = event_to_idr(synthetic_event)
    idr["actor"]["source_file"] = str(file_path)
    idr["actor"]["all_signers"] = [s.get("email", "") for s in signers]

    chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", "PROBAT.md"))
    try:
        append_to_chain(idr, chain_path)
        return idr.get("signature", "")
    except EnvironmentError:
        # DONNA_NOTARISE_KEY not set — IDR emission is optional
        return ""


def _utc_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Entry point (subprocess mode) ─────────────────────────────────────────────

if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
        result = handle(args)
        print(json.dumps(result))
    except Exception as exc:
        # Plain-language error — token must never appear here
        msg = str(exc)
        print(json.dumps({"error": msg}), file=sys.stderr)
        sys.exit(1)
