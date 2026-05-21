"""Legal document-understanding primitives.

Extracts text, detects handwriting/signature markers, and summarises
clauses from common legal document formats (.txt, .md, .docx, .pdf).

All parsing is pure stdlib. Clause extraction uses an injectable
OpenAI-compatible chat client (same pattern as donna.extractor).

Usage::

    from donna.legal_doc import analyse
    result = analyse("agreement.docx", config, prompts)
    print(result.clauses)
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from donna.config import Config
from donna.prompts import PromptLibrary

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class DocAnalysisError(ValueError):
    """Raised when a document cannot be parsed."""


@dataclass
class DocAnalysis:
    text: str
    has_handwriting: bool
    has_signature: bool
    clauses: list[str]
    confidence: float
    page_count: int


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_SUPPORTED = {".txt", ".md", ".docx", ".pdf"}

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_DOC = "word/document.xml"


def _extract_txt(path: Path) -> tuple[str, int]:
    return path.read_text(encoding="utf-8", errors="replace"), 1


def _extract_docx(path: Path) -> tuple[str, int]:
    with zipfile.ZipFile(path) as zf:
        if _WORD_DOC not in zf.namelist():
            return "", 1
        with zf.open(_WORD_DOC) as fh:
            tree = ET.parse(fh)
    root = tree.getroot()
    parts = [
        node.text
        for node in root.iter(f"{{{_WORD_NS}}}t")
        if node.text
    ]
    return " ".join(parts), 1


def _extract_pdf(path: Path) -> tuple[str, int]:
    """Best-effort embedded-text extraction — no binary deps."""
    raw = path.read_bytes()
    # Count pages via /Type /Page markers
    page_count = max(1, raw.count(b"/Type /Page"))
    # Extract readable ASCII runs between stream markers
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", raw, re.DOTALL):
        block = match.group(1)
        text = block.decode("latin-1", errors="replace")
        readable = " ".join(re.findall(r"[\x20-\x7e]{4,}", text))
        if readable:
            chunks.append(readable)
    return " ".join(chunks), page_count


_EXTRACTORS = {
    ".txt": _extract_txt,
    ".md": _extract_txt,
    ".docx": _extract_docx,
    ".pdf": _extract_pdf,
}


def _extract(path: Path) -> tuple[str, int]:
    ext = path.suffix.lower()
    fn = _EXTRACTORS.get(ext)
    if fn is None:
        raise DocAnalysisError(
            f"Unsupported document type {ext!r}. "
            f"Supported: {sorted(_SUPPORTED)}"
        )
    return fn(path)


# ---------------------------------------------------------------------------
# Heuristic detectors
# ---------------------------------------------------------------------------

_HANDWRITING_RE = re.compile(
    r"\b(handwritten|hand.?written|handwriting|cursive|signed\s+by\s+hand)\b",
    re.IGNORECASE,
)

_SIGNATURE_RE = re.compile(
    r"(/s/|Signed\s*:|Signature\s*:|_{4,}|x{4,}|\[signature\])",
    re.IGNORECASE,
)


def _detect_handwriting(text: str) -> bool:
    return bool(_HANDWRITING_RE.search(text))


def _detect_signature(text: str) -> bool:
    return bool(_SIGNATURE_RE.search(text))


# ---------------------------------------------------------------------------
# Clause extraction (LLM-backed, injectable)
# ---------------------------------------------------------------------------

_CLAUSE_SYSTEM = (
    "You are a legal document analyst. "
    "Given document text, return a JSON array of strings — one brief "
    "plain-English summary per legal clause. "
    "Return [] if no clauses are identifiable. "
    "Return only valid JSON, no prose."
)


def _extract_clauses(text: str, config: Config, client: Any) -> list[str]:
    if not text.strip():
        return []
    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            messages=[
                {"role": "system", "content": _CLAUSE_SYSTEM},
                {"role": "user", "content": text[:8000]},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content or "[]"
        result = json.loads(raw.strip())
        return [str(c) for c in result] if isinstance(result, list) else []
    except Exception:  # noqa: BLE001 — never propagate LLM errors
        return []


def _build_client(config: Config) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise DocAnalysisError(
            "openai package not installed; run `pip install openai`"
        ) from exc
    return OpenAI(api_key=config.llm_api_key, base_url=config.llm_base_url)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _confidence(text: str, clauses: list[str]) -> float:
    if text and clauses:
        return 1.0
    if text:
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyse(
    path: str | Path,
    config: Config,
    prompts: PromptLibrary,
    *,
    client: Any | None = None,
) -> DocAnalysis:
    """Analyse a legal document and return structured metadata.

    Args:
        path: Path to the document (.txt, .md, .docx, .pdf).
        config: Donna configuration (LLM endpoint + API key).
        prompts: Prompt library (reserved for future prompt-driven extraction).
        client: Injectable LLM client; built from config if None.

    Returns:
        DocAnalysis with extracted text, heuristic flags, clauses, confidence.

    Raises:
        DocAnalysisError: If the file extension is unsupported or the file
            cannot be read.
    """
    p = Path(path)
    if not p.exists():
        raise DocAnalysisError(f"File not found: {p}")

    try:
        text, page_count = _extract(p)
    except DocAnalysisError:
        raise
    except Exception as exc:
        raise DocAnalysisError(f"Failed to read {p.name}: {exc}") from exc

    llm = client or _build_client(config)
    clauses = _extract_clauses(text, config, llm)

    return DocAnalysis(
        text=text,
        has_handwriting=_detect_handwriting(text),
        has_signature=_detect_signature(text),
        clauses=clauses,
        confidence=_confidence(text, clauses),
        page_count=page_count,
    )
