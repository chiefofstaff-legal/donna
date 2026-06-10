"""Local document ingest for DONNA — liteparse-backed, confidentiality-first.

Implements the parse step of Scenario 3 (docs/SCENARIOS.md, "drop a PDF … get
it parsed"). Wraps run-llama/liteparse (local Rust + PDFium via PyO3): a client
document is parsed **in this process and never sent anywhere**. That locality is
the load-bearing property of DONNA's confidentiality moat — there is deliberately
no code path here to a cloud parser.

This mirrors the GRIP syscall-shim pattern (GRIP lib/liteparse_ingest.py),
vendored into DONNA because DONNA ships independently and does not import the
GRIP substrate.

Provenance: every ingest computes a SHA-256 over the exact source bytes, so a
downstream IDR can notarise *which* document was read (DONNA's whole value is a
verifiable decision chain — the ingest is the first link).

Scope (per no-stubs): exposes the confirmed liteparse 2.0.7 surface —
full-document text + page count + source hash. Per-page spans and clause
bounding boxes (the redline-positioning path) are not yet wired and are
deliberately omitted rather than stubbed; they arrive with the first
clause-level voice-edit consumer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional, Union

from donna.models import IngestedDocument

# A document source: a filesystem path, or raw bytes for a fully in-memory parse.
Source = Union[str, Path, bytes]

# Factory contract: given the resolved config, return an object exposing
# ``.parse(bytes) -> result`` where result has ``.text: str`` + ``.num_pages: int``.
ParserFactory = Callable[..., object]


class LiteParseUnavailable(RuntimeError):
    """liteparse is not installed.

    A complete implementation of the dependency boundary, not a stub: the
    capability genuinely does not exist until the optional extra is installed,
    and the message says exactly how to make it exist.
    """


def _default_parser_factory(
    *,
    ocr_enabled: bool,
    password: Optional[str],
    tessdata_path: Optional[str],
) -> object:
    """Construct the real liteparse backend, lazily imported."""
    try:
        from liteparse import LiteParse
    except ImportError as exc:  # dependency boundary — complete, not a stub
        raise LiteParseUnavailable(
            "liteparse is not installed — run `pip install 'donna[ingest]'` "
            "(local Rust+PDFium parser; no cloud)."
        ) from exc
    return LiteParse(
        ocr_enabled=ocr_enabled,
        password=password,
        tessdata_path=tessdata_path,
    )


def _to_bytes(source: Source) -> tuple[bytes, str]:
    """Normalise any source to raw bytes (read once), plus the original kind.

    Reading a path to bytes and parsing the bytes keeps every parse in-memory and
    lets a single read feed both the provenance hash and the parser.
    """
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), "bytes"
    return Path(source).read_bytes(), "path"


def ingest_document(
    source: Source,
    *,
    ocr: bool = False,
    password: Optional[str] = None,
    tessdata_path: Optional[str] = None,
    _parser_factory: Optional[ParserFactory] = None,
) -> IngestedDocument:
    """Parse a document to text, entirely locally, with a provenance hash.

    Args:
        source: a path (str/Path) or raw ``bytes``. Either way the parse runs in
            memory — the document is never written elsewhere to be read.
        ocr: enable the bundled Tesseract OCR pass (for scanned docs). Default
            False = the digital fast path.
        password: password for an encrypted PDF, if any.
        tessdata_path: local Tesseract data dir — set this for air-gapped OCR.
        _parser_factory: test seam (DIP); inject a fake backend.

    Returns:
        IngestedDocument with full-document ``text``, ``num_pages`` and the
        ``sha256`` of the source bytes.

    Raises:
        LiteParseUnavailable: liteparse is not installed.
    """
    raw, source_kind = _to_bytes(source)
    digest = hashlib.sha256(raw).hexdigest()
    factory = _parser_factory or _default_parser_factory
    parser = factory(ocr_enabled=ocr, password=password, tessdata_path=tessdata_path)
    result = parser.parse(raw)
    return IngestedDocument(
        text=result.text,
        num_pages=result.num_pages,
        sha256=digest,
        ocr_used=ocr,
        source_kind=source_kind,
    )
