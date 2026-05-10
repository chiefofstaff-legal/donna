"""
DocuSeal file-type adapter for DONNA.

Converts any DONNA-supported input format to a DocuSeal-acceptable
PDF, DOCX, or HTML output, returning the adapted path and the correct
DocuSeal endpoint suffix.

File-type matrix (W4 reference — quoted from grounding doc):
  Input | Adapter               | Output   | Endpoint
  PDF   | passthrough           | PDF      | /templates/pdf or /submissions/pdf
  DOCX  | passthrough           | DOCX     | /templates/docx or /submissions/docx
  DOC   | libreoffice convert   | DOCX     | /templates/docx
  RTF   | libreoffice convert   | DOCX     | /templates/docx
  ODT   | libreoffice convert   | DOCX     | /templates/docx
  HTML  | passthrough           | HTML     | /templates/html
  MD    | stdlib markdown→HTML  | HTML     | /templates/html
  PNG   | PIL embed             | PDF      | /templates/pdf
  JPG   | PIL embed             | PDF      | /templates/pdf
  TXT   | reportlab wrap        | PDF      | /templates/pdf
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AdapterError(Exception):
    """Plain-language error raised when conversion cannot proceed."""


# ---------------------------------------------------------------------------
# Magic-byte signatures
# ---------------------------------------------------------------------------

_MAGIC: dict[bytes, str] = {
    b"%PDF-": "pdf",
    b"PK\x03\x04": "zip",          # DOCX / ODT — need content-type sniff
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "doc",
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"{\\rtf": "rtf",
}

_ZIP_CONTENT_TYPES = {
    "word/": "docx",
    "mimetype": "odt",          # ODT stores mimetype as first entry
}

_ENDPOINT: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "html": "html",
}

_PASSTHROUGH = {"pdf", "docx", "html"}

_EXTENSION_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".rtf": "rtf",
    ".odt": "odt",
    ".html": "html",
    ".htm": "html",
    ".md": "md",
    ".markdown": "md",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".txt": "txt",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_format(path: Path) -> str:
    """Return one of pdf|docx|doc|rtf|odt|html|md|png|jpg|txt.

    Uses magic bytes first; falls back to extension.  Raises AdapterError
    for unrecognised files.
    """
    raw = path.read_bytes()[:16]

    for magic, fmt in _MAGIC.items():
        if raw.startswith(magic):
            if fmt == "zip":
                return _sniff_zip_type(path)
            return fmt

    # HTML detection: look for BOM or opening tag in first 512 bytes
    text_head = raw + path.read_bytes()[16:512]
    text_lower = text_head.lstrip(b"\xef\xbb\xbf").lower()
    if text_lower.startswith(b"<!doctype") or text_lower.startswith(b"<html"):
        return "html"

    # Fall back to extension
    ext = path.suffix.lower()
    if ext in _EXTENSION_MAP:
        return _EXTENSION_MAP[ext]

    raise AdapterError(
        f"Cannot determine file type for '{path.name}'. "
        "Supported formats: pdf, docx, doc, rtf, odt, html, md, png, jpg, txt."
    )


def can_passthrough(fmt: str) -> bool:
    """Return True if the format is accepted natively by DocuSeal."""
    return fmt in _PASSTHROUGH


def adapt(input_path: Path) -> tuple[Path, str]:
    """Convert *input_path* to a DocuSeal-compatible file.

    Returns (output_path, docuseal_endpoint) where endpoint is one of
    pdf|docx|html.  The output lives in a temp directory; the caller is
    responsible for cleanup (or use the adapt_ctx context manager).
    """
    fmt = detect_format(input_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="donna-docuseal-"))

    if can_passthrough(fmt):
        output = tmp_dir / input_path.name
        shutil.copy2(input_path, output)
        return output, _ENDPOINT[fmt]

    converters = {
        "doc": (_convert_doc_to_docx, "docx"),
        "rtf": (_convert_rtf_to_docx, "docx"),
        "odt": (_convert_odt_to_docx, "docx"),
        "md":  (_convert_md_to_html,  "html"),
        "png": (_convert_png_to_pdf,  "pdf"),
        "jpg": (_convert_jpg_to_pdf,  "pdf"),
        "txt": (_convert_txt_to_pdf,  "pdf"),
    }

    if fmt not in converters:
        raise AdapterError(f"No converter registered for format '{fmt}'.")

    converter_fn, output_fmt = converters[fmt]
    output = converter_fn(input_path, tmp_dir)
    return output, _ENDPOINT[output_fmt]


@contextmanager
def adapt_ctx(input_path: Path) -> Generator[tuple[Path, str], None, None]:
    """Context-manager variant of adapt() — cleans up the temp dir on exit."""
    output, endpoint = adapt(input_path)
    tmp_dir = output.parent
    try:
        yield output, endpoint
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _sniff_zip_type(path: Path) -> str:
    """Distinguish DOCX from ODT by inspecting the ZIP central directory."""
    try:
        import zipfile
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                if name.startswith("word/"):
                    return "docx"
            # ODT stores its mimetype as an uncompressed first entry
            if "mimetype" in names:
                mt = zf.read("mimetype").decode("ascii", errors="replace")
                if "opendocument" in mt:
                    return "odt"
    except Exception:
        pass
    # Default to docx for unknown ZIP-based office formats
    return "docx"


def _run_libreoffice(input_path: Path, out_dir: Path, target_fmt: str) -> Path:
    """Run libreoffice headless to convert *input_path* to *target_fmt*."""
    lo = shutil.which("libreoffice") or shutil.which("soffice")
    if lo is None:
        raise AdapterError(
            f"Converting {input_path.suffix.upper()} files requires LibreOffice. "
            "Install with: `brew install libreoffice` (macOS) or "
            "`apt install libreoffice` (Linux). "
            "Alternatively, convert the file to DOCX manually before upload."
        )
    result = subprocess.run(
        [lo, "--headless", "--convert-to", target_fmt, "--outdir", str(out_dir), str(input_path)],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise AdapterError(f"LibreOffice conversion failed: {stderr[:400]}")
    return out_dir / (input_path.stem + "." + target_fmt)


def _convert_doc_to_docx(path: Path, out_dir: Path) -> Path:
    return _run_libreoffice(path, out_dir, "docx")


def _convert_rtf_to_docx(path: Path, out_dir: Path) -> Path:
    return _run_libreoffice(path, out_dir, "docx")


def _convert_odt_to_docx(path: Path, out_dir: Path) -> Path:
    return _run_libreoffice(path, out_dir, "docx")


def _convert_md_to_html(path: Path, out_dir: Path) -> Path:
    """Convert Markdown to HTML.  Uses `markdown` package when available,
    falls back to a minimal stdlib renderer that handles headings, paragraphs,
    bulleted lists, code blocks, and links."""
    text = path.read_text(encoding="utf-8")
    try:
        import markdown as md_pkg
        html_body = md_pkg.markdown(text, extensions=["fenced_code"])
    except ImportError:
        html_body = _minimal_md_to_html(text)

    html = (
        "<!DOCTYPE html>\n<html>\n<body>\n"
        + html_body
        + "\n</body>\n</html>\n"
    )
    out = out_dir / (path.stem + ".html")
    out.write_text(html, encoding="utf-8")
    return out


def _minimal_md_to_html(text: str) -> str:
    """Minimal Markdown→HTML: headings, paragraphs, lists, code blocks, links."""
    import re

    lines = text.splitlines()
    parts: list[str] = []
    in_code = False
    in_list = False
    para_lines: list[str] = []

    def flush_para() -> None:
        if para_lines:
            parts.append("<p>" + " ".join(para_lines) + "</p>")
            para_lines.clear()

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for line in lines:
        # Fenced code blocks
        if line.startswith("```"):
            flush_para()
            flush_list()
            if not in_code:
                parts.append("<pre><code>")
                in_code = True
            else:
                parts.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            parts.append(line)
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            parts.append(f"<h{level}>{m.group(2)}</h{level}>")
            continue

        # Bulleted lists
        m = re.match(r"^[-*]\s+(.*)", line)
        if m:
            flush_para()
            if not in_list:
                parts.append("<ul>")
                in_list = True
            item = _inline_md(m.group(1))
            parts.append(f"<li>{item}</li>")
            continue

        # Blank line = paragraph separator
        if not line.strip():
            flush_para()
            flush_list()
            continue

        flush_list()
        para_lines.append(_inline_md(line))

    flush_para()
    flush_list()
    return "\n".join(parts)


def _inline_md(text: str) -> str:
    """Process inline Markdown: links, bold, italic, inline code."""
    import re
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def _convert_png_to_pdf(path: Path, out_dir: Path) -> Path:
    return _image_to_pdf(path, out_dir)


def _convert_jpg_to_pdf(path: Path, out_dir: Path) -> Path:
    return _image_to_pdf(path, out_dir)


def _image_to_pdf(path: Path, out_dir: Path) -> Path:
    """Embed an image in a single-page PDF using Pillow."""
    try:
        from PIL import Image
    except ImportError:
        raise AdapterError(
            "Converting image files to PDF requires Pillow. "
            "Install with: `pip install Pillow`."
        )

    img = Image.open(path).convert("RGB")
    out = out_dir / (path.stem + ".pdf")
    img.save(str(out), "PDF", resolution=150)
    return out


def _convert_txt_to_pdf(path: Path, out_dir: Path) -> Path:
    """Wrap plain text in a PDF.  Uses reportlab when available; falls back
    to a minimal PDF stream writer for single-font text."""
    text = path.read_text(encoding="utf-8")
    out = out_dir / (path.stem + ".pdf")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate
        _txt_to_pdf_reportlab(text, out, A4, getSampleStyleSheet, Paragraph, SimpleDocTemplate)
    except ImportError:
        _txt_to_pdf_minimal(text, out)

    return out


def _txt_to_pdf_reportlab(text, out, A4, getSampleStyleSheet, Paragraph, SimpleDocTemplate):
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    styles = getSampleStyleSheet()
    paragraphs = [
        Paragraph(p.replace("\n", "<br/>"), styles["Normal"])
        for p in text.split("\n\n") if p.strip()
    ]
    doc.build(paragraphs)


def _txt_to_pdf_minimal(text: str, out: Path) -> None:
    """Bare-minimum PDF stream: single font, wraps lines at 80 chars."""
    lines: list[str] = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, width=80) or [""])

    # Build PDF content stream
    font_size = 12
    leading = font_size * 1.4
    page_width, page_height = 595.28, 841.89  # A4 points
    margin = 50.0
    usable_height = page_height - 2 * margin

    pages: list[str] = []
    y = page_height - margin
    page_lines: list[str] = []

    for line in lines:
        if y - leading < margin:
            pages.append(_build_pdf_page(page_lines, font_size, leading, margin, page_height))
            page_lines = []
            y = page_height - margin
        page_lines.append(line)
        y -= leading

    if page_lines:
        pages.append(_build_pdf_page(page_lines, font_size, leading, margin, page_height))

    _write_pdf(out, pages, page_width, page_height)


def _build_pdf_page(lines: list[str], font_size: float, leading: float,
                    margin: float, page_height: float) -> str:
    y = page_height - margin
    ops = [f"BT /F1 {font_size} Tf"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"{margin} {y:.2f} Td ({escaped}) Tj 0 0 Td")
        y -= leading
    ops.append("ET")
    return "\n".join(ops)


def _write_pdf(out: Path, page_streams: list[str], width: float, height: float) -> None:
    """Write a minimal valid multi-page PDF using only stdlib."""
    objects: list[bytes] = []

    def add(obj: str) -> int:
        objects.append(obj.encode("latin-1", errors="replace"))
        return len(objects)  # 1-based object number

    # Object 1: catalog (placeholder, updated later)
    catalog_idx = add("")
    # Object 2: pages array (placeholder)
    pages_idx = add("")

    page_obj_ids: list[int] = []
    content_obj_ids: list[int] = []

    for stream in page_streams:
        encoded = stream.encode("latin-1", errors="replace")
        content_id = add(
            f"<< /Length {len(encoded)} >>\nstream\n"
            + stream
            + "\nendstream"
        )
        content_obj_ids.append(content_id)

        page_id = add(
            f"<< /Type /Page /Parent {pages_idx} 0 R "
            f"/MediaBox [0 0 {width:.2f} {height:.2f}] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        )
        page_obj_ids.append(page_id)

    kids = " ".join(f"{i} 0 R" for i in page_obj_ids)
    objects[pages_idx - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_ids)} >>"
    ).encode("latin-1")

    objects[catalog_idx - 1] = (
        f"<< /Type /Catalog /Pages {pages_idx} 0 R >>"
    ).encode("latin-1")

    # Write PDF
    body = b"%PDF-1.4\n"
    offsets: list[int] = []

    for i, obj_data in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + obj_data + b"\nendobj\n"

    xref_offset = len(body)
    n = len(objects)
    xref = f"xref\n0 {n + 1}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"

    trailer = (
        f"trailer\n<< /Size {n + 1} /Root {catalog_idx} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )

    out.write_bytes(body + xref.encode() + trailer.encode())
